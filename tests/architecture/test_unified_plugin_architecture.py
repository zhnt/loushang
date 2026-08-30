from __future__ import annotations

import ast
import inspect
import json
from collections.abc import Mapping
from dataclasses import fields
from functools import cache
from hashlib import sha256
from pathlib import Path
from typing import get_args

import loushang.harness.capabilities as public_capabilities
import loushang.harness.resources.plugins as public_plugins
import loushang.harness.runtime as public_runtime
from loushang.harness.runtime import RuntimeCapabilityScope

ARCHITECTURE_PATH = Path("docs/internals/architecture/harness/plugin/architecture.md")
AUTHORING_PLAN_PATH = Path(
    "docs/internals/architecture/harness/plugin/plugin-authoring-primitives-delivery-plan.md"
)
LIFECYCLE_PLAN_PATH = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-coding-pluginization-plan.md"
)
PLC1B_CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/plugin-declaration-foundation-plc1b-contract.md"
)
PLC2_CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc2-contract.md"
)
PLC3_CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/plugin-execution-trust-plc3-contract.md"
)
PLC6_CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc6-contract.md"
)
PLC7_CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc7-contract.md"
)
CODING_CAPABILITY_COMPOSER_PATH = Path(
    "src/loushang/coding/_capability_plugin_composition.py"
)
CODING_CAPABILITY_SPECS_PATH = Path(
    "src/loushang/coding/_capability_plugin_specs.py"
)
CODING_BOOTSTRAP_PATH = Path("src/loushang/coding/bootstrap.py")
CODING_LSP_COMPATIBILITY_PATH = Path("src/loushang/coding/lsp/_plugin_opt_in.py")
PAP4_CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/plugin-capability-admission-pap4-contract.md"
)
RESOURCE_CATALOG_PLAN_PATH = Path(
    "docs/internals/architecture/harness/plugin/resource-catalog-pluginization-plan.md"
)
CAPABILITY_LIFECYCLE_PATH = Path(
    "docs/internals/architecture/harness/capability-dependency-and-mount-lifecycle.md"
)
README_PATH = Path("docs/internals/architecture/harness/plugin/README.md")
HARNESS_README_PATH = Path("docs/internals/architecture/harness/README.md")
SOURCE_ROOT = Path("src/loushang")
EXPECTED_PLUGIN_JSON_STATIC_SITES = {
    Path("src/loushang/harness/resources/packages/manifest.py"),
    Path("src/loushang/harness/resources/plugins/manifest.py"),
    Path("src/loushang/plugin/_package.py"),
    Path("src/loushang/plugin/_validation.py"),
}
PLUGIN_PACKAGE_BOUNDARY_ROOTS = (
    Path("src/loushang/harness/plugin_management"),
    Path("src/loushang/harness/resources/plugins"),
    Path("src/loushang/harness/resources/packages"),
    Path("src/loushang/harness/plugin_authoring"),
)
PLUGIN_DECLARATION_COORDINATOR_PATH = Path(
    "src/loushang/harness/plugin_authoring/coordinator.py"
)
RAW_JSON_DECODER_MODULES = {
    "json",
    "json.decoder",
    "msgspec.json",
    "orjson",
    "pydantic_core",
    "rapidjson",
    "simplejson",
    "ujson",
}
RAW_JSON_DECODER_FUNCTIONS = {"decode", "from_json", "load", "loads"}
EXPECTED_PLUGIN_PACKAGE_BOUNDARY_SINK_OWNERS = {
    (
        Path("src/loushang/harness/resources/plugins/python_symbols.py"),
        "load_verified_plugin_python_module",
    ): "verified-plugin-python-loader",
    (
        Path("src/loushang/harness/plugin_authoring/coordinator.py"),
        "PluginDeclarationCoordinator._read_and_decode_document",
    ): "plugin-declaration-coordinator",
    (
        Path("src/loushang/harness/resources/plugins/_strict_json.py"),
        "StrictPluginJsonCodec.decode_bytes",
    ): "plugin-strict-json-codec",
    (
        Path("src/loushang/harness/resources/plugins/distribution_evidence.py"),
        "_editable_project_root",
    ): "installed-python-distribution-evidence-resolver",
    (
        Path("src/loushang/harness/resources/plugins/safe_files.py"),
        "_capture_descriptor_relative",
    ): "contained-regular-file-capture",
    (
        Path("src/loushang/harness/resources/plugins/safe_files.py"),
        "_capture_portable",
    ): "contained-regular-file-capture",
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_digest_file",
    ): "verified-revision-publisher",
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_digest_file_portable",
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
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_open_regular_file_portable",
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
        "PackageMaterializer._load_lockfile_unlocked",
    ): "package-materializer",
    (
        Path("src/loushang/harness/resources/packages/catalog.py"),
        "load_package_catalog",
    ): "package-catalog",
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "_prompt_inventory",
    ): "package-resource-inventory",
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "_read_skill_ignore_patterns",
    ): "package-resource-inventory",
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "_skill_directory_inventory",
    ): "package-resource-inventory",
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "_theme_inventory",
    ): "package-resource-inventory",
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "_pypi_latest_version_result",
    ): "package-materializer",
    (
        Path("src/loushang/harness/resources/packages/mounts.py"),
        "PackageResourceMount.read_text",
    ): "package-resource-mount",
}
EXPECTED_PLUGIN_PACKAGE_BOUNDARY_SINK_CALL_COUNTS = {
    (
        Path("src/loushang/harness/resources/plugins/python_symbols.py"),
        "load_verified_plugin_python_module",
        "verified_open_file:revision_handle",
    ): 1,
    (
        Path("src/loushang/harness/plugin_authoring/coordinator.py"),
        "PluginDeclarationCoordinator._read_and_decode_document",
        "verified_open_file:handle",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/catalog.py"),
        "load_package_catalog",
        "json_decode",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/catalog.py"),
        "load_package_catalog",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "_prompt_inventory",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "_read_skill_ignore_patterns",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "_skill_directory_inventory",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "_theme_inventory",
        "json_decode",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/inventory.py"),
        "_theme_inventory",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/manifest.py"),
        "resolve_package_manifest",
        "json_decode",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/manifest.py"),
        "resolve_package_manifest",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "PackageMaterializer._load_lockfile_unlocked",
        "json_decode",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "PackageMaterializer._load_lockfile_unlocked",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "PackageMaterializer.load_trusted_sources",
        "json_decode",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "PackageMaterializer.load_trusted_sources",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/materializer.py"),
        "_pypi_latest_version_result",
        "json_decode",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/mounts.py"),
        "PackageResourceMount.read_text",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/packages/mounts.py"),
        "PackageResourceMount.read_text",
        "verified_open_file:handle",
    ): 1,
    (
        Path("src/loushang/harness/resources/plugins/safe_files.py"),
        "_capture_descriptor_relative",
        "path_read",
    ): 3,
    (
        Path("src/loushang/harness/resources/plugins/safe_files.py"),
        "_capture_portable",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/plugins/_strict_json.py"),
        "StrictPluginJsonCodec.decode_bytes",
        "json_decode",
    ): 1,
    (
        Path("src/loushang/harness/resources/plugins/distribution_evidence.py"),
        "_editable_project_root",
        "json_decode",
    ): 1,
    (
        Path("src/loushang/harness/resources/plugins/distribution_evidence.py"),
        "_editable_project_root",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_digest_file",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_digest_file_portable",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_open_directory",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_open_regular_file",
        "path_read",
    ): 1,
    (
        Path("src/loushang/harness/resources/plugins/revisions.py"),
        "_open_regular_file_portable",
        "path_read",
    ): 1,
}


def _contract_text_fields(document: str, *, heading: str) -> set[str]:
    section_parts = document.split(heading, maxsplit=1)
    assert len(section_parts) == 2, f"missing contract heading: {heading}"
    fence_parts = section_parts[1].split("```text", maxsplit=1)
    assert len(fence_parts) == 2, f"missing text record after: {heading}"
    body_parts = fence_parts[1].split("```", maxsplit=1)
    assert len(body_parts) == 2, f"unterminated text record after: {heading}"
    return {line.strip() for line in body_parts[0].splitlines() if line.strip()}


def _contract_json_blocks(document: str) -> tuple[str, ...]:
    return tuple(
        part.split("```", maxsplit=1)[0].strip()
        for part in document.split("```json")[1:]
    )


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
        Path("src/loushang/coding/bootstrap.py"),
        "_create_agent_session",
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
    "ProductCapabilityProviderResolver": Path(
        "src/loushang/harness/capabilities/provider_selection.py"
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
        "PluginContributionSemanticFingerprint",
        "PluginDeclarationBuilder",
        "PluginDefinition",
        "PluginDefinitionEvaluationError",
        "PluginDefinitionEvaluator",
        "PluginExecutionConsumptionReceiptV1",
        "PluginImportRealm",
        "PluginInProcessEvaluatedEvidence",
        "PluginManagementCommandV1",
        "PluginManagementOperationEventV1",
        "PluginManagementOperationResultV1",
        "PluginManagementService",
        "PluginManagementUpdateCommandV2",
        "PluginDesiredStateLedger",
        "PluginInstanceActivationV1",
        "PluginInstanceLeaseFamilyV1",
        "PluginInstanceRetirementCompletionV1",
        "PluginInstanceRevocationV1",
        "PluginInstanceRuntimeLedger",
        "PluginInstanceRuntimeSnapshotV1",
        "PluginCleanupTaskV1",
        "PluginPackageGcCandidateV1",
        "PluginPackageLifecycleLedger",
        "PluginPackagePinV1",
        "PluginPackageRecoveryBarrierV1",
        "PluginRetirementIntentLedger",
        "PluginRetirementIntentV1",
        "PluginOwnerRetirementOutcomeV1",
        "PluginOwnerRetirementPlanV1",
        "PluginOwnerRetirementTargetV1",
        "PluginRetirementSetEventV1",
        "PluginRetirementSetLedger",
        "PluginRetirementSetSnapshotV1",
        "ProductCapabilityProviderResolver",
        "compile_plugin_contribution_semantic_fingerprint",
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
    Path("src/loushang/harness/plugin_management"),
    Path("src/loushang/harness/plugin_authoring"),
    Path("src/loushang/harness/resources/plugins"),
)


@cache
def _source_texts() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8") for path in SOURCE_ROOT.rglob("*.py")
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
                if alias.name in RAW_JSON_DECODER_MODULES:
                    json_modules.add(alias.asname or alias.name)
        elif (
            isinstance(node, ast.ImportFrom) and node.module in RAW_JSON_DECODER_MODULES
        ):
            for alias in node.names:
                if alias.name in RAW_JSON_DECODER_FUNCTIONS:
                    json_decoders.add(alias.asname or alias.name)

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            is_decoder = (
                isinstance(value, ast.Name) and value.id in json_decoders
            ) or (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in json_modules
                and value.attr in RAW_JSON_DECODER_FUNCTIONS
            )
            if not is_decoder:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in json_decoders:
                    json_decoders.add(target.id)
                    changed = True
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
            and call.func.attr in {"read_text", "read_bytes", "open", "open_file"}
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
            and call.func.attr in RAW_JSON_DECODER_FUNCTIONS
        )
        or (isinstance(call.func, ast.Name) and call.func.id in json_decoders)
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


def _json_decoder_class_aliases(tree: ast.Module) -> set[str]:
    aliases = {"JSONDecoder"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"json", "json.decoder"}:
            for alias in node.names:
                if alias.name == "JSONDecoder":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _json_decoder_instance_aliases(
    tree: ast.Module,
    *,
    json_modules: set[str],
    json_decoder_classes: set[str],
) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        constructor = value.func
        is_decoder = (
            isinstance(constructor, ast.Name) and constructor.id in json_decoder_classes
        ) or (
            isinstance(constructor, ast.Attribute)
            and constructor.attr == "JSONDecoder"
            and isinstance(constructor.value, ast.Name)
            and constructor.value.id in json_modules
        )
        if is_decoder:
            aliases.update(
                target.id for target in targets if isinstance(target, ast.Name)
            )
    return aliases


