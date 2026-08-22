from __future__ import annotations

import ast
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import get_args

import loushang.harness.capabilities as public_capabilities
import loushang.harness.resources.plugins as public_plugins
import loushang.harness.runtime as public_runtime
from loushang.harness.runtime import RuntimeCapabilityScope

ARCHITECTURE_PATH = Path(
    "docs/internals/architecture/harness/unified-plugin-architecture.md"
)
AUTHORING_PLAN_PATH = Path(
    "docs/internals/architecture/harness/plugin-authoring-primitives-delivery-plan.md"
)
LIFECYCLE_PLAN_PATH = Path(
    "docs/internals/architecture/harness/plugin-lifecycle-coding-pluginization-plan.md"
)
CAPABILITY_LIFECYCLE_PATH = Path(
    "docs/internals/architecture/harness/capability-dependency-and-mount-lifecycle.md"
)
README_PATH = Path("docs/internals/architecture/harness/README.md")
SOURCE_ROOT = Path("src/loushang")
EXPECTED_PLUGIN_JSON_STATIC_SITES = {
    Path("src/loushang/harness/resources/packages/manifest.py"),
    Path("src/loushang/harness/resources/plugins/manifest.py"),
}
PLUGIN_PACKAGE_BOUNDARY_ROOTS = (
    Path("src/loushang/harness/resources/plugins"),
    Path("src/loushang/harness/resources/packages"),
)
EXPECTED_PLUGIN_PACKAGE_BOUNDARY_SINK_OWNERS = {
    (
        Path("src/loushang/harness/resources/plugins/manifest.py"),
        "PluginManifestParser.parse",
    ): "plugin-manifest-parser",
    (
        Path("src/loushang/harness/resources/plugins/manifest.py"),
        "PluginManifestParser.revalidate",
    ): "plugin-manifest-parser",
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_digest_file",
    ): "verified-revision-publisher",
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_open_directory",
    ): "verified-revision-boundary",
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_open_regular_file",
    ): "verified-revision-boundary",
    (
        Path("src/loushang/harness/resources/packages/manifest.py"),
        "resolve_package_manifest",
    ): "package-manifest-parser",
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "PackageMaterializer.load_trusted_sources",
    ): "package-materializer",
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "PackageMaterializer._load_lockfile",
    ): "package-materializer",
    (
        Path("src/loushang/harness/resources/packages/catalog.py"),
        "load_package_catalog",
    ): "package-catalog",
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "_pypi_latest_version_result",
    ): "package-materializer",
    (
        Path("src/loushang/harness/resources/packages/mounts.py"),
        "PackageResourceMount.read_text",
    ): "package-resource-mount",
}
EXPECTED_GRAPH_PRIVATE_MUTATION_SITES = {
    (
        Path("src/loushang/harness/capabilities/graph_runtime.py"),
        "RuntimeCapabilityGraphRuntime.__init__",
    ),
    (
        Path("src/loushang/harness/capabilities/graph_binding.py"),
        "RuntimeCapabilityGraphBinder.bind",
    ),
    (
        Path("src/loushang/harness/capabilities/graph_binding.py"),
        "RuntimeCapabilityGraphBinder.dispose",
    ),
    (
        Path("src/loushang/harness/capabilities/graph_binding.py"),
        "_publish_registration_inventory",
    ),
}
EXPECTED_EXTENSION_DECLARATION_METHODS = {
    "on",
    "register_tool",
    "register_policy",
    "register_approval",
    "register_command",
    "register_flag",
    "register_shortcut",
    "register_message_renderer",
}
EXPECTED_LIVE_BINDING_SINK_INVENTORY = {
    (
        Path("src/loushang/coding/arch/tool_pack.py"),
        "register_coding_arch_tools",
        "register_tool",
    ),
    (
        Path("src/loushang/coding/bootstrap.py"),
        "_create_agent_session",
        "register_tool",
    ),
    (
        Path("src/loushang/coding/lsp/tool_pack.py"),
        "register_coding_lsp_tools",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/bootstrap.py"),
        "register_extension_tools",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/extensions/api.py"),
        "ExtensionContributionAPI._register_runtime_tool",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/api.py"),
        "ExtensionContributionAPI._register_runtime_tool",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/extensions/api.py"),
        "ExtensionContributionAPI.register_tool",
        "_register_runtime_tool",
    ),
    (
        Path("src/loushang/harness/extensions/loader.py"),
        "_adapt_legacy_extension_object",
        "on",
    ),
    (
        Path("src/loushang/harness/extensions/loader.py"),
        "_adapt_legacy_extension_object",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runner.py"),
        "ExtensionRunner._bind_declared_tools",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runner.py"),
        "ExtensionRunner._bindings_for_activation",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runner.py"),
        "ExtensionRunner._supports_staged_activation",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runtime_bindings.py"),
        "ExtensionRuntimeBindingFactory.build",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/extensions/runtime_bindings.py"),
        "ExtensionRuntimeBindingFactory.build",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/runtime/context.py"),
        "BoundProductRuntimeContext.register_tool",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/runtime/context.py"),
        "BoundProductRuntimeContext.register_tool",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/session/bootstrap_construction.py"),
        "_register_workspace_tool",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/session/tool_runtime.py"),
        "SessionToolRuntime.bind_runtime_tool",
        "bind_tool",
    ),
    (
        Path("src/loushang/harness/session/tool_runtime.py"),
        "SessionToolRuntime.register_runtime_tool",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/tools/agent_delegate.py"),
        "AgentDelegateToolPack.register",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/tools/multiagent.py"),
        "MultiAgentToolPack.register",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/tools/workspace/registry.py"),
        "WorkspaceToolRegistry._copy_contributions",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/tools/workspace/registry.py"),
        "WorkspaceToolRegistry.register_profile",
        "register_tool",
    ),
    (
        Path("src/loushang/harness/tools/workspace/registry.py"),
        "WorkspaceToolRegistry.register_tool",
        "register_tool",
    ),
}
EXPECTED_AUTHORITY_CLASS_SITES = {
    "RuntimeProfileResolver": Path(
        "src/loushang/harness/runtime/_profile_resolution.py"
    ),
    "RuntimeCapabilityGraphBinder": Path(
        "src/loushang/harness/capabilities/graph_binding.py"
    ),
    "RuntimeCapabilityGraphProjector": Path(
        "src/loushang/harness/capabilities/graph_projection.py"
    ),
}
EXPECTED_GRAPH_BINDER_CONSTRUCTION_SITES = {
    (
        Path("src/loushang/harness/session/agent_product.py"),
        "AgentProductSession.__init__",
    ),
}
FOUNDATION_PUBLIC_EXPORTS = {
    "capabilities": frozenset(
        {
            "CapabilityBundleProvider",
            "CapabilityBundleProviderBinding",
            "CapabilityDefinition",
            "CapabilityProviderContext",
            "CapabilityRequirement",
            "RuntimeCapabilityGraphBinder",
            "RuntimeCapabilityGraphPlan",
            "RuntimeCapabilityGraphPlanner",
        }
    ),
    "plugins": frozenset(
        {
            "PluginContributionCandidate",
            "PluginContributionIndex",
            "PluginContributionReservation",
            "PluginDeclaration",
            "PluginResolutionAuthority",
            "PluginSelectionResolver",
            "PublishedPluginPackage",
            "VerifiedRevisionHandle",
        }
    ),
    "runtime": frozenset(
        {
            "RegistrationLease",
            "RegistrationOwner",
            "RegistrationScope",
        }
    ),
}
PRE_SDK_PRIVATE_PLUGIN_SYMBOLS = frozenset(
    {
        "CapabilityComponentHost",
        "PluginContext",
        "PluginDeclarationBuilder",
        "PluginDefinition",
        "PluginDefinitionEvaluator",
        "PluginManagementService",
        "ProductCapabilityProviderResolver",
    }
)
INERT_PLUGIN_FORBIDDEN_IMPORT_PREFIXES = (
    "loushang.coding",
    "loushang.harness.capabilities.graph_binding",
    "loushang.harness.capabilities.graph_planning",
    "loushang.harness.capabilities.graph_runtime",
    "loushang.harness.capabilities.provider_binding",
    "loushang.harness.runtime.registration",
    "loushang.harness.session",
)
INERT_PLUGIN_SOURCE_ROOTS = (
    Path("src/loushang/harness/plugin_authoring"),
    Path("src/loushang/harness/resources/plugins"),
)


