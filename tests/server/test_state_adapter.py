"""Tests for state_adapter — the CLI schema compatibility layer."""
from video_cartoonize.server.services.state_adapter import (
    state_to_project_view,
    _build_subshots_from_paths,
)
from tests.server.conftest import MINIMAL_STATE
import copy


PROJECT_ID = "test_project"
WORK_DIR   = "/tmp/test_project"


def adapt(state_override=None):
    state = copy.deepcopy(MINIMAL_STATE)
    if state_override:
        state.update(state_override)
    return state_to_project_view(state, PROJECT_ID, WORK_DIR)


# ── Top-level ProjectView ─────────────────────────────────────────────────────

def test_project_id_preserved():
    view = adapt()
    assert view.id == PROJECT_ID


def test_work_dir_preserved():
    view = adapt()
    assert view.work_dir == WORK_DIR


def test_clip_count_matches():
    view = adapt()
    assert len(view.clips) == 2


def test_merged_false_when_no_final_video():
    view = adapt({"final_video": ""})
    assert view.merged is False


def test_merged_true_when_final_video_set(tmp_path):
    # Create a real file so os.path.exists returns True
    final = tmp_path / "final" / "merged.mp4"
    final.parent.mkdir()
    final.write_bytes(b"fake")
    import copy
    state = copy.deepcopy(MINIMAL_STATE)
    state["final_video"] = str(final)
    view = state_to_project_view(state, PROJECT_ID, str(tmp_path))
    assert view.merged is True
    assert view.final_video_url is not None


# ── Config ─────────────────────────────────────────────────────────────────────

def test_api_key_not_in_config():
    state = copy.deepcopy(MINIMAL_STATE)
    state["config"]["api_key"] = "sk-ark-secret"  # simulating a leaked key
    view = state_to_project_view(state, PROJECT_ID, WORK_DIR)
    assert "api_key" not in view.config


def test_style_id_in_config():
    view = adapt()
    assert view.config["style_id"] == "anime"


# ── Clips ──────────────────────────────────────────────────────────────────────

def test_done_clip_has_task_id():
    view = adapt()
    done = next(c for c in view.clips if c.status == "done")
    assert done.task_id.startswith("cgt-")


def test_split_clip_has_no_task_id():
    view = adapt()
    split = next(c for c in view.clips if c.status == "split")
    assert split.task_id == ""


def test_clip_duration_preserved():
    view = adapt()
    done = next(c for c in view.clips if c.status == "done")
    assert done.duration_s == 7.5


# ── Subshots ──────────────────────────────────────────────────────────────────

def test_done_clip_subshot_has_cartoon_url():
    view = adapt()
    done = next(c for c in view.clips if c.status == "done")
    assert len(done.subshots) == 1
    sub = done.subshots[0]
    assert sub.cartoon_url is not None
    assert "/api/projects/" in sub.cartoon_url


def test_done_clip_subshot_cartoon_asset_url_passthrough():
    view = adapt()
    done = next(c for c in view.clips if c.status == "done")
    sub = done.subshots[0]
    # TOS URL should pass through unmodified (not proxied)
    assert sub.cartoon_asset_url == "https://ark-asset.example.com/clip_00_sub_00.jpg"


def test_split_clip_has_no_subshots():
    view = adapt()
    split = next(c for c in view.clips if c.status == "split")
    assert split.subshots == []


def test_local_path_converted_to_api_url():
    view = adapt()
    done = next(c for c in view.clips if c.status == "done")
    sub = done.subshots[0]
    assert sub.keyframe_url.startswith("/api/projects/")
    assert "keyframes" in sub.keyframe_url


def test_http_url_not_double_proxied():
    """cartoon_asset_url that's already https:// should NOT be wrapped."""
    view = adapt()
    done = next(c for c in view.clips if c.status == "done")
    sub = done.subshots[0]
    assert sub.cartoon_asset_url.startswith("https://")


# ── Legacy schema (v4: subshots list missing, only paths arrays) ──────────────

def test_build_subshots_from_paths_v4():
    clip_v4 = {
        "clip_id": 0,
        "subshot_frame_paths": ["keyframes/f0.jpg", "keyframes/f1.jpg"],
        "subshot_cartoon_paths": ["cartoons/c0.jpg", "cartoons/c1.jpg"],
        "subshot_cartoon_urls": ["https://cdn/c0.jpg", "https://cdn/c1.jpg"],
        "verify_reason": "looks good",
    }
    subshots = _build_subshots_from_paths(clip_v4)
    assert len(subshots) == 2
    assert subshots[0]["idx"] == 0
    assert subshots[1]["cartoon_asset_url"] == "https://cdn/c1.jpg"


# ── Version warning (non-breaking) ───────────────────────────────────────────

def test_unsupported_version_does_not_raise(caplog):
    import logging
    state = copy.deepcopy(MINIMAL_STATE)
    state["version"] = 99  # future version
    with caplog.at_level(logging.WARNING):
        view = state_to_project_view(state, PROJECT_ID, WORK_DIR)
    assert view is not None  # should not raise
    assert any("99" in r.message for r in caplog.records)