def _plugin_boundary_call_operation(
    call: ast.Call,
    *,
    json_modules: set[str],
    json_decoders: set[str],
    json_decoder_classes: set[str],
    json_decoder_instances: set[str],
) -> str | None:
    if isinstance(call.func, ast.Attribute):
        if call.func.attr == "open_file":
            return f"verified_open_file:{ast.unparse(call.func.value)}"
        if call.func.attr in {"open", "read_bytes", "read_text"}:
            return "path_read"
        if (
            isinstance(call.func.value, ast.Name)
            and call.func.value.id in json_modules
            and call.func.attr in RAW_JSON_DECODER_FUNCTIONS
        ):
            return "json_decode"
        if (
            call.func.attr == "decode"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in json_decoder_instances
        ):
            return "json_decoder_decode"
        if call.func.attr == "decode" and isinstance(call.func.value, ast.Call):
            constructor = call.func.value.func
            if (
                isinstance(constructor, ast.Name)
                and constructor.id in json_decoder_classes
            ) or (
                isinstance(constructor, ast.Attribute)
                and constructor.attr == "JSONDecoder"
                and isinstance(constructor.value, ast.Name)
                and constructor.value.id in json_modules
            ):
                return "json_decoder_decode"
    if isinstance(call.func, ast.Name):
        if call.func.id in {"open", "read_bytes", "read_text"}:
            return "path_read"
        if call.func.id in json_decoders:
            return "json_decode"
    return None


def _plugin_package_boundary_sink_call_counts(
    sources: Mapping[Path, str],
) -> dict[tuple[Path, str, str], int]:
    inventory: dict[tuple[Path, str, str], int] = {}
    for path, source in sources.items():
        if not any(path.is_relative_to(root) for root in PLUGIN_PACKAGE_BOUNDARY_ROOTS):
            continue
        tree = ast.parse(source, filename=str(path))
        json_modules, json_decoders = _import_aliases(tree)
        json_decoder_classes = _json_decoder_class_aliases(tree)
        json_decoder_instances = _json_decoder_instance_aliases(
            tree,
            json_modules=json_modules,
            json_decoder_classes=json_decoder_classes,
        )
        units = [("<module>", _code_unit_nodes(tree.body))]
        units.extend(
            (qualified, _code_unit_nodes(function.body))
            for qualified, function in _qualified_functions(source, filename=path)
        )
        for qualified, nodes in units:
            for call in (node for node in nodes if isinstance(node, ast.Call)):
                operation = _plugin_boundary_call_operation(
                    call,
                    json_modules=json_modules,
                    json_decoders=json_decoders,
                    json_decoder_classes=json_decoder_classes,
                    json_decoder_instances=json_decoder_instances,
                )
                if operation is None:
                    continue
                key = (path, qualified, operation)
                inventory[key] = inventory.get(key, 0) + 1
    return inventory


def _annotation_terminal_name(annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value.rsplit(".", maxsplit=1)[-1]
    return None


def _document_ingress_boundary_violations(source: str) -> tuple[str, ...]:
    tree = ast.parse(source, filename=str(PLUGIN_DECLARATION_COORDINATOR_PATH))
    required_imports = {
        (
            "loushang.harness.resources.plugins.declarations",
            "PluginDeclarationDocumentCodec",
        ),
        (
            "loushang.harness.resources.plugins.revisions",
            "VerifiedRevisionHandle",
        ),
    }
    violations: list[str] = []
    if any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "*" for alias in node.names)
        for node in ast.walk(tree)
    ):
        violations.append("wildcard imports are forbidden at document byte ingress")
    import_bindings: list[tuple[str, str, str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            import_bindings.extend(
                (
                    alias.asname or alias.name,
                    node.module,
                    alias.name,
                    alias.asname,
                )
                for alias in node.names
            )
        elif isinstance(node, ast.Import):
            import_bindings.extend(
                (
                    alias.asname or alias.name.split(".", maxsplit=1)[0],
                    alias.name,
                    "",
                    alias.asname,
                )
                for alias in node.names
            )
    for module, symbol in sorted(required_imports):
        matches = tuple(binding for binding in import_bindings if binding[0] == symbol)
        if len(matches) != 1 or matches[0] != (symbol, module, symbol, None):
            violations.append(f"one unshadowed {module}.{symbol} import is required")
    if any(
        (
            isinstance(node, ast.Import)
            and any(alias.name in RAW_JSON_DECODER_MODULES for alias in node.names)
        )
        or (
            isinstance(node, ast.ImportFrom) and node.module in RAW_JSON_DECODER_MODULES
        )
        for node in ast.walk(tree)
    ):
        violations.append("raw decoder imports are forbidden")

    protected_symbols = {symbol for _, symbol in required_imports}
    if any(
        (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id in protected_symbols
        )
        or (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name in protected_symbols
        )
        or (isinstance(node, ast.arg) and node.arg in protected_symbols)
        for node in ast.walk(tree)
    ):
        violations.append("required document-boundary imports may not be rebound")

    qualified_functions = _qualified_functions(
        source,
        filename=PLUGIN_DECLARATION_COORDINATOR_PATH,
    )

    functions = tuple(
        function
        for qualified, function in qualified_functions
        if qualified == "PluginDeclarationCoordinator._read_and_decode_document"
    )
    if len(functions) != 1:
        violations.append("expected exactly one private document byte-ingress method")
        return tuple(violations)

    function = functions[0]
    arguments = {argument.arg: argument for argument in function.args.args}
    handle = arguments.get("handle")
    if handle is None or _annotation_terminal_name(handle.annotation) != (
        "VerifiedRevisionHandle"
    ):
        violations.append("handle must be annotated VerifiedRevisionHandle")
    if "locator" not in arguments:
        violations.append("locator must be an explicit ingress argument")
    if any(
        fragment in argument.arg.lower()
        for argument in function.args.args
        for fragment in ("callback", "decoder", "reader")
    ):
        violations.append("reader/decoder callbacks are forbidden")
    statements = tuple(ast.unparse(statement) for statement in function.body)
    if statements != (
        "with handle.open_file(locator) as stream:\n    verified_bytes = stream.read()",
        "return PluginDeclarationDocumentCodec.decode_bytes(verified_bytes)",
    ):
        violations.append("document byte ingress must preserve the exact byte flow")

    operations: list[str] = []
    for call in (
        node for node in _code_unit_nodes(function.body) if isinstance(node, ast.Call)
    ):
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "open_file"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "handle"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "locator"
            and not call.keywords
        ):
            operations.append("handle.open_file")
        elif (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "read"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "stream"
            and not call.args
            and not call.keywords
        ):
            operations.append("stream.read")
        elif (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "decode_bytes"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "PluginDeclarationDocumentCodec"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "verified_bytes"
            and not call.keywords
        ):
            operations.append("PluginDeclarationDocumentCodec.decode_bytes")
        else:
            operations.append(f"forbidden:{ast.unparse(call.func)}")

    expected = {
        "handle.open_file": 1,
        "stream.read": 1,
        "PluginDeclarationDocumentCodec.decode_bytes": 1,
    }
    actual = {
        operation: operations.count(operation) for operation in sorted(set(operations))
    }
    if actual != expected:
        violations.append(f"unexpected document byte-ingress calls: {actual!r}")
    return tuple(violations)


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
            if lowered != "self" and ("graph" in lowered or "runtime" in lowered):
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
        and any(
            isinstance(child, ast.Name) and child.id in aliases for child in children
        )
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
                    isinstance(argument, ast.Constant) and argument.value in attributes
                    for argument in node.args[1:]
                )
            ):
                return True
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "__setattr__",
            "__delattr__",
        }:
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
                        isinstance(child, ast.Constant) and child.value in attributes
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


def _class_sites(sources: Mapping[Path, str], class_name: str) -> tuple[Path, ...]:
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
    harness_readme = HARNESS_README_PATH.read_text(encoding="utf-8")

    assert "[Plugin Architecture V2](architecture.md)" in readme
    assert "[Plugin Architecture Hub](plugin/README.md)" in harness_readme
    assert "one strict `plugin.json`" in architecture
    assert "A Plugin is an independently selectable activation identity" in architecture
    assert "Installed is not enabled; enabled is not admitted" in architecture
    assert "accepted by the owner under issue `#502`" in architecture
    assert "owner accepted under issue `#502`" in readme
    assert "ready for owner acceptance" not in architecture
    assert "ready for owner acceptance" not in readme


def test_unified_plugin_architecture_defines_the_owner_preserving_pipeline() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    phases = (
        "### Resolve and inspect",
        "### Preflight and declare",
        "### Admit and bind",
        "### Disable, revoke, update, and remove",
        "## Diagnostics And Model Visibility",
    )
    assert all(phase in architecture for phase in phases)
    assert [architecture.index(phase) for phase in phases] == sorted(
        architecture.index(phase) for phase in phases
    )


def test_plc7_contract_freezes_second_provider_without_a_peer_graph() -> None:
    contract = PLC7_CONTRACT_PATH.read_text(encoding="utf-8")
    contract_text = " ".join(contract.split())
    readme = README_PATH.read_text(encoding="utf-8")

    for invariant in (
        "one Coding Capability-Plugin composition",
        "coding.arch -> harness.workspace(read, list, search)",
        "only the `tool-runtime` facet",
        "No CLI/bootstrap caller may directly call `register_coding_arch_tools()`",
        "quota is checked before publication",
        "three-view re-review pass",
    ):
        assert invariant in contract_text
    assert "[PLC7 Second-Provider Contract](plugin-lifecycle-plc7-contract.md)" in (
        readme
    )


def test_plc7_uses_one_neutral_composer_and_has_no_direct_arch_publisher() -> None:
    composer = CODING_CAPABILITY_COMPOSER_PATH.read_text(encoding="utf-8")
    specs = CODING_CAPABILITY_SPECS_PATH.read_text(encoding="utf-8")
    bootstrap = CODING_BOOTSTRAP_PATH.read_text(encoding="utf-8")
    compatibility = CODING_LSP_COMPATIBILITY_PATH.read_text(encoding="utf-8")
    bootstrap_tree = ast.parse(bootstrap, filename=str(CODING_BOOTSTRAP_PATH))

    assert "CODING_LSP_CAPABILITY_DEFINITION" not in composer
    assert "CODING_ARCH_CAPABILITY_DEFINITION" not in composer
    assert "coding_lsp_" not in composer
    assert "CODING_LSP_CAPABILITY_DEFINITION" in specs
    assert "CODING_ARCH_CAPABILITY_DEFINITION" in specs
    assert "ordered_coding_capability_plugin_specs" in composer
    assert "prepare_coding_capability_plugin_composition" in bootstrap
    assert "prepare_coding_lsp_plugin_opt_in" not in bootstrap
    assert "_assembly_request" not in compatibility
    assert not any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "register_coding_arch_tools"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "register_coding_arch_tools"
        )
        for node in ast.walk(bootstrap_tree)
    )


def test_plugin_classification_is_multidimensional_and_non_authoritative() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    capability_lifecycle = CAPABILITY_LIFECYCLE_PATH.read_text(encoding="utf-8")

    for axis in (
        "| Artifact |",
        "| Plugin identity |",
        "| Contribution |",
        "| Capability |",
        "| Execution topology |",
        "| Trust and authority |",
        "| Lifetime |",
        "| Placement and scope |",
    ):
        assert axis in architecture
    assert "`resource`, `capability`, `worker`, and `remote` are not Plugin" in (
        architecture
    )
    assert "bind to an exact\ncontribution and executable use" in architecture
    assert "Human-readable names are labels, not joins" in architecture
    assert "The Plugin manager cannot invent\nmerge, precedence" in architecture
    assert "complete Capability Bundle remains one owner-admitted Provider" in (
        architecture
    )
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
    assert "aggregate abort and zero finalization;" in lifecycle_plan
    assert (
        "successful mixed evaluation/join/single-finalization is a PLC3 exit gate"
        in (lifecycle_plan)
    )
    assert "candidate `decision_id` with strict source-group/evidence provenance" in (
        lifecycle_plan
    )
    assert "`ACTIVE_OPEN -> FINALIZED|CLOSING_ABORT|CLOSING_EXPIRE`" in (lifecycle_plan)
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
    lifecycle_plan = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")
    contract = PLC1B_CONTRACT_PATH.read_text(encoding="utf-8")

    assert "allow_nan=False" in contract
    assert "ensure_ascii=True" in contract
    assert "no Unicode normalization" in contract
    assert "unpaired Unicode\nsurrogates" in contract
    assert "`documentVersion: 1`" in contract
    assert "strictly sorted by `(pluginId, contributionId)`" in contract
    assert "the complete indexed closure for that one document source" in contract
    assert "bytes must equal their canonical re-encoding" in contract
    assert "duplicate object keys" in contract
    assert "mutable-root `resolve(strict=True)` remains only a pre-publication" in (
        lifecycle_plan
    )
    assert lifecycle_plan.index(
        "### PLC5: `coding.lsp.default` Production Provider"
    ) < lifecycle_plan.index("### PLC6: `coding.base` Production Resource Plugin")
    assert lifecycle_plan.index(
        "### PLC6: `coding.base` Production Resource Plugin"
    ) < lifecycle_plan.index("### PLC7: `coding.arch.default` Second Provider")


