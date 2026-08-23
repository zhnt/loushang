"""Approval-gated construction adapter for selected in-process components."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import Never, cast

from loushang.harness.approval.plugin_activation import (
    ActivationUseReservationV1,
    ContributionActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationJournalError,
    PluginActivationUseState,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerSnapshot,
    CapabilityProviderSymbolLocator,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityProviderContext,
    CapabilityProviderDisposer,
    CapabilityProviderFactory,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProvider,
)
from loushang.harness.resources.plugins.import_realm import PluginImportRealm
from loushang.harness.resources.plugins.python_symbols import (
    VerifiedPluginPythonModule,
    load_verified_plugin_python_module,
)
from loushang.harness.resources.plugins.selection import (
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import PublishedPluginPackage

_MAX_JOURNAL_CAS_ATTEMPTS = 16
_PROVIDER_HOST_API_PREFIXES = (
    "loushang.harness.capabilities",
    "loushang.harness.runtime",
)


class CapabilityComponentHostError(RuntimeError):
    """Stable fail-closed component preparation or activation failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class CapabilityComponentHost:
    """Prepare Binder inputs without planning, binding, or publishing a graph."""

    def __init__(
        self,
        *,
        decision_journal: PluginActivationDecisionJournal,
        import_realm: PluginImportRealm,
        host_boot_id: str,
        clock: Callable[[], int],
    ) -> None:
        if not isinstance(decision_journal, PluginActivationDecisionJournal):
            raise TypeError("Component Host requires an activation decision journal")
        if not isinstance(import_realm, PluginImportRealm):
            raise TypeError("Component Host requires one import realm")
        _require_hex(host_boot_id, length=32, name="Host boot id")
        if not callable(clock):
            raise TypeError("Component Host requires a durable clock")
        self._journal = decision_journal
        self._import_realm = import_realm
        self._host_boot_id = host_boot_id
        self._clock = clock

    def activation_subject(
        self,
        resolved: ResolvedCapabilityProvider,
        *,
        owner_snapshot: CapabilityProviderOwnerSnapshot,
        trust_snapshot: PluginSourceTrustSnapshotV1,
    ) -> ContributionActivationApprovalSubject:
        _validate_current_authorities(
            resolved,
            owner_snapshot=owner_snapshot,
            trust_snapshot=trust_snapshot,
        )
        admission = resolved.admission
        candidate = admission.candidate
        spec = resolved.binding_spec
        return ContributionActivationApprovalSubject(
            candidate_fingerprint=admission.candidate_fingerprint,
            admission_fingerprint=admission.fingerprint,
            binding_spec_fingerprint=spec.fingerprint,
            capability_id=resolved.capability_id,
            owner_id=resolved.definition.owner_id,
            provider_id=resolved.provider.provider_id,
            plugin_id=spec.plugin_id,
            contribution_id=spec.contribution_id,
            package_content_digest=spec.package_content_digest,
            dependency_lock_digest=spec.dependency_lock_digest,
            product_id=candidate.product_id,
            scope_id=candidate.scope_id,
            instance_revision_ref=candidate.instance_revision_ref,
            source_trust_class=trust_snapshot.source_trust_class,
            source_trust_policy_revision=(
                trust_snapshot.source_trust_policy_revision
            ),
            product_policy_revision=candidate.product_policy_revision,
            owner_policy_revision=owner_snapshot.policy_revision,
            revocation_epoch=owner_snapshot.revocation_epoch,
            effective_facets=admission.effective_facets,
            effective_authorities=admission.effective_authorities,
            execution_model=spec.factory.execution_model,
        )

    def prepare_component(
        self,
        resolved: ResolvedCapabilityProvider,
        *,
        package: PublishedPluginPackage,
        owner_snapshot: CapabilityProviderOwnerSnapshot,
        trust_snapshot: PluginSourceTrustSnapshotV1,
        decision_id: str,
    ) -> PreparedCapabilityComponent:
        """Consume approval while preserving cancellation of an unstarted use."""

        subject = self.activation_subject(
            resolved,
            owner_snapshot=owner_snapshot,
            trust_snapshot=trust_snapshot,
        )
        _validate_package(resolved, package)
        now = self._now()
        admission = resolved.admission
        if now < admission.issued_at or now >= admission.expires_at:
            _raise_host(
                "capability_provider_admission_not_current",
                "Selected Capability Provider admission is not current.",
            )
        package.revision_handle.verify()
        try:
            self._import_realm.preflight(
                host_boot_id=self._host_boot_id,
                dependency_lock=package.dependency_lock,
            )
        except Exception as exc:
            raise CapabilityComponentHostError(
                "Plugin import realm rejected component preparation.",
                code=getattr(exc, "code", "plugin_import_realm_rejected"),
            ) from exc
        reservation = self._consume(subject, decision_id=decision_id)
        attempt = _PreparedComponentAttempt(
            resolved=resolved,
            package=package,
            reservation=reservation,
            journal=self._journal,
            import_realm=self._import_realm,
            host_boot_id=self._host_boot_id,
            clock=self._clock,
        )
        binding = CapabilityBundleProviderBinding(
            provider=resolved.provider,
            scope_instance_id=(
                f"{subject.scope_id}:{subject.plugin_id}:"
                f"{subject.contribution_id}:r{subject.instance_revision_ref.revision}"
            ),
            binding_input_fingerprint=subject.binding_spec_fingerprint,
            create=attempt.create,
            dispose=attempt.dispose,
        )
        return PreparedCapabilityComponent(binding=binding, _attempt=attempt)

    def _consume(
        self,
        subject: ContributionActivationApprovalSubject,
        *,
        decision_id: str,
    ) -> ActivationUseReservationV1:
        for _ in range(_MAX_JOURNAL_CAS_ATTEMPTS):
            snapshot = self._journal.snapshot()
            try:
                return self._journal.consume_activation_decision(
                    subject,
                    decision_id=decision_id,
                    host_boot_id=self._host_boot_id,
                    import_realm_id=self._import_realm.import_realm_id,
                    expected_journal_revision=snapshot.journal_revision,
                )
            except PluginActivationJournalError as exc:
                if exc.code != "plugin_activation_journal_revision_conflict":
                    raise CapabilityComponentHostError(
                        "Component activation authority was rejected.",
                        code=exc.code,
                    ) from exc
        _raise_host(
            "plugin_activation_journal_contention",
            "Component activation journal remained contended.",
        )

    def _now(self) -> int:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Component Host clock must be non-negative integer")
        return value


