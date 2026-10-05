"""错误类型定义：所有可区分错误都从这里导出。"""

from __future__ import annotations


class VisualRegressionError(Exception):
    """所有视觉回归错误的基类。"""


class ImageDecodeError(VisualRegressionError):
    """输入图片损坏或格式不支持。"""


class ResourceLimitError(VisualRegressionError):
    """输入超出配置的资源上限（分辨率 / 像素量 / 字节数）。"""


class IgnoreRegionError(VisualRegressionError):
    """忽略区域坐标越界或格式非法。

    携带 region_index 与 reason，可定位到具体区域。
    """

    def __init__(self, region_index: int, reason: str) -> None:
        self.region_index = region_index
        self.reason = reason
        super().__init__(f"ignore region #{region_index} invalid: {reason}")


class DimensionMismatchError(VisualRegressionError):
    """基准图与候选图尺寸不一致。"""


class BaselineNotFoundError(VisualRegressionError):
    """用例没有可用基准版本。"""


class ProposalError(VisualRegressionError):
    """基准替换审批操作非法（提案不存在或状态不对）。"""
