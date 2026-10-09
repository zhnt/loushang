"""Explicit Product selection of one Worker for an ordinary Coding Session."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint,
)
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime

from ._base_product_composition import CodingBaseProductSessionAssembly
from .composition_provenance import startup_composition_record
from .package_product_worker_ordinary_error import CodingWorkerOrdinaryBootstrapError
from .package_product_worker_payload import plan_coding_product_worker_pending_launch
from .package_product_worker_pending_host import (
    prepare_coding_product_worker_pending_session_inputs,
)
from .package_product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
    coding_worker_query_capability_provider,
    prepare_coding_selected_worker_provider_candidate,
)
from .package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    coding_worker_query_owner_authority,
)
from .package_product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
    open_coding_product_selected_worker_receipt_owner,
)
from .package_product_worker_session_composition import (
    CodingProductWorkerOrdinarySessionBinding,
    compose_coding_product_worker_with_ordinary_session,
)
from .package_product_worker_windows_payload import (
    plan_coding_windows_product_worker_pending_launch,
)
from .package_product_worker_windows_pending_host import (
    prepare_coding_windows_product_worker_pending_session_inputs,
)
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
    open_coding_windows_product_selected_worker_receipt_owner,
)
from .session_manager import SessionManager


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
    ):
        raise TypeError("Coding Worker ordinary Product inputs are invalid")
    if not session_manager.is_persisted():
        raise CodingWorkerOrdinaryBootstrapError(
            "coding_worker_ordinary_transcript_not_materialized"
        )
    base_context = ordinary.session_inputs.product_composition.authority_context
    if (
        runtime.session_id != session_manager.get_header().conversation_id
        or ordinary.compilation.plan.context.scope_id
        != f"session:{runtime.session_id}"
        or base_context.product_policy_revision
        != ordinary.compilation.plan.context.policy_revision
    ):
        raise CodingWorkerOrdinaryBootstrapError(
            "coding_worker_ordinary_product_scope_changed"
        )
    transcript_directory = AgentTranscriptDirectoryRuntime(
        session_dir=session_manager.get_session_dir()
    )
    receipt_owner: CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner
    if type(product_owner) is WindowsLocalWheelProductSessionOwner:
        receipt_owner = open_coding_windows_product_selected_worker_receipt_owner(
            product_owner=product_owner,
            runtime=runtime,
            plugin_id=plugin_id,
            transcript_directory=transcript_directory,
            session_manager=session_manager,
        )
    else:
        assert type(product_owner) is PosixLocalWheelProductSessionOwner
        receipt_owner = open_coding_product_selected_worker_receipt_owner(
            product_owner=product_owner,
            runtime=runtime,
            plugin_id=plugin_id,
            transcript_directory=transcript_directory,
            session_manager=session_manager,
        )
    receipt = receipt_owner.issue()
    if receipt is None:
        raise CodingWorkerOrdinaryBootstrapError(
            "coding_worker_ordinary_candidate_not_allowed"
        )
    selected_worker = runtime.capture_selected_plugin_manifest_for(
        plugin_id, max_files=16, max_total_bytes=16 * 1024 * 1024
    )
    if (
        selected_worker.snapshot.root_ref.artifact_digest
        != receipt.policy.plugin_revision_digest
    ):
        raise CodingWorkerOrdinaryBootstrapError(
            "coding_worker_ordinary_selection_changed"
        )
    existing_startup = startup_composition_record(session_manager.get_entries())
    if existing_startup is None and session_manager.get_entries():
        raise CodingWorkerOrdinaryBootstrapError(
            "coding_worker_ordinary_startup_provenance_missing"
        )
    if existing_startup is not None:
        worker = existing_startup.get("workerSelection")
        expected_revision = {
            "pluginId": plugin_id,
            "packageRevisionFingerprint": plugin_package_revision_fingerprint(
                selected_worker.snapshot.package_revision
            ),
            "instanceRevisionRef": selected_worker.snapshot.instance_revision_ref.to_dict(),
        }
        revisions = existing_startup.get("selectedRevisions")
        if (
            not isinstance(worker, dict)
            or not isinstance(revisions, list)
            or expected_revision not in revisions
            or worker.get("pluginId") != receipt.policy.plugin_id
            or worker.get("productPolicyRevision")
            != receipt.policy.product_policy_revision
            or worker.get("nativeProfileId") != receipt.policy.native_profile_id
            or worker.get("selectedLocatorRevision")
            != receipt.policy.selected_locator_revision
            or worker.get("workerConfigurationFingerprint")
            != receipt.policy.worker_configuration_fingerprint
        ):
            raise CodingWorkerOrdinaryBootstrapError(
                "coding_worker_ordinary_startup_selection_changed"
            )
    base_policy = CodingWorkerBaseCompositionPolicyBinding(
        base=ordinary.compilation,
        receipt_owner=receipt_owner,
        receipt=receipt,
    )
    provider_owner = coding_worker_query_owner_authority()
    provider = coding_worker_query_capability_provider(plugin_id)
    candidate = prepare_coding_selected_worker_provider_candidate(
        receipt_owner=receipt_owner,
        receipt=receipt,
        definition=CODING_WORKER_QUERY_DEFINITION,
        provider=provider,
        base_policy_binding=base_policy,
    )
    evaluated_at = base_context.evaluated_at
    eligibility = provider_owner.grant_eligibility(
        candidate,
        issued_at=evaluated_at,
        expires_at=evaluated_at + 300_000,
    )
    admission = provider_owner.admit(
        candidate,
        eligibility=eligibility,
        issued_at=evaluated_at,
        expires_at=evaluated_at + 180_000,
    )
    resolved = ProductCapabilityProviderResolver().resolve(
        ProductCapabilityProviderSelectionPlanV1(
            product_id="coding",
            roots=(CODING_WORKER_QUERY_CAPABILITY_ID,),
            choices=(
                ProductCapabilityProviderChoice(
                    capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
                    provider_id=provider.provider_id,
                    candidate_fingerprint=admission.candidate_fingerprint,
                ),
            ),
            policy_revision=base_policy.policy_revision,
        ),
        definitions=(CODING_WORKER_QUERY_DEFINITION,),
        admissions=(admission,),
        owner_snapshots=(provider_owner.snapshot(),),
        evaluated_at=evaluated_at,
    )
    if type(product_owner) is WindowsLocalWheelProductSessionOwner:
        assert type(receipt_owner) is CodingWindowsWorkerProductReceiptOwner
        pending_windows = plan_coding_windows_product_worker_pending_launch(
            receipt_owner=receipt_owner,
            receipt=receipt,
            attempt_id=secrets.token_hex(16),
        )
        worker = prepare_coding_windows_product_worker_pending_session_inputs(
            resolved_providers=resolved,
            provider_owner=provider_owner,
            receipt_owner=receipt_owner,
            receipt=receipt,
            pending_launch=pending_windows,
            evaluated_at=evaluated_at,
            clock=clock,
            base_policy_binding=base_policy,
        )
    else:
        assert type(receipt_owner) is CodingWorkerProductReceiptOwner
        pending_linux = plan_coding_product_worker_pending_launch(
            receipt_owner=receipt_owner,
            receipt=receipt,
            attempt_id=secrets.token_hex(16),
        )
        worker = prepare_coding_product_worker_pending_session_inputs(
            resolved_providers=resolved,
            provider_owner=provider_owner,
            receipt_owner=receipt_owner,
            receipt=receipt,
            pending_launch=pending_linux,
            evaluated_at=evaluated_at,
            clock=clock,
            base_policy_binding=base_policy,
        )
    definitions = {
        item.capability_id: item
        for item in (
            MODEL_INPUT_CAPABILITY_DEFINITION,
            WORKSPACE_CAPABILITY_DEFINITION,
            CODING_WORKER_QUERY_DEFINITION,
            *(entry.definition for entry in ordinary.session_inputs.resolved_providers.entries),
        )
    }
    combined = compose_coding_product_worker_with_ordinary_session(
        ordinary=ordinary.session_inputs,
        worker=worker,
        definitions=tuple(definitions.values()),
        workspace_binding=ordinary.workspace_binding,
    )
    return CodingProductWorkerOrdinarySessionBinding(
        ordinary=ordinary.session_inputs,
        combined=combined,
        workspace_binding=ordinary.workspace_binding,
        selected_worker_manifest=selected_worker,
        activation_receipt=receipt,
    )


__all__ = [
    "CodingWorkerOrdinaryBootstrapError",
    "prepare_coding_product_worker_ordinary_binding",
]