@dataclass(slots=True)
class _PreparedComponentAttempt:
    resolved: ResolvedCapabilityProvider
    package: PublishedPluginPackage
    reservation: ActivationUseReservationV1
    journal: PluginActivationDecisionJournal
    import_realm: PluginImportRealm
    host_boot_id: str
    clock: Callable[[], int]
    started: bool = False
    disposer: CapabilityProviderDisposer | None = None

    async def create(
        self,
        context: CapabilityProviderContext,
    ) -> CapabilityBundleValue:
        if self.started:
            _raise_host(
                "component_activation_use_consumed",
                "Prepared component binding is single-use.",
            )
        self.started = True
        lease = self.import_realm.reserve(
            host_boot_id=self.host_boot_id,
            execution_use_id=self.reservation.activation_use_id,
            dependency_lock=self.package.dependency_lock,
        )
        try:
            self._transition("CONSUMED_NOT_STARTED", "STARTING")
        except BaseException:
            self.import_realm.cancel(lease)
            self._try_transition(
                "CONSUMED_NOT_STARTED",
                "CANCELLED_BEFORE_START",
            )
            raise

        try:
            factory, disposer = self.import_realm.execute(
                lease,
                self._load_symbols,
            )
            self.import_realm.commit(lease)
            self._transition("STARTING", "STARTED")
            provider_context = replace(
                context,
                binding_inputs=self.resolved.binding_spec.binding_inputs,
            )
            value = factory(provider_context)
            if inspect.isawaitable(value):
                value = await value
            if not isinstance(value, CapabilityBundleValue):
                raise TypeError(
                    "Component factory must return a CapabilityBundleValue"
                )
            self.disposer = disposer
            if set(value.facet_ids) != set(self.resolved.admission.effective_facets):
                await self._dispose_value(value, disposer=disposer)
                self.disposer = None
                raise ValueError("Component factory returned unexpected facets")
            return value
        except BaseException:
            self._try_fail_active_use()
            raise

    async def dispose(self, value: CapabilityBundleValue) -> None:
        disposer = self.disposer
        self.disposer = None
        await self._dispose_value(value, disposer=disposer)

    def cancel_before_start(self) -> bool:
        if self.reservation.state != "CONSUMED_NOT_STARTED":
            return False
        self._transition(
            "CONSUMED_NOT_STARTED",
            "CANCELLED_BEFORE_START",
        )
        return True

    def commit_after_graph_publication(self) -> None:
        if self.reservation.state != "STARTED":
            _raise_host(
                "component_activation_not_started",
                "Component activation cannot commit before successful construction.",
            )
        self._transition("STARTED", "COMMITTED")

    def abort_uncommitted(self) -> bool:
        if self.reservation.state == "CONSUMED_NOT_STARTED":
            self._transition(
                "CONSUMED_NOT_STARTED",
                "CANCELLED_BEFORE_START",
            )
            return True
        if self.reservation.state == "STARTING":
            self._transition("STARTING", "FAILED")
            return True
        if self.reservation.state == "STARTED":
            self._transition("STARTED", "FAILED")
            return True
        return False

    def _load_symbols(
        self,
    ) -> tuple[CapabilityProviderFactory, CapabilityProviderDisposer | None]:
        spec = self.resolved.binding_spec
        factory_module = self._load_module(spec.factory, suffix="factory")
        factory = factory_module.resolve(spec.factory.symbol)
        if not callable(factory):
            raise TypeError("Component Provider factory symbol must be callable")
        disposer: object | None = None
        if spec.disposer is not None:
            disposer_module = (
                factory_module
                if spec.disposer.path == spec.factory.path
                else self._load_module(spec.disposer, suffix="disposer")
            )
            disposer = disposer_module.resolve(spec.disposer.symbol)
            if not callable(disposer):
                raise TypeError("Component Provider disposer symbol must be callable")
        return (
            cast(CapabilityProviderFactory, factory),
            cast(CapabilityProviderDisposer | None, disposer),
        )

    def _load_module(
        self,
        locator: CapabilityProviderSymbolLocator,
        *,
        suffix: str,
    ) -> VerifiedPluginPythonModule:
        return load_verified_plugin_python_module(
            revision_handle=self.package.revision_handle,
            dependency_lock=self.package.dependency_lock,
            relative_path=locator.path,
            module_name=(
                "_loushang_plugin_component_"
                + self.reservation.activation_use_id[:16]
                + f"_{suffix}"
            ),
            host_api_prefixes=_PROVIDER_HOST_API_PREFIXES,
        )

    async def _dispose_value(
        self,
        value: CapabilityBundleValue,
        *,
        disposer: CapabilityProviderDisposer | None,
    ) -> None:
        if disposer is None:
            return
        result = disposer(value)
        if inspect.isawaitable(result):
            await result

    def _transition(
        self,
        expected_state: PluginActivationUseState,
        target_state: PluginActivationUseState,
    ) -> None:
        for _ in range(_MAX_JOURNAL_CAS_ATTEMPTS):
            revision = self.journal.snapshot().journal_revision
            try:
                self.reservation = self.journal.transition_activation_use(
                    self.reservation.activation_use_id,
                    expected_state=expected_state,
                    target_state=target_state,
                    host_boot_id=self.host_boot_id,
                    import_realm_id=self.import_realm.import_realm_id,
                    transitioned_at_unix_ms=self.clock(),
                    expected_journal_revision=revision,
                )
                return
            except PluginActivationJournalError as exc:
                if exc.code != "plugin_activation_journal_revision_conflict":
                    raise CapabilityComponentHostError(
                        "Component activation state transition was rejected.",
                        code=exc.code,
                    ) from exc
        _raise_host(
            "plugin_activation_journal_contention",
            "Component activation journal remained contended.",
        )

    def _try_transition(
        self,
        expected_state: PluginActivationUseState,
        target_state: PluginActivationUseState,
    ) -> None:
        with suppress(Exception):
            self._transition(expected_state, target_state)

    def _try_fail_active_use(self) -> None:
        if self.reservation.state == "STARTING":
            self._try_transition("STARTING", "FAILED")
        elif self.reservation.state == "STARTED":
            self._try_transition("STARTED", "FAILED")


