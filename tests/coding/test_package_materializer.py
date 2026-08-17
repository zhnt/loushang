from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path


def _run_git(args: list[str], *, cwd) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _git_stdout(args: list[str], *, cwd) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _write_python_dist(target: Path, *, name: str, version: str) -> None:
    dist_info_name = f"{name.replace('-', '_')}-{version}.dist-info"
    dist_info = target / dist_info_name
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n", encoding="utf-8")


def test_package_materializer_records_pending_remote_sources(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )

    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    source = "https://packages.example.invalid/review-pack.git"

    record = materializer.prepare_remote_source(source)

    assert record.source == source
    assert record.name == "review-pack"
    assert record.lifecycle == "materialization_pending"
    assert record.target_path == tmp_path / "packages" / "review-pack"
    assert materializer.get_record(source) == record
    assert materializer.list_records() == [record]


def test_package_resource_root_resolver_covers_local_and_installed_remote_sources(tmp_path) -> None:
    from pathlib import Path

    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.roots import resolve_package_resource_roots
    from loushang.harness.resources.packages.source import PackageSourceConfig

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        return record.with_lifecycle("installed")

    local_root = tmp_path / "local-pack"
    local_root.mkdir()
    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    asyncio.run(materializer.materialize_remote_source(source))

    resolved = resolve_package_resource_roots(
        package_roots=(str(local_root),),
        plugin_sources=(),
        package_sources=(PackageSourceConfig(source=source, prompts=("review.md",)),),
        materializer=materializer,
    )

    assert resolved.roots == (str(local_root.resolve()), str(tmp_path / "packages" / "review-pack"))
    assert resolved.filters[Path(tmp_path / "packages" / "review-pack").resolve()].prompts == ("review.md",)


