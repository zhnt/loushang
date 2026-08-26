from __future__ import annotations

import ast
from collections.abc import Mapping
from functools import cache
from pathlib import Path

BASELINE_PATH = Path(
    "docs/internals/architecture/harness/resource-catalog-rcp0-baseline.md"
)
PLAN_PATH = Path(
    "docs/internals/architecture/harness/resource-catalog-pluginization-plan.md"
)
README_PATH = Path("docs/internals/architecture/harness/README.md")
SOURCE_ROOT = Path("src/loushang")
LEGACY_LOADER_ROOT = Path("src/loushang/harness/resources")
PACKAGE_SOURCE_PATH = Path("src/loushang/harness/resources/_catalog_package_source.py")
EMBEDDED_SOURCE_PATH = Path(
    "src/loushang/harness/resources/_catalog_embedded_source.py"
)
RESOURCE_INPUTS_PATH = Path("src/loushang/harness/resource_catalog/inputs.py")

EXPECTED_CALL_SITES = {
    "discover_resources": {
        (
            Path("src/loushang/harness/bootstrap.py"),
            "ResourceBootstrapRuntime.discover",
        ),
        (
            Path("src/loushang/harness/bootstrap.py"),
            "create_standard_resource_bootstrap_runtime",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.reload_resources",
        ),
        (
            Path("src/loushang/harness/resources/skills.py"),
            "SkillLoader.discover_skills",
        ),
        (Path("src/loushang/method/loader.py"), "MethodLoader.discover_methods"),
    },
    "reload_resources": {
        (
            Path("src/loushang/harness/resources/skills.py"),
            "SkillLoader.reload_skills",
        ),
        (
            Path("src/loushang/harness/session/resource_refresh.py"),
            "SessionResourceRefreshRuntime._load_resource_bundle",
        ),
    },
    "get_resource_snapshot": {
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_diagnostics",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_extensions",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_package_resource_summaries",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_resource_bundle",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_resource_diagnostics",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_skills",
        ),
        (
            Path("src/loushang/harness/resources/skills.py"),
            "SkillLoader.list_skills",
        ),
    },
    "get_resource_bundle": {
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ProfiledResourceLoader.get_system_prompt",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_agents_files",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_append_system_prompt",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_prompts",
        ),
        (
            Path("src/loushang/harness/session/command_sources.py"),
            "ResourceCommandSourceRuntime.execute",
        ),
        (
            Path("src/loushang/harness/session/command_sources.py"),
            "ResourceCommandSourceRuntime.list_descriptors",
        ),
        (
            Path("src/loushang/harness/session/command_sources.py"),
            "ResourceCommandSourceRuntime.preflight_user_input",
        ),
        (
            Path("src/loushang/harness/session/resource_refresh.py"),
            "SessionResourceRefreshRuntime.__post_init__",
        ),
        (
            Path("src/loushang/harness/session/resource_refresh.py"),
            "SessionResourceRefreshRuntime._commit_resource_bundle",
        ),
        (
            Path("src/loushang/harness/session/resource_refresh.py"),
            "SessionResourceRefreshRuntime.get_prompt_templates",
        ),
        (
            Path("src/loushang/harness/session/resource_refresh.py"),
            "SessionResourceRefreshRuntime.reload_extension_generation",
        ),
        (
            Path("src/loushang/harness/session/tool_controller.py"),
            "create_tool_prompt_rebuilder.rebuild",
        ),
    },
}