@cache
def _source_texts() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in SOURCE_ROOT.rglob("*.py")
    }


def _static_string_value(
    node: ast.AST,
    bindings: Mapping[str, str],
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string_value(node.left, bindings)
        right = _static_string_value(node.right, bindings)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        values = tuple(_static_string_value(value, bindings) for value in node.values)
        return None if any(value is None for value in values) else "".join(values)
    if isinstance(node, ast.FormattedValue):
        return _static_string_value(node.value, bindings)
    return None


def _static_string_bindings(tree: ast.Module) -> dict[str, str]:
    bindings: dict[str, str] = {}
    pending = [node for node in tree.body if isinstance(node, ast.Assign)]
    changed = True
    while changed:
        changed = False
        for assignment in pending:
            value = _static_string_value(assignment.value, bindings)
            if value is None:
                continue
            for target in assignment.targets:
                if isinstance(target, ast.Name) and bindings.get(target.id) != value:
                    bindings[target.id] = value
                    changed = True
    return bindings


def _static_string_sites(sources: Mapping[Path, str], value: str) -> set[Path]:
    sites: set[Path] = set()
    fragments = tuple(fragment for fragment in value.split(".") if fragment)
    for path, source in sources.items():
        if any(fragment not in source for fragment in fragments):
            continue
        tree = ast.parse(source, filename=str(path))
        bindings = _static_string_bindings(tree)
        if any(
            _static_string_value(node, bindings) == value for node in ast.walk(tree)
        ):
            sites.add(path)
    return sites


class _QualifiedFunctionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.functions: list[
            tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]
        ] = []

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
    """Collect executable nodes without crossing a nested code-unit boundary."""

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


def _import_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    json_modules = {"json"}
    json_decoders: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"json", "orjson"}:
                    json_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module in {"json", "orjson"}:
            for alias in node.names:
                if alias.name in {"load", "loads"}:
                    json_decoders.add(alias.asname or alias.name)
    return json_modules, json_decoders


def _is_plugin_package_boundary_sink(
    nodes: tuple[ast.AST, ...],
    *,
    json_modules: set[str],
    json_decoders: set[str],
) -> bool:
    calls = tuple(node for node in nodes if isinstance(node, ast.Call))
    reads_file = any(
        (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in {"read_text", "read_bytes", "open"}
        )
        or (
            isinstance(call.func, ast.Name)
            and call.func.id in {"open", "read_text", "read_bytes"}
        )
        for call in calls
    )
    parses_json = any(
        (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in json_modules
            and call.func.attr in {"load", "loads"}
        )
        or (
            isinstance(call.func, ast.Name)
            and call.func.id in json_decoders
        )
        for call in calls
    )
    return reads_file or parses_json