def test_package_resource_root_resolver_uses_installed_package_manifest_root(tmp_path) -> None:
    from pathlib import Path

    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.roots import resolve_package_resource_roots
    from loushang.harness.resources.packages.source import PackageSourceConfig

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        (record.target_path / "resources" / "prompts").mkdir(parents=True)
        (record.target_path / "prompts").mkdir()
        (record.target_path / "resources" / "prompts" / "chosen.md").write_text("chosen", encoding="utf-8")
        (record.target_path / "prompts" / "ignored.md").write_text("ignored", encoding="utf-8")
        (record.target_path / "loushang-package.json").write_text(
            json.dumps({"name": "review-pack", "version": "1.2.3", "packageRoot": "resources"}),
            encoding="utf-8",
        )
        return record.with_lifecycle("installed", target_path=record.target_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    asyncio.run(materializer.materialize_remote_source(source))

    resolved = resolve_package_resource_roots(
        package_roots=(),
        plugin_sources=(),
        package_sources=(PackageSourceConfig(source=source, prompts=("chosen.md",)),),
        materializer=materializer,
    )

    package_root = (tmp_path / "packages" / "review-pack" / "resources").resolve()
    assert resolved.roots == (str(package_root),)
    assert resolved.filters[Path(package_root)].prompts == ("chosen.md",)


def test_package_lifecycle_types_are_exported_from_package_namespace() -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import collect_coding_package_entries
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.source import (
        is_remote_package_source,
        remote_package_name,
    )

    assert GitPackageMaterializerBackend is not None
    assert PackageMaterializationRecord is not None
    assert PackageMaterializer is not None
    assert collect_coding_package_entries is not None
    assert is_remote_package_source("https://example.invalid/review-pack.git") is True
    assert remote_package_name("https://example.invalid/review-pack.git") == "review-pack"


def test_package_source_identity_parses_pi_git_shorthand_and_at_refs() -> None:
    from loushang.harness.resources.packages.source import (
        PackageSourceIdentity,
        is_remote_package_source,
        package_source_match_key,
        remote_package_name,
    )

    shorthand = PackageSourceIdentity.parse("git:github.com/acme/review-pack@main")
    scp_like = PackageSourceIdentity.parse("git@github.com:acme/review-pack.git@v1.2.3")
    https_at_ref = PackageSourceIdentity.parse("https://github.com/acme/review-pack@feature")

    assert shorthand.source_type == "git"
    assert shorthand.repo == "https://github.com/acme/review-pack"
    assert shorthand.identity_key == "git:github.com/acme/review-pack#main"
    assert shorthand.ref == "main"
    assert shorthand.pinned is True
    assert scp_like.repo == "git@github.com:acme/review-pack.git"
    assert scp_like.identity_key == "git:github.com/acme/review-pack#v1.2.3"
    assert https_at_ref.repo == "https://github.com/acme/review-pack"
    assert https_at_ref.ref == "feature"
    assert is_remote_package_source("git:github.com/acme/review-pack") is True
    assert is_remote_package_source("git@github.com:acme/review-pack.git") is True
    assert package_source_match_key("git:github.com/acme/review-pack@main") == "git:github.com/acme/review-pack"
    assert remote_package_name("git:github.com/acme/review-pack@main") == "review-pack"


def test_package_source_identity_parses_python_package_sources() -> None:
    from loushang.harness.resources.packages.source import (
        PackageSourceIdentity,
        is_python_package_source,
        is_remote_package_source,
        package_source_match_key,
        remote_package_name,
    )

    source = "pypi:Acme_Review-Pack[cli]==1.2.3"
    identity = PackageSourceIdentity.parse(source)

    assert identity.source_type == "python"
    assert identity.identity_key == "python:acme-review-pack#Acme_Review-Pack[cli]==1.2.3"
    assert identity.path == "acme-review-pack"
    assert identity.ref == "==1.2.3"
    assert identity.pinned is True
    assert is_python_package_source(source) is True
    assert is_remote_package_source(source) is True
    assert package_source_match_key(source) == "python:acme-review-pack"
    assert remote_package_name(source) == "acme-review-pack"


def test_configured_package_sources_dedupes_pinned_versions_by_package_identity(tmp_path) -> None:
    from loushang.coding.control import SettingsManager
    from loushang.harness.resources.packages.source_resolver import (
        configured_package_sources,
    )

    global_settings = tmp_path / "agent" / "settings.json"
    project_settings = tmp_path / "project" / ".loushang" / "settings.json"
    global_settings.parent.mkdir()
    project_settings.parent.mkdir(parents=True)
    global_settings.write_text(
        json.dumps(
            {
                "packages": [
                    "pypi:acme-review-pack==1.2.3",
                    "git:github.com/acme/review-pack@v1",
                ]
            }
        ),
        encoding="utf-8",
    )
    project_settings.write_text(
        json.dumps(
            {
                "packages": [
                    "pypi:acme-review-pack==1.3.0",
                    "git+https://github.com/acme/review-pack#main",
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = SettingsManager(global_settings_path=global_settings, project_settings_path=project_settings)

    sources = configured_package_sources(settings)

    assert [source.source for source in sources] == [
        "pypi:acme-review-pack==1.3.0",
        "git+https://github.com/acme/review-pack#main",
    ]


def test_configured_package_sources_preserves_same_relative_local_source_across_scopes(tmp_path) -> None:
    from loushang.coding.control import SettingsManager
    from loushang.harness.resources.packages.source_resolver import (
        configured_package_sources,
        package_source_scopes,
    )

    global_settings = tmp_path / "agent" / "settings.json"
    project_settings = tmp_path / "project" / ".loushang" / "settings.json"
    global_pack = tmp_path / "agent" / "packages" / "shared-pack"
    project_pack = tmp_path / "project" / ".loushang" / "packages" / "shared-pack"
    global_settings.parent.mkdir()
    project_settings.parent.mkdir(parents=True)
    global_pack.mkdir(parents=True)
    project_pack.mkdir(parents=True)
    global_settings.write_text(json.dumps({"packages": ["packages/shared-pack"]}), encoding="utf-8")
    project_settings.write_text(json.dumps({"packages": ["packages/shared-pack"]}), encoding="utf-8")
    settings = SettingsManager(global_settings_path=global_settings, project_settings_path=project_settings)

    sources = configured_package_sources(settings)
    scopes = package_source_scopes(settings)

    assert [source.source for source in sources] == [
        str(project_pack.resolve()),
        str(global_pack.resolve()),
    ]
    assert scopes == {
        str(project_pack.resolve()): "project",
        str(global_pack.resolve()): "user",
    }


def test_python_package_installer_backend_installs_with_uv_and_records_metadata(tmp_path) -> None:
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
        PythonPackageInstallerBackend,
    )

    calls: list[list[str]] = []

    def runner(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        target = Path(args[args.index("--target") + 1])
        _write_python_dist(target, name="acme-review-pack", version="1.2.3")
        return subprocess.CompletedProcess(args, 0, "", "")

    backend = PythonPackageInstallerBackend(runner=runner)
    record = PackageMaterializationRecord(
        source="pypi:acme-review-pack==1.2.3",
        name="acme-review-pack",
        lifecycle="materialization_pending",
        target_path=tmp_path / "packages" / "python" / "acme-review-pack",
        source_type="python",
        requirement="acme-review-pack==1.2.3",
    )

    installed = backend(record)

    assert calls[0][:3] == ["uv", "pip", "install"]
    assert installed.lifecycle == "installed"
    assert installed.installer == "uv"
    assert installed.resolved_name == "acme-review-pack"
    assert installed.resolved_version == "1.2.3"
    assert installed.installed_distributions == ("acme-review-pack==1.2.3",)
    assert (installed.target_path / "acme_review_pack-1.2.3.dist-info" / "METADATA").is_file()


def test_python_package_installer_backend_falls_back_to_pip_when_uv_is_missing(tmp_path) -> None:
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
        PythonPackageInstallerBackend,
    )

    calls: list[list[str]] = []

    def runner(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "uv":
            raise FileNotFoundError("uv")
        target = Path(args[args.index("--target") + 1])
        _write_python_dist(target, name="acme-review-pack", version="1.2.3")
        return subprocess.CompletedProcess(args, 0, "", "")

    backend = PythonPackageInstallerBackend(python_command="python3", runner=runner)
    record = PackageMaterializationRecord(
        source="pypi:acme-review-pack==1.2.3",
        name="acme-review-pack",
        lifecycle="materialization_pending",
        target_path=tmp_path / "packages" / "python" / "acme-review-pack",
        source_type="python",
        requirement="acme-review-pack==1.2.3",
    )

    installed = backend(record)

    assert calls[0][:3] == ["uv", "pip", "install"]
    assert calls[1][:4] == ["python3", "-m", "pip", "install"]
    assert installed.installer == "pip"


def test_package_materializer_materializes_python_package_sources_and_persists_lockfile(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PythonPackageInstallerBackend,
    )

    def runner(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        target = Path(args[args.index("--target") + 1])
        _write_python_dist(target, name="acme-review-pack", version="1.2.3")
        return subprocess.CompletedProcess(args, 0, "", "")

    source = "pypi:acme-review-pack==1.2.3"
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        python_backend=PythonPackageInstallerBackend(runner=runner),
    )

    record = asyncio.run(materializer.materialize_remote_source(source))
    restored = PackageMaterializer(install_root=tmp_path / "packages")

    assert record.lifecycle == "installed"
    assert record.source_type == "python"
    assert record.requirement == "acme-review-pack==1.2.3"
    assert record.target_path == tmp_path / "packages" / "python" / "acme-review-pack"
    assert restored.get_record(source) == record


def test_package_materializer_uses_backend_to_install_remote_sources(tmp_path) -> None:
    from pathlib import Path

    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        target = Path(record.target_path)
        target.mkdir(parents=True)
        return record.with_lifecycle("installed", target_path=target)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)

    record = asyncio.run(materializer.materialize_remote_source(source))

    assert record.lifecycle == "installed"
    assert record.target_path == tmp_path / "packages" / "review-pack"
    assert record.target_path.is_dir()
    assert materializer.get_record(source) == record


def test_package_materializer_refreshes_temporary_remote_source_without_persisting_lockfile(tmp_path) -> None:
    from pathlib import Path

    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"
    revisions: list[str] = []

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        revisions.append(record.lifecycle)
        target = Path(record.target_path)
        target.mkdir(parents=True, exist_ok=True)
        (target / "revision.txt").write_text(str(len(revisions)), encoding="utf-8")
        return record.with_lifecycle("installed", target_path=target)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)

    first = asyncio.run(materializer.materialize_temporary_remote_source(source))
    second = asyncio.run(materializer.materialize_temporary_remote_source(source))

    assert first.lifecycle == "installed"
    assert second.lifecycle == "installed"
    assert second.target_path == first.target_path
    assert (second.target_path / "revision.txt").read_text(encoding="utf-8") == "2"
    assert materializer.get_record(source) is None
    assert not materializer.lockfile_path.exists()


def test_package_materializer_resolves_scope_relative_local_sources(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.roots import resolve_package_resource_roots
    from loushang.harness.resources.packages.source import PackageSourceConfig

    global_base = tmp_path / "agent"
    project_base = tmp_path / "project" / ".loushang"
    (global_base / "packages" / "global-pack").mkdir(parents=True)
    (project_base / "packages" / "project-pack").mkdir(parents=True)

    materializer = PackageMaterializer(install_root=tmp_path / "materialized")
    resolved = resolve_package_resource_roots(
        package_roots=(),
        plugin_sources=(),
        package_sources=(
            PackageSourceConfig(source="packages/global-pack"),
            PackageSourceConfig(source="packages/project-pack"),
        ),
        materializer=materializer,
        package_source_scopes={
            "packages/global-pack": "user",
            "packages/project-pack": "project",
        },
        global_base_dir=global_base,
        project_base_dir=project_base,
    )

    assert resolved.roots == (
        str((global_base / "packages" / "global-pack").resolve()),
        str((project_base / "packages" / "project-pack").resolve()),
    )


def test_package_projection_resolves_scope_relative_package_sources(tmp_path) -> None:
    from loushang.coding.control import SettingsManager
    from loushang.coding.resource_runtime import collect_coding_package_entries

    global_base = tmp_path / "agent"
    project_base = tmp_path / "project" / ".loushang"
    global_pack = global_base / "packages" / "global-pack"
    project_pack = project_base / "packages" / "project-pack"
    global_pack.mkdir(parents=True)
    project_pack.mkdir(parents=True)
    (global_base / "settings.json").write_text(json.dumps({"packages": ["packages/global-pack"]}), encoding="utf-8")
    (project_base / "settings.json").write_text(json.dumps({"packages": ["packages/project-pack"]}), encoding="utf-8")

    settings = SettingsManager(
        global_settings_path=global_base / "settings.json",
        project_settings_path=project_base / "settings.json",
    )

    entries = collect_coding_package_entries(
        package_roots=(),
        plugin_sources=(),
        package_sources=(),
        disabled_plugins=(),
        cwd=tmp_path / "project",
        settings_manager=settings,
    )

    entries_by_scope = {str(entry["scope"]): entry for entry in entries}
    assert entries_by_scope["user"]["path"] == str(global_pack.resolve())
    assert entries_by_scope["project"]["path"] == str(project_pack.resolve())


def test_git_package_materializer_backend_clones_remote_plugin_source(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )
    from loushang.harness.resources.plugins import PluginManager

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "version": "1.2.3", "packageRoot": "package"}),
        encoding="utf-8",
    )
    (source_repo / "package").mkdir()
    _run_git(["init"], cwd=source_repo)
    _run_git(["config", "user.email", "test@example.invalid"], cwd=source_repo)
    _run_git(["config", "user.name", "Test User"], cwd=source_repo)
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "initial"], cwd=source_repo)

    remote_repo = tmp_path / "review-pack.git"
    _run_git(["clone", "--bare", str(source_repo), str(remote_repo)], cwd=tmp_path)
    source = remote_repo.as_uri()
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=GitPackageMaterializerBackend(),
    )

    record = asyncio.run(materializer.materialize_remote_source(source))

    assert record.lifecycle == "installed"
    assert record.target_path == tmp_path / "packages" / "review-pack"
    assert (record.target_path / "plugin.json").is_file()
    manager = PluginManager()
    plugin = manager.add_plugin_source(record.target_path)
    assert plugin.manifest.name == "review-pack"
    assert plugin.manifest.version == "1.2.3"


