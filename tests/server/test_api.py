"""Integration tests for FastAPI endpoints.

Uses httpx AsyncClient against the real FastAPI app with:
  - SQLite in-memory DB
  - FakeRedis
  - Temp work_dir with a real state.json
"""
import os
import pytest

pytestmark = pytest.mark.asyncio


# ── Health ────────────────────────────────────────────────────────────────────

async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "pipeline_steps" in data
    assert "split" in data["pipeline_steps"]
    assert "merge" in data["pipeline_steps"]


# ── Projects ──────────────────────────────────────────────────────────────────

async def test_get_project_not_found(client):
    resp = await client.get("/api/projects/does_not_exist")
    assert resp.status_code == 404


async def test_get_project_invalid_id(client):
    resp = await client.get("/api/projects/../etc/passwd")
    assert resp.status_code in (404, 422)


async def test_get_project_returns_project_view(client, work_dir):
    project_id = os.path.basename(work_dir)
    resp = await client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == project_id
    assert "clips" in data
    assert len(data["clips"]) == 2
    assert "config" in data
    # api_key must never appear in config
    assert "api_key" not in data["config"]


async def test_get_project_clips_have_correct_status(client, work_dir):
    project_id = os.path.basename(work_dir)
    resp = await client.get(f"/api/projects/{project_id}")
    clips = {c["clip_id"]: c for c in resp.json()["clips"]}
    assert clips[0]["status"] == "done"
    assert clips[1]["status"] == "split"


async def test_get_project_done_clip_has_api_url(client, work_dir):
    project_id = os.path.basename(work_dir)
    resp = await client.get(f"/api/projects/{project_id}")
    done_clip = next(c for c in resp.json()["clips"] if c["status"] == "done")
    sub = done_clip["subshots"][0]
    assert sub["keyframe_url"].startswith("/api/projects/")
    assert sub["cartoon_url"].startswith("/api/projects/")


# ── Pipeline steps ────────────────────────────────────────────────────────────

async def test_trigger_unknown_step_returns_422(client, work_dir):
    project_id = os.path.basename(work_dir)
    resp = await client.post(
        f"/api/projects/{project_id}/pipeline/nonexistent",
        json={},
        headers={"X-Ark-Api-Key": "sk-test"},
    )
    assert resp.status_code == 422


async def test_trigger_merge_blocked_if_clips_not_done(client, work_dir):
    """merge requires ALL clips done — clip_1 is 'split', should 409."""
    project_id = os.path.basename(work_dir)
    resp = await client.post(
        f"/api/projects/{project_id}/pipeline/merge",
        json={},
        headers={"X-Ark-Api-Key": "sk-test"},
    )
    assert resp.status_code == 409


async def test_list_pipeline_steps(client, work_dir):
    project_id = os.path.basename(work_dir)
    resp = await client.get(f"/api/projects/{project_id}/pipeline")
    assert resp.status_code == 200
    steps = resp.json()
    assert "split" in steps
    assert "description" in steps["split"]


# ── Files ────────────────────────────────────────────────────────────────────

async def test_file_not_found(client, work_dir):
    project_id = os.path.basename(work_dir)
    resp = await client.get(f"/api/projects/{project_id}/files/keyframes/missing.jpg")
    assert resp.status_code == 404


async def test_file_path_traversal_blocked(client, work_dir):
    project_id = os.path.basename(work_dir)
    resp = await client.get(f"/api/projects/{project_id}/files/../../../etc/passwd")
    assert resp.status_code in (403, 404)


async def test_file_outside_whitelist_blocked(client, work_dir):
    project_id = os.path.basename(work_dir)
    resp = await client.get(f"/api/projects/{project_id}/files/state.json")
    assert resp.status_code == 403


async def test_file_served_from_whitelist(client, work_dir):
    # Create a real keyframe file
    kf_dir = os.path.join(work_dir, "keyframes")
    os.makedirs(kf_dir, exist_ok=True)
    (open(os.path.join(kf_dir, "clip_00_sub_00.jpg"), "wb")
     .write(b"\xff\xd8\xff" + b"\x00" * 100))  # minimal JPEG header

    project_id = os.path.basename(work_dir)
    resp = await client.get(
        f"/api/projects/{project_id}/files/keyframes/clip_00_sub_00.jpg"
    )
    assert resp.status_code == 200
    assert "image" in resp.headers.get("content-type", "")


# ── Credentials ───────────────────────────────────────────────────────────────

async def test_verify_empty_key_returns_invalid(client):
    resp = await client.post("/api/credentials/verify", json={"ark_api_key": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ark"]["valid"] is False


async def test_verify_key_returns_ark_result_only(client):
    import unittest.mock as mock

    mock_resp = mock.AsyncMock()
    mock_resp.status_code = 200

    with mock.patch("httpx.AsyncClient.get", return_value=mock_resp):
        resp = await client.post(
            "/api/credentials/verify",
            json={"ark_api_key": "sk-ark-fake-key-1234567890"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"ark": {"valid": True, "error": None}}


# ── Jobs ─────────────────────────────────────────────────────────────────────

async def test_get_job_not_found(client):
    resp = await client.get("/api/jobs/nonexistent-job-id")
    assert resp.status_code == 404


async def test_list_jobs_empty(client):
    resp = await client.get("/api/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Task history ─────────────────────────────────────────────────────────────

async def test_task_history_requires_api_key(client):
    resp = await client.get("/api/tasks/history")
    assert resp.status_code == 401


async def test_task_history_returns_empty_for_unknown_key(client):
    resp = await client.get(
        "/api/tasks/history",
        headers={"X-Ark-Api-Key": "sk-ark-unknown-key-xyz"},
    )
    assert resp.status_code == 200
    assert resp.json() == []
