from __future__ import annotations

from pathlib import Path

from loushang.harness.policy import PolicyDecision
from loushang.harness.resources.builtin import (
    BuiltInResourcePackage,
    BuiltInResourceRegistry,
)
from loushang.harness.resources.layout import (
    DEFAULT_SCOPE_PRECEDENCE,
    STANDARD_RESOURCE_DIRECTORIES,
    resolve_platform_home,
    resolve_product_resource_root,
    resolve_user_resource_roots,
    resolve_workspace_resource_root,
)
from loushang.harness.resources.loader import (
    ProfiledResourceLoader,
    ResourceLoader,
    ResourceLoaderProfile,
)
from loushang.harness.resources.packages import (
    PackageMaterializationRecord,
    PackageMaterializer,
    PackageSourceConfig,
    package_source_from_raw,
)
from loushang.harness.resources.plugins import (
    InstalledPlugin,
    PluginManager,
    PluginManifest,
    PluginRegistry,
    PluginSource,
)


class _AllowPackageSources:
    def evaluate_package_source(self, source: str | Path) -> PolicyDecision:
        del source
        return PolicyDecision.allow()


def test_resource_registries_public_key_compatibility_baseline(tmp_path) -> None:
    built_ins = BuiltInResourceRegistry()
    first_package = BuiltInResourcePackage(name="shared", package="first.resources")
    replacement_package = BuiltInResourcePackage(
        name="shared",
        package="replacement.resources",
    )

    assert built_ins.register(first_package) is first_package
    assert built_ins.register(replacement_package) is replacement_package
    assert built_ins.list_packages() == (replacement_package,)
    assert built_ins.unregister("shared") is replacement_package
    assert built_ins.unregister("shared") is None

    plugins = PluginRegistry()
    first_plugin = InstalledPlugin(
        manifest=PluginManifest(name="shared", root=tmp_path / "first"),
        source=PluginSource(path=tmp_path / "first"),
    )
    replacement_plugin = InstalledPlugin(
        manifest=PluginManifest(name="shared", root=tmp_path / "replacement"),
        source=PluginSource(path=tmp_path / "replacement"),
    )

    assert plugins.register(first_plugin) is first_plugin
    assert plugins.register(replacement_plugin) is replacement_plugin
    assert plugins.list_plugins() == [replacement_plugin]
    assert plugins.unregister("shared") is replacement_plugin
    assert plugins.unregister("shared") is None


def test_platform_resource_layout_resolves_standard_roots(tmp_path) -> None:
    configured_home = tmp_path / "shared-home"
    workspace = tmp_path / "workspace"

    assert (
        resolve_platform_home(
            environ={"LOUSHANG_HOME": str(configured_home)},
            home=tmp_path / "ignored-home",
        )
        == configured_home.resolve()
    )
    assert (
        resolve_platform_home(environ={}, home=tmp_path)
        == (tmp_path / ".loushang").resolve()
    )
    assert (
        resolve_workspace_resource_root(workspace)
        == (workspace / ".loushang").resolve()
    )
    assert (
        resolve_product_resource_root("research", platform_home=configured_home)
        == configured_home.resolve() / "products" / "research"
    )
    assert STANDARD_RESOURCE_DIRECTORIES == (
        "prompts",
        "skills",
        "extensions",
        "themes",
        "packages",
    )
    assert DEFAULT_SCOPE_PRECEDENCE == (
        "temporary",
        "project",
        "user",
        "package",
        "built_in",
    )


def test_user_resource_roots_include_platform_and_explicit_roots(tmp_path) -> None:
    platform_home = tmp_path / "platform"
    global_base = tmp_path / "settings"

    roots, explicit = resolve_user_resource_roots(
        ("team",),
        global_base_dir=global_base,
        environ={"LOUSHANG_HOME": str(platform_home)},
    )

    assert roots == (platform_home.resolve(), (global_base / "team").resolve())
    assert explicit == frozenset({(global_base / "team").resolve()})