def test_package_materializer_updates_existing_git_checkout(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "1.0.0"}), encoding="utf-8")
    _run_git(["init"], cwd=source_repo)
    _run_git(["config", "user.email", "test@example.invalid"], cwd=source_repo)
    _run_git(["config", "user.name", "Test User"], cwd=source_repo)
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "initial"], cwd=source_repo)
    remote_repo = tmp_path / "review-pack.git"
    _run_git(["clone", "--bare", str(source_repo), str(remote_repo)], cwd=tmp_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=GitPackageMaterializerBackend())
    source = remote_repo.as_uri()
    first = asyncio.run(materializer.materialize_remote_source(source))
    assert json.loads((first.target_path / "plugin.json").read_text(encoding="utf-8"))["version"] == "1.0.0"

    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "2.0.0"}), encoding="utf-8")
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "update"], cwd=source_repo)
    _run_git(["push", str(remote_repo), "HEAD"], cwd=source_repo)

    updated = asyncio.run(materializer.update_remote_source(source))

    assert updated.lifecycle == "installed"
    assert updated.target_path == first.target_path
    assert json.loads((updated.target_path / "plugin.json").read_text(encoding="utf-8"))["version"] == "2.0.0"
    assert updated.installed_commit
    assert updated.resolved_commit == updated.installed_commit
    assert updated.dirty is False


def test_git_package_materializer_updates_detached_checkout_without_upstream(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "1.0.0"}), encoding="utf-8")
    _run_git(["init", "-b", "main"], cwd=source_repo)
    _run_git(["config", "user.email", "test@example.invalid"], cwd=source_repo)
    _run_git(["config", "user.name", "Test User"], cwd=source_repo)
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "initial"], cwd=source_repo)
    initial_commit = _git_stdout(["rev-parse", "HEAD"], cwd=source_repo)
    remote_repo = tmp_path / "review-pack.git"
    _run_git(["clone", "--bare", str(source_repo), str(remote_repo)], cwd=tmp_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=GitPackageMaterializerBackend())
    source = remote_repo.as_uri()
    installed = asyncio.run(materializer.materialize_remote_source(source))
    _run_git(["checkout", "--detach", initial_commit], cwd=installed.target_path)

    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "2.0.0"}), encoding="utf-8")
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "update"], cwd=source_repo)
    latest_commit = _git_stdout(["rev-parse", "HEAD"], cwd=source_repo)
    _run_git(["push", str(remote_repo), "main"], cwd=source_repo)

    updated = asyncio.run(materializer.update_remote_source(source))

    assert updated.lifecycle == "installed"
    assert updated.installed_commit == latest_commit
    assert json.loads((updated.target_path / "plugin.json").read_text(encoding="utf-8"))["version"] == "2.0.0"


