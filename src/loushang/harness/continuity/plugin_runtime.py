"""Process-scoped owner generation for installed Continuity Plugins."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, TypeVar, runtime_checkable

from loushang.harness.capabilities.component_admission import (
    CapabilityComponentAdmission,
    CapabilityComponentOwnerAuthority,
    CapabilityComponentOwnerSnapshot,
)
from loushang.harness.capabilities.component_runtime import (
    CapabilityOwnerComponentBinder,
    CapabilityOwnerComponentGenerationSnapshot,
    CapabilityOwnerComponentRuntime,
)
from loushang.harness.capabilities.component_selection import (
    CapabilityComponentSelectionChoice,
    CapabilityComponentSelectionPlan,
    ProductCapabilityComponentResolver,
    ResolvedCapabilityComponentSet,
)
from loushang.harness.capabilities.owner_component_host import (
    CapabilityOwnerComponentHost,
    PreparedCapabilityOwnerComponent,
)
from loushang.harness.continuity.composition import (
    BoundContinuityProvider,
    ExperienceComposition,
    PluginContinuityProviderProvenance,
    _bind_gated_plugin_continuity_provider,
    _compose_experience_continuity_with_plugins,
    _create_plugin_continuity_provider_provenance,
)
from loushang.harness.continuity.hub import ContinuityHub, build_continuity_hub
from loushang.harness.continuity.import_provider import (
    ContinuityActivationBridge,
    ContinuityImportProvider,
    ContinuityImportProviderPack,
)
from loushang.harness.continuity.plugin_declaration import (
    CONTINUITY_PROVIDER_COMPONENT_DEFINITION,
    CONTINUITY_PROVIDER_COMPONENT_KIND,
    CONTINUITY_PROVIDER_CONTRIBUTION_KIND,
    prepare_continuity_provider_component_candidate,
    validate_continuity_provider_component_payload,
)
from loushang.harness.continuity.plugin_provider import (
    ContinuityPluginGenerationGate,
    ContinuityPluginGenerationQuiesceError,
    PluginContinuityProvider,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionCandidate,
    PluginContributionRef,
    PluginInstanceRevisionRef,
    PluginSelection,
)
from loushang.harness.runtime.registration import _await_cancellation_atomic

T = TypeVar("T")


class ContinuityPluginLifecycleError(RuntimeError):
    """Stable fail-closed diagnostic for one private owner generation."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code
        self.pending_cleanup: ContinuityPluginPendingCleanup | None = None


class _ContinuityPluginGenerationReservation:
    def __init__(self, authority: ContinuityPluginGenerationAuthority) -> None:
        self._authority = authority
        self._released = False

    @property
    def runtime_id(self) -> str:
        return self._authority.runtime_id

    def release(self) -> None:
        if self._released:
            return
        self._authority._release(self)
        self._released = True


