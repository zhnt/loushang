"""Strict Product read of original A2 Source and dependency-selection evidence.

This is a preflight observation only. It has no runtime admission, cleanup,
lease, journal-rebind, or transaction execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionBasisV1,
    PackageClosureResolutionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencySelectionV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV2,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)

_BASIS_PHASES = frozenset(
    {
        "resolving_closure",
        "closure_verified",
        "transaction_pinned",
        "staging",
        "set_published",
        "committed",
    }
)
_PLAN_PHASES = frozenset(
    {"closure_verified", "transaction_pinned", "staging", "set_published", "committed"}
)


class PackageProductRebindSourceReadError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageProductRebindSourceObservationV1:
    operation_id: str
    request_fingerprint: str
    attempt_epoch: int
    attempt_revision: int
    artifact_digests: tuple[str, ...]
    resolution_evidence_refs: tuple[str, ...]
    source_proof_ref: str


class PackageProductRebindSourceReader:
    """Bind three Product owner reads to one failed A2 attempt."""

    def __init__(
        self,
        *,
        policy: PackageProductLocalWheelPolicy,
        lifecycle: PackageLifecycleJournal,
        resolution: PackageClosureResolutionJournal,
    ) -> None:
        if not isinstance(policy, PackageProductLocalWheelPolicy):
            raise TypeError("Product Source policy is required")
        if not isinstance(lifecycle, PackageLifecycleJournal):
            raise TypeError("Package lifecycle journal is required")
        if not isinstance(resolution, PackageClosureResolutionJournal):
            raise TypeError("Package resolution journal is required")
        self._policy = policy
        self._lifecycle = lifecycle
        self._resolution = resolution

    def observe(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1:
        return self._observe(operation_id, max_bytes=max_bytes, claim_phases=None)

    def observe_acquired_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1:
        """Read selected root-stage Sources without recovery authority."""

        return self._observe(
            operation_id,
            max_bytes=max_bytes,
            claim_phases=frozenset({"acquired", "inspecting", "extracted"}),
        )

    def observe_unstarted_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1:
        """Recheck selected Source bytes before interrupting an effect-free claim."""

        return self._observe(
            operation_id,
            max_bytes=max_bytes,
            claim_phases=frozenset({"classified", "acquiring"}),
        )

    def observe_resolving_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1:
        """Recheck selected root and dependency bytes during closure resolution."""

        return self._observe(
            operation_id,
            max_bytes=max_bytes,
            claim_phases=frozenset({"resolving_closure"}),
        )

    def observe_verified_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1:
        """Recheck selected Sources against the durable verified closure."""

        return self._observe(
            operation_id,
            max_bytes=max_bytes,
            claim_phases=frozenset({"closure_verified"}),
        )

    def observe_pinned_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1:
        """Recheck a selected retained graph's exact Source bytes."""

        return self._observe(
            operation_id,
            max_bytes=max_bytes,
            claim_phases=frozenset({"transaction_pinned"}),
        )

    def observe_published_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1:
        """Recheck selected Source bytes after the complete set was published."""

        return self._observe(
            operation_id,
            max_bytes=max_bytes,
            claim_phases=frozenset({"set_published"}),
        )

    def _observe(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        claim_phases: frozenset[str] | None,
    ) -> PackageProductRebindSourceObservationV1:
        original = self._lifecycle.read_operation(operation_id)
        if original is None:
            raise PackageProductRebindSourceReadError(
                "Package operation is absent",
                code="package_rebind_operation_missing",
            )
        request, status = original
        if not isinstance(request, PackageLifecycleRequestV2):
            raise PackageProductRebindSourceReadError(
                "Package operation has no runtime admission binding",
                code="package_rebind_request_version_unsupported",
            )
        if claim_phases is not None:
            selected = self._lifecycle.latest_rebind(operation_id)
            selected_claim = (
                selected is not None
                and selected.request == request
                and status.disposition == "active"
                and status.phase in claim_phases
                and status.attempt_epoch
                == selected.decision.expected_attempt_epoch + 1
                and status.attempt_revision > selected.record_revision
                and status.request_fingerprint
                == selected.decision.request_fingerprint
            )
            original_retained_claim = (
                selected is None
                and claim_phases
                in (frozenset({"transaction_pinned"}), frozenset({"set_published"}))
                and status.disposition == "active"
                and status.phase in claim_phases
                and status.attempt_epoch == 1
                and status.request_fingerprint == request.request_fingerprint
            )
            if not (selected_claim or original_retained_claim):
                raise PackageProductRebindSourceReadError(
                    "Package root claim has no selected rebind decision",
                    code=(
                        "package_rebind_claim_not_unstarted"
                        if claim_phases == frozenset({"classified", "acquiring"})
                        else "package_rebind_claim_not_resolving"
                        if claim_phases == frozenset({"resolving_closure"})
                        else "package_rebind_claim_not_verified"
                        if claim_phases == frozenset({"closure_verified"})
                        else "package_rebind_claim_not_pinned"
                        if claim_phases == frozenset({"transaction_pinned"})
                        else "package_rebind_claim_not_published"
                        if claim_phases == frozenset({"set_published"})
                        else "package_rebind_claim_not_acquired"
                    ),
                )
        records = self._resolution.read_attempt_evidence(
            operation_id=operation_id,
            attempt_epoch=status.attempt_epoch,
        )
        bases = tuple(
            record.evidence
            for record in records
            if isinstance(record.evidence, PackageClosureResolutionBasisV1)
        )
        selections = tuple(
            record.evidence
            for record in records
            if isinstance(record.evidence, PackageDependencySelectionV1)
        )
        plans = tuple(
            record.evidence
            for record in records
            if isinstance(record.evidence, VerifiedClosurePlanV2)
        )
        if status.phase in _BASIS_PHASES and len(bases) != 1:
            raise PackageProductRebindSourceReadError(
                "Failed Package attempt has no resolution basis",
                code="package_rebind_resolution_basis_missing",
            )
        if bases:
            basis = bases[0]
            if (
                basis.request_fingerprint != status.request_fingerprint
                or basis.policy_revision != request.policy_revision
                or basis.quota_profile_revision != request.quota_profile_revision
                or basis.resolution_environment.fingerprint
                != request.resolution_environment_fingerprint
            ):
                raise PackageProductRebindSourceReadError(
                    "Original Package resolution basis changed",
                    code="package_rebind_resolution_basis_changed",
                )
        if status.phase in _PLAN_PHASES and len(plans) != 1:
            raise PackageProductRebindSourceReadError(
                "Failed Package attempt has no verified closure",
                code="package_rebind_verified_closure_missing",
            )
        if claim_phases is not None:
            proofs = self._policy.prove_selected_active_claim_sources(
                request,
                status,
                selections=selections,
                max_bytes=max_bytes,
            )
        else:
            proofs = self._policy.prove_rebind_selected_sources(
                request,
                status,
                selections=selections,
                max_bytes=max_bytes,
            )
        if plans:
            plan = plans[0]
            root_node = next(
                node for node in plan.nodes if node.node_id == plan.root_node_id
            )
            observed_by_source = {
                proof.source_ref: proof.artifact_digest for proof in proofs
            }
            if (
                plan.resolution_environment_fingerprint
                != request.resolution_environment_fingerprint
                or root_node.canonical_source_identity
                != request.canonical_source_identity
                or len(plan.nodes) != len(proofs)
                or any(
                    observed_by_source.get(
                        sha256(
                            node.canonical_source_identity.encode("utf-8")
                        ).hexdigest()
                    )
                    != node.artifact_digest
                    for node in plan.nodes
                )
            ):
                raise PackageProductRebindSourceReadError(
                    "Verified closure Source differs from current pinned bytes",
                    code="package_rebind_verified_closure_changed",
                )
        resolution_refs = tuple(record.evidence_ref for record in records)
        artifact_digests = tuple(proof.artifact_digest for proof in proofs)
        proof_ref = sha256(
            canonical_json_bytes(
                {
                    "artifactDigests": list(artifact_digests),
                    "attemptEpoch": status.attempt_epoch,
                    # Rebind and supersession advance attempt_revision without
                    # changing the failed attempt's operation revision. Keep
                    # the proof comparable to its durable decision on replay.
                    "failedOperationRevision": status.journal_revision,
                    "operationId": operation_id,
                    "policyAuthorityRevision": self._policy.authority_revision,
                    "requestFingerprint": status.request_fingerprint,
                    "resolutionEvidenceRefs": list(resolution_refs),
                    "sourceProofs": [
                        {
                            "artifactDigest": proof.artifact_digest,
                            "byteCount": proof.byte_count,
                            "sourceRef": proof.source_ref,
                        }
                        for proof in proofs
                    ],
                    "version": 1,
                }
            )
        ).hexdigest()
        return PackageProductRebindSourceObservationV1(
            operation_id=operation_id,
            request_fingerprint=status.request_fingerprint,
            attempt_epoch=status.attempt_epoch,
            attempt_revision=status.attempt_revision,
            artifact_digests=artifact_digests,
            resolution_evidence_refs=resolution_refs,
            source_proof_ref=proof_ref,
        )
