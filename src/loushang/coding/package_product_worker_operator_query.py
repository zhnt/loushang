"""Explicit Linux Product query through one installed, selected Worker.

This is an operator action against an existing Coding transcript. It never
creates a transcript, invokes a model, or changes ordinary Session routing.
"""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import NoReturn

from loushang.agent import Agent
from loushang.ai.model import Capabilities, Model
from loushang.harness.capabilities import (
    stage_resource_composition_candidate,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.runtime import RuntimeProfileResolver
from loushang.harness.session import AgentProductSession
from loushang.harness.transcript import AgentTranscriptDirectoryRuntime
from loushang.harness.worker._native_profile_bridge import (
    _bind_posix_static_contained_product_worker_profile,
)
from loushang.harness.worker.capability_query import (
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker.gated_start import bind_worker_gated_start_release
from loushang.harness.worker.hosting_adapter import HostingManagedWorkerSessionAdapter
from loushang.harness.worker.supervisor import WorkerSupervisor
from loushang.hosting.runtime import create_child_session_host

from .package_product_worker_capability import CodingProductWorkerCapabilityAuthority
from .package_product_worker_payload import (
    bind_coding_product_worker_launch_request,
    materialize_coding_product_worker_payload,
    open_coding_product_worker_supervisor_journal,
)
from .package_product_worker_provider import (
    coding_worker_query_capability_provider,
    prepare_coding_selected_worker_provider_candidate,
)
from .package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_FACET_ID,
    CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
    CODING_WORKER_QUERY_PROVIDER_ID,
    bind_coding_worker_query_consumer,
    bind_coding_worker_query_facet_owner,
    coding_worker_query_owner_authority,
    validate_coding_worker_query_symbol,
)
from .package_product_worker_receipt import (
    open_coding_product_selected_worker_receipt_owner,
)
from .package_product_worker_session_composition import (
    prepare_coding_product_worker_session_inputs,
)
from .package_product_worker_start_gate import CodingProductWorkerStartGate
from .session_manager import SessionManager


class CodingWorkerOperatorQueryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _QueryOnlyFooter:
    def set_extension_status(self, *_args: object) -> None:
        pass

    def set_available_provider_count(self, *_args: object) -> None:
        pass

    def dispose(self) -> None:
        pass


async def _no_model_execution(*_args: object, **_kwargs: object) -> NoReturn:
    raise CodingWorkerOperatorQueryError("coding_worker_query_model_execution_refused")


async def query_coding_product_worker(
    *,
    product: PosixLocalWheelProductSessionOwner,
    workspace: Path,
    plugin_id: str,
    session_file: Path,
    symbol: str,
) -> str:
    """Consume one bounded query from an installed Worker in a real Product Session."""

    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker query requires a POSIX Product owner")
    try:
        symbol = validate_coding_worker_query_symbol(symbol)
    except ValueError as exc:
        raise CodingWorkerOperatorQueryError(
            "coding_worker_query_symbol_invalid"
        ) from exc
    if session_file.is_symlink() or not session_file.is_file():
        raise CodingWorkerOperatorQueryError("coding_worker_query_session_unavailable")
    session_file = session_file.resolve(strict=True)
    manager = await SessionManager.load(session_file)
    session_id = manager.get_header().conversation_id
    runtime = product.factory_for_session(
        session_id=session_id,
        cwd=workspace,
        runtime_id=f"worker-query-{secrets.token_hex(16)}",
    ).create(
        PackageProductRuntimeRequestV1(
            product_id="coding", session_id=session_id, cwd=str(workspace)
        )
    )
    try:
        runtime.activate()
        receipt_owner = open_coding_product_selected_worker_receipt_owner(
            product_owner=product,
            runtime=runtime,
            plugin_id=plugin_id,
            transcript_directory=AgentTranscriptDirectoryRuntime(
                session_dir=session_file.parent
            ),
            session_manager=manager,
        )
        receipt = receipt_owner.issue()
        if receipt is None:
            raise CodingWorkerOperatorQueryError("coding_worker_query_not_selected")
        attempt_id = secrets.token_hex(16)
        with materialize_coding_product_worker_payload(
            receipt_owner=receipt_owner,
            receipt=receipt,
            attempt_id=attempt_id,
        ) as payload:
            journal = open_coding_product_worker_supervisor_journal(product)
            probe = bind_coding_product_worker_launch_request(
                receipt_owner=receipt_owner,
                receipt=receipt,
                payload_lease=payload,
                supervisor_epoch=1,
            )
            next_epoch = journal.next_supervisor_epoch(probe.identity)
            request = (
                probe
                if next_epoch == 1
                else bind_coding_product_worker_launch_request(
                    receipt_owner=receipt_owner,
                    receipt=receipt,
                    payload_lease=payload,
                    supervisor_epoch=next_epoch,
                )
            )
            native = receipt_owner.current_native_launch_material(receipt)
            gate = CodingProductWorkerStartGate(
                receipt_owner=receipt_owner,
                receipt=receipt,
                worker_request=request,
                attempt_id=attempt_id,
            )
            try:
                profile = _bind_posix_static_contained_product_worker_profile(
                    receipt=receipt,
                    worker_request=request,
                    native_profile_catalog_revision=(
                        native.closure.native_profile_catalog_revision
                    ),
                    launcher_path=native.launcher_path,
                    launcher_sha256=native.closure.containment_launcher_digest,
                    containment_profile_sha256=native.closure.containment_profile_digest,
                    start_gate_read_fd=gate.start_gate_read_fd,
                )
            except BaseException:
                gate.close()
                raise
            try:
                host = create_child_session_host(
                    max_sessions=1, enable_posix_static_capture=True
                )
            except BaseException:
                gate.close()
                await profile.close()
                raise
            try:
                supervisor = WorkerSupervisor(
                    identity=request.identity,
                    journal=journal,
                    protocol=request.runtime.protocol,
                    protocol_version=request.runtime.protocol_version,
                )
            except BaseException:
                gate.close()
                try:
                    await profile.close()
                finally:
                    await host.close()
                raise
            session: AgentProductSession | None = None
            try:
                adapter = HostingManagedWorkerSessionAdapter(
                    hosting=host,
                    preparation=profile,
                    start_gate=bind_worker_gated_start_release(gate),
                )
                await supervisor.start_session(
                    session_port=adapter,
                    launch_request=request,
                    correlation_id="coding-product-worker-query",
                )
                identity = request.identity
                owner = coding_worker_query_owner_authority()
                binding = CapabilityWorkerBindingV1(
                    plugin_id=identity.plugin_id,
                    contribution_id=identity.contribution_id,
                    product_id=identity.product_id,
                    scope_id=identity.scope_id,
                    owner_id=identity.owner_id,
                    allowed_capability_ids=(CODING_WORKER_QUERY_CAPABILITY_ID,),
                    authority=CapabilityWorkerAuthorityV1(
                        plugin_revision_digest=identity.plugin_revision_digest,
                        declaration_fingerprint=identity.declaration_fingerprint,
                        owner_generation=identity.owner_generation,
                        product_policy_revision=receipt.policy.product_policy_revision,
                        owner_policy_revision=CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
                        revocation_epoch=0,
                    ),
                )
                facet_owner = bind_coding_worker_query_facet_owner(
                    binding=binding,
                    provider_owner=owner,
                    current_owner_snapshot=owner.snapshot,
                )
                authority = CodingProductWorkerCapabilityAuthority(
                    receipt_owner=receipt_owner,
                    receipt=receipt,
                    request=request,
                    binding=binding,
                    owner_policy=facet_owner,
                )
                capability = bind_capability_query_worker_adapter(
                    supervisor=supervisor,
                    binding=authority.binding,
                    authority_reader=authority.current_authority,
                    enabled=True,
                )
                admitted = capability.admit()
                descriptors = await capability.describe()
                if (
                    len(descriptors) != 1
                    or descriptors[0].capability_id != CODING_WORKER_QUERY_CAPABILITY_ID
                    or descriptors[0].facet_ids != (CODING_WORKER_QUERY_FACET_ID,)
                ):
                    raise CodingWorkerOperatorQueryError(
                        "coding_worker_query_contract_mismatch"
                    )
                provider = coding_worker_query_capability_provider(plugin_id)
                candidate = prepare_coding_selected_worker_provider_candidate(
                    receipt_owner=receipt_owner,
                    receipt=receipt,
                    definition=CODING_WORKER_QUERY_DEFINITION,
                    provider=provider,
                )
                now = int(time.time())
                eligibility = owner.grant_eligibility(
                    candidate, issued_at=now, expires_at=now + 300
                )
                admission = owner.admit(
                    candidate,
                    eligibility=eligibility,
                    issued_at=now,
                    expires_at=now + 180,
                )
                resolved = ProductCapabilityProviderResolver().resolve(
                    ProductCapabilityProviderSelectionPlanV1(
                        product_id="coding",
                        roots=(CODING_WORKER_QUERY_CAPABILITY_ID,),
                        choices=(
                            ProductCapabilityProviderChoice(
                                capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
                                provider_id=CODING_WORKER_QUERY_PROVIDER_ID,
                                candidate_fingerprint=admission.candidate_fingerprint,
                            ),
                        ),
                        policy_revision=receipt.policy.product_policy_revision,
                    ),
                    definitions=(CODING_WORKER_QUERY_DEFINITION,),
                    admissions=(admission,),
                    owner_snapshots=(owner.snapshot(),),
                    evaluated_at=now,
                )

                async def release_attempt() -> None:
                    if supervisor.status.state == "healthy":
                        await supervisor.shutdown()

                inputs = prepare_coding_product_worker_session_inputs(
                    resolved_providers=resolved,
                    provider_owner=owner,
                    receipt_owner=receipt_owner,
                    receipt=receipt,
                    capability_authority=authority,
                    adapter=capability,
                    worker_admission=admitted,
                    evaluated_at=now,
                    clock=lambda: int(time.time()),
                    release_attempt=release_attempt,
                )
                profile_plan = RuntimeProfileResolver().resolve(
                    standard_capability_composition_plan(product_id="coding")
                )
                session = AgentProductSession(
                    agent=Agent(
                        initial_state={
                            "system_prompt": "Worker query",
                            "model": Model(
                                id="worker-query-only",
                                name="Worker Query",
                                provider="local",
                                endpoint="local",
                                capabilities=Capabilities(
                                    input=("text",),
                                    context_window=128_000,
                                    max_tokens=4_096,
                                ),
                            ),
                            "thinking_level": "off",
                        }
                    ),
                    session_manager=manager,
                    capability_runtime=stage_resource_composition_candidate(
                        profile_plan
                    ),
                    execute_compaction=_no_model_execution,
                    execute_branch_summary=_no_model_execution,
                    get_changelog=lambda cwd, args: (cwd, args),
                    copy_to_clipboard=lambda text: text,
                    retry_sleep=_no_model_execution,
                    footer_data_provider=_QueryOnlyFooter(),
                    capability_composition_inputs=inputs,
                )
                await session.prepare_model_call_runtime()
                result = await bind_coding_worker_query_consumer(session).query(
                    symbol=symbol
                )
                if receipt_owner.current_witness(receipt) != receipt.authority_witness:
                    raise CodingWorkerOperatorQueryError(
                        "coding_worker_query_receipt_stale"
                    )
                return result
            finally:
                try:
                    try:
                        if session is not None:
                            await session.dispose()
                    finally:
                        if supervisor.status.state == "healthy":
                            await supervisor.shutdown()
                finally:
                    gate.close()
                    try:
                        await profile.close()
                    finally:
                        await host.close()
    finally:
        runtime.dispose_runtime()


__all__ = ["CodingWorkerOperatorQueryError", "query_coding_product_worker"]
