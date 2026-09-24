from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
    reopen_coding_package_cutover,
)
from loushang.harness.config.agent import SettingsManager


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_empty_coding_workspace_prepares_private_roots_and_cuts_over(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    for root in (
        lifecycle.root,
        lifecycle.package_root,
        epoch.control_root,
        epoch.snapshot_root,
        epoch.epochs_root,
    ):
        assert stat.S_IMODE(root.lstat().st_mode) == 0o700
    assert cutover.attempt.result.disposition == "fenced"
    assert reopen_coding_package_cutover(lifecycle) == cutover.attempt.result


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_cutover_preparation_refuses_unsafe_existing_base_without_rewriting(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    private_base = tmp_path / "session-state"
    private_base.mkdir(mode=0o700)
    private_base.chmod(0o775)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        private_base, cwd=workspace
    )

    with pytest.raises(ValueError, match="not private"):
        prepare_coding_package_cutover_roots(lifecycle)

    assert stat.S_IMODE(private_base.lstat().st_mode) == 0o775
    assert not lifecycle.root.exists()
    assert not lifecycle.package_root.exists()
