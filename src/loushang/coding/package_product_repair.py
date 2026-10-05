"""Local Coding management SDK for exact fenced Product Package repair.

The author SDK does not import this module. Each call opens one admitted
Product runtime and closes its lease after the selected owner action.
"""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from uuid import uuid4

from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from .package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    CodingFencedProductApplicationOwner,
    open_coding_fenced_product_application_owner,
)

CodingPackageRepairActionV1 = Literal[
    "repair-handoff",
    "inspect-staging",
    "inspect-published",
    "repair-staging",
    "repair-published",
    "repair-pinned",
    "repair-retryable",
    "repair-unstarted",
    "repair-acquired",
    "repair-resolving",
    "repair-verified",
]
CODING_PACKAGE_REPAIR_ACTIONS_V1: tuple[CodingPackageRepairActionV1, ...] = (
    "repair-handoff",
    "inspect-staging",
    "inspect-published",
    "repair-staging",
    "repair-published",
    "repair-pinned",
    "repair-retryable",
    "repair-unstarted",
    "repair-acquired",
    "repair-resolving",
    "repair-verified",
)
CODING_PACKAGE_REPAIR_INSPECTIONS_V1 = frozenset(
    {"inspect-staging", "inspect-published"}
)
_ACTIONS = frozenset(CODING_PACKAGE_REPAIR_ACTIONS_V1)
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_OwnerFactory = Callable[..., CodingFencedProductApplicationOwner]


class CodingPackageRepairError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingPackageRepairResultV1:
    operation_id: str
    phase: str
    disposition: str | None = None
    decision_id: str | None = None
    failure_code: str | None = None
    checkpoint_id: str | None = None
    missing_node_ids: tuple[str, ...] = ()
    staged_node_count: int | None = None

    @property
    def committed(self) -> bool:
        return self.disposition == "committed"

    def to_dict(self) -> dict[str, object]:
        if self.staged_node_count is not None:
            return {
                "operationId": self.operation_id,
                "phase": self.phase,
                "checkpointId": self.checkpoint_id,
                "missingNodeIds": list(self.missing_node_ids),
                "stagedNodeCount": self.staged_node_count,
            }
        return {
            "operationId": self.operation_id,
            "decisionId": self.decision_id,
            "phase": self.phase,
            "disposition": self.disposition,
            "failureCode": self.failure_code,
        }


@dataclass(frozen=True, slots=True)
class CodingPackageRepairClientV1:
    workspace: Path
    layout: CodingPluginLifecycleStateLayout
    workspace_identity: tuple[int, int]
    runtime_version: str

    def perform(
        self, action: CodingPackageRepairActionV1, operation_id: str
    ) -> CodingPackageRepairResultV1:
        return _perform_coding_package_repair(self, action, operation_id)

    async def aperform(
        self, action: CodingPackageRepairActionV1, operation_id: str
    ) -> CodingPackageRepairResultV1:
        return await _aperform_coding_package_repair(self, action, operation_id)


def open_coding_package_repair_client(
    workspace: str | Path, *, runtime_version: str | None = None
) -> CodingPackageRepairClientV1:
    if os.name != "posix":
        raise CodingPackageRepairError("package_repair_posix_only")
    root = Path(workspace).expanduser().resolve(strict=True)
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise CodingPackageRepairError("package_repair_workspace_not_directory")
    return CodingPackageRepairClientV1(
        workspace=root,
        layout=resolve_coding_plugin_lifecycle_state_layout(root),
        workspace_identity=(metadata.st_dev, metadata.st_ino),
        runtime_version=runtime_version
        if runtime_version is not None
        else version("loushang"),
    )


def _perform_coding_package_repair(
    client: CodingPackageRepairClientV1,
    action: CodingPackageRepairActionV1,
    operation_id: str,
    *,
    owner_factory: _OwnerFactory = open_coding_fenced_product_application_owner,
) -> CodingPackageRepairResultV1:
    return asyncio.run(
        _aperform_coding_package_repair(
            client, action, operation_id, owner_factory=owner_factory
        )
    )