def test_git_package_materializer_recovers_after_remote_history_rewrite(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "1.0.0"}), encoding="utf-8")
    _run_git(["init", "-b", "main"], cwd=source_repo)
    _run_git(["config", "user.email", "test@example.invalid"], cwd=source_repo)
    _run_git(["config", "user.name", "Test User"], cwd=source_repo)
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "initial"], cwd=source_repo)
    initial_commit = _git_stdout(["rev-parse", "HEAD"], cwd=source_repo)
    remote_repo = tmp_path / "review-pack.git"
    _run_git(["clone", "--bare", str(source_repo), str(remote_repo)], cwd=tmp_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=GitPackageMaterializerBackend())
    source = remote_repo.as_uri()
    installed = asyncio.run(materializer.materialize_remote_source(source))

    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "2.0.0"}), encoding="utf-8")
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "update"], cwd=source_repo)
    _run_git(["push", str(remote_repo), "main"], cwd=source_repo)
    asyncio.run(materializer.update_remote_source(source))
    assert json.loads((installed.target_path / "plugin.json").read_text(encoding="utf-8"))["version"] == "2.0.0"

    _run_git(["reset", "--hard", initial_commit], cwd=source_repo)
    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "3.0.0"}), encoding="utf-8")
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "rewrite"], cwd=source_repo)
    rewritten_commit = _git_stdout(["rev-parse", "HEAD"], cwd=source_repo)
    _run_git(["push", "--force", str(remote_repo), "main"], cwd=source_repo)

    updated = asyncio.run(materializer.update_remote_source(source))

    assert updated.lifecycle == "installed"
    assert updated.installed_commit == rewritten_commit
    assert json.loads((updated.target_path / "plugin.json").read_text(encoding="utf-8"))["version"] == "3.0.0"


def test_git_package_materializer_skips_existing_pinned_checkout_update(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "1.0.0"}), encoding="utf-8")
    _run_git(["init", "-b", "main"], cwd=source_repo)
    _run_git(["config", "user.email", "test@example.invalid"], cwd=source_repo)
    _run_git(["config", "user.name", "Test User"], cwd=source_repo)
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "initial"], cwd=source_repo)
    initial_commit = _git_stdout(["rev-parse", "HEAD"], cwd=source_repo)
    remote_repo = tmp_path / "review-pack.git"
    _run_git(["clone", "--bare", str(source_repo), str(remote_repo)], cwd=tmp_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=GitPackageMaterializerBackend())
    source = f"{remote_repo.as_uri()}#{initial_commit}"
    asyncio.run(materializer.materialize_remote_source(source))

    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "2.0.0"}), encoding="utf-8")
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "update"], cwd=source_repo)
    _run_git(["push", str(remote_repo), "main"], cwd=source_repo)

    updated = asyncio.run(materializer.update_remote_source(source))

    assert updated.lifecycle == "installed"
    assert updated.pinned is True
    assert updated.installed_commit == initial_commit
    assert json.loads((updated.target_path / "plugin.json").read_text(encoding="utf-8"))["version"] == "1.0.0"


def test_git_package_materializer_uses_explicit_default_branch_fetch_without_pull(tmp_path) -> None:
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
        PackageMaterializationRecord,
    )

    class RecordingBackend(GitPackageMaterializerBackend):
        def __init__(self) -> None:
            super().__init__()
            self.commands: list[tuple[str, ...]] = []
            self.head = "local-old"

        def _run_git(self, args, *, cwd=None, check=True):
            del cwd, check
            command = tuple(args)
            self.commands.append(command)
            stdout = ""
            returncode = 0
            if command == ("rev-parse", "HEAD"):
                stdout = self.head
            elif command == ("status", "--porcelain"):
                stdout = ""
            elif command == ("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"):
                stdout = "origin/main"
            elif command == ("rev-parse", "origin/main"):
                stdout = "remote-new"
            elif command == ("reset", "--hard", "origin/main"):
                self.head = "remote-new"
            return subprocess.CompletedProcess(["git", *args], returncode, stdout=f"{stdout}\n" if stdout else "", stderr="")

    target = tmp_path / "packages" / "review-pack"
    (target / ".git").mkdir(parents=True)
    backend = RecordingBackend()
    record = PackageMaterializationRecord(
        source="https://github.com/acme/review-pack.git",
        name="review-pack",
        lifecycle="materialization_pending",
        target_path=target,
    )

    updated = backend(record)

    assert updated.lifecycle == "installed"
    assert updated.installed_commit == "remote-new"
    assert ("fetch", "--prune", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main") in backend.commands
    assert ("pull", "--ff-only") not in backend.commands


def test_package_materializer_refuses_to_update_dirty_git_checkout(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "1.0.0"}), encoding="utf-8")
    _run_git(["init"], cwd=source_repo)
    _run_git(["config", "user.email", "test@example.invalid"], cwd=source_repo)
    _run_git(["config", "user.name", "Test User"], cwd=source_repo)
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "initial"], cwd=source_repo)
    remote_repo = tmp_path / "review-pack.git"
    _run_git(["clone", "--bare", str(source_repo), str(remote_repo)], cwd=tmp_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=GitPackageMaterializerBackend())
    source = remote_repo.as_uri()
    installed = asyncio.run(materializer.materialize_remote_source(source))
    (installed.target_path / "local.md").write_text("local change", encoding="utf-8")

    updated = asyncio.run(materializer.update_remote_source(source))

    assert updated.lifecycle == "failed"
    assert updated.dirty is True
    assert "dirty" in (updated.error_message or "")
    assert (installed.target_path / "local.md").read_text(encoding="utf-8") == "local change"


