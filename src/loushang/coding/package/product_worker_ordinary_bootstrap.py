"""Explicit Product selection of one Worker for an ordinary Coding Session."""

from __future__ import annotations

import secrets as secrets
from collections.abc import Callable
from functools import partial

from loushang.coding.composition.base_product import CodingBaseProductSessionAssembly
from loushang.coding.composition.provenance import (
    CODING_COMPOSITION_STARTUP_TYPE,
)
from loushang.coding.session.manager import SessionManager
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.session.composition_evidence import (
    bind_ordinary_worker_startup,
)

from .product_worker_ordinary_error import CodingWorkerOrdinaryBootstrapError
from .product_worker_payload import (
    plan_coding_product_worker_pending_launch as plan_coding_product_worker_pending_launch,
)
from .product_worker_pending_host import (
    prepare_coding_product_worker_pending_session_inputs as prepare_coding_product_worker_pending_session_inputs,
)
from .product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding as CodingWorkerBaseCompositionPolicyBinding,
)
from .product_worker_query_consumer import (
    CODING_WORKER_QUERY_DEFINITION as CODING_WORKER_QUERY_DEFINITION,
)
from .product_worker_query_consumer import (
    coding_worker_query_owner_authority as coding_worker_query_owner_authority,
)
from .product_worker_receipt import (
    CodingWorkerProductReceiptOwner as CodingWorkerProductReceiptOwner,
)
from .product_worker_receipt import (
    open_coding_product_selected_worker_receipt_owner as open_coding_product_selected_worker_receipt_owner,
)
from .product_worker_resume import (
    CodingWorkerResumeSettlementBinding as CodingWorkerResumeSettlementBinding,
)
from .product_worker_session_composition import (
    _WORKER_SESSION_COMPOSITION as _WORKER_SESSION_COMPOSITION,
)
from .product_worker_session_composition import (
    CodingProductWorkerOrdinarySessionBinding,
    _resolve_selected_worker_query,
)
from .product_worker_windows_payload import (
    plan_coding_windows_product_worker_pending_launch as plan_coding_windows_product_worker_pending_launch,
)
from .product_worker_windows_pending_host import (
    prepare_coding_windows_product_worker_pending_session_inputs as prepare_coding_windows_product_worker_pending_session_inputs,
)
from .product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner as CodingWindowsWorkerProductReceiptOwner,
)
from .product_worker_windows_receipt import (
    open_coding_windows_product_selected_worker_receipt_owner as open_coding_windows_product_selected_worker_receipt_owner,
)

_STARTUP_MAX_FILES = 16
_STARTUP_MAX_BYTES = 16 * 1024 * 1024
_PROVIDER_ELIGIBILITY_DURATION = 300000
_PROVIDER_ADMISSION_DURATION = 180000


def _startup_failure(code: str) -> CodingWorkerOrdinaryBootstrapError:
    return CodingWorkerOrdinaryBootstrapError("coding_worker_ordinary_" + code)


