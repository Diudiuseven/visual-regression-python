"""对比配置与资源上限。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Region:
    """矩形忽略区域，坐标为像素单位，左上角原点。"""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class CompareConfig:
    """一次对比的判定参数与资源上限。

    判定语义见 docs，默认值在这里集中定义。
    """

    # 逐通道差值容忍度：差值 <= tolerance 的“零星”像素视为未变化。
    tolerance: int = 0
    # 零星判定：差值不超过 tolerance 的像素，仅当其 8 邻域内同样存在
    # 差异的像素数少于该值时才被容忍；成片色块 / 位移边缘的邻域差异
    # 像素多，不会被容忍吞掉。
    noise_max_neighbors: int = 2
    # 允许的变化像素个数上限（绝对值），超过则判为“有差异”。
    pixel_threshold: int = 0
    # 允许的变化面积比例上限（0~1），超过则判为“有差异”。
    changed_ratio_threshold: float = 0.0
    # 忽略区域列表，区域内的差异不计入判定。
    ignore_regions: tuple[Region, ...] = field(default_factory=tuple)
    # 资源上限。
    max_width: int = 8192
    max_height: int = 8192
    max_pixels: int = 40_000_000
    max_image_bytes: int = 64 * 1024 * 1024
