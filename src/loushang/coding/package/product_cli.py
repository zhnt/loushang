"""Narrow one-shot Coding CLI operations over an explicitly fenced Product."""

from __future__ import annotations

import json
import re as re
import secrets as secrets
from collections.abc import Sequence
from hashlib import sha256 as sha256
from importlib.metadata import version as version
from pathlib import Path
from typing import Literal, TextIO

from loushang.coding.composition.plan import CODING_PRODUCT_ID as CODING_PRODUCT_ID
from loushang.coding.harness.plugin_management import package_removal as _removal
from loushang.coding.package.management_binding import (
    CODING_CLI_MANAGEMENT_ACTOR_ID,
)
from loushang.coding.package.management_binding import (
    CODING_CLI_MANAGEMENT_POLICY_REVISION as CODING_CLI_MANAGEMENT_POLICY_REVISION,
)
from loushang.coding.package.management_binding import (
    build_coding_fenced_product_management_cli_ports as build_coding_fenced_product_management_cli_ports,
)
from loushang.coding.package.management_binding import (
    explain_coding_fenced_plugin_operation as explain_coding_fenced_plugin_operation,
)
from loushang.coding.package.management_binding import (
    read_coding_fenced_desired_transition as read_coding_fenced_desired_transition,
)
from loushang.coding.package.management_binding import (
    read_coding_fenced_handoff_desired_commit as read_coding_fenced_handoff_desired_commit,
)
from loushang.coding.package.management_binding import (
    read_coding_fenced_package_handoff as read_coding_fenced_package_handoff,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._plugin_bootstrap import (
    _product_plugin_runtime as _product_plugin_runtime,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1 as PackageProductRuntimeBindingV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1 as PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1 as PluginDesiredStateMutationV1,
)
from loushang.harness.plugin_management import (
    PluginManagementApplicationCommandV1 as PluginManagementApplicationCommandV1,
)
from loushang.harness.plugin_management import (
    PluginManagementCommandV1 as PluginManagementCommandV1,
)
from loushang.harness.plugin_management import (
    PluginManagementOperationEventV1 as PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management import (
    PluginManagementQueryV1 as PluginManagementQueryV1,
)
from loushang.harness.plugin_management.application import (
    PluginManagementInstallationViewV1,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1 as PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleRecordV1,
)

from .external_data_wheel import CodingExternalDataWheelBindingV1
from .product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH as CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
)
from .product_runtime import (
    admit_coding_external_data_wheel as admit_coding_external_data_wheel,
)
from .product_runtime import (
    open_coding_fenced_product_application_owner as open_coding_fenced_product_application_owner,
)

_PACKAGE_DISTRIBUTION = "loushang"
_PACKAGE_OPERATION_PREFIX = "coding-external-"
_PACKAGE_RUNTIME_PREFIX = "coding-external-cli:"
_PACKAGE_SOURCE_DIRECTORY = "product-sources"
_PACKAGE_SCOPE: Literal["project"] = "project"
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
                    outcome = runtime.lifecycle.route(
                        PackageProductLifecycleIntentV1(
                            operation_id=operation_id,
                            action=action,
                            source=str(
                                owner.epoch_runtime.control_root
                                / _PACKAGE_SOURCE_DIRECTORY
                                / record.wheel_filename
                            ),
                            scope=_PACKAGE_SCOPE,
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


def _observe_failed_change(
    layout: CodingPluginLifecycleStateLayout,
    operation_id: str,
) -> tuple[str, dict[str, object] | None, int | None, str | None, str, str]:
    """Observe recorded progress without retrying or inferring a rollback."""
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
    return (
        stage,
        committed_revision,
        desired_inventory_revision,
        handoff_receipt_id,
        handoff_evidence,
        join_status,
    )


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
    ) = _observe_failed_change(layout, operation_id)
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
    return _removal.remove_packages(
        layout, workspace=workspace, plugin_ids=plugin_ids, stdout=stdout, stderr=stderr
    )


__all__ = [
    "route_coding_fenced_data_wheels",
    "uninstall_coding_fenced_data_wheels",
]
