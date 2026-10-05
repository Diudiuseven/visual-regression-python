"""FastAPI HTTP layer for the visual regression service.

Images travel as base64-encoded PNG/JPEG payloads. Annotated diff images
are returned via a short-lived in-process artifact download endpoint
(``/api/v1/artifacts/{id}``), so comparison responses stay JSON.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .errors import VisualRegressionError
from .service import VisualRegressionService

router = APIRouter(prefix="/api/v1", tags=["visual-regression"])


class RegionModel(BaseModel):
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)


class ConfigModel(BaseModel):
    pixel_tolerance: int | None = Field(default=None, ge=0, le=255)
    change_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    min_cluster_size: int | None = Field(default=None, ge=1)
    auto_register: bool | None = None


class CompareRequest(BaseModel):
    case_id: str = Field(..., min_length=1)
    candidate: str = Field(..., description="base64-encoded PNG/JPEG")
    version: int | None = Field(default=None, ge=1)
    ignore_regions: list[RegionModel] = Field(default_factory=list)
    config: ConfigModel | None = None


class ProposeRequest(BaseModel):
    case_id: str = Field(..., min_length=1)
    candidate: str
    note: str = ""
    proposed_by: str = "anonymous"


class ApproveRequest(BaseModel):
    case_id: str = Field(..., min_length=1)
    approved_by: str = "reviewer"


class RejectRequest(BaseModel):
    case_id: str = Field(..., min_length=1)


def _error_response(exc: VisualRegressionError) -> JSONResponse:
    status_map = {
        "invalid_input": 400,
        "unsupported_format": 415,
        "image_too_large": 413,
        "dimension_mismatch": 422,
        "invalid_ignore_region": 422,
        "baseline_not_found": 404,
        "pending_change_not_found": 404,
    }
    status = status_map.get(exc.code, 400)
    detail: dict[str, Any] = {"error_code": exc.code, "error": str(exc)}
    idx = getattr(exc, "index", None)
    if idx is not None:
        detail["region_index"] = idx
    return JSONResponse(status_code=status, content={"detail": detail})


def _config_kwargs(config: ConfigModel | None) -> dict[str, Any]:
    if config is None:
        return {}
    data = config.model_dump(exclude_none=True)
    return data


def create_app(service: VisualRegressionService | None = None) -> FastAPI:
    app = FastAPI(title="Visual Regression", version="0.1.0")
    svc = service or VisualRegressionService()
    app.state.service = svc

    @app.exception_handler(VisualRegressionError)
    async def _handle(_request, exc):  # noqa: ANN001
        return _error_response(exc)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/compare")
    def compare(req: CompareRequest) -> dict[str, Any]:
        import base64

        from .config import CompareConfig

        raw_cfg = _config_kwargs(req.config)
        cfg = CompareConfig(**raw_cfg) if raw_cfg else None
        result = svc.compare_case(
            req.case_id,
            base64.b64decode(req.candidate),
            config=cfg,
            ignore_regions=[r.model_dump() for r in req.ignore_regions],
            version=req.version,
        )
        body = result.to_dict()
        if result.artifact_id:
            body["diff_image_url"] = f"/api/v1/artifacts/{result.artifact_id}"
        return body

    @router.post("/baselines/propose")
    def propose(req: ProposeRequest) -> dict[str, Any]:
        import base64

        return svc.propose_case(
            req.case_id,
            base64.b64decode(req.candidate),
            note=req.note,
            proposed_by=req.proposed_by,
        ).to_dict()

    @router.post("/baselines/approve")
    def approve(req: ApproveRequest) -> dict[str, Any]:
        return svc.approve_case(req.case_id, approved_by=req.approved_by).to_dict()

    @router.post("/baselines/reject")
    def reject(req: RejectRequest) -> dict[str, Any]:
        return svc.reject_case(req.case_id).to_dict()

    @router.get("/baselines/{case_id}/history")
    def history(case_id: str) -> dict[str, Any]:
        versions = svc.history(case_id)
        return {"case_id": case_id, "versions": versions}

    @router.post("/batch")
    def batch(items: list[dict[str, Any]]) -> dict[str, Any]:
        return svc.run_batch(items).to_dict()

    @router.get("/artifacts/{artifact_id}")
    def artifact(artifact_id: str) -> Response:
        data = svc.get_artifact(artifact_id)
        if data is None:
            return JSONResponse(
                status_code=404,
                content={
                    "detail": {
                        "error_code": "artifact_not_found",
                        "error": f"artifact {artifact_id!r} not found or expired",
                    }
                },
            )
        return Response(content=data, media_type="image/png")

    app.include_router(router)
    return app
