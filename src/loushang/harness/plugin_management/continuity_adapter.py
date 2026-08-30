"""Plugin-lifecycle adapters for the Continuity owner ports."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field

from loushang.harness.continuity.plugin_runtime import (
    ContinuityPluginInstanceFamilyLease,
    ContinuityPluginLifecycleError,
    ContinuityPluginSecurityRetirementEvidence,
)
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    journal_file_lock,
)
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRevocationV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
    PluginInstanceRuntimeSnapshotV1,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.security_acceptance import (
    PLUGIN_INSTANCE_SECURITY_RETIREMENT_ACCEPTANCE_CODEC as PLUGIN_CONTINUITY_SECURITY_RETIREMENT_ACCEPTANCE_CODEC,
)
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementAcceptanceV1 as PluginContinuitySecurityRetirementAcceptanceV1,
)
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournal as PluginContinuitySecurityRetirementJournal,
)
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournalError as PluginContinuitySecurityRetirementJournalError,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.selection import (
    PluginInstanceRevisionRef,
)


@dataclass(slots=True)
class _LedgerFamilyLease:
    ledger: PluginInstanceRuntimeLedger = field(repr=False)
    package_lifecycle: PluginPackageLifecycleLedger = field(repr=False)
    family: PluginInstanceLeaseFamilyV1
    instance_revision_ref: PluginInstanceRevisionRef
    _closed: bool = False

    @property
    def family_id(self) -> str:
        return self.family.family_id

    async def close(self) -> None:
        if self._closed:
            return
        release = PluginInstanceLeaseFamilyReleaseV1(
            family_id=self.family.family_id,
            operation_id=f"continuity-release:{self.family.family_id}",
            idempotency_key=f"continuity-release:{self.family.family_id}",
            release_reference=self.family.holder_reference,
        )
        await asyncio.to_thread(self.ledger.release_family, release)
        self._closed = True

    async def security_handoff(
        self,
        evidence: ContinuityPluginSecurityRetirementEvidence,
    ) -> None:
        if self._closed:
            return
        if (
            not isinstance(evidence, ContinuityPluginSecurityRetirementEvidence)
            or evidence.phase != "revoking"
            or self.instance_revision_ref not in evidence.instance_revision_refs
        ):
            raise ContinuityPluginLifecycleError(
                "Security cleanup evidence does not cover the Instance family.",
                code="continuity_provider_security_cleanup_evidence_mismatch",
            )
        identity = _security_cleanup_identity(
            self.family.family_id,
            evidence.evidence_fingerprint,
        )
        release = PluginInstanceLeaseFamilyReleaseV1(
            family_id=self.family.family_id,
            operation_id=f"continuity-security-release:{identity}",
            idempotency_key=f"continuity-security-release:{identity}",
            release_reference=f"continuity-security:{evidence.evidence_fingerprint}",
        )
        await asyncio.to_thread(
            self.package_lifecycle.handoff_cleanup_and_release,
            self.family.family_id,
            retirement_target_id=None,
            cleanup_kind="continuity.owner.security_shutdown",
            operation_id=f"continuity-security-cleanup:{identity}",
            idempotency_key=f"continuity-security-cleanup:{identity}",
            cleanup_reference=(f"continuity-security:{evidence.evidence_fingerprint}"),
            family_release=release,
        )
        self._closed = True


@dataclass(frozen=True, slots=True)
class PluginInstanceLedgerContinuityFamilyAuthority:
    """Resolve and pin exact installed revisions through the durable ledger."""

    ledger: PluginInstanceRuntimeLedger = field(repr=False, compare=False)
    package_lifecycle: PluginPackageLifecycleLedger = field(
        repr=False,
        compare=False,
    )
    security_acceptance_journal: PluginContinuitySecurityRetirementJournal = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.ledger, PluginInstanceRuntimeLedger):
            raise TypeError("Continuity family authority requires Instance ledger")
        if not isinstance(self.package_lifecycle, PluginPackageLifecycleLedger):
            raise TypeError("Continuity family authority requires Package lifecycle")
        if not isinstance(
            self.security_acceptance_journal,
            PluginContinuitySecurityRetirementJournal,
        ):
            raise TypeError("Continuity family authority requires security journal")
        if (
            self.package_lifecycle.instance_runtime_journal_path.resolve()
            != self.ledger.path.resolve()
        ):
            raise ValueError(
                "Continuity Package lifecycle belongs to another Instance ledger"
            )
        if (
            self.package_lifecycle.path.resolve()
            == self.security_acceptance_journal.path
        ):
            raise ValueError(
                "Continuity security and Package lifecycle journals must be distinct"
            )
        self.ledger.bind_security_acceptance_source(self.security_acceptance_journal)

    async def acquire(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
        *,
        holder_reference: str,
    ) -> ContinuityPluginInstanceFamilyLease:
        await asyncio.to_thread(
            self.security_acceptance_journal.reconcile,
            self.ledger,
        )
        snapshot = await asyncio.to_thread(self.ledger.snapshot)
        instance = snapshot.instance(instance_revision_ref)
        if instance is None or instance.state != "ACTIVE":
            raise ContinuityPluginLifecycleError(
                "Continuity Plugin Instance is not currently ACTIVE.",
                code="continuity_provider_instance_not_active",
            )
        identity = _lease_identity(holder_reference, instance_revision_ref)
        family = await asyncio.to_thread(
            self.ledger.acquire_current_family,
            (instance.installation_key,),
            lease_kind="owner_generation",
            operation_id=f"continuity-acquire:{identity}",
            idempotency_key=f"continuity-acquire:{identity}",
            holder_reference=holder_reference,
        )
        if (
            len(family.members) != 1
            or family.members[0].instance_revision_ref != instance_revision_ref
        ):
            stale_error = ContinuityPluginLifecycleError(
                "Instance ledger returned another Plugin revision.",
                code="continuity_provider_instance_revision_stale",
            )
            try:
                await _LedgerFamilyLease(
                    ledger=self.ledger,
                    package_lifecycle=self.package_lifecycle,
                    family=family,
                    instance_revision_ref=instance_revision_ref,
                ).close()
            except BaseException as cleanup_error:
                stale_error.add_note(
                    "Stale Continuity Instance family cleanup failed: "
                    f"{type(cleanup_error).__name__}"
                )
            raise stale_error
        return _LedgerFamilyLease(
            ledger=self.ledger,
            package_lifecycle=self.package_lifecycle,
            family=family,
            instance_revision_ref=instance_revision_ref,
        )


@dataclass(frozen=True, slots=True)
class PluginInstanceLedgerContinuitySecurityRetirementAuthority:
    """Durably accept and enter REVOKING for one exact Instance set."""

    ledger: PluginInstanceRuntimeLedger = field(repr=False, compare=False)
    acceptance_journal: PluginContinuitySecurityRetirementJournal = field(
        repr=False,
        compare=False,
    )
    revocations: tuple[PluginInstanceRevocationV1, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.ledger, PluginInstanceRuntimeLedger):
            raise TypeError("Continuity security retirement requires Instance ledger")
        if not isinstance(
            self.acceptance_journal,
            PluginContinuitySecurityRetirementJournal,
        ):
            raise TypeError(
                "Continuity security retirement requires acceptance journal"
            )
        if self.acceptance_journal.path.resolve() in {
            self.ledger.path.resolve(),
            self.ledger.management_operation_journal_path.resolve(),
        }:
            raise ValueError("Continuity security journals must be distinct")
        _validate_revocations(self.revocations)
        self.ledger.bind_security_acceptance_source(self.acceptance_journal)

    @property
    def instance_revision_refs(self) -> tuple[PluginInstanceRevisionRef, ...]:
        return _revocation_refs(self.revocations)

    async def accept_revocation(
        self,
    ) -> ContinuityPluginSecurityRetirementEvidence:
        record = await asyncio.to_thread(
            _accept_under_instance_operation_gate,
            self.ledger,
            self.acceptance_journal,
            self.revocations,
        )
        if record.revocations != self.revocations:
            raise ContinuityPluginLifecycleError(
                "Security acceptance returned another revocation set.",
                code="continuity_provider_security_acceptance_mismatch",
            )
        return ContinuityPluginSecurityRetirementEvidence._issue(
            self,
            instance_revision_refs=self.instance_revision_refs,
            phase="accepted",
            evidence_fingerprint=record.acceptance_id,
        )

    async def enter_revoking(
        self,
        acceptance: ContinuityPluginSecurityRetirementEvidence,
    ) -> ContinuityPluginSecurityRetirementEvidence:
        if (
            not isinstance(acceptance, ContinuityPluginSecurityRetirementEvidence)
            or acceptance._authority is not self
            or acceptance.phase != "accepted"
            or acceptance.instance_revision_refs != self.instance_revision_refs
            or acceptance.evidence_fingerprint
            != _security_acceptance_id(self.revocations)
        ):
            raise ContinuityPluginLifecycleError(
                "Continuity security acceptance evidence is invalid.",
                code="continuity_provider_security_acceptance_mismatch",
            )
        snapshots = list(
            await asyncio.to_thread(
                self.ledger.apply_accepted_security_revocations,
                self.revocations,
            )
        )
        for revocation, snapshot in zip(
            self.revocations,
            snapshots,
            strict=True,
        ):
            if (
                not isinstance(snapshot, PluginInstanceRuntimeSnapshotV1)
                or snapshot.instance_revision_ref != revocation.instance_revision_ref
                or snapshot.installation_key != revocation.installation_key
                or snapshot.state != "REVOKING"
                or snapshot.revocation != revocation
            ):
                raise ContinuityPluginLifecycleError(
                    "Instance ledger returned invalid REVOKING evidence.",
                    code="continuity_provider_security_revoking_evidence_invalid",
                )
        evidence_payload = [
            {
                "instanceRevisionRef": item.instance_revision_ref.to_dict(),
                "revocationId": item.revocation.revocation_id,
                "state": item.state,
            }
            for item in snapshots
            if item.revocation is not None
        ]
        evidence_fingerprint = hashlib.sha256(
            b"loushang.continuity-security-revoking/v1\0"
            + StrictPluginJsonCodec.encode(evidence_payload)
        ).hexdigest()
        return ContinuityPluginSecurityRetirementEvidence._issue(
            self,
            instance_revision_refs=self.instance_revision_refs,
            phase="revoking",
            evidence_fingerprint=evidence_fingerprint,
        )


def _lease_identity(
    holder_reference: str,
    instance: PluginInstanceRevisionRef,
) -> str:
    document = (
        f"{holder_reference}\0{instance.instance_id}\0"
        f"{instance.plugin_id}\0{instance.revision}"
    ).encode("utf-8")
    return hashlib.sha256(
        b"loushang.continuity-owner-generation-family/v1\0" + document
    ).hexdigest()


def _security_cleanup_identity(
    family_id: str,
    evidence_fingerprint: str,
) -> str:
    return hashlib.sha256(
        b"loushang.continuity-security-cleanup/v1\0"
        + f"{family_id}\0{evidence_fingerprint}".encode("utf-8")
    ).hexdigest()


def _accept_under_instance_operation_gate(
    ledger: PluginInstanceRuntimeLedger,
    journal: PluginContinuitySecurityRetirementJournal,
    revocations: tuple[PluginInstanceRevocationV1, ...],
) -> PluginContinuitySecurityRetirementAcceptanceV1:
    # This is the same cross-process gate used by every Instance activation
    # and family acquisition.  Either acquisition linearizes first, or the
    # durable acceptance becomes visible to its barrier check.
    with journal_file_lock(
        ledger.management_operation_journal_path,
        "exclusive",
        lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
    ):
        return journal._accept(revocations)


def _validate_revocations(
    revocations: tuple[PluginInstanceRevocationV1, ...],
) -> None:
    if not revocations or any(
        not isinstance(item, PluginInstanceRevocationV1) for item in revocations
    ):
        raise TypeError("Continuity security retirement requires revocations")
    refs = _revocation_refs(revocations)
    if len(refs) != len(set(refs)):
        raise ValueError("Continuity security retirement repeats an Instance revision")
    if refs != tuple(sorted(refs, key=_instance_ref_sort_key)):
        raise ValueError("Continuity security retirement set must be canonical")


def _revocation_refs(
    revocations: tuple[PluginInstanceRevocationV1, ...],
) -> tuple[PluginInstanceRevisionRef, ...]:
    return tuple(item.instance_revision_ref for item in revocations)


def _instance_ref_sort_key(
    value: PluginInstanceRevisionRef,
) -> tuple[str, str, int]:
    return value.plugin_id, value.instance_id, value.revision


def _security_acceptance_id(
    revocations: tuple[PluginInstanceRevocationV1, ...],
) -> str:
    payload = StrictPluginJsonCodec.encode([item.to_dict() for item in revocations])
    return hashlib.sha256(
        b"loushang.continuity-security-acceptance/v1\0" + payload
    ).hexdigest()


__all__ = [
    "PLUGIN_CONTINUITY_SECURITY_RETIREMENT_ACCEPTANCE_CODEC",
    "PluginContinuitySecurityRetirementAcceptanceV1",
    "PluginContinuitySecurityRetirementJournal",
    "PluginContinuitySecurityRetirementJournalError",
    "PluginInstanceLedgerContinuityFamilyAuthority",
    "PluginInstanceLedgerContinuitySecurityRetirementAuthority",
]
