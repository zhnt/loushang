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

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_private_data_backup import (
    CodingArchPrivateDataBackupOwner,
)
from loushang.coding.package_private_data_backup_expiry import (
    CodingArchPrivateDataBackupExpiryOwner,
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from loushang.coding.package_private_data_backup_expiry_journal import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
)
from loushang.coding.package_private_data_backup_sdk import (
    open_coding_arch_private_data_backup_client,
)
from loushang.coding.package_private_data_deletion_owner import (
    CodingArchPrivateDataDeletionOwner,
)
from loushang.coding.package_private_data_read_owner import (
    CodingArchPrivateDataReadOwner,
)
from loushang.coding.package_private_data_restore import (
    CodingArchPrivateDataRestoreOwner,
    CodingArchPrivateDataRestorePlanV1,
)
from loushang.coding.package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreJournal,
    restore_id_for,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    CodingFencedProductApplicationOwner,
    open_coding_fenced_product_application_owner,
    open_coding_package_product_state,
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
_PLUGIN_ID = "coding.arch.default"
_MAX_INPUT_BYTES = 16 * 1024


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
    restore_confirm_verify = commands.add_parser(
        "restore-confirm-verify", help="reopen one exact restore confirmation"
    )
    restore_confirm_verify.add_argument("--backup-id", required=True)
    restore_confirm_verify.add_argument("--confirmation-id", required=True)
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

    if os.name != "posix" or not sys.platform.startswith("linux"):
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
        if args.action == "backup-status":
            record = open_coding_arch_private_data_backup_client(workspace).status()
            sys.stdout.write(
                json.dumps({"backupRetention": record.to_dict()}, sort_keys=True) + "\n"
            )
            return 0
        if args.action in {
            "backup-verify",
            "preview",
            "restore-preview",
            "restore-confirm-verify",
            "backup-expiry-preview",
        }:
            identity = workspace.lstat()
            reader = CodingArchPrivateDataReadOwner.open(
                layout=layout,
                workspace=workspace,
                workspace_identity=(identity.st_dev, identity.st_ino),
            )
            try:
                read_result: dict[str, object]
                key = PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=layout.scope_id,
                    plugin_id=_PLUGIN_ID,
                )
                if args.action == "backup-verify":
                    receipt = reader.verify_backup(key, args.backup_id)
                    read_result = {"backupReceipt": receipt.to_dict()}
                elif args.action == "preview":
                    read_plan = reader.deletion_preview(key)
                    read_result = {
                        "fingerprint": read_plan.fingerprint,
                        "plan": read_plan.to_dict(),
                    }
                elif args.action == "restore-preview":
                    restore_plan = reader.restore_preview(key, args.backup_id)
                    read_result = {
                        "fingerprint": restore_plan.fingerprint,
                        "restorePlan": restore_plan.to_dict(),
                    }
                elif args.action == "restore-confirm-verify":
                    confirmation = reader.verify_restore_confirmation(
                        key, args.backup_id, args.confirmation_id
                    )
                    read_result = {"restoreConfirmation": confirmation.to_dict()}
                else:
                    expiry_plan = reader.expiry_preview(
                        key, args.backup_id, args.confirmation_id
                    )
                    read_result = {
                        "backupExpiryPlan": expiry_plan.to_dict(),
                        "fingerprint": expiry_plan.fingerprint,
                    }
            finally:
                reader.close()
            sys.stdout.write(json.dumps(read_result, sort_keys=True) + "\n")
            return 0
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
            result: dict[str, object]
            if args.action == "backup":
                key = PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=layout.scope_id,
                    plugin_id=_PLUGIN_ID,
                )
                receipt = CodingArchPrivateDataBackupOwner(
                    layout, product
                ).retain(key)
                result = {"backupReceipt": receipt.to_dict()}
            elif args.action == "restore":
                result = _run_restore(layout, product, args)
            elif args.action == "restore-confirm":
                key = PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=layout.scope_id,
                    plugin_id=_PLUGIN_ID,
                )
                owner = CodingArchPrivateDataRestoreOwner(layout, product)
                confirmation = owner.confirm(key, args.backup_id)
                result = {"restoreConfirmation": confirmation.to_dict()}
            elif args.action in {"backup-expiry-confirm", "backup-expire"}:
                result = _run_backup_expiry(layout, product, args)
            else:
                result = _run_product_action(layout, application, product, args)
        finally:
            application.close()
    except (OSError, RuntimeError, ValueError, PackageNotFoundError):
        sys.stderr.write("Coding private-data command refused: operation_refused\n")
        return 1
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


def _run_restore(
    layout: CodingPluginLifecycleStateLayout,
    product: PosixLocalWheelProductSessionOwner,
    args: argparse.Namespace,
) -> dict[str, object]:
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id=_PLUGIN_ID,
    )
    owner = CodingArchPrivateDataRestoreOwner(layout, product)
    if args.action == "restore-preview":
        plan = owner.preview(key, args.backup_id)
        return {"fingerprint": plan.fingerprint, "restorePlan": plan.to_dict()}
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
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id=_PLUGIN_ID,
    )
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
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id=_PLUGIN_ID,
    )
    return _run(coordinator, state.private_data_confirmation, key, args)


def _run(
    coordinator: PluginPrivateDataDeletionCoordinator,
    confirmations: PluginPrivateDataConfirmationJournal,
    key: PluginInstallationKeyV1,
    args: argparse.Namespace,
) -> dict[str, object]:
    if args.action == "preview":
        plan = coordinator.preview(key)
        return {"fingerprint": plan.fingerprint, "plan": plan.to_dict()}
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


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Coding private-data command has duplicate JSON keys")
        result[key] = value
    return result


if __name__ == "__main__":
    raise SystemExit(main())
