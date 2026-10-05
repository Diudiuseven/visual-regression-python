"""End-to-end HTTP behavior through the FastAPI app."""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from visual_regression.api import create_app
from visual_regression.service import VisualRegressionService
from visual_regression.config import ResourceLimits

from .conftest import make_png


@pytest.fixture
def client():
    svc = VisualRegressionService(limits=ResourceLimits(pixel_budget=100_000_000))
    return TestClient(create_app(svc))


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_compare_flow_and_diff_download(client):
    black = make_png((0, 0, 0), (12, 12))
    white = make_png((255, 255, 255), (12, 12))
    assert client.post("/api/v1/compare", json={"case_id": "c", "candidate": b64(black)}).json()["status"] == "success"
    assert client.post("/api/v1/compare", json={"case_id": "c", "candidate": b64(black)}).json()["status"] == "no_diff"
    diff = client.post("/api/v1/compare", json={"case_id": "c", "candidate": b64(white)}).json()
    assert diff["status"] == "diff"
    assert diff["summary"]["changed_pixels"] == 144
    resp = client.get(diff["diff_image_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_artifact_404(client):
    resp = client.get("/api/v1/artifacts/deadbeef")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "artifact_not_found"


def test_corrupt_image_returns_400(client):
    resp = client.post("/api/v1/compare", json={"case_id": "x", "candidate": b64(b"junk")})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "invalid_input"


def test_unsupported_format_returns_415(client):
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "GIF")
    resp = client.post("/api/v1/compare", json={"case_id": "x", "candidate": b64(buf.getvalue())})
    assert resp.status_code == 415
    assert resp.json()["detail"]["error_code"] == "unsupported_format"


def test_bad_region_returns_422_with_index(client):
    black = b64(make_png(size=(8, 8)))
    # seed a valid baseline first so the request reaches region validation
    client.post("/api/v1/compare", json={"case_id": "c", "candidate": black})
    resp = client.post("/api/v1/compare", json={
        "case_id": "c", "candidate": black,
        "ignore_regions": [{"x": 5, "y": 5, "width": 10, "height": 1}],
    })
    # out-of-bounds is rejected by the domain layer with a region index
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "invalid_ignore_region"
    assert detail["region_index"] == 0


def test_approval_workflow_over_http(client):
    black = b64(make_png((0, 0, 0), (8, 8)))
    white = b64(make_png((255, 255, 255), (8, 8)))
    client.post("/api/v1/compare", json={"case_id": "c", "candidate": black})
    assert client.post("/api/v1/baselines/propose", json={
        "case_id": "c", "candidate": white, "note": "update"}).status_code == 200
    ap = client.post("/api/v1/baselines/approve", json={"case_id": "c", "approved_by": "me"})
    assert ap.json()["baseline_version"] == 2
    hist = client.get("/api/v1/baselines/c/history").json()
    assert [v["version"] for v in hist["versions"]] == [1, 2]
    # approve without pending -> 404
    missing = client.post("/api/v1/baselines/approve", json={"case_id": "c"})
    assert missing.status_code == 404


def test_batch_endpoint_partial_failure(client):
    black = b64(make_png(size=(8, 8)))
    resp = client.post("/api/v1/batch", json=[
        {"case_id": "a", "candidate": black},
        {"case_id": "b", "candidate": b64(b"nope")},
    ])
    body = resp.json()
    assert body["total"] == 2
    assert body["success"] == 1 and body["failed"] == 1