def test_package_materializer_remove_deletes_checkout_and_keeps_registered_state(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"
    progress: list[tuple[str, str, str]] = []

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        (record.target_path / "plugin.json").write_text("{}", encoding="utf-8")
        return record.with_lifecycle("installed")

    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        progress_callback=lambda event: progress.append((event.type, event.action, event.source)),
    )
    installed = asyncio.run(materializer.materialize_remote_source(source))

    removed = materializer.remove_remote_source(source)

    assert installed.target_path.exists() is False
    assert removed.lifecycle == "remote_registered"
    assert removed.target_path == tmp_path / "packages" / "review-pack"
    assert materializer.get_record(source) == removed
    assert progress[-2:] == [
        ("start", "remove", source),
        ("complete", "remove", source),
    ]


def test_package_materializer_denies_insecure_remote_sources_by_policy(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )

    source = "http://packages.example.invalid/review-pack.git"
    backend_calls: list[str] = []
    progress: list[tuple[str, str, str, str | None]] = []

    async def backend(record):
        backend_calls.append(record.source)
        return record.with_lifecycle("installed")

    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        progress_callback=lambda event: progress.append(
            (event.type, event.action, event.source, event.message)
        ),
    )

    record = asyncio.run(materializer.materialize_remote_source(source))

    assert record.lifecycle == "failed"
    assert record.security == "denied"
    assert record.error_message == f"insecure remote package source requires HTTPS: {source}"
    assert backend_calls == []
    assert materializer.get_record(source) == record
    assert progress == [
        (
            "error",
            "install",
            source,
            f"insecure remote package source requires HTTPS: {source}",
        )
    ]


def test_package_materializer_records_pinned_git_ref_and_commit(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "1.0.0"}), encoding="utf-8")
    _run_git(["init"], cwd=source_repo)
    _run_git(["config", "user.email", "test@example.invalid"], cwd=source_repo)
    _run_git(["config", "user.name", "Test User"], cwd=source_repo)
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "initial"], cwd=source_repo)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    remote_repo = tmp_path / "review-pack.git"
    _run_git(["clone", "--bare", str(source_repo), str(remote_repo)], cwd=tmp_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=GitPackageMaterializerBackend())
    record = asyncio.run(materializer.materialize_remote_source(f"{remote_repo.as_uri()}#{commit}"))

    assert record.lifecycle == "installed"
    assert record.pinned is True
    assert record.requested_ref == commit
    assert record.installed_commit == commit
    assert record.resolved_commit == commit


def test_package_source_identity_normalizes_equivalent_git_urls() -> None:
    from loushang.harness.resources.packages.source import PackageSourceIdentity

    plain = PackageSourceIdentity.parse("https://github.com/acme/review-pack.git")
    prefixed = PackageSourceIdentity.parse("git+https://github.com/acme/review-pack")
    branch = PackageSourceIdentity.parse("https://github.com/acme/review-pack.git#main")

    assert plain.identity_key == prefixed.identity_key == "git:github.com/acme/review-pack"
    assert branch.identity_key == "git:github.com/acme/review-pack#main"
    assert branch.ref == "main"
    assert branch.pinned is True


def test_package_materializer_persists_and_restores_lockfile_records(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        return record.with_lifecycle("installed").with_git_state(
            resolved_commit="abc123",
            installed_commit="abc123",
            dirty=False,
        )

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    installed = asyncio.run(materializer.materialize_remote_source(source))

    restored = PackageMaterializer(install_root=tmp_path / "packages")

    assert (tmp_path / "package-lock.json").is_file()
    assert restored.get_record(source) == installed


def test_package_materializer_keys_records_by_normalized_source_identity(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://github.com/acme/review-pack.git"
    equivalent = "git+https://github.com/acme/review-pack"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True, exist_ok=True)
        return record.with_lifecycle("installed")

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    installed = asyncio.run(materializer.materialize_remote_source(source))

    assert materializer.get_record(equivalent) == installed
    assert materializer.list_records() == [installed]
    restored = PackageMaterializer(install_root=tmp_path / "packages")
    assert restored.get_record(equivalent) == installed
    assert len(json.loads((tmp_path / "package-lock.json").read_text(encoding="utf-8"))["packages"]) == 1


def test_package_materializer_reports_corrupt_lockfile_and_writes_atomically(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    import pytest

    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )

    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text("not json", encoding="utf-8")
    materializer = PackageMaterializer(install_root=tmp_path / "packages")

    assert materializer.get_lockfile_diagnostics()[0]["code"] == "package_lockfile_unreadable"

    original_replace = Path.replace

    def fail_replace(self, target):
        if self.name.startswith("package-lock") and self.name.endswith(".tmp"):
            raise RuntimeError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(RuntimeError, match="replace failed"):
        materializer.prepare_remote_source("https://packages.example.invalid/review-pack.git")

    assert lockfile.read_text(encoding="utf-8") == "not json"


def test_package_materializer_skips_ref_pinned_update_checks(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "1.0.0"}), encoding="utf-8")
    _run_git(["init", "-b", "main"], cwd=source_repo)
    _run_git(["config", "user.email", "test@example.invalid"], cwd=source_repo)
    _run_git(["config", "user.name", "Test User"], cwd=source_repo)
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "initial"], cwd=source_repo)
    remote_repo = tmp_path / "review-pack.git"
    _run_git(["clone", "--bare", str(source_repo), str(remote_repo)], cwd=tmp_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=GitPackageMaterializerBackend())
    source = f"{remote_repo.as_uri()}#main"
    installed = asyncio.run(materializer.materialize_remote_source(source))
    assert installed.pinned is True

    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "2.0.0"}), encoding="utf-8")
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "update"], cwd=source_repo)
    _run_git(["push", str(remote_repo), "main"], cwd=source_repo)

    updates = asyncio.run(materializer.check_package_updates())

    assert updates == []


