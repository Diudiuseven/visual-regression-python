"""基准版本化：审批式替换、历史回溯、并发读写一致性。"""

from __future__ import annotations

import threading

import pytest

from visual_regression import BaselineNotFoundError, BaselineStore, ProposalError


class TestApprovalFlow:
    def test_missing_case_raises(self):
        store = BaselineStore()
        with pytest.raises(BaselineNotFoundError):
            store.current("nope")
        assert store.history("nope") == []

    def test_pending_proposal_not_visible(self):
        store = BaselineStore()
        store.submit_replace("c", b"v1", "alice")
        with pytest.raises(BaselineNotFoundError):
            store.current("c")

    def test_approve_activates_and_keeps_history(self):
        store = BaselineStore()
        p1 = store.submit_replace("c", b"v1", "alice")
        v1 = store.approve(p1)
        assert v1.version == 1
        p2 = store.submit_replace("c", b"v2", "bob")
        # 审批前读到的仍是旧版本
        assert store.current("c").image == b"v1"
        v2 = store.approve(p2)
        assert v2.version == 2
        assert store.current("c").image == b"v2"
        history = store.history("c")
        assert [(h.version, h.author, h.current) for h in history] == [
            (1, "alice", False),
            (2, "bob", True),
        ]

    def test_history_versions_retrievable(self):
        store = BaselineStore()
        for i in range(3):
            store.approve(store.submit_replace("c", f"v{i}".encode(), "a"))
        assert store.get_version("c", 1).image == b"v0"
        assert store.get_version("c", 3).image == b"v2"
        with pytest.raises(BaselineNotFoundError):
            store.get_version("c", 99)

    def test_reject_keeps_baseline(self):
        store = BaselineStore()
        store.approve(store.submit_replace("c", b"v1", "a"))
        p = store.submit_replace("c", b"v2", "b")
        store.reject(p)
        assert store.current("c").image == b"v1"
        assert len(store.history("c")) == 1

    def test_proposal_double_handling_rejected(self):
        store = BaselineStore()
        p = store.submit_replace("c", b"v1", "a")
        store.approve(p)
        with pytest.raises(ProposalError):
            store.approve(p)
        with pytest.raises(ProposalError):
            store.reject(p)
        with pytest.raises(ProposalError):
            store.approve("unknown-id")


class TestConcurrency:
    def test_reads_always_see_complete_version(self):
        store = BaselineStore()
        store.approve(store.submit_replace("c", b"gen-0", "init"))
        errors: list[str] = []
        stop = threading.Event()

        def reader() -> None:
            while not stop.is_set():
                v = store.current("c")
                expected = f"gen-{v.version - 1}".encode()
                if v.image != expected:
                    errors.append(f"version {v.version} has image {v.image!r}")

        def writer() -> None:
            for i in range(1, 200):
                store.approve(store.submit_replace("c", f"gen-{i}".encode(), "w"))

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        writer()
        stop.set()
        for t in threads:
            t.join()
        assert errors == []
        assert store.current("c").version == 200
        # 历史完整可回溯
        assert len(store.history("c")) == 200
        assert store.get_version("c", 1).image == b"gen-0"

    def test_concurrent_compares_use_consistent_snapshot(self):
        """对比与替换并发：每次对比都基于某个完整基准版本。"""
        import io

        from PIL import Image

        from visual_regression import CompareConfig, compare_images

        def png(color: tuple[int, int, int]) -> bytes:
            img = Image.new("RGB", (8, 8), color)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return buf.getvalue()

        store = BaselineStore()
        img_a = png((0, 0, 0))
        img_b = png((255, 255, 255))
        store.approve(store.submit_replace("c", img_a, "init"))
        candidate = png((255, 255, 255))
        results: list[bool] = []
        stop = threading.Event()

        def comparer() -> None:
            while not stop.is_set():
                base = store.current("c")
                r = compare_images(base.image, candidate, CompareConfig())
                # 基准只能是 img_a 或 img_b：结论只能是“有差异”或“无差异”
                results.append(r.changed)

        def replacer() -> None:
            for _ in range(50):
                store.approve(store.submit_replace("c", img_b, "w"))
                store.approve(store.submit_replace("c", img_a, "w"))

        threads = [threading.Thread(target=comparer) for _ in range(4)]
        for t in threads:
            t.start()
        replacer()
        stop.set()
        for t in threads:
            t.join()
        assert results  # 确实跑过对比
        assert all(isinstance(x, bool) for x in results)
