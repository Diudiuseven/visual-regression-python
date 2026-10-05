"""批量对比：一次提交多组，单组失败不影响其余组。

状态语义：
- UNCHANGED：零变化像素。
- SUCCESS：有变化像素但在阈值内，对比通过。
- CHANGED：差异超出阈值。
- FAILED：对比过程出错（输入损坏 / 超资源上限 / 配置非法 / 基准缺失等），
  error 字段给出原因；单组 FAILED 不影响其余组。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .baseline import BaselineStore
from .compare import CompareResult, Verdict, compare_images
from .config import CompareConfig
from .errors import VisualRegressionError


class ItemStatus(Enum):
    """单组对比的四种状态。"""

    SUCCESS = "success"  # 对比通过（变化在阈值内）
    UNCHANGED = "unchanged"  # 完全一致，零变化像素
    CHANGED = "changed"  # 有差异，超出阈值
    FAILED = "failed"  # 对比失败（输入损坏 / 超限 / 配置非法等）


@dataclass(frozen=True)
class BatchItem:
    """一组待对比输入。baseline 为 None 时从基准仓库取当前版本。"""

    case_id: str
    candidate: bytes
    baseline: bytes | None = None


@dataclass(frozen=True)
class ItemResult:
    case_id: str
    status: ItemStatus
    compare: CompareResult | None
    error: str | None


@dataclass(frozen=True)
class BatchSummary:
    success: int = 0
    unchanged: int = 0
    changed: int = 0
    failed: int = 0


@dataclass(frozen=True)
class BatchResult:
    items: tuple[ItemResult, ...] = field(default_factory=tuple)
    summary: BatchSummary = BatchSummary()


_VERDICT_TO_STATUS = {
    Verdict.UNCHANGED: ItemStatus.UNCHANGED,
    Verdict.WITHIN_THRESHOLD: ItemStatus.SUCCESS,
    Verdict.CHANGED: ItemStatus.CHANGED,
}


def _run_one(
    item: BatchItem, config: CompareConfig, store: BaselineStore | None
) -> ItemResult:
    try:
        baseline = item.baseline
        if baseline is None:
            if store is None:
                raise VisualRegressionError(
                    f"case {item.case_id!r}: no baseline given and no store provided"
                )
            baseline = store.current(item.case_id).image
        result = compare_images(baseline, item.candidate, config)
        return ItemResult(
            case_id=item.case_id,
            status=_VERDICT_TO_STATUS[result.verdict],
            compare=result,
            error=None,
        )
    except Exception as exc:  # 单组失败不得影响其余组
        return ItemResult(
            case_id=item.case_id,
            status=ItemStatus.FAILED,
            compare=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def run_batch(
    items: list[BatchItem],
    config: CompareConfig | None = None,
    store: BaselineStore | None = None,
) -> BatchResult:
    """逐组对比并汇总；单组异常被捕获并记为 FAILED，不影响其余组。"""
    cfg = config or CompareConfig()
    results = tuple(_run_one(item, cfg, store) for item in items)
    counts = {status: 0 for status in ItemStatus}
    for r in results:
        counts[r.status] += 1
    summary = BatchSummary(
        success=counts[ItemStatus.SUCCESS],
        unchanged=counts[ItemStatus.UNCHANGED],
        changed=counts[ItemStatus.CHANGED],
        failed=counts[ItemStatus.FAILED],
    )
    return BatchResult(items=results, summary=summary)
