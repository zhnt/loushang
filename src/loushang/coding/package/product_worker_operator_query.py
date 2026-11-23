"""Explicit Linux Product query through one installed, selected Worker.

This is an operator action against an existing Coding transcript. It never
creates a transcript, invokes a model, or changes ordinary Session routing.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import ClassVar, cast

from loushang.coding.package.worker_preparation_inputs import (
    CodingWorkerProductReceiptOwner,
)
from loushang.coding.session.manager import SessionManager
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.session import AgentProductSession
from loushang.harness.session._worker_operator_query import _query_selected_worker_once
from loushang.harness.session._worker_provider import (
    _QueryAuthority,
    _selected_query_worker_binding,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.transcript import AgentTranscriptDirectoryRuntime
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .product_worker_capability import (
    CodingProductWorkerCapabilityAuthority,
    _bind_query_authority,
)
from .product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_FACET_ID,
    bind_coding_worker_query_consumer,
    coding_worker_query_owner_authority,
    validate_coding_worker_query_symbol,
)
from .product_worker_receipt import open_coding_product_selected_worker_receipt_owner
from .product_worker_session_composition import (
    _resolve_selected_worker_query,
    prepare_coding_product_worker_session_inputs,
)

_QUERY_PRODUCT_ID = "coding"
_QUERY_ERROR_PREFIX = "coding_worker_query"
_QUERY_CORRELATION_ID = "coding-product-worker-query"
_QUERY_CLEANUP_NOTE = "Coding Worker query C5 cleanup also failed: "


class CodingWorkerOperatorQueryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _CodingOperatorQueryPolicy:
    """Coding query contract, admission policy and query-only Session settings."""

    receipt_owner: CodingWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1
    plugin_id: str
    capability_id: ClassVar[str] = CODING_WORKER_QUERY_CAPABILITY_ID
    facet_id: ClassVar[str] = CODING_WORKER_QUERY_FACET_ID

    def bind_authority(
        self, request: ManagedWorkerLaunchRequestV1
    ) -> tuple[
        CapabilityProviderOwnerAuthority, CodingProductWorkerCapabilityAuthority
    ]:
        owner = coding_worker_query_owner_authority()
        authority = _bind_query_authority(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            request=request,
            binding=_selected_query_worker_binding(request.identity, self.receipt, owner),
            provider_owner=owner,
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
        resolved, now = _resolve_selected_worker_query(
            owner=owner,
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            plugin_id=self.plugin_id,
            clock=lambda: int(time.time()),
            eligibility_duration=300,
            admission_duration=180,
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

    def query(self, session: AgentProductSession, symbol: str) -> Awaitable[str]:
        return bind_coding_worker_query_consumer(session).query(symbol=symbol)


def _open_selected_receipt(
    runtime: PackageProductRuntimeBindingV1,
    session_file: Path,
    manager: SessionManager,
    *,
    product: PosixLocalWheelProductSessionOwner,
    plugin_id: str,
) -> tuple[CodingWorkerProductReceiptOwner, _CodingOperatorQueryPolicy] | None:
    owner = open_coding_product_selected_worker_receipt_owner(
        product_owner=product,
        runtime=runtime,
        plugin_id=plugin_id,
        transcript_directory=AgentTranscriptDirectoryRuntime(
            session_dir=session_file.parent
        ),
        session_manager=manager,
    )
    receipt = owner.issue()
    if receipt is None:
        return None
    return owner, _CodingOperatorQueryPolicy(owner, receipt, plugin_id)


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
    return await _query_selected_worker_once(
        product=product,
        product_id=_QUERY_PRODUCT_ID,
        workspace=workspace,
        session_file=session_file,
        transcript_type=SessionManager,
        open_query=partial(_open_selected_receipt, product=product, plugin_id=plugin_id),
        symbol=symbol,
        failure=CodingWorkerOperatorQueryError,
        error_prefix=_QUERY_ERROR_PREFIX,
        correlation_id=_QUERY_CORRELATION_ID,
        cleanup_note=_QUERY_CLEANUP_NOTE,
    )


__all__ = ["CodingWorkerOperatorQueryError", "query_coding_product_worker"]