def test_plc5_default_lsp_mount_keeps_product_and_graph_ownership() -> None:
    lifecycle_plan = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")
    lifecycle_plan_text = " ".join(lifecycle_plan.split())

    for required in (
        "`CodingLspPluginOptInRequest | None`",
        "not a caller-assembled Session composition",
        "same bounded 300-second construction window",
        "A failed Graph preparation rolls back Provider and Tool generations and never falls back",
        "`AgentSession` never calls `close()` on a Graph-owned LSP runtime",
        "Binder rollback/retirement remains its sole disposer",
        "stages invisible Tool registration leases",
        "neither widens the Component Host API prefixes",
        "not a boolean treated as authority",
        "an opt-in request is neither a declaration-execution decision",
        "Bootstrap neither constructs LSP Tool definitions nor owns their leases",
        "`CodingLspPluginConfigV1`",
        "No per-workspace package generation",
    ):
        assert required in lifecycle_plan_text


def test_plc5_co_distributed_dependency_evidence_keeps_one_lock_authority() -> None:
    lifecycle_plan = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")
    lifecycle_plan_text = " ".join(lifecycle_plan.split())

    for required in (
        "#### PLC5.1a: Co-Distributed Dependency Evidence",
        "Harness-owned `InstalledPythonDistributionEvidenceResolver`",
        "private Product-owned `CoDistributedPluginDependencyGrantResolver`",
        "exact `(pluginId, sourceIdentity)`",
        "`coding.lsp.default -> loushang` relationship",
        "Neither a manifest, declaration, user configuration nor Plugin code can add a grant",
        "`PackageMaterializer._plugin_dependency_lock()` remains the only assembler",
        "emits the existing `loushang.plugin-dependency-lock/v1` document",
        "not a Plugin type, Capability grant, execution decision, import result or lifecycle owner",
        "A plain source tree without matching installed metadata is not evidence",
        "does not execute `.pth` files",
        "This is a same-trust-domain private code boundary, not a public SDK",
        "The resolver enumerates every installed candidate with the normalized name",
        "Candidate paths are never unioned into one wider installation",
        "never use the legacy LSP route",
        "does not add arbitrary host-package dependencies",
    ):
        assert required in lifecycle_plan_text


def test_plc1b_contract_freezes_no_self_reference_and_exact_v2_records() -> None:
    contract = PLC1B_CONTRACT_PATH.read_text(encoding="utf-8")

    assert (
        "The descriptor fingerprint never includes package content digest" in contract
    )
    assert "prevents a declaration document from needing\nto contain a hash" in contract
    assert "verified package revision. It is the sole source-group key" not in contract
    assert "`PluginSymbolReference` v2" in contract
    assert (
        "Neither the payload nor either symbol\nreference contains `packageDigest`"
        in (contract)
    )
    assert "V2 removes the redundant v1 `configurationFingerprint`" in contract
    assert "required key; exact SymbolReference v2 object or JSON `null`" in contract
    assert "One private low-level `StrictPluginJsonCodec`" in contract
    assert "exact import/call edge, not by a decoder-name\nheuristic" in contract
    assert "accepts\nno reader or decoder callback and makes no other call" in contract
    assert "Candidate construction is private to Resolver finalization" in contract
    assert "Declaration fingerprint is a member of that Batch" in contract
    assert "only in resolved views" in AUTHORING_PLAN_PATH.read_text(encoding="utf-8")

    for exact_wire_key in (
        "`contributionExecutionModel`",
        "`declarationSource`",
        "`reservationFingerprint`",
        "`sourceDescriptorFingerprint`",
        "`sourceKind`",
        "`sourceVersion`",
    ):
        assert f"| {exact_wire_key} |" in contract
    assert "They are\nnot serialized as a second interchange format" in contract
    assert "no copied Gate, subject, decision, or evidence" in contract
    assert "exactly cover the union of every proposed\nsource reservation closure" in (
        contract
    )
    assert "There is no Plan-global configuration fingerprint" in contract
    assert "changing only group B\nconfiguration does not change group A's" in (
        contract
    )

    subject_fields = _contract_text_fields(
        contract,
        heading="### `PluginExecutionApprovalSubject` v2",
    )
    assert subject_fields == {
        "ambientHostAuthority",
        "allowedAuthorityCeiling",
        "configurationMapFingerprint",
        "dependencyLockDigest",
        "entrypoint",
        "instanceRevisionRef",
        "packageContentDigest",
        "packageSourceIdentity",
        "pluginId",
        "policyRevision",
        "productId",
        "requestedAuthorities",
        "reservationClosureFingerprint",
        "schemaVersion",
        "scopeId",
        "sourceDescriptorFingerprint",
        "sourceTrustClass",
        "sourceTrustPolicyRevision",
    }
    decision_fields = _contract_text_fields(
        contract,
        heading="### `PluginExecutionDecisionRecord` v2 selection view",
    )
    assert decision_fields == {
        "decisionId",
        "decisionRecordVersion",
        "disposition",
        "policyRevision",
        "subjectDigest",
        "subjectSchemaVersion",
    }
    evidence_fields = _contract_text_fields(
        contract,
        heading="### `PluginDeclarationEvidence` v1",
    )
    assert evidence_fields == {
        "declarationSetFingerprint",
        "documentBytesDigest",
        "documentSchemaVersion",
        "evidenceVersion",
        "kind",
        "packageContentDigest",
        "preflightUseId",
        "reservationClosureFingerprint",
        "sourceDescriptorFingerprint",
        "sourceGroupFingerprint",
        "sourceGroupId",
    }

    for domain in (
        "loushang.plugin-declaration-source-descriptor/v1",
        "loushang.plugin-contribution-index/v2",
        "loushang.plugin-contribution-reservation/v2",
        "loushang.plugin-reservation-closure/v1",
        "loushang.plugin-group-configuration/v1",
        "loushang.plugin-declaration/v2",
        "loushang.plugin-execution-approval-subject/v2",
        "loushang.plugin-declaration-source-group/v1",
        "loushang.plugin-declaration-source-group-use/v1",
        "loushang.plugin-declaration-set/v2",
        "loushang.plugin-declaration-evidence/v1",
        "loushang.plugin-contribution-candidate/v2",
    ):
        assert domain in contract
    golden_digests = (
        "aec4eb58e83e5b4ee53392eee1881c358f75ca6c3d202c56c348a657edac6595",
        "2fe5d856380b78228e5d3baeb5227598e19268f403c4765e12e99e2567381217",
        "c24ebbab018030bda115eee4257003ef8ac86423faa480fe158bce31fc0377b7",
        "cfa8e2bbeb73cc55c4e67149c4d6bc0b452b7d93c9d76bfa2bb610a3ebd330fb",
        "bab38106e94908a0e7385da2c5576aa3ce0898348a0521aec1c83d3d8732fb3c",
        "4f2924b72efe84918324a0b37a3c70921b6584a8c390d343bd702d9791e4e1b1",
    )
    for golden_digest in golden_digests:
        assert golden_digest in contract
    json_blocks = _contract_json_blocks(contract)
    assert (
        tuple(sha256(block.encode("utf-8")).hexdigest() for block in json_blocks)
        == golden_digests
    )
    records = tuple(json.loads(block) for block in json_blocks)
    executable_source = records[2]["source"]
    subject = records[3]["subject"]
    assert executable_source["kind"] == "in_process"
    assert subject["entrypoint"] == executable_source["entrypoint"]
    assert subject["sourceDescriptorFingerprint"] == golden_digests[2]
    assert subject["ambientHostAuthority"] is True
    candidate = records[4]
    assert candidate["declarationFingerprint"] == golden_digests[1]
    assert candidate["sourceGroupFingerprint"] == "6" * 64


def test_plc1b_contract_freezes_attempt_claim_and_forbidden_peer_semantics() -> None:
    contract = PLC1B_CONTRACT_PATH.read_text(encoding="utf-8")
    lifecycle_plan = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")

    assert "preflightUseId` plus `sourceGroupFingerprint" in contract
    assert "plugin_declaration_evidence_attempt_mismatch" in contract
    assert "PENDING -> CLAIMED -> COMPLETED | FAILED" in contract
    assert "ACTIVE_OPEN -> CLOSING_ABORT -> ABORTED" in contract
    assert "CAS ACTIVE_OPEN -> CLOSING_ABORT | CLOSING_EXPIRE" in contract
    assert "in_flight == 0" in contract
    assert "finalize CAS loser destroys its private staged candidates" in contract
    assert "help-completable and shielded from caller cancellation" in contract
    assert "if now >= expiresAt, CAS to CLOSING_EXPIRE and join/help close" in contract
    assert "closer never settles for worker" in contract
    assert "process-owner expiry task/reaper registered before" in contract
    assert "CANCELLED_BEFORE_START" in contract
    assert "PluginExecutionStartPermit" in contract
    assert "`hostEpoch` is only the process-local typed name for `hostBootId`" in (
        contract
    )
    assert "Any token from a prior host boot returns\n`preflight_expired`" in contract
    assert "ABORTED -> ACTIVE" not in contract
    assert "`PluginSelectionPlanV2` is the sole Product authority" in contract
    assert "`PluginEffectiveConfigurationSetV1`" in contract
    assert "`PluginExecutionDecisionLookupPort`" in contract
    assert "`PendingOnlyPluginExecutionDecisionLookup`" in contract
    assert "callers cannot supply a tuple or map of\ndecisions" in contract
    assert "strict duplicate-key decoding precedes Index extraction" in lifecycle_plan
    assert "typed codec diagnostics are\n  preserved" in lifecycle_plan
    assert "accepts no\nBuilder output or external executable declaration" in contract
    assert "zero executable declaration ingress" in lifecycle_plan
    assert "delete/private-scope the top-level subject builder" in lifecycle_plan
    assert "direct\n  `finalize()` and `rollback()` entry points" in lifecycle_plan

    diagnostics = _contract_text_fields(
        contract,
        heading="## Exact Version Diagnostics",
    )
    assert diagnostics == {
        "unsupported_plugin_contribution_index_version",
        "unsupported_capability_provider_declaration_payload_version",
        "unsupported_continuity_provider_declaration_payload_version",
        "unsupported_command_pack_declaration_payload_version",
        "unsupported_resource_item_declaration_payload_version",
        "unsupported_tool_pack_declaration_payload_version",
        "unsupported_plugin_declaration_document_version",
        "unsupported_plugin_declaration_evidence_version",
        "unsupported_plugin_declaration_ir_version",
        "unsupported_plugin_declaration_source_version",
        "unsupported_plugin_execution_approval_subject_version",
        "unsupported_plugin_execution_decision_record_version",
        "unsupported_plugin_symbol_reference_version",
    }
    non_version_diagnostics = _contract_text_fields(
        contract,
        heading="## Exact Non-Version Diagnostics",
    )
    assert non_version_diagnostics == {
        "duplicate_plugin_contribution_identity",
        "duplicate_plugin_declaration_identity",
        "invalid_plugin_effective_configuration",
        "plugin_contribution_index_unsorted",
        "plugin_declaration_closure_mismatch",
        "plugin_declaration_cross_field_mismatch",
        "plugin_declaration_document_too_large",
        "plugin_declaration_document_too_many_declarations",
        "plugin_declaration_document_unsorted",
        "plugin_declaration_duplicate_json_key",
        "plugin_declaration_evidence_attempt_mismatch",
        "plugin_declaration_exact_field_mismatch",
        "plugin_declaration_field_type_mismatch",
        "plugin_declaration_field_value_mismatch",
        "plugin_declaration_invalid_json",
        "plugin_declaration_invalid_json_constant",
        "plugin_declaration_invalid_utf8",
        "plugin_declaration_json_depth_exceeded",
        "plugin_declaration_noncanonical_bytes",
        "plugin_declaration_utf8_bom",
        "unsupported_plugin_contribution_execution_model",
        "unsupported_plugin_contribution_kind",
        "unsupported_plugin_declaration_evidence_kind",
        "unsupported_plugin_declaration_source_kind",
        "unsupported_resource_item_kind",
        "unsupported_resource_item_locator_kind",
    }
    assert (
        "The condition-to-code mapping is normative and exhaustive for PLC1B"
        in contract
    )
    condition_mapping = contract.split(
        "The condition-to-code mapping is normative and exhaustive for PLC1B",
        maxsplit=1,
    )[1].split("Decode priority is deterministic", maxsplit=1)[0]
    for diagnostic in non_version_diagnostics:
        assert f"`{diagnostic}`" in condition_mapping
    for condition_code_example in (
        "field-level sorted-unique list such as `requestedAuthorities` | "
        "`plugin_declaration_field_value_mismatch`",
        "canonical contained locator/symbol path",
        "Provider owner metadata versus Declaration owner/source",
        "`plugin_declaration_cross_field_mismatch`",
    ):
        assert condition_code_example in contract
    assert (
        "specialized kind,\nexecution-model, ordering, duplicate, closure, "
        "Evidence-attempt, and effective-\nconfiguration rows override" in contract
    )


