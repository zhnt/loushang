from __future__ import annotations

import os
from importlib.metadata import version
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_repair import (
    CodingPackageRepairError,
    _perform_coding_package_repair,
    open_coding_package_repair_client,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    open_coding_fenced_product_application_owner,
)
from loushang.harness.config.agent import SettingsManager


def test_package_repair_client_refuses_replaced_workspace_before_product_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    client = open_coding_package_repair_client(workspace, runtime_version="2.0.0")
    workspace.rename(tmp_path / "moved-workspace")
    workspace.mkdir()

    with pytest.raises(CodingPackageRepairError) as changed:
        client.perform("repair-retryable", "operation:one")
    assert changed.value.code == "package_repair_workspace_changed"
    assert not (tmp_path / "home").exists()


def test_package_repair_client_rejects_bad_operation_before_product_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    client = open_coding_package_repair_client(workspace, runtime_version="2.0.0")

    with pytest.raises(CodingPackageRepairError) as invalid:
        client.perform("repair-retryable", " operation:one ")
    assert invalid.value.code == "package_repair_invalid_operation_id"
    assert not (tmp_path / "home").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Package repair SDK")
def test_package_repair_client_refuses_workspace_replaced_after_product_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    cutover_and_bootstrap_coding_package_product(
        layout,
        SettingsManager(
            global_settings_path=tmp_path / "global-settings.json",
            project_settings_path=workspace / ".loushang" / "settings.json",
        ),
        workspace=workspace,
        namespace_id="c" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    client = open_coding_package_repair_client(workspace)

    def replace_after_open(*args: object, **kwargs: object):
        owner = open_coding_fenced_product_application_owner(*args, **kwargs)
        workspace.rename(tmp_path / "moved-workspace")
        workspace.mkdir(mode=0o700)
        return owner

    with pytest.raises(CodingPackageRepairError) as changed:
        _perform_coding_package_repair(
            client,
            "repair-retryable",
            "operation:missing",
            owner_factory=replace_after_open,
        )
    assert changed.value.code == "package_repair_workspace_changed"
    assert list(workspace.iterdir()) == []
