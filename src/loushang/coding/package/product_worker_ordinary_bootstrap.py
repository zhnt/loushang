"""Explicit Product selection of one Worker for an ordinary Coding Session."""

from __future__ import annotations

import secrets as secrets
from collections.abc import Callable

from loushang.coding.composition.base_product import CodingBaseProductSessionAssembly
from loushang.coding.composition.provenance import (
    historical_startup_composition_record as historical_startup_composition_record,
)
from loushang.coding.harness.worker import session_selection as _session_programs
from loushang.coding.session.manager import SessionManager
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION as MODEL_INPUT_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities import (
    WORKSPACE_CAPABILITY_DEFINITION as WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.package_product._worker_product_authority import (
    capture_worker_startup_selection as capture_worker_startup_selection,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.transcript.directory import (
    AgentTranscriptDirectoryRuntime as AgentTranscriptDirectoryRuntime,
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
from .product_worker_provider import (
    coding_worker_query_capability_provider as coding_worker_query_capability_provider,
)
from .product_worker_provider import (
    prepare_coding_selected_worker_provider_candidate as prepare_coding_selected_worker_provider_candidate,
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
)
from .product_worker_session_composition import (
    compose_coding_product_worker_with_ordinary_session as compose_coding_product_worker_with_ordinary_session,
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


_WORKER_SESSION_PROGRAM_VALUES = {
    "value_001": "Coding Worker ordinary Product inputs are invalid",
    "value_002": "coding_worker_ordinary_transcript_not_materialized",
    "value_003": "coding_worker_ordinary_product_scope_changed",
    "value_004": "coding_worker_ordinary_startup_provenance_missing",
    "value_005": "coding_worker_ordinary_candidate_not_allowed",
    "value_006": "coding_worker_ordinary_",
}


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

    return _session_programs.prepare_worker_session(
        product_owner=product_owner,
        runtime=runtime,
        session_manager=session_manager,
        plugin_id=plugin_id,
        ordinary=ordinary,
        clock=clock,
        resume_parent_context=resume_parent_context,
    )


__all__ = [
    "CodingWorkerOrdinaryBootstrapError",
    "prepare_coding_product_worker_ordinary_binding",
]
