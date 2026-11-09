"""Plugin Session cleanup barrier using the same facade fields and authorities."""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar

from loushang.harness.plugin_management import PluginInstanceLeaseFamilyV1
from loushang.harness.runtime.registration import OwnerGenerationRetirementReceipt

from ._membership import (
    EventT,
    FamilyT,
    RootsT,
    _MembershipPolicy,
    _PluginSessionLifecycle,
)
from ._owner_lease import _SessionOwnerLease

LeaseT = TypeVar("LeaseT", bound=_SessionOwnerLease)


class _CloseState(Protocol):
    _closed: bool


class _PluginSessionLease(Generic[RootsT, EventT, FamilyT, LeaseT]):
    __slots__ = ()
    lifecycle: _PluginSessionLifecycle[RootsT, EventT, FamilyT, LeaseT]
    family: PluginInstanceLeaseFamilyV1
    _session_owner_lease: LeaseT
    _closed: bool
    _membership_policy: _MembershipPolicy[RootsT]

    def claim_runtime(self, runtime_claim_id: str | None = None) -> None:
        policy = self._membership_policy
        if self._closed:
            raise policy.make_error(
                f"Closed {policy.product_label} Session cannot claim a runtime",
                f"{policy.error_code_prefix}_session_lease_closed",
            )
        self._session_owner_lease.claim_runtime(
            self.family.family_id
            if runtime_claim_id is None
            else self._session_owner_lease._policy.normalize_identifier(
                runtime_claim_id, "Session runtime claim id"
            )
        )

    def prepare_owner_generations(
        self,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        policy = self._membership_policy
        if self._closed:
            raise policy.make_error(
                f"Closed {policy.product_label} Session cannot prepare owner generations",
                f"{policy.error_code_prefix}_session_lease_closed",
            )
        self.lifecycle.prepare_session_owner_generations(self.family, receipts)

    def publish_owner_generations(
        self,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        policy = self._membership_policy
        if self._closed:
            raise policy.make_error(
                f"Closed {policy.product_label} Session cannot publish owner generations",
                f"{policy.error_code_prefix}_session_lease_closed",
            )
        self.lifecycle.publish_session_owner_generations(self.family, receipts)

    def retire_owner_generations(
        self,
        receipts: tuple[OwnerGenerationRetirementReceipt, ...],
    ) -> None:
        policy = self._membership_policy
        if self._closed:
            raise policy.make_error(
                f"Closed {policy.product_label} Session cannot retire owner generations",
                f"{policy.error_code_prefix}_session_lease_closed",
            )
        self.lifecycle.retire_session_owner_generations(self.family, receipts)

    def close(self) -> None:
        policy = self._membership_policy
        if self._closed:
            return
        evidence = self.lifecycle.owner_evidence.family(self.family.family_id)
        if evidence is not None and not evidence.retired:
            raise policy.make_error(
                f"{policy.product_label} Session owner generation cleanup remains pending",
                f"{policy.error_code_prefix}_owner_generation_cleanup_pending",
            )
        self.lifecycle.release_session_family_and_reconcile(self.family)
        self._session_owner_lease.__exit__(None, None, None)
        state: _CloseState = self
        state._closed = True
