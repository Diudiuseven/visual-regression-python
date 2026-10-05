"""单组截图对比：判定、差异统计与差异标注图生成。

判定语义：
- 逐像素计算 RGB 三通道最大差值；差值 > tolerance 的像素直接计为变化。
- 差值在 (0, tolerance] 的像素，仅当其 8 邻域内同样存在差异的像素数
  少于 noise_max_neighbors（即“零星”噪声）时才被容忍；成片色块、
  位移边缘等结构性差异邻域密集，不会被容忍吞掉。
- 落在忽略区域内的差异不计入判定。
- 变化像素数 > pixel_threshold，或变化比例 > changed_ratio_threshold，
  任一条件成立即判为 CHANGED；两者都在阈值内但有变化像素时为
  WITHIN_THRESHOLD；零变化像素为 UNCHANGED。
- 同一对输入在相同配置下重复对比，输出逐字节一致的差异图与相同结论
  （解码、逐像素循环、PNG 编码均为确定性实现）。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from enum import Enum

from PIL import Image, UnidentifiedImageError

from .config import CompareConfig, Region
from .errors import (
    DimensionMismatchError,
    IgnoreRegionError,
    ImageDecodeError,
    ResourceLimitError,
)


class Verdict(Enum):
    """单组对比的判定结论。"""

    UNCHANGED = "unchanged"  # 零变化像素
    CHANGED = "changed"  # 超出阈值，判定发生变化
    WITHIN_THRESHOLD = "within_threshold"  # 有变化像素但在阈值内容忍


@dataclass(frozen=True)
class CompareResult:
    """一次对比的稳定输出。"""

    verdict: Verdict
    changed: bool
    changed_pixels: int
    effective_pixels: int  # 忽略区域之外参与判定的像素数
    changed_ratio: float
    diff_image: bytes  # PNG 编码的差异标注图，可下载


def _decode(data: bytes, config: CompareConfig, label: str) -> Image.Image:
    """解码图片并施加资源上限，错误可区分。"""
    if len(data) > config.max_image_bytes:
        raise ResourceLimitError(
            f"{label}: {len(data)} bytes exceeds max_image_bytes={config.max_image_bytes}"
        )
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError as exc:
        raise ResourceLimitError(f"{label}: {exc}") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageDecodeError(f"{label}: cannot decode image: {exc}") from exc
    w, h = img.size
    if w > config.max_width or h > config.max_height:
        raise ResourceLimitError(
            f"{label}: {w}x{h} exceeds max {config.max_width}x{config.max_height}"
        )
    if w * h > config.max_pixels:
        raise ResourceLimitError(
            f"{label}: {w * h} pixels exceeds max_pixels={config.max_pixels}"
        )
    return img.convert("RGB")


def _validate_regions(
    regions: tuple[Region, ...], width: int, height: int
) -> None:
    """校验忽略区域，非法时抛出可定位到具体区域的 IgnoreRegionError。"""
    for i, r in enumerate(regions):
        if not all(isinstance(v, int) for v in (r.x, r.y, r.width, r.height)):
            raise IgnoreRegionError(i, "coordinates must be integers")
        if r.width <= 0 or r.height <= 0:
            raise IgnoreRegionError(
                i, f"width/height must be positive, got {r.width}x{r.height}"
            )
        if r.x < 0 or r.y < 0:
            raise IgnoreRegionError(i, f"negative origin ({r.x}, {r.y})")
        if r.x + r.width > width or r.y + r.height > height:
            raise IgnoreRegionError(
                i,
                f"region ({r.x}, {r.y}, {r.width}, {r.height}) exceeds "
                f"image bounds {width}x{height}",
            )


def compare_images(
    baseline: bytes, candidate: bytes, config: CompareConfig | None = None
) -> CompareResult:
    """对比基准图与候选图，返回判定结果与差异标注图（PNG 字节）。"""
    cfg = config or CompareConfig()
    base_img = _decode(baseline, cfg, "baseline")
    cand_img = _decode(candidate, cfg, "candidate")
    width, height = base_img.size
    if cand_img.size != (width, height):
        raise DimensionMismatchError(
            f"baseline is {width}x{height}, candidate is {cand_img.size[0]}x{cand_img.size[1]}"
        )
    _validate_regions(cfg.ignore_regions, width, height)

    total = width * height
    # 忽略掩码：1 表示该像素被忽略。
    ignored = bytearray(total)
    ignored_count = 0
    for r in cfg.ignore_regions:
        for y in range(r.y, r.y + r.height):
            row = y * width
            for x in range(r.x, r.x + r.width):
                if not ignored[row + x]:
                    ignored[row + x] = 1
                    ignored_count += 1
    effective = total - ignored_count

    base_px = base_img.tobytes()
    cand_px = cand_img.tobytes()
    tolerance = cfg.tolerance

    # 第一遍：逐像素最大通道差（忽略区域视为无差异）。
    diffs = bytearray(total)
    for i in range(total):
        if ignored[i]:
            continue
        o = i * 3
        d0 = base_px[o] - cand_px[o]
        if d0 < 0:
            d0 = -d0
        d1 = base_px[o + 1] - cand_px[o + 1]
        if d1 < 0:
            d1 = -d1
        d2 = base_px[o + 2] - cand_px[o + 2]
        if d2 < 0:
            d2 = -d2
        diffs[i] = max(d0, d1, d2)

    # 第二遍：判定。差值 > tolerance 直接计为变化；差值在 (0, tolerance]
    # 的像素仅当 8 邻域内差异像素数少于 noise_max_neighbors（零星噪声）
    # 时才被容忍，否则视为结构性差异计入。
    diff_px = bytearray(cand_px)
    changed_pixels = 0
    max_noise_neighbors = cfg.noise_max_neighbors
    for i in range(total):
        d = diffs[i]
        if d == 0:
            continue
        if d <= tolerance:
            x = i % width
            y = i // width
            neighbors = 0
            for dy in (-1, 0, 1):
                ny = y + dy
                if ny < 0 or ny >= height:
                    continue
                base_i = ny * width
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx = x + dx
                    if 0 <= nx < width and diffs[base_i + nx] > 0:
                        neighbors += 1
            if neighbors < max_noise_neighbors:
                continue
        changed_pixels += 1
        o = i * 3
        diff_px[o] = 255
        diff_px[o + 1] = 0
        diff_px[o + 2] = 0

    changed_ratio = changed_pixels / effective if effective > 0 else 0.0
    exceeds = (
        changed_pixels > cfg.pixel_threshold
        or changed_ratio > cfg.changed_ratio_threshold
    )
    if changed_pixels == 0:
        verdict = Verdict.UNCHANGED
    elif exceeds:
        verdict = Verdict.CHANGED
    else:
        verdict = Verdict.WITHIN_THRESHOLD

    diff_img = Image.frombytes("RGB", (width, height), bytes(diff_px))
    buf = io.BytesIO()
    diff_img.save(buf, format="PNG")  # 确定性编码：同输入必得同字节
    return CompareResult(
        verdict=verdict,
        changed=verdict is Verdict.CHANGED,
        changed_pixels=changed_pixels,
        effective_pixels=effective,
        changed_ratio=changed_ratio,
        diff_image=buf.getvalue(),
    )
