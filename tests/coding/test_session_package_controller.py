from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from loushang.coding.control import ControlConfig, SettingsManager
from loushang.coding.resource_runtime import (
    CodingPackageMaterializer as PackageMaterializer,
)
from loushang.coding.resource_runtime import (
    CodingResourceLoader as DefaultResourceLoader,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.resources.packages.materializer import (
    PythonPackageInstallerBackend,
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
