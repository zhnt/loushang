from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

import pytest

from loushang.harness.resources.packages.manifest import resolve_package_manifest
from loushang.harness.resources.plugins.manager import PluginManager
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.resources.plugins.resolver import PluginResolver
from loushang.harness.resources.plugins.types import (
    InstalledPlugin,
    PluginManifest,
    PluginSource,
    ResolvedPluginPackage,
)


def test_plugin_manifest_parser_returns_authority_bound_descriptor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-pack"
    package_root = root / "resources"
    package_root.mkdir(parents=True)
    payload = {
        "name": "review-pack",
        "version": "1.2.3",
        "enabled": True,
        "packageRoot": "resources",
        "contributions": {"commands": ["review"]},
    }
    encoded = json.dumps(payload, sort_keys=True).encode()
    (root / "plugin.json").write_bytes(encoded)
    source = PluginSource(path=root, enabled=False)

    resolved = PluginManifestParser().parse(root, source=source)

    assert isinstance(resolved, ResolvedPluginPackage)
    assert resolved.root == root.resolve()
    assert resolved.package_root == package_root.resolve()
    assert resolved.manifest_path == (root / "plugin.json").resolve()
    assert resolved.manifest_digest == sha256(encoded).hexdigest()
    assert resolved.source == PluginSource(path=root.resolve(), enabled=False)
    assert resolved.manifest.name == "review-pack"
    assert resolved.manifest.version == "1.2.3"
    assert resolved.manifest.enabled is True
    assert resolved.manifest.metadata == {
        **payload,
        "contributions": MappingProxyType({"commands": ("review",)}),
    }
    with pytest.raises(TypeError):
        resolved.manifest.metadata["name"] = "changed"  # type: ignore[index]


def test_plugin_and_package_views_reuse_one_resolved_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "review-pack"
    resources = root / "resources"
    resources.mkdir(parents=True)
    manifest_path = root / "plugin.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "review-pack",
                "version": "1.0.0",
                "packageRoot": "resources",
            }
        ),
        encoding="utf-8",
    )
    original_read_bytes = Path.read_bytes
    reads: list[Path] = []

    def record_read(path: Path) -> bytes:
        reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", record_read)
    resolver = PluginResolver(manifest_parser=PluginManifestParser())

    plugin = resolver.resolve_plugin(root)

    assert reads == [manifest_path]
    assert plugin.resolved_package is not None
    manifest_path.write_text("{changed after resolution", encoding="utf-8")

    package_view = resolve_package_manifest(
        root,
        resolved_plugin_package=plugin.resolved_package,
    )

    assert reads == [manifest_path]
    assert package_view.resolved_plugin_package is plugin.resolved_package
    assert package_view.version == "1.0.0"
    assert package_view.package_root == resources.resolve()
    with pytest.raises(PluginManifestError) as caught:
        resolver.resolve_resources(plugin)

    assert caught.value.code == "plugin_package_changed"


def test_disabled_plugin_projects_effective_state_without_reparsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    manifest_path = root / "plugin.json"
    manifest_path.write_text(
        json.dumps({"name": "review-pack", "enabled": True}),
        encoding="utf-8",
    )
    original_read_bytes = Path.read_bytes
    reads: list[Path] = []

    def record_read(path: Path) -> bytes:
        reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", record_read)

    plugin = PluginManager(disabled_plugins=("review-pack",)).add_plugin_source(root)

    assert plugin.enabled is False
    assert plugin.manifest.enabled is True
    assert reads == [manifest_path]


def test_package_manifest_entrypoint_delegates_plugin_json_to_canonical_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "version": "2.0.0"}),
        encoding="utf-8",
    )
    original_parse = PluginManifestParser.parse
    parsed: list[ResolvedPluginPackage] = []

    def record_parse(
        parser: PluginManifestParser,
        candidate: str | Path,
        *,
        source: PluginSource | None = None,
    ) -> ResolvedPluginPackage:
        descriptor = original_parse(parser, candidate, source=source)
        parsed.append(descriptor)
        return descriptor

    monkeypatch.setattr(PluginManifestParser, "parse", record_parse)

    package_view = resolve_package_manifest(root)

    assert len(parsed) == 1
    assert package_view.resolved_plugin_package is parsed[0]
    assert package_view.version == "2.0.0"


@pytest.mark.parametrize("package_root", ["../outside", "/absolute/outside"])
def test_plugin_manifest_parser_rejects_package_root_escape(
    tmp_path: Path,
    package_root: str,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "packageRoot": package_root}),
        encoding="utf-8",
    )

    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(root)

    assert caught.value.code == "invalid_plugin_manifest"
    assert caught.value.path == (root / "plugin.json").resolve()