def test_plugin_preflight_reads_decisions_only_through_the_approval_owner_port() -> (
    None
):
    signature = inspect.signature(public_plugins.PluginSelectionResolver.preflight)
    parameters = signature.parameters

    assert tuple(parameters) == (
        "self",
        "packages",
        "bindings",
        "plan",
        "decision_lookup",
    )
    assert "decisions" not in parameters
    assert signature.return_annotation == "PluginPreflightOutcome"
    assert hasattr(
        public_plugins.PendingOnlyPluginExecutionDecisionLookup,
        "lookup_execution_decision",
    )
    assert not hasattr(
        public_plugins.PendingOnlyPluginExecutionDecisionLookup(),
        "record_decision",
    )
    selection_tree = ast.parse(
        Path("src/loushang/harness/resources/plugins/selection.py").read_text(
            encoding="utf-8"
        )
    )
    resolver_class = next(
        node
        for node in selection_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PluginSelectionResolver"
    )
    preflight_method = next(
        node
        for node in resolver_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "preflight"
    )
    assert not any(isinstance(node, ast.Raise) for node in ast.walk(preflight_method))


def test_plugin_preflight_builds_a_resumeless_source_proposal_before_acceptance() -> (
    None
):
    assert tuple(public_plugins.PluginPreflightProposal.__dataclass_fields__) == (
        "plan",
        "source_proposals",
    )
    source_fields = tuple(
        public_plugins.PluginDeclarationSourceProposal.__dataclass_fields__
    )
    assert source_fields == (
        "package",
        "declaration_source",
        "source_descriptor_fingerprint",
        "reservation_closure",
        "effective_configuration_entries",
        "configuration_map_fingerprint",
        "trust_snapshot",
        "requested_authorities",
        "allowed_authority_ceiling",
        "source_disposition",
    )
    assert not {
        "preflight_use_id",
        "gate",
        "decision",
        "reservation",
        "terminal_handle",
    }.intersection(source_fields)
    assert set(get_args(public_plugins.PluginDeclarationSourceDisposition)) == {
        public_plugins.PluginDeclarationDataOnlyDisposition,
        public_plugins.PluginDeclarationExecutionSubjectDisposition,
    }
    selection_source = Path(
        "src/loushang/harness/resources/plugins/selection.py"
    ).read_text(encoding="utf-8")
    assert "proposal = PluginPreflightProposal(" in selection_source
    assert "source_proposals=_build_source_proposals(" in selection_source


def test_accepted_preflight_moves_gate_and_context_ownership_to_source_group() -> None:
    from loushang.harness.plugin_authoring.builder import PluginDeclarationBuilder

    assert tuple(public_plugins.AcceptedPluginPreflight.__dataclass_fields__) == (
        "preflight_use_id",
        "host_boot_id",
        "expires_at",
        "context",
        "source_groups",
        "_terminal_handle",
    )
    assert tuple(public_plugins.PluginDeclarationReservation.__dataclass_fields__) == (
        "package",
        "contribution",
        "source_group_id",
        "source_group_fingerprint",
    )
    assert set(get_args(public_plugins.PluginDeclarationGate)) == {
        public_plugins.PluginDeclarationDataOnlyGate,
        public_plugins.PluginDeclarationExecutionPreflightGate,
    }
    assert not hasattr(public_plugins, "PluginPreflight")
    builder_parameters = inspect.signature(PluginDeclarationBuilder.__init__).parameters
    assert tuple(builder_parameters) == ("self", "source_group")
    assert "reservations" not in builder_parameters


def test_coordinator_exclusively_owns_evidenced_terminal_finalization() -> None:
    assert tuple(public_plugins.PluginDocumentDecodedEvidence.__dataclass_fields__) == (
        "declaration_set_fingerprint",
        "document_bytes_digest",
        "document_schema_version",
        "evidence_version",
        "kind",
        "package_content_digest",
        "preflight_use_id",
        "reservation_closure_fingerprint",
        "source_descriptor_fingerprint",
        "source_group_fingerprint",
        "source_group_id",
    )
    assert tuple(public_plugins.PluginDeclarationBatch.__dataclass_fields__) == (
        "preflight_use_id",
        "source_group_id",
        "source_group_fingerprint",
        "declarations",
        "evidence",
    )
    assert tuple(public_plugins.PluginContributionCandidate.__dataclass_fields__) == (
        "package",
        "declaration",
        "evidence",
        "fingerprint",
    )
    assert all(
        record_type.__dataclass_params__.init is False
        for record_type in (
            public_plugins.PluginDocumentDecodedEvidence,
            public_plugins.PluginDeclarationBatch,
            public_plugins.PluginContributionCandidate,
        )
    )
    assert not hasattr(public_plugins.PluginSelectionResolver, "finalize")
    assert not hasattr(public_plugins.PluginSelectionResolver, "rollback")
    assert not hasattr(public_plugins, "build_execution_approval_subject")
    assert all(
        hasattr(public_plugins.PluginSelectionResolver, method_name)
        for method_name in (
            "_claim_group",
            "_settle_group",
            "_abort",
            "_finalize",
            "_expire_from_reaper",
        )
    )
    resolver_source = _source_texts()[
        Path("src/loushang/harness/resources/plugins/selection.py")
    ]
    assert "_consume_active" not in resolver_source
    assert "def build_execution_approval_subject(" not in resolver_source
    assert "def _build_execution_approval_subject(" in resolver_source
    assert "_PLUGIN_MAX_ACTIVE_ATTEMPTS = 1024" in resolver_source
    assert "_PLUGIN_MAX_TERMINAL_TOMBSTONES = 8192" in resolver_source
    assert "_PLUGIN_MAX_ATTEMPT_LIFETIME_SECONDS = 300.0" in resolver_source
    assert all(
        state in resolver_source
        for state in (
            '"active_open"',
            '"closing_abort"',
            '"closing_expire"',
            '"finalized"',
            '"aborted"',
            '"expired"',
        )
    )
    coordinator_source = _source_texts()[PLUGIN_DECLARATION_COORDINATOR_PATH]
    assert coordinator_source.count("._claim_group(") == 1
    assert coordinator_source.count("._settle_group(") == 2
    terminal_callers = {
        path
        for path, source in _source_texts().items()
        if "PluginSelectionResolver" in source
        and ("._finalize(" in source or "._abort(" in source)
    }
    assert terminal_callers == {PLUGIN_DECLARATION_COORDINATOR_PATH}


def test_declaration_host_is_the_single_production_composition_entry() -> None:
    from loushang.harness.plugin_authoring.host import (
        PluginDeclarationHost,
        PluginDeclarationHostResult,
    )

    parameters = inspect.signature(PluginDeclarationHost.resolve).parameters
    assert tuple(parameters) == (
        "self",
        "packages",
        "bindings",
        "plan",
        "decision_lookup",
    )
    assert set(get_args(PluginDeclarationHostResult)) == {
        public_plugins.PluginSelection,
        public_plugins.PluginPreflightPendingApprovalOutcome,
        public_plugins.PluginPreflightDeniedOutcome,
        public_plugins.PluginPreflightRejectedOutcome,
    }
    host_path = Path("src/loushang/harness/plugin_authoring/host.py")
    host_source = _source_texts()[host_path]
    assert host_source.count("self._resolver.preflight(") == 1
    assert host_source.count("self._coordinator.finalize(") == 1
    assert _call_sites(_source_texts(), "PluginSelectionResolver") == {
        (host_path, "PluginDeclarationHost.__init__"),
    }
    assert _call_sites(_source_texts(), "PluginDeclarationCoordinator") == {
        (host_path, "PluginDeclarationHost.__init__"),
    }
    assert not hasattr(public_plugins, "PluginDeclarationHost")
    contract = PLC1B_CONTRACT_PATH.read_text(encoding="utf-8")
    authoring_plan = AUTHORING_PLAN_PATH.read_text(encoding="utf-8")
    assert "exactly one production composition entry" in contract
    assert "returns the accepted token to\nProduct code" in contract
    assert "It never writes an Approval decision" in contract
    assert "-> PluginDeclarationHost.resolve()" in authoring_plan


def test_resource_item_is_one_inert_kind_with_six_owner_subtypes() -> None:
    from loushang.harness.plugin_authoring.resource_item import (
        ResourceItemDeclarationPayload,
        ResourceItemKind,
        ResourceItemLocatorKind,
    )
    from loushang.harness.resources.plugins.declarations import (
        PluginContributionKind,
    )

    assert {
        "capability_provider",
        "resource_item",
    }.issubset(get_args(PluginContributionKind))
    assert set(get_args(ResourceItemKind)) == {
        "asset",
        "method",
        "prompt",
        "skill",
        "source",
        "theme",
    }
    assert set(get_args(ResourceItemLocatorKind)) == {"directory", "file"}
    assert tuple(ResourceItemDeclarationPayload.__dataclass_fields__) == (
        "locator",
        "locator_kind",
        "media_type",
        "owner_namespace",
        "resource_kind",
        "schema_id",
        "schema_version",
        "payload_version",
    )
    assert not hasattr(public_plugins, "ResourceItemDeclarationPayload")
    resource_source = _source_texts()[
        Path("src/loushang/harness/plugin_authoring/resource_item.py")
    ]
    for forbidden in (
        "ResourceBundle",
        "RegistrationScope",
        "bind_tool",
        "bind_command",
        "RuntimeCapabilityGraphBinder",
        "ModelInput",
        "PluginDefinition",
    ):
        assert forbidden not in resource_source
    selection_source = _source_texts()[
        Path("src/loushang/harness/resources/plugins/selection.py")
    ]
    assert "ambient_host_authority=True" in selection_source
    contract = PLC1B_CONTRACT_PATH.read_text(encoding="utf-8")
    assert "### `resource_item` payload v1" in contract
    assert "no Resource subtype is a Plugin type" in contract
    assert '`contributionExecutionModel: "data_only"`' in contract
    assert "## PLC1B-2 Regression Gate" in contract


