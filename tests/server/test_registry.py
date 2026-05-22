"""Tests for the Step Registry — the primary CLI extensibility point."""
import pytest
from video_cartoonize.server.pipeline.registry import STEP_REGISTRY, get_step


EXPECTED_STEPS = [
    "split", "keyframes", "cartoon", "vlm",
    "upload", "submit", "poll", "run", "mux", "merge",
]


def test_all_expected_steps_registered():
    for step in EXPECTED_STEPS:
        assert step in STEP_REGISTRY, f"Step {step!r} missing from registry"


def test_get_step_returns_step_def():
    sd = get_step("split")
    assert sd.timeout > 0
    assert sd.description


def test_get_step_raises_for_unknown():
    with pytest.raises(KeyError, match="Unknown pipeline step"):
        get_step("nonexistent_step_xyz")


# ── cli_args construction ─────────────────────────────────────────────────────

def test_split_cli_args_empty_request():
    sd = get_step("split")
    args = sd.cli_args({})
    assert isinstance(args, list)


def test_split_cli_args_with_threshold():
    sd = get_step("split")
    args = sd.cli_args({"scene_threshold": 30.0})
    assert "--scene-threshold" in args
    assert "30.0" in args


def test_cartoon_cli_args_with_clip_id():
    sd = get_step("cartoon")
    args = sd.cli_args({"clip_id": 3})
    assert "--clip-id" in args
    assert "3" in args


def test_cartoon_cli_args_without_clip_id():
    sd = get_step("cartoon")
    args = sd.cli_args({})
    assert "--clip-id" not in args


def test_submit_dry_run():
    sd = get_step("submit")
    args = sd.cli_args({"dry_run": True})
    assert "--dry-run" in args


def test_submit_no_dry_run():
    sd = get_step("submit")
    args = sd.cli_args({"dry_run": False})
    assert "--dry-run" not in args


def test_merge_has_no_extra_args():
    sd = get_step("merge")
    args = sd.cli_args({"clip_id": 5})  # merge ignores clip_id
    assert args == []


def test_all_steps_have_positive_timeout():
    for name, sd in STEP_REGISTRY.items():
        assert sd.timeout > 0, f"Step {name!r} has non-positive timeout"


def test_all_steps_have_description():
    for name, sd in STEP_REGISTRY.items():
        assert sd.description, f"Step {name!r} has empty description"
