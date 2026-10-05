"""Baseline versioning, approval workflow, history and concurrency."""
from __future__ import annotations

import threading
import time

from visual_regression.config import CompareConfig
from visual_regression.errors import (
    BaselineNotFoundError,
    PendingChangeNotFoundError,
)
from visual_regression.service import ItemStatus, VisualRegressionService

from .conftest import make_png


def test_first_compare_auto_registers_version_one(service):
    result = service.compare_case("case-a", make_png((1, 2, 3)))
    assert result.status == ItemStatus.SUCCESS
    assert result.baseline_version == 1
    assert service.store.latest("case-a").version == 1


def test_no_auto_register_without_baseline_fails():
    svc = VisualRegressionService(
        default_config=CompareConfig(auto_register=False)
    )
    try:
        svc.compare_case("case-x", make_png())
    except BaselineNotFoundError:
        return
    raise AssertionError("expected BaselineNotFoundError")


def test_propose_does_not_change_latest(service):
    service.compare_case("c", make_png((0, 0, 0), (8, 8)))
    service.propose_case("c", make_png((5, 5, 5), (8, 8)))
    assert service.store.latest("c").version == 1


def test_approve_appends_new_version_and_keeps_history(service):
    v1_png = make_png((0, 0, 0), (8, 8))
    service.compare_case("c", v1_png)
    v2_png = make_png((9, 9, 9), (8, 8))
    service.propose_case("c", v2_png, note="intentional update")
    entry = service.approve_case("c", approved_by="reviewer-1")
    assert entry.baseline_version == 2
    history = service.history("c")
    assert [h["version"] for h in history] == [1, 2]
    assert history[1]["approved_by"] == "reviewer-1"
    assert history[1]["note"] == "intentional update"
    # old version still retrievable byte-for-byte
    old = service.store.get_version("c", 1)
    assert old.version == 1 and len(old.image_png) > 0


def test_history_returns_immutable_snapshot(service):
    service.compare_case("c", make_png())
    h1 = service.store.history("c")
    service.propose_case("c", make_png((1, 1, 1)))
    service.approve_case("c")
    # the earlier snapshot is untouched
    assert [v.version for v in h1] == [1]


def test_reject_drops_pending_without_new_version(service):
    service.compare_case("c", make_png())
    service.propose_case("c", make_png((1, 1, 1)))
    service.reject_case("c")
    assert [v.version for v in service.store.history("c")] == [1]
    try:
        service.reject_case("c")
    except PendingChangeNotFoundError:
        pass
    else:
        raise AssertionError("expected PendingChangeNotFoundError")


def test_approve_without_pending_fails(service):
    service.compare_case("c", make_png())
    try:
        service.approve_case("c")
    except PendingChangeNotFoundError:
        return
    raise AssertionError("expected PendingChangeNotFoundError")


def test_compare_against_pinned_historical_version(service):
    v1 = make_png((0, 0, 0), (8, 8))
    v2 = make_png((255, 255, 255), (8, 8))
    service.compare_case("c", v1)
    service.propose_case("c", v2)
    service.approve_case("c")
    # comparing the v1 image while pinning version 1 -> no diff
    r = service.compare_case("c", v1, version=1)
    assert r.status == ItemStatus.NO_DIFF
    # against latest (v2, white) it is a diff
    r2 = service.compare_case("c", v1)
    assert r2.status == ItemStatus.DIFF


def test_concurrent_approve_never_exposes_half_updated_state(service):
    """Comparisons running while replacements are approved must always land
    on one complete, numbered baseline version and never see partial state."""
    black = make_png((0, 0, 0), (32, 32))
    service.compare_case("c", black)

    colors = [
        make_png((v * 8 % 256, 20, 40), (32, 32)) for v in range(1, 31)
    ]
    stop = threading.Event()
    observed_versions: list[int] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def approver():
        try:
            for i, img in enumerate(colors):
                service.propose_case("c", img, note=f"round {i}")
                service.approve_case("c")
                time.sleep(0)
        except Exception as exc:  # pragma: no cover - failure capture
            with lock:
                errors.append(exc)

    def comparer():
        try:
            while not stop.is_set():
                # Snapshot one complete, numbered version, then pin the
                # comparison to exactly that version. Whatever the approver
                # does meanwhile, the result must be NO_DIFF with ratio 0;
                # a torn/partial baseline would make these assertions fail.
                latest = service.store.latest("c")
                res = service.compare_case("c", latest.image_png, version=latest.version)
                with lock:
                    observed_versions.append(res.baseline_version or -1)
                assert res.status in (ItemStatus.NO_DIFF, ItemStatus.SUCCESS)
                assert res.baseline_version == latest.version
                cp = res.summary.get("changed_pixels")
                assert cp == 0
        except Exception as exc:  # pragma: no cover - failure capture
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=approver)]
    threads += [threading.Thread(target=comparer) for _ in range(4)]
    for t in threads:
        t.start()
    threads[0].join()
    stop.set()
    for t in threads[1:]:
        t.join()

    assert not errors, errors
    # 30 replacements + initial version => 31 versions total
    assert service.store.latest("c").version == 31
    # every observed version is a real complete version (1..31)
    assert observed_versions
    assert all(1 <= v <= 31 for v in observed_versions)
    # history is complete and contiguous
    assert [v.version for v in service.store.history("c")] == list(range(1, 32))