async def _aperform_coding_package_repair(
    client: CodingPackageRepairClientV1,
    action: CodingPackageRepairActionV1,
    operation_id: str,
    *,
    owner_factory: _OwnerFactory = open_coding_fenced_product_application_owner,
) -> CodingPackageRepairResultV1:
    if not isinstance(client, CodingPackageRepairClientV1):
        raise TypeError("Coding Package repair client is required")
    if action not in _ACTIONS:
        raise CodingPackageRepairError("package_repair_unsupported_action")
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or operation_id != operation_id.strip()
    ):
        raise CodingPackageRepairError("package_repair_invalid_operation_id")
    _require_workspace_identity(client)
    owner = owner_factory(
        client.layout,
        workspace=client.workspace,
        runtime_version=client.runtime_version,
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        _require_workspace_identity(client)
        product = owner.runtime_owner.product_owner
        session_id = f"package-repair:{uuid4().hex}"
        runtime = product.factory_for_session(
            session_id=session_id,
            cwd=client.workspace,
            runtime_id=session_id,
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=session_id, cwd=str(client.workspace)
            )
        )
        try:
            if action == "repair-handoff":
                recovered = runtime.recover_committed_handoff_exact(operation_id)
                return CodingPackageRepairResultV1(
                    operation_id=operation_id,
                    phase="committed",
                    disposition=(
                        "committed"
                        if recovered.terminal_state == "settled"
                        else "aborted"
                    ),
                    failure_code=(
                        None
                        if recovered.terminal_state == "settled"
                        else "package_handoff_aborted"
                    ),
                )
            runtime.activate()
            if action == "inspect-staging":
                observed = await runtime.inspect_staging_rebind_claim(
                    operation_id, max_bytes=_MAX_SOURCE_BYTES
                )
                checkpoint = observed.checkpoint
                return CodingPackageRepairResultV1(
                    operation_id=operation_id,
                    phase=checkpoint.status.phase,
                    checkpoint_id=checkpoint.checkpoint_id,
                    missing_node_ids=checkpoint.missing_node_ids,
                    staged_node_count=len(checkpoint.receipts),
                )
            if action == "inspect-published":
                observed_published = await runtime.inspect_published_set_rebind_claim(
                    operation_id, max_bytes=_MAX_SOURCE_BYTES
                )
                published_checkpoint = observed_published.checkpoint
                return CodingPackageRepairResultV1(
                    operation_id=operation_id,
                    phase=published_checkpoint.status.phase,
                    checkpoint_id=published_checkpoint.checkpoint_id,
                    missing_node_ids=(),
                    staged_node_count=len(published_checkpoint.receipts),
                )
            if action in {"repair-staging", "repair-published"}:
                if action == "repair-staging":
                    await runtime.inspect_staging_rebind_claim(
                        operation_id, max_bytes=_MAX_SOURCE_BYTES
                    )
                else:
                    await runtime.inspect_published_set_rebind_claim(
                        operation_id, max_bytes=_MAX_SOURCE_BYTES
                    )
                staged_selection = runtime.prepare_staging_adoption(
                    operation_id, max_bytes=_MAX_SOURCE_BYTES
                )
                decision_id = staged_selection.decision.decision_id
                settled = runtime.execute_staging_adoption(
                    operation_id, max_bytes=_MAX_SOURCE_BYTES
                )
            elif action == "repair-pinned":
                pinned_selection = runtime.prepare_pinned_adoption(
                    operation_id, max_bytes=_MAX_SOURCE_BYTES
                )
                decision_id = pinned_selection.decision.decision_id
                settled = runtime.execute_pinned_adoption(
                    operation_id, max_bytes=_MAX_SOURCE_BYTES
                )
            else:
                if action == "repair-unstarted":
                    runtime.recover_unstarted_rebind(
                        operation_id, max_bytes=_MAX_SOURCE_BYTES
                    )
                elif action == "repair-acquired":
                    runtime.recover_acquired_rebind(
                        operation_id, max_bytes=_MAX_SOURCE_BYTES
                    )
                elif action == "repair-resolving":
                    runtime.recover_resolving_rebind(
                        operation_id, max_bytes=_MAX_SOURCE_BYTES
                    )
                elif action == "repair-verified":
                    runtime.recover_verified_rebind(
                        operation_id, max_bytes=_MAX_SOURCE_BYTES
                    )
                rebound_selection = runtime.prepare_rebind_decision(
                    operation_id, max_bytes=_MAX_SOURCE_BYTES
                )
                decision_id = rebound_selection.decision.decision_id
                settled = runtime.execute_rebind_decision(
                    operation_id, max_bytes=_MAX_SOURCE_BYTES
                )
            return CodingPackageRepairResultV1(
                operation_id=operation_id,
                phase=settled.phase,
                disposition=settled.disposition,
                decision_id=decision_id,
                failure_code=(
                    settled.failure.code if settled.failure is not None else None
                ),
            )
        finally:
            runtime.dispose_runtime()
    finally:
        owner.close()


def _require_workspace_identity(client: CodingPackageRepairClientV1) -> None:
    try:
        metadata = client.workspace.lstat()
        current = client.workspace.resolve(strict=True)
    except OSError as exc:
        raise CodingPackageRepairError("package_repair_workspace_changed") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or current != client.workspace
        or (metadata.st_dev, metadata.st_ino) != client.workspace_identity
    ):
        raise CodingPackageRepairError("package_repair_workspace_changed")


__all__ = [
    "CODING_PACKAGE_REPAIR_ACTIONS_V1",
    "CODING_PACKAGE_REPAIR_INSPECTIONS_V1",
    "CodingPackageRepairActionV1",
    "CodingPackageRepairClientV1",
    "CodingPackageRepairError",
    "CodingPackageRepairResultV1",
    "open_coding_package_repair_client",
]
