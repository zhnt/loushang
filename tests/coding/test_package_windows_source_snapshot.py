from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from time import sleep

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.control import SettingsManager
from loushang.coding.package_legacy_classification import (
    CodingScopedLegacyDisableV1,
    classify_coding_legacy_source_configuration,
)
from loushang.coding.package_pre_b_snapshot import (
    hold_coding_pre_b_snapshot_owner,
    prepare_coding_package_cutover_roots,
)
from loushang.coding.package_source_snapshot import (
    hold_coding_pre_b_source_configuration,
    read_coding_settings_patch_without_writes,
)
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    prepare_windows_product_control_root,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")


def test_windows_settings_read_accepts_a_previously_modified_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"{}")
    # Separate creation and change timestamps even on a fast Windows runner.
    sleep(0.05)
    raw = b'{"theme":"dark"}\n'
    path.write_bytes(raw)

    assert read_coding_settings_patch_without_writes(path) == (
        True,
        sha256(raw).hexdigest(),
        {"theme": "dark"},
    )


def test_windows_source_projection_pins_real_settings_and_private_bytes(
    tmp_path: Path,
) -> None:
    global_path = tmp_path / "global" / "settings.json"
    project_path = tmp_path / "project" / ".loushang" / "settings.json"
    global_path.parent.mkdir()
    project_path.parent.mkdir(parents=True)
    global_raw = b'{"plugin_sources":["C:/plugins/old"],"theme":"dark"}\n'
    project_raw = b'{"disabled_plugins":["old"]}\n'
    global_path.write_bytes(global_raw)
    project_path.write_bytes(project_raw)
    parent = tmp_path / "projections"
    prepare_windows_product_control_root(parent)
    manager = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )

    with hold_coding_pre_b_source_configuration(
        manager,
        global_settings_path=global_path,
        project_settings_path=project_path,
        projection_parent=parent,
    ) as source_root:
        projection = json.loads(
            (source_root / "coding-source-configuration.json").read_bytes()
        )
        assert projection["scopes"]["global"]["sourcePatch"] == {
            "plugin_sources": ["C:/plugins/old"]
        }
        assert (
            projection["scopes"]["global"]["rawSha256"]
            == sha256(global_raw).hexdigest()
        )
        assert projection["scopes"]["project"]["sourcePatch"] == {
            "disabled_plugins": ["old"]
        }
        assert (
            projection["scopes"]["project"]["rawSha256"]
            == sha256(project_raw).hexdigest()
        )
        classified = classify_coding_legacy_source_configuration(projection)
        assert classified.configured_source_keys == ("global:plugin_sources",)
        assert classified.disabled_plugins == (
            CodingScopedLegacyDisableV1("project", "old"),
        )
        projection["scopes"]["global"]["settingsPath"] = "global/settings.json"
        with pytest.raises(ValueError, match="projection layer is invalid"):
            classify_coding_legacy_source_configuration(projection)
        with WindowsPrivateDirectoryAcl() as acl:
            pinned = _PinnedWindowsAuthority.open(source_root, read_control=True)
            try:
                acl.validate(pinned.descriptor)
                descriptor = open_windows_regular_file_at(
                    pinned.descriptor,
                    "coding-source-configuration.json",
                    create_new=False,
                    write=False,
                    read_control=True,
                )
                try:
                    acl.validate(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                pinned.close()
    assert not source_root.exists()


def test_windows_source_projection_refuses_session_override_before_creation(
    tmp_path: Path,
) -> None:
    global_path = tmp_path / "global" / "settings.json"
    project_path = tmp_path / "project" / "settings.json"
    global_path.parent.mkdir()
    project_path.parent.mkdir()
    parent = tmp_path / "projections"
    prepare_windows_product_control_root(parent)
    manager = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    manager.update_settings(scope="session", plugin_sources=())

    with pytest.raises(ValueError, match="session Source overrides"):
        with hold_coding_pre_b_source_configuration(
            manager,
            global_settings_path=global_path,
            project_settings_path=project_path,
            projection_parent=parent,
        ):
            pytest.fail("transient Source override must be rejected")
    assert not list(parent.iterdir())


def test_windows_snapshot_preparation_reads_long_source_projection_path(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    prepare_coding_package_cutover_roots(lifecycle)
    manager = SettingsManager(
        global_settings_path=tmp_path / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    parent = tmp_path / ("projection-" + "x" * 90)
    prepare_windows_product_control_root(parent)

    with hold_coding_pre_b_snapshot_owner(
        lifecycle, manager, projection_parent=parent
    ) as prepared:
        source = prepared.source_configuration_root / "coding-source-configuration.json"
        assert len(str(source)) > 260
        assert prepared.legacy_classification.kind == "fresh"