EXPECTED_SKILLS_ATTRIBUTE_LOAD_SITES = {
    (
        Path("src/loushang/harness/commands/resources.py"),
        "list_resource_command_descriptors",
    ),
    (
        Path("src/loushang/harness/config/agent/_settings_codec.py"),
        "_serialize_package_source",
    ),
    # RCP4 keeps these reads inside the private Extension hook-pass adapter.
    # They normalize and bind source evidence; none is effective Catalog authority.
    (
        Path("src/loushang/harness/extensions/resources.py"),
        "_bind_contribution_source_facts",
    ),
    (
        Path("src/loushang/harness/extensions/resources.py"),
        "_catalog_route_contribution",
    ),
    (Path("src/loushang/harness/extensions/resources.py"), "_defensive_bundle"),
    (
        Path("src/loushang/harness/extensions/resources.py"),
        "_merge_normalized_contribution",
    ),
    (
        Path("src/loushang/harness/resources/_catalog_extension_source.py"),
        "ExtensionResourceRouteContribution.__post_init__",
    ),
    (
        Path("src/loushang/harness/resources/_catalog_extension_source.py"),
        "_descriptor_records",
    ),
    (
        Path("src/loushang/harness/resources/_loader_discovery.py"),
        "_apply_resource_switches",
    ),
    (
        Path("src/loushang/harness/resources/_loader_discovery.py"),
        "_discover_external_package_resources",
    ),
    (
        Path("src/loushang/harness/resources/_loader_pipeline.py"),
        "_ResourceDiscoveries.skills",
    ),
    (
        Path("src/loushang/harness/resources/_loader_pipeline.py"),
        "_discover_snapshot",
    ),
    (
        Path("src/loushang/harness/resources/_loader_pipeline.py"),
        "_legacy_package_resource_candidate_facts",
    ),
    (
        Path("src/loushang/harness/resources/activation.py"),
        "ResourceActivation.active_skills",
    ),
    (Path("src/loushang/harness/resources/activation.py"), "apply_disabled_skills"),
    (
        Path("src/loushang/harness/resources/packages/source.py"),
        "PackageSourceConfig.filtered",
    ),
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "FilesystemPackageResourceInventory.summarize",
    ),
    # The optional RCP4 Session adapter only takes a defensive Extension input
    # copy; the final compatibility Bundle is projected from Catalog authority.
    (
        Path("src/loushang/harness/resource_catalog/session_bootstrap.py"),
        "_defensive_bundle",
    ),
    (
        Path("src/loushang/harness/resources/types.py"),
        "ResourceBundle.merge",
    ),
    (
        Path("src/loushang/harness/session/agent_adapter.py"),
        "AgentSessionAdapterMixin._before_agent_start_system_prompt_options",
    ),
    (
        Path("src/loushang/harness/session/agent_adapter.py"),
        "AgentSessionAdapterMixin._resource_watch_paths",
    ),
    (
        Path("src/loushang/harness/session/agent_product.py"),
        "AgentProductSession._composition_ports",
    ),
    (Path("src/loushang/method/loader.py"), "MethodLoader.discover_methods"),
}

LEGACY_LOADER_MODULES = (
    "_loader_discovery.py",
    "_loader_discovery_builtin.py",
    "_loader_discovery_context.py",
    "_loader_discovery_filesystem.py",
    "_loader_discovery_temporary.py",
    "_loader_descriptor_parsing.py",
    "_loader_package_policy.py",
    "_loader_pipeline.py",
    "_loader_precedence.py",
    "_loader_resolution.py",
    "_loader_types.py",
)

EXPECTED_LEGACY_LOADER_IMPORT_EDGES = {
    (LEGACY_LOADER_ROOT / importer, imported)
    for importer, imported in (
        ("_loader_discovery.py", "_loader_discovery_filesystem"),
        ("_loader_discovery.py", "_loader_package_policy"),
        ("_loader_discovery.py", "_loader_types"),
        ("_loader_discovery_builtin.py", "_loader_descriptor_parsing"),
        ("_loader_discovery_builtin.py", "_loader_types"),
        ("_loader_discovery_context.py", "_loader_types"),
        ("_loader_discovery_filesystem.py", "_loader_descriptor_parsing"),
        ("_loader_discovery_filesystem.py", "_loader_types"),
        ("_loader_discovery_temporary.py", "_loader_descriptor_parsing"),
        ("_loader_discovery_temporary.py", "_loader_discovery_filesystem"),
        ("_loader_discovery_temporary.py", "_loader_types"),
        ("_loader_package_policy.py", "_loader_types"),
        ("_loader_pipeline.py", "_loader_discovery"),
        ("_loader_pipeline.py", "_loader_discovery_builtin"),
        ("_loader_pipeline.py", "_loader_discovery_context"),
        ("_loader_pipeline.py", "_loader_discovery_temporary"),
        ("_loader_pipeline.py", "_loader_resolution"),
        ("_loader_pipeline.py", "_loader_types"),
        ("_loader_precedence.py", "_loader_types"),
        ("_loader_resolution.py", "_loader_precedence"),
        ("_loader_resolution.py", "_loader_types"),
        ("loader.py", "_loader_package_policy"),
        ("loader.py", "_loader_pipeline"),
        ("loader.py", "_loader_types"),
    )
}


