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
    {"harness.model_input", "harness.resources", "harness.workspace"}
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
        path for path, _node in definitions.get("CapabilityCompositionRuntime", [])
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
    assert definition_imports == {"loushang.harness.capabilities.contracts"}
    assert all("provider" not in item for item in definition_imports)
    assert all("consumer" not in item for item in definition_imports)

    provider_imports = _absolute_loushang_imports(WORKSPACE_PROVIDER_PATH)
    assert "loushang.harness.capabilities.workspace_contracts" in provider_imports
    provider_source = WORKSPACE_PROVIDER_PATH.read_text(encoding="utf-8")
    assert "ProcessHost" not in provider_source
    assert "SandboxBackend" not in provider_source
    for consumer_path in WORKSPACE_CONSUMER_PATHS:
        consumer_imports = _absolute_loushang_imports(consumer_path)
        assert "loushang.harness.capabilities.workspace_contracts" in consumer_imports
        assert all("workspace_provider" not in item for item in consumer_imports)
        consumer_source = consumer_path.read_text(encoding="utf-8")
        assert "RuntimeCapabilityGraphRuntime" not in consumer_source


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