def _plugin_package_boundary_sink_sites(
    sources: Mapping[Path, str],
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if not any(path.is_relative_to(root) for root in PLUGIN_PACKAGE_BOUNDARY_ROOTS):
            continue
        tree = ast.parse(source, filename=str(path))
        json_modules, json_decoders = _import_aliases(tree)
        if _is_plugin_package_boundary_sink(
            _code_unit_nodes(tree.body),
            json_modules=json_modules,
            json_decoders=json_decoders,
        ):
            sites.add((path, "<module>"))
        for qualified, function in _qualified_functions(source, filename=path):
            if _is_plugin_package_boundary_sink(
                _code_unit_nodes(function.body),
                json_modules=json_modules,
                json_decoders=json_decoders,
            ):
                sites.add((path, qualified))
    return sites


def _receiver_looks_like_graph_state(
    node: ast.AST,
    *,
    allow_self: bool,
    receiver_aliases: set[str],
) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            lowered = child.id.lower()
            if child.id in receiver_aliases:
                return True
            if allow_self and lowered == "self":
                return True
            if lowered != "self" and (
                "graph" in lowered or "runtime" in lowered
            ):
                return True
        elif isinstance(child, ast.Attribute):
            lowered = child.attr.lower()
            if "graph" in lowered or lowered in {"runtime", "_runtime"}:
                return True
    return False


def _graph_receiver_aliases(
    nodes: tuple[ast.AST, ...],
    *,
    allow_self: bool,
) -> set[str]:
    aliases = {
        child.id
        for node in nodes
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
        and (
            "graph" in child.id.lower()
            or "runtime" in child.id.lower()
            or (allow_self and child.id == "self")
        )
    }
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not any(
                isinstance(child, ast.Name) and child.id in aliases
                for child in ast.walk(value)
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return aliases


def _contains_sensitive_attribute(
    node: ast.AST,
    attributes: frozenset[str],
    *,
    allow_self: bool,
    receiver_aliases: set[str],
) -> bool:
    return any(
        isinstance(child, ast.Attribute)
        and child.attr in attributes
        and _receiver_looks_like_graph_state(
            child.value,
            allow_self=allow_self,
            receiver_aliases=receiver_aliases,
        )
        for child in ast.walk(node)
    )


def _sensitive_container_aliases(
    nodes: tuple[ast.AST, ...],
    attributes: frozenset[str],
    *,
    allow_self: bool,
    receiver_aliases: set[str],
) -> set[str]:
    aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            aliases_sensitive = _contains_sensitive_attribute(
                value,
                attributes,
                allow_self=allow_self,
                receiver_aliases=receiver_aliases,
            ) or (isinstance(value, ast.Name) and value.id in aliases)
            if not aliases_sensitive:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return aliases


def _contains_sensitive_mutation_target(
    node: ast.AST,
    *,
    attributes: frozenset[str],
    aliases: set[str],
    allow_self: bool,
    receiver_aliases: set[str],
) -> bool:
    children = tuple(ast.walk(node))
    return any(
        (
            isinstance(child, ast.Attribute)
            and child.attr in attributes
            and _receiver_looks_like_graph_state(
                child.value,
                allow_self=allow_self,
                receiver_aliases=receiver_aliases,
            )
        )
        or (
            isinstance(child, ast.Subscript)
            and isinstance(child.slice, ast.Constant)
            and child.slice.value in attributes
            and _receiver_looks_like_graph_state(
                child.value,
                allow_self=allow_self,
                receiver_aliases=receiver_aliases,
            )
        )
        for child in children
    ) or (
        not isinstance(node, ast.Name)
        and any(isinstance(child, ast.Name) and child.id in aliases for child in children)
    )


def _function_mutates_private_graph_state(
    function: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef,
    attributes: frozenset[str],
    *,
    allow_self: bool,
) -> bool:
    mutation_methods = {
        "__setitem__",
        "append",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "remove",
        "setdefault",
        "update",
    }
    nodes = _code_unit_nodes(function.body)
    receiver_aliases = _graph_receiver_aliases(nodes, allow_self=allow_self)
    aliases = _sensitive_container_aliases(
        nodes,
        attributes,
        allow_self=allow_self,
        receiver_aliases=receiver_aliases,
    )
    for node in nodes:
        targets: tuple[ast.AST, ...] = ()
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        elif isinstance(node, ast.AugAssign):
            targets = (node.target,)
        elif isinstance(node, (ast.Delete,)):
            targets = tuple(node.targets)
        if any(
            _contains_sensitive_mutation_target(
                target,
                attributes=attributes,
                aliases=aliases,
                allow_self=allow_self,
                receiver_aliases=receiver_aliases,
            )
            for target in targets
        ):
            return True
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in {"setattr", "delattr"}:
            receiver = node.args[0] if node.args else None
            if (
                receiver is not None
                and _receiver_looks_like_graph_state(
                    receiver,
                    allow_self=allow_self,
                    receiver_aliases=receiver_aliases,
                )
                and any(
                    isinstance(argument, ast.Constant)
                    and argument.value in attributes
                    for argument in node.args[1:]
                )
            ):
                return True
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"__setattr__", "__delattr__"}
        ):
            receiver = (
                node.args[0]
                if isinstance(node.func.value, ast.Name)
                and node.func.value.id == "object"
                and node.args
                else node.func.value
            )
            if _receiver_looks_like_graph_state(
                receiver,
                allow_self=allow_self,
                receiver_aliases=receiver_aliases,
            ) and any(
                isinstance(argument, ast.Constant) and argument.value in attributes
                for argument in node.args
            ):
                return True
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in mutation_methods
            and (
                _contains_sensitive_attribute(
                    node.func.value,
                    attributes,
                    allow_self=allow_self,
                    receiver_aliases=receiver_aliases,
                )
                or (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id in aliases
                )
                or (
                    _receiver_looks_like_graph_state(
                        node.func.value,
                        allow_self=allow_self,
                        receiver_aliases=receiver_aliases,
                    )
                    and any(
                        isinstance(child, ast.Constant)
                        and child.value in attributes
                        for child in ast.walk(node)
                    )
                )
            )
        ):
            return True
    return False


