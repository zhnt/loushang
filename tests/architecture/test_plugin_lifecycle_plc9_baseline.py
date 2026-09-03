from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

BASELINE = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9-baseline.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9-inventory.md"
)
INDEX = Path("docs/internals/architecture/harness/plugin/README.md")
PLAN = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-coding-pluginization-plan.md"
)

MANAGEMENT_SERVICE = Path("src/loushang/harness/plugin_management/service.py")
MANAGEMENT_OPERATIONS = Path("src/loushang/harness/plugin_management/operations.py")
MANAGEMENT_UPDATES = Path("src/loushang/harness/plugin_management/updates.py")
PACKAGE_LIFECYCLE = Path("src/loushang/harness/plugin_management/package_lifecycle.py")
CLI_TOGGLES = Path("src/loushang/harness/cli/resource_toggles.py")
CLI_LISTING = Path("src/loushang/harness/cli/plugin_listing.py")
CLI_PROFILE = Path("src/loushang/harness/cli/profile.py")
CLI_PARSER = Path("src/loushang/harness/cli/parser.py")
PACKAGE_CLI = Path("src/loushang/harness/cli/package_lifecycle.py")
HOST_OPERATIONS = Path("src/loushang/harness/cli/host_operations.py")
RPC_PACKAGES = Path("src/loushang/harness/host/rpc/commands/packages.py")
SESSION_ADAPTER = Path("src/loushang/harness/session/lifecycle_adapter.py")
SESSION_FACADE_OPTIONAL = Path("src/loushang/harness/session/facade_optional.py")
PACKAGE_SESSION = Path("src/loushang/harness/resources/packages/session.py")
PACKAGE_OPERATIONS = Path("src/loushang/harness/resources/packages/operations.py")
PACKAGE_SOURCE_RESOLVER = Path(
    "src/loushang/harness/resources/packages/source_resolver.py"
)
PLUGIN_MANAGER = Path("src/loushang/harness/resources/plugins/manager.py")
PLUGIN_AUTHORITY = Path("src/loushang/harness/resources/plugins/authority.py")
PLUGIN_RESOLVER = Path("src/loushang/harness/resources/plugins/resolver.py")
PLUGIN_SELECTION = Path("src/loushang/harness/resources/plugins/selection.py")
DECLARATIONS = Path("src/loushang/harness/resources/plugins/declarations.py")
PACKAGE_MATERIALIZER = Path("src/loushang/harness/resources/packages/materializer.py")
PLUGIN_REVISIONS = Path("src/loushang/harness/resources/plugins/revisions.py")
PLUGIN_DEPENDENCIES = Path("src/loushang/harness/resources/plugins/dependencies.py")
PROCESS_HOST = Path("src/loushang/harness/workspace/process/host.py")
PROCESS_HOSTING = Path("src/loushang/harness/tools/process_hosting.py")
SKILL_ACTIONS = Path("src/loushang/harness/tools/skill_actions.py")
SANDBOX_SERVICE = Path("src/loushang/harness/sandbox/service.py")
SANDBOX_PROCESS = Path("src/loushang/harness/sandbox/process.py")
SANDBOX_RUNTIME = Path("src/loushang/harness/sandbox/runtime.py")
AUTHOR_SDK = Path("src/loushang/plugin/__init__.py")
AUTHOR_SDK_ROOT = Path("src/loushang/plugin")
CONTINUITY_MUTATION = Path("src/loushang/harness/continuity/mutation.py")
CONTINUITY_PROVIDER = Path("src/loushang/harness/continuity/plugin_provider.py")
PLUGIN_CONTINUITY_MUTATION = Path(
    "src/loushang/harness/plugin_management/continuity_mutation.py"
)
SOURCE_ROOTS = (Path("src/loushang"),)

