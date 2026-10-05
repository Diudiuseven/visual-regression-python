"""In-process, versioned, approval-based baseline store.

Concurrency model:

* All state is guarded by one re-entrant lock. Version lists are only
  appended to; a :class:`BaselineVersion` is itself immutable and holds
  the full image bytes. Readers receive the object reference (or a copied
  list snapshot) and can never observe a half-written replacement.
* A replacement is a two-step approval flow: ``propose_replace`` stages a
  candidate; ``approve_replace`` appends it as the next version in a
  single critical section; ``reject_replace`` drops the staging entry.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import BaselineNotFoundError, PendingChangeNotFoundError


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class BaselineVersion:
    case_id: str
    version: int
    image_png: bytes
    created_at: str
    note: str = ""
    approved_by: str = ""


@dataclass(frozen=True)
class PendingChange:
    image_png: bytes
    created_at: str
    note: str
    proposed_by: str


class BaselineStore:
    """Thread-safe append-only baseline store with an approval workflow."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._versions: dict[str, list[BaselineVersion]] = {}
        self._pending: dict[str, PendingChange] = {}

    # ------------------------------------------------------------------ reads
    def has_case(self, case_id: str) -> bool:
        with self._lock:
            return case_id in self._versions and bool(self._versions[case_id])

    def latest(self, case_id: str) -> BaselineVersion:
        with self._lock:
            versions = self._versions.get(case_id)
            if not versions:
                raise BaselineNotFoundError(f"no baseline registered for case {case_id!r}")
            return versions[-1]

    def get_version(self, case_id: str, version: int) -> BaselineVersion:
        with self._lock:
            versions = self._versions.get(case_id)
            if not versions:
                raise BaselineNotFoundError(f"no baseline registered for case {case_id!r}")
            for item in versions:
                if item.version == version:
                    return item
            raise BaselineNotFoundError(
                f"case {case_id!r} has no version {version}; "
                f"available: 1..{versions[-1].version}"
            )

    def history(self, case_id: str) -> list[BaselineVersion]:
        """Return an immutable snapshot copy of the full version history."""
        with self._lock:
            return list(self._versions.get(case_id, ()))

    def pending(self, case_id: str) -> PendingChange | None:
        with self._lock:
            return self._pending.get(case_id)

    # ----------------------------------------------------------------- writes
    def register(
        self,
        case_id: str,
        image_png: bytes,
        *,
        note: str = "",
        approved_by: str = "system",
    ) -> BaselineVersion:
        """Append a version directly (used for first-baseline auto-register)."""
        if not isinstance(image_png, (bytes, bytearray)) or not image_png:
            from .errors import InvalidInputError

            raise InvalidInputError("baseline image must be non-empty bytes")
        with self._lock:
            versions = self._versions.setdefault(case_id, [])
            entry = BaselineVersion(
                case_id=case_id,
                version=len(versions) + 1,
                image_png=bytes(image_png),
                created_at=_utc_now(),
                note=note,
                approved_by=approved_by,
            )
            versions.append(entry)
            return entry

    def propose_replace(
        self,
        case_id: str,
        image_png: bytes,
        *,
        note: str = "",
        proposed_by: str = "anonymous",
    ) -> PendingChange:
        """Stage a replacement candidate, overwriting any earlier proposal."""
        if not isinstance(case_id, str) or not case_id:
            from .errors import InvalidInputError

            raise InvalidInputError("case_id must be a non-empty string")
        if not isinstance(image_png, (bytes, bytearray)) or not image_png:
            from .errors import InvalidInputError

            raise InvalidInputError("candidate image must be non-empty bytes")
        with self._lock:
            pending = PendingChange(
                image_png=bytes(image_png),
                created_at=_utc_now(),
                note=note,
                proposed_by=proposed_by,
            )
            self._pending[case_id] = pending
            return pending

    def approve_replace(self, case_id: str, *, approved_by: str = "reviewer") -> BaselineVersion:
        """Atomically promote the staged candidate to a new numbered version."""
        with self._lock:
            pending = self._pending.get(case_id)
            if pending is None:
                raise PendingChangeNotFoundError(
                    f"no pending replacement for case {case_id!r}"
                )
            versions = self._versions.setdefault(case_id, [])
            entry = BaselineVersion(
                case_id=case_id,
                version=len(versions) + 1,
                image_png=pending.image_png,
                created_at=_utc_now(),
                note=pending.note,
                approved_by=approved_by,
            )
            versions.append(entry)
            del self._pending[case_id]
            return entry

    def reject_replace(self, case_id: str) -> None:
        with self._lock:
            if case_id not in self._pending:
                raise PendingChangeNotFoundError(
                    f"no pending replacement for case {case_id!r}"
                )
            del self._pending[case_id]
