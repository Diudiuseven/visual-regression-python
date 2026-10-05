"""Orchestration: decode inputs, validate regions, compare, render annotation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .config import CompareConfig, ResourceLimits
from .diffing import DiffResult, compute_diff
from .errors import DimensionMismatchError
from .imaging import DecodedImage, decode_image, encode_diff_png
from .regions import Region, parse_regions


class Verdict(str, Enum):
    EQUAL = "no_diff"
    CHANGED = "diff"
    NO_BASELINE = "no_baseline"


@dataclass(frozen=True)
class ComparisonOutcome:
    case_id: str
    verdict: Verdict
    baseline_version: int | None
    diff: DiffResult | None
    auto_registered: bool = False
    dimensions: tuple[int, int] | None = None


def run_comparison(
    case_id: str,
    baseline_png: bytes | None,
    candidate_bytes: bytes,
    config: CompareConfig,
    limits: ResourceLimits,
    ignore_regions: object = (),
    candidate_decoded: DecodedImage | None = None,
) -> ComparisonOutcome:
    """Decode candidate/baseline, validate regions, run the pixel diff.

    When *baseline_png* is None the candidate is normalized/encoded and
    returned via ``ComparisonOutcome`` (the service persists it as version 1
    when ``config.auto_register`` is set); no pixel comparison occurs.

    *candidate_decoded* lets a caller reuse an already-decoded candidate.
    """
    config.validate()
    limits.validate()

    candidate = candidate_decoded or decode_image(candidate_bytes, limits)

    if baseline_png is None:
        return ComparisonOutcome(
            case_id=case_id,
            verdict=Verdict.NO_BASELINE,
            baseline_version=None,
            diff=None,
            auto_registered=config.auto_register,
            dimensions=candidate.size,
        )

    baseline = decode_image(baseline_png, limits)
    if baseline.size != candidate.size:
        raise DimensionMismatchError(
            f"baseline dimensions {baseline.width}x{baseline.height} differ from "
            f"candidate {candidate.width}x{candidate.height}"
        )

    regions: list[Region]
    if ignore_regions and isinstance(ignore_regions[0], Region):
        regions = list(ignore_regions)  # type: ignore[arg-type]
    else:
        regions = parse_regions(ignore_regions, candidate.width, candidate.height)
    diff = compute_diff(baseline, candidate, config, regions)
    verdict = Verdict.CHANGED if diff.changed else Verdict.EQUAL
    return ComparisonOutcome(
        case_id=case_id,
        verdict=verdict,
        baseline_version=None,
        diff=diff,
    )


def normalize_as_png(
    candidate_bytes: bytes,
    limits: ResourceLimits,
    candidate_decoded: DecodedImage | None = None,
) -> tuple[bytes, tuple[int, int]]:
    """Decode then re-encode an input as canonical RGB PNG (for baselines)."""
    img = candidate_decoded or decode_image(candidate_bytes, limits)
    return encode_diff_png(img.rgb, img.width, img.height), img.size
