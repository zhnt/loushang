"""Approval-gated Host preparation for external Capability owner components."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Never, cast

from loushang.harness.approval.plugin_activation import (
    ActivationUseReservationV1,
    OwnerComponentActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationUseState,
)
from loushang.harness.capabilities._activation_host_lifecycle import (
    DurableActivationHostLifecycle,
)
from loushang.harness.capabilities.component_admission import (
    CapabilityComponentOwnerSnapshot,
)
from loushang.harness.capabilities.component_binding import (
    CapabilityOwnerComponentBinding,
    CapabilityOwnerComponentContext,
    CapabilityOwnerComponentPayloadValidator,
    CapabilityOwnerComponentValue,
    owner_component_binding_fingerprint,
)
from loushang.harness.capabilities.component_contracts import (
    CapabilityComponentDefinition,
)
from loushang.harness.capabilities.component_selection import (
    ResolvedCapabilityComponent,
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

_COMPONENT_HOST_API_PREFIXES = (
    "loushang.harness.capabilities",
    "loushang.harness.runtime",
)
_NO_PENDING_PAYLOAD = object()

_PluginComponentFactory = Callable[[CapabilityOwnerComponentContext], object]
_PluginComponentDisposer = Callable[[object], object]


class CapabilityOwnerComponentHostError(RuntimeError):
    """Stable fail-closed owner-component preparation or activation failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class CapabilityOwnerComponentHost:
    """Prepare owner-component Bindings without publishing a generation."""

    def __init__(
        self,
        *,
        decision_journal: PluginActivationDecisionJournal,
        import_realm: PluginImportRealm,
        host_boot_id: str,
        clock: Callable[[], int],
        owner_snapshot_reader: Callable[
            [str, str], CapabilityComponentOwnerSnapshot
        ],
        trust_snapshot_reader: Callable[[str, str], PluginSourceTrustSnapshotV1],
        product_policy_revision_reader: Callable[[str, str], str],
        payload_validator_reader: Callable[
            [CapabilityComponentDefinition],
            CapabilityOwnerComponentPayloadValidator,
        ],
    ) -> None:
        if not isinstance(decision_journal, PluginActivationDecisionJournal):
            raise TypeError("Owner Component Host requires an activation journal")
        if not isinstance(import_realm, PluginImportRealm):
            raise TypeError("Owner Component Host requires one import realm")
        _require_hex(host_boot_id, length=32, name="Host boot id")
        if not callable(clock):
            raise TypeError("Owner Component Host requires a durable clock")
        if not all(
            callable(item)
            for item in (
                owner_snapshot_reader,
                trust_snapshot_reader,
                product_policy_revision_reader,
                payload_validator_reader,
            )
        ):
            raise TypeError("Owner Component Host requires current authority readers")
        self._import_realm = import_realm
        self._host_boot_id = host_boot_id
        self._owner_snapshot_reader = owner_snapshot_reader
        self._trust_snapshot_reader = trust_snapshot_reader
        self._product_policy_revision_reader = product_policy_revision_reader
        self._payload_validator_reader = payload_validator_reader
        self._lifecycle = DurableActivationHostLifecycle(
            journal=decision_journal,
            host_boot_id=host_boot_id,
            import_realm_id=import_realm.import_realm_id,
            clock=clock,
            error_factory=_owner_host_error,
        )
        self._lifecycle.recover_incomplete_uses()

    def activation_subject(
        self,
        resolved: ResolvedCapabilityComponent,
        *,
        owner_snapshot: CapabilityComponentOwnerSnapshot,
        trust_snapshot: PluginSourceTrustSnapshotV1,
    ) -> OwnerComponentActivationApprovalSubject:
        self._validate_current_authorities(
            resolved,
            owner_snapshot=owner_snapshot,
            trust_snapshot=trust_snapshot,
        )
        admission = resolved.admission
        candidate = admission.candidate
        spec = candidate.binding_spec
        if (
            spec.source_kind != "plugin"
            or spec.plugin_id is None
            or spec.dependency_lock_digest is None
            or candidate.instance_revision_ref is None
            or candidate.package_source_identity is None
        ):
            _raise_host(
                "owner_component_not_external_plugin",
                "Owner Component Host only prepares exact external Plugin bindings.",
            )
        return OwnerComponentActivationApprovalSubject(
            candidate_fingerprint=candidate.fingerprint,
            admission_fingerprint=admission.fingerprint,
            resolved_component_fingerprint=resolved.fingerprint,
            binding_spec_fingerprint=spec.fingerprint,
            definition_fingerprint=resolved.definition.fingerprint,
            owner_snapshot_fingerprint=owner_snapshot.fingerprint,
            selection_plan_fingerprint=resolved.selection_plan_fingerprint,
            capability_id=resolved.definition.capability_id,
            owner_id=resolved.definition.owner_id,
            component_kind=resolved.definition.component_kind,
            component_id=resolved.component_id,
            plugin_id=spec.plugin_id,
            contribution_id=spec.contribution_id,
            package_content_digest=spec.content_digest,
            dependency_lock_digest=spec.dependency_lock_digest,
            product_id=candidate.product_id,
            scope_id=candidate.scope_id,
            instance_revision_ref=candidate.instance_revision_ref,
            package_source_identity=candidate.package_source_identity,
            source_trust_class=trust_snapshot.source_trust_class,
            source_trust_policy_revision=(
                trust_snapshot.source_trust_policy_revision
            ),
            product_policy_revision=candidate.product_policy_revision,
            owner_policy_revision=owner_snapshot.policy_revision,
            revocation_epoch=owner_snapshot.revocation_epoch,
            effective_authorities=admission.effective_authorities,
            execution_model="in_process",
        )

    def prepare_component(
        self,
        resolved: ResolvedCapabilityComponent,
        *,
        package: PublishedPluginPackage,
        owner_snapshot: CapabilityComponentOwnerSnapshot,
        trust_snapshot: PluginSourceTrustSnapshotV1,
        decision_id: str,
    ) -> PreparedCapabilityOwnerComponent:
        """Consume approval while deferring import and construction to Binder."""

        subject = self.activation_subject(
            resolved,
            owner_snapshot=owner_snapshot,
            trust_snapshot=trust_snapshot,
        )
        _validate_package(resolved, package)
        definition = resolved.definition
        spec = resolved.admission.candidate.binding_spec
        if definition.disposer_contract == "required" and spec.disposer_path is None:
            _raise_host(
                "owner_component_disposer_missing",
                "Owner Component Definition requires an external disposer.",
            )
        now = self._now()
        admission = resolved.admission
        if now < admission.issued_at or now >= admission.expires_at:
            _raise_host(
                "capability_component_admission_not_current",
                "Selected owner-component admission is not current.",
            )
        package.revision_handle.verify()
        try:
            self._import_realm.preflight(
                host_boot_id=self._host_boot_id,
                package_namespace=subject.plugin_id,
                dependency_lock=package.dependency_lock,
            )
        except Exception as exc:
            raise CapabilityOwnerComponentHostError(
                "Plugin import realm rejected owner-component preparation.",
                code=getattr(exc, "code", "plugin_import_realm_rejected"),
            ) from exc
        payload_validator = self._payload_validator_reader(definition)
        if not callable(payload_validator):
            raise TypeError("Component owner payload validator must be callable")
        reservation = self._consume(subject, decision_id=decision_id)
        attempt = _PreparedOwnerComponentAttempt(
            resolved=resolved,
            package=package,
            reservation=reservation,
            import_realm=self._import_realm,
            lifecycle=self._lifecycle,
            validate_current_authorities=lambda: self._validate_current_authorities(
                resolved,
                owner_snapshot=owner_snapshot,
                trust_snapshot=trust_snapshot,
            ),
        )
        binding = CapabilityOwnerComponentBinding(
            resolved=resolved,
            binding_fingerprint=owner_component_binding_fingerprint(resolved),
            create=attempt.create,
            validate_payload=payload_validator,
            dispose=attempt.dispose,
        )
        return PreparedCapabilityOwnerComponent(binding=binding, _attempt=attempt)

    def _consume(
        self,
        subject: OwnerComponentActivationApprovalSubject,
        *,
        decision_id: str,
    ) -> ActivationUseReservationV1:
        return self._lifecycle.consume(subject, decision_id=decision_id)

    def _now(self) -> int:
        return self._lifecycle.now()

    def _validate_current_authorities(
        self,
        resolved: ResolvedCapabilityComponent,
        *,
        owner_snapshot: CapabilityComponentOwnerSnapshot,
        trust_snapshot: PluginSourceTrustSnapshotV1,
    ) -> None:
        _validate_current_authorities(
            resolved,
            owner_snapshot=owner_snapshot,
            trust_snapshot=trust_snapshot,
        )
        candidate = resolved.admission.candidate
        spec = candidate.binding_spec
        assert spec.plugin_id is not None
        assert candidate.package_source_identity is not None
        current_owner = self._owner_snapshot_reader(
            resolved.definition.capability_id,
            resolved.definition.component_kind,
        )
        current_trust = self._trust_snapshot_reader(
            spec.plugin_id,
            candidate.package_source_identity,
        )
        current_product_policy_revision = self._product_policy_revision_reader(
            candidate.product_id,
            candidate.scope_id,
        )
        if current_owner != owner_snapshot:
            _raise_host(
                "capability_component_owner_authority_stale",
                "Current component owner authority changed after selection.",
            )
        if current_trust != trust_snapshot:
            _raise_host(
                "capability_component_source_trust_stale",
                "Current Plugin source trust changed after selection.",
            )
        if current_product_policy_revision != candidate.product_policy_revision:
            _raise_host(
                "capability_component_product_policy_stale",
                "Current Product policy changed after component selection.",
            )

