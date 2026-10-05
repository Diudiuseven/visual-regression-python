"""Ignore-region parsing, validation and masking."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import IgnoreRegionError

_REQUIRED_KEYS = ("x", "y", "width", "height")


@dataclass(frozen=True)
class Region:
    """Axis-aligned rectangle; covers columns x..x+width-1, rows y..y+height-1."""

    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def _reject(index: int | None, reason: str) -> None:
    raise IgnoreRegionError(f"ignore_regions[{index}]: {reason}", index=index)


def parse_regions(raw: Any, width: int, height: int) -> list[Region]:
    """Validate raw regions against image bounds.

    Every region must be an object with integer x, y, width, height;
    width/height strictly positive; the rectangle fully inside the image.
    Failure names the offending region index rather than failing silently.
    """
    if raw is None:
        raw = []
    if not isinstance(raw, (list, tuple)):
        _reject(None, "ignore_regions must be a list of region objects")

    regions: list[Region] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            _reject(i, "region must be an object {x, y, width, height}")
        missing = [k for k in _REQUIRED_KEYS if k not in item]
        if missing:
            _reject(i, f"missing keys: {', '.join(missing)}")
        values: dict[str, int] = {}
        for key in _REQUIRED_KEYS:
            value = item[key]
            if isinstance(value, bool) or not isinstance(value, int):
                _reject(i, f"key '{key}' must be an integer, got {type(value).__name__}")
            values[key] = int(value)
        x, y = values["x"], values["y"]
        w, h = values["width"], values["height"]
        if x < 0 or y < 0:
            _reject(i, f"origin ({x}, {y}) must be non-negative")
        if w <= 0 or h <= 0:
            _reject(i, f"width/height must be positive, got {w}x{h}")
        if x + w > width or y + h > height:
            _reject(
                i,
                f"rectangle ({x},{y},{w}x{h}) exceeds image bounds {width}x{height}",
            )
        regions.append(Region(x=x, y=y, width=w, height=h))
    return regions


def build_ignore_mask(regions: list[Region], width: int, height: int) -> bytearray:
    """Return an H*W mask; 1 where the pixel is inside an ignore region.

    Overlapping regions are coalesced (mask value stays 1).
    """
    mask = bytearray(width * height)
    for region in regions:
        x0, y0 = region.x, region.y
        for row in range(y0, y0 + region.height):
            start = row * width + x0
            mask[start : start + region.width] = b"\x01" * region.width
    return mask
