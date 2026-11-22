"""Narrow one-shot Coding CLI operations over an explicitly fenced Product."""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from functools import partial
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Literal, TextIO

from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.cli.package_lifecycle import package_operator_error_code
from loushang.harness.package_product._plugin_bootstrap import (
    _product_plugin_runtime,
    route_project_package,
)
from loushang.harness.plugin_management.application import (
    PluginManagementInstallationViewV1,
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginPackageRemovalAttempt,
    remove_installed_plugin_package,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleRecordV1,
)

from .external_data_wheel import CodingExternalDataWheelBindingV1
from .management_binding import (
    CODING_CLI_MANAGEMENT_ACTOR_ID,
    CODING_CLI_MANAGEMENT_POLICY_REVISION,
    _ProductCliOwner,
)
from .product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    admit_coding_external_data_wheel,
    open_coding_fenced_product_application_owner,
)

_PACKAGE_DISTRIBUTION = "loushang"
_PACKAGE_OPERATION_PREFIX = "coding-external-"
_PACKAGE_RUNTIME_PREFIX = "coding-external-cli:"
_PACKAGE_SOURCE_DIRECTORY = "product-sources"
_PACKAGE_ENTRYPOINT: Literal["cli"] = "cli"


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

    return _change_packages(
        layout,
        action=action,
        workspace=workspace,
        sources=sources,
        stdout=stdout,
        stderr=stderr,
    )