def prepare_coding_product_worker_ordinary_binding(
    *,
    product_owner: (
        PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner
    ),
    runtime: PackageProductRuntimeBindingV1,
    session_manager: SessionManager,
    plugin_id: str,
    ordinary: CodingBaseProductSessionAssembly,
    clock: Callable[[], int],
    resume_parent_context: ResumeEffectParentContextV1 | None = None,
) -> CodingProductWorkerOrdinarySessionBinding:
    """Join exact Product, transcript, base graph, and Worker authorities.

    This function does not launch a Worker. The returned graph request starts
    one only during async preparation and owns its subsequent cleanup.
    """

    if (
        type(product_owner)
        not in (
            PosixLocalWheelProductSessionOwner,
            WindowsLocalWheelProductSessionOwner,
        )
        or not isinstance(runtime, PackageProductRuntimeBindingV1)
        or not isinstance(session_manager, SessionManager)
        or not isinstance(ordinary, CodingBaseProductSessionAssembly)
        or not isinstance(plugin_id, str)
        or not plugin_id
        or plugin_id != plugin_id.strip()
        or not callable(clock)
        or (
            resume_parent_context is not None
            and type(resume_parent_context) is not ResumeEffectParentContextV1
        )
    ):
        raise TypeError('Coding Worker ordinary Product inputs are invalid')
    if not session_manager.is_persisted():
        raise CodingWorkerOrdinaryBootstrapError(
            'coding_worker_ordinary_transcript_not_materialized'
        )
    base_context = ordinary.session_inputs.product_composition.authority_context
    open_receipt_owner: Callable[
        ..., CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner
    ] = (
        open_coding_windows_product_selected_worker_receipt_owner
        if type(product_owner) is WindowsLocalWheelProductSessionOwner
        else open_coding_product_selected_worker_receipt_owner
    )
    receipt_owner, receipt, selected_worker, resume_settlement = bind_ordinary_worker_startup(
        session_manager,
        runtime,
        plugin_id=plugin_id,
        base_context=base_context,
        plan_context=ordinary.compilation.plan.context,
        extension_type=CODING_COMPOSITION_STARTUP_TYPE,
        label="Coding Session",
        max_files=_STARTUP_MAX_FILES,
        max_total_bytes=_STARTUP_MAX_BYTES,
        open_receipt_owner=lambda directory: open_receipt_owner(
            product_owner=product_owner,
            runtime=runtime,
            plugin_id=plugin_id,
            transcript_directory=directory,
            session_manager=session_manager,
            active_session=True,
        ),
        bind_receipt_context=lambda selected_receipt: (
            CodingWorkerResumeSettlementBinding(
                receipt=selected_receipt, context=resume_parent_context
            )
            if resume_parent_context is not None
            else None
        ),
        failure=_startup_failure,
    )
    base_policy = CodingWorkerBaseCompositionPolicyBinding(
        base=ordinary.compilation,
        receipt_owner=receipt_owner,
        receipt=receipt,
    )
    provider_owner = coding_worker_query_owner_authority()
    resolved, evaluated_at = _resolve_selected_worker_query(
        owner=provider_owner,
        receipt_owner=receipt_owner,
        receipt=receipt,
        plugin_id=plugin_id,
        clock=lambda: base_context.evaluated_at,
        eligibility_duration=_PROVIDER_ELIGIBILITY_DURATION,
        admission_duration=_PROVIDER_ADMISSION_DURATION,
        base_policy_binding=base_policy,
    )
    prepare_pending: Callable[..., SessionCapabilityCompositionInputs]
    if type(product_owner) is WindowsLocalWheelProductSessionOwner:
        assert type(receipt_owner) is CodingWindowsWorkerProductReceiptOwner
        prepare_pending = partial(
            prepare_coding_windows_product_worker_pending_session_inputs,
            receipt_owner=receipt_owner,
            pending_launch=plan_coding_windows_product_worker_pending_launch(
                receipt_owner=receipt_owner,
                receipt=receipt,
                attempt_id=secrets.token_hex(16),
            ),
        )
    else:
        assert type(receipt_owner) is CodingWorkerProductReceiptOwner
        prepare_pending = partial(
            prepare_coding_product_worker_pending_session_inputs,
            receipt_owner=receipt_owner,
            pending_launch=plan_coding_product_worker_pending_launch(
                receipt_owner=receipt_owner,
                receipt=receipt,
                attempt_id=secrets.token_hex(16),
            ),
        )
    worker = prepare_pending(
        resolved_providers=resolved,
        provider_owner=provider_owner,
        receipt=receipt,
        evaluated_at=evaluated_at,
        clock=clock,
        base_policy_binding=base_policy,
        resume_parent_context=resume_parent_context,
        resume_settlement=resume_settlement,
    )
    combined = _WORKER_SESSION_COMPOSITION.compose_selected(
        ordinary=ordinary.session_inputs,
        worker=worker,
        worker_definition=CODING_WORKER_QUERY_DEFINITION,
        workspace_binding=ordinary.workspace_binding,
    )
    return CodingProductWorkerOrdinarySessionBinding(
        ordinary=ordinary.session_inputs,
        combined=combined,
        workspace_binding=ordinary.workspace_binding,
        selected_worker_manifest=selected_worker,
        activation_receipt=receipt,
        resume_settlement=resume_settlement,
    )


__all__ = [
    "CodingWorkerOrdinaryBootstrapError",
    "prepare_coding_product_worker_ordinary_binding",
]