def test_tool_and_command_packs_share_one_inert_catalog_consumer_primitive() -> None:
    from loushang.harness.plugin_authoring.consumer_pack import (
        CommandPackDeclarationPayload,
        ToolPackDeclarationPayload,
    )
    from loushang.harness.resources.plugins.declarations import (
        PluginContributionKind,
    )

    assert set(get_args(PluginContributionKind)) == {
        "capability_provider",
        "command_pack",
        "continuity_provider",
        "resource_item",
        "tool_pack",
    }
    assert ToolPackDeclarationPayload.__bases__ == (
        CommandPackDeclarationPayload.__bases__
    )
    assert tuple(field.name for field in fields(ToolPackDeclarationPayload)) == (
        "catalog_id",
        "catalog_revision",
        "item_ids",
        "owner_namespace",
        "requirements",
        "payload_version",
    )
    assert (
        ToolPackDeclarationPayload._ITEM_FIELD,
        CommandPackDeclarationPayload._ITEM_FIELD,
    ) == ("tools", "commands")
    assert not hasattr(public_plugins, "ToolPackDeclarationPayload")
    assert not hasattr(public_plugins, "CommandPackDeclarationPayload")

    source_texts = _source_texts()
    consumer_source = source_texts[
        Path("src/loushang/harness/plugin_authoring/consumer_pack.py")
    ]
    requirement_source = source_texts[
        Path("src/loushang/harness/plugin_authoring/capability_requirement.py")
    ]
    provider_source = source_texts[
        Path("src/loushang/harness/plugin_authoring/capability_provider.py")
    ]
    builder_source = source_texts[
        Path("src/loushang/harness/plugin_authoring/builder.py")
    ]
    assert consumer_source.count("def from_dict(") == 1
    assert consumer_source.count("def from_candidate(") == 1
    assert consumer_source.count("def from_reserved_declaration(") == 1
    assert builder_source.count("def _add_catalog_consumer(") == 1
    assert "plugin_authoring.capability_provider" not in consumer_source
    assert requirement_source.count("def capability_requirement_from_dict(") == 1
    assert "plugin_authoring.capability_requirement" in consumer_source
    assert "plugin_authoring.capability_requirement" in provider_source
    for forbidden in (
        "ToolDefinition",
        "CommandDef",
        "RegistrationScope",
        "RuntimeCapabilityGraphPlanner",
        "PluginSymbolReference",
        "WorkspaceToolRegistry",
        "SessionFacade",
        "McpSurfaceGeneration",
    ):
        assert forbidden not in consumer_source

    contract = PLC1B_CONTRACT_PATH.read_text(encoding="utf-8")
    normalized_contract = " ".join(contract.split())
    assert "### Catalog Consumer payload v1" in contract
    assert "outer Declaration kind remains the only" in contract
    assert (
        "These requirement facets are the only Capability-use request"
        in normalized_contract
    )
    assert "## PLC1B-3 Regression Gate" in contract


def test_semantic_fingerprint_is_one_inert_compiler_owned_diagnostic() -> None:
    from loushang.harness.plugin_authoring.semantic_fingerprint import (
        PLUGIN_CONTRIBUTION_SEMANTIC_FINGERPRINT_VERSION,
        PluginContributionSemanticFingerprint,
        compile_plugin_contribution_semantic_fingerprint,
    )

    assert PLUGIN_CONTRIBUTION_SEMANTIC_FINGERPRINT_VERSION == 1
    assert tuple(
        field.name for field in fields(PluginContributionSemanticFingerprint)
    ) == ("digest", "canonical_bytes", "_record")
    assert tuple(
        inspect.signature(compile_plugin_contribution_semantic_fingerprint).parameters
    ) == ("declaration",)
    assert not hasattr(public_plugins, "PluginContributionSemanticFingerprint")
    assert not hasattr(
        public_plugins,
        "compile_plugin_contribution_semantic_fingerprint",
    )

    source_texts = _source_texts()
    semantic_path = Path(
        "src/loushang/harness/plugin_authoring/semantic_fingerprint.py"
    )
    semantic_source = source_texts[semantic_path]
    assert (
        semantic_source.count("def compile_plugin_contribution_semantic_fingerprint(")
        == 1
    )
    assert "StrictPluginJsonCodec.encode(record)" in semantic_source
    assert "sha256(canonical_bytes).hexdigest()" in semantic_source
    assert "unicodedata" not in semantic_source
    assert "import json" not in semantic_source
    for forbidden in (
        "RegistrationScope",
        "WorkspaceToolRegistry",
        "RuntimeCapabilityGraphPlanner",
        "RuntimeCapabilityGraphBinder",
        "SessionFacade",
        "ModelInput",
        "McpSurfaceGeneration",
    ):
        assert forbidden not in semantic_source
    for runtime_path in (
        Path("src/loushang/harness/plugin_authoring/coordinator.py"),
        Path("src/loushang/harness/plugin_authoring/host.py"),
        Path("src/loushang/harness/resources/plugins/selection.py"),
    ):
        assert "semantic_fingerprint" not in source_texts[runtime_path]

    fixture_root = Path("tests/harness/resources/plugins/fixtures/coding_base_shadow")
    assert {
        path.relative_to(fixture_root).as_posix()
        for path in fixture_root.rglob("*")
        if path.is_file()
    } == {
        "declarations/plugin.json",
        "plugin.json",
        "prompts/standard.md",
        "skills/standard/SKILL.md",
    }
    assert not (fixture_root / "definition.py").exists()
    declaration_bytes = (fixture_root / "declarations/plugin.json").read_bytes()
    assert not declaration_bytes.endswith(b"\n")

    contract = PLC1B_CONTRACT_PATH.read_text(encoding="utf-8")
    assert "## Contribution Semantic Fingerprint v1" in contract
    assert "The declaration compiler is its sole\nconstructor" in contract
    assert "<Declaration owner>.tool-pack" in contract
    assert "<Declaration owner>.command-pack" in contract
    assert "## PLC1B-4 Regression Gate" in contract


def test_executable_declaration_is_gated_by_inert_preflight() -> None:
    # Exact preflight wire/state details belong to the frozen incremental
    # contracts and delivery plan, not to the concise V2 architecture master.
    architecture = "\n".join(
        (
            PLC1B_CONTRACT_PATH.read_text(encoding="utf-8"),
            PLC3_CONTRACT_PATH.read_text(encoding="utf-8"),
            AUTHORING_PLAN_PATH.read_text(encoding="utf-8"),
            LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8"),
        )
    )

    assert architecture.index("PluginPreflightProposal") < architecture.index(
        "## Verified Definition Evaluator And Import Realm"
    )
    for required in (
        "PluginExecutionApprovalSubject` v2",
        "ContributionActivationApprovalSubject",
        "`PluginPreflightOutcome`: strict `accepted`/`pending_approval`/`denied`/",
        "Only `accepted` carries an active token and source groups",
        "no reservation, gate, or finalizable preflight",
        "no copied Gate, subject, decision, or evidence",
        "unsupported_plugin_execution_approval_subject_version",
        "unsupported_plugin_execution_decision_record_version",
        "`decisionRecordVersion: 2` and `subjectSchemaVersion: 2`",
        "ACTIVE_OPEN -> CLOSING_ABORT -> ABORTED",
        "-> CLOSING_EXPIRE -> EXPIRED",
        "CAS ACTIVE_OPEN -> FINALIZED",
        "`ExecutionUseReservation` v1",
        "CONSUMED_NOT_STARTED -> CANCELLED_BEFORE_START | STARTING",
        "STARTING             -> EVALUATED | FAILED_AFTER_START",
        "disabled, denied, expired, stale, wrong-scope, wrong-digest, revoked",
        "code is never imported",
    ):
        assert required in architecture


def test_top_level_capability_provider_selection_is_not_a_profile_slot() -> None:
    architecture = "\n".join(
        (
            PAP4_CONTRACT_PATH.read_text(encoding="utf-8"),
            AUTHORING_PLAN_PATH.read_text(encoding="utf-8"),
            LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8"),
        )
    )

    assert "ProductCapabilityProviderResolver" in architecture
    assert "ProductCapabilityConsumerRequirementSet" in architecture
    assert (
        "one sorted Definition/Provider/binding/admission/\nchoice entry"
        in architecture
    )
    assert (
        "ProductCompositionCompiler` preserves every admitted Consumer requirement"
        in architecture
    )
    assert "same-Capability requirements retain deterministic ordering" in architecture
    assert "optional-only" in architecture
    assert "`satisfied` adds the root, `unsatisfied` adds no root/view" in architecture
    assert "CapabilityProviderEligibilityGrant" in architecture
    assert "CapabilityProviderAdmissionRecord" in architecture
    assert "CapabilityProviderBindingSpec" in architecture
    assert "one Provider per closed Capability" in architecture
    assert "CapabilityProviderCandidateFingerprint" in architecture
    assert "resulting transitive closure" in architecture
    assert "ProductCompositionCompiler" in architecture
    assert "Runtime Profile candidate for coding.lsp" not in architecture
    assert (
        "no Runtime Profile slot is created for a top-level Capability ID"
        in architecture
    )
    assert "Product selector over already\n  owner-admitted candidates" in architecture


def test_pap4_core_keeps_owner_admission_and_product_selection_inert() -> None:
    from loushang.harness.capabilities.provider_admission import (
        CapabilityProviderAdmissionRecord,
        CapabilityProviderBindingSpec,
        CapabilityProviderCandidateEnvelope,
        CapabilityProviderEligibilityGrant,
        CapabilityProviderOwnerSnapshot,
        CapabilityProviderSymbolLocator,
    )
    from loushang.harness.capabilities.provider_selection import (
        ProductCapabilityProviderResolver,
        ResolvedCapabilityProviderSet,
    )

    private_symbols = {
        "CapabilityProviderAdmissionRecord",
        "CapabilityProviderBindingSpec",
        "CapabilityProviderCandidateEnvelope",
        "CapabilityProviderEligibilityGrant",
        "CapabilityProviderOwnerSnapshot",
        "CapabilityProviderSymbolLocator",
        "ProductCapabilityProviderResolver",
        "ResolvedCapabilityProviderSet",
    }
    assert private_symbols.isdisjoint(set(public_capabilities.__all__))
    assert all(not hasattr(public_capabilities, symbol) for symbol in private_symbols)
    assert all(
        value.__dataclass_params__.frozen
        for value in (
            CapabilityProviderAdmissionRecord,
            CapabilityProviderBindingSpec,
            CapabilityProviderCandidateEnvelope,
            CapabilityProviderEligibilityGrant,
            CapabilityProviderOwnerSnapshot,
            CapabilityProviderSymbolLocator,
            ResolvedCapabilityProviderSet,
        )
    )
    assert (
        inspect.signature(ProductCapabilityProviderResolver.resolve)
        .parameters["evaluated_at"]
        .default
        is inspect.Parameter.empty
    )

    admission_source = Path(
        "src/loushang/harness/capabilities/provider_admission.py"
    ).read_text(encoding="utf-8")
    selection_source = Path(
        "src/loushang/harness/capabilities/provider_selection.py"
    ).read_text(encoding="utf-8")
    admission_bridge_source = Path(
        "src/loushang/harness/plugin_authoring/provider_admission.py"
    ).read_text(encoding="utf-8")
    provider_codec_source = Path(
        "src/loushang/harness/plugin_authoring/capability_provider.py"
    ).read_text(encoding="utf-8")
    assert (
        admission_source.count("CapabilityProviderDeclarationPayload.from_dict(") == 0
    )
    assert (
        provider_codec_source.count("CapabilityProviderDeclarationPayload.from_dict(")
        == 1
    )
    assert "_capability_provider_payload_from_finalized_candidate" not in (
        admission_source
    )
    assert "_capability_provider_payload_from_finalized_candidate" in (
        admission_bridge_source
    )
    assert "prepare_capability_provider_candidate" not in public_capabilities.__all__
    assert "semantic_fingerprint" not in admission_source
    for forbidden in (
        "RuntimeCapabilityGraphBinder",
        "RuntimeCapabilityGraphPlanner",
        "RuntimeProfileResolver",
        "RegistrationScope",
        "PluginDefinitionEvaluator",
        "McpSurfaceGeneration",
    ):
        assert forbidden not in admission_source
    for forbidden in (
        "CapabilityProviderOwnerAuthority",
        "CapabilityProviderOwnerPolicy",
        "PluginSelection",
        "PluginDefinitionEvaluator",
        "RuntimeCapabilityGraphBinder",
        "RuntimeCapabilityGraphPlanner",
        "RuntimeProfileResolver",
        "RegistrationScope",
        "McpSurfaceGeneration",
    ):
        assert forbidden not in selection_source

    contract = PAP4_CONTRACT_PATH.read_text(encoding="utf-8")
    assert "Status: PAP4-1 generic Capability-owner" in contract
    assert "Only that authority constructs" in contract
    assert "cannot manufacture, renew, widen, or revoke owner records" in contract
    assert "semantic\nfingerprint remains diagnostic only" in contract
    assert "Cycles are retained as metadata for the existing Graph Planner" in contract
    assert "public SDK and MCP expansion remain closed" in contract


