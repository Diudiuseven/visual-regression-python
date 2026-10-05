"""基准版本化管理：审批式替换、历史回溯、并发安全读取。

并发语义：
- 所有状态变更都在同一把锁内完成；版本快照（BaselineVersion）不可变。
- 替换走“提交提案 -> 审批 -> 生效”两步，生效是原子的：任何一次
  current() 读取要么拿到旧版本、要么拿到完整的新版本，不会读到中间态。
- 历史版本永久保留，可通过 get_version 回溯。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from enum import Enum

from .errors import BaselineNotFoundError, ProposalError


@dataclass(frozen=True)
class BaselineVersion:
    """一个不可变的基准版本快照。"""

    case_id: str
    version: int
    image: bytes
    author: str


@dataclass(frozen=True)
class VersionInfo:
    """历史版本元信息（不含图片字节）。"""

    version: int
    author: str
    current: bool


class _ProposalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class _Proposal:
    proposal_id: str
    case_id: str
    image: bytes
    author: str
    status: _ProposalStatus


class BaselineStore:
    """进程内基准仓库。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # case_id -> 版本号升序的不可变快照列表；最后一个为当前版本。
        self._versions: dict[str, list[BaselineVersion]] = {}
        self._proposals: dict[str, _Proposal] = {}

    def current(self, case_id: str) -> BaselineVersion:
        """返回当前生效的基准版本快照。"""
        with self._lock:
            versions = self._versions.get(case_id)
            if not versions:
                raise BaselineNotFoundError(f"no baseline for case {case_id!r}")
            return versions[-1]

    def get_version(self, case_id: str, version: int) -> BaselineVersion:
        """回溯指定历史版本。"""
        with self._lock:
            versions = self._versions.get(case_id)
            if not versions:
                raise BaselineNotFoundError(f"no baseline for case {case_id!r}")
            for v in versions:
                if v.version == version:
                    return v
            raise BaselineNotFoundError(
                f"case {case_id!r} has no version {version}"
            )

    def history(self, case_id: str) -> list[VersionInfo]:
        """返回该用例全部版本（含当前与历史），按版本号升序。"""
        with self._lock:
            versions = self._versions.get(case_id, [])
            if not versions:
                return []
            current_version = versions[-1].version
            return [
                VersionInfo(
                    version=v.version,
                    author=v.author,
                    current=v.version == current_version,
                )
                for v in versions
            ]

    def submit_replace(self, case_id: str, image: bytes, author: str) -> str:
        """提交替换提案，返回提案 ID；此时不生效。"""
        proposal_id = uuid.uuid4().hex
        with self._lock:
            self._proposals[proposal_id] = _Proposal(
                proposal_id=proposal_id,
                case_id=case_id,
                image=bytes(image),
                author=author,
                status=_ProposalStatus.PENDING,
            )
        return proposal_id

    def _take_pending(self, proposal_id: str) -> _Proposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ProposalError(f"unknown proposal {proposal_id!r}")
        if proposal.status is not _ProposalStatus.PENDING:
            raise ProposalError(
                f"proposal {proposal_id!r} already {proposal.status.value}"
            )
        return proposal

    def approve(self, proposal_id: str) -> BaselineVersion:
        """审批通过提案，新基准原子生效，旧版本进入历史。"""
        with self._lock:
            proposal = self._take_pending(proposal_id)
            versions = self._versions.setdefault(proposal.case_id, [])
            next_version = (versions[-1].version + 1) if versions else 1
            snapshot = BaselineVersion(
                case_id=proposal.case_id,
                version=next_version,
                image=proposal.image,
                author=proposal.author,
            )
            versions.append(snapshot)
            proposal.status = _ProposalStatus.APPROVED
            return snapshot

    def reject(self, proposal_id: str) -> None:
        """驳回提案，基准保持不变。"""
        with self._lock:
            proposal = self._take_pending(proposal_id)
            proposal.status = _ProposalStatus.REJECTED
