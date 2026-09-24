from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_legacy_classification import (
    CodingScopedLegacyDisableV1,
)
from loushang.coding.package_legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members,
)
from loushang.coding.package_legacy_source_evidence import (
    CodingLegacySourceEvidenceError,
    parse_coding_legacy_source_evidence,
    read_coding_legacy_source_evidence,
)
from loushang.coding.package_pre_b_snapshot import (
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
def test_first_b_source_settings_survive_mutable_settings_change(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    (lifecycle.package_root / "installed").mkdir(mode=0o700)
    global_path = tmp_path / "global-settings.json"
    project_path = workspace / ".loushang" / "settings.json"
    global_path.write_bytes(b'{"disabled_plugins":["coding.base"]}\n')
    project_path.parent.mkdir(mode=0o700, exist_ok=True)
    project_path.write_bytes(b'{"plugin_sources":["/original/plugins"]}\n')
    settings = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    (lifecycle.package_root / "installed").rmdir()
    global_path.write_bytes(b'{"disabled_plugins":[]}\n')
    project_path.write_bytes(b'{"plugin_sources":["/other/plugins"]}\n')
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        assert list_coding_first_b_snapshot_domain_members(
            lifecycle, owner, domain="binding_history"
        ) == ()
        assert list_coding_first_b_snapshot_domain_members(
            lifecycle, owner, domain="store_bytes"
        ) == ("installed",)
        evidence = read_coding_legacy_source_evidence(
            lifecycle,
            owner,
            global_settings_path=global_path,
            project_settings_path=project_path,
        )
        assert evidence.classification.disabled_plugins == (
            CodingScopedLegacyDisableV1("global", "coding.base"),
        )
        assert evidence.classification.configured_source_keys == (
            "project:plugin_sources",
        )
        assert evidence.source_patch("project") == {
            "plugin_sources": ["/original/plugins"]
        }
        evidence.source_patch("project")["plugin_sources"] = ["/mutated"]
        assert evidence.source_patch("project")["plugin_sources"] == [
            "/original/plugins"
        ]
        assert len(evidence.projection_digest) == 64
    finally:
        owner.close()


def test_source_projection_refuses_wrong_settings_paths_and_duplicate_keys(
    tmp_path: Path,
) -> None:
    global_path = tmp_path / "global.json"
    project_path = tmp_path / "project.json"
    raw = json.dumps(
        {
            "productId": "coding",
            "projectionVersion": 1,
            "scopes": {
                scope: {
                    "present": False,
                    "rawSha256": None,
                    "settingsPath": str(path),
                    "sourcePatch": {},
                }
                for scope, path in (("global", global_path), ("project", project_path))
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert (
        parse_coding_legacy_source_evidence(
            raw, global_settings_path=global_path, project_settings_path=project_path
        ).classification.configured_source_keys
        == ()
    )
    with pytest.raises(CodingLegacySourceEvidenceError):
        parse_coding_legacy_source_evidence(
            raw,
            global_settings_path=tmp_path / "other.json",
            project_settings_path=project_path,
        )
    with pytest.raises(CodingLegacySourceEvidenceError):
        parse_coding_legacy_source_evidence(
            raw.replace(
                b'"productId":"coding"', b'"productId":"coding","productId":"coding"'
            ),
            global_settings_path=global_path,
            project_settings_path=project_path,
        )