def test_package_materializer_reports_update_check_failures(
    tmp_path, monkeypatch
) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = (tmp_path / "missing.git").as_uri()

    async def _failed_remote_check(
        source: str, timeout_seconds: float | None = None
    ) -> tuple[str | None, str]:
        del source, timeout_seconds
        return None, "Failed to check remote package update: unavailable"

    monkeypatch.setattr(
        "loushang.harness.resources.packages.materializer._remote_git_head_result_async",
        _failed_remote_check,
    )

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        return record.with_lifecycle("installed", target_path=record.target_path).with_git_state(
            installed_commit="abc",
            resolved_commit="abc",
        )

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    asyncio.run(materializer.materialize_remote_source(source))

    updates = asyncio.run(materializer.check_package_updates())

    assert updates == [
        {
            "source": source,
            "name": "missing",
            "currentCommit": "abc",
            "availableCommit": "",
            "installedCommit": "abc",
            "resolvedCommit": "abc",
            "requestedRef": "",
            "availableRef": "HEAD",
            "dirty": False,
            "pinned": False,
            "status": "check_failed",
            "reason": updates[0]["reason"],
        }
    ]
    assert "Failed to check remote package update" in str(updates[0]["reason"])


def test_package_materializer_skips_update_work_in_offline_mode(tmp_path, monkeypatch) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"
    calls: list[str] = []

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        calls.append(record.source)
        return record.with_lifecycle("installed", target_path=record.target_path)

    monkeypatch.setenv("PI_OFFLINE", "1")
    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    materializer.prepare_remote_source(source)

    records = asyncio.run(materializer.update_all_remote_sources())
    updates = asyncio.run(materializer.check_package_updates())

    assert records == []
    assert updates == []
    assert calls == []


def test_package_materializer_updates_remote_sources_with_bounded_concurrency(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.security import PackageSecurityPolicy

    active = 0
    max_active = 0

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return record.with_lifecycle("installed", target_path=record.target_path)

    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        update_concurrency=2,
        security_policy=PackageSecurityPolicy(trusted_hosts=("packages.example.invalid",)),
    )
    for index in range(4):
        materializer.prepare_remote_source(f"https://packages.example.invalid/review-pack-{index}.git")

    records = asyncio.run(materializer.update_all_remote_sources())

    assert len(records) == 4
    assert max_active == 2


def test_package_materializer_check_updates_uses_configured_timeout(tmp_path, monkeypatch) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.security import PackageSecurityPolicy

    source = "https://packages.example.invalid/review-pack.git"
    captured_timeouts: list[float | None] = []

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        return record.with_lifecycle("installed", target_path=record.target_path).with_git_state(
            installed_commit="abc",
            resolved_commit="abc",
        )

    async def fake_remote_head(source_arg: str, timeout_seconds: float | None):
        captured_timeouts.append(timeout_seconds)
        return None, f"timed out checking {source_arg}"

    monkeypatch.setattr("loushang.harness.resources.packages.materializer._remote_git_head_result_async", fake_remote_head)
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        security_policy=PackageSecurityPolicy(trusted_hosts=("packages.example.invalid",)),
        update_check_timeout_seconds=1.5,
    )
    asyncio.run(materializer.materialize_remote_source(source))

    updates = asyncio.run(materializer.check_package_updates())

    assert captured_timeouts == [1.5]
    assert updates[0]["status"] == "check_failed"


def test_package_materializer_check_updates_emits_progress_events(tmp_path, monkeypatch) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.security import PackageSecurityPolicy

    source = "https://packages.example.invalid/review-pack.git"
    progress: list[tuple[str, str, str]] = []

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        return record.with_lifecycle("installed", target_path=record.target_path).with_git_state(
            installed_commit="abc",
            resolved_commit="abc",
        )

    async def fake_remote_head(source_arg: str, timeout_seconds: float | None):
        del source_arg, timeout_seconds
        return "abc", ""

    monkeypatch.setattr("loushang.harness.resources.packages.materializer._remote_git_head_result_async", fake_remote_head)
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        security_policy=PackageSecurityPolicy(trusted_hosts=("packages.example.invalid",)),
        progress_callback=lambda event: progress.append((event.type, event.action, event.source)),
    )
    asyncio.run(materializer.materialize_remote_source(source))

    updates = asyncio.run(materializer.check_package_updates())

    assert updates == []
    assert progress[-2:] == [
        ("start", "check", source),
        ("complete", "check", source),
    ]


def test_package_materializer_check_updates_reports_python_package_update(tmp_path, monkeypatch) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "pypi:acme-review-pack"
    checked: list[tuple[str, float | None]] = []

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        return record.with_lifecycle("installed", target_path=record.target_path).with_python_state(
            installer="pip",
            resolved_name="acme-review-pack",
            resolved_version="1.2.3",
            installed_distributions=("acme-review-pack==1.2.3",),
        )

    async def fake_pypi_latest(record: PackageMaterializationRecord, timeout_seconds: float | None):
        checked.append((record.resolved_name or "", timeout_seconds))
        return "1.3.0", ""

    monkeypatch.setattr("loushang.harness.resources.packages.materializer._pypi_latest_version_result_async", fake_pypi_latest)
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=None,
        python_backend=backend,
        update_check_timeout_seconds=2.5,
    )
    asyncio.run(materializer.materialize_remote_source(source))

    updates = asyncio.run(materializer.check_package_updates())

    assert checked == [("acme-review-pack", 2.5)]
    assert updates == [
        {
            "source": source,
            "name": "acme-review-pack",
            "currentVersion": "1.2.3",
            "availableVersion": "1.3.0",
            "installedVersion": "1.2.3",
            "resolvedVersion": "1.2.3",
            "requirement": "acme-review-pack",
            "installedDistributions": ["acme-review-pack==1.2.3"],
            "pinned": False,
            "status": "update_available",
            "reason": "",
            "sourceType": "python",
        }
    ]


def test_package_materializer_check_updates_skips_pinned_python_packages(tmp_path, monkeypatch) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "pypi:acme-review-pack==1.2.3"
    checked: list[str] = []

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        return record.with_lifecycle("installed", target_path=record.target_path).with_python_state(
            installer="pip",
            resolved_name="acme-review-pack",
            resolved_version="1.2.3",
            installed_distributions=("acme-review-pack==1.2.3",),
        )

    async def fake_pypi_latest(record: PackageMaterializationRecord, timeout_seconds: float | None):
        del timeout_seconds
        checked.append(record.source)
        return "1.3.0", ""

    monkeypatch.setattr("loushang.harness.resources.packages.materializer._pypi_latest_version_result_async", fake_pypi_latest)
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=None,
        python_backend=backend,
    )
    asyncio.run(materializer.materialize_remote_source(source))

    updates = asyncio.run(materializer.check_package_updates())

    assert updates == []
    assert checked == []