LEGACY_DISABLED_PLUGIN_FILES = {
    Path("src/loushang/coding/bootstrap.py"),
    Path("src/loushang/coding/cli/__main__.py"),
    Path("src/loushang/coding/continuity_bootstrap.py"),
    Path("src/loushang/harness/config/agent/_settings_codec.py"),
    Path("src/loushang/harness/config/agent/_settings_patch.py"),
    Path("src/loushang/harness/config/agent/manager.py"),
    Path("src/loushang/harness/config/agent/types.py"),
    Path("src/loushang/harness/resources/packages/catalog.py"),
    Path("src/loushang/harness/resources/packages/projection.py"),
    Path("src/loushang/harness/resources/packages/roots.py"),
    Path("src/loushang/harness/resources/packages/session.py"),
    Path("src/loushang/harness/resources/plugins/authority.py"),
    Path("src/loushang/harness/resources/plugins/manager.py"),
    Path("src/loushang/harness/session/bootstrap_activation.py"),
}
MANIFEST_ENABLED_FILES = {
    Path("src/loushang/coding/_base_plugin.py"),
    Path("src/loushang/coding/_capability_plugin_composition.py"),
    Path("src/loushang/coding/continuity_bootstrap.py"),
    Path("src/loushang/coding/plugin_management_cli.py"),
    Path("src/loushang/harness/resources/plugins/authority.py"),
    Path("src/loushang/harness/resources/plugins/resolver.py"),
    Path("src/loushang/harness/resources/plugins/selection.py"),
}
SOURCE_ENABLED_FILES = {
    Path("src/loushang/harness/resources/plugins/authority.py"),
    Path("src/loushang/harness/resources/plugins/resolver.py"),
    Path("src/loushang/harness/resources/plugins/selection.py"),
    Path("src/loushang/harness/resources/plugins/manifest.py"),
}
LEGACY_DISABLED_PLUGIN_SCOPE_COUNTS = Counter(
    {
        (
            Path("src/loushang/harness/config/agent/_settings_patch.py"),
            "AgentSettingsUpdate",
        ): 1,
        (
            Path("src/loushang/harness/config/agent/_settings_patch.py"),
            "build_settings_patch",
        ): 4,
        (
            Path("src/loushang/coding/continuity_bootstrap.py"),
            "_bootstrap_request_fingerprint",
        ): 2,
        (
            Path("src/loushang/coding/continuity_bootstrap.py"),
            "bind_coding_configured_continuity",
        ): 5,
        (Path("src/loushang/coding/continuity_bootstrap.py"), "_configured_sources"): 1,
        (
            Path("src/loushang/coding/cli/__main__.py"),
            "_run_list_packages.fallback_records",
        ): 2,
        (Path("src/loushang/harness/config/agent/types.py"), "ControlConfig"): 1,
        (
            Path("src/loushang/harness/resources/plugins/authority.py"),
            "PluginResolutionAuthority.__init__",
        ): 2,
        (
            Path("src/loushang/harness/session/bootstrap_activation.py"),
            "standard_agent_session_activation_plan",
        ): 2,
        (Path("src/loushang/coding/bootstrap.py"), "_create_agent_session"): 1,
        (
            Path("src/loushang/harness/resources/packages/roots.py"),
            "resolve_package_resource_roots",
        ): 3,
        (
            Path("src/loushang/harness/resources/packages/roots.py"),
            "configure_resource_loader_roots",
        ): 2,
        (
            Path("src/loushang/harness/resources/packages/roots.py"),
            "ResourceRootSettingsSnapshot.disabled_plugins",
        ): 1,
        (
            Path("src/loushang/harness/resources/packages/catalog.py"),
            "collect_package_catalog",
        ): 3,
        (
            Path("src/loushang/harness/resources/packages/catalog.py"),
            "PackageCatalogBuilder.collect",
        ): 3,
        (
            Path("src/loushang/harness/resources/packages/session.py"),
            "SessionPackageSettings",
        ): 1,
        (
            Path("src/loushang/harness/resources/packages/session.py"),
            "SessionPackageController.get_packages",
        ): 2,
        (Path("src/loushang/harness/config/agent/_settings_codec.py"), "<module>"): 2,
        (
            Path("src/loushang/harness/resources/plugins/manager.py"),
            "PluginManager.__init__",
        ): 2,
        (
            Path("src/loushang/harness/config/agent/manager.py"),
            "SettingsManager.update_settings",
        ): 9,
        (
            Path("src/loushang/harness/config/agent/manager.py"),
            "SettingsManager.apply_overrides",
        ): 6,
        (
            Path("src/loushang/harness/config/agent/manager.py"),
            "SettingsManager.get_disabled_plugins",
        ): 1,
        (
            Path("src/loushang/harness/config/agent/manager.py"),
            "SettingsManager._guard_legacy_plugin_changes",
        ): 1,
        (
            Path("src/loushang/harness/config/agent/manager.py"),
            "SettingsManager._mutate_legacy_plugin",
        ): 1,
        (
            Path("src/loushang/harness/config/agent/manager.py"),
            "SettingsManager._write_legacy_disabled_plugins",
        ): 1,
        (
            Path("src/loushang/harness/config/agent/manager.py"),
            "SettingsManager._publish_legacy_plugin_compatibility",
        ): 4,
        (
            Path("src/loushang/harness/config/agent/manager.py"),
            "_disabled_plugins_from_patch",
        ): 1,
        (
            Path("src/loushang/harness/resources/packages/projection.py"),
            "collect_projected_package_entries",
        ): 3,
    }
)
MANIFEST_ENABLED_SCOPE_COUNTS = Counter(
    {
        (
            Path("src/loushang/coding/_base_plugin.py"),
            "prepare_managed_coding_base_plugin_assembly",
        ): 1,
        (
            Path("src/loushang/coding/_capability_plugin_composition.py"),
            "_resolve_managed_capability_plugins",
        ): 1,
        (
            Path("src/loushang/coding/continuity_bootstrap.py"),
            "_reconcile_enabled_instances",
        ): 1,
        (
            Path("src/loushang/coding/plugin_management_cli.py"),
            "CodingConfiguredPluginSourceProjection.snapshot",
        ): 1,
        (PLUGIN_RESOLVER, "PluginResolver.project_package"): 1,
        (PLUGIN_SELECTION, "PluginSelectionResolver._resolve_preflight"): 1,
        (PLUGIN_AUTHORITY, "_assert_published_lineage"): 2,
    }
)
SOURCE_ENABLED_SCOPE_COUNTS = Counter(
    {
        (PLUGIN_RESOLVER, "PluginResolver.project_package"): 1,
        (
            Path("src/loushang/harness/resources/plugins/manifest.py"),
            "_resolved_source",
        ): 2,
        (PLUGIN_SELECTION, "PluginSelectionResolver._resolve_preflight"): 1,
        (PLUGIN_AUTHORITY, "PluginResolutionAuthority.project_package"): 1,
    }
)
PLUGIN_MANAGER_SCOPE_COUNTS = Counter({(PLUGIN_MANAGER, "PluginManager"): 1})
PACKAGE_ENTRYPOINT_ROOTS = (
    Path("src/loushang/coding/cli"),
    Path("src/loushang/harness/cli"),
    Path("src/loushang/harness/host/rpc/commands"),
    Path("src/loushang/harness/session"),
    Path("src/loushang/harness/resources/packages"),
)
PACKAGE_ENTRYPOINT_SYMBOLS = {
    "execute_package_lifecycle",
    "get_packages",
    "materialize_package",
    "install_package",
    "update_package",
    "update_packages",
    "check_package_updates",
    "remove_package",
    "uninstall_package",
    "uninstall_package_async",
    "materialize_remote_source_sync",
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _python_files_containing(value: str) -> set[Path]:
    return {
        path
        for root in SOURCE_ROOTS
        for path in root.rglob("*.py")
        if value in _source(path)
    }


class _QualifiedDefinitionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.definitions: set[str] = set()
        self.functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
        self.scopes: list[tuple[str, ast.AST]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified = ".".join((*self.scope, node.name))
        self.definitions.add(qualified)
        self.scopes.append((qualified, node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.definitions.add(".".join((*self.scope, target.id)))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.definitions.add(".".join((*self.scope, node.target.id)))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        qualified = ".".join((*self.scope, node.name))
        self.definitions.add(qualified)
        self.functions.append((qualified, node))
        self.scopes.append((qualified, node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _qualified_definitions(path: Path) -> set[str]:
    visitor = _QualifiedDefinitionVisitor()
    visitor.visit(ast.parse(_source(path), filename=str(path)))
    return visitor.definitions


def _call_sites_in_sources(
    sources: dict[Path, str], callable_name: str
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if callable_name not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        visitor = _QualifiedDefinitionVisitor()
        visitor.visit(tree)
        for qualified, function in visitor.functions:
            if any(
                isinstance(node, ast.Call)
                and (
                    isinstance(node.func, ast.Name)
                    and node.func.id == callable_name
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == callable_name
                )
                for node in ast.walk(function)
            ):
                sites.add((path, qualified))
        module_nodes = [
            statement
            for statement in tree.body
            if not isinstance(
                statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
        ]
        if any(
            isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id == callable_name
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == callable_name
            )
            for statement in module_nodes
            for node in ast.walk(statement)
        ):
            sites.add((path, "<module>"))
        for qualified, scope in visitor.scopes:
            if not isinstance(scope, ast.ClassDef):
                continue
            class_nodes = [
                statement
                for statement in scope.body
                if not isinstance(
                    statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
            ]
            if any(
                isinstance(node, ast.Call)
                and (
                    isinstance(node.func, ast.Name)
                    and node.func.id == callable_name
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == callable_name
                )
                for statement in class_nodes
                for node in ast.walk(statement)
            ):
                sites.add((path, qualified))
    return sites


def _call_sites(root: Path, callable_name: str) -> set[tuple[Path, str]]:
    return _call_sites_in_sources(
        {path: _source(path) for path in root.rglob("*.py")},
        callable_name,
    )


def _semantic_token_scope_counts(value: str) -> Counter[tuple[Path, str]]:
    """Count source facts by their narrowest qualified AST scope."""

    counts: Counter[tuple[Path, str]] = Counter()
    for path in _python_files_containing(value):
        tree = ast.parse(_source(path), filename=str(path))
        visitor = _QualifiedDefinitionVisitor()
        visitor.visit(tree)
        for node in ast.walk(tree):
            matches = False
            if "." in value and isinstance(node, ast.Attribute):
                matches = ast.unparse(node).endswith(value)
            elif "." not in value:
                matches = (
                    isinstance(node, ast.Name)
                    and node.id == value
                    or isinstance(
                        node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                    )
                    and node.name == value
                    or isinstance(node, ast.Attribute)
                    and node.attr == value
                    or isinstance(node, ast.arg)
                    and node.arg == value
                    or isinstance(node, ast.keyword)
                    and node.arg == value
                    or isinstance(node, ast.Constant)
                    and node.value == value
                )
            if not matches or not hasattr(node, "lineno"):
                continue
            enclosing = [
                (qualified, scope)
                for qualified, scope in visitor.scopes
                if scope.lineno <= node.lineno <= scope.end_lineno
            ]
            qualified = (
                max(
                    enclosing,
                    key=lambda item: (
                        item[0].count("."),
                        -int(item[1].end_lineno - item[1].lineno),
                    ),
                )[0]
                if enclosing
                else "<module>"
            )
            counts[(path, qualified)] += 1
    return counts


def _package_entrypoint_scope_counts() -> Counter[tuple[Path, str, str]]:
    counts: Counter[tuple[Path, str, str]] = Counter()
    for root in PACKAGE_ENTRYPOINT_ROOTS:
        for path in root.rglob("*.py"):
            source = _source(path)
            if not any(symbol in source for symbol in PACKAGE_ENTRYPOINT_SYMBOLS):
                continue
            tree = ast.parse(source, filename=str(path))
            visitor = _QualifiedDefinitionVisitor()
            visitor.visit(tree)
            for qualified, function in visitor.functions:
                if function.name in PACKAGE_ENTRYPOINT_SYMBOLS:
                    counts[(path, qualified, function.name)] += 1
                for node in ast.walk(function):
                    symbol: str | None = None
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name):
                            symbol = node.func.id
                        elif isinstance(node.func, ast.Attribute):
                            symbol = node.func.attr
                    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                        symbol = node.value
                    if symbol in PACKAGE_ENTRYPOINT_SYMBOLS:
                        counts[(path, qualified, symbol)] += 1
    return counts


def _is_desired_ledger_expression(node: ast.AST, aliases: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in {"desired", "_desired_state"}
        or isinstance(node, (ast.Name, ast.Attribute))
        and ast.unparse(node) in aliases
        or isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "PluginDesiredStateLedger"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "PluginDesiredStateLedger"
        )
    )


def _typed_desired_ledger_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    return {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
        if argument.annotation is not None
        and "PluginDesiredStateLedger" in ast.unparse(argument.annotation)
    }


def _propagate_desired_ledger_aliases(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: set[str],
) -> set[str]:
    aliases = set(aliases)
    assignments = [
        node
        for node in ast.walk(function)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    changed = True
    while changed:
        changed = False
        for assignment in assignments:
            value = assignment.value
            targets = (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else (assignment.target,)
            )
            target_names = {
                ast.unparse(target)
                for target in targets
                if isinstance(target, (ast.Name, ast.Attribute))
            }
            if (
                not target_names
                or value is None
                or not _is_desired_ledger_expression(value, aliases)
            ):
                continue
            if not target_names <= aliases:
                aliases.update(target_names)
                changed = True
    return aliases


def _desired_state_mutation_sites_in_sources(
    sources: dict[Path, str],
) -> set[tuple[Path, str, str]]:
    sites: set[tuple[Path, str, str]] = set()
    for path, source in sources.items():
        if "commit" not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        visitor = _QualifiedDefinitionVisitor()
        visitor.visit(tree)

        file_aliases: set[str] = set()
        module_assignments = [
            node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
        ]
        changed = True
        while changed:
            changed = False
            for assignment in module_assignments:
                targets = (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else (assignment.target,)
                )
                target_names = {
                    ast.unparse(target)
                    for target in targets
                    if isinstance(target, (ast.Name, ast.Attribute))
                }
                typed_ledger = (
                    isinstance(assignment, ast.AnnAssign)
                    and assignment.annotation is not None
                    and "PluginDesiredStateLedger" in ast.unparse(assignment.annotation)
                )
                value = assignment.value
                if not target_names or not (
                    typed_ledger
                    or value is not None
                    and _is_desired_ledger_expression(value, file_aliases)
                ):
                    continue
                if not target_names <= file_aliases:
                    file_aliases.update(target_names)
                    changed = True
        class_aliases: dict[str, set[str]] = {}
        for qualified, scope in visitor.scopes:
            if not isinstance(scope, ast.ClassDef):
                continue
            declared_aliases = {
                f"self.{ast.unparse(statement.target)}"
                for statement in scope.body
                if isinstance(statement, ast.AnnAssign)
                and statement.annotation is not None
                and "PluginDesiredStateLedger" in ast.unparse(statement.annotation)
                and isinstance(statement.target, ast.Name)
            }
            for statement in scope.body:
                if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    continue
                value = statement.value
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else (statement.target,)
                )
                if value is None or not _is_desired_ledger_expression(
                    value, declared_aliases
                ):
                    continue
                declared_aliases.update(
                    f"self.{ast.unparse(target)}"
                    for target in targets
                    if isinstance(target, ast.Name)
                )
            class_aliases[qualified] = declared_aliases
        for qualified, function in visitor.functions:
            owner = qualified.rpartition(".")[0]
            aliases = file_aliases | _typed_desired_ledger_names(function)
            aliases = _propagate_desired_ledger_aliases(function, aliases)
            if owner:
                class_aliases.setdefault(owner, set()).update(
                    alias for alias in aliases if alias.startswith("self.")
                )

        changed = True
        while changed:
            changed = False
            for qualified, function in visitor.functions:
                owner = qualified.rpartition(".")[0]
                aliases = (
                    file_aliases
                    | class_aliases.get(owner, set())
                    | _typed_desired_ledger_names(function)
                )
                propagated = _propagate_desired_ledger_aliases(function, aliases)
                owner_aliases = {
                    alias for alias in propagated if alias.startswith("self.")
                }
                if owner and not owner_aliases <= class_aliases.setdefault(
                    owner, set()
                ):
                    class_aliases[owner].update(owner_aliases)
                    changed = True

        for qualified, function in visitor.functions:
            owner = qualified.rpartition(".")[0]
            aliases = (
                file_aliases
                | class_aliases.get(owner, set())
                | _typed_desired_ledger_names(function)
            )
            aliases = _propagate_desired_ledger_aliases(function, aliases)
            for node in ast.walk(function):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"commit", "commit_update"}
                    and _is_desired_ledger_expression(node.func.value, aliases)
                ):
                    continue
                sites.add((path, qualified, node.func.attr))
    return sites


def _desired_state_mutation_sites() -> set[tuple[Path, str, str]]:
    return _desired_state_mutation_sites_in_sources(
        {path: _source(path) for root in SOURCE_ROOTS for path in root.rglob("*.py")}
    )


def _literal_members(path: Path, alias: str) -> tuple[str, ...]:
    tree = ast.parse(_source(path), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == alias
            for target in node.targets
        ):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Subscript)
            and isinstance(value.value, ast.Name)
            and value.value.id == "Literal"
        ):
            raise AssertionError(f"{alias} is not a Literal alias")
        elements = (
            value.slice.elts if isinstance(value.slice, ast.Tuple) else (value.slice,)
        )
        return tuple(
            element.value
            for element in elements
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
    raise AssertionError(f"missing {alias} in {path}")


def test_plc9_baseline_and_inventory_are_indexed_without_runtime_claims() -> None:
    baseline = _source(BASELINE)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    plan = _source(PLAN)

    assert index.count("(plugin-lifecycle-plc9-baseline.md)") == 1
    assert index.count("(plugin-lifecycle-plc9-inventory.md)") == 1
    assert plan.count("(plugin-lifecycle-plc9-baseline.md)") == 1
    assert plan.count("(plugin-lifecycle-plc9-inventory.md)") == 1
    assert "Runtime effect: none" in baseline
    assert "PLC9.0 authorizes no remote-service declaration or client" in baseline
    assert "grants no new runtime authority" in inventory
    assert "common management query snapshot/projector" in inventory
    assert "versioned `local_worker` execution-topology IR" in inventory


def test_plc9_inventory_names_existing_owner_and_peer_source_sites() -> None:
    inventory = _source(INVENTORY)
    inventoried_paths = (
        "src/loushang/harness/plugin_management/ledger.py",
        "src/loushang/harness/plugin_management/service.py",
        "src/loushang/harness/plugin_management/retirement.py",
        "src/loushang/harness/plugin_management/retirement_sets.py",
        "src/loushang/harness/plugin_management/instance_runtime.py",
        "src/loushang/harness/plugin_management/security_acceptance.py",
        "src/loushang/harness/plugin_management/package_lifecycle.py",
        "src/loushang/coding/_plugin_lifecycle.py",
        "src/loushang/harness/cli/resource_toggles.py",
        "src/loushang/harness/cli/plugin_listing.py",
        "src/loushang/harness/cli/profile.py",
        "src/loushang/harness/cli/parser.py",
        "src/loushang/harness/cli/package_lifecycle.py",
        "src/loushang/harness/cli/host_operations.py",
        "src/loushang/harness/host/rpc/commands/packages.py",
        "src/loushang/harness/session/lifecycle_adapter.py",
        "src/loushang/harness/session/facade_optional.py",
        "src/loushang/harness/resources/packages/session.py",
        "src/loushang/harness/resources/packages/operations.py",
        "src/loushang/harness/resources/packages/source_resolver.py",
        "src/loushang/harness/resources/plugins/manager.py",
        "src/loushang/harness/resources/plugins/authority.py",
        "src/loushang/harness/resources/plugins/resolver.py",
        "src/loushang/harness/resources/plugins/selection.py",
        "src/loushang/harness/resources/packages/materializer.py",
        "src/loushang/harness/resources/plugins/revisions.py",
        "src/loushang/harness/resources/plugins/dependencies.py",
        "src/loushang/harness/resources/plugins/declarations.py",
        "src/loushang/harness/workspace/process/host.py",
        "src/loushang/harness/tools/process_hosting.py",
        "src/loushang/harness/tools/skill_actions.py",
        "src/loushang/harness/sandbox/service.py",
        "src/loushang/harness/sandbox/process.py",
        "src/loushang/harness/sandbox/runtime.py",
        "src/loushang/plugin/__init__.py",
        "src/loushang/harness/continuity/mutation.py",
        "src/loushang/harness/continuity/plugin_provider.py",
        "src/loushang/harness/plugin_management/continuity_mutation.py",
        "src/loushang/harness/plugin_management/continuity_adapter.py",
    )

    for relative in inventoried_paths:
        assert Path(relative).is_file(), relative
        assert relative in inventory, relative

    qualified_sites = re.findall(
        r"`(src/loushang/[^`]+\.py)::([A-Za-z_][A-Za-z0-9_.]*)`",
        inventory,
    )
    assert qualified_sites
    for relative, symbol in qualified_sites:
        path = Path(relative)
        assert path.is_file(), relative
        assert symbol in _qualified_definitions(path), (relative, symbol)


def test_plc9_freezes_the_current_management_and_enablement_split() -> None:
    service = _source(MANAGEMENT_SERVICE)
    updates = _source(MANAGEMENT_UPDATES)
    toggles = _source(CLI_TOGGLES)
    listing = _source(CLI_LISTING)
    manager = _source(PLUGIN_MANAGER)
    authority = _source(PLUGIN_AUTHORITY)
    resolver = _source(PLUGIN_RESOLVER)
    selection = _source(PLUGIN_SELECTION)

    assert "class PluginManagementService:" in service
    assert (
        "Sole PLC2-2/PLC2-3 command authority over inert Plugin desired state"
        in service
    )
    assert _literal_members(MANAGEMENT_OPERATIONS, "PluginManagementAction") == (
        "install",
        "enable",
        "disable",
        "remove",
    )
    assert "class PluginManagementUpdateCommandV2" in updates
    assert "PluginManagementApplicationCommandV1(" in toggles
    assert '_call(settings_manager, "disable_plugin"' not in toggles
    assert '_call(settings_manager, "enable_plugin"' not in toggles
    assert "management.query(" in listing
    assert "PluginResolutionAuthority" not in listing
    assert "class PluginManager:" in manager
    assert "def enable_plugin(" in manager
    assert "def disable_plugin(" in manager
    assert "def remove_plugin_source(" in manager
    assert "package.manifest.name not in self._disabled_plugins" in authority
    assert "enabled=enabled and resolved_package.manifest.enabled" in resolver
    assert "not package.source.enabled or not package.manifest.enabled" in selection
    assert "The enablement migration is one-way" in _source(BASELINE)


def test_plc9_inventories_every_legacy_plugin_enablement_token_file() -> None:
    inventory = _source(INVENTORY)

    assert _python_files_containing("disabled_plugins") == LEGACY_DISABLED_PLUGIN_FILES
    assert _python_files_containing("manifest.enabled") == MANIFEST_ENABLED_FILES
    assert _python_files_containing("source.enabled") == SOURCE_ENABLED_FILES
    assert _semantic_token_scope_counts("disabled_plugins") == (
        LEGACY_DISABLED_PLUGIN_SCOPE_COUNTS
    )
    assert _semantic_token_scope_counts("manifest.enabled") == (
        MANIFEST_ENABLED_SCOPE_COUNTS
    )
    assert _semantic_token_scope_counts("source.enabled") == (
        SOURCE_ENABLED_SCOPE_COUNTS
    )
    assert _semantic_token_scope_counts("PluginManager") == PLUGIN_MANAGER_SCOPE_COUNTS
    for path in LEGACY_DISABLED_PLUGIN_FILES | SOURCE_ENABLED_FILES:
        assert str(path) in inventory, path


def test_plc9_keeps_one_desired_state_writer_and_composition_site() -> None:
    assert _desired_state_mutation_sites() == {
        (MANAGEMENT_SERVICE, "PluginManagementService._execute_unlocked", "commit"),
        (
            MANAGEMENT_SERVICE,
            "PluginManagementService._execute_update_unlocked",
            "commit_update",
        ),
    }
    assert _call_sites(Path("src/loushang"), "PluginDesiredStateLedger") == {
        (
            Path("src/loushang/coding/_plugin_lifecycle.py"),
            "build_coding_plugin_lifecycle",
        ),
        (
            Path("src/loushang/coding/_plugin_lifecycle.py"),
            "build_coding_plugin_management_application",
        ),
    }

    synthetic_path = Path("src/loushang/example/rogue_writer.py")
    synthetic_source = """
class RogueWriter:
    def __init__(self, ledger: PluginDesiredStateLedger) -> None:
        self.ledger = ledger

    def mutate(self) -> None:
        self.ledger.commit(object())

class TypedRogueWriter:
    ledger: PluginDesiredStateLedger

    def mutate(self) -> None:
        self.ledger.commit(object())

class StaticRogueWriter:
    ledger = PluginDesiredStateLedger(object())

    def mutate(self) -> None:
        self.ledger.commit(object())

file_ledger = PluginDesiredStateLedger(object())

def mutate_file_alias() -> None:
    file_ledger.commit(object())
"""
    assert _desired_state_mutation_sites_in_sources(
        {synthetic_path: synthetic_source}
    ) == {
        (synthetic_path, "RogueWriter.mutate", "commit"),
        (synthetic_path, "StaticRogueWriter.mutate", "commit"),
        (synthetic_path, "TypedRogueWriter.mutate", "commit"),
        (synthetic_path, "mutate_file_alias", "commit"),
    }
    assert _call_sites_in_sources(
        {synthetic_path: synthetic_source}, "PluginDesiredStateLedger"
    ) == {
        (synthetic_path, "<module>"),
        (synthetic_path, "StaticRogueWriter"),
    }


def test_plc9_inventories_existing_cli_rpc_session_and_startup_entries() -> None:
    profile = _source(CLI_PROFILE)
    parser = _source(CLI_PARSER)
    package_cli = _source(PACKAGE_CLI)
    host_operations = _source(HOST_OPERATIONS)
    rpc = _source(RPC_PACKAGES)
    session_adapter = _source(SESSION_ADAPTER)
    session_facade = _source(SESSION_FACADE_OPTIONAL)
    package_session = _source(PACKAGE_SESSION)
    resolver = _source(PACKAGE_SOURCE_RESOLVER)
    inventory = _source(INVENTORY)
    baseline = _source(BASELINE)

    assert '"--add-plugin-source", "--add-plugin"' in profile
    assert '"--remove-plugin-source", "--remove-plugin"' in profile
    assert "--add-plugin-source/--remove-plugin-source" in parser
    for command in (
        "materialize_package",
        "install_package",
        "update_package",
        "remove_package",
        "uninstall_package",
    ):
        assert command in package_cli
        assert command in rpc
        assert command in session_adapter
        assert command in session_facade
        assert command in package_session
    assert "run_package_lifecycle_operation(" in host_operations
    assert (
        'missing_source_action: MissingSourceAction | MissingSourceResolver = "install"'
        in resolver
    )
    assert "materialize_remote_source_sync(source)" in resolver
    assert "Source add/remove meaning" in baseline
    assert "route through the canonical Plugin" in baseline
    assert "lifecycle or refuse without mutation" in baseline
    for path in (
        CLI_PROFILE,
        CLI_PARSER,
        PACKAGE_CLI,
        HOST_OPERATIONS,
        RPC_PACKAGES,
        SESSION_ADAPTER,
        SESSION_FACADE_OPTIONAL,
        PACKAGE_SESSION,
        PACKAGE_SOURCE_RESOLVER,
    ):
        assert str(path) in inventory
        source = _source(path)
        assert "plugin_management.ledger" not in source
        assert "plugin_management.package_lifecycle" not in source


def test_plc9_freezes_named_package_lifecycle_sites_and_occurrences() -> None:
    expected: Counter[tuple[Path, str, str]] = Counter()

    def add_methods(
        path: Path,
        owner: str,
        symbols: set[str],
        *,
        count: int,
    ) -> None:
        for symbol in symbols:
            expected[(path, f"{owner}.{symbol}", symbol)] = count

    public_methods = {
        "get_packages",
        "materialize_package",
        "install_package",
        "update_package",
        "update_packages",
        "check_package_updates",
        "remove_package",
        "uninstall_package",
        "uninstall_package_async",
    }
    rpc_methods = public_methods - {"uninstall_package_async"}
    add_methods(
        RPC_PACKAGES,
        "_PackageCapabilities",
        rpc_methods,
        count=1,
    )
    add_methods(
        RPC_PACKAGES,
        "_DynamicPackageCapabilities",
        {"get_packages", "update_packages", "check_package_updates"},
        count=2,
    )
    add_methods(
        RPC_PACKAGES,
        "_DynamicPackageCapabilities",
        {
            "materialize_package",
            "install_package",
            "update_package",
            "remove_package",
            "uninstall_package",
        },
        count=1,
    )
    expected[(RPC_PACKAGES, "RpcPackageCommands.bindings", "get_packages")] = 1
    expected[(RPC_PACKAGES, "RpcPackageCommands.get_packages", "get_packages")] = 6

    add_methods(
        SESSION_FACADE_OPTIONAL,
        "SessionPackagePort",
        public_methods,
        count=1,
    )
    add_methods(
        SESSION_FACADE_OPTIONAL,
        "SessionFacadeOptionalOperations",
        public_methods,
        count=2,
    )
    adapter_methods = public_methods - {"uninstall_package_async"}
    add_methods(
        SESSION_ADAPTER,
        "SessionLifecycleOperationAdapter",
        adapter_methods,
        count=2,
    )
    expected[
        (
            SESSION_ADAPTER,
            "SessionLifecycleOperationAdapter.uninstall_package",
            "uninstall_package_async",
        )
    ] = 2
    add_methods(
        PACKAGE_SESSION,
        "SessionPackageController",
        public_methods,
        count=1,
    )
    expected[
        (
            PACKAGE_SESSION,
            "SessionPackageController.check_package_updates",
            "check_package_updates",
        )
    ] = 2

    cli_sites = {
        "check_package_updates": 3,
        "update_packages": 4,
        "materialize_package": 1,
        "update_package": 1,
        "remove_package": 1,
        "uninstall_package": 2,
        "install_package": 2,
    }
    for symbol, count in cli_sites.items():
        expected[(PACKAGE_CLI, "run_package_lifecycle", symbol)] = count
    expected[(PACKAGE_CLI, "_invoke_source_operation", "uninstall_package")] = 2
    expected[(PACKAGE_CLI, "_invoke_source_operation", "uninstall_package_async")] = 1
    expected[(PACKAGE_CLI, "_invoke_source_operation", "execute_package_lifecycle")] = 1
    for symbol in {
        "install_package",
        "materialize_package",
        "remove_package",
        "uninstall_package",
        "update_package",
    }:
        expected[(PACKAGE_CLI, "_lifecycle_action", symbol)] = 1
    for symbol in {
        "install_package",
        "materialize_package",
        "remove_package",
        "uninstall_package",
        "uninstall_package_async",
        "update_package",
    }:
        expected[(RPC_PACKAGES, "_DynamicPackageCapabilities._invoke_lifecycle", symbol)] = 1
    expected[
        (
            RPC_PACKAGES,
            "_DynamicPackageCapabilities._invoke_lifecycle",
            "execute_package_lifecycle",
        )
    ] = 1
    for path, owner, count in (
        (SESSION_FACADE_OPTIONAL, "SessionPackagePort", 1),
        (SESSION_FACADE_OPTIONAL, "SessionFacadeOptionalOperations", 2),
        (PACKAGE_SESSION, "SessionPackageController", 1),
    ):
        expected[(path, f"{owner}.execute_package_lifecycle", "execute_package_lifecycle")] = count
    agent_args = Path("src/loushang/harness/cli/agent_args.py")
    expected[(agent_args, "agent_cli_argument_values", "update_packages")] = 1
    expected[(agent_args, "agent_cli_argument_values", "check_package_updates")] = 1
    expected[
        (
            Path("src/loushang/coding/cli/__main__.py"),
            "_run_list_packages",
            "get_packages",
        )
    ] = 2
    expected[
        (
            PACKAGE_SOURCE_RESOLVER,
            "PackageSourceResolver._materialize_startup_source",
            "materialize_remote_source_sync",
        )
    ] = 2
    expected[
        (
            PACKAGE_MATERIALIZER,
            "PackageMaterializer.materialize_remote_source_sync",
            "materialize_remote_source_sync",
        )
    ] = 1
    expected[
        (
            PACKAGE_MATERIALIZER,
            "PackageMaterializer.check_package_updates",
            "check_package_updates",
        )
    ] = 1

    actual = _package_entrypoint_scope_counts()
    assert actual == expected
    inventory = _source(INVENTORY)
    for path, _, _ in actual:
        assert str(path) in inventory, path


def test_plc9_freezes_package_safety_gap_and_reusable_primitives() -> None:
    materializer = _source(PACKAGE_MATERIALIZER)
    operations = _source(PACKAGE_OPERATIONS)
    revisions = _source(PLUGIN_REVISIONS)
    dependencies = _source(PLUGIN_DEPENDENCIES)
    lifecycle = _source(PACKAGE_LIFECYCLE)
    baseline = _source(BASELINE)
    inventory = _source(INVENTORY)

    assert "class PackageSourcePolicy(Protocol):" in materializer
    assert "class PythonPackageInstallerBackend:" in materializer
    assert '"pip",\n                    "install",' in materializer
    assert (
        '"-m",\n                    "pip",\n                    "install",'
        in materializer
    )
    assert "--only-binary" not in materializer
    assert "def remove_remote_source(" in materializer
    assert "shutil.rmtree(record.target_path)" in materializer
    assert "def forget_remote_source(" in materializer
    assert "def forget_plugin_binding(" in materializer
    assert "self._plugin_binding_history = {" in materializer
    assert "class PackageOperationsRuntime:" in operations
    assert "def uninstall_sync(" in operations
    assert "self._require_materializer().remove_remote_source(source)" in operations
    assert "class PluginRevisionStore:" in revisions
    assert 'tempfile.mkdtemp(prefix=".quarantine-"' in revisions
    assert "quarantine.rename(published_root)" in revisions
    assert "class PluginPackageLifecycleLedger:" in lifecycle
    assert "def gc_candidates(" in lifecycle
    assert "def recheck_gc_candidate(" in lifecycle
    assert 'PLUGIN_DEPENDENCY_LOCK_FORMAT = "loushang.plugin-dependency-lock/v1"' in (
        dependencies
    )
    assert 'return {"name": self.name, "version": self.version}' in dependencies
    for state in (
        "retryable_failure",
        "terminal_failure",
        "retry_permitted",
        "safe_abandoned",
    ):
        assert state in lifecycle
    assert "does not satisfy this target" in baseline
    assert "verified wheel-only" in baseline
    assert "not a recursive digest graph" in baseline
    assert "Direct mutable removal" in inventory
    assert "Binding/history forgetting" in inventory


def test_plc9_does_not_pretend_worker_or_remote_topologies_exist() -> None:
    declarations = _source(DECLARATIONS)
    author_sdk = "\n".join(
        _source(path) for path in sorted(AUTHOR_SDK_ROOT.rglob("*.py"))
    )
    process_host = _source(PROCESS_HOST)
    sandbox = _source(SANDBOX_SERVICE)
    process_hosting = _source(PROCESS_HOSTING)
    sandbox_process = _source(SANDBOX_PROCESS)
    sandbox_runtime = _source(SANDBOX_RUNTIME)
    skill_actions = _source(SKILL_ACTIONS)
    inventory = _source(INVENTORY)

    assert _literal_members(DECLARATIONS, "PluginDeclarationSourceKind") == (
        "document",
        "in_process",
    )
    assert _literal_members(DECLARATIONS, "PluginContributionExecutionModel") == (
        "data_only",
        "in_process",
    )
    assert "local_worker" not in declarations
    assert "remote_service" not in declarations
    plugin_contract_sources = "\n".join(
        _source(path)
        for root in (
            AUTHOR_SDK_ROOT,
            Path("src/loushang/harness/resources/plugins"),
        )
        for path in sorted(root.rglob("*.py"))
    )
    assert "local_worker" not in plugin_contract_sources
    assert "remote_service" not in plugin_contract_sources
    for forbidden_export in (
        "PluginManagementService",
        "PluginPackageLifecycleLedger",
        "ProcessHost",
        "LocalSandboxService",
        "local_worker",
        "remote_service",
    ):
        assert forbidden_export not in author_sdk
    assert "class ProcessHost:" in process_host
    assert "containment_planner" in process_host
    assert "class LocalSandboxService:" in sandbox
    assert 'requirement not in {"best_effort", "required"}' in sandbox
    assert 'if self._requirement == "required"' in sandbox
    assert "class ScopeBoundProcessLauncher:" in process_hosting
    assert (
        "managed process requests require the owner-only start path" in process_hosting
    )
    assert "def _start_managed(" in process_hosting
    assert "def _verify_managed_start_authority(" in process_hosting
    assert "def _managed_process_launch_request(" in process_hosting
    assert "managed process start requires mandatory Approval" in process_hosting
    assert "managed process start requires required containment" in process_hosting
    assert "managed process containment is not Sandbox-owner-bound" in process_hosting
    assert "containment_planner=cast(ProcessContainmentPlanner, plan)" in (
        process_hosting
    )
    assert "class HostedProcessContainmentPlanner:" in sandbox_process
    assert 'if self._settings.requirement == "required"' in sandbox_process
    assert "_verify_managed_process_plan" in sandbox_process
    assert "def bind_process_launcher(" in sandbox_runtime
    assert "_bind_process_owner_launcher(" in sandbox_runtime
    assert "async def execute_managed_skill_action(" in skill_actions
    assert "request = _managed_process_launch_request(" in skill_actions
    assert "handle = await launcher._start_managed(" in skill_actions
    assert "launcher._verify_managed_start_authority()" in skill_actions
    for path in (PROCESS_HOSTING, SKILL_ACTIONS, SANDBOX_PROCESS, SANDBOX_RUNTIME):
        assert str(path) in inventory
    baseline = _source(BASELINE)
    assert "It is not a new" in baseline
    assert "`PluginDeclarationSourceKind`" in baseline
    assert "future narrow, owner-only `ManagedWorkerLaunchPort`" in baseline
    assert "forbidden for Worker admission" in baseline


def test_plc9_operation_boundaries_remain_explicit_in_design() -> None:
    baseline = _source(BASELINE)

    for operation in (
        "| install |",
        "| enable |",
        "| disable |",
        "| update |",
        "| remove |",
        "| retire |",
        "| GC |",
        "| delete private data |",
        "| repair |",
    ):
        assert operation in baseline
    assert "Removal is not deletion" in baseline
    assert "desired-state command commit" in baseline
    assert "Separate lifecycle operations" in baseline
    assert "Terminal cleanup failure is debt" in baseline
    assert "durable deletion receipt" in baseline
    assert "no surface emits an unqualified `disabled`, `removed`, or `completed`" in (
        baseline
    )
    assert "operation query/resume" in baseline
    assert "backup retention/expiry" in baseline
    assert "same-user child" in baseline
    assert "remote_service` is not a second arm hidden inside `local_worker" in baseline


def test_plc9_enablement_migration_has_durable_recovery_and_downgrade_rules() -> None:
    baseline = _source(BASELINE)
    inventory = _source(INVENTORY)

    for state in (
        "accepted -> desired_committed -> compatibility_window -> finalized",
        "already_authoritative",
        "absent` tombstone",
        "legacy input fingerprint",
        "runtime/version compatibility gate",
        "upgrade -> downgrade ->",
    ):
        assert state in baseline
    assert "durable migration receipt" in inventory
    assert "minimum-version/downgrade gate" in inventory


def test_plc9_keeps_continuity_destructive_commit_in_the_source_domain() -> None:
    product_authority = _source(PLUGIN_CONTINUITY_MUTATION)
    domain_mutation = _source(CONTINUITY_MUTATION)
    provider = _source(CONTINUITY_PROVIDER)
    inventory = _source(INVENTORY)
    baseline = _source(BASELINE)

    assert "class PluginContinuityDeletionAuthority:" in product_authority
    assert "candidate.commit(" not in product_authority
    source_commit = "receipt = await self._candidate.commit(self._plan)"
    settlement = "await self._authority.complete_delete(self._authorization, receipt)"
    assert source_commit in domain_mutation
    assert settlement in domain_mutation
    assert domain_mutation.index(source_commit) < domain_mutation.index(settlement)
    assert "async def _prepare_delete(" in provider
    assert "does not perform the source mutation" in inventory
    assert "source/data-domain candidate commit first" in inventory
    assert "move destructive execution" in baseline
    assert "into `plugin_management`" in baseline


def test_plc9_classifies_compatibility_candidates_before_plc9e() -> None:
    inventory = _source(INVENTORY)
    candidates = {
        Path(
            "src/loushang/harness/resources/packages/operations.py"
        ): "PackageOperationsRuntime.uninstall_sync",
        Path("src/loushang/harness/resources/plugins/manager.py"): "PluginManager",
        Path(
            "src/loushang/harness/resources/plugins/resolver.py"
        ): "PluginResolver.resolve_resources",
        Path(
            "src/loushang/harness/resources/plugins/safe_files.py"
        ): "compatibility import",
        Path(
            "src/loushang/harness/resources/plugins/import_realm.py"
        ): "PluginImportRealm",
        Path(
            "src/loushang/harness/extensions/loader.py"
        ): "_adapt_legacy_extension_object",
        Path(
            "src/loushang/coding/_plugin_lifecycle.py"
        ): "CodingPluginLifecycle.publish_session_owner_generations",
        Path(
            "src/loushang/harness/plugin_management/continuity_adapter.py"
        ): "PluginInstanceLedgerContinuityFamilyAuthority",
    }

    assert "## Compatibility Candidate Ledger" in inventory
    for path, symbol in candidates.items():
        assert path.is_file()
        assert str(path) in inventory
        assert symbol in inventory
    for disposition in (
        "migrate/delete",
        "decision-required",
        "retain",
        "narrow for non-Plugin",
    ):
        assert disposition in inventory
