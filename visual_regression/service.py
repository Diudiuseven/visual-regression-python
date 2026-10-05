"""Application service: baselines, comparisons, batches, artifact cache."""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .baseline import BaselineStore
from .comparator import ComparisonOutcome, Verdict, normalize_as_png, run_comparison
from .config import CompareConfig, ResourceLimits
from .errors import VisualRegressionError
from .imaging import decode_image
from .regions import parse_regions


class ItemStatus(str, Enum):
    SUCCESS = "success"     # non-comparison action succeeded (register/approve/...)
    NO_DIFF = "no_diff"     # comparison completed, no visual change
    DIFF = "diff"           # comparison completed, visual change detected
    FAILED = "failed"       # the item could not be processed


@dataclass(frozen=True)
class BatchItemResult:
    case_id: str
    action: str
    status: ItemStatus
    summary: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error: str | None = None
    artifact_id: str | None = None
    baseline_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "action": self.action,
            "status": self.status.value,
            "summary": self.summary,
            "error_code": self.error_code,
            "error": self.error,
            "artifact_id": self.artifact_id,
            "baseline_version": self.baseline_version,
        }


@dataclass(frozen=True)
class BatchSummary:
    total: int
    success: int
    no_diff: int
    diff: int
    failed: int
    items: list[BatchItemResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "success": self.success,
            "no_diff": self.no_diff,
            "diff": self.diff,
            "failed": self.failed,
            "items": [item.to_dict() for item in self.items],
        }