def test_package_materializer_persists_trusted_sources(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.security import PackageSecurityPolicy

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        return record.with_lifecycle("installed")

    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        security_policy=PackageSecurityPolicy(trusted_hosts=("packages.example.invalid",)),
    )
    asyncio.run(materializer.materialize_remote_source(source))

    restored = PackageMaterializer(
        install_root=tmp_path / "packages",
        security_policy=PackageSecurityPolicy(trusted_sources=PackageMaterializer.load_trusted_sources(tmp_path / "package-lock.json")),
    )

    assert restored.get_record(source) is not None
    assert restored._security_policy.evaluate_package_source(source).disposition == "allow"


def test_package_materializer_updates_all_and_checks_available_updates(
    tmp_path, monkeypatch
) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "1.0.0"}), encoding="utf-8")
    _run_git(["init"], cwd=source_repo)
    _run_git(["config", "user.email", "test@example.invalid"], cwd=source_repo)
    _run_git(["config", "user.name", "Test User"], cwd=source_repo)
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "initial"], cwd=source_repo)
    remote_repo = tmp_path / "review-pack.git"
    _run_git(["clone", "--bare", str(source_repo), str(remote_repo)], cwd=tmp_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=GitPackageMaterializerBackend())
    source = remote_repo.as_uri()
    installed = asyncio.run(materializer.materialize_remote_source(source))
    remote_heads = [installed.installed_commit]

    async def _remote_head(
        source: str, timeout_seconds: float | None = None
    ) -> tuple[str | None, str]:
        del source, timeout_seconds
        return remote_heads.pop(0), ""

    monkeypatch.setattr(
        "loushang.harness.resources.packages.materializer._remote_git_head_result_async",
        _remote_head,
    )
    assert asyncio.run(materializer.check_package_updates()) == []

    (source_repo / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "2.0.0"}), encoding="utf-8")
    _run_git(["add", "."], cwd=source_repo)
    _run_git(["commit", "-m", "update"], cwd=source_repo)
    _run_git(["push", str(remote_repo), "HEAD"], cwd=source_repo)
    remote_heads.append(_git_stdout(["rev-parse", "HEAD"], cwd=source_repo))

    updates = asyncio.run(materializer.check_package_updates())
    assert updates == [
        {
            "source": source,
            "name": "review-pack",
            "currentCommit": installed.installed_commit,
            "availableCommit": updates[0]["availableCommit"],
            "installedCommit": installed.installed_commit,
            "resolvedCommit": installed.resolved_commit,
            "requestedRef": "",
            "availableRef": "HEAD",
            "dirty": False,
            "pinned": False,
            "status": "update_available",
            "reason": "",
        }
    ]

    updated_records = asyncio.run(materializer.update_all_remote_sources())
    assert [record.source for record in updated_records] == [source]
    assert updated_records[0].installed_commit == updates[0]["availableCommit"]


def test_package_security_policy_can_restrict_remote_hosts() -> None:
    from loushang.harness.resources.packages.security import PackageSecurityPolicy

    policy = PackageSecurityPolicy(trusted_hosts=("packages.example.invalid",))

    assert policy.evaluate_package_source("https://packages.example.invalid/review-pack.git").disposition == "allow"
    denied = policy.evaluate_package_source("https://evil.example.invalid/review-pack.git")
    assert denied.disposition == "deny"
    assert denied.reason == "untrusted remote package host: evil.example.invalid"


def test_package_security_policy_trusted_sources_use_normalized_identity() -> None:
    from loushang.harness.resources.packages.security import PackageSecurityPolicy

    policy = PackageSecurityPolicy(
        trusted_hosts=("packages.example.invalid",),
        trusted_sources=("https://github.com/acme/review-pack.git",),
    )

    assert policy.evaluate_package_source("git+https://github.com/acme/review-pack").disposition == "allow"


def test_package_security_policy_explains_source_trust_decision() -> None:
    from loushang.harness.resources.packages.security import (
        PackageSecurityPolicy,
        PackageSourceSecurityReport,
    )

    policy = PackageSecurityPolicy(trusted_hosts=("packages.example.invalid",))

    allowed = policy.explain_package_source("https://packages.example.invalid/review-pack.git#main")
    denied = policy.explain_package_source("https://evil.example.invalid/review-pack.git")

    assert isinstance(allowed, PackageSourceSecurityReport)
    assert allowed.ok is True
    assert allowed.source_type == "git"
    assert allowed.host == "packages.example.invalid"
    assert allowed.pinned is True
    assert allowed.decision.disposition == "allow"
    assert denied.ok is False
    assert denied.identity_key == "git:evil.example.invalid/review-pack"
    assert denied.decision.reason == "untrusted remote package host: evil.example.invalid"
    assert denied.to_dict()["decision"]["disposition"] == "deny"


def test_package_projection_applies_package_source_filters(tmp_path) -> None:
    from pathlib import Path

    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import collect_coding_package_entries
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )
    from loushang.harness.resources.packages.source import PackageSourceConfig

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        target = Path(record.target_path)
        (target / "prompts").mkdir(parents=True)
        (target / "skills" / "review").mkdir(parents=True)
        (target / "prompts" / "review.md").write_text("Review prompt", encoding="utf-8")
        (target / "skills" / "review" / "SKILL.md").write_text("Review skill", encoding="utf-8")
        return record.with_lifecycle("installed", target_path=target)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    asyncio.run(materializer.materialize_remote_source(source))

    entries = collect_coding_package_entries(
        package_roots=(),
        plugin_sources=(),
        package_sources=(PackageSourceConfig(source=source, prompts=("review.md",), skills=()),),
        disabled_plugins=(),
        cwd=tmp_path,
        materializer=materializer,
    )

    assert entries[0]["source"] == source
    assert entries[0]["prompts"] == 1
    assert entries[0]["skills"] == 0
    assert entries[0]["filtered"] is True


