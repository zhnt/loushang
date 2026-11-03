"""PLC9A2 Product activation over the accepted PLC9B package router.

The activation owns no acquisition, publication, desired-state, or retention
capability. It freezes startup recovery and epoch admission before exposing a
single pathless routing port to Product transports.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from typing import Literal, Protocol, TypeVar, cast

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
    PackageProductLifecycleRetryIntentV1,
    PackageProductRoutingDisposition,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductLifecycleRouter,
    PackageProductPinnedAdoptedRouteRequestV1,
    PackageProductReboundRouteRequestV1,
    PackageProductRouteRequestV1,
    PackageProductStagingAdoptedRouteRequestV1,
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


class PackageProductAdmittedRecoveryPort(Protocol):
    """Recovery that mutates Product state only under the admitted epoch."""

    def recover(self, admission: PackageEpochRuntimeAdmissionReceiptV1) -> object: ...


@dataclass(frozen=True, slots=True)
class PackageProductExactHandoffRecoveryV1:
    operation_id: str
    retained_handoff_ids: tuple[str, ...]
    committed_operation_ids: tuple[str, ...]
    terminal_state: Literal["settled", "aborted"]

    def __post_init__(self) -> None:
        if (
            type(self.operation_id) is not str
            or not self.operation_id
            or type(self.retained_handoff_ids) is not tuple
            or type(self.committed_operation_ids) is not tuple
            or any(
                type(value) is not str or not value
                for value in self.retained_handoff_ids
            )
            or self.committed_operation_ids not in {(), (self.operation_id,)}
            or self.terminal_state not in {"settled", "aborted"}
        ):
            raise ValueError("Exact Package handoff recovery result is invalid")

    @property
    def changed(self) -> bool:
        return bool(self.retained_handoff_ids or self.committed_operation_ids)


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
        admitted_recoveries: tuple[PackageProductAdmittedRecoveryPort, ...] = (),
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
        if any(
            not callable(getattr(item, "recover", None)) for item in admitted_recoveries
        ):
            raise TypeError("Package Product admitted recovery owner is invalid")
        self._product_id = product_id
        self._binding_id = binding_id
        self._router = router
        self._ingress_factory = ingress_factory
        self._runtime_admission = runtime_admission
        self._admission_request = admission_request
        self._transaction_guard = transaction_guard
        self._recoveries = tuple(recoveries)
        self._admitted_recoveries = tuple(admitted_recoveries)
        self._receipt: PackageEpochRuntimeAdmissionReceiptV1 | None = None
        self._exact_recovery_used = False
        self._lock = Lock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._receipt is not None

    @property
    def binding_id(self) -> str:
        return self._binding_id

    def activate(self) -> PackageEpochRuntimeAdmissionReceiptV1:
        """Admit, recover, and publish under one guarded runtime epoch."""

        with self._lock:
            if self._receipt is not None:
                return self._receipt
            if self._exact_recovery_used:
                raise PackageProductActivationError(
                    "Exact handoff recovery runtime cannot activate general routing",
                    code="package_product_exact_recovery_consumed",
                )
            with self._transaction_guard.shared_runtime(
                store_id=self._admission_request.store_id
            ):
                preflight = self._admit()
                for recovery in self._recoveries:
                    recovery.recover()
                receipt = self._admit()
                if receipt != preflight:
                    raise PackageProductActivationError(
                        "Package runtime epoch changed during recovery",
                        code="package_runtime_epoch_unsupported",
                    )
                for admitted_recovery in self._admitted_recoveries:
                    admitted_recovery.recover(receipt)
            self._receipt = receipt
            return receipt

    def recover_handoff_exact(
        self, operation_id: str
    ) -> PackageProductExactHandoffRecoveryV1:
        """Recover one operation without publishing a general Product route."""

        if type(operation_id) is not str or not operation_id:
            raise ValueError("Exact Package handoff operation ID is required")
        with self._lock:
            if self._receipt is not None or self._exact_recovery_used:
                raise PackageProductActivationError(
                    "Exact handoff recovery requires a fresh Product runtime",
                    code="package_product_exact_recovery_consumed",
                )
            if len(self._recoveries) != 1 or len(self._admitted_recoveries) != 1:
                raise PackageProductActivationError(
                    "Exact handoff recovery owners are unavailable",
                    code="package_product_exact_recovery_unavailable",
                )
            preliminary = getattr(self._recoveries[0], "recover_exact", None)
            committed = getattr(self._admitted_recoveries[0], "recover_exact", None)
            terminal_state = getattr(
                self._admitted_recoveries[0], "terminal_state", None
            )
            if (
                not callable(preliminary)
                or not callable(committed)
                or not callable(terminal_state)
            ):
                raise PackageProductActivationError(
                    "Exact handoff recovery owners are unavailable",
                    code="package_product_exact_recovery_unavailable",
                )
            self._exact_recovery_used = True
            with self._transaction_guard.shared_runtime(
                store_id=self._admission_request.store_id
            ):
                preflight = self._admit()
                retained_ids = preliminary(operation_id)
                receipt = self._admit()
                if receipt != preflight:
                    raise PackageProductActivationError(
                        "Package runtime epoch changed during exact recovery",
                        code="package_runtime_epoch_unsupported",
                    )
                committed_ids = committed(receipt, operation_id)
                state = terminal_state(operation_id)
                if state not in {"settled", "aborted"}:
                    raise PackageProductActivationError(
                        "Exact Package handoff is not terminal",
                        code="package_product_exact_recovery_incomplete",
                    )
                if self._admit() != preflight:
                    raise PackageProductActivationError(
                        "Package runtime epoch changed during exact recovery",
                        code="package_runtime_epoch_unsupported",
                    )
            return PackageProductExactHandoffRecoveryV1(
                operation_id=operation_id,
                retained_handoff_ids=retained_ids,
                committed_operation_ids=committed_ids,
                terminal_state=state,
            )

    def route(
        self,
        intent: PackageProductLifecycleIntentV1,
        *,
        entrypoint: PackageProductEntrypoint,
    ) -> PackageProductLifecycleOutcomeV1:
        if not isinstance(intent, PackageProductLifecycleIntentV1):
            raise TypeError("Package Product lifecycle intent is required")
        return self._route_with_admission(intent, entrypoint=entrypoint, retry=None)

    def retry(
        self,
        request: PackageProductLifecycleRetryIntentV1,
        *,
        entrypoint: PackageProductEntrypoint,
    ) -> PackageProductLifecycleOutcomeV1:
        if not isinstance(request, PackageProductLifecycleRetryIntentV1):
            raise TypeError("Package Product retry intent is required")
        return self._route_with_admission(
            request.intent, entrypoint=entrypoint, retry=request
        )

    def _route_with_admission(
        self,
        intent: PackageProductLifecycleIntentV1,
        *,
        entrypoint: PackageProductEntrypoint,
        retry: PackageProductLifecycleRetryIntentV1 | None,
    ) -> PackageProductLifecycleOutcomeV1:
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
                    retry=retry,
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

    def execute_guarded_mutation(
        self,
        mutation: Callable[[PackageEpochRuntimeAdmissionReceiptV1], T],
    ) -> T:
        """Run one internal Product mutation under fresh admitted epoch proof."""

        if not callable(mutation):
            raise TypeError("Package Product guarded mutation is required")
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
                return mutation(receipt)
        except BaseException:
            with self._lock:
                self._receipt = None
            raise

    def execute_guarded_rebound(
        self,
        prepare: Callable[
            [PackageEpochRuntimeAdmissionReceiptV1],
            tuple[PackageProductReboundRouteRequestV1, PackageLifecycleStatusV1],
        ],
    ) -> PackageLifecycleStatusV1:
        """Resume and execute an internal rebound route inside one epoch guard."""

        if not callable(prepare):
            raise TypeError("Package Product rebound preparation is required")

        def execute(
            receipt: PackageEpochRuntimeAdmissionReceiptV1,
        ) -> PackageLifecycleStatusV1:
            route, current = prepare(receipt)
            if (
                not isinstance(route, PackageProductReboundRouteRequestV1)
                or route.admission.request != receipt.request
                or not isinstance(current, PackageLifecycleStatusV1)
            ):
                raise PackageProductActivationError(
                    "Rebound Package route changed the admitted runtime",
                    code="package_product_rebound_route_invalid",
                )
            return self._router.route_rebound(route, current=current)

        return self.execute_guarded_mutation(execute)

    def execute_guarded_pinned_adoption(
        self,
        prepare: Callable[
            [PackageEpochRuntimeAdmissionReceiptV1],
            tuple[PackageProductPinnedAdoptedRouteRequestV1, PackageLifecycleStatusV1],
        ],
    ) -> PackageLifecycleStatusV1:
        """Claim and execute the selected pinned admission in one epoch guard."""

        if not callable(prepare):
            raise TypeError("Pinned Package Product preparation is required")

        def execute(
            receipt: PackageEpochRuntimeAdmissionReceiptV1,
        ) -> PackageLifecycleStatusV1:
            route, current = prepare(receipt)
            if (
                not isinstance(route, PackageProductPinnedAdoptedRouteRequestV1)
                or route.admission != receipt
                or not isinstance(current, PackageLifecycleStatusV1)
            ):
                raise PackageProductActivationError(
                    "Pinned Package route changed the admitted runtime",
                    code="package_product_pinned_route_invalid",
                )
            return self._router.route_pinned_adopted(route, current=current)

        return self.execute_guarded_mutation(execute)

    def execute_guarded_staging_adoption(
        self,
        prepare: Callable[
            [PackageEpochRuntimeAdmissionReceiptV1],
            tuple[PackageProductStagingAdoptedRouteRequestV1, PackageLifecycleStatusV1],
        ],
    ) -> PackageLifecycleStatusV1:
        """Claim and resume the selected staged set in one epoch guard."""

        if not callable(prepare):
            raise TypeError("Staging Package Product preparation is required")

        def execute(
            receipt: PackageEpochRuntimeAdmissionReceiptV1,
        ) -> PackageLifecycleStatusV1:
            route, current = prepare(receipt)
            if (
                not isinstance(route, PackageProductStagingAdoptedRouteRequestV1)
                or route.admission != receipt
                or not isinstance(current, PackageLifecycleStatusV1)
            ):
                raise PackageProductActivationError(
                    "Staging Package route changed the admitted runtime",
                    code="package_product_staging_route_invalid",
                )
            return self._router.route_staging_adopted(route, current=current)

        return self.execute_guarded_mutation(execute)

    def _route_guarded(
        self,
        intent: PackageProductLifecycleIntentV1,
        *,
        entrypoint: PackageProductEntrypoint,
        receipt: PackageEpochRuntimeAdmissionReceiptV1,
        retry: PackageProductLifecycleRetryIntentV1 | None,
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
                runtime_admission_request_id=(receipt.request.admission_request_id),
            )
        except ValueError:
            raise PackageProductActivationError(
                "Package Product ingress changed runtime admission identity",
                code="package_product_ingress_changed",
            ) from None
        ingress = bound_ingress
        route_request = PackageProductRouteRequestV1(
            entrypoint=entrypoint,
            ingress=ingress,
            admission=receipt,
        )
        status = (
            self._router.route(route_request)
            if retry is None
            else self._router.retry(
                route_request,
                request_fingerprint=retry.request_fingerprint,
                expected_attempt_epoch=retry.expected_attempt_epoch,
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
    "PackageProductAdmittedRecoveryPort",
    "PackageProductEpochTransactionGuardPort",
    "PackageProductExactHandoffRecoveryV1",
    "PackageProductIngressFactoryPort",
    "PackageProductLifecycleActivation",
    "PackageProductLifecycleIntentV1",
    "PackageProductLifecycleOperationPort",
    "PackageProductLifecycleOutcomeV1",
    "PackageProductLifecycleRecordV1",
    "PackageProductRecoveryPort",
    "PackageProductRoutingDisposition",
]