def _validate_current_authorities(
    resolved: ResolvedCapabilityProvider,
    *,
    owner_snapshot: CapabilityProviderOwnerSnapshot,
    trust_snapshot: PluginSourceTrustSnapshotV1,
) -> None:
    if not isinstance(resolved, ResolvedCapabilityProvider):
        raise TypeError("Component Host requires a resolved Capability Provider")
    if not isinstance(owner_snapshot, CapabilityProviderOwnerSnapshot):
        raise TypeError("Component Host requires a Capability owner snapshot")
    if not isinstance(trust_snapshot, PluginSourceTrustSnapshotV1):
        raise TypeError("Component Host requires a Plugin trust snapshot")
    admission = resolved.admission
    candidate = admission.candidate
    if (
        owner_snapshot.capability_id != resolved.capability_id
        or owner_snapshot.owner_id != resolved.definition.owner_id
        or owner_snapshot.policy_revision != admission.owner_policy_revision
        or owner_snapshot.revocation_epoch != admission.revocation_epoch
    ):
        _raise_host(
            "capability_provider_owner_authority_stale",
            "Current Capability owner authority does not match admission.",
        )
    if (
        not trust_snapshot.trusted
        or trust_snapshot.plugin_id != resolved.binding_spec.plugin_id
        or trust_snapshot.package_source_identity
        != candidate.package_source_identity
        or trust_snapshot.source_trust_class != candidate.source_trust_class
        or trust_snapshot.source_trust_policy_revision
        != candidate.source_trust_policy_revision
    ):
        _raise_host(
            "capability_provider_source_trust_stale",
            "Current Plugin source trust does not match admission.",
        )