def _graph_private_mutation_sites(
    sources: Mapping[Path, str],
) -> set[tuple[Path, str]]:
    attributes = frozenset(
        {"_generation", "_nodes", "_snapshot", "_registration_inventory"}
    )
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if not path.is_relative_to(SOURCE_ROOT):
            continue
        if not any(attribute in source for attribute in attributes):
            continue
        allow_self = "harness/capabilities/graph_" in path.as_posix()
        tree = ast.parse(source, filename=str(path))
        if _function_mutates_private_graph_state(
            tree,
            attributes,
            allow_self=allow_self,
        ):
            sites.add((path, "<module>"))
        for qualified, function in _qualified_functions(source, filename=path):
            if _function_mutates_private_graph_state(
                function,
                attributes,
                allow_self=allow_self,
            ):
                sites.add((path, qualified))
    return sites


def _class_method_names(source: str, class_name: str) -> set[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (child.name == "on" or child.name.startswith("register_"))
            }
    raise AssertionError(f"missing class: {class_name}")


def _live_sink_tokens(
    nodes: tuple[ast.AST, ...],
    tokens: frozenset[str],
) -> set[str]:
    found: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Attribute) and node.attr in tokens:
            found.add(node.attr)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "hasattr"}
        ):
            found.update(
                argument.value
                for argument in node.args[1:]
                if isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and argument.value in tokens
            )
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
            and node.slice.value in tokens
        ):
            found.add(node.slice.value)
    return found


def _live_binding_sink_inventory(
    sources: Mapping[Path, str],
) -> set[tuple[Path, str, str]]:
    tokens = frozenset(
        {
            *EXPECTED_EXTENSION_DECLARATION_METHODS,
            "_register_runtime_tool",
            "bind_approval",
            "bind_command",
            "bind_event",
            "bind_flag",
            "bind_handler",
            "bind_message_renderer",
            "bind_policy",
            "bind_shortcut",
            "bind_tool",
        }
    )
    inventory: set[tuple[Path, str, str]] = set()
    for path, source in sources.items():
        if not path.is_relative_to(SOURCE_ROOT):
            continue
        if not any(token in source for token in tokens):
            continue
        tree = ast.parse(source, filename=str(path))
        for token in _live_sink_tokens(_code_unit_nodes(tree.body), tokens):
            inventory.add((path, "<module>", token))
        for qualified, function in _qualified_functions(source, filename=path):
            for token in _live_sink_tokens(
                _code_unit_nodes(function.body),
                tokens,
            ):
                inventory.add((path, qualified, token))
    return inventory


def _class_sites(
    sources: Mapping[Path, str], class_name: str
) -> tuple[Path, ...]:
    return tuple(
        path
        for path, source in sources.items()
        if f"class {class_name}" in source
        if any(
            isinstance(node, ast.ClassDef) and node.name == class_name
            for node in ast.walk(ast.parse(source, filename=str(path)))
        )
    )


def _call_sites(
    sources: Mapping[Path, str],
    callable_name: str,
) -> set[tuple[Path, str]]:
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if callable_name not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        module_nodes = _code_unit_nodes(tree.body)
        if _nodes_call_name(module_nodes, callable_name):
            sites.add((path, "<module>"))
        for qualified, function in _qualified_functions(source, filename=path):
            if _nodes_call_name(_code_unit_nodes(function.body), callable_name):
                sites.add((path, qualified))
    return sites


def _nodes_call_name(nodes: tuple[ast.AST, ...], callable_name: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == callable_name
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == callable_name
        )
        for parent in nodes
        for node in ast.walk(parent)
    )


def _imported_modules(source: str, *, filename: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source, filename=str(filename))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _executable_loading_sites(
    sources: Mapping[Path, str],
) -> set[tuple[Path, str]]:
    tokens = {
        "__import__",
        "exec_module",
        "import_module",
        "run_module",
        "run_path",
        "spec_from_file_location",
    }
    sites: set[tuple[Path, str]] = set()
    for path, source in sources.items():
        if not any(token in source for token in tokens):
            continue
        tree = ast.parse(source, filename=str(path))
        if _nodes_call_any_name(_code_unit_nodes(tree.body), tokens):
            sites.add((path, "<module>"))
        for qualified, function in _qualified_functions(source, filename=path):
            if _nodes_call_any_name(_code_unit_nodes(function.body), tokens):
                sites.add((path, qualified))
    return sites


def _nodes_call_any_name(nodes: tuple[ast.AST, ...], names: set[str]) -> bool:
    return any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id in names
            or isinstance(node.func, ast.Attribute)
            and node.func.attr in names
        )
        for parent in nodes
        for node in ast.walk(parent)
    )


def test_unified_plugin_architecture_document_is_indexed() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "unified-plugin-architecture.md" in readme
    assert "Every manifest format has one parser" in architecture
    assert "Plugin identity is not a Capability Graph node" in architecture
    assert "installed != enabled != preflight-approved != declared != requested" in (
        architecture
    )