def test_resource_loader_discovers_registered_builtin_package(
    tmp_path, monkeypatch
) -> None:
    package_root = tmp_path / "neutral_resources"
    prompts = package_root / "prompts"
    prompts.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (prompts / "review.md").write_text("Neutral review rules", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    registry = BuiltInResourceRegistry()
    registry.register(
        BuiltInResourcePackage(name="neutral", package="neutral_resources")
    )
    loader = ResourceLoader(
        built_in_resource_registry=registry,
        user_resource_roots=(),
    )

    bundle = loader.discover_resources(tmp_path / "project")

    assert [prompt.name for prompt in bundle.prompts] == ["review"]
    assert bundle.prompts[0].source_kind == "built_in"
    assert bundle.prompts[0].source_path == Path("neutral_resources/prompts/review.md")
    assert loader.get_resource_snapshot().source_kinds == (
        "built_in",
        "project_local",
    )


def test_resource_loader_requires_explicit_compatibility_context_convention(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text("Compatibility guidance", encoding="utf-8")

    standard = ResourceLoader(user_resource_roots=()).discover_resources(workspace)
    compatibility = ResourceLoader(
        context_file_names=("CLAUDE.md",),
        user_resource_roots=(),
    ).discover_resources(workspace)

    assert standard.agents_md is None
    assert compatibility.agents_md == "Compatibility guidance"
    assert compatibility.prompt_descriptors[0].prompt_kind == "claude_md"


def test_resource_loader_uses_standard_workspace_resource_root(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    prompts = workspace / ".loushang" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "review.md").write_text("Workspace review rules", encoding="utf-8")

    bundle = ResourceLoader(user_resource_roots=()).discover_resources(workspace)

    assert [prompt.name for prompt in bundle.prompts] == ["review"]
    assert bundle.prompts[0].source_root == workspace / ".loushang" / "prompts"


def test_profiled_resource_loader_injects_product_conventions(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "RESEARCH.md").write_text("Cite primary sources.", encoding="utf-8")
    profile = ResourceLoaderProfile(
        context_file_names=("RESEARCH.md",),
        user_resource_roots=(),
        project_resource_mode="legacy",
        system_prompt_assembler=lambda base, bundle: "\n".join(
            item for item in (base, bundle.agents_md) if isinstance(item, str) and item
        ),
    )
    loader = ProfiledResourceLoader(profile=profile)

    bundle = loader.discover_resources(workspace)

    assert bundle.agents_md == "Cite primary sources."
    assert loader.get_system_prompt(base_prompt="Research carefully.") == (
        "Research carefully.\nCite primary sources."
    )


def test_package_materializer_requires_product_policy(tmp_path) -> None:
    source = "https://packages.example.invalid/review-pack.git"
    calls: list[str] = []

    def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        calls.append(record.source)
        return record.with_lifecycle("installed")

    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
    )

    record = materializer.materialize_remote_source_sync(source)

    assert record.lifecycle == "failed"
    assert record.security == "denied"
    assert record.error_message == (
        "Package source policy must be supplied by the product adapter."
    )
    assert calls == []


def test_package_materializer_accepts_injected_policy(tmp_path) -> None:
    source = "https://packages.example.invalid/review-pack.git"

    def backend(
        record: PackageMaterializationRecord,
    ) -> PackageMaterializationRecord:
        return record.with_lifecycle("installed")

    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        security_policy=_AllowPackageSources(),
    )

    assert materializer.materialize_remote_source_sync(source).lifecycle == "installed"


def test_package_source_parser_and_plugin_registry_are_product_neutral(
    tmp_path,
) -> None:
    config = package_source_from_raw(
        {"source": "pypi:review-pack", "skills": ["review", "debug"]}
    )
    assert config == PackageSourceConfig(
        source="pypi:review-pack",
        skills=("review", "debug"),
    )

    plugin_root = tmp_path / "review-pack"
    plugin_root.mkdir()
    manager = PluginManager()
    plugin = manager.add_plugin_source(plugin_root)

    assert plugin.manifest.name == "review-pack"
    assert manager.resolve_package_roots() == (plugin_root.resolve(),)