class ContinuityPluginGenerationAuthority:
    """Product-owned, single-generation authority for one concrete runtime."""

    def __init__(self, *, product_id: str, runtime_id: str) -> None:
        for value, name in (
            (product_id, "Continuity Product id"),
            (runtime_id, "Continuity runtime id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        self.product_id = product_id
        self.runtime_id = runtime_id
        self._lock = threading.Lock()
        self._active: _ContinuityPluginGenerationReservation | None = None

    def _reserve(self, *, product_id: str) -> _ContinuityPluginGenerationReservation:
        if product_id != self.product_id:
            raise ContinuityPluginLifecycleError(
                "Continuity generation authority belongs to another Product.",
                code="continuity_provider_generation_authority_mismatch",
            )
        with self._lock:
            if self._active is not None:
                raise ContinuityPluginLifecycleError(
                    "Continuity runtime already owns a generation reservation.",
                    code="continuity_provider_generation_already_reserved",
                )
            reservation = _ContinuityPluginGenerationReservation(self)
            self._active = reservation
            return reservation

    def _release(self, reservation: _ContinuityPluginGenerationReservation) -> None:
        with self._lock:
            if self._active is not reservation:
                raise RuntimeError("Continuity generation reservation is not active")
            self._active = None


@dataclass(frozen=True, slots=True, init=False)
class ResolvedContinuityPluginSelection:
    """Exact owner-admitted projection of one finalized Plugin selection."""

    plugin_selection: PluginSelection = field(repr=False)
    candidates: tuple[PluginContributionCandidate, ...] = field(repr=False)
    admissions: tuple[CapabilityComponentAdmission, ...]
    owner_snapshot: CapabilityComponentOwnerSnapshot
    resolved_set: ResolvedCapabilityComponentSet

    def __init__(self) -> None:
        raise TypeError("Continuity Plugin selection is owner-constructed")

    def __post_init__(self) -> None:
        if not isinstance(self.plugin_selection, PluginSelection):
            raise TypeError("Continuity selection requires finalized PluginSelection")
        if not self.candidates or any(
            not isinstance(item, PluginContributionCandidate)
            for item in self.candidates
        ):
            raise TypeError("Continuity selection requires Plugin candidates")
        if len(self.candidates) != len(self.admissions) or len(self.admissions) != len(
            self.resolved_set.components
        ):
            raise ValueError("Continuity owner selection chain is incomplete")


def resolve_continuity_plugin_selection(
    selection: PluginSelection,
    *,
    owner_authority: CapabilityComponentOwnerAuthority,
    issued_at: int,
    expires_at: int,
    now: int,
) -> ResolvedContinuityPluginSelection:
    """Compile, admit, and resolve only finalized Continuity contributions."""

    if not isinstance(selection, PluginSelection):
        raise TypeError("Continuity owner requires finalized PluginSelection")
    if (
        not isinstance(owner_authority, CapabilityComponentOwnerAuthority)
        or owner_authority.definition != CONTINUITY_PROVIDER_COMPONENT_DEFINITION
    ):
        raise TypeError("Continuity owner authority does not own its Definition")
    all_candidate_refs = tuple(
        PluginContributionRef(
            item.package.manifest.name,
            item.declaration.contribution_id,
        )
        for item in selection.candidates
    )
    if len(all_candidate_refs) != len(set(all_candidate_refs)) or set(
        all_candidate_refs
    ) != set(selection.plan.selected_contributions):
        raise ContinuityPluginLifecycleError(
            "Finalized Plugin candidate set does not match Product selection.",
            code="continuity_provider_selection_mismatch",
        )
    candidate_by_ref = dict(zip(all_candidate_refs, selection.candidates, strict=True))
    selected_refs = tuple(
        item
        for item in selection.plan.selected_contributions
        if candidate_by_ref[item].declaration.kind
        == CONTINUITY_PROVIDER_CONTRIBUTION_KIND
    )
    if not selected_refs:
        raise ContinuityPluginLifecycleError(
            "Finalized Plugin selection has no Continuity Provider.",
            code="continuity_provider_selection_empty",
        )
    candidates = tuple(candidate_by_ref[item] for item in selected_refs)
    component_candidates = tuple(
        prepare_continuity_provider_component_candidate(selection, item)
        for item in candidates
    )
    admissions = tuple(
        owner_authority.admit(
            item,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        for item in component_candidates
    )
    plan = CapabilityComponentSelectionPlan(
        product_id=selection.plan.context.product_id,
        scope_id=selection.plan.context.scope_id,
        capability_id=CONTINUITY_PROVIDER_COMPONENT_DEFINITION.capability_id,
        owner_id=CONTINUITY_PROVIDER_COMPONENT_DEFINITION.owner_id,
        product_policy_revision=selection.plan.context.policy_revision,
        choices=(
            CapabilityComponentSelectionChoice(
                component_kind=CONTINUITY_PROVIDER_COMPONENT_KIND,
                admission_fingerprints=tuple(item.fingerprint for item in admissions),
            ),
        ),
    )
    owner_snapshot = owner_authority.snapshot()
    resolved = ProductCapabilityComponentResolver().resolve(
        plan,
        definitions=(CONTINUITY_PROVIDER_COMPONENT_DEFINITION,),
        admissions=admissions,
        owner_snapshots=(owner_snapshot,),
        now=now,
    )
    return _create_resolved_continuity_plugin_selection(
        plugin_selection=selection,
        candidates=candidates,
        admissions=admissions,
        owner_snapshot=owner_snapshot,
        resolved_set=resolved,
    )


def _create_resolved_continuity_plugin_selection(
    *,
    plugin_selection: PluginSelection,
    candidates: tuple[PluginContributionCandidate, ...],
    admissions: tuple[CapabilityComponentAdmission, ...],
    owner_snapshot: CapabilityComponentOwnerSnapshot,
    resolved_set: ResolvedCapabilityComponentSet,
) -> ResolvedContinuityPluginSelection:
    resolved = object.__new__(ResolvedContinuityPluginSelection)
    for name, value in locals().items():
        if name != "resolved":
            object.__setattr__(resolved, name, value)
    resolved.__post_init__()
    return resolved


@runtime_checkable
class ContinuityPluginInstanceFamilyLease(Protocol):
    @property
    def family_id(self) -> str: ...

    @property
    def instance_revision_ref(self) -> PluginInstanceRevisionRef: ...

    async def security_handoff(
        self,
        evidence: ContinuityPluginSecurityRetirementEvidence,
    ) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class ContinuityPluginInstanceFamilyAuthority(Protocol):
    async def acquire(
        self,
        instance_revision_ref: PluginInstanceRevisionRef,
        *,
        holder_reference: str,
    ) -> ContinuityPluginInstanceFamilyLease: ...


@dataclass(slots=True, init=False)
class ContinuityPluginGeneration:
    """Private owner generation; it is inert until a Publication is created."""

    resolved: ResolvedContinuityPluginSelection
    runtime: CapabilityOwnerComponentRuntime = field(repr=False)
    binder: CapabilityOwnerComponentBinder = field(repr=False)
    snapshot: CapabilityOwnerComponentGenerationSnapshot
    prepared: tuple[PreparedCapabilityOwnerComponent, ...] = field(repr=False)
    instance_families: tuple[ContinuityPluginInstanceFamilyLease, ...] = field(
        repr=False
    )
    providers: tuple[
        tuple[ContinuityImportProvider, PluginContinuityProviderProvenance], ...
    ] = field(repr=False)
    _reservation: _ContinuityPluginGenerationReservation = field(repr=False)
    gate: ContinuityPluginGenerationGate = field(
        default_factory=ContinuityPluginGenerationGate,
        repr=False,
    )
    _published: bool = False
    _security_cleanup_evidence: ContinuityPluginSecurityRetirementEvidence | None = (
        field(default=None, repr=False)
    )
    _security_cleanup_prepared: bool = False
    _disposed: bool = False

    def __init__(self) -> None:
        raise TypeError("Continuity Plugin generation is owner-constructed")

    async def dispose(self) -> None:
        """Dispose components first and release exact Instance families last."""

        if self._disposed:
            return
        if self._published and not self.gate.closing:
            raise ContinuityPluginLifecycleError(
                "Published Continuity generation must close through its Publication.",
                code="continuity_provider_publication_close_required",
            )
        if self.gate.security_closing and self._security_cleanup_evidence is None:
            raise ContinuityPluginLifecycleError(
                "Security cleanup handoff must precede generation disposal.",
                code="continuity_provider_security_cleanup_handoff_required",
            )
        diagnostic_codes = await self.binder.dispose(self.runtime)
        if diagnostic_codes:
            raise ContinuityPluginLifecycleError(
                "Continuity owner generation cleanup remains retryable.",
                code="continuity_provider_generation_cleanup_retryable",
            )
        if self._security_cleanup_evidence is not None:
            await self._handoff_security_cleanup()
        failures: list[BaseException] = []
        for lease in reversed(self.instance_families):
            try:
                await lease.close()
            except BaseException as exc:
                failures.append(exc)
        if failures:
            error = ContinuityPluginLifecycleError(
                "Continuity Instance family cleanup remains retryable.",
                code="continuity_provider_instance_family_cleanup_retryable",
            )
            for failure in failures:
                error.add_note(type(failure).__name__)
            raise error
        self._disposed = True
        self._reservation.release()

    def authorize_security_cleanup(
        self,
        evidence: ContinuityPluginSecurityRetirementEvidence,
    ) -> None:
        """Bind exact REVOKING evidence for post-component cleanup handoff."""

        if self._security_cleanup_evidence is evidence:
            return
        if self._security_cleanup_evidence is not None:
            raise ContinuityPluginLifecycleError(
                "Continuity security cleanup evidence changed during disposal.",
                code="continuity_provider_security_cleanup_evidence_mismatch",
            )
        if (
            not isinstance(evidence, ContinuityPluginSecurityRetirementEvidence)
            or evidence.phase != "revoking"
        ):
            raise TypeError("Continuity security cleanup requires REVOKING evidence")
        self._security_cleanup_evidence = evidence

    async def _handoff_security_cleanup(self) -> None:
        """Write ahead package cleanup after components, before family release."""

        if self._security_cleanup_prepared:
            return
        evidence = self._security_cleanup_evidence
        if evidence is None:
            raise RuntimeError("Continuity security cleanup evidence is missing")
        failures: list[BaseException] = []
        for lease in self.instance_families:
            try:
                await lease.security_handoff(evidence)
            except BaseException as exc:
                failures.append(exc)
        if failures:
            error = ContinuityPluginLifecycleError(
                "Continuity security cleanup handoff remains retryable.",
                code="continuity_provider_security_cleanup_handoff_retryable",
            )
            for failure in failures:
                error.add_note(type(failure).__name__)
            raise error
        self._security_cleanup_prepared = True


@dataclass(slots=True)
class ContinuityPluginPendingCleanup:
    """Exact unpublished state retained when reverse cleanup cannot finish."""

    binder: CapabilityOwnerComponentBinder = field(repr=False)
    runtime: CapabilityOwnerComponentRuntime = field(repr=False)
    prepared: tuple[PreparedCapabilityOwnerComponent, ...] = field(repr=False)
    families: tuple[ContinuityPluginInstanceFamilyLease, ...] = field(repr=False)
    reservation: _ContinuityPluginGenerationReservation = field(repr=False)
    _completed: bool = False

    async def retry(self) -> None:
        if self._completed:
            return
        codes = await _rollback_private_generation(
            binder=self.binder,
            runtime=self.runtime,
            prepared=self.prepared,
            families=self.families,
        )
        if codes:
            error = ContinuityPluginLifecycleError(
                "Continuity construction cleanup remains retryable.",
                code="continuity_provider_construction_cleanup_retryable",
            )
            error.pending_cleanup = self
            for code in codes:
                error.add_note(code)
            raise error
        self.reservation.release()
        self._completed = True


async def construct_continuity_plugin_generation(
    resolved: ResolvedContinuityPluginSelection,
    *,
    component_host: CapabilityOwnerComponentHost,
    activation_decision_ids: Mapping[str, str],
    instance_family_authority: ContinuityPluginInstanceFamilyAuthority,
    generation_authority: ContinuityPluginGenerationAuthority,
) -> ContinuityPluginGeneration:
    """Pin, prepare, construct, commit, and return one private generation."""

    if not isinstance(resolved, ResolvedContinuityPluginSelection):
        raise TypeError("Continuity construction requires resolved owner selection")
    if not isinstance(component_host, CapabilityOwnerComponentHost):
        raise TypeError("Continuity construction requires Component Host")
    if not isinstance(
        instance_family_authority, ContinuityPluginInstanceFamilyAuthority
    ):
        raise TypeError("Continuity construction requires Instance family authority")
    if not isinstance(generation_authority, ContinuityPluginGenerationAuthority):
        raise TypeError("Continuity construction requires generation authority")
    decisions = dict(activation_decision_ids)
    component_ids = tuple(
        item.component_id for item in resolved.resolved_set.components
    )
    if set(decisions) != set(component_ids) or any(
        not isinstance(item, str) or not item for item in decisions.values()
    ):
        raise ContinuityPluginLifecycleError(
            "Continuity activation decisions do not cover exact selection.",
            code="continuity_provider_activation_decision_set_mismatch",
        )
    reservation = generation_authority._reserve(
        product_id=resolved.resolved_set.product_id,
    )
    runtime_id = reservation.runtime_id

    try:
        runtime = CapabilityOwnerComponentRuntime(
            capability_id=CONTINUITY_PROVIDER_COMPONENT_DEFINITION.capability_id,
            owner_id=CONTINUITY_PROVIDER_COMPONENT_DEFINITION.owner_id,
            product_id=resolved.resolved_set.product_id,
            runtime_id=runtime_id,
        )
    except BaseException:
        reservation.release()
        raise
    holder_reference = _generation_holder_reference(
        runtime_id,
        resolved.resolved_set.fingerprint,
        generation=runtime.generation + 1,
    )
    families: list[ContinuityPluginInstanceFamilyLease] = []
    prepared: list[PreparedCapabilityOwnerComponent] = []
    binder = CapabilityOwnerComponentBinder()
    try:
        seen_instances: set[PluginInstanceRevisionRef] = set()
        for component in resolved.resolved_set.components:
            instance = component.admission.candidate.instance_revision_ref
            assert instance is not None
            if instance in seen_instances:
                continue
            seen_instances.add(instance)
            families.append(
                await instance_family_authority.acquire(
                    instance,
                    holder_reference=holder_reference,
                )
            )

        candidate_by_ref = {
            PluginContributionRef(
                item.package.manifest.name,
                item.declaration.contribution_id,
            ): item
            for item in resolved.candidates
        }
        trust_by_plugin = {
            item.plugin_id: item
            for item in resolved.plugin_selection.plan.source_trust_snapshots
        }
        for component in resolved.resolved_set.components:
            candidate = component.admission.candidate
            spec = candidate.binding_spec
            assert spec.plugin_id is not None
            package = candidate_by_ref[
                PluginContributionRef(spec.plugin_id, spec.contribution_id)
            ].package
            prepared.append(
                component_host.prepare_component(
                    component,
                    package=package,
                    owner_snapshot=resolved.owner_snapshot,
                    trust_snapshot=trust_by_plugin[spec.plugin_id],
                    decision_id=decisions[component.component_id],
                )
            )
        bind_result = await binder.bind(
            runtime,
            resolved.resolved_set,
            tuple(item.binding for item in prepared),
        )
        if bind_result.retirement_diagnostic_codes:
            raise ContinuityPluginLifecycleError(
                "Unexpected prior Continuity generation needs cleanup.",
                code="continuity_provider_generation_not_fresh",
            )
        for item in prepared:
            item.commit_after_owner_generation_publication()
        providers = await _capture_generation_providers(
            runtime,
            resolved=resolved,
            snapshot=bind_result.snapshot,
            prepared=tuple(prepared),
        )
        return _create_continuity_plugin_generation(
            resolved=resolved,
            runtime=runtime,
            binder=binder,
            snapshot=bind_result.snapshot,
            prepared=tuple(prepared),
            instance_families=tuple(families),
            providers=providers,
            reservation=reservation,
        )
    except BaseException as error:
        pending_cleanup = ContinuityPluginPendingCleanup(
            binder=binder,
            runtime=runtime,
            prepared=tuple(prepared),
            families=tuple(families),
            reservation=reservation,
        )
        cleanup = asyncio.create_task(pending_cleanup.retry())
        try:
            await _await_cancellation_atomic(cleanup)
        except ContinuityPluginLifecycleError as cleanup_error:
            raise cleanup_error from error
        raise


def _create_continuity_plugin_generation(
    *,
    resolved: ResolvedContinuityPluginSelection,
    runtime: CapabilityOwnerComponentRuntime,
    binder: CapabilityOwnerComponentBinder,
    snapshot: CapabilityOwnerComponentGenerationSnapshot,
    prepared: tuple[PreparedCapabilityOwnerComponent, ...],
    instance_families: tuple[ContinuityPluginInstanceFamilyLease, ...],
    providers: tuple[
        tuple[ContinuityImportProvider, PluginContinuityProviderProvenance], ...
    ],
    reservation: _ContinuityPluginGenerationReservation,
) -> ContinuityPluginGeneration:
    generation = object.__new__(ContinuityPluginGeneration)
    object.__setattr__(generation, "resolved", resolved)
    object.__setattr__(generation, "runtime", runtime)
    object.__setattr__(generation, "binder", binder)
    object.__setattr__(generation, "snapshot", snapshot)
    object.__setattr__(generation, "prepared", prepared)
    object.__setattr__(generation, "instance_families", instance_families)
    object.__setattr__(generation, "providers", providers)
    object.__setattr__(generation, "gate", ContinuityPluginGenerationGate())
    object.__setattr__(generation, "_published", False)
    object.__setattr__(generation, "_security_cleanup_evidence", None)
    object.__setattr__(generation, "_security_cleanup_prepared", False)
    object.__setattr__(generation, "_disposed", False)
    object.__setattr__(generation, "_reservation", reservation)
    return generation


@dataclass(frozen=True, slots=True, init=False)
class ContinuityPluginSecurityRetirementEvidence:
    """Opaque exact-member evidence returned by Plugin lifecycle authority."""

    instance_revision_refs: tuple[PluginInstanceRevisionRef, ...]
    phase: str
    evidence_fingerprint: str
    _authority: object = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("Security retirement evidence is authority-constructed")

    @classmethod
    def _issue(
        cls,
        authority: ContinuityPluginSecurityRetirementAuthority,
        *,
        instance_revision_refs: tuple[PluginInstanceRevisionRef, ...],
        phase: str,
        evidence_fingerprint: str,
    ) -> ContinuityPluginSecurityRetirementEvidence:
        """Narrow issuance seam for Plugin lifecycle authority adapters."""

        if phase not in {"accepted", "revoking"}:
            raise ValueError("Unsupported Continuity security retirement phase")
        if not instance_revision_refs or any(
            not isinstance(item, PluginInstanceRevisionRef)
            for item in instance_revision_refs
        ):
            raise TypeError("Security retirement evidence requires Instance revisions")
        if len(instance_revision_refs) != len(set(instance_revision_refs)):
            raise ValueError(
                "Security retirement evidence repeats an Instance revision"
            )
        if (
            not isinstance(evidence_fingerprint, str)
            or len(evidence_fingerprint) != 64
            or any(item not in "0123456789abcdef" for item in evidence_fingerprint)
        ):
            raise ValueError("Security retirement evidence fingerprint is invalid")
        evidence = object.__new__(cls)
        object.__setattr__(evidence, "instance_revision_refs", instance_revision_refs)
        object.__setattr__(evidence, "phase", phase)
        object.__setattr__(evidence, "evidence_fingerprint", evidence_fingerprint)
        object.__setattr__(evidence, "_authority", authority)
        return evidence


@runtime_checkable
class ContinuityPluginSecurityRetirementAuthority(Protocol):
    @property
    def instance_revision_refs(self) -> tuple[PluginInstanceRevisionRef, ...]: ...

    async def accept_revocation(
        self,
    ) -> ContinuityPluginSecurityRetirementEvidence: ...

    async def enter_revoking(
        self,
        acceptance: ContinuityPluginSecurityRetirementEvidence,
    ) -> ContinuityPluginSecurityRetirementEvidence: ...


@dataclass(slots=True, init=False)
class ContinuityPluginPublication:
    """The sole observable Hub over Product/OEM and one Plugin generation."""

    generation: ContinuityPluginGeneration = field(repr=False)
    composition: ExperienceComposition
    hub: ContinuityHub
    _lifecycle_lock: asyncio.Lock = field(repr=False)
    _security_authority: ContinuityPluginSecurityRetirementAuthority | None = field(
        default=None,
        repr=False,
    )
    _revocation_acceptance: ContinuityPluginSecurityRetirementEvidence | None = field(
        default=None, repr=False
    )
    _revoking_evidence: ContinuityPluginSecurityRetirementEvidence | None = field(
        default=None,
        repr=False,
    )
    _dispose_started: bool = False
    _closed: bool = False

    def __init__(self) -> None:
        raise TypeError("Continuity Plugin publication is owner-constructed")

    async def shutdown(self, *, quiesce_timeout: float | None = 30.0) -> None:
        """Graceful sealed-process shutdown: Hub, generation, then families."""

        if self._closed:
            return
        self.generation.gate.begin_close(security=False)
        async with self._lifecycle_lock:
            await self._retire(quiesce_timeout=quiesce_timeout)

    async def security_revoke(
        self,
        *,
        retirement: ContinuityPluginSecurityRetirementAuthority,
        quiesce_timeout: float | None = 30.0,
    ) -> None:
        """Enforce durable-accept, poison, quiesce, REVOKING, cleanup order."""

        if self._closed:
            if (
                self._security_authority is retirement
                and self._revoking_evidence is not None
            ):
                return
            raise ContinuityPluginLifecycleError(
                "Continuity publication closed before security retirement.",
                code="continuity_provider_security_retirement_after_graceful_close",
            )
        self._register_security_retirement(retirement)
        async with self._lifecycle_lock:
            await self._retire(quiesce_timeout=quiesce_timeout)

    def _register_security_retirement(
        self,
        retirement: ContinuityPluginSecurityRetirementAuthority,
    ) -> None:
        if self._dispose_started:
            raise ContinuityPluginLifecycleError(
                "Graceful Continuity disposal already linearized.",
                code="continuity_provider_generation_disposal_in_progress",
            )
        if not isinstance(retirement, ContinuityPluginSecurityRetirementAuthority):
            raise TypeError("Continuity security close requires retirement authority")
        expected = _generation_instance_revision_refs(self.generation)
        actual = tuple(retirement.instance_revision_refs)
        if len(actual) != len(set(actual)) or set(actual) != set(expected):
            raise ContinuityPluginLifecycleError(
                "Security retirement does not cover the exact owner generation.",
                code="continuity_provider_security_retirement_set_mismatch",
            )
        if self._security_authority is None:
            self._security_authority = retirement
        elif self._security_authority is not retirement:
            raise ContinuityPluginLifecycleError(
                "Continuity security retirement authority changed during close.",
                code="continuity_provider_security_retirement_authority_mismatch",
            )

    async def _retire(self, *, quiesce_timeout: float | None) -> None:
        if self._closed:
            return
        if self._dispose_started:
            raise ContinuityPluginLifecycleError(
                "Continuity generation disposal is already in progress.",
                code="continuity_provider_generation_disposal_in_progress",
            )
        await self._advance_security_acceptance()
        await _close_and_quiesce_publication(
            self,
            timeout=quiesce_timeout,
        )
        # A security request may have arrived while graceful quiesce awaited.
        await self._advance_security_acceptance()
        await self._advance_security_revoking()
        if self._revoking_evidence is not None:
            self.generation.authorize_security_cleanup(self._revoking_evidence)
        self._dispose_started = True
        try:
            await self.generation.dispose()
        except BaseException:
            self._dispose_started = False
            raise
        self._closed = True

    async def _advance_security_acceptance(self) -> None:
        authority = self._security_authority
        if authority is None or self._revocation_acceptance is not None:
            return
        transition = asyncio.create_task(authority.accept_revocation())
        evidence, cancellation = await _join_owned_transition(transition)
        _validate_security_retirement_evidence(
            evidence,
            authority=authority,
            expected_refs=_generation_instance_revision_refs(self.generation),
            phase="accepted",
        )
        self._revocation_acceptance = evidence
        # No await occurs between accepted evidence and the security close mark.
        self.generation.gate.begin_close(security=True)
        if cancellation is not None:
            raise cancellation

    async def _advance_security_revoking(self) -> None:
        authority = self._security_authority
        acceptance = self._revocation_acceptance
        if authority is None or self._revoking_evidence is not None:
            return
        if acceptance is None:
            raise RuntimeError("Security retirement acceptance is missing")
        transition = asyncio.create_task(authority.enter_revoking(acceptance))
        evidence, cancellation = await _join_owned_transition(transition)
        _validate_security_retirement_evidence(
            evidence,
            authority=authority,
            expected_refs=_generation_instance_revision_refs(self.generation),
            phase="revoking",
        )
        self._revoking_evidence = evidence
        if cancellation is not None:
            raise cancellation


def publish_continuity_plugin_generation(
    base: ExperienceComposition,
    generation: ContinuityPluginGeneration,
    *,
    activation_bridge: ContinuityActivationBridge,
    cursor_secret: bytes | None = None,
    provider_timeout: float = 5.0,
    activation_timeout: float | None = 120.0,
    concurrency_limit: int = 8,
    cursor_ttl: float = 900.0,
) -> ContinuityPluginPublication:
    """Validate one final composition before exposing its sole Hub."""

    if not isinstance(generation, ContinuityPluginGeneration):
        raise TypeError("Continuity publication requires its owner generation")
    if generation._published or generation._disposed:
        raise ContinuityPluginLifecycleError(
            "Continuity owner generation was already published or disposed.",
            code="continuity_provider_generation_not_publishable",
        )
    bound: list[BoundContinuityProvider] = []
    for provider, provenance in generation.providers:
        wrapped = PluginContinuityProvider(
            provider,
            bridge=activation_bridge,
            provenance=provenance,
            gate=generation.gate,
        )
        bound.append(_bind_gated_plugin_continuity_provider(wrapped, provenance))
    composition = _compose_experience_continuity_with_plugins(base, tuple(bound))
    hub = build_continuity_hub(
        composition,
        cursor_secret=cursor_secret,
        provider_timeout=provider_timeout,
        activation_timeout=activation_timeout,
        concurrency_limit=concurrency_limit,
        cursor_ttl=cursor_ttl,
    )
    generation._published = True
    return _create_continuity_plugin_publication(
        generation=generation,
        composition=composition,
        hub=hub,
    )


def _create_continuity_plugin_publication(
    *,
    generation: ContinuityPluginGeneration,
    composition: ExperienceComposition,
    hub: ContinuityHub,
) -> ContinuityPluginPublication:
    publication = object.__new__(ContinuityPluginPublication)
    object.__setattr__(publication, "generation", generation)
    object.__setattr__(publication, "composition", composition)
    object.__setattr__(publication, "hub", hub)
    object.__setattr__(publication, "_lifecycle_lock", asyncio.Lock())
    object.__setattr__(publication, "_security_authority", None)
    object.__setattr__(publication, "_revocation_acceptance", None)
    object.__setattr__(publication, "_revoking_evidence", None)
    object.__setattr__(publication, "_dispose_started", False)
    object.__setattr__(publication, "_closed", False)
    return publication


async def _close_and_quiesce_publication(
    publication: ContinuityPluginPublication,
    *,
    timeout: float | None,
) -> None:
    async def close() -> None:
        await publication.hub.close()
        await publication.generation.gate.quiesce(timeout=None)

    if timeout is not None and timeout <= 0:
        raise ValueError("Continuity quiesce timeout must be positive")
    try:
        if timeout is None:
            await close()
        else:
            async with asyncio.timeout(timeout):
                await close()
    except TimeoutError as exc:
        raise ContinuityPluginGenerationQuiesceError(
            "Continuity Plugin generation did not quiesce."
        ) from exc


def _generation_instance_revision_refs(
    generation: ContinuityPluginGeneration,
) -> tuple[PluginInstanceRevisionRef, ...]:
    result: list[PluginInstanceRevisionRef] = []
    seen: set[PluginInstanceRevisionRef] = set()
    for component in generation.resolved.resolved_set.components:
        instance = component.admission.candidate.instance_revision_ref
        assert instance is not None
        if instance not in seen:
            seen.add(instance)
            result.append(instance)
    return tuple(result)


def _validate_security_retirement_evidence(
    evidence: ContinuityPluginSecurityRetirementEvidence,
    *,
    authority: ContinuityPluginSecurityRetirementAuthority,
    expected_refs: tuple[PluginInstanceRevisionRef, ...],
    phase: str,
) -> None:
    if (
        not isinstance(evidence, ContinuityPluginSecurityRetirementEvidence)
        or evidence._authority is not authority
        or len(evidence.instance_revision_refs)
        != len(set(evidence.instance_revision_refs))
        or set(evidence.instance_revision_refs) != set(expected_refs)
        or evidence.phase != phase
        or not isinstance(evidence.evidence_fingerprint, str)
        or len(evidence.evidence_fingerprint) != 64
        or any(item not in "0123456789abcdef" for item in evidence.evidence_fingerprint)
    ):
        raise ContinuityPluginLifecycleError(
            "Plugin lifecycle returned invalid security retirement evidence.",
            code="continuity_provider_security_retirement_evidence_invalid",
        )


async def _join_owned_transition(
    task: asyncio.Task[T],
) -> tuple[T, asyncio.CancelledError | None]:
    """Finish a durable lifecycle transition before propagating cancellation."""

    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if caller is None or caller.cancelling() == 0:
                return task.result(), None
            cancellation = exc
    return task.result(), cancellation


async def _capture_generation_providers(
    runtime: CapabilityOwnerComponentRuntime,
    *,
    resolved: ResolvedContinuityPluginSelection,
    snapshot: CapabilityOwnerComponentGenerationSnapshot,
    prepared: tuple[PreparedCapabilityOwnerComponent, ...],
) -> tuple[tuple[ContinuityImportProvider, PluginContinuityProviderProvenance], ...]:
    leases = runtime.capture_all(CONTINUITY_PROVIDER_COMPONENT_KIND)
    try:
        resolved_by_id = {
            item.component_id: item for item in resolved.resolved_set.components
        }
        binding_by_id = {
            item.binding.resolved.component_id: item.binding for item in prepared
        }
        result: list[
            tuple[ContinuityImportProvider, PluginContinuityProviderProvenance]
        ] = []
        for lease in leases:
            payload = lease.require()
            validate_continuity_provider_component_payload(payload)
            assert isinstance(payload, ContinuityImportProviderPack)
            component = resolved_by_id[lease.component_id]
            candidate = component.admission.candidate
            spec = candidate.binding_spec
            instance = candidate.instance_revision_ref
            assert spec.plugin_id is not None
            assert instance is not None
            provenance = _create_plugin_continuity_provider_provenance(
                component_id=component.component_id,
                plugin_id=spec.plugin_id,
                contribution_id=spec.contribution_id,
                instance_id=instance.instance_id,
                instance_revision=instance.revision,
                source_trust_class=candidate.source_trust_class,
                source_trust_policy_revision=(candidate.source_trust_policy_revision),
                candidate_fingerprint=candidate.fingerprint,
                admission_fingerprint=component.admission_fingerprint,
                selection_plan_fingerprint=(component.selection_plan_fingerprint),
                binding_fingerprint=(
                    binding_by_id[component.component_id].binding_fingerprint
                ),
                generation_fingerprint=snapshot.generation_fingerprint,
            )
            result.extend((provider, provenance) for provider in payload.providers)
        return tuple(result)
    finally:
        for lease in reversed(leases):
            await lease.aclose()


async def _rollback_private_generation(
    *,
    binder: CapabilityOwnerComponentBinder,
    runtime: CapabilityOwnerComponentRuntime,
    prepared: tuple[PreparedCapabilityOwnerComponent, ...],
    families: tuple[ContinuityPluginInstanceFamilyLease, ...],
) -> tuple[str, ...]:
    codes: list[str] = []
    try:
        codes.extend(await binder.dispose(runtime))
    except BaseException:
        codes.append("continuity_provider_generation_rollback_failed")
    for item in reversed(prepared):
        try:
            await item.abort_uncommitted()
        except BaseException:
            codes.append("continuity_provider_activation_rollback_failed")
    if not runtime.has_pending_retirements:
        for lease in reversed(families):
            try:
                await lease.close()
            except BaseException:
                codes.append("continuity_provider_family_rollback_failed")
    return tuple(sorted(set(codes)))


def _generation_holder_reference(
    runtime_id: str,
    resolved_set_fingerprint: str,
    *,
    generation: int,
) -> str:
    document = (f"{runtime_id}\0{resolved_set_fingerprint}\0{generation}").encode(
        "utf-8"
    )
    digest = hashlib.sha256(
        b"loushang.continuity-owner-generation-holder/v1\0" + document
    ).hexdigest()
    return f"continuity-owner-generation:{digest}"


__all__ = [
    "ContinuityPluginGeneration",
    "ContinuityPluginGenerationAuthority",
    "ContinuityPluginInstanceFamilyAuthority",
    "ContinuityPluginInstanceFamilyLease",
    "ContinuityPluginLifecycleError",
    "ContinuityPluginPendingCleanup",
    "ContinuityPluginPublication",
    "ContinuityPluginSecurityRetirementAuthority",
    "ContinuityPluginSecurityRetirementEvidence",
    "ResolvedContinuityPluginSelection",
    "construct_continuity_plugin_generation",
    "publish_continuity_plugin_generation",
    "resolve_continuity_plugin_selection",
]
