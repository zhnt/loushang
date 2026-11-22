"""Explicit local-operator command for Coding Arch Installation data."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from collections.abc import Sequence
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
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
    CodingArchPrivateDataBackupClientV1,
    open_coding_arch_private_data_backup_client,
)
from loushang.coding.package.private_data_deletion_owner import (
    CodingArchPrivateDataDeletionOwner,
)
from loushang.coding.package.private_data_restore import (
    CodingArchPrivateDataRestoreOwner,
    CodingArchPrivateDataRestorePlanV1,
)
from loushang.coding.package.private_data_restore_journal import (
    CodingArchPrivateDataRestoreJournal,
    restore_id_for,
)
from loushang.coding.package.private_data_windows_backup_client import (
    CodingWindowsArchBackupCandidateClientV1,
    open_coding_windows_arch_backup_candidate_client,
)
from loushang.coding.package.product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    CodingFencedProductApplicationOwner,
    open_coding_fenced_product_application_owner,
    open_coding_package_product_state,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.foundation.json import _unique_json_object_hook
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
_BACKUP_ACCESS_ACTIONS = ("backup", "backup-status", "backup-verify", "restore-preview")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-plugin-private-data")
    parser.add_argument("--workspace", default=".", help="fenced Coding workspace")
    parser.add_argument(
        "--plugin-id", required=True, help="currently only coding.arch.default"
    )
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("preview", help="read exact Installation deletion target")
    commands.add_parser("backup", help="retain a verified Installation backup")
    commands.add_parser("backup-status", help="read verified backup retention")
    verify = commands.add_parser("backup-verify", help="verify one exact backup")
    verify.add_argument("--backup-id", required=True)
    expiry_preview = commands.add_parser(
        "backup-expiry-preview",
        help="read an exact, confirmed restore-backed backup expiry plan",
    )
    expiry_preview.add_argument("--backup-id", required=True)
    expiry_preview.add_argument("--confirmation-id", required=True)
    expiry_confirm = commands.add_parser(
        "backup-expiry-confirm", help="confirm one exact backup expiry plan"
    )
    expiry_confirm.add_argument("--plan-file", required=True)
    expiry_confirm.add_argument("--accept-fingerprint", required=True)
    expire = commands.add_parser(
        "backup-expire", help="expire only a separately confirmed Arch backup"
    )
    expire.add_argument("--plan-file", required=True)
    expire.add_argument("--confirmation-file", required=True)
    restore_preview = commands.add_parser(
        "restore-preview", help="read one exact, offline backup restore plan"
    )
    restore_preview.add_argument("--backup-id", required=True)
    restore = commands.add_parser(
        "restore", help="restore only a previewed, accepted backup into absent data"
    )
    restore.add_argument("--plan-file", required=True)
    restore.add_argument("--accept-fingerprint", required=True)
    restore_confirm = commands.add_parser(
        "restore-confirm", help="confirm one completed and verified Arch restore"
    )
    restore_confirm.add_argument("--backup-id", required=True)
    restore_confirm.add_argument("--plan-file")
    restore_confirm_verify = commands.add_parser(
        "restore-confirm-verify", help="reopen one exact restore confirmation"
    )
    restore_confirm_verify.add_argument("--backup-id", required=True)
    restore_confirm_verify.add_argument("--confirmation-id", required=True)
    restore_confirm_verify.add_argument("--plan-file")
    confirm = commands.add_parser(
        "confirm", help="separately confirm one unchanged preview fingerprint"
    )
    confirm.add_argument("--plan-file", required=True)
    confirm.add_argument("--accept-fingerprint", required=True)
    delete = commands.add_parser(
        "delete", help="delete only the separately confirmed, removed Installation"
    )
    delete.add_argument("--plan-file", required=True)
    delete.add_argument("--confirmation-file", required=True)
    args = parser.parse_args(argv)

    if os.name not in {"posix", "nt"} or (
        os.name == "posix" and not sys.platform.startswith("linux")
    ):
        sys.stderr.write("Coding private-data command refused: platform_unsupported\n")
        return 1
    if args.plugin_id != _PLUGIN_ID:
        sys.stderr.write("Coding private-data command refused: plugin_type_unopened\n")
        return 1
    try:
        workspace = Path(args.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Coding workspace is not a directory")
        layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
        if os.name == "nt":
            result = _run_windows_action(workspace, layout, args)
        elif args.action in _BACKUP_ACCESS_ACTIONS or args.action in {
            "preview",
            "restore-confirm",
            "restore-confirm-verify",
            "backup-expiry-preview",
        }:
            result = _run_posix_backup_action(workspace, args)
        else:
            result = _run_posix_product_action(workspace, layout, args)
    except (OSError, RuntimeError, ValueError, PackageNotFoundError):
        sys.stderr.write("Coding private-data command refused: operation_refused\n")
        return 1
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


def _run_posix_product_action(
    workspace: Path,
    layout: CodingPluginLifecycleStateLayout,
    args: argparse.Namespace,
) -> dict[str, object]:
    application = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = application.runtime_owner.product_owner
        if not isinstance(
            product, PosixLocalWheelProductSessionOwner
        ) or not isinstance(
            application.epoch_runtime, PackageProductPosixFencedRuntimeOwner
        ):
            raise ValueError("Coding private-data Product owner is unsupported")
        if args.action == "restore":
            return _run_restore(layout, product, args)
        if args.action in {"backup-expiry-confirm", "backup-expire"}:
            return _run_backup_expiry(layout, product, args)
        return _run_product_action(layout, application, product, args)
    finally:
        application.close()


def _run_backup_access(
    client: CodingArchPrivateDataBackupClientV1
    | CodingWindowsArchBackupCandidateClientV1,
    args: argparse.Namespace,
) -> dict[str, object]:
    if args.action == "backup-status":
        return {"backupRetention": client.status().to_dict()}
    if args.action == "backup":
        return {"backupReceipt": client.retain().to_dict()}
    if args.action == "backup-verify":
        return {"backupReceipt": client.verify(args.backup_id).to_dict()}
    plan = client.restore_preview(args.backup_id)
    return {"fingerprint": plan.fingerprint, "restorePlan": plan.to_dict()}


def _run_posix_backup_action(
    workspace: Path, args: argparse.Namespace
) -> dict[str, object]:
    client = open_coding_arch_private_data_backup_client(workspace)
    if args.action == "preview":
        deletion_plan = client._preview_deletion()
        return {
            "fingerprint": deletion_plan.fingerprint,
            "plan": deletion_plan.to_dict(),
        }
    if args.action == "restore-confirm":
        return {"restoreConfirmation": client.confirm_restore(args.backup_id).to_dict()}
    if args.action == "restore-confirm-verify":
        confirmation = client.verify_restore_confirmation(
            args.backup_id, args.confirmation_id
        )
        return {"restoreConfirmation": confirmation.to_dict()}
    if args.action == "backup-expiry-preview":
        plan = client.expiry_preview(args.backup_id, args.confirmation_id)
        return _backup_expiry_preview_document(plan)
    return _run_backup_access(client, args)


def _backup_expiry_preview_document(
    plan: CodingArchPrivateDataBackupExpiryPlanV1,
) -> dict[str, object]:
    return {"backupExpiryPlan": plan.to_dict(), "fingerprint": plan.fingerprint}


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
    if action in _BACKUP_ACCESS_ACTIONS:
        return _run_backup_access(client, args)
    if action == "preview":
        deletion_plan = client.deletion_preview()
        return {
            "fingerprint": deletion_plan.fingerprint,
            "plan": deletion_plan.to_dict(),
        }
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
        restore_result = client.restore(restore_plan)
        return {
            "restore": {
                "backupId": restore_result.backup_id,
                "disposition": restore_result.disposition,
                "restoreId": restore_result.restore_id,
            }
        }
    if action == "backup-expiry-preview":
        return _backup_expiry_preview_document(
            client.backup_expiry_preview(args.backup_id, args.confirmation_id)
        )
    if action == "backup-expiry-confirm":
        expiry_plan = _read_expiry_plan(Path(args.plan_file))
        if args.accept_fingerprint != expiry_plan.fingerprint:
            raise ValueError("Coding Arch backup expiry plan was not accepted")
        expiry_confirmation = client.backup_expiry_confirm(
            expiry_plan,
            actor_id="local-operator:windows-private-data-cli",
            policy_revision=_EXPIRY_POLICY_REVISION,
        )
        return {"expiryConfirmation": expiry_confirmation.to_dict()}
    if action == "backup-expire":
        expiry_plan = _read_expiry_plan(Path(args.plan_file))
        expiry_confirmation = _read_expiry_confirmation(Path(args.confirmation_file))
        return {
            "expiryReceipt": client.backup_expire(
                expiry_plan, expiry_confirmation
            ).to_dict()
        }
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
    current = owner.preview(key, plan.backup_id)
    if current != plan:
        if (
            plan.target_state != "absent"
            or current.target_state != "same_bytes"
            or replace(current, target_state="absent") != plan
        ):
            raise ValueError("Coding Arch restore plan is stale")
        restore_id = restore_id_for(key, plan.backup_id, plan.deletion_receipt_id)
        if not any(
            event.restore_id == restore_id
            for event in CodingArchPrivateDataRestoreJournal(
                product.state_root
            ).events()
        ):
            raise ValueError("Coding Arch restore plan has no prior start")
    result = owner.restore(key, plan.backup_id, expected_plan=plan)
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
    if args.action == "backup-expiry-confirm":
        if args.accept_fingerprint != plan.fingerprint:
            raise ValueError("Coding Arch backup expiry plan was not accepted")
        confirmation = owner.confirm(
            plan,
            actor_id=f"local-uid:{os.geteuid()}",
            policy_revision=_EXPIRY_POLICY_REVISION,
        )
        return {"expiryConfirmation": confirmation.to_dict()}
    confirmation = _read_expiry_confirmation(Path(args.confirmation_file))
    receipt = owner.expire(plan, confirmation)
    return {"expiryReceipt": receipt.to_dict()}


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
    document = _read_json(path)
    if type(document) is not dict or set(document) != {"fingerprint", "plan"}:
        raise ValueError("Coding private-data preview document is invalid")
    plan = PluginPrivateDataDeletionPlanV1.from_dict(document["plan"])
    if document["fingerprint"] != plan.fingerprint:
        raise ValueError("Coding private-data preview fingerprint changed")
    return plan


def _read_confirmation(path: Path) -> PluginPrivateDataDeletionConfirmationV1:
    document = _read_json(path)
    if type(document) is not dict or set(document) != {"confirmation"}:
        raise ValueError("Coding private-data confirmation document is invalid")
    return PluginPrivateDataDeletionConfirmationV1.from_dict(document["confirmation"])


def _read_restore_plan(path: Path) -> CodingArchPrivateDataRestorePlanV1:
    document = _read_json(path)
    if type(document) is not dict or set(document) != {
        "fingerprint",
        "restorePlan",
    }:
        raise ValueError("Coding Arch restore preview document is invalid")
    plan = CodingArchPrivateDataRestorePlanV1.from_dict(document["restorePlan"])
    if document["fingerprint"] != plan.fingerprint:
        raise ValueError("Coding Arch restore preview fingerprint changed")
    return plan


def _read_expiry_plan(path: Path) -> CodingArchPrivateDataBackupExpiryPlanV1:
    document = _read_json(path)
    if type(document) is not dict or set(document) != {
        "backupExpiryPlan",
        "fingerprint",
    }:
        raise ValueError("Coding Arch backup expiry preview document is invalid")
    plan = CodingArchPrivateDataBackupExpiryPlanV1.from_dict(
        document["backupExpiryPlan"]
    )
    if document["fingerprint"] != plan.fingerprint:
        raise ValueError("Coding Arch backup expiry preview fingerprint changed")
    return plan


def _read_expiry_confirmation(
    path: Path,
) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
    document = _read_json(path)
    if type(document) is not dict or set(document) != {"expiryConfirmation"}:
        raise ValueError("Coding Arch backup expiry confirmation document is invalid")
    return CodingArchPrivateDataBackupExpiryConfirmationV1.from_dict(
        document["expiryConfirmation"]
    )


def _read_json(path: Path) -> object:
    with path.open("rb") as handle:
        content = handle.read(_MAX_INPUT_BYTES + 1)
    if len(content) > _MAX_INPUT_BYTES:
        raise ValueError("Coding private-data command input is too large")
    return json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)


_unique_object = _unique_json_object_hook(
    lambda: 'Coding private-data command has duplicate JSON keys',
)


if __name__ == "__main__":
    raise SystemExit(main())
