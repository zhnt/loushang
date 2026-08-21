from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

import pytest

from loushang.harness.resources.packages.manifest import resolve_package_manifest
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.resources.plugins.resolver import PluginResolver
from loushang.harness.resources.plugins.types import (
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
    assert resolver.resolve_resources(plugin).package_roots == (resources.resolve(),)


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
