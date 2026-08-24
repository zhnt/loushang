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
            Path("src/loushang/harness/resources/packages/catalog.py"),
            "_summarize_package_resources",
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

EXPECTED_RESOURCE_BUNDLE_SKILL_LOAD_SITES = {
    (
        Path("src/loushang/harness/commands/resources.py"),
        "list_resource_command_descriptors",
    ),
    (Path("src/loushang/harness/extensions/resources.py"), "_merge_contribution"),
    (
        Path("src/loushang/harness/resources/activation.py"),
        "ResourceActivation.active_skills",
    ),
    (Path("src/loushang/harness/resources/activation.py"), "apply_disabled_skills"),
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


def _literal_sites(sources: Mapping[Path, str], value: str) -> set[Path]:
    return {
        path
        for path, source in sources.items()
        if value in source
        and any(
            isinstance(node, ast.Constant) and node.value == value
            for node in ast.walk(ast.parse(source, filename=str(path)))
        )
    }


def test_rcp0_baseline_is_indexed_and_does_not_claim_runtime_implementation() -> None:
    baseline = BASELINE_PATH.read_text(encoding="utf-8")
    plan = PLAN_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "resource-catalog-rcp0-baseline.md" in plan
    assert readme.count("resource-catalog-rcp0-baseline.md") == 2
    assert "RCP0 baseline only" in baseline
    assert "No Catalog engine, source\n  component" in baseline
    assert "grants no new public API" in baseline


def test_rcp0_discovery_and_projection_caller_inventory_is_exact() -> None:
    sources = _source_texts()

    for callable_name, expected in EXPECTED_CALL_SITES.items():
        assert _call_sites(sources, callable_name) == expected


def test_rcp0_skill_fallback_projection_and_eager_body_sinks_are_exact() -> None:
    sources = _source_texts()
    resource_bundle_sources = {
        path: source for path, source in sources.items() if "ResourceBundle" in source
    }

    assert _literal_sites(sources, "get_skills") == {
        Path("src/loushang/harness/cli/skill_listing.py")
    }
    assert (
        _attribute_load_sites(resource_bundle_sources, "skills")
        == EXPECTED_RESOURCE_BUNDLE_SKILL_LOAD_SITES
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
        (extension_path, "_merge_contribution"),
    }
    for module in (
        "_loader_precedence.py",
        "_loader_resolution.py",
        "_loader_pipeline.py",
    ):
        assert (Path("src/loushang/harness/resources") / module).is_file()


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
    for code in (
        "resource_source_discovery_failed",
        "resource_source_discovery_budget_exceeded",
        "resource_source_snapshot_invalid",
        "resource_catalog_proposal_invalid",
        "resource_body_identity_mismatch",
        "resource_catalog_generation_stale",
        "resource_component_start_failed",
        "resource_component_dispose_failed",
        "resource_extension_snapshot_invalid",
    ):
        assert code in plan
    for required in (
        "root_owned -> graph_constructing -> graph_owned -> retiring -> disposed",
        "a top-level `harness.skills` Capability or second Skill Catalog",
        "raw admitted `resource_item` candidates entering the engine",
        "Package Catalog choosing effective Resources",
        "Extension output merging effective Resources after final Catalog composition",
        "an owner component creating another Graph, registry, nested Plugin host, or\n  MCP route",
    ):
        assert required in baseline
