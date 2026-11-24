"""Coding query policy and existing preparation component bindings.

Harness Receipt owners borrow the original payload, journal and evidence
constructors. No per-attempt source or activation object is created here.
"""

from __future__ import annotations

from functools import partial

from loushang.coding.package.product_worker_activation_state import (
    open_coding_product_worker_activation_state_store,
    open_coding_windows_product_worker_activation_state_store,
)
from loushang.coding.package.product_worker_capability import (
    _bind_query_authority,
)
from loushang.coding.package.product_worker_cleanup_evidence import (
    CodingPosixWorkerCleanupEvidenceAuthority,
)
from loushang.coding.package.product_worker_payload import (
    bind_coding_product_worker_launch_request,
    materialize_coding_product_worker_payload,
    open_coding_product_worker_supervisor_journal,
)
from loushang.coding.package.product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
)
from loushang.coding.package.product_worker_provider_host import (
    CodingPreparedWorkerProvider,
)
from loushang.coding.package.product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_FACET_ID,
    coding_worker_query_owner_authority,
)
from loushang.coding.package.product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
)
from loushang.coding.package.product_worker_resume import (
    _parent_failure,
    _resume_parent_matches_settlement,
)
from loushang.coding.package.product_worker_session_composition import (
    prepare_coding_product_worker_session_inputs,
)
from loushang.coding.package.product_worker_start_gate import (
    CodingProductWorkerStartGate,
)
from loushang.coding.package.product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
)
from loushang.coding.package.product_worker_windows_launch_intent import (
    commit_coding_windows_product_worker_launch_intent,
)
from loushang.coding.package.product_worker_windows_payload import (
    bind_coding_windows_product_worker_launch_request,
    materialize_coding_windows_product_worker_payload,
)
from loushang.coding.package.product_worker_windows_provisioning import (
    open_coding_windows_product_worker_provisioning_state_store,
)
from loushang.coding.package.product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)
from loushang.coding.package.product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)
from loushang.harness.session._worker_provider import (
    _PendingWorkerSessionInputs,
)

# Native preparation borrows the actual Receipt owner and existing components.
# These are complete operation/constructor bindings, not another source object.
CodingWorkerProductReceiptOwner._worker_materialize_factory = staticmethod(
    materialize_coding_product_worker_payload
)
CodingWorkerProductReceiptOwner._worker_bind_factory = staticmethod(
    bind_coding_product_worker_launch_request
)
CodingWorkerProductReceiptOwner._worker_state_store_factory = staticmethod(
    open_coding_product_worker_activation_state_store
)
CodingWorkerProductReceiptOwner._worker_supervisor_factory = staticmethod(
    open_coding_product_worker_supervisor_journal
)
CodingWorkerProductReceiptOwner._worker_evidence_type = (
    CodingPosixWorkerCleanupEvidenceAuthority
)
CodingWorkerProductReceiptOwner._worker_start_gate_type = CodingProductWorkerStartGate
CodingWindowsWorkerProductReceiptOwner._worker_materialize_factory = staticmethod(
    materialize_coding_windows_product_worker_payload
)
CodingWindowsWorkerProductReceiptOwner._worker_bind_factory = staticmethod(
    bind_coding_windows_product_worker_launch_request
)
CodingWindowsWorkerProductReceiptOwner._worker_state_store_factory = staticmethod(
    open_coding_windows_product_worker_activation_state_store
)
CodingWindowsWorkerProductReceiptOwner._worker_supervisor_factory = staticmethod(
    open_coding_windows_product_worker_supervisor_journal
)
CodingWindowsWorkerProductReceiptOwner._worker_evidence_type = (
    CodingWindowsWorkerCleanupEvidenceAuthority
)
CodingWindowsWorkerProductReceiptOwner._worker_commit_intent_factory = staticmethod(
    commit_coding_windows_product_worker_launch_intent
)
CodingWindowsWorkerProductReceiptOwner._worker_provisioning_factory = staticmethod(
    open_coding_windows_product_worker_provisioning_state_store
)


prepare_pending_provider = partial(
    CodingPreparedWorkerProvider._prepare_pending,
    bind_authority=_bind_query_authority,
    capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
    facet_id=CODING_WORKER_QUERY_FACET_ID,
    parent_failure=_parent_failure,
)


bind_pending_session_inputs = partial(
    _PendingWorkerSessionInputs,
    definition=CODING_WORKER_QUERY_DEFINITION,
    expected_provider_owner=coding_worker_query_owner_authority,
    base_policy_type=CodingWorkerBaseCompositionPolicyBinding,
    resume_matches=_resume_parent_matches_settlement,
    prepare_session_inputs=prepare_coding_product_worker_session_inputs,
)
