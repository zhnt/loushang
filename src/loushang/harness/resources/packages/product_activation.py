"""PLC9A2 Product activation over the accepted PLC9B package router.

The activation owns no acquisition, publication, desired-state, or retention
capability. It freezes startup recovery and epoch admission before exposing a
single pathless routing port to Product transports.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from hashlib import sha256
from threading import Lock
from typing import Protocol, TypeVar, cast

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionReceiptV1,
    PackageEpochRuntimeAdmissionRequestV1,
    PackageEpochRuntimeAdmissionResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleIngressRequestV1,
    PackageLifecycleIngressRequestV2,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.product_contract import (
    PACKAGE_PRODUCT_EVIDENCE_VERSION,
    PACKAGE_PRODUCT_INTENT_VERSION,
    PACKAGE_PRODUCT_OUTCOME_VERSION,
    PACKAGE_PRODUCT_RECORD_VERSION,
    PackageProductClassificationDecision,
    PackageProductEntrypoint,
    PackageProductLifecycleDisposition,
    PackageProductLifecycleEvidenceV1,
    PackageProductLifecycleIntentV1,
    PackageProductLifecycleOperationPort,
    PackageProductLifecycleOutcomeV1,
    PackageProductLifecyclePhase,
    PackageProductLifecycleRecordV1,
    PackageProductRoutingDisposition,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductLifecycleRouter,
    PackageProductRouteRequestV1,
)

PACKAGE_PRODUCT_ACTIVATION_VERSION = 1
T = TypeVar("T")


class PackageProductActivationError(RuntimeError):
    """Fail-closed Product activation or routing failure with a stable code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageProductIngressFactoryPort(Protocol):
    """Product policy owner that creates unclassified PLC9B ingress."""

    def create(
        self,
        intent: PackageProductLifecycleIntentV1,
    ) -> PackageLifecycleIngressRequestV1: ...

    def scope_id(self, intent: PackageProductLifecycleIntentV1) -> str: ...


class PackageProductRecoveryPort(Protocol):
    """One durable owner that must recover before Product activation."""

    def recover(self) -> object: ...


class PackageProductEpochTransactionGuardPort(Protocol):
    """Cross-process read guard paired with cutover's exclusive quiescence."""

    def shared_runtime(
        self,
        *,
        store_id: str,
    ) -> AbstractContextManager[None]: ...


