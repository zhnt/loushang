"""Process-local Plugin Session owner references over original Journal locks."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, TypeVar

from loushang.harness.journal import JournalLockUnavailable, journal_file_lock


@dataclass(frozen=True, slots=True)
class _OwnerLeasePolicy:
    product_label: str
    error_code_prefix: str
    make_error: Callable[[str, str], RuntimeError]
    normalize_identifier: Callable[[str, str], str]


_PROCESS_SESSION_OWNER_LEASES_LOCK = threading.Lock()


@dataclass(slots=True)
class _SessionOwnerLeaseState:
    owner_id: str
    authority_id: str
    lease: AbstractContextManager[None]
    references: int = 1
    runtime_claim_id: str | None = None
    runtime_claim_references: int = 0


_PROCESS_SESSION_OWNER_LEASES: dict[Path, _SessionOwnerLeaseState] = {}


@dataclass(slots=True)
class _SessionOwnerLease(AbstractContextManager[None]):
    path: Path
    owner_id: str
    authority_id: str
    _runtime_claim_id: str | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _state_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    _policy: ClassVar[_OwnerLeasePolicy]

    def claim_runtime(self, claim_id: str) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError(
                    f"Closed {self._policy.product_label} Session owner cannot claim a runtime"
                )
            normalized_claim_id = self._policy.normalize_identifier(
                claim_id, "Session runtime claim id"
            )
            if self._runtime_claim_id == normalized_claim_id:
                return
            if self._runtime_claim_id is not None:
                raise RuntimeError(
                    f"{self._policy.product_label} Session owner lease already claimed another runtime"
                )
            _claim_session_owner_runtime(
                self.path,
                owner_id=self.owner_id,
                authority_id=self.authority_id,
                claim_id=normalized_claim_id,
                policy=self._policy,
            )
            self._runtime_claim_id = normalized_claim_id

    def __exit__(self, *_args: object) -> None:
        with self._state_lock:
            if self._closed:
                return
            try:
                _release_session_owner_lease(
                    self.path,
                    owner_id=self.owner_id,
                    authority_id=self.authority_id,
                    runtime_claim_id=self._runtime_claim_id,
                    policy=self._policy,
                )
            except BaseException:
                with _PROCESS_SESSION_OWNER_LEASES_LOCK:
                    current = _PROCESS_SESSION_OWNER_LEASES.get(self.path)
                    authority_was_removed = (
                        current is None or current.authority_id != self.authority_id
                    )
                # journal_file_lock closes its handle even when platform
                # unlock reports an error. In that case the exact authority
                # incarnation was removed and this wrapper cannot retry it.
                if authority_was_removed:
                    self._closed = True
                raise
            else:
                self._closed = True


LeaseT = TypeVar("LeaseT", bound=_SessionOwnerLease)


def _acquire_session_owner_lease(
    lease_path: Path,
    *,
    owner_id: str,
    lease_type: type[LeaseT],
) -> LeaseT:
    policy = lease_type._policy
    normalized_owner_id = policy.normalize_identifier(owner_id, "Session owner id")
    with _PROCESS_SESSION_OWNER_LEASES_LOCK:
        existing = _PROCESS_SESSION_OWNER_LEASES.get(lease_path)
        if existing is not None:
            if existing.owner_id != normalized_owner_id:
                raise policy.make_error(
                    f"{policy.product_label} Session is already active in another runtime",
                    f"{policy.error_code_prefix}_session_already_active",
                )
            existing.references += 1
            return lease_type(
                path=lease_path,
                owner_id=normalized_owner_id,
                authority_id=existing.authority_id,
            )
        lease = journal_file_lock(
            lease_path,
            "exclusive",
            lock_suffix="",
            blocking=False,
        )
        try:
            lease.__enter__()
        except JournalLockUnavailable as exc:
            raise policy.make_error(
                f"{policy.product_label} Session is already active in another runtime",
                f"{policy.error_code_prefix}_session_already_active",
            ) from exc
        authority_id = secrets.token_hex(16)
        _PROCESS_SESSION_OWNER_LEASES[lease_path] = _SessionOwnerLeaseState(
            owner_id=normalized_owner_id,
            authority_id=authority_id,
            lease=lease,
        )
        return lease_type(
            path=lease_path,
            owner_id=normalized_owner_id,
            authority_id=authority_id,
        )


def _claim_session_owner_runtime(
    path: Path,
    *,
    owner_id: str,
    authority_id: str,
    claim_id: str,
    policy: _OwnerLeasePolicy,
) -> None:
    with _PROCESS_SESSION_OWNER_LEASES_LOCK:
        existing = _PROCESS_SESSION_OWNER_LEASES.get(path)
        if (
            existing is None
            or existing.owner_id != owner_id
            or existing.authority_id != authority_id
        ):
            raise RuntimeError(
                f"{policy.product_label} Session owner lease ownership was lost"
            )
        if existing.runtime_claim_id is None:
            existing.runtime_claim_id = claim_id
            existing.runtime_claim_references = 1
            return
        if existing.runtime_claim_id != claim_id:
            raise policy.make_error(
                f"{policy.product_label} Session already has another prepared runtime",
                f"{policy.error_code_prefix}_session_runtime_already_active",
            )
        existing.runtime_claim_references += 1


def _release_session_owner_lease(
    path: Path,
    *,
    owner_id: str,
    authority_id: str,
    runtime_claim_id: str | None,
    policy: _OwnerLeasePolicy,
) -> None:
    with _PROCESS_SESSION_OWNER_LEASES_LOCK:
        existing = _PROCESS_SESSION_OWNER_LEASES.get(path)
        if (
            existing is None
            or existing.owner_id != owner_id
            or existing.authority_id != authority_id
        ):
            raise RuntimeError(
                f"{policy.product_label} Session owner lease ownership was lost"
            )
        if runtime_claim_id is not None:
            if existing.runtime_claim_id != runtime_claim_id:
                raise RuntimeError(
                    f"{policy.product_label} Session runtime claim ownership was lost"
                )
            existing.runtime_claim_references -= 1
            if existing.runtime_claim_references < 0:
                raise RuntimeError(
                    f"{policy.product_label} Session runtime claim count is invalid"
                )
            if existing.runtime_claim_references == 0:
                existing.runtime_claim_id = None
        if existing.references > 1:
            existing.references -= 1
            return
        # Keep the process-local authority visible until the OS authority is
        # actually released. A replacement acquisition then waits on this
        # mutex instead of observing an empty registry and failing against the
        # still-held non-blocking file lock.
        try:
            existing.lease.__exit__(None, None, None)
        finally:
            # The journal lock context always closes its file handle on exit.
            # Never retain a ref-countable state after a reported unlock
            # failure because the cross-process authority is already gone.
            del _PROCESS_SESSION_OWNER_LEASES[path]
