"""Narrow one-shot Coding CLI operations over an explicitly fenced Product."""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Literal, TextIO

from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.cli.package_lifecycle import (
    FencedPackageOperatorOutput,
    run_fenced_package_changes,
    run_fenced_package_removals,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredCommandAuthorityV1,
)

from .management_binding import (
    CODING_CLI_MANAGEMENT_ACTOR_ID,
    CODING_CLI_MANAGEMENT_POLICY_REVISION,
    _ProductCliOwner,
)
from .product_runtime import (
    _open_installed_product,
    admit_coding_external_data_wheel,
)

_PACKAGE_OPERATION_PREFIX = "coding-external-"
_PACKAGE_RUNTIME_PREFIX = "coding-external-cli:"


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

    return run_fenced_package_changes(
        sources,
        action=action,
        admit_source=lambda source: admit_coding_external_data_wheel(layout, source=source),
        open_application=partial(_open_installed_product, layout, workspace=workspace),
        management=_ProductCliOwner(layout),
        product_id=CODING_PRODUCT_ID,
        operation_prefix=_PACKAGE_OPERATION_PREFIX,
        runtime_prefix=_PACKAGE_RUNTIME_PREFIX,
        output=_package_operator_output(workspace, stdout, stderr),
    )


_REMOVAL_SCOPE: Literal["workspace"] = "workspace"
_REMOVAL_MAX_ATTEMPTS = 32
_REMOVAL_ID_DOMAIN = "coding:uninstall:"


def _package_operator_output(
    workspace: Path, stdout: TextIO, stderr: TextIO
) -> FencedPackageOperatorOutput:
    workspace_args = ("--workspace", str(workspace))
    return FencedPackageOperatorOutput(
        program="loushang",
        explain_command=("loushang", "--explain-plugin-operation"),
        repair_handoff_command=("loushang-package-repair", *workspace_args, "repair-handoff"),
        repair_desired_command=("loushang", "--repair-plugin-desired-operation"),
        gc_command=("loushang-package-gc", *workspace_args),
        stdout=stdout,
        stderr=stderr,
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
    return run_fenced_package_removals(
        plugin_ids,
        application=_ProductCliOwner(layout),
        authority=PluginDesiredCommandAuthorityV1(
            product_id=CODING_PRODUCT_ID,
            installation_scope=_REMOVAL_SCOPE,
            scope_id=layout.scope_id,
            actor_id=CODING_CLI_MANAGEMENT_ACTOR_ID,
            policy_revision=CODING_CLI_MANAGEMENT_POLICY_REVISION,
        ),
        max_attempts=_REMOVAL_MAX_ATTEMPTS,
        operation_id_for_revision=partial(_uninstall_operation_id, layout.scope_id),
        output=_package_operator_output(workspace, stdout, stderr),
    )


def _uninstall_operation_id(scope_id: str, plugin_id: str, revision: int) -> str:
    identity = sha256(
        f"{_REMOVAL_ID_DOMAIN}{scope_id}:{plugin_id}:{revision}".encode()
    ).hexdigest()
    return f"cli-product-uninstall:{identity}"


__all__ = [
    "route_coding_fenced_data_wheels",
    "uninstall_coding_fenced_data_wheels",
]
