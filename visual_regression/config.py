"""Configuration objects for comparison semantics and resource limits."""
from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidInputError


@dataclass(frozen=True)
class ResourceLimits:
    """Hard resource caps applied to every decoded input image.

    Args:
        max_pixels: maximum width*height allowed after decode.
        max_width / max_height: maximum dimension allowed after decode.
        max_bytes: maximum encoded payload size accepted (bytes).
        pixel_budget: coarse upper bound of decoded pixels processed per batch.
    """

    max_pixels: int = 4096 * 2304
    max_width: int = 8192
    max_height: int = 8192
    max_bytes: int = 32 * 1024 * 1024
    pixel_budget: int = 64 * 1_000_000

    def validate(self) -> None:
        if (
            self.max_pixels <= 0
            or self.max_width <= 0
            or self.max_height <= 0
            or self.max_bytes <= 0
            or self.pixel_budget <= 0
        ):
            raise InvalidInputError("resource limits must be positive integers")


@dataclass(frozen=True)
class CompareConfig:
    """Tunable comparison semantics.

    Args:
        pixel_tolerance: per-channel tolerance (0-255). A pixel counts as
            "different" only when at least one RGB channel differs by MORE
            than this value (|a-b| > pixel_tolerance). Default 16.
        change_ratio: decision threshold (0.0-1.0). When the fraction of
            changed pixels over the non-ignored area is strictly greater
            than this value, the verdict is CHANGED; otherwise NO_DIFF.
            Default 0.01 (1%).
        min_cluster_size: changed 4-connected components smaller than this
            many pixels are regarded as isolated rendering noise (e.g.
            single anti-aliased pixels) and discarded before counting.
            Coordinate shifts and color patches span large components and
            are therefore never swallowed. Default 1 (keep every pixel).
        alpha_threshold: opacity (0-255) at/above which a pixel is treated
            opaque; below it the pixel is treated transparent and
            composited onto the matte color. Default 1.
        auto_register: when true, comparing a case without any baseline
            records the candidate as version 1 and reports "no_baseline".
            Default true.
        matte: RGB background used when flattening transparent input.
    """

    pixel_tolerance: int = 16
    change_ratio: float = 0.01
    min_cluster_size: int = 1
    alpha_threshold: int = 1
    auto_register: bool = True
    matte: tuple[int, int, int] = (0, 0, 0)

    def validate(self) -> None:
        if not isinstance(self.pixel_tolerance, int) or not 0 <= self.pixel_tolerance <= 255:
            raise InvalidInputError("pixel_tolerance must be an integer in [0, 255]")
        if not isinstance(self.change_ratio, (int, float)) or isinstance(self.change_ratio, bool):
            raise InvalidInputError("change_ratio must be a number in [0, 1]")
        if not 0.0 <= float(self.change_ratio) <= 1.0:
            raise InvalidInputError("change_ratio must be in [0, 1]")
        if not isinstance(self.min_cluster_size, int) or self.min_cluster_size < 1:
            raise InvalidInputError("min_cluster_size must be a positive integer")
        if not isinstance(self.alpha_threshold, int) or not 0 <= self.alpha_threshold <= 255:
            raise InvalidInputError("alpha_threshold must be an integer in [0, 255]")
        if (
            not isinstance(self.matte, tuple)
            or len(self.matte) != 3
            or not all(isinstance(c, int) and 0 <= c <= 255 for c in self.matte)
        ):
            raise InvalidInputError("matte must be an (r, g, b) tuple with values in [0, 255]")


DEFAULT_LIMITS = ResourceLimits()
