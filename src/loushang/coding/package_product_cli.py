"""Narrow one-shot Coding CLI operations over an explicitly fenced Product."""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Literal, TextIO

from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementApplicationCommandV1,
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
    PluginManagementQueryV1,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_product_management_cli import (
    build_coding_fenced_product_management_cli_ports,
)
from .package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    admit_coding_external_data_wheel,
    open_coding_fenced_product_application_owner,
)


def route_coding_fenced_data_wheels(
    layout: CodingPluginLifecycleStateLayout,
    *,
    action: Literal["install", "update"],
    workspace: Path,
    sources: Sequence[str],
    scope: str,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if scope != "project":
        stderr.write(
            f"Error: Fenced Product {action} requires --package-scope project\n"
        )
        return 1


    try:
        controlled = tuple(
            admit_coding_external_data_wheel(layout, source=Path(raw))
            for raw in sources
        )
        owner = open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            for record in controlled:
                operation_id = f"coding-external-{action}:{secrets.token_hex(16)}"
                runtime_id = f"coding-external-cli:{secrets.token_hex(16)}"
                factory = product.factory_for_session(
                    session_id=runtime_id, cwd=workspace, runtime_id=runtime_id
                )
                runtime: PackageProductRuntimeBindingV1 | None = None
                try:
                    runtime = factory.create(
                        PackageProductRuntimeRequestV1(
                            product_id="coding",
                            session_id=runtime_id,
                            cwd=str(workspace),
                        )
                    )
                    runtime.activate()
                    outcome = runtime.lifecycle.route(
                        PackageProductLifecycleIntentV1(
                            operation_id=operation_id,
                            action=action,
                            source=str(
                                owner.epoch_runtime.control_root
                                / "product-sources"
                                / record.wheel_filename
                            ),
                            scope="project",
                        ),
                        entrypoint="cli",
                    )
                finally:
                    if runtime is None:
                        factory.dispose_unbound_runtime()
                    else:
                        runtime.dispose_runtime()
                if not outcome.handled or outcome.record is None:
                    raise RuntimeError(f"Package Product {action} was not handled")
                if outcome.record.lifecycle == "failed":
                    stderr.write(
                        "Error: "
                        f"{outcome.record.failure_code or 'Package operation failed'} "
                        f"(Package operation: {outcome.record.operation_id})\n"
                    )
                    return 1
                stdout.write(
                    json.dumps(
                        {"command": f"{action}_package", "record": outcome.record.to_dict()},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            return 0
        finally:
            owner.close()
    except (OSError, RuntimeError, ValueError) as error:
        stderr.write(f"Error: {error}\n")
        return 1


def uninstall_coding_fenced_data_wheels(
    layout: CodingPluginLifecycleStateLayout,
    *,
    plugin_ids: Sequence[str],
    scope: str,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if scope != "project":
        stderr.write("Error: Fenced Product uninstall requires --package-scope project\n")
        return 1
    ports = build_coding_fenced_product_management_cli_ports(layout)
    try:
        for plugin_id in plugin_ids:
            for _attempt in range(32):
                projection = ports.queries.snapshot(
                    PluginManagementQueryV1(
                        correlation_id=f"cli:uninstall-package:{plugin_id}:query",
                        product_id="coding",
                        installation_scope="workspace",
                        scope_id=layout.scope_id,
                        plugin_ids=(plugin_id,),
                    )
                )
                if len(projection.installations) != 1:
                    raise ValueError(f"Product Plugin Installation is unavailable: {plugin_id}")
                view = projection.installations[0]
                if (
                    view.selected_package_revision is None
                    or view.desired_state not in {"installed_disabled", "installed_enabled"}
                ):
                    raise ValueError(f"Product Plugin is not installed: {plugin_id}")
                revision = projection.owner_revisions.desired_state
                identity = sha256(
                    f"coding:uninstall:{layout.scope_id}:{plugin_id}:{revision}".encode()
                ).hexdigest()
                operation_id = f"cli-product-uninstall:{identity}"
                result = ports.commands.submit(
                    PluginManagementApplicationCommandV1(
                        correlation_id=f"cli:uninstall-package:{plugin_id}",
                        command=PluginManagementCommandV1(
                            action="remove",
                            mutation=PluginDesiredStateMutationV1(
                                operation_id=operation_id,
                                idempotency_key=operation_id,
                                expected_inventory_revision=revision,
                                installation_key=view.installation_key,
                                desired_state="absent",
                                package_revision=None,
                                actor_id="coding:cli",
                                policy_revision="coding-plugin-management-cli-v1",
                            ),
                        ),
                    )
                )
                operation = result.operation
                if not isinstance(operation, PluginManagementOperationEventV1):
                    raise RuntimeError("Product uninstall returned incompatible evidence")
                terminal = operation.result
                if terminal is not None and terminal.disposition == "succeeded":
                    stdout.write(
                        json.dumps(
                            {
                                "command": "uninstall_package",
                                "record": {
                                    "pluginId": plugin_id,
                                    "desiredState": "absent",
                                    "operationId": operation_id,
                                },
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    break
                error_code = (
                    "plugin_management_operation_incomplete"
                    if terminal is None or terminal.error_code is None
                    else terminal.error_code
                )
                if error_code != "plugin_inventory_revision_conflict":
                    raise RuntimeError(f"Product uninstall failed: {error_code}")
            else:
                raise RuntimeError("Product uninstall could not linearize")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        stderr.write(f"Error: {error}\n")
        return 1


__all__ = [
    "route_coding_fenced_data_wheels",
    "uninstall_coding_fenced_data_wheels",
]