@dataclass(slots=True)
class _PreparedOwnerComponentAttempt:
    resolved: ResolvedCapabilityComponent
    package: PublishedPluginPackage
    reservation: ActivationUseReservationV1
    import_realm: PluginImportRealm
    lifecycle: DurableActivationHostLifecycle
    validate_current_authorities: Callable[[], None] = field(repr=False)
    started: bool = False
    disposer: _PluginComponentDisposer | None = None
    pending_payload: object = _NO_PENDING_PAYLOAD

    async def create(self, context: CapabilityOwnerComponentContext) -> object:
        if self.started:
            _raise_host(
                "owner_component_activation_use_consumed",
                "Prepared owner-component binding is single-use.",
            )
        self.validate_current_authorities()
        now = self.lifecycle.now()
        admission = self.resolved.admission
        if now < admission.issued_at or now >= admission.expires_at:
            _raise_host(
                "capability_component_admission_not_current",
                "Selected owner-component admission expired before start.",
            )
        self.lifecycle.validate_current(
            self.reservation,
            expected_state="CONSUMED_NOT_STARTED",
        )
        self.started = True
        spec = self.resolved.admission.candidate.binding_spec
        assert spec.plugin_id is not None
        try:
            lease = self.import_realm.reserve(
                host_boot_id=self.lifecycle.host_boot_id,
                execution_use_id=self.reservation.activation_use_id,
                package_namespace=spec.plugin_id,
                dependency_lock=self.package.dependency_lock,
            )
        except BaseException:
            self._try_transition(
                "CONSUMED_NOT_STARTED",
                "CANCELLED_BEFORE_START",
            )
            raise
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
            factory, disposer = self.import_realm.execute(lease, self._load_symbols)
            self.import_realm.commit(lease)
            self.disposer = disposer
            payload = factory(context)
            if inspect.isawaitable(payload):
                payload = await payload
            self.pending_payload = payload
            self._transition("STARTING", "STARTED")
            return payload
        except BaseException:
            try:
                if self.pending_payload is not _NO_PENDING_PAYLOAD:
                    await self._dispose_pending_payload()
            finally:
                self._try_fail_active_use()
            raise

    async def dispose(self, value: CapabilityOwnerComponentValue) -> None:
        await self._dispose_payload(value.payload, disposer=self.disposer)
        if self.pending_payload is value.payload:
            self.pending_payload = _NO_PENDING_PAYLOAD
        if self.reservation.state == "STARTED":
            self._transition("STARTED", "FAILED")

    def cancel_before_start(self) -> bool:
        if self.reservation.state != "CONSUMED_NOT_STARTED":
            return False
        self._transition("CONSUMED_NOT_STARTED", "CANCELLED_BEFORE_START")
        return True

    def commit_after_owner_generation_publication(self) -> None:
        if self.reservation.state != "STARTED":
            _raise_host(
                "owner_component_activation_not_started",
                "Owner-component activation cannot commit before construction.",
            )
        self._transition("STARTED", "COMMITTED")
        self.pending_payload = _NO_PENDING_PAYLOAD

    async def abort_uncommitted(self) -> bool:
        cleaned_pending_payload = False
        if self.pending_payload is not _NO_PENDING_PAYLOAD:
            await self._dispose_pending_payload()
            cleaned_pending_payload = True
        if self.reservation.state == "CONSUMED_NOT_STARTED":
            self._transition("CONSUMED_NOT_STARTED", "CANCELLED_BEFORE_START")
            return True
        if self.reservation.state == "STARTING":
            self._transition("STARTING", "FAILED")
            return True
        if self.reservation.state == "STARTED":
            self._transition("STARTED", "FAILED")
            return True
        return cleaned_pending_payload

    async def _dispose_pending_payload(self) -> None:
        payload = self.pending_payload
        if payload is _NO_PENDING_PAYLOAD:
            return
        await self._dispose_payload(payload, disposer=self.disposer)
        self.pending_payload = _NO_PENDING_PAYLOAD

    def _load_symbols(
        self,
    ) -> tuple[_PluginComponentFactory, _PluginComponentDisposer | None]:
        spec = self.resolved.admission.candidate.binding_spec
        assert spec.factory_path is not None
        assert spec.factory_symbol is not None
        factory_module = self._load_module(spec.factory_path, suffix="factory")
        factory = factory_module.resolve(spec.factory_symbol)
        if not callable(factory):
            raise TypeError("Owner-component factory symbol must be callable")
        disposer: object | None = None
        if spec.disposer_path is not None:
            assert spec.disposer_symbol is not None
            disposer_module = (
                factory_module
                if spec.disposer_path == spec.factory_path
                else self._load_module(spec.disposer_path, suffix="disposer")
            )
            disposer = disposer_module.resolve(spec.disposer_symbol)
            if not callable(disposer):
                raise TypeError("Owner-component disposer symbol must be callable")
        return (
            cast(_PluginComponentFactory, factory),
            cast(_PluginComponentDisposer | None, disposer),
        )

    def _load_module(self, relative_path: str, *, suffix: str) -> VerifiedPluginPythonModule:
        return load_verified_plugin_python_module(
            revision_handle=self.package.revision_handle,
            dependency_lock=self.package.dependency_lock,
            relative_path=relative_path,
            module_name=(
                "_loushang_plugin_owner_component_"
                + self.reservation.activation_use_id[:16]
                + f"_{suffix}"
            ),
            host_api_prefixes=_COMPONENT_HOST_API_PREFIXES,
        )

    @staticmethod
    async def _dispose_payload(
        payload: object,
        *,
        disposer: _PluginComponentDisposer | None,
    ) -> None:
        if disposer is None:
            return
        result = disposer(payload)
        if inspect.isawaitable(result):
            await result

    def _transition(
        self,
        expected_state: PluginActivationUseState,
        target_state: PluginActivationUseState,
    ) -> None:
        self.reservation = self.lifecycle.transition(
            self.reservation,
            expected_state=expected_state,
            target_state=target_state,
        )

    def _try_transition(
        self,
        expected_state: PluginActivationUseState,
        target_state: PluginActivationUseState,
    ) -> None:
        self.reservation = self.lifecycle.try_transition(
            self.reservation,
            expected_state=expected_state,
            target_state=target_state,
        )

    def _try_fail_active_use(self) -> None:
        if self.reservation.state == "STARTING":
            self._try_transition("STARTING", "FAILED")
        elif self.reservation.state == "STARTED":
            self._try_transition("STARTED", "FAILED")