def test_unified_plugin_architecture_defines_the_four_phase_pipeline() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    for phase in (
        "Resolve once",
        "Preflight, then declare once",
        "Bind once",
        "Project once",
    ):
        assert phase in architecture


def test_plugin_classification_is_multidimensional_and_non_authoritative() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    capability_lifecycle = CAPABILITY_LIFECYCLE_PATH.read_text(encoding="utf-8")

    assert "has no mutually exclusive top-level `pluginType`" in architecture
    assert "Product and OEM\nare selectors and provenance authorities" in architecture
    assert "do not carry a hierarchical\nnumeric type code or a capability bitmap" in (
        architecture
    )
    assert "never persisted as the canonical identity, fingerprint" in architecture
    assert "cannot\ncontain arbitrary Plugin contributions" in architecture
    assert "sibling `tool_pack` and `command_pack` contributions" in architecture
    assert "| Tool definition/contribution owner |" in architecture
    assert "sibling tool_pack binds model-visible definitions" in architecture
    assert "this Session visibility rule is not a cross-owner publication or" in (
        architecture
    )
    assert "Declaration source model is not contributed-runtime execution model" in (
        architecture
    )
    assert "No parity test may erase that\nprovenance distinction" in architecture
    assert "PluginContributionSemanticFingerprint" in architecture
    assert "never substitutes for\ndeclaration/candidate identity" in architecture
    assert "Independently selected model-visible Tool definitions" in (
        capability_lifecycle
    )
    assert "does not become a Graph node or a Capability-generation registration" in (
        capability_lifecycle
    )
    assert "Resource owner resolves\nResource identities and bytes only" in (
        capability_lifecycle
    )
    assert "Tool owner exclusively owns\n`tool_pack` admission" in capability_lifecycle


def test_plc1b_declaration_plan_and_pap_crosswalk_are_explicit() -> None:
    lifecycle_plan = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")
    authoring_plan = AUTHORING_PLAN_PATH.read_text(encoding="utf-8")

    for slice_name in (
        "PLC1B-1: Versioned Declaration Source Union",
        "PLC1B-2: Resource Item Declaration",
        "PLC1B-3: Tool And Command Consumer Declarations",
        "PLC1B-4: `coding.base` Shadow Declaration",
    ):
        assert slice_name in lifecycle_plan
    assert "no top-level Plugin type code or bitmap participates" in lifecycle_plan
    assert "runtime-only v2" in lifecycle_plan
    assert "PluginDeclarationDocument` envelope v1" in lifecycle_plan
    assert "`PluginDeclarationSourceGroup`" in lifecycle_plan
    assert "closes its proposed reservation group over every index entry" in (
        lifecycle_plan
    )
    assert "same declaration source cannot be split across groups" in lifecycle_plan
    assert "`document_decoded` and\n  `in_process_evaluated`" in lifecycle_plan
    assert "rejects in-process finalization as `execution_not_consumed`" in (
        lifecycle_plan
    )
    assert "mixed document/in-process fixtures prove exact partitioning" in (
        lifecycle_plan
    )
    assert "one aggregate abort and zero finalization" in lifecycle_plan
    assert "successful mixed evaluation/join/single-finalization is a PLC3 exit gate" in (
        lifecycle_plan
    )
    assert "candidate `decision_id` with strict source-group/evidence provenance" in (
        lifecycle_plan
    )
    assert "`ACTIVE -> FINALIZED|ABORTED|EXPIRED`" in lifecycle_plan
    assert "Transitive cycles are deferred to the existing Graph\n  Planner" in (
        lifecycle_plan
    )
    assert "## PAP/PLC Sequencing Crosswalk" in authoring_plan
    assert "PLC order wins" in authoring_plan
    assert "### PAP1B: Data-Only Declaration Source And Consumer Expansion" in (
        authoring_plan
    )
    assert "| PAP1B | PLC1B |" in authoring_plan
    assert "| PAP4 + PAP4R + PAP5 | PLC4 |" in authoring_plan
    assert "### PAP4R: Resource/Tool/Command Owner And Consumer-Root Bridge" in (
        authoring_plan
    )
    assert "ProductCapabilityConsumerRequirementSet" in authoring_plan
    assert "this slice is part of PLC3" in authoring_plan
    assert "after PAP1B/PLC1B and the PLC2 minimum lifecycle command core" in (
        authoring_plan
    )


def test_plc1b_versioned_bytes_and_delivery_order_are_frozen() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    lifecycle_plan = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")

    assert "`allow_nan=False`, `ensure_ascii=True`" in architecture
    assert "performs no Unicode normalization" in architecture
    assert "rejects unpaired\nsurrogates before hashing" in architecture
    assert '"documentVersion": 1' in architecture
    assert "strictly sorted by `(pluginId, contributionId)`" in architecture
    assert "different from the complete indexed source closure fails" in architecture
    assert "mutable-root `resolve(strict=True)` remains only a pre-publication" in (
        lifecycle_plan
    )
    assert architecture.index("### UPA4: LSP Vertical Slice") < architecture.index(
        "### UPA5: Base Coding Composition"
    )
    assert architecture.index("### UPA5: Base Coding Composition") < architecture.index(
        "### UPA6: Architecture Vertical Slice"
    )