class VisualRegressionService:
    """Facade bundling the baseline store, limits and artifact cache."""

    def __init__(
        self,
        limits: ResourceLimits | None = None,
        default_config: CompareConfig | None = None,
        artifact_cache_size: int = 128,
    ) -> None:
        self.limits = limits or ResourceLimits()
        self.limits.validate()
        self.default_config = default_config or CompareConfig()
        self.default_config.validate()
        self.store = BaselineStore()
        self._artifacts: OrderedDict[str, bytes] = OrderedDict()
        self._artifact_lock = threading.Lock()
        self._artifact_cache_size = artifact_cache_size

    # ------------------------------------------------------------- artifacts
    def _store_artifact(self, png: bytes) -> str:
        artifact_id = uuid.uuid4().hex
        with self._artifact_lock:
            self._artifacts[artifact_id] = png
            self._artifacts.move_to_end(artifact_id)
            while len(self._artifacts) > self._artifact_cache_size:
                self._artifacts.popitem(last=False)
        return artifact_id

    def get_artifact(self, artifact_id: str) -> bytes | None:
        with self._artifact_lock:
            data = self._artifacts.get(artifact_id)
            if data is not None:
                self._artifacts.move_to_end(artifact_id)
            return bytes(data) if data is not None else None

    # ------------------------------------------------------------ comparison
    def compare_case(
        self,
        case_id: str,
        candidate: bytes,
        config: CompareConfig | None = None,
        ignore_regions: Any = (),
        version: int | None = None,
        *,
        consume_pixels: "list[int] | None" = None,
    ) -> BatchItemResult:
        """Run one comparison and translate the outcome to a status item."""
        cfg = config or self.default_config
        cfg.validate()
        # Decode the candidate first (resource/corrupt-format checks) and
        # validate ignore regions against it; a malformed request must be
        # rejected before any baseline side effect such as auto-register.
        candidate_img = decode_image(candidate, self.limits)
        parsed_regions = parse_regions(ignore_regions, candidate_img.width, candidate_img.height)
        if consume_pixels is not None:
            consume_pixels[0] += candidate_img.pixel_count

        baseline_bytes: bytes | None = None
        baseline_version: int | None = None
        auto = False

        if self.store.has_case(case_id):
            baseline = (
                self.store.get_version(case_id, version)
                if version is not None
                else self.store.latest(case_id)
            )
            baseline_bytes = baseline.image_png
            baseline_version = baseline.version
        else:
            if not cfg.auto_register:
                from .errors import BaselineNotFoundError

                raise BaselineNotFoundError(
                    f"no baseline for case {case_id!r} and auto_register is disabled"
                )
            auto = True

        outcome: ComparisonOutcome = run_comparison(
            case_id,
            baseline_bytes,
            candidate,
            cfg,
            self.limits,
            parsed_regions,
            candidate_decoded=candidate_img,
        )

        if outcome.verdict is Verdict.NO_BASELINE and auto:
            # First time we see this case: persist a complete version 1.
            png, size = normalize_as_png(candidate, self.limits, candidate_decoded=candidate_img)
            entry = self.store.register(
                case_id, png, note="auto-registered from first candidate"
            )
            baseline_version = entry.version

        return self._outcome_to_item(outcome, baseline_version)

    def _outcome_to_item(
        self, outcome: ComparisonOutcome, baseline_version: int | None
    ) -> BatchItemResult:
        if outcome.verdict is Verdict.NO_BASELINE:
            return BatchItemResult(
                case_id=outcome.case_id,
                action="compare",
                status=ItemStatus.SUCCESS,
                summary={
                    "verdict": Verdict.NO_BASELINE.value,
                    "message": "candidate recorded as baseline version 1",
                    "dimensions": outcome.dimensions,
                },
                baseline_version=baseline_version,
            )

        assert outcome.diff is not None
        diff = outcome.diff
        artifact_id = self._store_artifact(diff.diff_png)
        status = ItemStatus.DIFF if outcome.verdict is Verdict.CHANGED else ItemStatus.NO_DIFF
        return BatchItemResult(
            case_id=outcome.case_id,
            action="compare",
            status=status,
            summary={
                "verdict": outcome.verdict.value,
                **diff.to_dict(),
            },
            artifact_id=artifact_id,
            baseline_version=baseline_version,
        )

    # ------------------------------------------------------------- approvals
    def propose_case(
        self,
        case_id: str,
        candidate: bytes,
        *,
        note: str = "",
        proposed_by: str = "anonymous",
    ) -> BatchItemResult:
        # Validate/normalize the image before staging anything.
        png, size = normalize_as_png(candidate, self.limits)
        existed = self.store.has_case(case_id)
        self.store.propose_replace(
            case_id, png, note=note, proposed_by=proposed_by
        )
        return BatchItemResult(
            case_id=case_id,
            action="propose",
            status=ItemStatus.SUCCESS,
            summary={
                "message": "replacement staged, awaiting approval",
                "dimensions": list(size),
                "new_case": not existed,
            },
        )

    def approve_case(self, case_id: str, *, approved_by: str = "reviewer") -> BatchItemResult:
        entry = self.store.approve_replace(case_id, approved_by=approved_by)
        return BatchItemResult(
            case_id=case_id,
            action="approve",
            status=ItemStatus.SUCCESS,
            summary={
                "message": "baseline replaced",
                "version": entry.version,
                "approved_by": entry.approved_by,
                "created_at": entry.created_at,
            },
            baseline_version=entry.version,
        )

    def reject_case(self, case_id: str) -> BatchItemResult:
        self.store.reject_replace(case_id)
        return BatchItemResult(
            case_id=case_id,
            action="reject",
            status=ItemStatus.SUCCESS,
            summary={"message": "pending replacement rejected"},
        )

    def history(self, case_id: str) -> list[dict[str, Any]]:
        return [
            {
                "version": v.version,
                "created_at": v.created_at,
                "note": v.note,
                "approved_by": v.approved_by,
                "bytes": len(v.image_png),
            }
            for v in self.store.history(case_id)
        ]

    # ----------------------------------------------------------------- batch
    def run_batch(self, items: list[dict[str, Any]]) -> BatchSummary:
        """Process mixed compare/propose/approve/reject actions independently.

        One item failing never affects the others; failures are reported as
        ``failed`` items carrying a stable error code.
        """
        if not isinstance(items, list):
            from .errors import InvalidInputError

            raise InvalidInputError("batch items must be a list")

        consumed = [0]
        results: list[BatchItemResult] = []
        counts = {s: 0 for s in ItemStatus}

        for pos, item in enumerate(items):
            result = self._run_one(item, pos, consumed)
            results.append(result)
            counts[result.status] += 1

        return BatchSummary(
            total=len(results),
            success=counts[ItemStatus.SUCCESS],
            no_diff=counts[ItemStatus.NO_DIFF],
            diff=counts[ItemStatus.DIFF],
            failed=counts[ItemStatus.FAILED],
            items=results,
        )

    def _run_one(self, item: Any, pos: int, consumed: list[int]) -> BatchItemResult:
        if not isinstance(item, dict):
            return BatchItemResult(
                case_id=f"items[{pos}]",
                action="unknown",
                status=ItemStatus.FAILED,
                error_code="invalid_input",
                error="batch item must be an object",
            )
        action = item.get("action", "compare")
        case_id = str(item.get("case_id", f"items[{pos}]"))
        try:
            if action == "compare":
                candidate = _require_bytes(item, "candidate")
                cfg = _config_from_dict(item.get("config"))
                version = item.get("version")
                result = self.compare_case(
                    case_id,
                    candidate,
                    config=cfg,
                    ignore_regions=item.get("ignore_regions", ()),
                    version=int(version) if version is not None else None,
                    consume_pixels=consumed,
                )
                self._check_budget(consumed[0])
                return result
            if action == "propose":
                consumed[0] += self._probe(item["candidate"])
                self._check_budget(consumed[0])
                return self.propose_case(
                    case_id,
                    _require_bytes(item, "candidate"),
                    note=str(item.get("note", "")),
                    proposed_by=str(item.get("proposed_by", "anonymous")),
                )
            if action == "approve":
                return self.approve_case(
                    case_id, approved_by=str(item.get("approved_by", "reviewer"))
                )
            if action == "reject":
                return self.reject_case(case_id)
            from .errors import InvalidInputError

            raise InvalidInputError(f"unknown action {action!r}")
        except VisualRegressionError as exc:
            return BatchItemResult(
                case_id=case_id,
                action=str(action),
                status=ItemStatus.FAILED,
                error_code=exc.code,
                error=str(exc),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return BatchItemResult(
                case_id=case_id,
                action=str(action),
                status=ItemStatus.FAILED,
                error_code="invalid_input",
                error=str(exc),
            )

    def _probe(self, candidate: Any) -> int:
        from .imaging import decode_image

        return decode_image(_as_bytes(candidate), self.limits).pixel_count

    def _check_budget(self, consumed: int) -> None:
        if consumed > self.limits.pixel_budget:
            from .errors import ImageTooLargeError

            raise ImageTooLargeError(
                f"batch decoded pixel budget {self.limits.pixel_budget} exceeded "
                f"(processed {consumed} pixels)"
            )


def _as_bytes(value: Any) -> bytes:
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        import base64

        try:
            return base64.b64decode(value, validate=True)
        except Exception as exc:
            from .errors import InvalidInputError

            raise InvalidInputError("candidate is not valid base64 image data") from exc
    from .errors import InvalidInputError

    raise InvalidInputError("candidate must be raw image bytes or base64 string")


def _require_bytes(item: dict[str, Any], key: str) -> bytes:
    if key not in item:
        from .errors import InvalidInputError

        raise InvalidInputError(f"missing required field {key!r}")
    return _as_bytes(item[key])


def _config_from_dict(raw: Any) -> CompareConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        from .errors import InvalidInputError

        raise InvalidInputError("config must be an object")
    allowed = {
        "pixel_tolerance",
        "change_ratio",
        "min_cluster_size",
        "alpha_threshold",
        "auto_register",
    }
    bad = set(raw) - allowed
    if bad:
        from .errors import InvalidInputError

        raise InvalidInputError(f"unknown config keys: {', '.join(sorted(bad))}")
    cfg = CompareConfig(**raw)
    cfg.validate()
    return cfg
