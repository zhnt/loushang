"""Narrow one-shot Coding CLI operations over an explicitly fenced Product."""

from __future__ import annotations

import json
import re
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
    explain_coding_fenced_plugin_operation,
    read_coding_fenced_desired_transition,
    read_coding_fenced_handoff_desired_commit,
    read_coding_fenced_package_handoff,
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

    current_operation_id: str | None = None
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
                current_operation_id = operation_id
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
                    _write_package_failure(
                        layout,
                        workspace=workspace,
                        operation_id=operation_id,
                        error_code=outcome.record.failure_code
                        or "package_operation_failed",
                        stderr=stderr,
                    )
                    return 1
                next_commands = [
                    "loushang --list-plugins --list-plugins-format json",
                    f"loushang --explain-plugin-operation {outcome.record.operation_id}",
                ]
                if action == "install":
                    next_commands.insert(
                        0, f"loushang --enable-plugin {record.plugin_id}"
                    )
                stdout.write(
                    json.dumps(
                        {
                            "command": f"{action}_package",
                            "operationKind": "A2",
                            "pluginId": record.plugin_id,
                            "sourceSha256": record.artifact_digest,
                            "stage": "package_operation_recorded",
                            "record": outcome.record.to_dict(),
                            "nextCommands": next_commands,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            return 0
        finally:
            owner.close()
    except (OSError, RuntimeError, ValueError) as error:
        if current_operation_id is None:
            stderr.write(f"Error: {error}\n")
        else:
            code = getattr(error, "code", None)
            _write_package_failure(
                layout,
                workspace=workspace,
                operation_id=current_operation_id,
                error_code=(
                    code
                    if isinstance(code, str)
                    and re.fullmatch(r"[a-z][a-z0-9_]{1,127}", code)
                    else "package_operation_incomplete"
                ),
                stderr=stderr,
            )
        return 1


def _write_package_failure(
    layout: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    operation_id: str,
    error_code: str,
    stderr: TextIO,
) -> None:
    """Report exact owner evidence after failure without mutating or inferring rollback."""

    stage = "unknown"
    committed_revision: dict[str, object] | None = None
    desired_inventory_revision: int | None = None
    handoff_receipt_id: str | None = None
    try:
        handoff = read_coding_fenced_package_handoff(layout, operation_id)
        if handoff is not None:
            stage = handoff.state
            handoff_receipt_id = handoff.receipt_id
            desired_commit = read_coding_fenced_handoff_desired_commit(layout, handoff)
            if desired_commit is not None:
                desired_inventory_revision, committed_revision, _source = desired_commit
                if handoff.state == "dependency_pinned":
                    stage = "desired_committed"
    except (OSError, RuntimeError, ValueError):
        pass
    try:
        explanation = explain_coding_fenced_plugin_operation(
            layout,
            operation_id,
            correlation_id=f"cli:failed-package:{operation_id}",
        )
        handoff_evidence: str = explanation.handoff_evidence
        join_status: str = explanation.join_status
    except (OSError, RuntimeError, ValueError):
        handoff_evidence = "not_checked"
        join_status = "not_checked"
    next_commands = [
        ["loushang", "--explain-plugin-operation", operation_id],
        ["loushang", "--list-plugins", "--list-plugins-format", "json"],
    ]
    if stage == "desired_committed":
        next_commands.append(
            [
                "loushang-package-repair",
                "--workspace",
                str(workspace),
                "repair-handoff",
                operation_id,
            ]
        )
    stderr.write(f"Error: {error_code} (Package operation: {operation_id})\n")
    stderr.write(
        json.dumps(
            {
                "operationKind": "A2",
                "operationId": operation_id,
                "stage": stage,
                "desiredInventoryRevision": desired_inventory_revision,
                "committedRevision": committed_revision,
                "handoffReceiptId": handoff_receipt_id,
                "handoffEvidence": handoff_evidence,
                "joinStatus": join_status,
                "nextCommands": next_commands,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )


def uninstall_coding_fenced_data_wheels(
    layout: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    plugin_ids: Sequence[str],
    scope: str,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if scope != "project":
        stderr.write(
            "Error: Fenced Product uninstall requires --package-scope project\n"
        )
        return 1
    ports = build_coding_fenced_product_management_cli_ports(layout)
    current_operation_id: str | None = None
    pending_operation = False
    try:
        for plugin_id in plugin_ids:
            current_operation_id = None
            pending_operation = False
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
                    raise ValueError(
                        f"Product Plugin Installation is unavailable: {plugin_id}"
                    )
                view = projection.installations[0]
                if view.selected_package_revision is None or view.desired_state not in {
                    "installed_disabled",
                    "installed_enabled",
                }:
                    raise ValueError(f"Product Plugin is not installed: {plugin_id}")
                revision = projection.owner_revisions.desired_state
                identity = sha256(
                    f"coding:uninstall:{layout.scope_id}:{plugin_id}:{revision}".encode()
                ).hexdigest()
                operation_id = f"cli-product-uninstall:{identity}"
                current_operation_id = operation_id
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
                    raise RuntimeError(
                        "Product uninstall returned incompatible evidence"
                    )
                terminal = operation.result
                if terminal is not None and terminal.disposition == "succeeded":
                    after = ports.queries.snapshot(
                        PluginManagementQueryV1(
                            correlation_id=f"cli:uninstall-package:{plugin_id}:after",
                            product_id="coding",
                            installation_scope="workspace",
                            scope_id=layout.scope_id,
                            plugin_ids=(plugin_id,),
                        )
                    )
                    installed = (
                        after.installations[0]
                        if len(after.installations) == 1
                        else None
                    )
                    stdout.write(
                        json.dumps(
                            {
                                "command": "uninstall_package",
                                "operationKind": "A1",
                                "stage": "desired_absent",
                                "retirementStatus": (
                                    {
                                        "evidence": "observed",
                                        "retirementStates": list(
                                            installed.retirement_states
                                        ),
                                        "cleanupDebtIds": list(
                                            installed.cleanup_debt_ids
                                        ),
                                        "unknownDimensions": list(
                                            installed.unknown_dimensions
                                        ),
                                    }
                                    if installed is not None
                                    else {"evidence": "not_checked"}
                                ),
                                "gcStatus": "not_checked",
                                "nextCommands": [
                                    [
                                        "loushang",
                                        "--list-plugins",
                                        "--list-plugins-format",
                                        "json",
                                    ],
                                ],
                                "gcStatusCommand": [
                                    "loushang-package-gc",
                                    "--workspace",
                                    str(workspace),
                                    "list",
                                ],
                                "gcPrepareCommand": [
                                    "loushang-package-gc",
                                    "--workspace",
                                    str(workspace),
                                    "prepare",
                                ],
                                "gcStatusPrerequisite": "close_active_sessions_and_prepare_gc",
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
                pending_operation = terminal is None
                if error_code != "plugin_inventory_revision_conflict":
                    raise RuntimeError(f"Product uninstall failed: {error_code}")
            else:
                raise RuntimeError("Product uninstall could not linearize")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        if current_operation_id is None:
            stderr.write(f"Error: {error}\n")
        else:
            operation_status = "unknown"
            actor_id: str | None = None
            committed_revision: int | None = None
            try:
                observed = ports.commands.operation(
                    current_operation_id,
                    correlation_id=f"cli:failed-uninstall:{current_operation_id}",
                )
                if observed is not None and isinstance(
                    observed.operation, PluginManagementOperationEventV1
                ):
                    operation_status = observed.operation.status
                    actor_id = observed.operation.command.mutation.actor_id
                    pending_operation = observed.operation.status != "terminal"
            except (OSError, RuntimeError, ValueError):
                pass
            try:
                transition = read_coding_fenced_desired_transition(
                    layout, current_operation_id
                )
                if (
                    transition is not None
                    and transition.mutation.desired_state == "absent"
                ):
                    committed_revision = transition.inventory_revision
            except (OSError, RuntimeError, ValueError):
                pass
            next_commands = [
                ["loushang", "--explain-plugin-operation", current_operation_id],
                ["loushang", "--list-plugins", "--list-plugins-format", "json"],
            ]
            if pending_operation and actor_id == "coding:cli":
                next_commands.append(
                    [
                        "loushang",
                        "--repair-plugin-desired-operation",
                        current_operation_id,
                    ]
                )
            stderr.write(
                f"Error: plugin_uninstall_incomplete (Desired operation: {current_operation_id})\n"
            )
            stderr.write(
                json.dumps(
                    {
                        "operationKind": "A1",
                        "operationId": current_operation_id,
                        "actorId": actor_id,
                        "operationStatus": operation_status,
                        "stage": (
                            "desired_absent"
                            if committed_revision is not None
                            else "unknown"
                        ),
                        "desiredInventoryRevision": committed_revision,
                        "retirementEvidence": (
                            "incomplete"
                            if committed_revision is not None and pending_operation
                            else "not_checked"
                        ),
                        "nextCommands": next_commands,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        return 1


__all__ = [
    "route_coding_fenced_data_wheels",
    "uninstall_coding_fenced_data_wheels",
]