def _change_packages(
    layout: CodingPluginLifecycleStateLayout,
    *,
    action: Literal["install", "update"],
    workspace: Path,
    sources: Sequence[str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:

    current_operation_id: str | None = None
    try:
        controlled = tuple(
            admit_coding_external_data_wheel(layout, source=Path(raw))
            for raw in sources
        )
        owner = open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version=version(_PACKAGE_DISTRIBUTION),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            for record in controlled:
                operation_id = (
                    f"{_PACKAGE_OPERATION_PREFIX}{action}:{secrets.token_hex(16)}"
                )
                current_operation_id = operation_id
                runtime_id = f"{_PACKAGE_RUNTIME_PREFIX}{secrets.token_hex(16)}"
                with _product_plugin_runtime(
                    product,
                    product_id=CODING_PRODUCT_ID,
                    session_id=runtime_id,
                ) as runtime:
                    outcome = route_project_package(
                        runtime,
                        operation_id=operation_id,
                        action=action,
                        source=str(
                            owner.epoch_runtime.control_root
                            / _PACKAGE_SOURCE_DIRECTORY
                            / record.wheel_filename
                        ),
                        entrypoint=_PACKAGE_ENTRYPOINT,
                    )
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
                _write_package_success(stdout, action, record, outcome.record)
            return 0
        finally:
            owner.close()
    except (OSError, RuntimeError, ValueError) as error:
        if current_operation_id is None:
            _write_cli_error(stderr, error)
        else:
            _write_package_failure(
                layout,
                workspace=workspace,
                operation_id=current_operation_id,
                error_code=package_operator_error_code(
                    error, fallback="package_operation_incomplete"
                ),
                stderr=stderr,
            )
        return 1


def _write_package_success(
    stdout: TextIO,
    action: Literal["install", "update"],
    record: CodingExternalDataWheelBindingV1,
    lifecycle_record: PackageProductLifecycleRecordV1,
) -> None:
    next_commands = [
        "loushang --list-plugins --list-plugins-format json",
        f"loushang --explain-plugin-operation {lifecycle_record.operation_id}",
    ]
    if action == "install":
        next_commands.insert(0, f"loushang --enable-plugin {record.plugin_id}")
    stdout.write(
        json.dumps(
            {
                "command": f"{action}_package",
                "operationKind": "A2",
                "pluginId": record.plugin_id,
                "sourceSha256": record.artifact_digest,
                "stage": "package_operation_recorded",
                "record": lifecycle_record.to_dict(),
                "nextCommands": next_commands,
            },
            ensure_ascii=False,
        )
        + "\n"
    )


def _write_package_failure(
    layout: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    operation_id: str,
    error_code: str,
    stderr: TextIO,
) -> None:
    """Report exact owner evidence after failure without mutating or inferring rollback."""

    (
        stage,
        committed_revision,
        desired_inventory_revision,
        handoff_receipt_id,
        handoff_evidence,
        join_status,
    ) = _ProductCliOwner(layout).observe_package_change_failure(operation_id)
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


_REMOVAL_SCOPE: Literal["workspace"] = "workspace"
_REMOVAL_MAX_ATTEMPTS = 32
_REMOVAL_ID_DOMAIN = "coding:uninstall:"


def _write_uninstall_success(
    stdout: TextIO,
    *,
    workspace: Path,
    plugin_id: str,
    operation_id: str,
    installed: PluginManagementInstallationViewV1 | None,
) -> None:
    stdout.write(
        json.dumps(
            {
                "command": "uninstall_package",
                "operationKind": "A1",
                "stage": "desired_absent",
                "retirementStatus": (
                    {
                        "evidence": "observed",
                        "retirementStates": list(installed.retirement_states),
                        "cleanupDebtIds": list(installed.cleanup_debt_ids),
                        "unknownDimensions": list(installed.unknown_dimensions),
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


def _write_uninstall_failure(
    stderr: TextIO,
    *,
    current_operation_id: str,
    operation_status: str,
    actor_id: str | None,
    pending_operation: bool,
    committed_revision: int | None,
) -> None:
    next_commands = [
        ["loushang", "--explain-plugin-operation", current_operation_id],
        ["loushang", "--list-plugins", "--list-plugins-format", "json"],
    ]
    if pending_operation and actor_id == CODING_CLI_MANAGEMENT_ACTOR_ID:
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
                    "desired_absent" if committed_revision is not None else "unknown"
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


def _write_cli_error(stderr: TextIO, error: BaseException) -> None:
    stderr.write(f"Error: {error}\n")


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
    application = _ProductCliOwner(layout)
    ports = application.bind_ports()
    attempt = PluginPackageRemovalAttempt()
    try:
        for plugin_id in plugin_ids:
            attempt = PluginPackageRemovalAttempt()
            correlation_id = f"cli:uninstall-package:{plugin_id}"
            installed = remove_installed_plugin_package(
                ports,
                attempt,
                query=PluginManagementQueryV1(
                    correlation_id=f"{correlation_id}:query",
                    product_id=CODING_PRODUCT_ID,
                    installation_scope=_REMOVAL_SCOPE,
                    scope_id=layout.scope_id,
                    plugin_ids=(plugin_id,),
                ),
                correlation_id=correlation_id,
                actor_id=CODING_CLI_MANAGEMENT_ACTOR_ID,
                policy_revision=CODING_CLI_MANAGEMENT_POLICY_REVISION,
                max_attempts=_REMOVAL_MAX_ATTEMPTS,
                operation_id_for_revision=partial(
                    _uninstall_operation_id, layout.scope_id, plugin_id
                ),
            )
            operation_id = attempt.operation_id
            assert operation_id is not None
            _write_uninstall_success(
                stdout,
                workspace=workspace,
                plugin_id=plugin_id,
                operation_id=operation_id,
                installed=installed,
            )
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        operation_id = attempt.operation_id
        if operation_id is None:
            _write_cli_error(stderr, error)
        else:
            details = application.observe_package_removal_failure(
                ports, operation_id, pending_operation=attempt.pending
            )
            _write_uninstall_failure(
                stderr,
                current_operation_id=operation_id,
                operation_status=details.operation_status,
                actor_id=details.actor_id,
                pending_operation=details.pending_operation,
                committed_revision=details.committed_revision,
            )
        return 1


def _uninstall_operation_id(scope_id: str, plugin_id: str, revision: int) -> str:
    identity = sha256(
        f"{_REMOVAL_ID_DOMAIN}{scope_id}:{plugin_id}:{revision}".encode()
    ).hexdigest()
    return f"cli-product-uninstall:{identity}"


__all__ = [
    "route_coding_fenced_data_wheels",
    "uninstall_coding_fenced_data_wheels",
]