def test_executable_declaration_is_gated_by_inert_preflight() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert architecture.index("Plugin Preflight Proposal") < architecture.index(
        "Plugin Definition"
    )
    assert (
        "Only a digest-bound package with a positive execution-preflight decision"
        in architecture
    )
    assert "A document reservation never fabricates or" in architecture
    assert "executable packages are never imported and\nnever launched" in architecture
    assert "PluginExecutionApprovalSubject" in architecture
    assert "ContributionActivationApprovalSubject" in architecture
    assert "PluginPreflightOutcome" in architecture
    assert "PluginPreflightProposal" in architecture
    assert "calls `preflight()` again" in architecture
    assert "there is no mutable proposal to resume" in architecture
    assert "A group alone owns exactly one `PluginDeclarationGate`" in architecture
    assert "no copied gate, subject, decision or nullable peer fields" in architecture
    assert "Reservation gate and completed declaration evidence are different" in (
        architecture
    )
    assert "A positive decision reference alone cannot become a candidate" in (
        architecture
    )
    assert "Non-accepted arms carry no accepted group,\nreservation, gate, active token" in (
        architecture
    )
    assert "atomically create one active token" in architecture
    assert "PluginExecutionApprovalSubject` v2" in architecture
    assert "unsupported_plugin_execution_approval_subject_version" in architecture
    assert "`subjectSchemaVersion: 2`" in architecture
    assert "unsupported_plugin_execution_decision_record_version" in architecture
    assert "ACTIVE -> FINALIZED" in architecture
    assert "ACTIVE -> ABORTED" in architecture
    assert "ACTIVE -> EXPIRED" in architecture
    assert "calls `finalize()` zero times" in architecture
    assert "Definition returns the analogous complete frozen declaration" in architecture
    assert "sequence for its exact group" in architecture
    assert "removes the current unconditional `decision_id`" in architecture
    assert "serialize no execution subject, decision or receipt field" in architecture
    assert "is an independent complete subject" in architecture
    assert "PluginApprovalDecisionRecord" in architecture
    assert "consume_execution_decision(subject, decision_id)" in architecture
    assert "Revocation linearizes against consumption" in architecture
    assert "normalized group security-configuration\n  fingerprint" in architecture
    assert "Security-relevant configuration includes" in architecture
    assert "factory execution, owner bind and external-service launch are\nauthorized only" in (
        architecture
    )


def test_top_level_capability_provider_selection_is_not_a_profile_slot() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "ProductCapabilityProviderResolver" in architecture
    assert "ProductCapabilityConsumerRequirementSet" in architecture
    assert "sole bridge into\n`ProductCapabilityProviderResolver`" in architecture
    assert "not a third\nTool-to-Provider locator" in architecture
    assert "does not collapse same-Capability entries" in architecture
    assert "optional-only" in architecture
    assert "entry never silently creates a root" in architecture
    assert "CapabilityProviderEligibilityGrant" in architecture
    assert "CapabilityProviderAdmissionRecord" in architecture
    assert "CapabilityProviderBindingSpec" in architecture
    assert "one owner-admitted `CapabilityBundleProvider` metadata value" in architecture
    assert "CapabilityProviderCandidateFingerprint" in architecture
    assert "deterministically selects the complete transitive" in architecture
    assert "ProductCompositionCompiler" in architecture
    assert "never supplied as an external `source=\"product\"` layer" in architecture
    assert "A top-level Capability ID such\nas `coding.lsp` is never used" in architecture
    assert "Runtime Profile candidate for coding.lsp" not in architecture
    assert "Top-level Provider facts remain\nseparate data" in architecture
    assert "never carries a\n`ResolvedCapabilityProviderSet`" in architecture


def test_owner_admission_agent_event_and_disable_contracts_are_explicit() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "OwnerContributionAdmissionRecord" in architecture
    assert "never labels a contribution\n`admitted`" in architecture
    assert "`agent_definition`" in architecture
    assert "Product Agent Host" in architecture
    assert "EventDefinitionCatalog" in architecture
    assert "`durable_fact` after domain commit" in architecture
    assert "A durable interceptor/reducer/first-match declaration is invalid" in (
        architecture
    )
    assert "must atomically append its delivery\noutbox" in architecture
    assert "an unknown `required` fact fails closed" in architecture
    assert "security envelope and one-use\ndeclaration reservation" in architecture
    assert "`capability_component`" in architecture
    assert "CapabilityComponentDefinition" in architecture
    assert "Agent fields have one authority each" in architecture
    assert "calling a declaration-forming `register_*` after IR freeze" in architecture
    assert "performs no partial recompose and returns `restart_required`" in architecture


def test_revision_retention_and_python_import_realm_are_closed_for_v1() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "Plugin Instance Revisions alone use the execution-state machine" in (
        architecture
    )
    assert "Materialized Package Revision has a separate cache lifecycle" in (
        architecture
    )
    assert "write-\nahead lease handoff" in architecture
    assert "SessionPluginMembershipLease" in architecture
    assert "AgentPluginMembershipLease" in architecture
    assert "REVOKING" in architecture
    assert "PluginCleanupJournal" in architecture
    assert "changing its package\ndigest is Product-Host `restart_required`" in (
        architecture
    )
    assert "digest-qualified import realm" in architecture
    assert "process-wide import-realm gate" in architecture
    assert "`RESERVED -> LOADING -> LOADED`" in architecture
    assert "VerifiedRevisionHandle" in architecture
    assert "data-generation/schema" in architecture
    assert "`UPDATE_STAGED`, then `MIGRATING`" in architecture
    assert "PluginManagementService" in architecture
    assert "MCP is intentionally static-surface-only in v1" in architecture
    assert "ExecutionUseReservation" in architecture