def test_package_projection_uses_materializer_lifecycle_records(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import collect_coding_package_entries

    source = "https://packages.example.invalid/review-pack.git"
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    materializer.prepare_remote_source(source)

    entries = collect_coding_package_entries(
        package_roots=(),
        plugin_sources=(source,),
        disabled_plugins=(),
        cwd=tmp_path,
        materializer=materializer,
    )

    assert entries[0]["lifecycle"] == "materialization_pending"
    assert entries[0]["kind"] == "remote_plugin"
    assert entries[0]["packageKind"] == "remote_package"
    assert entries[0]["path"] == str(tmp_path / "packages" / "review-pack")
    assert entries[0]["enabled"] is False


def test_package_projection_summarizes_installed_remote_plugin_resources(tmp_path) -> None:
    from pathlib import Path

    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import collect_coding_package_entries
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        target = Path(record.target_path)
        (target / "prompts").mkdir(parents=True)
        (target / "prompts" / "review.md").write_text("Review prompt", encoding="utf-8")
        return record.with_lifecycle("installed", target_path=target)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    asyncio.run(materializer.materialize_remote_source(source))

    entries = collect_coding_package_entries(
        package_roots=(),
        plugin_sources=(source,),
        disabled_plugins=(),
        cwd=tmp_path,
        materializer=materializer,
    )

    assert entries[0]["lifecycle"] == "installed"
    assert entries[0]["enabled"] is True
    assert entries[0]["prompts"] == 1


def test_package_projection_reads_installed_remote_manifest_version(tmp_path) -> None:
    from pathlib import Path

    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import collect_coding_package_entries
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        target = Path(record.target_path)
        target.mkdir(parents=True)
        (target / "plugin.json").write_text(json.dumps({"name": "review-pack", "version": "1.2.3"}), encoding="utf-8")
        return record.with_lifecycle("installed", target_path=target)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    asyncio.run(materializer.materialize_remote_source(source))

    entries = collect_coding_package_entries(
        package_roots=(),
        plugin_sources=(source,),
        disabled_plugins=(),
        cwd=tmp_path,
        materializer=materializer,
    )

    assert entries[0]["version"] == "1.2.3"


def test_package_projection_adds_conflict_diagnostics_for_same_name_versions(tmp_path) -> None:
    from loushang.coding.resource_runtime import collect_coding_package_entries

    first = tmp_path / "plugins" / "debug-pack-a"
    second = tmp_path / "plugins" / "debug-pack-b"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "plugin.json").write_text(json.dumps({"name": "debug-pack", "version": "1.0.0"}), encoding="utf-8")
    (second / "plugin.json").write_text(json.dumps({"name": "debug-pack", "version": "2.0.0"}), encoding="utf-8")

    entries = collect_coding_package_entries(
        package_roots=(),
        plugin_sources=(str(first), str(second)),
        disabled_plugins=(),
        cwd=tmp_path,
    )

    assert [entry["versionConflict"] for entry in entries] == [True, True]
    assert entries[0]["conflictDiagnostics"] == (
        {
            "code": "package_version_conflict",
            "message": "Package 'debug-pack' has multiple configured versions: 1.0.0, 2.0.0.",
            "path": str(first.resolve()),
            "packageName": "debug-pack",
            "conflictVersions": ["1.0.0", "2.0.0"],
        },
    )


def test_package_projection_summarizes_manifest_package_root(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import collect_coding_package_entries
    from loushang.harness.resources.packages.source import PackageSourceConfig

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record):
        (record.target_path / "resources" / "prompts").mkdir(parents=True)
        (record.target_path / "prompts").mkdir()
        (record.target_path / "resources" / "prompts" / "chosen.md").write_text("chosen", encoding="utf-8")
        (record.target_path / "resources" / "prompts" / "second.md").write_text("second", encoding="utf-8")
        (record.target_path / "prompts" / "ignored.md").write_text("ignored", encoding="utf-8")
        (record.target_path / "plugin.json").write_text(
            json.dumps({"name": "review-pack", "version": "1.2.3", "packageRoot": "resources"}),
            encoding="utf-8",
        )
        return record.with_lifecycle("installed", target_path=record.target_path)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    asyncio.run(materializer.materialize_remote_source(source))

    entries = collect_coding_package_entries(
        package_roots=(),
        plugin_sources=(),
        package_sources=(PackageSourceConfig(source=source),),
        disabled_plugins=(),
        cwd=tmp_path,
        materializer=materializer,
    )

    assert entries[0]["version"] == "1.2.3"
    assert entries[0]["prompts"] == 2
    assert entries[0]["packageRoot"] == str(tmp_path / "packages" / "review-pack" / "resources")


def test_package_projection_reports_invalid_remote_manifest_diagnostics(tmp_path) -> None:
    from pathlib import Path

    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import collect_coding_package_entries
    from loushang.harness.resources.packages.materializer import (
        PackageMaterializationRecord,
    )

    source = "https://packages.example.invalid/review-pack.git"

    async def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        target = Path(record.target_path)
        target.mkdir(parents=True)
        (target / "prompts").mkdir()
        (target / "prompts" / "review.md").write_text("Review prompt", encoding="utf-8")
        (target / "plugin.json").write_text("{not json", encoding="utf-8")
        return record.with_lifecycle("installed", target_path=target)

    materializer = PackageMaterializer(install_root=tmp_path / "packages", backend=backend)
    asyncio.run(materializer.materialize_remote_source(source))

    entries = collect_coding_package_entries(
        package_roots=(),
        plugin_sources=(source,),
        disabled_plugins=(),
        cwd=tmp_path,
        materializer=materializer,
    )

    assert entries[0]["version"] == ""
    assert entries[0]["diagnostics"] == 1
    assert entries[0]["manifestDiagnostics"][0]["code"] == "invalid_package_manifest"


def test_package_projection_reports_denied_materializer_security(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingPackageMaterializer as PackageMaterializer,
    )
    from loushang.coding.resource_runtime import collect_coding_package_entries

    source = "http://packages.example.invalid/review-pack.git"
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    asyncio.run(materializer.materialize_remote_source(source))

    entries = collect_coding_package_entries(
        package_roots=(),
        plugin_sources=(source,),
        disabled_plugins=(),
        cwd=tmp_path,
        materializer=materializer,
    )

    assert entries[0]["lifecycle"] == "failed"
    assert entries[0]["security"] == "denied"
    assert entries[0]["enabled"] is False