def _validate_package(
    resolved: ResolvedCapabilityProvider,
    package: PublishedPluginPackage,
) -> None:
    if not isinstance(package, PublishedPluginPackage):
        raise TypeError("Component Host requires a published Plugin package")
    spec = resolved.binding_spec
    if (
        package.manifest.name != spec.plugin_id
        or package.content_digest != spec.package_content_digest
        or package.dependency_lock.digest != spec.dependency_lock_digest
    ):
        _raise_host(
            "capability_provider_package_mismatch",
            "Published Plugin package does not match the selected binding spec.",
        )


def _require_hex(value: object, *, length: int, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be {length} lowercase hexadecimal characters")


def _raise_host(code: str, message: str) -> Never:
    raise CapabilityComponentHostError(message, code=code)


@dataclass(frozen=True, slots=True)
class PreparedCapabilityComponent:
    """One lazy Binder input with explicit unstarted-reservation cancellation."""

    binding: CapabilityBundleProviderBinding
    _attempt: _PreparedComponentAttempt = field(
        repr=False,
        compare=False,
    )

    def cancel_before_start(self) -> bool:
        return self._attempt.cancel_before_start()

    def commit_after_graph_publication(self) -> None:
        self._attempt.commit_after_graph_publication()

    def abort_uncommitted(self) -> bool:
        return self._attempt.abort_uncommitted()


__all__ = [
    "CapabilityComponentHost",
    "CapabilityComponentHostError",
    "PreparedCapabilityComponent",
]
