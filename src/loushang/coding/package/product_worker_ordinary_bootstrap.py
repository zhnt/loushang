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
from loushang.harness.session.product_composition_assembly import (
    _OrdinaryWorkerPlatform,
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
    platform = (
        _OrdinaryWorkerPlatform(
            CodingWindowsWorkerProductReceiptOwner,
            open_coding_windows_product_selected_worker_receipt_owner,
            plan_coding_windows_product_worker_pending_launch,
            prepare_coding_windows_product_worker_pending_session_inputs,
        )
        if type(product_owner) is WindowsLocalWheelProductSessionOwner
        else _OrdinaryWorkerPlatform(
            CodingWorkerProductReceiptOwner,
            open_coding_product_selected_worker_receipt_owner,
            plan_coding_product_worker_pending_launch,
            prepare_coding_product_worker_pending_session_inputs,
        )
    )
    return _WORKER_SESSION_COMPOSITION.prepare_ordinary(
        ordinary,
        transcript=session_manager,
        runtime=runtime,
        product_owner=product_owner,
        plugin_id=plugin_id,
        definition=CODING_WORKER_QUERY_DEFINITION,
        platform=platform,
        startup_type=CODING_COMPOSITION_STARTUP_TYPE,
        startup_label="Coding Session",
        manifest_limits=(_STARTUP_MAX_FILES, _STARTUP_MAX_BYTES),
        startup_failure=_startup_failure,
        bind_receipt_context=lambda receipt: (
            CodingWorkerResumeSettlementBinding(
                receipt=receipt, context=resume_parent_context
            )
            if resume_parent_context is not None
            else None
        ),
        make_base_policy=CodingWorkerBaseCompositionPolicyBinding,
        make_provider_owner=coding_worker_query_owner_authority,
        resolve_provider=partial(
            _resolve_selected_worker_query,
            eligibility_duration=_PROVIDER_ELIGIBILITY_DURATION,
            admission_duration=_PROVIDER_ADMISSION_DURATION,
        ),
        clock=clock,
        resume_parent_context=resume_parent_context,
        binding_type=CodingProductWorkerOrdinarySessionBinding,
    )


__all__ = [
    "CodingWorkerOrdinaryBootstrapError",
    "prepare_coding_product_worker_ordinary_binding",
]
