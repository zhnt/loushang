from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import defaultdict
from functools import cache
from pathlib import Path

BASELINE_PATH = Path(
    "docs/internals/architecture/harness/capability-runtime-convergence-pr0-baseline.md"
)
PLAN_PATH = Path(
    "docs/internals/architecture/harness/capability-runtime-convergence-plan.md"
)
README_PATH = Path("docs/internals/architecture/harness/README.md")
CAPABILITY_CATALOG_PATH = Path(
    "docs/internals/architecture/harness/capability-catalog.md"
)
CAPABILITY_LIFECYCLE_PATH = Path(
    "docs/internals/architecture/harness/capability-dependency-and-mount-lifecycle.md"
)
CAPABILITY_VARIATION_PATH = Path(
    "docs/internals/architecture/harness/capability-variation-and-replacement-boundary.md"
)
CAPABILITY_CATALOG_GENERATOR_PATH = Path(
    "scripts/generate_harness_capability_catalog.py"
)
SOURCE_ROOT = Path("src/loushang")
HARNESS_ROOT = Path("src/loushang/harness")
CAPABILITIES_ROOT = HARNESS_ROOT / "capabilities"
PURE_GRAPH_MODULE_IMPORTS = {
    CAPABILITIES_ROOT / "contracts.py": {"loushang.harness.runtime"},
    CAPABILITIES_ROOT / "providers.py": {"loushang.harness.capabilities.contracts"},
    CAPABILITIES_ROOT / "graph_planning.py": {
        "loushang.harness.capabilities.contracts",
        "loushang.harness.capabilities.providers",
    },
}
GRAPH_RUNTIME_MODULE_IMPORTS = {
    CAPABILITIES_ROOT / "provider_binding.py": {
        "loushang.harness.capabilities.contracts",
        "loushang.harness.capabilities.providers",
        "loushang.harness.runtime.registration",
    },
    CAPABILITIES_ROOT / "graph_runtime.py": {
        "loushang.harness.capabilities.contracts",
        "loushang.harness.capabilities.graph_planning",
        "loushang.harness.capabilities.provider_binding",
        "loushang.harness.runtime.bindings",
        "loushang.harness.runtime.registration",
    },
    CAPABILITIES_ROOT / "graph_binding.py": {
        "loushang.harness.capabilities.graph_planning",
        "loushang.harness.capabilities.graph_runtime",
        "loushang.harness.capabilities.provider_binding",
        "loushang.harness.runtime._owned_tasks",
        "loushang.harness.runtime.bindings",
        "loushang.harness.runtime.registration",
    },
    CAPABILITIES_ROOT / "effective_runtime.py": {
        "loushang.foundation.json",
        "loushang.harness.capabilities.graph_runtime",
        "loushang.harness.runtime",
    },
    CAPABILITIES_ROOT / "graph_projection.py": {
        "loushang.foundation.json",
        "loushang.harness.capabilities.effective_runtime",
        "loushang.harness.capabilities.graph_runtime",
        "loushang.harness.runtime",
    },
}
WORKSPACE_DEFINITION_PATH = CAPABILITIES_ROOT / "workspace_contracts.py"
WORKSPACE_PROVIDER_PATH = CAPABILITIES_ROOT / "workspace_provider.py"
WORKSPACE_CONSUMER_PATHS = (
    CAPABILITIES_ROOT / "workspace_tool_consumer.py",
    CAPABILITIES_ROOT / "workspace_process_consumer.py",
)
RESOURCES_DEFINITION_PATH = CAPABILITIES_ROOT / "resources_contracts.py"
RESOURCES_PROVIDER_PATH = CAPABILITIES_ROOT / "resources_provider.py"
RESOURCES_CONSUMER_PATH = CAPABILITIES_ROOT / "resources_consumers.py"
SESSION_DEFINITION_PATH = CAPABILITIES_ROOT / "session_contracts.py"
SESSION_PROVIDER_PATH = HARNESS_ROOT / "session" / "session_capability_provider.py"
SESSION_CONSUMER_PATH = HARNESS_ROOT / "session" / "session_capability_consumer.py"
WORKSPACE_CAPABILITY_PORTS_PATH = (
    HARNESS_ROOT / "session" / "workspace_capability_ports.py"
)
SESSION_SUPPORT_PATHS = (
    HARNESS_ROOT / "session" / "resource_capability_ports.py",
    HARNESS_ROOT / "session" / "session_transcript_capability_ports.py",
    WORKSPACE_CAPABILITY_PORTS_PATH,
    HARNESS_ROOT / "transcript" / "capability_candidate.py",
)

