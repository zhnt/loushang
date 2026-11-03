from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest

from loushang.coding.control import SettingsManager
from loushang.coding.package_source_snapshot import (
    hold_coding_pre_b_source_configuration,
)


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    global_path = tmp_path / "global" / "settings.json"
    project_path = tmp_path / "project" / ".loushang" / "settings.json"
    parent = tmp_path / "projections"
    for path in (global_path.parent, project_path.parent, parent):
        path.mkdir(parents=True, mode=0o700)
    return global_path, project_path, parent


def test_source_projection_preserves_real_scope_values_and_file_evidence(
    tmp_path: Path,
) -> None:
    global_path, project_path, parent = _paths(tmp_path)
    global_raw = b'{"plugin_sources":["/plugins/a"],"disabled_plugins":["a"],"theme":"dark"}\n'
    project_raw = b'{"package_roots":["/packages/b"],"theme":"light"}\n'
    global_path.write_bytes(global_raw)
    project_path.write_bytes(project_raw)
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
        assert projection == {
            "productId": "coding",
            "projectionVersion": 1,
            "scopes": {
                "global": {
                    "present": True,
                    "rawSha256": sha256(global_raw).hexdigest(),
                    "settingsPath": str(global_path),
                    "sourcePatch": {
                        "plugin_sources": ["/plugins/a"],
                        "disabled_plugins": ["a"],
                    },
                },
                "project": {
                    "present": True,
                    "rawSha256": sha256(project_raw).hexdigest(),
                    "settingsPath": str(project_path),
                    "sourcePatch": {"package_roots": ["/packages/b"]},
                },
            },
        }
        assert source_root.stat().st_mode & 0o777 == 0o700
        assert (source_root / "coding-source-configuration.json").stat().st_mode & 0o777 == 0o600
    assert not source_root.exists()


def test_source_projection_rejects_session_override_even_when_empty(
    tmp_path: Path,
) -> None:
    global_path, project_path, parent = _paths(tmp_path)
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
            pytest.fail("transient override must refuse before projection")
    assert not list(parent.iterdir())


def test_source_projection_refuses_ambiguous_persistent_json(
    tmp_path: Path,
) -> None:
    global_path, project_path, parent = _paths(tmp_path)
    global_path.write_bytes(b'{"plugin_sources":[],"plugin_sources":["/plugins/a"]}\n')
    manager = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    with pytest.raises(ValueError, match="strict JSON"):
        with hold_coding_pre_b_source_configuration(
            manager,
            global_settings_path=global_path,
            project_settings_path=project_path,
            projection_parent=parent,
        ):
            pytest.fail("ambiguous settings must refuse before projection")
    assert not list(parent.iterdir())


def test_source_projection_refuses_unmapped_future_source_setting(
    tmp_path: Path,
) -> None:
    global_path, project_path, parent = _paths(tmp_path)
    global_path.write_bytes(b'{"plugin_source_policy":"unmapped"}\n')
    manager = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    with pytest.raises(ValueError, match="unmapped key"):
        with hold_coding_pre_b_source_configuration(
            manager,
            global_settings_path=global_path,
            project_settings_path=project_path,
            projection_parent=parent,
        ):
            pytest.fail("unmapped Source setting must refuse before projection")
    assert not list(parent.iterdir())


def test_source_projection_holds_persistent_writer_locks_through_cutover_scope(
    tmp_path: Path,
) -> None:
    global_path, project_path, parent = _paths(tmp_path)
    project_path.write_bytes(b'{"plugin_sources":["/plugins/old"]}\n')
    reader = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    writer = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    started = Event()

    def update() -> None:
        started.set()
        writer.update_settings(scope="project", plugin_sources=("/plugins/new",))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with hold_coding_pre_b_source_configuration(
            reader,
            global_settings_path=global_path,
            project_settings_path=project_path,
            projection_parent=parent,
        ) as source_root:
            future = pool.submit(update)
            assert started.wait(timeout=5)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.1)
            projection = json.loads(
                (source_root / "coding-source-configuration.json").read_bytes()
            )
            assert projection["scopes"]["project"]["sourcePatch"] == {
                "plugin_sources": ["/plugins/old"]
            }
        future.result(timeout=5)
    assert writer.get_project_settings()["plugin_sources"] == ["/plugins/new"]