class PackageProductLifecycleActivation:
    """Recover, admit, and expose one immutable Product routing composition."""

    def __init__(
        self,
        *,
        product_id: str,
        binding_id: str,
        router: PackageProductLifecycleRouter,
        ingress_factory: PackageProductIngressFactoryPort,
        runtime_admission: PackageEpochRuntimeAdmissionOwner,
        admission_request: PackageEpochRuntimeAdmissionRequestV1,
        transaction_guard: PackageProductEpochTransactionGuardPort,
        recoveries: tuple[PackageProductRecoveryPort, ...] = (),
    ) -> None:
        if not isinstance(product_id, str) or not product_id:
            raise ValueError("Package Product id must be non-empty")
        if not isinstance(binding_id, str) or not binding_id:
            raise ValueError("Package Product binding id must be non-empty")
        if not isinstance(router, PackageProductLifecycleRouter):
            raise TypeError("Package Product lifecycle router is required")
        if not callable(getattr(ingress_factory, "create", None)) or not callable(
            getattr(ingress_factory, "scope_id", None)
        ):
            raise TypeError("Package Product ingress factory is required")
        if not isinstance(runtime_admission, PackageEpochRuntimeAdmissionOwner):
            raise TypeError("Package runtime admission owner is required")
        if not isinstance(admission_request, PackageEpochRuntimeAdmissionRequestV1):
            raise TypeError("Package runtime admission request is required")
        if not callable(getattr(transaction_guard, "shared_runtime", None)):
            raise TypeError("Package Product epoch transaction guard is required")
        if any(not callable(getattr(item, "recover", None)) for item in recoveries):
            raise TypeError("Package Product recovery owner is invalid")
        self._product_id = product_id
        self._binding_id = binding_id
        self._router = router
        self._ingress_factory = ingress_factory
        self._runtime_admission = runtime_admission
        self._admission_request = admission_request
        self._transaction_guard = transaction_guard
        self._recoveries = tuple(recoveries)
        self._receipt: PackageEpochRuntimeAdmissionReceiptV1 | None = None
        self._lock = Lock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._receipt is not None

    @property
    def binding_id(self) -> str:
        return self._binding_id

    def activate(self) -> PackageEpochRuntimeAdmissionReceiptV1:
        """Recover every owner, then atomically expose the admitted composition."""

        with self._lock:
            if self._receipt is not None:
                return self._receipt
            for recovery in self._recoveries:
                recovery.recover()
            receipt = self._admit()
            self._receipt = receipt
            return receipt

    def route(
        self,
        intent: PackageProductLifecycleIntentV1,
        *,
        entrypoint: PackageProductEntrypoint,
    ) -> PackageProductLifecycleOutcomeV1:
        if not isinstance(intent, PackageProductLifecycleIntentV1):
            raise TypeError("Package Product lifecycle intent is required")
        with self._lock:
            active = self._receipt is not None
        if not active:
            raise PackageProductActivationError(
                "Package Product lifecycle has not completed startup admission",
                code="package_product_activation_required",
            )
        try:
            guard = self._transaction_guard.shared_runtime(
                store_id=self._admission_request.store_id
            )
            with guard:
                # Cutover cannot enter its exclusive quiescence while this guard
                # is held. Admission and every transaction side effect therefore
                # belong to the same epoch.
                receipt = self._admit()
                with self._lock:
                    self._receipt = receipt
                return self._route_guarded(
                    intent,
                    entrypoint=entrypoint,
                    receipt=receipt,
                )
        except BaseException:
            with self._lock:
                self._receipt = None
            raise

    async def execute_guarded_query(
        self,
        query: Callable[[], Awaitable[T]],
    ) -> T:
        """Run one Product inventory query under the admitted runtime epoch."""

        if not callable(query):
            raise TypeError("Package Product guarded query is required")
        with self._lock:
            active = self._receipt is not None
        if not active:
            raise PackageProductActivationError(
                "Package Product lifecycle has not completed startup admission",
                code="package_product_activation_required",
            )
        try:
            guard = self._transaction_guard.shared_runtime(
                store_id=self._admission_request.store_id
            )
            with guard:
                receipt = self._admit()
                with self._lock:
                    self._receipt = receipt
                return await query()
        except BaseException:
            with self._lock:
                self._receipt = None
            raise

    def _route_guarded(
        self,
        intent: PackageProductLifecycleIntentV1,
        *,
        entrypoint: PackageProductEntrypoint,
        receipt: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageProductLifecycleOutcomeV1:
        ingress = self._ingress_factory.create(intent)
        if not isinstance(ingress, PackageLifecycleIngressRequestV1):
            raise PackageProductActivationError(
                "Package Product ingress factory returned an invalid request",
                code="package_product_ingress_invalid",
            )
        expected_scope_id = self._ingress_factory.scope_id(intent)
        if not isinstance(expected_scope_id, str) or not expected_scope_id:
            raise PackageProductActivationError(
                "Package Product scope binding is invalid",
                code="package_product_scope_invalid",
            )
        if (
            ingress.operation_id != intent.operation_id
            or ingress.action != intent.action
            or ingress.source_locator != intent.source
            or ingress.product_id != self._product_id
            or ingress.scope_id != expected_scope_id
        ):
            raise PackageProductActivationError(
                "Package Product ingress changed the caller intent",
                code="package_product_ingress_changed",
            )
        try:
            bound_ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
                ingress,
                runtime_admission_request_id=(
                    receipt.request.admission_request_id
                ),
            )
        except ValueError:
            raise PackageProductActivationError(
                "Package Product ingress changed runtime admission identity",
                code="package_product_ingress_changed",
            ) from None
        ingress = bound_ingress
        status = self._router.route(
            PackageProductRouteRequestV1(
                entrypoint=entrypoint,
                ingress=ingress,
                admission=receipt,
            )
        )
        classification = status.classification
        if classification is None:
            raise PackageProductActivationError(
                "Package Product route returned no classification",
                code="package_product_classification_missing",
            )
        evidence = _product_evidence(ingress, status)
        if classification.decision == "non_plugin":
            if status.disposition != "active" or status.phase != "classified":
                raise PackageProductActivationError(
                    "Non-Plugin route did not retain classified evidence",
                    code="package_product_non_plugin_invalid",
                )
            return PackageProductLifecycleOutcomeV1(
                routing_disposition="non_plugin",
                evidence=evidence,
                record=None,
            )
        if status.disposition == "active":
            raise PackageProductActivationError(
                "Plugin Package transaction remained active",
                code="package_product_transaction_incomplete",
            )
        return PackageProductLifecycleOutcomeV1(
            routing_disposition="plugin_handled",
            evidence=evidence,
            record=PackageProductLifecycleRecordV1.from_evidence(intent, evidence),
        )

    def _admit(self) -> PackageEpochRuntimeAdmissionReceiptV1:
        result = self._runtime_admission.admit(self._admission_request)
        if not isinstance(result, PackageEpochRuntimeAdmissionResultV1):
            raise PackageProductActivationError(
                "Package runtime admission returned an invalid result",
                code="package_product_runtime_admission_invalid",
            )
        if result.disposition != "admitted" or result.receipt is None:
            raise PackageProductActivationError(
                "Package runtime epoch is not admitted",
                code="package_runtime_epoch_unsupported",
            )
        return result.receipt


