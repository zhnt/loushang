"""Explicit Linux Product query through one installed, selected Worker.

This is an operator action against an existing Coding transcript. It never
creates a transcript, invokes a model, or changes ordinary Session routing.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, NoReturn, cast

from loushang.agent import Agent
from loushang.ai.model import Capabilities, Model
from loushang.harness.capabilities import (
    stage_resource_composition_candidate,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
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
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.runtime import RuntimeProfileResolver
from loushang.harness.session import AgentProductSession
from loushang.harness.session._worker_operator_query import _query_selected_worker_once
from loushang.harness.session._worker_provider import _QueryAuthority
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.transcript import AgentTranscriptDirectoryRuntime
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from ._worker_preparation_inputs import (
    _PosixActivationInputs,
    _PosixSelectedWorkerSource,
)
from .package_product_worker_capability import CodingProductWorkerCapabilityAuthority
from .package_product_worker_installed_native import CodingWorkerNativeLaunchMaterialV1
from .package_product_worker_payload import (
    CodingProductWorkerPayloadLeaseV1,
    bind_coding_product_worker_launch_request,
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
    CodingWorkerProductReceiptOwner,
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


@dataclass(frozen=True, slots=True)
class _CodingOperatorLaunchSource(_PosixSelectedWorkerSource):
    """Product-selected facts and original IO adapters; no execution state."""

    receipt_owner: CodingWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1

    @property
    def activation(self) -> _PosixActivationInputs:
        return _PosixActivationInputs(self.receipt_owner)

    def bind_request(
        self, payload: CodingProductWorkerPayloadLeaseV1, *, supervisor_epoch: int
    ) -> ManagedWorkerLaunchRequestV1:
        return bind_coding_product_worker_launch_request(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            payload_lease=payload,
            supervisor_epoch=supervisor_epoch,
        )

    def read_native(self) -> CodingWorkerNativeLaunchMaterialV1:
        return self.receipt_owner.current_native_launch_material(self.receipt)

    def start_gate(
        self, request: ManagedWorkerLaunchRequestV1, attempt_id: str
    ) -> CodingProductWorkerStartGate:
        return CodingProductWorkerStartGate(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            worker_request=request,
            attempt_id=attempt_id,
        )

    native_profile = _PosixSelectedWorkerSource._profile_from_material


@dataclass(frozen=True, slots=True)
class _CodingOperatorQueryPolicy:
    """Coding query contract, admission policy and query-only Session settings."""

    receipt_owner: CodingWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1
    plugin_id: str
    manager: SessionManager
    capability_id: ClassVar[str] = CODING_WORKER_QUERY_CAPABILITY_ID
    facet_id: ClassVar[str] = CODING_WORKER_QUERY_FACET_ID

    def bind_authority(
        self, request: ManagedWorkerLaunchRequestV1
    ) -> tuple[
        CapabilityProviderOwnerAuthority, CodingProductWorkerCapabilityAuthority
    ]:
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
                product_policy_revision=self.receipt.policy.product_policy_revision,
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
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            request=request,
            binding=binding,
            owner_policy=facet_owner,
        )
        return owner, authority

    def prepare_inputs(
        self,
        *,
        owner: CapabilityProviderOwnerAuthority,
        authority: _QueryAuthority,
        capability: CapabilityQueryWorkerAdapter,
        admitted: CapabilityWorkerAdmissionV1,
        release_attempt: Callable[[], Awaitable[None]],
    ) -> SessionCapabilityCompositionInputs:
        provider = coding_worker_query_capability_provider(self.plugin_id)
        candidate = prepare_coding_selected_worker_provider_candidate(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
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
                policy_revision=self.receipt.policy.product_policy_revision,
            ),
            definitions=(CODING_WORKER_QUERY_DEFINITION,),
            admissions=(admission,),
            owner_snapshots=(owner.snapshot(),),
            evaluated_at=now,
        )

        return prepare_coding_product_worker_session_inputs(
            resolved_providers=resolved,
            provider_owner=owner,
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            capability_authority=cast(
                CodingProductWorkerCapabilityAuthority, authority
            ),
            adapter=capability,
            worker_admission=admitted,
            evaluated_at=now,
            clock=lambda: int(time.time()),
            release_attempt=release_attempt,
        )

    def create_session(
        self, inputs: SessionCapabilityCompositionInputs
    ) -> AgentProductSession:
        profile_plan = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        return AgentProductSession(
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
            session_manager=self.manager,
            capability_runtime=stage_resource_composition_candidate(profile_plan),
            execute_compaction=_no_model_execution,
            execute_branch_summary=_no_model_execution,
            get_changelog=lambda cwd, args: (cwd, args),
            copy_to_clipboard=lambda text: text,
            retry_sleep=_no_model_execution,
            footer_data_provider=_QueryOnlyFooter(),
            allowed_tool_names=[],
            capability_composition_inputs=inputs,
        )

    def query(self, session: AgentProductSession, symbol: str) -> Awaitable[str]:
        return bind_coding_worker_query_consumer(session).query(symbol=symbol)


def _open_coding_operator_query(
    *,
    product: PosixLocalWheelProductSessionOwner,
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    session_file: Path,
    manager: SessionManager,
) -> tuple[_CodingOperatorLaunchSource, _CodingOperatorQueryPolicy] | None:
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
        return None
    return (
        _CodingOperatorLaunchSource(receipt_owner, receipt),
        _CodingOperatorQueryPolicy(receipt_owner, receipt, plugin_id, manager),
    )


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
    return await _query_selected_worker_once(
        runtime=runtime,
        open_query=lambda: _open_coding_operator_query(
            product=product,
            runtime=runtime,
            plugin_id=plugin_id,
            session_file=session_file,
            manager=manager,
        ),
        symbol=symbol,
        failure=CodingWorkerOperatorQueryError,
        error_prefix="coding_worker_query",
        correlation_id="coding-product-worker-query",
        cleanup_note="Coding Worker query C5 cleanup also failed: ",
    )


__all__ = ["CodingWorkerOperatorQueryError", "query_coding_product_worker"]