@cache
def _source_texts() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
    }


class _QualifiedFunctionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        qualified = ".".join((*self.scope, node.name))
        self.functions.append((qualified, node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _qualified_functions(
    source: str,
    *,
    filename: Path,
) -> tuple[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef], ...]:
    visitor = _QualifiedFunctionVisitor()
    visitor.visit(ast.parse(source, filename=str(filename)))
    return tuple(visitor.functions)


class _CodeUnitNodeVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.nodes: list[ast.AST] = []

    def generic_visit(self, node: ast.AST) -> None:
        self.nodes.append(node)
        super().generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        del node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        del node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        del node

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node


def _code_unit_nodes(body: list[ast.stmt]) -> tuple[ast.AST, ...]:
    visitor = _CodeUnitNodeVisitor()
    for statement in body:
        visitor.visit(statement)
    return tuple(visitor.nodes)


def _call_sites(
    sources: Mapping[Path, str],
    callable_name: str,
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if callable_name not in source:
            continue
        for qualified, function in _qualified_functions(source, filename=path):
            if any(
                isinstance(node, ast.Call)
                and (
                    isinstance(node.func, ast.Name)
                    and node.func.id == callable_name
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == callable_name
                )
                for parent in _code_unit_nodes(function.body)
                for node in ast.walk(parent)
            ):
                sites.add((path, qualified))
    return sites


def _attribute_load_sites(
    sources: Mapping[Path, str],
    attribute_name: str,
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if f".{attribute_name}" not in source:
            continue
        for qualified, function in _qualified_functions(source, filename=path):
            if any(
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Load)
                and node.attr == attribute_name
                for parent in _code_unit_nodes(function.body)
                for node in ast.walk(parent)
            ):
                sites.add((path, qualified))
    return sites


def _named_attribute_load_sites(
    sources: Mapping[Path, str],
    *,
    receiver_name: str,
    attribute_name: str,
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if f"{receiver_name}.{attribute_name}" not in source:
            continue
        for qualified, function in _qualified_functions(source, filename=path):
            if any(
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Load)
                and node.attr == attribute_name
                and isinstance(node.value, ast.Name)
                and node.value.id == receiver_name
                for parent in _code_unit_nodes(function.body)
                for node in ast.walk(parent)
            ):
                sites.add((path, qualified))
    return sites


def _getattr_sites(
    sources: Mapping[Path, str],
    *,
    receiver_name: str,
    attribute_name: str,
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if "getattr" not in source or attribute_name not in source:
            continue
        for qualified, function in _qualified_functions(source, filename=path):
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == receiver_name
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == attribute_name
                for parent in _code_unit_nodes(function.body)
                for node in ast.walk(parent)
            ):
                sites.add((path, qualified))
    return sites


def _keyword_sites(
    sources: Mapping[Path, str],
    keyword_name: str,
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if keyword_name not in source:
            continue
        for qualified, function in _qualified_functions(source, filename=path):
            if any(
                isinstance(node, ast.keyword) and node.arg == keyword_name
                for parent in _code_unit_nodes(function.body)
                for node in ast.walk(parent)
            ):
                sites.add((path, qualified))
    return sites


def _legacy_loader_import_edges(
    sources: Mapping[Path, str],
) -> set[tuple[Path, str]]:
    prefix = "loushang.harness.resources."
    edges: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if not node.module.startswith(f"{prefix}_loader"):
                continue
            edges.add((path, node.module.removeprefix(prefix)))
    return edges


def _imported_modules(source: str, *, filename: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source, filename=str(filename))):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _text_record_fields(document: str, heading: str) -> tuple[str, ...]:
    section = document.split(heading, maxsplit=1)[1]
    block = section.split("```text", maxsplit=1)[1].split("```", maxsplit=1)[0]
    return tuple(line.strip() for line in block.splitlines() if line.strip())


def test_rcp0_baseline_is_indexed_and_distinguishes_private_rcp3_implementation() -> (
    None
):
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    plan = PLAN_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "resource-catalog-rcp0-baseline.md" in plan
    assert readme.count("resource-catalog-rcp0-baseline.md") == 2
    assert "RCP1 through RCP3 remain private foundations" in baseline
    assert "No Product invokes\n  them by default" in baseline
    assert "v1 legacy loader remains the default Resource" in baseline
    assert "authority and no cutover or refresh" in baseline
    assert "grants no new public API" in baseline


def test_rcp0_discovery_and_projection_caller_inventory_is_exact() -> None:
    sources = _source_texts()

    for callable_name, expected in EXPECTED_CALL_SITES.items():
        assert _call_sites(sources, callable_name) == expected


def test_rcp0_skill_fallback_projection_and_eager_body_sinks_are_exact() -> None:
    sources = _source_texts()
    skill_listing_path = Path("src/loushang/harness/cli/skill_listing.py")

    assert _getattr_sites(
        sources,
        receiver_name="bundle",
        attribute_name="skills",
    ) == {(skill_listing_path, "list_skill_records")}
    assert _getattr_sites(
        sources,
        receiver_name="loader",
        attribute_name="get_skills",
    ) == {(skill_listing_path, "list_skill_records")}
    assert _call_sites(sources, "get_skills") == set()
    assert (
        _attribute_load_sites(sources, "skills") == EXPECTED_SKILLS_ATTRIBUTE_LOAD_SITES
    )
    assert _named_attribute_load_sites(
        sources,
        receiver_name="skill",
        attribute_name="content",
    ) == {
        (
            Path("src/loushang/harness/capabilities/prompt_preflight.py"),
            "_preflight_resource_input",
        ),
        (
            Path("src/loushang/harness/commands/resources.py"),
            "command_description_from_skill",
        ),
        (
            Path("src/loushang/method/skill_adapter.py"),
            "method_from_skill",
        ),
    }


def test_rcp0_legacy_authority_mount_and_extension_merge_inventory_is_exact() -> None:
    sources = _source_texts()
    extension_path = Path("src/loushang/harness/extensions/resources.py")

    assert _call_sites(sources, "ResourceSnapshot") == {
        (
            Path("src/loushang/harness/resources/_catalog_projection.py"),
            "ResourceCatalogProjection.to_compatibility_bundle",
        ),
        (
            Path("src/loushang/harness/resources/_catalog_shadow.py"),
            "project_shadow_compatibility_bundle",
        ),
        (
            Path("src/loushang/harness/resources/_loader_pipeline.py"),
            "_discover_snapshot",
        ),
        (
            Path("src/loushang/harness/resources/loader.py"),
            "ResourceLoader.get_resource_snapshot",
        ),
    }
    assert _call_sites(sources, "PackageResourceMount") == {
        (
            Path("src/loushang/harness/resources/loader.py"),
            "_package_mounts_from_legacy_roots",
        ),
        (
            Path("src/loushang/harness/resources/packages/roots.py"),
            "resolve_package_resource_roots",
        ),
    }
    assert _call_sites({extension_path: sources[extension_path]}, "merge") == {
        (extension_path, "ExtensionResourceRuntime._finish"),
        (extension_path, "_merge_normalized_contribution"),
    }
    for module in LEGACY_LOADER_MODULES:
        assert (Path("src/loushang/harness/resources") / module).is_file()
    assert _legacy_loader_import_edges(sources) == EXPECTED_LEGACY_LOADER_IMPORT_EDGES


def test_rcp0_initial_and_refresh_extension_ingress_inventory_is_exact() -> None:
    sources = _source_texts()
    bootstrap_path = Path("src/loushang/harness/bootstrap.py")
    extension_runtime_path = Path("src/loushang/harness/extensions/runtime.py")
    refresh_path = Path("src/loushang/harness/resources/refresh.py")
    session_refresh_path = Path("src/loushang/harness/session/resource_refresh.py")

    assert _call_sites(sources, "rediscover_resources") == {
        (bootstrap_path, "ResourceBootstrapRuntime.activate_extensions")
    }
    assert _keyword_sites(sources, "rediscover_resources") == {
        (bootstrap_path, "create_standard_resource_bootstrap_runtime")
    }
    assert _call_sites(sources, "RuntimeResourceDiscovery") == {
        (session_refresh_path, "SessionResourceRefreshRuntime.__post_init__")
    }
    assert _getattr_sites(
        sources,
        receiver_name="runtime",
        attribute_name="discover_resources",
    ) == {
        (refresh_path, "RuntimeResourceDiscovery.discover"),
        (refresh_path, "RuntimeResourceDiscovery.discover_async"),
    }
    assert _getattr_sites(
        sources,
        receiver_name="runtime",
        attribute_name="discover_resources_async",
    ) == {(refresh_path, "RuntimeResourceDiscovery.discover_async")}
    assert _call_sites(
        {extension_runtime_path: sources[extension_runtime_path]},
        "discover",
    ) == {(extension_runtime_path, "ExtensionRuntime.discover_resources")}
    assert _call_sites(
        {extension_runtime_path: sources[extension_runtime_path]},
        "discover_async",
    ) == {(extension_runtime_path, "ExtensionRuntime.discover_resources_async")}
    assert _keyword_sites(sources, "discover_resource") == {
        (session_refresh_path, "SessionResourceRefreshRuntime.__post_init__")
    }
    assert _keyword_sites(sources, "discover_resource_async") == {
        (session_refresh_path, "SessionResourceRefreshRuntime.__post_init__")
    }


def test_rcp0_refresh_mount_mutation_and_close_inventory_is_exact() -> None:
    sources = _source_texts()
    adapter_path = Path("src/loushang/harness/session/agent_adapter.py")
    loader_path = Path("src/loushang/harness/resources/loader.py")
    roots_path = Path("src/loushang/harness/resources/packages/roots.py")
    package_session_path = Path("src/loushang/harness/resources/packages/session.py")
    bootstrap_configuration_path = Path(
        "src/loushang/harness/session/bootstrap_configuration.py"
    )

    assert _call_sites(sources, "_configure_package_resource_roots") == {
        (adapter_path, "AgentSessionAdapterMixin._prepare_resource_refresh")
    }
    assert _call_sites(sources, "configure_package_resource_roots") == {
        (package_session_path, "SessionPackageController.refresh_package_resources"),
        (adapter_path, "AgentSessionAdapterMixin._configure_package_resource_roots"),
    }
    assert _call_sites(sources, "configure_resource_loader_roots") == {
        (
            package_session_path,
            "SessionPackageController.configure_package_resource_roots",
        ),
        (
            bootstrap_configuration_path,
            "StandardAgentSessionConfigurationRuntime._resource_roots",
        ),
    }
    assert _call_sites(sources, "set_package_mounts") == {
        (loader_path, "ResourceLoader.set_package_roots"),
        (roots_path, "configure_resource_loader_roots"),
    }
    assert _call_sites(sources, "_close_mounts") == {
        (roots_path, "configure_resource_loader_roots")
    }
    assert _call_sites(
        {loader_path: sources[loader_path], roots_path: sources[roots_path]},
        "close",
    ) == {
        (loader_path, "ResourceLoader.__del__"),
        (loader_path, "ResourceLoader.close"),
        (loader_path, "ResourceLoader.set_package_mounts"),
        (roots_path, "_close_mounts"),
        (roots_path, "_upsert_package_mount"),
        (roots_path, "resolve_package_resource_roots"),
    }
    assert _keyword_sites(sources, "prepare_refresh") == {
        (
            Path("src/loushang/harness/session/resource_refresh.py"),
            "SessionResourceRefreshRuntime.__post_init__",
        )
    }
    assert _keyword_sites(sources, "prepare_resource_refresh") == {
        (
            Path("src/loushang/harness/session/agent_product.py"),
            "AgentProductSession._composition_ports",
        ),
        (
            Path("src/loushang/harness/session/composition.py"),
            "_build_foundation_runtimes",
        ),
        (
            Path("src/loushang/harness/session/composition.py"),
            "_legacy_composition_inputs",
        ),
    }


def test_rcp3_package_catalog_uses_only_the_pure_inventory_bridge() -> None:
    sources = _source_texts()
    package_catalog_path = Path("src/loushang/harness/resources/packages/catalog.py")
    package_catalog = sources[package_catalog_path]

    assert (
        _call_sites(
            {package_catalog_path: package_catalog},
            "discover_resources",
        )
        == set()
    )
    assert "summarize_package_inventory" in package_catalog
    assert "ProfiledResourceLoader" not in package_catalog
    assert "ResourceLoader(" not in package_catalog
    for target_catalog_symbol in (
        "ResourceCatalogSnapshot",
        "ResourceSourceSnapshot",
        "ResourceCatalogEngine",
        "resource.catalog",
    ):
        assert target_catalog_symbol not in package_catalog


def test_rcp3_source_adapters_keep_authority_and_orchestration_boundaries() -> None:
    sources = _source_texts()
    package_source = sources[PACKAGE_SOURCE_PATH]
    embedded_source = sources[EMBEDDED_SOURCE_PATH]
    orchestration_inputs = sources[RESOURCE_INPUTS_PATH]

    for path, source in (
        (PACKAGE_SOURCE_PATH, package_source),
        (EMBEDDED_SOURCE_PATH, embedded_source),
    ):
        imports = _imported_modules(source, filename=path)
        assert not any(
            module.startswith("loushang.harness.capabilities") for module in imports
        )
        assert not any(
            token in module.lower()
            for module in imports
            for token in ("graph", "mcp", "registry")
        )

    assert "OwnerContributionAdmissionRecord" not in package_source
    assert "ResourceContributionSpec" not in package_source
    assert "PluginInstanceRevisionRef" not in package_source
    assert "file_identity(" in package_source
    assert ".open_file(" in package_source
    package_tree = ast.parse(package_source, filename=str(PACKAGE_SOURCE_PATH))
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"Path", "open"}
        for node in ast.walk(package_tree)
    )

    embedded_tree = ast.parse(embedded_source, filename=str(EMBEDDED_SOURCE_PATH))
    embedded_source_class = next(
        node
        for node in embedded_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EmbeddedOemResourceSource"
    )
    embedded_runtime_source = ast.get_source_segment(
        embedded_source,
        embedded_source_class,
    )
    assert embedded_runtime_source is not None
    assert "importlib_resources" not in embedded_runtime_source
    assert "Traversable" not in embedded_runtime_source

    assert "OwnerContributionAdmissionRecord" in orchestration_inputs
    assert "acquire_verified_package_resource_input" in orchestration_inputs


