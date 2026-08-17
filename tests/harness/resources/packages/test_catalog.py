from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.resources.loader import ResourceLoaderProfile
from loushang.harness.resources.packages.catalog import (
    PackageCatalogBuilder,
    PackageCatalogEntry,
    PackageCatalogSources,
    package_catalog_sources,
    summarize_profiled_package_resources,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.projection import project_package_entry
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.types import PackageResourceSummary


def test_catalog_builds_local_plugin_entries_and_marks_version_conflicts(
    tmp_path: Path,
) -> None:
    first = tmp_path / "plugins" / "review-a"
    second = tmp_path / "plugins" / "review-b"
    for root, version in ((first, "1.0.0"), (second, "2.0.0")):
        root.mkdir(parents=True)
        (root / "plugin.json").write_text(
            json.dumps({"name": "review-pack", "version": version}),
            encoding="utf-8",
        )

    builder = PackageCatalogBuilder(summary_provider=_summary)
    entries = builder.collect(
        sources=PackageCatalogSources(
            plugin_sources=((str(first), "merged"), (str(second), "merged")),
        ),
        cwd=tmp_path,
    )

    assert [entry.name for entry in entries] == ["review-pack", "review-pack"]
    assert [entry.summary.prompt_count for entry in entries] == [1, 1]
    assert [entry.conflict_versions for entry in entries] == [
        ("1.0.0", "2.0.0"),
        ("1.0.0", "2.0.0"),
    ]
    assert entries[0].conflict_diagnostics[0].code == "package_version_conflict"


def test_catalog_projects_prepared_remote_source_without_product_policy(
    tmp_path: Path,
) -> None:
    source = "https://packages.example.invalid/review-pack.git"
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    materializer.prepare_remote_source(source)

    entries = PackageCatalogBuilder(summary_provider=_summary).collect(
        sources=PackageCatalogSources(
            package_sources=((PackageSourceConfig(source=source), "merged"),),
        ),
        cwd=tmp_path,
        materializer=materializer,
    )

    assert len(entries) == 1
    assert entries[0].kind == "remote_package"
    assert entries[0].lifecycle == "materialization_pending"
    assert entries[0].enabled is False
    assert entries[0].path == tmp_path / "packages" / "review-pack"


def test_package_projection_is_available_without_coding() -> None:
    entry = PackageCatalogEntry(
        name="review-pack",
        kind="package_root",
        scope="project",
        version="1.0.0",
        source="/workspace/packages/review-pack",
        path=Path("/workspace/packages/review-pack"),
        enabled=True,
        summary=PackageResourceSummary(source_root=Path("/workspace/packages")),
    )

    assert project_package_entry(entry) == {
        "name": "review-pack",
        "kind": "package_root",
        "packageKind": "local_package_root",
        "scope": "project",
        "version": "1.0.0",
        "source": "/workspace/packages/review-pack",
        "path": "/workspace/packages/review-pack",
        "enabled": True,
        "prompts": 0,
        "skills": 0,
        "extensions": 0,
        "themes": 0,
        "diagnostics": 0,
        "description": "",
    }


def test_profiled_package_summary_uses_product_resource_profile(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "design-package"
    skill_root = package_root / "skills" / "layout-review"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: layout-review\ndescription: Review a layout\n---\n",
        encoding="utf-8",
    )

    summary = summarize_profiled_package_resources(
        package_root,
        tmp_path,
        profile=ResourceLoaderProfile(
            built_in_resource_packages=(),
            context_file_names=("DESIGN.md",),
            user_resource_roots=(),
            project_resource_mode="legacy",
        ),
    )

    assert summary.source_root == package_root
    assert summary.skill_count == 1


def test_catalog_sources_resolve_scoped_local_paths_and_prefer_project_sources(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user"
    project_root = tmp_path / "project"
    settings = _Settings(
        global_base_dir=user_root,
        project_base_dir=project_root,
        global_settings={
            "packages": ["packages/shared", "git:github.com/acme/review@v1"]
        },
        project_settings={
            "packages": ["packages/shared", "git:github.com/acme/review@v2"]
        },
    )

    sources = package_catalog_sources(
        settings,
        package_roots=(),
        plugin_sources=(),
        package_sources=(),
    )

    assert [(source.source, scope) for source, scope in sources.package_sources] == [
        (str((project_root / "packages" / "shared").resolve()), "project"),
        ("git:github.com/acme/review@v2", "project"),
        (str((user_root / "packages" / "shared").resolve()), "user"),
    ]


def _summary(
    package_root: Path,
    _cwd: Path,
    _source: PackageSourceConfig | None,
) -> PackageResourceSummary:
    return PackageResourceSummary(source_root=package_root, prompt_count=1)


@dataclass
class _Settings:
    global_base_dir: Path
    project_base_dir: Path
    global_settings: dict[str, object]
    project_settings: dict[str, object]

    def get_global_settings(self) -> dict[str, object]:
        return self.global_settings

    def get_project_settings(self) -> dict[str, object]:
        return self.project_settings

    def get_session_settings(self) -> dict[str, object]:
        return {}