def _validate_current_authorities(
    resolved: ResolvedCapabilityComponent,
    *,
    owner_snapshot: CapabilityComponentOwnerSnapshot,
    trust_snapshot: PluginSourceTrustSnapshotV1,
) -> None:
    if not isinstance(resolved, ResolvedCapabilityComponent):
        raise TypeError("Owner Component Host requires a resolved component")
    if not isinstance(owner_snapshot, CapabilityComponentOwnerSnapshot):
        raise TypeError("Owner Component Host requires an owner snapshot")
    if not isinstance(trust_snapshot, PluginSourceTrustSnapshotV1):
        raise TypeError("Owner Component Host requires a Plugin trust snapshot")
    admission = resolved.admission
    candidate = admission.candidate
    spec = candidate.binding_spec
    if spec.source_kind != "plugin" or spec.plugin_id is None:
        _raise_host(
            "owner_component_not_external_plugin",
            "Owner Component Host requires an external Plugin component.",
        )
    if (
        owner_snapshot.capability_id != resolved.definition.capability_id
        or owner_snapshot.owner_id != resolved.definition.owner_id
        or owner_snapshot.component_kind != resolved.definition.component_kind
        or owner_snapshot.definition_fingerprint != resolved.definition.fingerprint
        or owner_snapshot.fingerprint != resolved.owner_snapshot_fingerprint
        or owner_snapshot.fingerprint != admission.owner_snapshot_fingerprint
        or owner_snapshot.policy_revision != admission.owner_policy_revision
        or owner_snapshot.revocation_epoch != admission.revocation_epoch
    ):
        _raise_host(
            "capability_component_owner_authority_stale",
            "Current component owner authority does not match selection.",
        )
    if (
        candidate.package_source_identity is None
        or not trust_snapshot.trusted
        or trust_snapshot.plugin_id != spec.plugin_id
        or trust_snapshot.package_source_identity
        != candidate.package_source_identity
        or trust_snapshot.source_trust_class != candidate.source_trust_class
        or trust_snapshot.source_trust_policy_revision
        != candidate.source_trust_policy_revision
    ):
        _raise_host(
            "capability_component_source_trust_stale",
            "Current Plugin source trust does not match component admission.",
        )