@pytest.mark.parametrize("enabled", ["false", 0, 1, None, [], {}])
def test_plugin_manifest_parser_rejects_non_boolean_enabled(
    tmp_path: Path,
    enabled: object,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "enabled": enabled}),
        encoding="utf-8",
    )

    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(root)

    assert caught.value.code == "invalid_plugin_manifest"


@pytest.mark.parametrize("field", ["name", "version"])
@pytest.mark.parametrize("value", [7, "", "   ", None, [], {}])
def test_plugin_manifest_parser_rejects_invalid_identity_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({field: value}),
        encoding="utf-8",
    )

    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(root)

    assert caught.value.code == "invalid_plugin_manifest"


def test_plugin_manifest_parser_rejects_conflicting_package_root_aliases(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"packageRoot": "one", "package_root": "two"}),
        encoding="utf-8",
    )

    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(root)

    assert caught.value.code == "invalid_plugin_manifest"


def test_plugin_manifest_parser_normalizes_compatible_package_root_alias(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-pack"
    resources = root / "resources"
    resources.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"package_root": "resources"}),
        encoding="utf-8",
    )

    resolved = PluginManifestParser().parse(root)

    assert resolved.package_root == resources.resolve()
    assert resolved.manifest.metadata == {"packageRoot": "resources"}


def test_package_manifest_view_projects_package_root_symlink_loop_as_diagnostic(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    (root / "loop").symlink_to("loop")
    manifest_path = root / "plugin.json"
    manifest_path.write_text(
        json.dumps({"name": "review-pack", "packageRoot": "loop"}),
        encoding="utf-8",
    )

    resolved = resolve_package_manifest(root)

    assert resolved.resolved_plugin_package is None
    assert resolved.manifest_path == manifest_path.resolve()
    assert resolved.diagnostics[0]["code"] == "invalid_package_manifest"


def test_resource_package_view_projects_package_root_symlink_loop_as_diagnostic(
    tmp_path: Path,
) -> None:
    root = tmp_path / "resource-pack"
    root.mkdir()
    (root / "loop").symlink_to("loop")
    manifest_path = root / "loushang-package.json"
    manifest_path.write_text(
        json.dumps({"name": "resource-pack", "packageRoot": "loop"}),
        encoding="utf-8",
    )

    resolved = resolve_package_manifest(root)

    assert resolved.package_root == root.resolve()
    assert resolved.manifest_path == manifest_path.resolve()
    assert resolved.diagnostics[0]["code"] == "invalid_package_manifest"


def test_package_manifest_view_projects_canonical_plugin_parser_error(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    manifest_path = root / "plugin.json"
    manifest_path.write_text("{not json", encoding="utf-8")

    resolved = resolve_package_manifest(root)

    assert resolved.package_root == root.resolve()
    assert resolved.manifest_path == manifest_path.resolve()
    assert resolved.resolved_plugin_package is None
    assert resolved.diagnostics[0]["code"] == "invalid_package_manifest"


def test_package_manifest_view_rejects_dangling_plugin_manifest_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    manifest_path = root / "plugin.json"
    manifest_path.symlink_to(root / "missing-plugin.json")

    resolved = resolve_package_manifest(root)

    assert resolved.manifest_path == manifest_path
    assert resolved.resolved_plugin_package is None
    assert resolved.diagnostics[0]["code"] == "invalid_package_manifest"


def test_resolver_rejects_package_root_replaced_after_resolution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-pack"
    package_root = root / "resources"
    outside = tmp_path / "outside"
    package_root.mkdir(parents=True)
    outside.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "packageRoot": "resources"}),
        encoding="utf-8",
    )
    resolver = PluginResolver()
    plugin = resolver.resolve_plugin(root)
    package_root.rmdir()
    package_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PluginManifestError) as caught:
        resolver.resolve_resources(plugin)

    assert caught.value.code == "plugin_package_changed"


def test_resolver_rejects_enabled_plugin_without_canonical_descriptor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy"
    root.mkdir()
    plugin = InstalledPlugin(
        manifest=PluginManifest(name="legacy", root=root, package_root=root),
        source=PluginSource(path=root),
    )

    with pytest.raises(PluginManifestError) as caught:
        PluginResolver().resolve_resources(plugin)

    assert caught.value.code == "unresolved_plugin_package"


def test_materialized_remote_source_identity_is_bound_to_descriptor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    source = PluginSource(
        path=root,
        url="https://packages.example.invalid/review-pack.git",
        kind="remote",
    )

    resolved = PluginManifestParser().parse(root, source=source)

    assert resolved.source == PluginSource(
        path=root.resolve(),
        url=source.url,
        kind="remote",
    )


def test_plugin_manifest_parser_returns_default_descriptor_without_manifest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "resource-only"
    root.mkdir()

    resolved = PluginManifestParser().parse(root)

    assert resolved.manifest.name == "resource-only"
    assert resolved.manifest_path is None
    assert resolved.manifest_digest is None
    assert resolved.package_root == root.resolve()
