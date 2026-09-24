from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from loushang.coding.package_epoch_layout import (
    CodingLifecyclePreBMembersV1,
    CodingPackagePreBStoreMembersV1,
)
from loushang.coding.package_legacy_classification import (
    CodingScopedLegacyDisableV1,
    classify_coding_legacy_workspace,
)
from loushang.coding.package_source_snapshot import (
    hold_coding_pre_b_source_configuration,
)
from loushang.harness.config.agent import SettingsManager


def _projection(tmp_path: Path) -> dict[str, object]:
    return {
        "productId": "coding",
        "projectionVersion": 1,
        "scopes": {
            scope: {
                "present": False,
                "rawSha256": None,
                "settingsPath": str(tmp_path / f"{scope}.json"),
                "sourcePatch": {},
            }
            for scope in ("global", "project")
        },
    }


def _members(
    tmp_path: Path, *, old_state: bool = False
) -> tuple[CodingLifecyclePreBMembersV1, CodingPackagePreBStoreMembersV1]:
    return (
        CodingLifecyclePreBMembersV1(
            source_root=tmp_path / "old-lifecycle",
            desired_state=("desired-state.jsonl",) if old_state else (),
            enablement_state=(),
            instance_state=(),
        ),
        CodingPackagePreBStoreMembersV1(
            source_root=tmp_path / "old-package",
            store_bytes=("installed",) if old_state else (),
            binding_history=(),
            lock_history=(),
        ),
    )


def _set_patch(
    projection: dict[str, object], scope: str, patch: dict[str, object]
) -> None:
    scopes = projection["scopes"]
    assert isinstance(scopes, dict)
    layer = scopes[scope]
    assert isinstance(layer, dict)
    layer.update(present=True, rawSha256="a" * 64, sourcePatch=patch)


def test_classification_distinguishes_fresh_and_scoped_disable_only(
    tmp_path: Path,
) -> None:
    lifecycle, package = _members(tmp_path)
    projection = _projection(tmp_path)
    fresh = classify_coding_legacy_workspace(
        projection, lifecycle=lifecycle, package=package
    )
    assert fresh.kind == "fresh"
    assert fresh.disabled_plugins == fresh.configured_source_keys == ()

    _set_patch(projection, "global", {"disabled_plugins": ["coding.base"]})
    _set_patch(projection, "project", {"disabled_plugins": ["coding.lsp.default"]})
    disabled = classify_coding_legacy_workspace(
        projection, lifecycle=lifecycle, package=package
    )
    assert disabled.kind == "disabled_only"
    assert disabled.disabled_plugins == (
        CodingScopedLegacyDisableV1("global", "coding.base"),
        CodingScopedLegacyDisableV1("project", "coding.lsp.default"),
    )
    assert disabled.configured_source_keys == ()


def test_classification_never_converts_source_or_old_store_to_fresh(
    tmp_path: Path,
) -> None:
    lifecycle, package = _members(tmp_path)
    projection = _projection(tmp_path)
    _set_patch(
        projection,
        "project",
        {
            "disabled_plugins": ["coding.base"],
            "packages": ["/some/old/source"],
            "resource_roots": ["/ordinary/resources"],
        },
    )
    configured = classify_coding_legacy_workspace(
        projection, lifecycle=lifecycle, package=package
    )
    assert configured.kind == "configured_source"
    assert configured.configured_source_keys == ("project:packages",)
    assert configured.disabled_plugins == (
        CodingScopedLegacyDisableV1("project", "coding.base"),
    )

    lifecycle, package = _members(tmp_path, old_state=True)
    old = classify_coding_legacy_workspace(
        projection, lifecycle=lifecycle, package=package
    )
    assert old.kind == "legacy_state"
    assert old.lifecycle_members == ("desired_state:desired-state.jsonl",)
    assert old.package_members == ("store_bytes:installed",)


def test_classification_consumes_locked_persistent_source_projection(
    tmp_path: Path,
) -> None:
    global_path = tmp_path / "global" / "settings.json"
    project_path = tmp_path / "project" / "settings.json"
    projection_parent = tmp_path / "projection"
    for parent in (global_path.parent, project_path.parent, projection_parent):
        parent.mkdir(mode=0o700)
    global_path.write_text('{"disabled_plugins":["coding.base"]}\n')
    project_path.write_text('{"plugin_sources":["/old/plugins"]}\n')
    manager = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    lifecycle, package = _members(tmp_path)

    with hold_coding_pre_b_source_configuration(
        manager,
        global_settings_path=global_path,
        project_settings_path=project_path,
        projection_parent=projection_parent,
    ) as source_root:
        projection = json.loads(
            (source_root / "coding-source-configuration.json").read_text()
        )
        classified = classify_coding_legacy_workspace(
            projection, lifecycle=lifecycle, package=package
        )

    assert classified.kind == "configured_source"
    assert classified.disabled_plugins == (
        CodingScopedLegacyDisableV1("global", "coding.base"),
    )
    assert classified.configured_source_keys == ("project:plugin_sources",)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(projectionVersion=True),
        lambda value: value["scopes"]["global"].update(rawSha256="a" * 64),
        lambda value: value["scopes"]["global"].update(sourcePatch={"unknown": []}),
        lambda value: value["scopes"]["global"].update(
            present=True,
            rawSha256="a" * 64,
            sourcePatch={"disabled_plugins": ["x", "x"]},
        ),
        lambda value: value["scopes"]["global"].update(
            present=True, rawSha256="a" * 64, sourcePatch={"plugin_sources": "git:repo"}
        ),
    ),
)
def test_classification_refuses_unverified_or_ambiguous_projection(
    tmp_path: Path, mutation
) -> None:
    lifecycle, package = _members(tmp_path)
    projection = deepcopy(_projection(tmp_path))
    mutation(projection)
    with pytest.raises(ValueError):
        classify_coding_legacy_workspace(
            projection, lifecycle=lifecycle, package=package
        )