def _validate_package(
    resolved: ResolvedCapabilityComponent,
    package: PublishedPluginPackage,
) -> None:
    if not isinstance(package, PublishedPluginPackage):
        raise TypeError("Owner Component Host requires a published Plugin package")
    spec = resolved.admission.candidate.binding_spec
    if (
        spec.plugin_id is None
        or spec.dependency_lock_digest is None
        or package.manifest.name != spec.plugin_id
        or package.content_digest != spec.content_digest
        or package.dependency_lock.digest != spec.dependency_lock_digest
    ):
        _raise_host(
            "capability_component_package_mismatch",
            "Published Plugin package does not match the component binding spec.",
        )


def _require_hex(value: object, *, length: int, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be {length} lowercase hexadecimal characters")


def _raise_host(code: str, message: str) -> Never:
    raise CapabilityOwnerComponentHostError(message, code=code)


def _owner_host_error(message: str, code: str) -> RuntimeError:
    return CapabilityOwnerComponentHostError(message, code=code)


@dataclass(frozen=True, slots=True)
class PreparedCapabilityOwnerComponent:
    """One lazy owner-component Binding and its durable activation attempt."""

    binding: CapabilityOwnerComponentBinding
    _attempt: _PreparedOwnerComponentAttempt = field(repr=False, compare=False)

    def cancel_before_start(self) -> bool:
        return self._attempt.cancel_before_start()

    def commit_after_owner_generation_publication(self) -> None:
        self._attempt.commit_after_owner_generation_publication()

    async def abort_uncommitted(self) -> bool:
        return await self._attempt.abort_uncommitted()


__all__ = [
    "CapabilityOwnerComponentHost",
    "CapabilityOwnerComponentHostError",
    "PreparedCapabilityOwnerComponent",
]
