"""Batch execution: four states, partial failure isolation, mixed actions."""
from __future__ import annotations

from visual_regression.service import ItemStatus, VisualRegressionService
from visual_regression.config import ResourceLimits

from .conftest import make_png


def _svc():
    return VisualRegressionService(
        limits=ResourceLimits(max_pixels=1_000_000, pixel_budget=100_000_000)
    )


def test_batch_reports_four_statuses():
    svc = _svc()
    black = make_png((0, 0, 0), (16, 16))
    white = make_png((255, 255, 255), (16, 16))
    # seed baselines
    svc.compare_case("same", black)
    svc.compare_case("will-change", black)

    summary = svc.run_batch([
        # success: first-time auto-register
        {"case_id": "fresh", "candidate": black},
        # no_diff
        {"case_id": "same", "candidate": black},
        # diff
        {"case_id": "will-change", "candidate": white},
        # failed: corrupt image
        {"case_id": "broken", "candidate": b"garbage"},
    ])
    assert summary.total == 4
    assert (summary.success, summary.no_diff, summary.diff, summary.failed) == (1, 1, 1, 1)
    statuses = [i.status for i in summary.items]
    assert statuses == [
        ItemStatus.SUCCESS,
        ItemStatus.NO_DIFF,
        ItemStatus.DIFF,
        ItemStatus.FAILED,
    ]


def test_one_failure_does_not_stop_later_items():
    svc = _svc()
    black = make_png((0, 0, 0), (8, 8))
    summary = svc.run_batch([
        {"case_id": "a", "candidate": b"bad"},
        {"case_id": "b", "candidate": black},
        {"case_id": "c", "candidate": b"bad2"},
        {"case_id": "d", "candidate": black},
    ])
    assert summary.failed == 2 and summary.success == 2
    assert summary.items[1].case_id == "b"
    assert summary.items[3].case_id == "d"


def test_mixed_actions_in_one_batch():
    svc = _svc()
    black = make_png((0, 0, 0), (8, 8))
    white = make_png((255, 255, 255), (8, 8))
    svc.compare_case("c", black)
    summary = svc.run_batch([
        {"action": "propose", "case_id": "c", "candidate": white, "note": "x"},
        {"action": "approve", "case_id": "c", "approved_by": "bob"},
        {"action": "compare", "case_id": "c", "candidate": white},
        {"action": "approve", "case_id": "c"},  # no pending -> failed, isolated
        {"action": "reject", "case_id": "missing"},  # failed
    ])
    assert summary.success == 2 and summary.no_diff == 1 and summary.failed == 2
    assert summary.items[1].baseline_version == 2
    assert summary.items[2].status == ItemStatus.NO_DIFF
    assert summary.items[3].error_code == "pending_change_not_found"


def test_bad_region_in_batch_item_is_rejected_with_index():
    svc = _svc()
    black = make_png(size=(8, 8))
    svc.compare_case("c", black)
    summary = svc.run_batch([
        {
            "case_id": "c",
            "candidate": black,
            "ignore_regions": [{"x": 0, "y": 0, "width": 99, "height": 1}],
        }
    ])
    assert summary.failed == 1
    assert summary.items[0].error_code == "invalid_ignore_region"
    assert "ignore_regions[0]" in summary.items[0].error


def test_unknown_action_and_malformed_item_fail_without_raising():
    svc = _svc()
    summary = svc.run_batch(["not-an-object", {"action": "frobnicate", "case_id": "c"}])
    assert summary.failed == 2


def test_diff_item_carries_ratio_and_artifact():
    svc = _svc()
    svc.compare_case("c", make_png((0, 0, 0), (10, 10)))
    summary = svc.run_batch([
        {"case_id": "c", "candidate": make_png((200, 200, 200), (10, 10))}
    ])
    item = summary.items[0]
    assert item.status == ItemStatus.DIFF
    assert item.summary["ratio"] == 1.0
    assert item.artifact_id and svc.get_artifact(item.artifact_id)
