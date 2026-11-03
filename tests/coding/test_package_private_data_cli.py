from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from importlib.metadata import version
from io import StringIO
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.cli.plugin_private_data import main as private_data_main
from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package_installation_private_data import (
    coding_arch_installation_private_data_root,
    prepare_coding_product_arch_private_data_root,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_private_data_backup import (
    CodingArchPrivateDataBackupOwner,
    CodingArchPrivateDataBackupReadSource,
)
from loushang.coding.package_private_data_backup_expiry import (
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from loushang.coding.package_private_data_backup_sdk import (
    open_coding_arch_private_data_backup_client,
)
from loushang.coding.package_private_data_restore import (
    CodingArchPrivateDataRestorePlanV1,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.plugin_management_read_sdk import (
    bind_coding_plugin_management_rpc_query,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.host.rpc.commands.plugin_management_snapshot import (
    RpcPluginManagementSnapshotCommands,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementCommandV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data CLI")
@pytest.mark.parametrize(
    ("run_expiry", "sdk_lifecycle"),
    ((False, False), (True, False), (True, True)),
)
def test_cli_preview_confirm_delete_uses_fenced_product_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    run_expiry: bool,
    sdk_lifecycle: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    installed_version = version("loushang")
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version=installed_version,
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id="coding.arch.default",
    )
    app = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=installed_version,
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "session", cwd=str(workspace), persist=True
        )
    )
    session_id = manager.get_header().conversation_id
    runtime = app.factory_for_session(manager).create(
        PackageProductRuntimeRequestV1(
            product_id="coding", session_id=session_id, cwd=str(workspace)
        )
    )
    try:
        runtime.activate()
        private_root = prepare_coding_product_arch_private_data_root(
            layout, runtime, session_id=session_id
        )
        (private_root / "cache.json").write_text("private", encoding="utf-8")
        if not run_expiry:
            with pytest.raises(ValueError, match="runtime is active"):
                CodingArchPrivateDataBackupOwner(
                    layout, app.runtime_owner.product_owner
                ).retain(key)
            with pytest.raises(ValueError, match="runtime is active"):
                open_coding_arch_private_data_backup_client(workspace).verify(
                    "0" * 64
                )
    finally:
        runtime.dispose_runtime()
        app.close()
    installation_root = coding_arch_installation_private_data_root(layout, key)
    common = ["--workspace", str(workspace), "--plugin-id", "coding.arch.default"]

    def rpc_backup_status() -> str:
        output = StringIO()
        RpcPluginManagementSnapshotCommands(
            get_cwd=lambda: str(workspace),
            bind_query=bind_coding_plugin_management_rpc_query,
            output=RpcOutput(output),
        ).snapshot(
            "rpc:backup-status",
            {
                "productId": "coding",
                "scopeId": layout.scope_id,
                "pluginIds": ["coding.arch.default"],
            },
        )
        [response] = [json.loads(line) for line in output.getvalue().splitlines()]
        assert response["success"] is True
        [installation] = response["data"]["installations"]
        assert installation["installationKey"] == key.to_dict()
        return installation["backupRetention"]["status"]

    backup_client = (
        open_coding_arch_private_data_backup_client(workspace)
        if not run_expiry or sdk_lifecycle
        else None
    )
    sdk_receipt = backup_client.retain() if backup_client is not None else None
    assert private_data_main([*common, "backup"]) == 0
    backup_receipt = json.loads(capsys.readouterr().out)["backupReceipt"]
    assert backup_receipt["installationKey"] == key.to_dict()
    if backup_client is not None:
        assert sdk_receipt is not None
        assert sdk_receipt.to_dict() == backup_receipt
        assert backup_client.verify(sdk_receipt.backup_id) == sdk_receipt
        assert backup_client.status().status == "retained"
    assert private_data_main([*common, "backup-status"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["backupRetention"]["status"] == "retained"
    )
    assert rpc_backup_status() == "retained"
    restarted_status = subprocess.run(
        [
            sys.executable,
            "-m",
            "loushang.coding.cli.plugin_private_data",
            *common,
            "backup-status",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert restarted_status.returncode == 0, restarted_status.stderr
    assert (
        json.loads(restarted_status.stdout)["backupRetention"]["status"] == "retained"
    )
    archive = (
        layout.package_root
        / "installation-backups"
        / installation_root.name
        / backup_receipt["backupId"]
    )
    archived_file = next(archive.glob("files/sessions/*/cache.json"))
    archived_file.write_text("tampered", encoding="utf-8")
    if backup_client is not None:
        with pytest.raises((OSError, ValueError)):
            backup_client.verify(backup_receipt["backupId"])
        assert backup_client.status().status == "unknown"
    tampered_status = subprocess.run(
        [
            sys.executable,
            "-m",
            "loushang.coding.cli.plugin_private_data",
            *common,
            "backup-status",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert tampered_status.returncode == 0, tampered_status.stderr
    assert json.loads(tampered_status.stdout)["backupRetention"]["status"] == "unknown"
    assert rpc_backup_status() == "unknown"
    archived_file.write_text("private", encoding="utf-8")

    assert private_data_main([*common, "preview"]) == 0
    preview_output = capsys.readouterr()
    preview = json.loads(preview_output.out)
    assert preview_output.err == ""
    assert preview["plan"]["targetId"].startswith("present:")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(preview_output.out, encoding="utf-8")

    assert (
        private_data_main(
            [
                *common,
                "confirm",
                "--plan-file",
                str(plan_file),
                "--accept-fingerprint",
                "0" * 64,
            ]
        )
        == 1
    )
    assert capsys.readouterr().out == ""
    assert installation_root.is_dir()
    assert (
        private_data_main(
            [
                *common,
                "confirm",
                "--plan-file",
                str(plan_file),
                "--accept-fingerprint",
                preview["fingerprint"],
            ]
        )
        == 0
    )
    confirmation_output = capsys.readouterr()
    confirmation = json.loads(confirmation_output.out)
    confirmation_file = tmp_path / "confirmation.json"
    confirmation_file.write_text(confirmation_output.out, encoding="utf-8")

    delete_args = [
        *common,
        "delete",
        "--plan-file",
        str(plan_file),
        "--confirmation-file",
        str(confirmation_file),
    ]
    assert private_data_main(delete_args) == 1
    assert capsys.readouterr().out == ""
    assert installation_root.is_dir()

    app = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=installed_version,
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        product = app.runtime_owner.product_owner
        selected = product.desired_state.snapshot()
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:remove-for-cli-delete",
                    idempotency_key="operator:remove-for-cli-delete",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
    finally:
        app.close()

    assert private_data_main(delete_args) == 0
    first_receipt = json.loads(capsys.readouterr().out)["receipt"]
    assert first_receipt["disposition"] == "deleted"
    assert not installation_root.exists()
    assert private_data_main(delete_args) == 0
    assert json.loads(capsys.readouterr().out)["receipt"] == first_receipt
    assert confirmation["confirmation"]["planFingerprint"] == preview["fingerprint"]
    assert private_data_main([*common, "backup-status"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["backupRetention"]["status"] == "retained"
    )
    verify_args = [
        sys.executable,
        "-m",
        "loushang.coding.cli.plugin_private_data",
        *common,
        "backup-verify",
        "--backup-id",
        backup_receipt["backupId"],
    ]
    verified = subprocess.run(verify_args, capture_output=True, text=True, check=False)
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["backupReceipt"] == backup_receipt
    restore_preview = subprocess.run(
        [
            sys.executable,
            "-m",
            "loushang.coding.cli.plugin_private_data",
            *common,
            "restore-preview",
            "--backup-id",
            backup_receipt["backupId"],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert restore_preview.returncode == 0, restore_preview.stderr
    restore_plan = json.loads(restore_preview.stdout)
    assert restore_plan["restorePlan"]["targetState"] == "absent"
    if sdk_lifecycle:
        assert backup_client is not None
        assert (
            backup_client.restore_preview(backup_receipt["backupId"]).to_dict()
            == (restore_plan["restorePlan"])
        )
    assert not installation_root.exists()
    assert not (
        resolve_coding_package_epoch_layout(layout).control_root
        / "product-state"
        / "private-data-restores.jsonl"
    ).exists()
    restore_plan_file = tmp_path / "restore-plan.json"
    restore_plan_file.write_text(restore_preview.stdout, encoding="utf-8")
    restore_confirm_args = [
        sys.executable,
        "-m",
        "loushang.coding.cli.plugin_private_data",
        *common,
        "restore-confirm",
        "--backup-id",
        backup_receipt["backupId"],
    ]
    expiry_preview_args = [
        sys.executable,
        "-m",
        "loushang.coding.cli.plugin_private_data",
        *common,
        "backup-expiry-preview",
        "--backup-id",
        backup_receipt["backupId"],
        "--confirmation-id",
        "missing",
    ]
    premature_expiry = subprocess.run(
        expiry_preview_args, capture_output=True, text=True, check=False
    )
    assert premature_expiry.returncode == 1
    assert premature_expiry.stdout == ""
    premature_confirmation = subprocess.run(
        restore_confirm_args, capture_output=True, text=True, check=False
    )
    assert premature_confirmation.returncode == 1
    assert premature_confirmation.stdout == ""
    assert not (
        resolve_coding_package_epoch_layout(layout).control_root
        / "product-state"
        / "private-data-restore-confirmations.jsonl"
    ).exists()
    restore_args = [
        sys.executable,
        "-m",
        "loushang.coding.cli.plugin_private_data",
        *common,
        "restore",
        "--plan-file",
        str(restore_plan_file),
        "--accept-fingerprint",
        restore_plan["fingerprint"],
    ]
    wrong_fingerprint = subprocess.run(
        [*restore_args[:-1], "0" * 64],
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_fingerprint.returncode == 1
    assert wrong_fingerprint.stdout == ""
    assert not installation_root.exists()
    if sdk_lifecycle:
        assert backup_client is not None
        assert (
            backup_client.restore(
                CodingArchPrivateDataRestorePlanV1.from_dict(
                    restore_plan["restorePlan"]
                )
            ).disposition
            == "restored"
        )
    else:
        restored = subprocess.run(
            restore_args, capture_output=True, text=True, check=False
        )
        assert restored.returncode == 0, restored.stderr
        assert json.loads(restored.stdout)["restore"]["disposition"] == "restored"
    restored_file = next(installation_root.glob("sessions/*/cache.json"))
    assert restored_file.read_text(encoding="utf-8") == "private"
    replay = subprocess.run(restore_args, capture_output=True, text=True, check=False)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["restore"]["disposition"] == "already_present"
    sdk_restore_confirmation = (
        backup_client.confirm_restore(backup_receipt["backupId"])
        if sdk_lifecycle and backup_client is not None
        else None
    )
    confirmed_restore = subprocess.run(
        restore_confirm_args, capture_output=True, text=True, check=False
    )
    assert confirmed_restore.returncode == 0, confirmed_restore.stderr
    restore_confirmation = json.loads(confirmed_restore.stdout)["restoreConfirmation"]
    assert restore_confirmation["confirmationId"].startswith("arch-restore-confirm:")
    if sdk_restore_confirmation is not None:
        assert sdk_restore_confirmation.to_dict() == restore_confirmation
        assert backup_client is not None
        assert (
            backup_client.verify_restore_confirmation(
                backup_receipt["backupId"], restore_confirmation["confirmationId"]
            )
            == sdk_restore_confirmation
        )
    expiry_preview_args[-1] = restore_confirmation["confirmationId"]
    expiry_preview = subprocess.run(
        expiry_preview_args, capture_output=True, text=True, check=False
    )
    assert expiry_preview.returncode == 0, expiry_preview.stderr
    expiry_plan = json.loads(expiry_preview.stdout)
    assert expiry_plan["backupExpiryPlan"]["backupReceiptId"] == (
        "arch-backup:" + backup_receipt["backupId"]
    )
    if sdk_lifecycle:
        assert backup_client is not None
        assert (
            backup_client.expiry_preview(
                backup_receipt["backupId"], restore_confirmation["confirmationId"]
            ).to_dict()
            == expiry_plan["backupExpiryPlan"]
        )
    replayed_expiry_preview = subprocess.run(
        expiry_preview_args, capture_output=True, text=True, check=False
    )
    assert replayed_expiry_preview.returncode == 0
    assert json.loads(replayed_expiry_preview.stdout) == expiry_plan
    restore_confirm_verify_args = [
        sys.executable,
        "-m",
        "loushang.coding.cli.plugin_private_data",
        *common,
        "restore-confirm-verify",
        "--backup-id",
        backup_receipt["backupId"],
        "--confirmation-id",
        restore_confirmation["confirmationId"],
    ]
    verified_restore = subprocess.run(
        restore_confirm_verify_args, capture_output=True, text=True, check=False
    )
    assert verified_restore.returncode == 0, verified_restore.stderr
    assert json.loads(verified_restore.stdout)["restoreConfirmation"] == (
        restore_confirmation
    )
    if run_expiry:
        expiry_plan_file = tmp_path / "expiry-plan.json"
        expiry_plan_file.write_text(expiry_preview.stdout, encoding="utf-8")
        expiry_confirm_args = [
            sys.executable,
            "-m",
            "loushang.coding.cli.plugin_private_data",
            *common,
            "backup-expiry-confirm",
            "--plan-file",
            str(expiry_plan_file),
            "--accept-fingerprint",
            expiry_plan["fingerprint"],
        ]
        refused_confirm = subprocess.run(
            [*expiry_confirm_args[:-1], "0" * 64],
            capture_output=True,
            text=True,
            check=False,
        )
        assert refused_confirm.returncode == 1
        assert refused_confirm.stdout == ""
        if sdk_lifecycle:
            assert backup_client is not None
            sdk_expiry_plan = CodingArchPrivateDataBackupExpiryPlanV1.from_dict(
                expiry_plan["backupExpiryPlan"]
            )
            sdk_expiry_confirmation = backup_client.confirm_expiry(sdk_expiry_plan)
            expiry_confirmation = sdk_expiry_confirmation.to_dict()
            accepted_expiry_output = json.dumps(
                {"expiryConfirmation": expiry_confirmation}
            )
        else:
            accepted_expiry = subprocess.run(
                expiry_confirm_args, capture_output=True, text=True, check=False
            )
            assert accepted_expiry.returncode == 0, accepted_expiry.stderr
            expiry_confirmation = json.loads(accepted_expiry.stdout)[
                "expiryConfirmation"
            ]
            accepted_expiry_output = accepted_expiry.stdout
        expiry_confirmation_file = tmp_path / "expiry-confirmation.json"
        expiry_confirmation_file.write_text(accepted_expiry_output, encoding="utf-8")
        expiry_args = [
            sys.executable,
            "-m",
            "loushang.coding.cli.plugin_private_data",
            *common,
            "backup-expire",
            "--plan-file",
            str(expiry_plan_file),
            "--confirmation-file",
            str(expiry_confirmation_file),
        ]
        sdk_expiry_receipt = (
            backup_client.expire(sdk_expiry_plan, sdk_expiry_confirmation)
            if sdk_lifecycle and backup_client is not None
            else None
        )
        expired = subprocess.run(
            expiry_args, capture_output=True, text=True, check=False
        )
        assert expired.returncode == 0, expired.stderr
        expiry_receipt = json.loads(expired.stdout)["expiryReceipt"]
        if sdk_expiry_receipt is not None:
            assert sdk_expiry_receipt.to_dict() == expiry_receipt
        assert (
            expiry_receipt["confirmationId"] == (expiry_confirmation["confirmationId"])
        )
        assert not archive.exists()
        repeated_expiry = subprocess.run(
            expiry_args, capture_output=True, text=True, check=False
        )
        assert repeated_expiry.returncode == 0, repeated_expiry.stderr
        assert json.loads(repeated_expiry.stdout)["expiryReceipt"] == expiry_receipt
        assert private_data_main([*common, "backup-status"]) == 0
        retention = json.loads(capsys.readouterr().out)["backupRetention"]
        assert retention["status"] == "expired"
        assert retention["expiryReceiptId"] == expiry_receipt["receiptId"]
        return
    restored_file.write_text("changed", encoding="utf-8")
    changed_target = subprocess.run(
        restore_args, capture_output=True, text=True, check=False
    )
    assert changed_target.returncode == 1
    assert restored_file.read_text(encoding="utf-8") == "changed"
    stale_confirmation = subprocess.run(
        restore_confirm_verify_args, capture_output=True, text=True, check=False
    )
    assert stale_confirmation.returncode == 1
    assert stale_confirmation.stdout == ""
    stale_expiry_preview = subprocess.run(
        expiry_preview_args, capture_output=True, text=True, check=False
    )
    assert stale_expiry_preview.returncode == 1
    assert stale_expiry_preview.stdout == ""
    restored_file.write_text("private", encoding="utf-8")
    archived_file.write_text("tampered", encoding="utf-8")
    refused = subprocess.run(verify_args, capture_output=True, text=True, check=False)
    assert refused.returncode == 1
    assert refused.stdout == ""
    refused_restore = subprocess.run(
        restore_args, capture_output=True, text=True, check=False
    )
    assert refused_restore.returncode == 1
    refused_confirmation = subprocess.run(
        restore_confirm_verify_args, capture_output=True, text=True, check=False
    )
    assert refused_confirmation.returncode == 1
    assert refused_confirmation.stdout == ""
    assert restored_file.read_text(encoding="utf-8") == "private"


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data CLI")
def test_cli_refuses_unopened_plugin_type_without_workspace_effect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert (
        private_data_main(
            [
                "--workspace",
                str(workspace),
                "--plugin-id",
                "coding.example",
                "preview",
            ]
        )
        == 1
    )
    assert "plugin_type_unopened" in capsys.readouterr().err
    assert list(workspace.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data SDK")
def test_backup_sdk_refuses_unfenced_workspace_without_cutover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    client = open_coding_arch_private_data_backup_client(workspace)
    with pytest.raises(ValueError, match="Product route is unavailable"):
        client.retain()
    with pytest.raises(ValueError, match="Product route is unavailable"):
        client.status()
    with pytest.raises(ValueError, match="Product route is unavailable"):
        client.restore_preview("0" * 64)
    with pytest.raises(ValueError, match="Product route is unavailable"):
        client.expiry_preview("0" * 64, "missing")
    assert list(workspace.iterdir()) == []
    assert not (tmp_path / "private-home").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data SDK")
def test_backup_sdk_status_refuses_partial_epoch_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="b" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    epoch = resolve_coding_package_epoch_layout(layout)
    journal = epoch.control_root / "epoch.jsonl"
    partial = journal.read_bytes() + b'{"unfinished":'
    journal.write_bytes(partial)
    (epoch.control_root / "epoch.jsonl.lock").unlink(missing_ok=True)
    before = tuple(sorted(path.name for path in epoch.control_root.iterdir()))
    client = open_coding_arch_private_data_backup_client(workspace)
    with pytest.raises((RuntimeError, ValueError)):
        client.status()
    assert journal.read_bytes() == partial
    assert tuple(sorted(path.name for path in epoch.control_root.iterdir())) == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data reader")
def test_private_data_reads_refuse_partial_epoch_without_product_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import loushang.coding.cli.plugin_private_data as private_cli_module
    import loushang.coding.package_private_data_backup_sdk as backup_sdk_module

    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="b" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    epoch = resolve_coding_package_epoch_layout(layout)
    journal = epoch.control_root / "epoch.jsonl"
    journal.write_bytes(journal.read_bytes() + b'{"unfinished":')
    client = open_coding_arch_private_data_backup_client(workspace)

    def forbid_product(*args: object, **kwargs: object) -> None:
        raise AssertionError("read command opened writable Product")

    monkeypatch.setattr(
        private_cli_module, "open_coding_fenced_product_application_owner", forbid_product
    )
    monkeypatch.setattr(
        backup_sdk_module, "open_coding_fenced_product_application_owner", forbid_product
    )

    def control_snapshot() -> tuple[tuple[str, int, bytes | None], ...]:
        return tuple(
            (
                str(path.relative_to(epoch.control_root)),
                path.lstat().st_mode,
                path.read_bytes() if path.is_file() else None,
            )
            for path in sorted(epoch.control_root.rglob("*"))
        )

    before = control_snapshot()
    sdk_reads = (
        lambda: client.verify("0" * 64),
        lambda: client.restore_preview("0" * 64),
        lambda: client.verify_restore_confirmation("0" * 64, "missing"),
        lambda: client.expiry_preview("0" * 64, "missing"),
    )
    for read in sdk_reads:
        with pytest.raises((OSError, RuntimeError, ValueError)):
            read()
        assert control_snapshot() == before
    common = ("--workspace", str(workspace), "--plugin-id", "coding.arch.default")
    cli_reads = (
        ("preview",),
        ("backup-verify", "--backup-id", "0" * 64),
        ("restore-preview", "--backup-id", "0" * 64),
        (
            "restore-confirm-verify",
            "--backup-id",
            "0" * 64,
            "--confirmation-id",
            "missing",
        ),
        (
            "backup-expiry-preview",
            "--backup-id",
            "0" * 64,
            "--confirmation-id",
            "missing",
        ),
    )
    for action in cli_reads:
        assert private_data_main([*common, *action]) == 1
        capsys.readouterr()
        assert control_snapshot() == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data reader")
@pytest.mark.parametrize(
    "missing_lock", ("coordination.lock", "product-state/gc-reservations.jsonl.lock")
)
def test_private_data_preview_refuses_missing_read_lock_without_creating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing_lock: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="b" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    epoch = resolve_coding_package_epoch_layout(layout)
    common = ("--workspace", str(workspace), "--plugin-id", "coding.arch.default")
    assert private_data_main([*common, "preview"]) == 0
    capsys.readouterr()
    lock = epoch.control_root / missing_lock
    assert lock.is_file()
    lock.unlink()
    before = tuple(
        (str(path.relative_to(epoch.control_root)), path.lstat().st_mode)
        for path in sorted(epoch.control_root.rglob("*"))
    )
    assert private_data_main([*common, "preview"]) == 1
    capsys.readouterr()
    assert not lock.exists()
    assert tuple(
        (str(path.relative_to(epoch.control_root)), path.lstat().st_mode)
        for path in sorted(epoch.control_root.rglob("*"))
    ) == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data reader")
@pytest.mark.parametrize(
    "partial_journal",
    ("desired-state.jsonl", "private-data-deletions.jsonl"),
)
def test_private_data_preview_refuses_partial_state_without_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    partial_journal: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="b" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    state_root = resolve_coding_package_epoch_layout(layout).control_root / "product-state"
    journal = state_root / partial_journal
    partial = (journal.read_bytes() if journal.exists() else b"") + b'{"unfinished":'
    journal.write_bytes(partial)
    before = tuple(sorted(path.name for path in state_root.iterdir()))
    assert private_data_main(
        ["--workspace", str(workspace), "--plugin-id", "coding.arch.default", "preview"]
    ) == 1
    capsys.readouterr()
    assert journal.read_bytes() == partial
    assert tuple(sorted(path.name for path in state_root.iterdir())) == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data SDK")
def test_backup_sdk_refuses_replaced_fenced_workspace_at_owner_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.package_private_data_backup_sdk as backup_sdk_module

    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="b" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    client = open_coding_arch_private_data_backup_client(workspace)
    original = tmp_path / "original-workspace"
    workspace.rename(original)
    workspace.mkdir(mode=0o700)
    before = tuple(workspace.rglob("*"))
    for action in (client.status, client.retain):
        with pytest.raises(RuntimeError) as changed:
            action()
        assert getattr(changed.value, "code", None) == (
            "coding_arch_backup_workspace_changed"
        )
    assert tuple(workspace.rglob("*")) == before

    workspace.rmdir()
    original.rename(workspace)
    open_product = backup_sdk_module.open_coding_fenced_product_application_owner

    def replace_after_product_open(*args: object, **kwargs: object):
        application = open_product(*args, **kwargs)
        workspace.rename(tmp_path / "moved-during-open")
        workspace.mkdir(mode=0o700)
        return application

    backup_root = layout.package_root / "installation-backups"
    before_backup = tuple(backup_root.rglob("*")) if backup_root.exists() else ()
    with monkeypatch.context() as patch:
        patch.setattr(
            backup_sdk_module,
            "open_coding_fenced_product_application_owner",
            replace_after_product_open,
        )
        with pytest.raises(RuntimeError) as changed_during_open:
            client.retain()
    assert getattr(changed_during_open.value, "code", None) == (
        "coding_arch_backup_workspace_changed"
    )
    assert (tuple(backup_root.rglob("*")) if backup_root.exists() else ()) == (
        before_backup
    )

    workspace.rmdir()
    (tmp_path / "moved-during-open").rename(workspace)
    read_status = backup_sdk_module.CodingArchPrivateDataBackupReadSource.snapshot

    def replace_after_status_read(source: CodingArchPrivateDataBackupReadSource):
        result = read_status(source)
        workspace.rename(tmp_path / "moved-during-status")
        workspace.mkdir(mode=0o700)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(
            backup_sdk_module.CodingArchPrivateDataBackupReadSource,
            "snapshot",
            replace_after_status_read,
        )
        with pytest.raises(RuntimeError) as changed_during_status:
            client.status()
    assert getattr(changed_during_status.value, "code", None) == (
        "coding_arch_backup_workspace_changed"
    )