def test_rcp0_target_records_diagnostics_and_forbidden_routes_are_frozen() -> None:
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    plan = PLAN_PATH.read_text(encoding="utf-8")

    for record in (
        "ResourceIdentity",
        "ResourceSourceGenerationRef",
        "ResourceSourceSnapshot",
        "ResourceCandidateSummary",
        "ResourceBodyRead",
        "ResourceCatalogSnapshot",
        "ResourceLoadReceipt",
        "LoadedResource",
    ):
        assert f"`{record}`" in baseline
    assert _text_record_fields(plan, "### `ResourceSourceGenerationRef`") == (
        "source_id",
        "product_id",
        "generation",
        "source_policy_fingerprint",
        "producer (strict tagged union)",
    )
    assert _text_record_fields(plan, "### `ResourceCandidateSummary`") == (
        "identity",
        "canonical_name",
        "description",
        "media_type",
        "invocation_policy",
        "source_generation_ref",
        "source_class",
        "scope_id",
        "source_root_order",
        "content_origin (strict tagged union)",
        "opaque_locator",
        "discovery_fingerprint",
        "candidate_fingerprint",
        "expected_content_digest",
        "expected_content_length",
        "diagnostics",
    )
    diagnostic_codes = (
        "resource_source_discovery_failed",
        "resource_source_discovery_budget_exceeded",
        "resource_source_snapshot_invalid",
        "resource_catalog_proposal_invalid",
        "resource_body_read_failed",
        "resource_body_validation_failed",
        "resource_body_identity_mismatch",
        "resource_catalog_generation_stale",
        "resource_component_start_failed",
        "resource_component_dispose_failed",
        "resource_extension_snapshot_invalid",
    )
    taxonomy = plan.split("### Stable diagnostic taxonomy", maxsplit=1)[1]
    code_block = taxonomy.split("```text", maxsplit=1)[1].split("```", maxsplit=1)[0]
    assert tuple(code_block.split()) == diagnostic_codes
    assert len(set(diagnostic_codes)) == len(diagnostic_codes)
    for code in diagnostic_codes:
        assert code in plan
    for required in (
        "root_owned -> graph_constructing -> graph_owned -> retiring -> disposed",
        "a top-level `harness.skills` Capability or second Skill Catalog",
        "raw admitted `resource_item` candidates entering the engine",
        "Package Catalog choosing effective Resources",
        "Extension output merging effective Resources after final Catalog composition",
        "an owner component creating another Graph, registry, nested Plugin host, or\n  MCP route",
        "Root order does not break this strict conflict.",
        "The current post-discovery Extension hook path is a separately frozen legacy\nbehavior",
        "Initial Session bootstrap is a direct two-phase visible path",
        "pure classification before mutation",
    ):
        assert required in baseline