def test_owner_admission_agent_event_and_disable_contracts_are_explicit() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    admission = PAP4_CONTRACT_PATH.read_text(encoding="utf-8")

    assert "Every mutation and registration has one exact owner" in architecture
    assert "A manifest may request authority. It cannot grant authority" in architecture
    assert "Declarations are immutable proposals" in architecture
    for contribution_kind in (
        "`resource_item`",
        "`tool_pack`",
        "`command_pack`",
        "`capability_provider`",
    ):
        assert contribution_kind in architecture
    assert "A new contribution kind needs an\nowner contract" in architecture
    assert "The Plugin manager cannot invent\nmerge, precedence" in architecture
    assert "cannot manufacture, renew, widen, or revoke owner records" in admission
    assert (
        "The agent loop specifically remains owned by `loushang.agent`" in architecture
    )
    assert "`restart_required`" in architecture


def test_revision_retention_and_python_import_realm_are_closed_for_v1() -> None:
    architecture = "\n".join(
        (
            PLC2_CONTRACT_PATH.read_text(encoding="utf-8"),
            PLC3_CONTRACT_PATH.read_text(encoding="utf-8"),
            LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8"),
        )
    )

    assert "The only Instance execution states are" in architecture
    assert "ACTIVE --graceful--> DRAINING --> RETIRED" in architecture
    assert "ACTIVE --security--> REVOKING --> RETIRED" in architecture
    assert (
        "There is no `INSTALLED`, `ENABLED`, `STARTING`, `FAILED`, `REMOVED`"
        in architecture
    )
    assert "Package Revision" in architecture
    assert "Materialized Package Revision cache state" in architecture
    assert "write-ahead cleanup journal" in architecture
    assert "`session_membership`" in architecture
    assert "`agent_membership`" in architecture
    assert "enabled_package_revision_changed" in architecture
    assert "process-wide `PluginImportRealm`" in architecture
    assert "not claimed as an enforceable closure" in architecture
    assert "VerifiedRevisionHandle" in architecture
    assert "migration fence" in architecture
    assert "PluginManagementService" in architecture
    assert "MCP" in architecture
    assert "ExecutionUseReservation" in architecture


def test_master_lifecycle_families_match_the_frozen_plc2_contract() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    contract = PLC2_CONTRACT_PATH.read_text(encoding="utf-8")

    assert "desired set:   {absent, installed_disabled, installed_enabled}" in (
        architecture
    )
    assert "`update_staged` is progress\nin the management operation journal" in (
        architecture
    )
    assert "it is not a desired state" in architecture
    assert "Preparation likewise belongs to an activation or\nowner operation" in (
        architecture
    )
    assert "The desired states are exactly `absent`, `installed_disabled`, and" in (
        contract
    )
    assert (
        "`update_staged` persists the complete target while leaving desired selection\nunchanged"
        in (contract)
    )
    assert "desired:     absent -> installed_disabled -> enabled" not in architecture


def test_unified_plugin_architecture_preserves_existing_runtime_authorities() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    for authority in EXPECTED_AUTHORITY_CLASS_SITES:
        assert authority in architecture
    assert "There is no new Plugin Profile resolver" in architecture
    assert "global Plugin transaction" in architecture
    assert "fifth effective-runtime clock" in architecture
    assert "cannot become a second Registration" in architecture
    assert "One lease belongs to one scope and exact owner\ngeneration" in architecture


def test_current_plugin_manifest_name_sites_are_a_baseline_inventory() -> None:
    sources = _source_texts()

    assert (
        _static_string_sites(sources, "plugin.json")
        == EXPECTED_PLUGIN_JSON_STATIC_SITES
    )
    synthetic = {
        Path("third_parser.py"): (
            'PREFIX = "plugin."\n'
            'MANIFEST = f"{PREFIX}json"\n'
            "payload = (root / MANIFEST).read_text()\n"
        )
    }
    assert _static_string_sites(synthetic, "plugin.json") == {Path("third_parser.py")}


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
        _plugin_package_boundary_sink_call_counts(sources)
        == EXPECTED_PLUGIN_PACKAGE_BOUNDARY_SINK_CALL_COUNTS
    )
    assert _plugin_package_boundary_sink_sites(sources) == set(
        EXPECTED_PLUGIN_PACKAGE_BOUNDARY_SINK_OWNERS
    )
    assert set(EXPECTED_PLUGIN_PACKAGE_BOUNDARY_SINK_OWNERS.values()) == {
        "contained-regular-file-capture",
        "package-catalog",
        "package-manifest-parser",
        "package-materializer",
        "package-resource-inventory",
        "package-resource-mount",
        "installed-python-distribution-evidence-resolver",
        "plugin-declaration-coordinator",
        "plugin-strict-json-codec",
        "verified-plugin-python-loader",
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
            "import json as codec\npayload = codec.loads(path.read_text())\n"
        ),
        Path("src/loushang/harness/plugin_authoring/second_decoder.py"): (
            "import json\ndef decode(path):\n    return json.loads(path.read_bytes())\n"
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
        (
            Path("src/loushang/harness/plugin_authoring/second_decoder.py"),
            "decode",
        ),
    }

    same_function_bypasses = {
        Path("src/loushang/harness/plugin_authoring/coordinator.py"): (
            "import json\n"
            "import json.decoder as decoder_module\n"
            "from pydantic_core import from_json\n"
            "decode_alias = json.loads\n"
            "decoder_instance = decoder_module.JSONDecoder()\n"
            "def decode(path, handle):\n"
            "    first = json.loads(path.read_bytes())\n"
            "    second = json.JSONDecoder().decode(path.read_text())\n"
            "    third = decode_alias(first)\n"
            "    fourth = decoder_module.JSONDecoder().decode(first)\n"
            "    fifth = decoder_instance.decode(first)\n"
            "    sixth = from_json(first)\n"
            "    verified = handle.open_file('declarations.json')\n"
            "    return first, second, third, fourth, fifth, sixth, verified\n"
        )
    }
    assert _plugin_package_boundary_sink_call_counts(same_function_bypasses) == {
        (
            Path("src/loushang/harness/plugin_authoring/coordinator.py"),
            "decode",
            "json_decode",
        ): 3,
        (
            Path("src/loushang/harness/plugin_authoring/coordinator.py"),
            "decode",
            "json_decoder_decode",
        ): 3,
        (
            Path("src/loushang/harness/plugin_authoring/coordinator.py"),
            "decode",
            "path_read",
        ): 2,
        (
            Path("src/loushang/harness/plugin_authoring/coordinator.py"),
            "decode",
            "verified_open_file:handle",
        ): 1,
    }


def test_document_byte_ingress_freezes_verified_handle_and_exact_call_edges() -> None:
    compliant = (
        "from loushang.harness.resources.plugins.declarations import "
        "PluginDeclarationDocumentCodec\n"
        "from loushang.harness.resources.plugins.revisions import "
        "VerifiedRevisionHandle\n"
        "class PluginDeclarationCoordinator:\n"
        "    def _read_and_decode_document(\n"
        "        self, handle: VerifiedRevisionHandle, locator: str\n"
        "    ):\n"
        "        with handle.open_file(locator) as stream:\n"
        "            verified_bytes = stream.read()\n"
        "        return PluginDeclarationDocumentCodec.decode_bytes(verified_bytes)\n"
    )
    assert _document_ingress_boundary_violations(compliant) == ()

    helper_bypass = (
        "from loushang.harness.resources.plugins.declarations import "
        "PluginDeclarationDocumentCodec\n"
        "from loushang.harness.resources.plugins.revisions import "
        "VerifiedRevisionHandle\n"
        "from loushang.harness.other.json_helper import hidden_decode\n"
        "class PluginDeclarationCoordinator:\n"
        "    def _read_and_decode_document(\n"
        "        self, handle: VerifiedRevisionHandle, locator: str\n"
        "    ):\n"
        "        with handle.open_file(locator) as stream:\n"
        "            verified_bytes = stream.read()\n"
        "        PluginDeclarationDocumentCodec.decode_bytes(verified_bytes)\n"
        "        return hidden_decode(verified_bytes)\n"
    )
    assert _document_ingress_boundary_violations(helper_bypass) == (
        "document byte ingress must preserve the exact byte flow",
        "unexpected document byte-ingress calls: "
        "{'PluginDeclarationDocumentCodec.decode_bytes': 1, "
        "'forbidden:hidden_decode': 1, 'handle.open_file': 1, 'stream.read': 1}",
    )

    mutable_codec_bypass = (
        "from loushang.harness.resources.plugins.declarations import "
        "PluginDeclarationDocumentCodec\n"
        "from loushang.harness.resources.plugins.revisions import "
        "VerifiedRevisionHandle\n"
        "class PluginDeclarationCoordinator:\n"
        "    def __init__(self, supplied):\n"
        "        PluginDeclarationDocumentCodec()\n"
        "        self._document_codec = supplied\n"
        "    def _read_and_decode_document(\n"
        "        self, handle: VerifiedRevisionHandle, locator: str\n"
        "    ):\n"
        "        with handle.open_file(locator) as stream:\n"
        "            verified_bytes = stream.read()\n"
        "        return self._document_codec.decode_bytes(verified_bytes)\n"
    )
    assert _document_ingress_boundary_violations(mutable_codec_bypass) == (
        "document byte ingress must preserve the exact byte flow",
        "unexpected document byte-ingress calls: "
        "{'forbidden:self._document_codec.decode_bytes': 1, "
        "'handle.open_file': 1, 'stream.read': 1}",
    )

    shadowed_import = (
        "from loushang.harness.resources.plugins.declarations import "
        "PluginDeclarationDocumentCodec\n"
        "from loushang.harness.resources.plugins.revisions import "
        "VerifiedRevisionHandle\n"
        "PluginDeclarationDocumentCodec = replacement\n"
        "class PluginDeclarationCoordinator:\n"
        "    def _read_and_decode_document(\n"
        "        self, handle: VerifiedRevisionHandle, locator: str\n"
        "    ):\n"
        "        with handle.open_file(locator) as stream:\n"
        "            verified_bytes = stream.read()\n"
        "        return PluginDeclarationDocumentCodec.decode_bytes(verified_bytes)\n"
    )
    assert _document_ingress_boundary_violations(shadowed_import) == (
        "required document-boundary imports may not be rebound",
    )

    import_alias_shadow = compliant.replace(
        "class PluginDeclarationCoordinator:\n",
        "from evil import EvilCodec as PluginDeclarationDocumentCodec\n"
        "class PluginDeclarationCoordinator:\n",
    )
    assert _document_ingress_boundary_violations(import_alias_shadow) == (
        "one unshadowed loushang.harness.resources.plugins.declarations."
        "PluginDeclarationDocumentCodec import is required",
    )

    wildcard_import_shadow = compliant.replace(
        "class PluginDeclarationCoordinator:\n",
        "from evil import *\nclass PluginDeclarationCoordinator:\n",
    )
    assert _document_ingress_boundary_violations(wildcard_import_shadow) == (
        "wildcard imports are forbidden at document byte ingress",
    )


def test_coordinator_source_uses_the_frozen_boundary_when_present() -> None:
    sources = _source_texts()
    coordinator = sources.get(PLUGIN_DECLARATION_COORDINATOR_PATH)
    if coordinator is None:
        return
    assert _document_ingress_boundary_violations(coordinator) == ()