REQUIRED_ROWS = {
    "SUR": 28,
    "COMP": 11,
    "CALL": 6,
    "OWN": 9,
    "FAULT": 14,
}

ACCEPTED_GRAPH_OWNERS: dict[str, tuple[Path, ...]] = {
    "RuntimeCapabilityGraphPlanner": (CAPABILITIES_ROOT,),
    "RuntimeCapabilityGraphBinder": (CAPABILITIES_ROOT,),
    "RuntimeCapabilityGraphRuntime": (CAPABILITIES_ROOT,),
    "RuntimeCapabilityGraphProjector": (CAPABILITIES_ROOT,),
}

FORBIDDEN_RUNTIME_SYMBOLS = frozenset(
    {
        "EffectiveRuntimeSnapshot",
        "GlobalCapabilityRegistry",
        "GlobalCapabilityProviderRegistry",
        "GlobalCapabilityGraph",
        "GlobalCapabilityContainer",
        "GlobalCapabilityContext",
    }
)

GRAPH_API_SYMBOLS = frozenset(
    {
        "RuntimeCapabilityGraphPlanner",
        "RuntimeCapabilityGraphBinder",
        "RuntimeCapabilityGraphRuntime",
        "RuntimeCapabilityGraphProjector",
    }
)

IMPLEMENTED_GRAPH_API_SYMBOLS = GRAPH_API_SYMBOLS

BROAD_PARAMETER_NAMES = frozenset(
    {"context", "runtime", "bindings", "services", "container"}
)

EXPECTED_SOURCE_BACKED_CAPABILITY_IDS = frozenset(
    {
        "coding.lsp",
        "harness.model_input",
        "harness.resources",
        "harness.session",
        "harness.workspace",
    }
)


@cache
def _python_trees() -> dict[Path, ast.Module]:
    return {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in SOURCE_ROOT.rglob("*.py")
    }


def _class_definitions(
    trees: dict[Path, ast.Module],
) -> dict[str, list[tuple[Path, ast.ClassDef]]]:
    definitions: dict[str, list[tuple[Path, ast.ClassDef]]] = defaultdict(list)
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                definitions[node.name].append((path, node))
    return definitions


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _annotation_name(annotation: ast.expr) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        prefix = _annotation_name(annotation.value)
        return annotation.attr if prefix is None else f"{prefix}.{annotation.attr}"
    return None


def _subscript_items(annotation: ast.Subscript) -> tuple[ast.expr, ...]:
    if isinstance(annotation.slice, ast.Tuple):
        return tuple(annotation.slice.elts)
    return (annotation.slice,)


def _is_broad_annotation(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return True
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            parsed = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return False
        return _is_broad_annotation(parsed)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_broad_annotation(annotation.left) or _is_broad_annotation(
            annotation.right
        )

    name = _annotation_name(annotation)
    if name is not None:
        return name.rsplit(".", maxsplit=1)[-1] in {
            "Any",
            "Mapping",
            "MutableMapping",
            "dict",
            "object",
        }
    if not isinstance(annotation, ast.Subscript):
        return False

    container = _annotation_name(annotation.value)
    if container is None:
        return False
    container = container.rsplit(".", maxsplit=1)[-1]
    items = _subscript_items(annotation)
    if container in {"Optional", "Union"}:
        return any(_is_broad_annotation(item) for item in items)
    if container == "Annotated":
        return bool(items) and _is_broad_annotation(items[0])
    if container in {"Mapping", "MutableMapping", "dict"}:
        return len(items) != 2 or _is_broad_annotation(items[1])
    return False


def _absolute_loushang_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_python_trees()[path]):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name for alias in node.names if alias.name.startswith("loushang.")
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module is not None
            and node.module.startswith("loushang.")
        ):
            imports.add(node.module)
    return imports


