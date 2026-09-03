"""PLC9A2 Product activation over the accepted PLC9B package router.

The activation owns no acquisition, publication, desired-state, or retention
capability.  It freezes startup recovery and epoch admission before exposing a
single pathless routing port to Product transports.
"""

from __future__ import annotations

from threading import Lock
from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionReceiptV1,
    PackageEpochRuntimeAdmissionRequestV1,
    PackageEpochRuntimeAdmissionResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleIngressRequestV1,
)
from loushang.harness.resources.packages.product_contract import (
    PACKAGE_PRODUCT_INTENT_VERSION,
    PACKAGE_PRODUCT_OUTCOME_VERSION,
    PACKAGE_PRODUCT_RECORD_VERSION,
    PackageProductEntrypoint,
    PackageProductLifecycleIntentV1,
    PackageProductLifecycleOperationPort,
    PackageProductLifecycleOutcomeV1,
    PackageProductLifecycleRecordV1,
    PackageProductRoutingDisposition,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductLifecycleRouter,
    PackageProductRouteRequestV1,
)

PACKAGE_PRODUCT_ACTIVATION_VERSION = 1


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


class PackageProductRecoveryPort(Protocol):
    """One durable owner that must recover before Product activation."""

    def recover(self) -> object: ...


class PackageProductLifecycleActivation:
    """Recover, admit, and expose one immutable Product routing composition."""

    def __init__(
        self,
        *,
        product_id: str,
        router: PackageProductLifecycleRouter,
        ingress_factory: PackageProductIngressFactoryPort,
        runtime_admission: PackageEpochRuntimeAdmissionOwner,
        admission_request: PackageEpochRuntimeAdmissionRequestV1,
        recoveries: tuple[PackageProductRecoveryPort, ...] = (),
    ) -> None:
        if not isinstance(product_id, str) or not product_id:
            raise ValueError("Package Product id must be non-empty")
        if not isinstance(router, PackageProductLifecycleRouter):
            raise TypeError("Package Product lifecycle router is required")
        if not callable(getattr(ingress_factory, "create", None)):
            raise TypeError("Package Product ingress factory is required")
        if not isinstance(runtime_admission, PackageEpochRuntimeAdmissionOwner):
            raise TypeError("Package runtime admission owner is required")
        if not isinstance(admission_request, PackageEpochRuntimeAdmissionRequestV1):
            raise TypeError("Package runtime admission request is required")
        if any(not callable(getattr(item, "recover", None)) for item in recoveries):
            raise TypeError("Package Product recovery owner is invalid")
        self._product_id = product_id
        self._router = router
        self._ingress_factory = ingress_factory
        self._runtime_admission = runtime_admission
        self._admission_request = admission_request
        self._recoveries = tuple(recoveries)
        self._receipt: PackageEpochRuntimeAdmissionReceiptV1 | None = None
        self._lock = Lock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._receipt is not None

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
            if self._receipt is None:
                raise PackageProductActivationError(
                    "Package Product lifecycle has not completed startup admission",
                    code="package_product_activation_required",
                )
            # Admission is read-only and repeated immediately before routing so a
            # changed epoch or mixed active lease cannot fall through to legacy.
            try:
                receipt = self._admit()
            except Exception:
                self._receipt = None
                raise
            self._receipt = receipt
        ingress = self._ingress_factory.create(intent)
        if not isinstance(ingress, PackageLifecycleIngressRequestV1):
            raise PackageProductActivationError(
                "Package Product ingress factory returned an invalid request",
                code="package_product_ingress_invalid",
            )
        if (
            ingress.operation_id != intent.operation_id
            or ingress.action != intent.action
            or ingress.source_locator != intent.source
            or ingress.product_id != self._product_id
        ):
            raise PackageProductActivationError(
                "Package Product ingress changed the caller intent",
                code="package_product_ingress_changed",
            )
        status = self._router.route(
            PackageProductRouteRequestV1(entrypoint=entrypoint, ingress=ingress)
        )
        classification = status.classification
        if classification is None:
            raise PackageProductActivationError(
                "Package Product route returned no classification",
                code="package_product_classification_missing",
            )
        if classification.decision == "non_plugin":
            if status.disposition != "active" or status.phase != "classified":
                raise PackageProductActivationError(
                    "Non-Plugin route did not retain classified evidence",
                    code="package_product_non_plugin_invalid",
                )
            return PackageProductLifecycleOutcomeV1(
                routing_disposition="non_plugin",
                status=status,
                record=None,
            )
        return PackageProductLifecycleOutcomeV1(
            routing_disposition="plugin_handled",
            status=status,
            record=PackageProductLifecycleRecordV1.from_status(intent, status),
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


__all__ = [
    "PACKAGE_PRODUCT_ACTIVATION_VERSION",
    "PACKAGE_PRODUCT_INTENT_VERSION",
    "PACKAGE_PRODUCT_OUTCOME_VERSION",
    "PACKAGE_PRODUCT_RECORD_VERSION",
    "PackageProductActivationError",
    "PackageProductIngressFactoryPort",
    "PackageProductLifecycleActivation",
    "PackageProductLifecycleIntentV1",
    "PackageProductLifecycleOperationPort",
    "PackageProductLifecycleOutcomeV1",
    "PackageProductLifecycleRecordV1",
    "PackageProductRecoveryPort",
    "PackageProductRoutingDisposition",
]