def test_current_graph_private_mutations_use_qualified_owner_allowlist() -> None:
    sources = _source_texts()

    assert (
        _graph_private_mutation_sites(sources) == EXPECTED_GRAPH_PRIVATE_MUTATION_SITES
    )
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
        ),
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

    assert (
        _class_method_names(
            sources[api_path],
            "ExtensionContributionAPI",
        )
        == EXPECTED_EXTENSION_DECLARATION_METHODS
    )
    assert _live_binding_sink_inventory(sources) == EXPECTED_LIVE_BINDING_SINK_INVENTORY
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
            "def outside(bindings, policy):\n    bindings.bind_policy(policy)\n"
        ),
        Path("src/loushang/harness/module_binding.py"): ("bindings.bind_tool(tool)\n"),
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


def test_plugin_layer_has_only_the_shared_verified_python_loading_site() -> None:
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
    assert _executable_loading_sites(plugin_sources) == {
        (
            Path("src/loushang/harness/resources/plugins/python_symbols.py"),
            "_DirectImportPolicy._import",
        )
    }


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
    assert "an Agent holds an explicit membership lease" in architecture


def test_unified_plugin_architecture_preserves_exact_registration_ownership() -> None:
    registration_source = Path(
        "src/loushang/harness/runtime/registration.py"
    ).read_text(encoding="utf-8")
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "if lease.owner != self._owner:" in registration_source
    assert "One lease belongs to one scope and exact owner\ngeneration" in architecture
    assert "a root Plugin object cannot capture foreign leases" in architecture


def test_unified_plugin_architecture_keeps_complete_model_input_authority() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "complete Tool definitions and schemas" in architecture
    assert "Fingerprints are supplementary\nprovenance only" in architecture
    assert "never reopens the\ncurrent Plugin package" in architecture


def test_unified_plugin_architecture_keeps_product_kernel_outside_plugins() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "the Product Kernel" in architecture
    assert "`coding.base` Plugin" in architecture
    assert (
        "base Product remains useful with every optional Plugin disabled"
        in architecture
    )
    assert "minimum mandatory\nsystem prompt" in architecture


def test_plc2_contract_freezes_inert_desired_state_before_management_service() -> None:
    contract = PLC2_CONTRACT_PATH.read_text(encoding="utf-8")
    lifecycle_plan = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "plugin-lifecycle-plc2-contract.md" in readme
    assert "plugin-lifecycle-plc2-contract.md" in lifecycle_plan
    for slice_name in (
        "PLC2-1 desired-state ledger",
        "PLC2-2 management command core",
        "PLC2-3 staged update",
        "PLC2-4 retirement and cleanup handoff",
    ):
        assert slice_name in contract
    for desired_state in (
        "absent",
        "installed_disabled",
        "installed_enabled",
    ):
        assert desired_state in contract
    assert "installed_enabled` means desired selection only" in contract
    assert "No caller may supply the committed Instance identity" in contract
    assert "## PLC2-1 Exact Error Codes" in contract
    assert "## PLC2-1 Regression Gate" in contract


def test_plc2_desired_state_layer_has_no_owner_binding_or_product_imports() -> None:
    root = Path("src/loushang/harness/plugin_management")
    sources = {path: path.read_text(encoding="utf-8") for path in root.rglob("*.py")}
    imported = {
        module
        for path, source in sources.items()
        for module in _imported_modules(source, filename=path)
    }

    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported
        for prefix in INERT_PLUGIN_FORBIDDEN_IMPORT_PREFIXES
    )
    assert _executable_loading_sites(sources) == set()
    joined = "\n".join(sources.values())
    for forbidden_call in (
        "register_tool(",
        "bind_tool(",
        "publish_resource(",
        "RuntimeCapabilityGraphBinder(",
        "PluginManager(",
    ):
        assert forbidden_call not in joined


def test_plc2_management_contract_freezes_one_durable_command_authority() -> None:
    contract = PLC2_CONTRACT_PATH.read_text(encoding="utf-8")

    assert "## PLC2-2 Typed Management Command Core" in contract
    assert "Install is intentionally disabled-by-default" in contract
    assert "There is deliberately no claim of atomic commit" in contract
    assert "`pending_approval` and `cancelling` remain reserved" in contract
    assert "## PLC2-2 Exact Error Codes" in contract
    assert "## PLC2-2 Regression Gate" in contract
    for state in (
        "accepted",
        "running",
        "terminal",
    ):
        assert state in contract


def test_plc2_management_service_is_the_only_desired_state_mutation_caller() -> None:
    root = Path("src/loushang/harness/plugin_management")
    sources = {path: path.read_text(encoding="utf-8") for path in root.rglob("*.py")}

    assert _call_sites(sources, "commit") == {
        (
            Path("src/loushang/harness/plugin_management/service.py"),
            "PluginManagementService._execute_unlocked",
        )
    }
    assert _call_sites(sources, "commit_update") == {
        (
            Path("src/loushang/harness/plugin_management/service.py"),
            "PluginManagementService._execute_update_unlocked",
        )
    }
    assert _call_sites(sources, "request_for") == {
        (
            Path("src/loushang/harness/plugin_management/service.py"),
            "PluginManagementService._handoff_retirement",
        ),
    }


def test_plc2_staged_update_contract_is_versioned_inert_and_conservative() -> None:
    contract = PLC2_CONTRACT_PATH.read_text(encoding="utf-8")
    operations = Path("src/loushang/harness/plugin_management/operations.py").read_text(
        encoding="utf-8"
    )

    assert "## PLC2-3 Staged Update Contract" in contract
    assert "`PluginManagementCommandV1` remains exact" in contract
    assert "share one operation journal" in contract
    assert "`not_applicable_unbound`" in contract
    assert "must never be translated into\nschema compatibility" in contract
    assert "`enabled_package_revision_changed`" in contract
    assert "not evidence that a host\nor Session restarted" in contract
    assert (
        'PluginManagementAction = Literal["install", "enable", "disable", "remove"]'
        in (operations)
    )


def test_plc2_retirement_intent_is_handoff_not_effective_state() -> None:
    contract = PLC2_CONTRACT_PATH.read_text(encoding="utf-8")
    retirement = Path("src/loushang/harness/plugin_management/retirement.py").read_text(
        encoding="utf-8"
    )

    assert "## PLC2-4A Durable Retirement Intent" in contract
    assert "do not\nprove that an Instance was ever `ACTIVE`" in contract
    assert "mode `graceful` only" in contract
    assert "Owner retirement and\ncleanup have not begun in PLC2-4A" in contract
    assert (
        "management operation journal\n  -> desired-state journal\n  -> retirement-intent journal"
        in contract
    )
    for forbidden_call in (
        ".dispose(",
        ".deactivate(",
        ".release_package(",
        ".delete(",
        "acquire_current(",
    ):
        assert forbidden_call not in retirement


def test_plc2_retirement_set_is_exact_inert_and_opened_by_one_authority() -> None:
    contract = PLC2_CONTRACT_PATH.read_text(encoding="utf-8")
    retirement_sets_path = Path(
        "src/loushang/harness/plugin_management/retirement_sets.py"
    )
    retirement_sets = retirement_sets_path.read_text(encoding="utf-8")
    management_root = Path("src/loushang/harness/plugin_management")
    management_sources = {
        path: path.read_text(encoding="utf-8") for path in management_root.rglob("*.py")
    }

    assert "## PLC2-4B Exact-Owner Retirement Aggregation" in contract
    assert "does not prove the Instance was\ninactive" in contract
    assert "PLC2-4C must still prove zero Instance leases" in contract
    assert "PLC2-4D must separately own cleanup/package-lease release" in contract
    assert _call_sites(management_sources, "open_set") == {
        (
            Path("src/loushang/harness/plugin_management/service.py"),
            "PluginManagementService._handoff_retirement",
        ),
    }
    assert _call_sites(management_sources, "commit_plan") == set()
    assert _call_sites(management_sources, "record_outcome") == set()
    for forbidden_call in (
        ".dispose(",
        ".deactivate(",
        ".release_package(",
        ".delete(",
        "acquire_current(",
        "register_tool(",
        "bind_tool(",
        "publish_resource(",
    ):
        assert forbidden_call not in retirement_sets


def test_plc2_instance_runtime_is_host_gated_and_not_package_cleanup() -> None:
    contract = PLC2_CONTRACT_PATH.read_text(encoding="utf-8")
    management_root = Path("src/loushang/harness/plugin_management")
    management_sources = {
        path: path.read_text(encoding="utf-8") for path in management_root.rglob("*.py")
    }
    instance_runtime = Path(
        "src/loushang/harness/plugin_management/instance_runtime.py"
    ).read_text(encoding="utf-8")

    assert "## PLC2-4C Instance Lease And State Gate" in contract
    assert "ACTIVE --graceful--> DRAINING --> RETIRED" in contract
    assert "ACTIVE --security--> REVOKING --> RETIRED" in contract
    assert "management operation/coordination lock" in contract
    assert "does not make its Package Revision `gc_eligible`" in contract
    for host_only_call in (
        "activate_current",
        "acquire_current_family",
        "derive_agent_membership",
        "begin_drain",
        "begin_revoke",
        "release_family",
        "complete_retirement",
    ):
        expected_callers = (
            {
                (
                    Path("src/loushang/harness/plugin_management/package_lifecycle.py"),
                    "PluginPackageLifecycleLedger.handoff_cleanup_and_release",
                )
            }
            if host_only_call == "release_family"
            else set()
        )
        assert _call_sites(management_sources, host_only_call) == expected_callers
    for forbidden_call in (
        ".dispose(",
        ".deactivate(",
        ".release_package(",
        ".delete(",
        "register_tool(",
        "bind_tool(",
        "publish_resource(",
    ):
        assert forbidden_call not in instance_runtime


def test_plc2_package_cleanup_is_write_ahead_inert_and_gc_rechecked() -> None:
    contract = PLC2_CONTRACT_PATH.read_text(encoding="utf-8")
    management_root = Path("src/loushang/harness/plugin_management")
    management_sources = {
        path: path.read_text(encoding="utf-8") for path in management_root.rglob("*.py")
    }
    package_lifecycle = Path(
        "src/loushang/harness/plugin_management/package_lifecycle.py"
    ).read_text(encoding="utf-8")
    package_records = Path(
        "src/loushang/harness/plugin_management/package_records.py"
    ).read_text(encoding="utf-8")

    assert "## PLC2-4D Package Cleanup Lease And Recovery Gate" in contract
    assert "One Reference Projection, Not Another Instance Ledger" in contract
    assert "Write-Ahead Cleanup Handoff" in contract
    assert "Startup Recovery Barrier And Conservative GC Candidate" in contract
    assert "A 4D candidate is never permission to unlink bytes by itself" in contract
    assert "PLUGIN_PACKAGE_LIFECYCLE_EVENT_CODEC" in package_records
    assert "PluginInstanceRuntimeEventV1" in package_lifecycle
    assert "recheck_gc_candidate" in package_lifecycle
    assert _call_sites(management_sources, "handoff_cleanup_and_release") == set()
    for forbidden_call in (
        ".dispose(",
        ".deactivate(",
        ".unlink(",
        ".rmdir(",
        ".rmtree(",
        ".delete(",
        "register_tool(",
        "bind_tool(",
        "publish_resource(",
        "mcp_",
    ):
        assert forbidden_call not in package_lifecycle


