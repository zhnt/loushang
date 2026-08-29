from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from loushang.coding.control import ControlConfig, SettingsManager
from loushang.coding.resource_runtime import (
    CodingPackageMaterializer as PackageMaterializer,
)
from loushang.coding.resource_runtime import (
    CodingResourceLoader as DefaultResourceLoader,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
    PythonPackageInstallerBackend,
)
from loushang.harness.resources.packages.operations import (
    PackageMutationRequiresAsyncError,
    PackageResourceRefreshOutcome,
)
from loushang.harness.resources.packages.session import SessionPackageController


def test_package_controller_installs_local_package_updates_settings_and_refreshes_once(
    tmp_path,
) -> None:
    local_package = tmp_path / "local-pack"
    local_package.mkdir()
    settings = SettingsManager(ControlConfig())
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    resource_loader = DefaultResourceLoader()
    refreshes: list[str] = []

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
    )
    controller = SessionPackageController(
        get_session_id=lambda: manager.get_session_record().session_id,
        get_cwd=manager.get_cwd,
        get_settings_manager=lambda: settings,
        get_package_materializer=lambda: materializer,
        get_resource_loader=lambda: resource_loader,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: refreshes.append("refresh"),
    )

    result = asyncio.run(
        controller.install_package(str(local_package), scope="project")
    )

    assert result["lifecycle"] == "installed"
    assert result["targetPath"] == str(local_package.resolve())
    assert [package.source for package in settings.get_package_sources()] == [
        str(local_package)
    ]
    assert refreshes == ["refresh"]


def test_package_controller_installs_python_package_updates_settings_and_refreshes_once(
    tmp_path,
) -> None:
    settings = SettingsManager(ControlConfig())
    resource_loader = DefaultResourceLoader()
    refreshes: list[str] = []

    def runner(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        target = Path(args[args.index("--target") + 1])
        dist_info = target / "acme_review_pack-1.2.3.dist-info"
        dist_info.mkdir(parents=True)
        (dist_info / "METADATA").write_text(
            "Name: acme-review-pack\nVersion: 1.2.3\n", encoding="utf-8"
        )
        (target / "prompts").mkdir()
        (target / "prompts" / "review.md").write_text(
            "Review prompt.", encoding="utf-8"
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        python_backend=PythonPackageInstallerBackend(runner=runner),
    )
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
    )
    controller = SessionPackageController(
        get_session_id=lambda: manager.get_session_record().session_id,
        get_cwd=manager.get_cwd,
        get_settings_manager=lambda: settings,
        get_package_materializer=lambda: materializer,
        get_resource_loader=lambda: resource_loader,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: refreshes.append("refresh"),
    )

    result = asyncio.run(
        controller.install_package("pypi:acme-review-pack==1.2.3", scope="project")
    )

    assert result["lifecycle"] == "installed"
    assert result["sourceType"] == "python"
    assert result["installer"] == "uv"
    assert result["resolvedName"] == "acme-review-pack"
    assert result["resolvedVersion"] == "1.2.3"
    assert [package.source for package in settings.get_package_sources()] == [
        "pypi:acme-review-pack==1.2.3"
    ]
    assert refreshes == ["refresh"]


def test_package_controller_rolls_back_exact_settings_layer_on_prepublication_failure(
    tmp_path,
) -> None:
    local_package = tmp_path / "existing-pack"
    local_package.mkdir()
    source = str(local_package)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global.json",
        project_settings_path=tmp_path / "project.json",
    )
    settings.set_package_sources((source,), scope="global")
    settings.set_resource_roots(("project-root",), scope="project")
    before = (
        settings.get_global_settings(),
        settings.get_project_settings(),
        settings.get_session_settings(),
    )
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
    )
    controller = SessionPackageController(
        get_session_id=lambda: manager.get_session_record().session_id,
        get_cwd=manager.get_cwd,
        get_settings_manager=lambda: settings,
        get_package_materializer=lambda: PackageMaterializer(
            install_root=tmp_path / "packages"
        ),
        get_resource_loader=DefaultResourceLoader,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: PackageResourceRefreshOutcome(
            published=False,
            error=RuntimeError("candidate rejected"),
        ),
    )

    with pytest.raises(RuntimeError, match="candidate rejected"):
        asyncio.run(controller.install_package(source, scope="project"))

    assert (
        settings.get_global_settings(),
        settings.get_project_settings(),
        settings.get_session_settings(),
    ) == before


def test_package_controller_keeps_remote_checkout_until_uninstall_publication(
    tmp_path,
) -> None:
    source = "https://packages.example.invalid/review-pack.git"

    async def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True, exist_ok=True)
        return record.with_lifecycle("installed")

    settings = SettingsManager(ControlConfig())
    settings.add_package_source(source, scope="session")
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
    )
    record = asyncio.run(materializer.materialize_remote_source(source))
    before = settings.get_session_settings()
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
    )
    controller = SessionPackageController(
        get_session_id=lambda: manager.get_session_record().session_id,
        get_cwd=manager.get_cwd,
        get_settings_manager=lambda: settings,
        get_package_materializer=lambda: materializer,
        get_resource_loader=DefaultResourceLoader,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: PackageResourceRefreshOutcome(
            published=False,
            error=RuntimeError("uninstall candidate rejected"),
        ),
    )

    with pytest.raises(RuntimeError, match="uninstall candidate rejected"):
        asyncio.run(controller.uninstall_package_async(source, scope="session"))

    assert settings.get_session_settings() == before
    assert record.target_path.exists()
    assert materializer.get_record(source) is not None


def test_package_controller_sync_catalog_uninstall_fails_before_any_mutation(
    tmp_path,
) -> None:
    source = "https://packages.example.invalid/review-pack.git"
    settings = SettingsManager(ControlConfig())
    settings.add_package_source(source, scope="session")
    before = settings.get_session_settings()
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), persist=False)
    )
    controller = SessionPackageController(
        get_session_id=lambda: manager.get_session_record().session_id,
        get_cwd=manager.get_cwd,
        get_settings_manager=lambda: settings,
        get_package_materializer=lambda: PackageMaterializer(
            install_root=tmp_path / "packages"
        ),
        get_resource_loader=DefaultResourceLoader,
        get_diagnostics_service=lambda: None,
        refresh_resources=lambda: asyncio.sleep(0),
        supports_synchronous_refresh=lambda: False,
    )

    with pytest.raises(
        PackageMutationRequiresAsyncError,
        match="uninstall_package_async",
    ):
        controller.uninstall_package(source, scope="session")

    assert settings.get_session_settings() == before