def _resolved_import_targets(
    path: Path,
    tree: ast.Module | None = None,
) -> set[str]:
    """Resolve absolute and package-relative imports to canonical targets."""

    module_parts = path.relative_to(Path("src")).with_suffix("").parts
    package_parts = module_parts[:-1]
    targets: set[str] = set()
    for node in ast.walk(tree or _python_trees()[path]):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            keep = len(package_parts) - (node.level - 1)
            if keep < 0:
                continue
            base_parts = package_parts[:keep]
            if node.module:
                base_parts = (*base_parts, *node.module.split("."))
            module = ".".join(base_parts)
        else:
            module = node.module or ""
        if module:
            targets.add(module)
        for alias in node.names:
            if alias.name == "*":
                continue
            targets.add(".".join(part for part in (module, alias.name) if part))
    return targets


def _workspace_consumer_graph_runtime_import_violations(
    tree: ast.Module,
) -> list[str]:
    """Allow only a direct import of the generation-scoped facet lease type."""

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations.extend(
                alias.name
                for alias in node.names
                if "graph_runtime" in alias.name.split(".")
            )
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if any(alias.name == "graph_runtime" for alias in node.names):
            violations.append("graph_runtime module alias")
            continue
        if node.module is not None and "graph_runtime" in node.module.split("."):
            unexpected = {
                alias.name for alias in node.names if alias.name != "CapabilityFacetSet"
            }
            violations.extend(sorted(unexpected))
    return violations


def test_pr0_inventory_keeps_required_rows_and_evidence() -> None:
    text = BASELINE_PATH.read_text(encoding="utf-8")

    for prefix, count in REQUIRED_ROWS.items():
        actual = re.findall(rf"^\| ({prefix}-\d{{2}}) \|", text, re.MULTILINE)
        expected = [f"{prefix}-{index:02d}" for index in range(1, count + 1)]
        assert actual == expected

    evidence_references = sorted(
        set(re.findall(r"`(tests/[\w./-]+\.py)::(test_[\w]+)`", text))
    )
    assert evidence_references
    for raw_path, function_name in evidence_references:
        path = Path(raw_path)
        assert path.is_file(), f"missing PR0 evidence file: {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert function_name in functions, (
            f"missing PR0 evidence function: {raw_path}::{function_name}"
        )


def test_pr0_baseline_is_linked_from_the_plan_and_harness_catalog() -> None:
    link = "capability-runtime-convergence-pr0-baseline.md"
    assert link in PLAN_PATH.read_text(encoding="utf-8")
    assert link in README_PATH.read_text(encoding="utf-8")