def test_unified_plugin_architecture_preserves_existing_runtime_authorities() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    for authority in EXPECTED_AUTHORITY_CLASS_SITES:
        assert authority in architecture
    assert "There is no new Plugin Profile resolver" in architecture
    assert "not one global Plugin\ntransaction" in architecture
    assert "does not create a fifth effective clock" in architecture
    assert "aggregate retirement handles" in architecture
    assert "never becomes the Registration owner" in architecture


def test_current_plugin_manifest_name_sites_are_a_baseline_inventory() -> None:
    sources = _source_texts()

    assert _static_string_sites(sources, "plugin.json") == EXPECTED_PLUGIN_JSON_STATIC_SITES
    synthetic = {
        Path("third_parser.py"): (
            'PREFIX = "plugin."\n'
            'MANIFEST = f"{PREFIX}json"\n'
            "payload = (root / MANIFEST).read_text()\n"
        )
    }
    assert _static_string_sites(synthetic, "plugin.json") == {
        Path("third_parser.py")
    }


def test_plugin_manifest_has_one_parser_and_one_resolved_descriptor_authority() -> None:
    sources = _source_texts()

    assert _class_sites(sources, "PluginManifestParser") == (
        Path("src/loushang/harness/resources/plugins/manifest.py"),
    )
    assert _class_sites(sources, "ResolvedPluginPackage") == (
        Path("src/loushang/harness/resources/plugins/types.py"),
    )


def test_current_plugin_package_boundary_sinks_have_qualified_owners() -> None:
    sources = _source_texts()

    assert (
        _plugin_package_boundary_sink_sites(sources)
        == set(EXPECTED_PLUGIN_PACKAGE_BOUNDARY_SINK_OWNERS)
    )
    assert set(EXPECTED_PLUGIN_PACKAGE_BOUNDARY_SINK_OWNERS.values()) == {
        "package-catalog",
        "package-manifest-parser",
        "package-materializer",
        "package-resource-mount",
        "plugin-manifest-parser",
        "verified-revision-boundary",
        "verified-revision-publisher",
    }
    synthetic = {
        Path("src/loushang/harness/resources/plugins/read_helper.py"): (
            "def read_text(path):\n"
            "    with path.open() as stream:\n"
            "        return stream.read()\n"
        ),
        Path("src/loushang/harness/resources/plugins/indirect.py"): (
            "from json import loads as decode\n"
            "from names import PLUGIN_MANIFEST\n"
            "from .read_helper import read_text\n"
            "def parse(root):\n"
            "    return decode(read_text(root / PLUGIN_MANIFEST))\n"
        ),
        Path("src/loushang/harness/resources/packages/alias.py"): (
            "import orjson as codec\n"
            "def parse(path):\n"
            "    return codec.loads(path.read_bytes())\n"
        ),
        Path("src/loushang/harness/resources/packages/stream.py"): (
            "from json import load as decode\n"
            "def parse(path):\n"
            "    with path.open() as stream:\n"
            "        return decode(stream)\n"
        ),
        Path("src/loushang/harness/resources/packages/module_parse.py"): (
            "import json as codec\n"
            "payload = codec.loads(path.read_text())\n"
        ),
    }
    assert _plugin_package_boundary_sink_sites(synthetic) == {
        (
            Path("src/loushang/harness/resources/plugins/indirect.py"),
            "parse",
        ),
        (
            Path("src/loushang/harness/resources/plugins/read_helper.py"),
            "read_text",
        ),
        (
            Path("src/loushang/harness/resources/packages/alias.py"),
            "parse",
        ),
        (
            Path("src/loushang/harness/resources/packages/stream.py"),
            "parse",
        ),
        (
            Path("src/loushang/harness/resources/packages/module_parse.py"),
            "<module>",
        ),
    }


def test_current_graph_private_mutations_use_qualified_owner_allowlist() -> None:
    sources = _source_texts()

    assert _graph_private_mutation_sites(sources) == EXPECTED_GRAPH_PRIVATE_MUTATION_SITES
    synthetic = {
        Path("src/loushang/harness/capabilities/graph_alias.py"): (
            "def alias_write(graph, candidate):\n"
            "    graph._snapshot = candidate\n"
            "def receiver_alias_write(runtime, candidate):\n"
            "    target = runtime\n"
            "    target._snapshot = candidate\n"
            "def nested_write(self, nodes):\n"
            "    self._runtime._nodes['new'] = nodes\n"
            "def setattr_write(runtime, candidate):\n"
            "    setattr(runtime, '_snapshot', candidate)\n"
            "def dunder_write(runtime, candidate):\n"
            "    object.__setattr__(runtime, '_snapshot', candidate)\n"
            "def bound_dunder_write(runtime, candidate):\n"
            "    runtime.__setattr__('_snapshot', candidate)\n"
            "def container_write(runtime, nodes):\n"
            "    runtime._nodes.update(nodes)\n"
            "def container_alias_write(runtime, nodes):\n"
            "    registry = runtime._nodes\n"
            "    registry.update(nodes)\n"
        ),
        Path("src/loushang/harness/rogue_graph_write.py"): (
            "def outside_graph_module(runtime, candidate):\n"
            "    runtime._snapshot = candidate\n"
        ),
        Path("src/loushang/harness/rogue_graph_module.py"): (
            "graph_runtime._snapshot = candidate\n"
        )
    }
    assert _graph_private_mutation_sites(synthetic) == {
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "alias_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "nested_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "receiver_alias_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "setattr_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "dunder_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "container_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "bound_dunder_write",
        ),
        (
            Path("src/loushang/harness/capabilities/graph_alias.py"),
            "container_alias_write",
        ),
        (
            Path("src/loushang/harness/rogue_graph_write.py"),
            "outside_graph_module",
        ),
        (
            Path("src/loushang/harness/rogue_graph_module.py"),
            "<module>",
        ),
    }


