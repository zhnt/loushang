"""Explicit local-operator command for Coding Arch Installation data."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from collections.abc import Sequence
from importlib.metadata import version
from operator import attrgetter
from pathlib import Path

from loushang.coding.package.installation_private_data import (
    _ARCH_PLUGIN_ID as _PLUGIN_ID,
)
from loushang.coding.package.installation_private_data import (
    coding_arch_workspace_installation_key,
)
from loushang.coding.package.private_data_backup_expiry import (
    CodingArchPrivateDataBackupExpiryOwner,
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from loushang.coding.package.private_data_backup_expiry_journal import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
)
from loushang.coding.package.private_data_backup_sdk import (
    open_coding_arch_private_data_backup_client,
)
from loushang.coding.package.private_data_deletion_owner import (
    CodingArchPrivateDataDeletionOwner,
)
from loushang.coding.package.private_data_restore import (
    CodingArchPrivateDataRestoreOwner,
    CodingArchPrivateDataRestorePlanV1,
    CodingArchPrivateDataRestoreResultV1,
)
from loushang.coding.package.private_data_windows_backup_client import (
    open_coding_windows_arch_backup_candidate_client,
)
from loushang.coding.package.product_runtime import (
    CodingFencedProductApplicationOwner,
    _open_installed_product,
    open_coding_package_product_state,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.cli.package_lifecycle import (
    PRIVATE_DATA_ACCESS_ACTIONS,
    PackageOperatorRecordInput,
    add_private_data_operator_commands,
    run_package_operator_command,
    run_private_data_access,
    run_private_data_expiry,
)
from loushang.harness.package_product._private_data_custody import (
    hold_private_data_product,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationJournal,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionCoordinator,
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

_POLICY_REVISION = "coding-arch-private-data-cli:1"
_EXPIRY_POLICY_REVISION = "coding-arch-backup-expiry-cli:1"
_MAX_INPUT_BYTES = 16 * 1024
_RECORD_INPUT = PackageOperatorRecordInput(
    label="Coding private-data command", maximum_bytes=_MAX_INPUT_BYTES
)
_FINGERPRINT = attrgetter("fingerprint")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-plugin-private-data")
    parser.add_argument("--workspace", default=".", help="fenced Coding workspace")
    parser.add_argument(
        "--plugin-id", required=True, help="currently only coding.arch.default"
    )
    add_private_data_operator_commands(parser, installation_name="Arch")
    args = parser.parse_args(argv)

    if os.name not in {"posix", "nt"} or (
        os.name == "posix" and not sys.platform.startswith("linux")
    ):
        sys.stderr.write("Coding private-data command refused: platform_unsupported\n")
        return 1
    if args.plugin_id != _PLUGIN_ID:
        sys.stderr.write("Coding private-data command refused: plugin_type_unopened\n")
        return 1

    def execute(workspace: Path) -> dict[str, object]:
        layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
        if os.name == "nt":
            return _run_windows_action(workspace, layout, args)
        if args.action in PRIVATE_DATA_ACCESS_ACTIONS or args.action in {
            "restore-confirm",
            "restore-confirm-verify",
        }:
            return _run_posix_backup_action(workspace, args)
        return _run_posix_product_action(workspace, layout, args)

    return run_package_operator_command(
        args.workspace,
        execute,
        not_directory="Coding workspace is not a directory",
        refused="Coding private-data command refused",
        failure_reason="operation_refused",
    )


def _run_posix_product_action(
    workspace: Path,
    layout: CodingPluginLifecycleStateLayout,
    args: argparse.Namespace,
) -> dict[str, object]:
    application = _open_installed_product(layout, workspace=workspace)
    with hold_private_data_product(
        application, PosixLocalWheelProductSessionOwner, PackageProductPosixFencedRuntimeOwner,
        error="Coding private-data Product owner is unsupported",
    ) as product:
        if args.action == "restore":
            return _run_restore(layout, product, args)
        if args.action in {"backup-expiry-confirm", "backup-expire"}:
            return _run_backup_expiry(layout, product, args)
        return _run_product_action(layout, application, product, args)


def _run_posix_backup_action(
    workspace: Path, args: argparse.Namespace
) -> dict[str, object]:
    client = open_coding_arch_private_data_backup_client(workspace)
    if args.action == "restore-confirm":
        return {"restoreConfirmation": client.confirm_restore(args.backup_id).to_dict()}
    if args.action == "restore-confirm-verify":
        confirmation = client.verify_restore_confirmation(
            args.backup_id, args.confirmation_id
        )
        return {"restoreConfirmation": confirmation.to_dict()}
    return run_private_data_access(client, args)


def _run_windows_action(
    workspace: Path,
    layout: CodingPluginLifecycleStateLayout,
    args: argparse.Namespace,
) -> dict[str, object]:
    """Route one explicit command through the fenced Windows Product client."""

    client = open_coding_windows_arch_backup_candidate_client(
        workspace, layout=layout, runtime_version=version("loushang")
    )
    action = args.action
    if action in PRIVATE_DATA_ACCESS_ACTIONS:
        return run_private_data_access(client, args)
    if action == "restore-confirm-verify":
        restore_plan = _read_windows_restore_plan(args)
        return {
            "restoreConfirmation": client.restore_confirm_verify(
                restore_plan, args.confirmation_id
            ).to_dict()
        }
    if action == "restore-confirm":
        restore_plan = _read_windows_restore_plan(args)
        return {"restoreConfirmation": client.restore_confirm(restore_plan).to_dict()}
    if action == "restore":
        restore_plan = _read_restore_plan(Path(args.plan_file))
        if args.accept_fingerprint != restore_plan.fingerprint:
            raise ValueError("Coding Arch restore plan was not accepted")
        return _restore_document(client.restore(restore_plan))
    if action in {"backup-expiry-confirm", "backup-expire"}:
        plan = _read_expiry_plan(Path(args.plan_file))
        return run_private_data_expiry(
            args,
            plan,
            confirm=lambda: client.backup_expiry_confirm(
                plan,
                actor_id="local-operator:windows-private-data-cli",
                policy_revision=_EXPIRY_POLICY_REVISION,
            ),
            expire=lambda path: client.backup_expire(plan, _read_expiry_confirmation(path)),
            refused="Coding Arch backup expiry plan was not accepted",
        )
    if action == "confirm":
        deletion_plan = _read_plan(Path(args.plan_file))
        if (
            args.accept_fingerprint != deletion_plan.fingerprint
            or client.deletion_preview() != deletion_plan
        ):
            raise ValueError("Coding private-data plan was not accepted")
        deletion_confirmation = PluginPrivateDataDeletionConfirmationV1(
            plan_fingerprint=deletion_plan.fingerprint,
            confirmation_id="arch-private-data:" + secrets.token_hex(16),
        )
        client.deletion_confirm(
            deletion_plan,
            deletion_confirmation,
            actor_id="local-operator:windows-private-data-cli",
            policy_revision=_POLICY_REVISION,
        )
        return {"confirmation": deletion_confirmation.to_dict()}
    if action == "delete":
        deletion_plan = _read_plan(Path(args.plan_file))
        deletion_confirmation = _read_confirmation(Path(args.confirmation_file))
        return {
            "receipt": client.delete_confirmed(
                deletion_plan, deletion_confirmation
            ).to_dict()
        }
    raise ValueError("Coding private-data command action is invalid")


def _read_windows_restore_plan(
    args: argparse.Namespace,
) -> CodingArchPrivateDataRestorePlanV1:
    if args.plan_file is None:
        raise ValueError("Windows Coding Arch restore confirmation needs its plan")
    plan = _read_restore_plan(Path(args.plan_file))
    if plan.backup_id != args.backup_id:
        raise ValueError("Windows Coding Arch restore plan is foreign")
    return plan


def _run_restore(
    layout: CodingPluginLifecycleStateLayout,
    product: PosixLocalWheelProductSessionOwner,
    args: argparse.Namespace,
) -> dict[str, object]:
    key = coding_arch_workspace_installation_key(layout.scope_id)
    owner = CodingArchPrivateDataRestoreOwner(layout, product)
    plan = _read_restore_plan(Path(args.plan_file))
    if plan.installation_key != key or args.accept_fingerprint != plan.fingerprint:
        raise ValueError("Coding Arch restore plan was not accepted")
    return _restore_document(
        owner._restore(key, plan.backup_id, expected_plan=plan, operator_submission=True)
    )


def _restore_document(result: CodingArchPrivateDataRestoreResultV1) -> dict[str, object]:
    return {
        "restore": {
            "backupId": result.backup_id,
            "disposition": result.disposition,
            "restoreId": result.restore_id,
        }
    }


def _run_backup_expiry(
    layout: CodingPluginLifecycleStateLayout,
    product: PosixLocalWheelProductSessionOwner,
    args: argparse.Namespace,
) -> dict[str, object]:
    key = coding_arch_workspace_installation_key(layout.scope_id)
    plan = _read_expiry_plan(Path(args.plan_file))
    if plan.installation_key != key:
        raise ValueError("Coding Arch backup expiry plan is foreign")
    owner = CodingArchPrivateDataBackupExpiryOwner(layout, product)
    return run_private_data_expiry(
        args,
        plan,
        confirm=lambda: owner.confirm(
            plan,
            actor_id=f"local-uid:{os.geteuid()}",
            policy_revision=_EXPIRY_POLICY_REVISION,
        ),
        expire=lambda path: owner.expire(plan, _read_expiry_confirmation(path)),
        refused="Coding Arch backup expiry plan was not accepted",
    )


def _run_product_action(
    layout: CodingPluginLifecycleStateLayout,
    application: CodingFencedProductApplicationOwner,
    product: PosixLocalWheelProductSessionOwner,
    args: argparse.Namespace,
) -> dict[str, object]:
    state = open_coding_package_product_state(layout, application.epoch_runtime)
    domain_owner = CodingArchPrivateDataDeletionOwner(
        layout,
        product,
        state.private_data_confirmation,
        state.private_data_deletion,
    )
    coordinator = PluginPrivateDataDeletionCoordinator(
        domain_owner,
        confirmation_authority=state.private_data_confirmation,
    )
    key = coding_arch_workspace_installation_key(layout.scope_id)
    return _run(coordinator, state.private_data_confirmation, key, args)


def _run(
    coordinator: PluginPrivateDataDeletionCoordinator,
    confirmations: PluginPrivateDataConfirmationJournal,
    key: PluginInstallationKeyV1,
    args: argparse.Namespace,
) -> dict[str, object]:
    plan = _read_plan(Path(args.plan_file))
    if plan.installation_key != key:
        raise ValueError("Coding private-data plan is foreign")
    if args.action == "confirm":
        if coordinator.preview(key) != plan:
            raise ValueError("Coding private-data plan is stale")
        if args.accept_fingerprint != plan.fingerprint:
            raise ValueError("Coding private-data fingerprint was not accepted")
        confirmation = PluginPrivateDataDeletionConfirmationV1(
            plan_fingerprint=plan.fingerprint,
            confirmation_id="arch-private-data:" + secrets.token_hex(16),
        )
        confirmations.record_confirmation(
            plan,
            confirmation,
            actor_id=f"local-uid:{os.geteuid()}",
            policy_revision=_POLICY_REVISION,
        )
        return {"confirmation": confirmation.to_dict()}
    if args.action == "delete":
        confirmation = _read_confirmation(Path(args.confirmation_file))
        receipt = coordinator.delete(plan, confirmation)
        return {"receipt": receipt.to_dict()}
    raise ValueError("Coding private-data command action is invalid")


def _read_plan(path: Path) -> PluginPrivateDataDeletionPlanV1:
    return _RECORD_INPUT.read(
        path, "plan", PluginPrivateDataDeletionPlanV1.from_dict,
        label="Coding private-data preview", fingerprint=_FINGERPRINT,
    )


def _read_confirmation(path: Path) -> PluginPrivateDataDeletionConfirmationV1:
    return _RECORD_INPUT.read(
        path, "confirmation", PluginPrivateDataDeletionConfirmationV1.from_dict,
        label="Coding private-data confirmation",
    )


def _read_restore_plan(path: Path) -> CodingArchPrivateDataRestorePlanV1:
    return _RECORD_INPUT.read(
        path, "restorePlan", CodingArchPrivateDataRestorePlanV1.from_dict,
        label="Coding Arch restore preview", fingerprint=_FINGERPRINT,
    )


def _read_expiry_plan(path: Path) -> CodingArchPrivateDataBackupExpiryPlanV1:
    return _RECORD_INPUT.read(
        path, "backupExpiryPlan", CodingArchPrivateDataBackupExpiryPlanV1.from_dict,
        label="Coding Arch backup expiry preview", fingerprint=_FINGERPRINT,
    )


def _read_expiry_confirmation(
    path: Path,
) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
    return _RECORD_INPUT.read(
        path, "expiryConfirmation", CodingArchPrivateDataBackupExpiryConfirmationV1.from_dict,
        label="Coding Arch backup expiry confirmation",
    )


if __name__ == "__main__":
    raise SystemExit(main())
