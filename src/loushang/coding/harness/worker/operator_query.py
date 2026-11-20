"""Bind an original Product Session and receipt for the native Worker query."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.coding.package import product_worker_operator_query as _binding
from loushang.coding.package.product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
    open_coding_product_selected_worker_receipt_owner,
)
from loushang.coding.session.manager import SessionManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.session._worker_operator_query import _query_selected_worker_once
from loushang.harness.transcript import AgentTranscriptDirectoryRuntime

if TYPE_CHECKING:
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PosixLocalWheelProductSessionOwner,
    )
    from loushang.harness.package_product.product_runtime import (
        PackageProductRuntimeBindingV1,
    )


def _open_selected_receipt(
    *,
    product: PosixLocalWheelProductSessionOwner,
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    session_file: Path,
    manager: SessionManager,
) -> tuple[CodingWorkerProductReceiptOwner, _binding._CodingOperatorQueryPolicy] | None:
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
    return owner, _binding._CodingOperatorQueryPolicy(
        owner, receipt, plugin_id, manager
    )


async def query_selected_worker(
    *,
    product: PosixLocalWheelProductSessionOwner,
    workspace: Path,
    plugin_id: str,
    session_file: Path,
    symbol: str,
) -> str:
    """Load the original Session and join the existing Worker query owner."""
    if session_file.is_symlink() or not session_file.is_file():
        raise _binding.CodingWorkerOperatorQueryError(
            _binding._QUERY_ERROR_PREFIX + "_session_unavailable"
        )
    session_file = session_file.resolve(strict=True)
    manager = await SessionManager.load(session_file)
    session_id = manager.get_header().conversation_id
    runtime = product.factory_for_session(
        session_id=session_id,
        cwd=workspace,
        runtime_id=_binding._QUERY_RUNTIME_PREFIX + secrets.token_hex(16),
    ).create(
        PackageProductRuntimeRequestV1(
            product_id=_binding._QUERY_PRODUCT_ID,
            session_id=session_id,
            cwd=str(workspace),
        )
    )
    return await _query_selected_worker_once(
        runtime=runtime,
        open_query=lambda: _open_selected_receipt(
            product=product,
            runtime=runtime,
            plugin_id=plugin_id,
            session_file=session_file,
            manager=manager,
        ),
        symbol=symbol,
        failure=_binding.CodingWorkerOperatorQueryError,
        error_prefix=_binding._QUERY_ERROR_PREFIX,
        correlation_id=_binding._QUERY_CORRELATION_ID,
        cleanup_note=_binding._QUERY_CLEANUP_NOTE,
    )