def test_source_backed_capability_catalog_is_complete_and_current() -> None:
    result = subprocess.run(
        [sys.executable, str(CAPABILITY_CATALOG_GENERATOR_PATH), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    catalog = CAPABILITY_CATALOG_PATH.read_text(encoding="utf-8")
    source_backed_ids = frozenset(
        re.findall(r"^\| `([\w.]+)` \|", catalog, re.MULTILINE)
    )
    assert source_backed_ids == EXPECTED_SOURCE_BACKED_CAPABILITY_IDS

    catalog_link = "capability-catalog.md"
    assert catalog_link in README_PATH.read_text(encoding="utf-8")
    assert catalog_link in CAPABILITY_LIFECYCLE_PATH.read_text(encoding="utf-8")
    assert catalog_link in CAPABILITY_VARIATION_PATH.read_text(encoding="utf-8")


def test_capability_authority_docs_do_not_claim_the_graph_is_unimplemented() -> None:
    lifecycle = CAPABILITY_LIFECYCLE_PATH.read_text(encoding="utf-8")
    variation = CAPABILITY_VARIATION_PATH.read_text(encoding="utf-8")

    assert "top-level Capability dependency planner" not in lifecycle
    assert "until the top-level planner exists" not in lifecycle
    assert "while the top-level planner and live Mount graph do not" not in variation


def test_accepted_graph_contracts_have_one_declared_package_owner() -> None:
    definitions = _class_definitions(_python_trees())

    for symbol, owners in ACCEPTED_GRAPH_OWNERS.items():
        locations = [path for path, _node in definitions.get(symbol, [])]
        expected_count = 1 if symbol in IMPLEMENTED_GRAPH_API_SYMBOLS else 0
        assert len(locations) == expected_count, (
            f"unexpected convergence contract count for {symbol}: {locations}"
        )
        assert all(
            any(_is_relative_to(path, owner) for owner in owners) for path in locations
        ), f"{symbol} must be owned by one of {owners}, found {locations}"

    legacy_runtime_locations = [
        path for path, _node in definitions.get("StagedResourceCompositionCandidate", [])
    ]
    assert legacy_runtime_locations == [
        Path("src/loushang/harness/capabilities/composition_runtime.py")
    ]

    forbidden = {
        symbol: [
            path
            for path, _node in definitions[symbol]
            if _is_relative_to(path, HARNESS_ROOT)
        ]
        for symbol in FORBIDDEN_RUNTIME_SYMBOLS
        if any(
            _is_relative_to(path, HARNESS_ROOT)
            for path, _node in definitions.get(symbol, [])
        )
    }
    assert forbidden == {}

    accepted_graph_managers = {
        "RuntimeCapabilityGraphRuntime",
        "RuntimeCapabilityGraphProjector",
    }
    duplicate_graph_managers = {
        symbol: [path for path, _node in locations]
        for symbol, locations in definitions.items()
        if symbol.endswith(("GraphRuntime", "GraphProjector"))
        and symbol not in accepted_graph_managers
        and any(_is_relative_to(path, CAPABILITIES_ROOT) for path, _node in locations)
    }
    assert duplicate_graph_managers == {}


def test_target_graph_apis_reject_broad_service_locator_parameters() -> None:
    definitions = _class_definitions(_python_trees())
    violations: list[str] = []

    for symbol in GRAPH_API_SYMBOLS:
        for path, class_node in definitions.get(symbol, []):
            for node in class_node.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                parameters = (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                    *(() if node.args.vararg is None else (node.args.vararg,)),
                    *(() if node.args.kwarg is None else (node.args.kwarg,)),
                )
                for parameter in parameters:
                    if parameter.arg in BROAD_PARAMETER_NAMES and _is_broad_annotation(
                        parameter.annotation
                    ):
                        annotation = (
                            "<unannotated>"
                            if parameter.annotation is None
                            else ast.unparse(parameter.annotation)
                        )
                        violations.append(
                            f"{path}:{node.lineno} "
                            f"{symbol}.{node.name}({parameter.arg}: "
                            f"{annotation})"
                        )

    assert violations == []


def test_graph_planning_modules_keep_data_only_dependency_boundaries() -> None:
    assert {
        path: _absolute_loushang_imports(path) for path in PURE_GRAPH_MODULE_IMPORTS
    } == PURE_GRAPH_MODULE_IMPORTS


def test_graph_runtime_and_workspace_definition_provider_consumer_boundaries() -> None:
    assert {
        path: _absolute_loushang_imports(path) for path in GRAPH_RUNTIME_MODULE_IMPORTS
    } == GRAPH_RUNTIME_MODULE_IMPORTS

    definition_imports = _absolute_loushang_imports(WORKSPACE_DEFINITION_PATH)
    definition_targets = _resolved_import_targets(WORKSPACE_DEFINITION_PATH)
    assert definition_imports == {"loushang.harness.capabilities.contracts"}
    assert not any(
        target.startswith(
            (
                "loushang.harness.capabilities.provider_binding",
                "loushang.harness.capabilities.workspace_provider",
                "loushang.harness.capabilities.workspace_tool_consumer",
                "loushang.harness.capabilities.workspace_process_consumer",
                "loushang.harness.capabilities.graph_binding",
                "loushang.harness.capabilities.graph_planning",
                "loushang.harness.capabilities.graph_projection",
                "loushang.harness.capabilities.graph_runtime",
            )
        )
        for target in definition_targets
    )

    provider_imports = _absolute_loushang_imports(WORKSPACE_PROVIDER_PATH)
    assert "loushang.harness.capabilities.workspace_contracts" in provider_imports
    provider_targets = _resolved_import_targets(WORKSPACE_PROVIDER_PATH)
    assert not any(
        target.startswith(
            (
                "loushang.harness.capabilities.graph_binding",
                "loushang.harness.capabilities.graph_planning",
                "loushang.harness.capabilities.graph_projection",
                "loushang.harness.capabilities.graph_runtime",
            )
        )
        for target in provider_targets
    )
    forbidden_authority_imports = (
        "loushang.harness.approval",
        "loushang.harness.policy",
        "loushang.harness.sandbox",
        "loushang.harness.tools.process_hosting",
        "loushang.harness.workspace.process.host",
        "loushang.harness.workspace.process.local",
    )
    assert not any(
        imported.startswith(forbidden)
        for imported in provider_targets
        for forbidden in forbidden_authority_imports
    )
    provider_source = WORKSPACE_PROVIDER_PATH.read_text(encoding="utf-8")
    assert "ProcessHost" not in provider_source
    assert "SandboxBackend" not in provider_source
    for consumer_path in WORKSPACE_CONSUMER_PATHS:
        consumer_imports = _absolute_loushang_imports(consumer_path)
        consumer_targets = _resolved_import_targets(consumer_path)
        assert "loushang.harness.capabilities.workspace_contracts" in consumer_imports
        assert not any(
            target.startswith(
                (
                    "loushang.harness.capabilities.provider_binding",
                    "loushang.harness.capabilities.workspace_provider",
                    "loushang.harness.capabilities.graph_binding",
                    "loushang.harness.capabilities.graph_planning",
                    "loushang.harness.capabilities.graph_projection",
                )
            )
            for target in consumer_targets
        )
        assert (
            _workspace_consumer_graph_runtime_import_violations(
                _python_trees()[consumer_path]
            )
            == []
        )
        assert not any(
            target.startswith("loushang.harness.capabilities.graph_runtime")
            and target
            not in {
                "loushang.harness.capabilities.graph_runtime",
                "loushang.harness.capabilities.graph_runtime.CapabilityFacetSet",
            }
            for target in consumer_targets
        )
        assert not any(
            imported.startswith(forbidden)
            for imported in consumer_targets
            for forbidden in forbidden_authority_imports
        )
        assert {
            "loushang.harness.capabilities.graph_binding",
            "loushang.harness.capabilities.graph_planning",
            "loushang.harness.capabilities.graph_projection",
        }.isdisjoint(consumer_imports)
        consumer_source = consumer_path.read_text(encoding="utf-8")
        assert "RuntimeCapabilityGraphRuntime" not in consumer_source


def test_resources_definition_provider_consumer_boundaries() -> None:
    definition_imports = _absolute_loushang_imports(RESOURCES_DEFINITION_PATH)
    assert definition_imports == {"loushang.harness.capabilities.contracts"}

    provider_imports = _absolute_loushang_imports(RESOURCES_PROVIDER_PATH)
    assert "loushang.harness.capabilities.resources_contracts" in provider_imports
    assert not any(item.startswith("loushang.coding") for item in provider_imports)

    consumer_imports = _absolute_loushang_imports(RESOURCES_CONSUMER_PATH)
    assert "loushang.harness.capabilities.resources_contracts" in consumer_imports
    assert all("resources_provider" not in item for item in consumer_imports)

    forbidden_symbols = {
        *GRAPH_API_SYMBOLS,
        "AgentProductSession",
        "CapabilityDependencyBinding",
        "ProductTranscriptSession",
    }
    forbidden_modules = {
        "graph_binding",
        "graph_planning",
        "graph_projection",
        "graph_runtime",
    }
    violations: list[str] = []
    for path in (
        RESOURCES_DEFINITION_PATH,
        RESOURCES_PROVIDER_PATH,
        RESOURCES_CONSUMER_PATH,
    ):
        resolved_imports = _resolved_import_targets(path)
        if path != RESOURCES_PROVIDER_PATH:
            for target in resolved_imports:
                if target.startswith(
                    "loushang.harness.capabilities.provider_binding"
                ) or target.startswith(
                    "loushang.harness.capabilities.resources_provider"
                ):
                    violations.append(f"{path}:resolved-import:{target}")
        path_forbidden_modules = forbidden_modules
        if path == RESOURCES_CONSUMER_PATH:
            path_forbidden_modules = forbidden_modules - {"graph_runtime"}
        for node in ast.walk(_python_trees()[path]):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if path == RESOURCES_CONSUMER_PATH and any(
                    alias.name == "graph_runtime" for alias in node.names
                ):
                    violations.append(
                        f"{path}:{node.lineno}:module-alias:graph_runtime"
                    )
                if path == RESOURCES_CONSUMER_PATH and "graph_runtime" in module.split(
                    "."
                ):
                    unexpected = {
                        alias.name
                        for alias in node.names
                        if alias.name != "CapabilityFacetSet"
                    }
                    violations.extend(
                        f"{path}:{node.lineno}:graph-runtime-symbol:{name}"
                        for name in sorted(unexpected)
                    )
                if any(part in path_forbidden_modules for part in module.split(".")):
                    violations.append(f"{path}:{node.lineno}:module:{module}")
                for alias in node.names:
                    if alias.name in forbidden_symbols:
                        violations.append(f"{path}:{node.lineno}:symbol:{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "graph_runtime" in alias.name.split("."):
                        violations.append(f"{path}:{node.lineno}:module:{alias.name}")
                    elif any(
                        part in path_forbidden_modules for part in alias.name.split(".")
                    ):
                        violations.append(f"{path}:{node.lineno}:module:{alias.name}")
            elif isinstance(node, ast.Name) and node.id in forbidden_symbols:
                violations.append(f"{path}:{node.lineno}:name:{node.id}")

    assert violations == []


def test_session_definition_provider_consumer_boundaries() -> None:
    definition_imports = _absolute_loushang_imports(SESSION_DEFINITION_PATH)
    assert definition_imports == {"loushang.harness.capabilities.contracts"}

    provider_imports = _absolute_loushang_imports(SESSION_PROVIDER_PATH)
    assert "loushang.harness.capabilities.session_contracts" in provider_imports
    assert "loushang.harness.session.legacy_side_question" in provider_imports
    assert not any(item.startswith("loushang.coding") for item in provider_imports)
    assert {
        "loushang.harness.capabilities.graph_binding",
        "loushang.harness.capabilities.graph_planning",
        "loushang.harness.capabilities.graph_projection",
        "loushang.harness.capabilities.graph_runtime",
    }.isdisjoint(provider_imports)

    consumer_imports = _absolute_loushang_imports(SESSION_CONSUMER_PATH)
    assert "loushang.harness.capabilities.session_contracts" in consumer_imports
    assert all("session_capability_provider" not in item for item in consumer_imports)
    assert {
        "loushang.harness.capabilities.graph_binding",
        "loushang.harness.capabilities.graph_planning",
        "loushang.harness.capabilities.graph_projection",
    }.isdisjoint(consumer_imports)

    forbidden_symbols = {
        "RuntimeCapabilityGraphBinder",
        "RuntimeCapabilityGraphPlanner",
        "RuntimeCapabilityGraphProjector",
        "RuntimeCapabilityGraphRuntime",
        "AgentProductSession",
        "ProductTranscriptSession",
        "RuntimeProfileBinding",
    }
    forbidden_modules = {
        "graph_binding",
        "graph_planning",
        "graph_projection",
        "graph_runtime",
    }
    violations: list[str] = []
    for path in (
        SESSION_DEFINITION_PATH,
        SESSION_PROVIDER_PATH,
        SESSION_CONSUMER_PATH,
        *SESSION_SUPPORT_PATHS,
    ):
        resolved_imports = _resolved_import_targets(path)
        if path != SESSION_PROVIDER_PATH:
            for target in resolved_imports:
                if target.startswith(
                    "loushang.harness.capabilities.provider_binding"
                ) or target.startswith(
                    "loushang.harness.session.session_capability_provider"
                ):
                    violations.append(f"{path}:resolved-import:{target}")
        path_forbidden_symbols = forbidden_symbols
        if path != SESSION_PROVIDER_PATH:
            path_forbidden_symbols = {
                *forbidden_symbols,
                "CapabilityDependencyBinding",
            }
        path_forbidden_modules = forbidden_modules
        if path == SESSION_CONSUMER_PATH:
            path_forbidden_modules = forbidden_modules - {"graph_runtime"}
        tree = _python_trees()[path]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if path == SESSION_CONSUMER_PATH and any(
                    alias.name == "graph_runtime" for alias in node.names
                ):
                    violations.append(
                        f"{path}:{node.lineno}:module-alias:graph_runtime"
                    )
                if path == SESSION_CONSUMER_PATH and "graph_runtime" in module.split(
                    "."
                ):
                    unexpected = {
                        alias.name
                        for alias in node.names
                        if alias.name != "CapabilityFacetSet"
                    }
                    violations.extend(
                        f"{path}:{node.lineno}:graph-runtime-symbol:{name}"
                        for name in sorted(unexpected)
                    )
                if any(part in path_forbidden_modules for part in module.split(".")):
                    violations.append(f"{path}:{node.lineno}:module:{module}")
                for alias in node.names:
                    if alias.name in path_forbidden_symbols:
                        violations.append(f"{path}:{node.lineno}:symbol:{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if (
                        path == SESSION_CONSUMER_PATH
                        and "graph_runtime" in alias.name.split(".")
                    ):
                        violations.append(f"{path}:{node.lineno}:module:{alias.name}")
                        continue
                    if any(
                        part in path_forbidden_modules for part in alias.name.split(".")
                    ):
                        violations.append(f"{path}:{node.lineno}:module:{alias.name}")
            elif isinstance(node, ast.Name) and node.id in path_forbidden_symbols:
                violations.append(f"{path}:{node.lineno}:name:{node.id}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parameters = (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                    *(() if node.args.vararg is None else (node.args.vararg,)),
                    *(() if node.args.kwarg is None else (node.args.kwarg,)),
                )
                for parameter in parameters:
                    if parameter.arg in {"self", "cls"}:
                        continue
                    if _is_broad_annotation(parameter.annotation) and not (
                        parameter.arg == "signal"
                        and path
                        in {SESSION_CONSUMER_PATH, WORKSPACE_CAPABILITY_PORTS_PATH}
                    ):
                        violations.append(
                            f"{path}:{node.lineno}:parameter:{parameter.arg}"
                        )
            elif isinstance(node, ast.AnnAssign) and _is_broad_annotation(
                node.annotation
            ):
                target = ast.unparse(node.target)
                if not (
                    path == WORKSPACE_CAPABILITY_PORTS_PATH
                    and target == "self._operation_bindings"
                ):
                    violations.append(f"{path}:{node.lineno}:field:{target}")
    assert violations == []

    provider_tree = _python_trees()[SESSION_PROVIDER_PATH]
    dependency_fields = {
        class_node.name: node
        for class_node in provider_tree.body
        if isinstance(class_node, ast.ClassDef)
        and class_node.name
        in {
            "_ResourceCompositionFacet",
            "_WorkspaceProcessFacet",
            "_WorkspaceToolFacet",
        }
        for node in class_node.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_dependency"
        and any(
            isinstance(annotation, ast.Name)
            and annotation.id == "CapabilityDependencyBinding"
            for annotation in ast.walk(node.annotation)
        )
    }
    dependency_name_uses = [
        node
        for node in ast.walk(provider_tree)
        if isinstance(node, ast.Name) and node.id == "CapabilityDependencyBinding"
    ]
    assert set(dependency_fields) == {
        "_ResourceCompositionFacet",
        "_WorkspaceProcessFacet",
        "_WorkspaceToolFacet",
    }
    expected_dependency_uses = {
        annotation
        for field in dependency_fields.values()
        for annotation in ast.walk(field.annotation)
        if isinstance(annotation, ast.Name)
        and annotation.id == "CapabilityDependencyBinding"
    }
    assert set(dependency_name_uses) == expected_dependency_uses


def test_relative_import_resolution_covers_capability_boundary_bypasses() -> None:
    bypass_tree = ast.parse(
        "from .resources_provider import resources_capability_provider_binding\n"
        "from ..capabilities import provider_binding as raw\n"
        "from .workspace_provider import workspace_capability_provider_binding\n"
        "from . import graph_runtime as graph_api\n"
    )
    targets = _resolved_import_targets(RESOURCES_CONSUMER_PATH, bypass_tree)

    assert "loushang.harness.capabilities.resources_provider" in targets
    assert "loushang.harness.capabilities.provider_binding" in targets
    assert "loushang.harness.capabilities.workspace_provider" in targets
    assert "loushang.harness.capabilities.graph_runtime" in targets
    assert _workspace_consumer_graph_runtime_import_violations(bypass_tree)
    assert not _workspace_consumer_graph_runtime_import_violations(
        ast.parse("from .graph_runtime import CapabilityFacetSet\n")
    )


def test_broad_annotation_syntax_gate_covers_obvious_locator_shapes() -> None:
    broad = (
        "object",
        "'object'",
        "Any",
        "typing.Optional[object]",
        "Union[None, Mapping[str, Any]]",
        "None | object",
        "Annotated[object, 'runtime services']",
        "dict[str, object]",
    )
    narrow = (
        "WorkspaceContext",
        "Mapping[str, WorkspaceFacet]",
        "tuple[CapabilityRequirement, ...]",
    )

    assert all(
        _is_broad_annotation(ast.parse(value, mode="eval").body) for value in broad
    )
    assert not any(
        _is_broad_annotation(ast.parse(value, mode="eval").body) for value in narrow
    )