def test_plc3_verified_evaluation_is_internal_and_host_injection_is_narrow() -> None:
    contract = PLC3_CONTRACT_PATH.read_text(encoding="utf-8")
    approval_execution_path = Path("src/loushang/harness/approval/plugin_execution.py")
    approval_execution = approval_execution_path.read_text(encoding="utf-8")
    selection = Path("src/loushang/harness/resources/plugins/selection.py").read_text(
        encoding="utf-8"
    )
    approval_exports = Path("src/loushang/harness/approval/__init__.py").read_text(
        encoding="utf-8"
    )
    coordinator = PLUGIN_DECLARATION_COORDINATOR_PATH.read_text(encoding="utf-8")
    evaluator_path = Path("src/loushang/harness/plugin_authoring/evaluator.py")
    compatibility_import_realm_path = Path(
        "src/loushang/harness/plugin_authoring/import_realm.py"
    )
    import_realm_path = Path("src/loushang/harness/resources/plugins/import_realm.py")
    evaluator = evaluator_path.read_text(encoding="utf-8")
    import_realm = import_realm_path.read_text(encoding="utf-8")
    compatibility_import_realm = compatibility_import_realm_path.read_text(
        encoding="utf-8"
    )
    authoring_exports = Path(
        "src/loushang/harness/plugin_authoring/__init__.py"
    ).read_text(encoding="utf-8")
    declaration_host = Path("src/loushang/harness/plugin_authoring/host.py").read_text(
        encoding="utf-8"
    )

    assert "Status: PLC3-3 verified Definition evaluation and mixed-source join" in (
        contract
    )
    assert "A durable approved decision remains necessary but not sufficient" in (
        contract
    )
    assert (
        "private `coding.lsp.default` Product\ncomposer the first production caller"
        in (contract)
    )
    assert "generic Host\ndoes not construct either implicitly" in contract
    assert "the executable path still has no production\ncaller" not in contract
    assert "The production\nHost constructs neither" not in contract
    assert (
        "Consumption and reservation creation are therefore one replay transition"
        in (contract)
    )
    assert "one-event multi-use recovery" in contract
    assert "claim group\n-> issue aggregate start permit" in contract
    assert "PLC4/PAP4 subsequently added exact Capability owner admission" in contract
    assert "PluginExecutionDecisionJournal" not in approval_exports
    assert "PluginExecutionStartPermit" not in public_plugins.__all__
    assert "execution_not_consumed" in coordinator
    assert evaluator_path.exists()
    assert import_realm_path.exists()
    assert compatibility_import_realm_path.exists()
    assert "PluginDefinitionEvaluator" not in authoring_exports
    assert "PluginImportRealm" not in authoring_exports
    assert "execution_evaluator: PluginDefinitionEvaluator | None = None" in (
        declaration_host
    )
    assert declaration_host.count("execution_evaluator=execution_evaluator") == 1
    assert "VerifiedRevisionHandle.open_file()" in contract
    assert "PluginExecutionDecisionJournal" in evaluator
    assert "PluginExecutionStartPermit" in evaluator
    assert "sys.path" not in evaluator
    assert "sys.modules" not in evaluator
    assert "PluginImportRealm" in import_realm
    assert "plugin_import_realm_polluted" in import_realm
    assert "Compatibility import" in compatibility_import_realm
    assert "plugin_import_realm_polluted" not in compatibility_import_realm
    assert approval_execution.count("append_jsonl_record(") == 1
    assert "append_jsonl_records(" not in approval_execution
    assert "_ExecutionConsumedV1" in approval_execution
    assert "_ExecutionUseTransitionedV1" in approval_execution
    assert "_ExecutionUsesRecoveredV1" in approval_execution
    assert "PluginExecutionConsumptionReceiptV1" in approval_execution
    assert "PluginExecutionUseReservationV1" in approval_execution
    assert 'consumption_state="CONSUMED"' in approval_execution
    assert selection.count("def _issue_execution_start_permit(") == 1
    assert "plugin_execution_start_permit_consumed" in selection
    assert "plugin_execution_start_not_applicable" in selection
    assert "approval.plugin_execution" not in selection
    for forbidden in (
        "VerifiedRevisionHandle",
        "import_module",
        "exec_module",
        "PluginDeclarationHost",
        "RuntimeCapabilityGraphBinder",
        "RegistrationScope",
        "WorkspaceToolRegistry",
        "SessionFacade",
        "McpSurfaceGeneration",
        "mcp_",
    ):
        assert forbidden not in approval_execution
    for forbidden in (
        "RuntimeCapabilityGraphBinder",
        "RegistrationScope",
        "WorkspaceToolRegistry",
        "SessionFacade",
        "McpSurfaceGeneration",
        "mcp_",
    ):
        assert forbidden not in evaluator


def test_pap5_session_root_is_the_only_graph_planning_site() -> None:
    model_call = Path("src/loushang/harness/session/model_call.py").read_text(
        encoding="utf-8"
    )
    agent_product = Path("src/loushang/harness/session/agent_product.py").read_text(
        encoding="utf-8"
    )

    assert "RuntimeCapabilityGraphPlanner" not in model_call
    # Initial v1 planning and the opt-in pre-publication v2 Resource replan both
    # remain inside the one Product Session composition root.
    assert agent_product.count("RuntimeCapabilityGraphPlanner().plan(") == 2


def test_pap55_resource_catalog_plan_preserves_one_owner_and_native_skills() -> None:
    plan = RESOURCE_CATALOG_PLAN_PATH.read_text(encoding="utf-8")
    authoring = AUTHORING_PLAN_PATH.read_text(encoding="utf-8")
    lifecycle = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    for required in (
        "Pluginize mechanisms, not every piece of content.",
        "`resource.catalog_engine`",
        "`resource.source`",
        "Both are `capability_component` contributions",
        "`harness.resources` Capability Provider remains the only top-level",
        "A native filesystem Skill remains loadable",
        "without a Plugin manifest",
        "The engine also does not own precedence",
        "an owner validator canonicalizes",
        "Package Catalog; never choose effective Resources",
        "focused `resource.catalog`\nand `resource.load` facets",
        "there is no `skill.catalog` facet",
        "`ResourceBundle` as a compatibility projection",
        "the Catalog never imports or starts it",
        "`PreparedResourceOwnerGeneration`",
        "`StagedResourceCompositionCandidate` remains the sole\nResource Profile",
        "RCP0 through RCP5 precede the `coding.lsp` production migration",
        "new MCP functionality",
    ):
        assert required in plan

    assert "### PAP5.5: Resource Catalog And Source Component Foundation" in authoring
    assert "### PLC4.5: Resource Catalog And Source Component Foundation" in lifecycle
    assert "resource-catalog-pluginization-plan.md" in authoring
    assert "resource-catalog-pluginization-plan.md" in lifecycle
    assert "resource-catalog-pluginization-plan.md" in readme
    assert "Source implementation and merge remain PLC8 work" not in authoring


def test_pap55_review_corrections_freeze_single_catalog_ingress_and_custody() -> None:
    plan = RESOURCE_CATALOG_PLAN_PATH.read_text(encoding="utf-8")
    lifecycle = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")
    extension_resources = Path(
        "src/loushang/harness/extensions/resources.py"
    ).read_text(encoding="utf-8")

    for required in (
        "There is no direct candidate ingress beside `ResourceSourceSnapshot`.",
        "one `extension_generation` source snapshot",
        "generation-scoped body-read adapter",
        "one synchronous, no-await commit publishes Extension state, Catalog",
        "`discover_initial` to be synchronous, non-awaiting",
        "lazy loading delays only body injection, never body identity",
        "may narrow a handle's relative subtree or filters, but may not name",
        "The producer union has no ambiguous nullable peers",
        "The independent content-origin union is",
        "is exclusively held as a child of the existing\n"
        "`StagedResourceCompositionCandidate`",
        "ResourceRefreshClassification",
        "`restart_required` returns without mutating the active Session",
        "replace Package Catalog's effective `ResourceLoader.discover_resources()`",
        "delete production effective-selection imports of `ResourceSnapshot`",
    ):
        assert required in plan

    assert "admitted data-only Resource candidates;" not in plan
    assert "declared_content_digest (optional)" not in plan
    assert "Catalog\nengine alone chooses effective entries" not in plan
    assert "`capability_component` follows after the complete-Bundle" not in lifecycle
    assert "PLC4.5 adds only the two internal Resource-owner" in lifecycle
    assert "return bundle.merge(" in extension_resources
    assert "delete direct post-Catalog bundle merge authority" in plan


def test_plc6abcde_freezes_sets_owners_management_and_authority_cutover() -> None:
    lifecycle_plan = LIFECYCLE_PLAN_PATH.read_text(encoding="utf-8")
    contract = PLC6_CONTRACT_PATH.read_text(encoding="utf-8")

    assert "PLC6A through PLC6E implementation status (2026-08-30)" in (lifecycle_plan)
    assert "PLC6 production validation and its terminal three-view review" in (
        lifecycle_plan
    )
    assert "without mutating settings or rediscovering a source" in lifecycle_plan
    assert "publishes its Prompt and Skill through the sole Resource Catalog" in (
        lifecycle_plan
    )
    assert "PLC6A through PLC6E are implemented" in contract
    assert "disabled or removed Installation is never resurrected" in contract
    assert "without consulting a deleted mutable source" in contract
    assert "publish atomically with the\nusable Session" in contract
    assert "enter effective-runtime provenance" in contract
    for required in (
        "A Composition Set is an inert Product policy request",
        "`PluginManagementService` remains the only durable desired-state command",
        "cannot override an explicit disable or removal",
        "`coding-minimal`",
        "`coding-standard`",
        "`coding-architecture`",
        "not persisted as management state",
        "The Kernel must remain truthful",
        "No slice may retain two effective writers",
        "source scans prove no old caller can independently publish",
    ):
        assert required in contract


def test_plc6e_catalog_session_has_no_peer_exact_tool_or_command_publisher() -> None:
    coding_sources = tuple(Path("src/loushang/coding").rglob("*.py"))
    tool_calls: list[Path] = []
    command_stage_calls: list[Path] = []
    standard_command_catalog_calls: list[Path] = []
    for path in coding_sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        tool_names: set[str] = set()
        tool_modules: set[str] = set()
        command_catalog_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == (
                "loushang.coding.tool_pack"
            ):
                tool_names.update(
                    item.asname or item.name
                    for item in node.names
                    if item.name == "register_coding_builtin_tools"
                )
            elif isinstance(node, ast.Import):
                tool_modules.update(
                    item.asname or item.name
                    for item in node.names
                    if item.name == "loushang.coding.tool_pack"
                )
            elif isinstance(node, ast.ImportFrom) and node.module in {
                "loushang.harness.session",
                "loushang.harness.session.commands.catalog",
            }:
                command_catalog_names.update(
                    item.asname or item.name
                    for item in node.names
                    if item.name == "list_standard_session_command_descriptors"
                )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            is_tool_call = (
                isinstance(node.func, ast.Name) and node.func.id in tool_names
            ) or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "register_coding_builtin_tools"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in tool_modules
            )
            if is_tool_call:
                tool_calls.append(path)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "stage_pack":
                command_stage_calls.append(path)
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in command_catalog_names
            ):
                standard_command_catalog_calls.append(path)
    agent_session = Path("src/loushang/coding/session/agent_session.py").read_text(
        encoding="utf-8"
    )
    coding_sdk = Path("src/loushang/coding/__init__.py").read_text(encoding="utf-8")
    coding_bootstrap = Path("src/loushang/coding/bootstrap.py").read_text(
        encoding="utf-8"
    )
    tool_pack = Path("src/loushang/coding/tool_pack.py").read_text(
        encoding="utf-8"
    )
    agent_product = Path("src/loushang/harness/session/agent_product.py").read_text(
        encoding="utf-8"
    )

    assert not Path("src/loushang/coding/resource_authority.py").exists()
    assert all(
        "resource_authority_mode" not in path.read_text(encoding="utf-8")
        and "legacy_explicit" not in path.read_text(encoding="utf-8")
        for path in coding_sources
    )
    # PLC6E removes the last peer Tool publisher from the stable SDK and rejects
    # every exact-owner compatibility definition at Catalog construction.
    assert tool_calls == []
    assert '"AgentSession",' not in coding_sdk
    assert '"register_coding_builtin_tools",' not in coding_sdk
    assert '"register_coding_builtin_tools",' not in tool_pack
    assert "peer_exact_tool_publisher" in coding_bootstrap
    assert set(command_stage_calls) == {
        Path("src/loushang/coding/_base_plugin_owners.py")
    }
    assert set(standard_command_catalog_calls) == {
        Path("src/loushang/coding/_base_plugin_owners.py")
    }
    assert "build_coding_base_plugin_owners(" in agent_session
    assert "SessionCommandGenerationRegistry()" in agent_session
    assert "command_generations=self._command_generation_registry" in agent_product