def test_current_extension_declaration_and_live_binding_inventory_is_frozen() -> None:
    sources = _source_texts()
    api_path = Path("src/loushang/harness/extensions/api.py")

    assert _class_method_names(
        sources[api_path],
        "ExtensionContributionAPI",
    ) == EXPECTED_EXTENSION_DECLARATION_METHODS
    assert (
        _live_binding_sink_inventory(sources)
        == EXPECTED_LIVE_BINDING_SINK_INVENTORY
    )
    synthetic = {
        Path("src/loushang/harness/extensions/late.py"): (
            "def direct(bindings, tool):\n"
            "    bindings.bind_tool(tool)\n"
            "def reflected(bindings, tool):\n"
            "    getattr(bindings, 'bind_tool')(tool)\n"
            "def saved(bindings, tool):\n"
            "    binder = bindings.bind_tool\n"
            "    binder(tool)\n"
            "def new_kind(bindings, policy):\n"
            "    bindings.bind_policy(policy)\n"
        ),
        Path("src/loushang/harness/outside_extension.py"): (
            "def outside(bindings, policy):\n"
            "    bindings.bind_policy(policy)\n"
        ),
        Path("src/loushang/harness/module_binding.py"): (
            "bindings.bind_tool(tool)\n"
        ),
    }
    assert _live_binding_sink_inventory(synthetic) == {
        (
            Path("src/loushang/harness/extensions/late.py"),
            "direct",
            "bind_tool",
        ),
        (
            Path("src/loushang/harness/extensions/late.py"),
            "reflected",
            "bind_tool",
        ),
        (
            Path("src/loushang/harness/extensions/late.py"),
            "saved",
            "bind_tool",
        ),
        (
            Path("src/loushang/harness/extensions/late.py"),
            "new_kind",
            "bind_policy",
        ),
        (
            Path("src/loushang/harness/outside_extension.py"),
            "outside",
            "bind_policy",
        ),
        (
            Path("src/loushang/harness/module_binding.py"),
            "<module>",
            "bind_tool",
        ),
    }


def test_current_profile_graph_authority_classes_have_one_definition() -> None:
    sources = _source_texts()

    for class_name, expected_path in EXPECTED_AUTHORITY_CLASS_SITES.items():
        assert _class_sites(sources, class_name) == (expected_path,)
    assert (
        _call_sites(sources, "RuntimeCapabilityGraphBinder")
        == EXPECTED_GRAPH_BINDER_CONSTRUCTION_SITES
    )
    assert _class_sites(sources, "EffectivePluginRuntimeProjector") == ()
    assert _class_sites(sources, "PluginProfileResolver") == ()


def test_inert_plugin_layer_has_no_live_runtime_or_product_dependencies() -> None:
    plugin_sources = {
        path: source
        for path, source in _source_texts().items()
        if any(path.is_relative_to(root) for root in INERT_PLUGIN_SOURCE_ROOTS)
    }
    assert Path("src/loushang/harness/plugin_authoring/builder.py") in plugin_sources
    forbidden_imports = {
        (path, imported)
        for path, source in plugin_sources.items()
        for imported in _imported_modules(source, filename=path)
        if any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for prefix in INERT_PLUGIN_FORBIDDEN_IMPORT_PREFIXES
        )
    }

    assert forbidden_imports == set()
    assert _executable_loading_sites(plugin_sources) == set()


def test_plugin_foundation_public_exports_are_frozen_before_sdk() -> None:
    surfaces = {
        "capabilities": public_capabilities,
        "plugins": public_plugins,
        "runtime": public_runtime,
    }

    for surface_name, expected in FOUNDATION_PUBLIC_EXPORTS.items():
        surface = surfaces[surface_name]
        assert expected.issubset(set(surface.__all__))
        assert all(hasattr(surface, symbol) for symbol in expected)
    assert PRE_SDK_PRIVATE_PLUGIN_SYMBOLS.isdisjoint(set(public_plugins.__all__))
    assert all(
        not hasattr(public_plugins, symbol) for symbol in PRE_SDK_PRIVATE_PLUGIN_SYMBOLS
    )


def test_plugin_scope_contract_preserves_current_runtime_scope_vocabulary() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    expected = {"process", "tenant", "workspace", "session", "turn", "channel"}

    assert set(get_args(RuntimeCapabilityScope)) == expected
    for scope in expected:
        assert scope in architecture
    assert "Agent is a composition membership boundary" in architecture


def test_unified_plugin_architecture_preserves_exact_registration_ownership() -> None:
    registration_source = Path(
        "src/loushang/harness/runtime/registration.py"
    ).read_text(encoding="utf-8")
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "if lease.owner != self._owner:" in registration_source
    assert "one lease never belongs to two scopes" in architecture
    assert "Root Plugin scope capturing foreign leases" in architecture


def test_unified_plugin_architecture_keeps_complete_model_input_authority() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "complete Tool definitions and schemas" in architecture
    assert "fingerprints are supplementary provenance only" in architecture
    assert "never reopens the current\nPlugin package" in architecture


def test_unified_plugin_architecture_keeps_product_kernel_outside_plugins() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "Coding Product Kernel" in architecture
    assert "coding.base" in architecture
    assert "must remain\nusable when every optional Plugin is disabled" in architecture
    assert "mandatory system prompt" in architecture
