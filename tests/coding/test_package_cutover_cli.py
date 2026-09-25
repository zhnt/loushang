from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.cli.package_cutover import main as cutover_main
from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    open_coding_fenced_product_application_owner,
)
from loushang.foundation.platform_paths import resolve_platform_paths


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_command_fences_persistent_workspace_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}
    command = (
        sys.executable,
        "-m",
        "loushang.coding.cli.package_cutover",
        "--workspace",
        str(workspace),
    )

    first = subprocess.run(
        command,
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    assert result["disposition"] == "fenced"
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace, platform_paths=resolve_platform_paths(environ=environ)
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert result["storeId"] == epoch.store_id
    assert len(result["namespaceId"]) == 64
    fence_bytes = (epoch.control_root / "epoch.jsonl").read_bytes()

    second = subprocess.run(
        command,
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == result
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_bytes

    monkeypatch.setenv("LOUSHANG_HOME", environ["LOUSHANG_HOME"])
    with patch("loushang.coding.cli.package_cutover.version", return_value="9.0.0"):
        assert cutover_main(("--workspace", str(workspace))) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_bytes

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        selected = owner.runtime_owner.product_owner.desired_state.snapshot()
        assert {
            item.installation_key.plugin_id
            for item in selected.installations
            if item.selection.desired_state == "installed_enabled"
        } == {"coding.base", "coding.lsp.default", "coding.arch.default"}
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_offline_command_refuses_legacy_disabled_setting_before_fence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    project_config = workspace / ".loushang"
    project_config.mkdir(mode=0o700)
    (project_config / "settings.json").write_text(
        json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
    )
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "loushang.coding.cli.package_cutover",
            "--workspace",
            str(workspace),
        ),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert "explicit migration" in result.stderr
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace, platform_paths=resolve_platform_paths(environ=environ)
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    assert not (epoch.control_root / "epoch.jsonl").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_cutover_backup_status_reads_exact_snapshot_owner_without_expiry_claim(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    environ = {**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")}
    command = (
        sys.executable,
        "-m",
        "loushang.coding.cli.package_cutover",
        "--workspace",
        str(workspace),
    )
    initial = subprocess.run(
        command, env=environ, capture_output=True, text=True, check=False, timeout=90
    )
    assert initial.returncode == 0, initial.stderr
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace, platform_paths=resolve_platform_paths(environ=environ)
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    fence_before = (epoch.control_root / "epoch.jsonl").read_bytes()
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        desired_path = owner.runtime_owner.product_owner.desired_state.path
        desired_before = desired_path.read_bytes()
    finally:
        owner.close()

    status = subprocess.run(
        (*command, "--backup-status"),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert status.returncode == 0, status.stderr
    verified = json.loads(status.stdout)
    assert verified["backupKind"] == "pre_b_workspace_snapshot"
    assert verified["status"] == "retained"
    assert verified["expiryStatus"] == "unknown"
    assert verified["snapshotReceiptId"]
    assert str(workspace) not in status.stdout
    assert str(epoch.snapshot_root) not in status.stdout
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_before
    assert desired_path.read_bytes() == desired_before

    evidence_file = epoch.snapshot_root / (
        verified["snapshotReceiptId"] + ".evidence.json"
    )
    evidence_file.rename(evidence_file.with_suffix(".unavailable"))
    missing = subprocess.run(
        (*command, "--backup-status"),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert missing.returncode == 0, missing.stderr
    unknown = json.loads(missing.stdout)
    assert unknown["status"] == "unknown"
    assert unknown["reason"] == "snapshot_evidence_missing"
    assert unknown["entryCount"] is None
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_before
    assert desired_path.read_bytes() == desired_before

    evidence_file.with_suffix(".unavailable").rename(evidence_file)
    evidence_file.write_bytes(b"{}\n")
    corrupted = subprocess.run(
        (*command, "--backup-status"),
        env=environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert corrupted.returncode == 1
    assert corrupted.stdout == ""
    assert (epoch.control_root / "epoch.jsonl").read_bytes() == fence_before
    assert desired_path.read_bytes() == desired_before
