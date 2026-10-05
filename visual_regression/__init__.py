"""进程内截图回归对比：对比判定、差异标注、忽略区域、基准版本管理与批量执行。"""

from .baseline import BaselineStore, BaselineVersion, VersionInfo
from .batch import (
    BatchItem,
    BatchResult,
    BatchSummary,
    ItemResult,
    ItemStatus,
    run_batch,
)
from .compare import CompareResult, Verdict, compare_images
from .config import CompareConfig, Region
from .errors import (
    BaselineNotFoundError,
    DimensionMismatchError,
    IgnoreRegionError,
    ImageDecodeError,
    ProposalError,
    ResourceLimitError,
    VisualRegressionError,
)

__all__ = [
    "BaselineNotFoundError",
    "BaselineStore",
    "BaselineVersion",
    "BatchItem",
    "BatchResult",
    "BatchSummary",
    "CompareConfig",
    "CompareResult",
    "DimensionMismatchError",
    "IgnoreRegionError",
    "ImageDecodeError",
    "ItemResult",
    "ItemStatus",
    "ProposalError",
    "Region",
    "ResourceLimitError",
    "Verdict",
    "VersionInfo",
    "VisualRegressionError",
    "compare_images",
    "run_batch",
]
