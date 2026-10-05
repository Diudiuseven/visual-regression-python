"""批量对比：四种状态、汇总计数、单组失败隔离。"""

from __future__ import annotations

from visual_regression import (
    BaselineStore,
    BatchItem,
    CompareConfig,
    ItemStatus,
    Region,
    run_batch,
)

from .helpers import fill_rect, make_png, paint

BASE = (10, 20, 30)


class TestBatchStatuses:
    def test_four_statuses_and_summary(self):
        same = make_png(BASE)
        noisy = paint(same, {(1, 1): (BASE[0] + 5, BASE[1], BASE[2])})
        different = make_png((200, 200, 200))
        cfg = CompareConfig(tolerance=1, pixel_threshold=2, changed_ratio_threshold=0.5)
        items = [
            BatchItem("ok-same", same, same),          # UNCHANGED
            BatchItem("ok-noise", noisy, same),        # SUCCESS（容忍内）
            BatchItem("diff", different, same),        # CHANGED
            BatchItem("broken", b"junk", same),        # FAILED
        ]
        res = run_batch(items, cfg)
        statuses = {it.case_id: it.status for it in res.items}
        assert statuses == {
            "ok-same": ItemStatus.UNCHANGED,
            "ok-noise": ItemStatus.SUCCESS,
            "diff": ItemStatus.CHANGED,
            "broken": ItemStatus.FAILED,
        }
        assert res.summary.unchanged == 1
        assert res.summary.success == 1
        assert res.summary.changed == 1
        assert res.summary.failed == 1

    def test_single_failure_does_not_affect_others(self):
        same = make_png(BASE)
        items = [
            BatchItem("bad-1", b"junk", same),
            BatchItem("good", same, same),
            BatchItem("bad-2", same, b"junk"),
        ]
        res = run_batch(items)
        by_id = {it.case_id: it for it in res.items}
        assert by_id["good"].status is ItemStatus.UNCHANGED
        assert by_id["bad-1"].status is ItemStatus.FAILED
        assert by_id["bad-2"].status is ItemStatus.FAILED
        assert by_id["bad-1"].error and "ImageDecodeError" in by_id["bad-1"].error
        assert res.summary.failed == 2

    def test_baseline_from_store(self):
        store = BaselineStore()
        base_img = make_png(BASE)
        store.approve(store.submit_replace("case-a", base_img, "setup"))
        items = [
            BatchItem("case-a", make_png(BASE)),
            BatchItem("case-missing", make_png(BASE)),
        ]
        res = run_batch(items, store=store)
        by_id = {it.case_id: it for it in res.items}
        assert by_id["case-a"].status is ItemStatus.UNCHANGED
        assert by_id["case-missing"].status is ItemStatus.FAILED
        assert "BaselineNotFoundError" in (by_id["case-missing"].error or "")

    def test_invalid_region_fails_only_that_item(self):
        same = make_png(BASE)
        bad_cfg_item = BatchItem("good", same, same)
        res = run_batch([bad_cfg_item], CompareConfig(ignore_regions=(Region(0, 0, 1, 1),)))
        assert res.items[0].status is ItemStatus.UNCHANGED
        # 非法区域：该组 FAILED 并给出定位信息
        res = run_batch(
            [BatchItem("bad-region", same, same), BatchItem("good2", same, same)],
            CompareConfig(ignore_regions=(Region(100, 100, 5, 5),)),
        )
        by_id = {it.case_id: it for it in res.items}
        assert by_id["bad-region"].status is ItemStatus.FAILED
        assert "ignore region #0" in (by_id["bad-region"].error or "")
        assert by_id["good2"].status is ItemStatus.FAILED  # 同一 config，同样拒绝
        assert res.summary.failed == 2

    def test_empty_batch(self):
        res = run_batch([])
        assert res.items == ()
        assert res.summary.success == res.summary.failed == 0

    def test_diff_image_available_for_download(self):
        same = make_png(BASE)
        changed = fill_rect(same, 0, 0, 4, 4, (0, 0, 0))
        res = run_batch([BatchItem("c", changed, same)])
        item = res.items[0]
        assert item.status is ItemStatus.CHANGED
        assert item.compare is not None
        assert item.compare.diff_image[:8] == b"\x89PNG\r\n\x1a\n"