def _product_evidence(
    ingress: PackageLifecycleIngressRequestV1,
    status: PackageLifecycleStatusV1,
) -> PackageProductLifecycleEvidenceV1:
    classification = status.classification
    if classification is None:
        raise PackageProductActivationError(
            "Package Product route returned no classification",
            code="package_product_classification_missing",
        )
    source_digest = sha256(
        classification.canonical_source_identity.encode("utf-8")
    ).hexdigest()
    # requested_plugin_id belongs to the untrusted ingress adapter and may be a
    # raw locator. Public evidence therefore uses an opaque stable display id.
    display_name = f"plugin-{source_digest[:12]}"
    decision = classification.decision
    if decision not in {"plugin_bound", "non_plugin", "indeterminate"}:
        raise PackageProductActivationError(
            "Package owner returned an unsupported classification",
            code="package_product_evidence_unsupported",
        )
    phase = status.phase
    if phase not in {
        "accepted",
        "classified",
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
        "transaction_pinned",
        "staging",
        "set_published",
        "committed",
    }:
        raise PackageProductActivationError(
            "Package owner returned an unsupported lifecycle phase",
            code="package_product_evidence_unsupported",
        )
    disposition = status.disposition
    if disposition not in {
        "active",
        "committed",
        "rejected",
        "retryable_failure",
        "cancelled",
    }:
        raise PackageProductActivationError(
            "Package owner returned an unsupported lifecycle disposition",
            code="package_product_evidence_unsupported",
        )
    return PackageProductLifecycleEvidenceV1(
        operation_id=status.operation_id,
        request_ref=f"sha256:{status.request_fingerprint}",
        source_ref=f"sha256:{source_digest}",
        display_name=display_name,
        classification=cast(PackageProductClassificationDecision, decision),
        phase=cast(PackageProductLifecyclePhase, phase),
        disposition=cast(PackageProductLifecycleDisposition, disposition),
        failure_code=None if status.failure is None else status.failure.code,
    )


__all__ = [
    "PACKAGE_PRODUCT_ACTIVATION_VERSION",
    "PACKAGE_PRODUCT_EVIDENCE_VERSION",
    "PACKAGE_PRODUCT_INTENT_VERSION",
    "PACKAGE_PRODUCT_OUTCOME_VERSION",
    "PACKAGE_PRODUCT_RECORD_VERSION",
    "PackageProductActivationError",
    "PackageProductEpochTransactionGuardPort",
    "PackageProductIngressFactoryPort",
    "PackageProductLifecycleActivation",
    "PackageProductLifecycleIntentV1",
    "PackageProductLifecycleOperationPort",
    "PackageProductLifecycleOutcomeV1",
    "PackageProductLifecycleRecordV1",
    "PackageProductRecoveryPort",
    "PackageProductRoutingDisposition",
]
