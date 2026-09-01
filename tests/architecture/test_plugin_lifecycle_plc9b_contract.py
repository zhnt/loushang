from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

CONTRACT = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9b-contract.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9-inventory.md"
)
INDEX = Path("docs/internals/architecture/harness/plugin/README.md")
BASELINE_TEST = Path("tests/architecture/test_plugin_lifecycle_plc9_baseline.py")
PACKAGE_ROOT = Path("src/loushang/harness/resources/packages")
PACKAGE_MATERIALIZER = PACKAGE_ROOT / "materializer.py"
PACKAGE_OPERATIONS = PACKAGE_ROOT / "operations.py"
PACKAGE_SOURCE_RESOLVER = PACKAGE_ROOT / "source_resolver.py"
PLUGIN_REVISIONS = Path("src/loushang/harness/resources/plugins/revisions.py")
PLUGIN_DEPENDENCIES = Path("src/loushang/harness/resources/plugins/dependencies.py")
PACKAGE_LIFECYCLE = Path("src/loushang/harness/plugin_management/package_lifecycle.py")
AUTHOR_SDK = Path("src/loushang/plugin/__init__.py")

PACKAGE_ENTRYPOINT_ROOTS = (
    Path("src/loushang/coding/cli"),
    Path("src/loushang/harness/cli"),
    Path("src/loushang/harness/host/rpc/commands"),
    Path("src/loushang/harness/session"),
    PACKAGE_ROOT,
)
PACKAGE_ENTRYPOINT_SYMBOLS = {
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
EXPECTED_MATRIX_IDS = {
    "B-ACQ-01",
    "B-ACQ-02",
    "B-ACQ-03",
    "B-PATH-01",
    "B-PATH-02",
    "B-PATH-03",
    "B-PATH-04",
    "B-TYPE-01",
    "B-LIMIT-01",
    "B-WHEEL-01",
    "B-WHEEL-02",
    "B-WHEEL-03",
    "B-WHEEL-04",
    "B-CLOSURE-01",
    "B-CLOSURE-02",
    "B-CLOSURE-03",
    "B-PUB-01",
    "B-PUB-02",
    "B-PUB-03",
    "B-CRASH-01",
    "B-CRASH-02",
    "B-CONCUR-01",
    "B-ENTRY-01",
    "B-ENTRY-02",
    "B-NOEXEC-01",
    "B-STATE-01",
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def _package_entrypoint_scope_counts() -> Counter[tuple[Path, str, str]]:
    counts: Counter[tuple[Path, str, str]] = Counter()
    for root in PACKAGE_ENTRYPOINT_ROOTS:
        for path in root.rglob("*.py"):
            source = _source(path)
            if not any(symbol in source for symbol in PACKAGE_ENTRYPOINT_SYMBOLS):
                continue
            visitor = _QualifiedFunctionVisitor()
            visitor.visit(ast.parse(source, filename=str(path)))
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


def _documented_entrypoint_counts() -> Counter[tuple[Path, str, str]]:
    inventory = _source(INVENTORY)
    block = inventory.split("<!-- plc9b-entrypoint-inventory:start -->", 1)[1]
    block = block.split("<!-- plc9b-entrypoint-inventory:end -->", 1)[0]
    counts: Counter[tuple[Path, str, str]] = Counter()
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line.startswith("src/"):
            continue
        qualified_site, raw_count = line.rsplit(" = ", 1)
        raw_path, scope, symbol = qualified_site.rsplit("::", 2)
        key = (Path(raw_path), scope, symbol)
        assert key not in counts, key
        counts[key] = int(raw_count)
    return counts


def _adversarial_matrix() -> dict[str, tuple[str, str, str]]:
    contract = _source(CONTRACT)
    section = contract.split("## Adversarial Acceptance Matrix", 1)[1]
    section = section.split("## Rollout, Rollback, And Deletion Gates", 1)[0]
    rows: dict[str, tuple[str, str, str]] = {}
    for line in section.splitlines():
        if not line.startswith("| B-"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        assert len(cells) == 4, cells
        case_id, stage, adversary, outcome = cells
        assert case_id not in rows, case_id
        rows[case_id] = (stage, adversary, outcome)
    return rows


def test_plc9b_contract_is_indexed_and_explicitly_design_only() -> None:
    contract = _source(CONTRACT)
    index = _source(INDEX)
    inventory = _source(INVENTORY)

    assert index.count("(plugin-lifecycle-plc9b-contract.md)") == 1
    assert inventory.count("(plugin-lifecycle-plc9b-contract.md)") == 1
    assert "Contract version: PLC9B.0" in contract
    assert "Delivery status: design-only" in contract
    assert "No runtime acquisition, archive extraction" in contract
    assert "Public author SDK effect: none" in contract
    for deferred in (
        "PLC9A2 transport activation",
        "`local_worker`",
        "`remote_service`",
        "source builds",
        "artifact GC/deletion",
        "private-data deletion",
    ):
        assert deferred in contract


def test_plc9b_canonical_entrypoint_inventory_exactly_matches_source_ast() -> None:
    documented = _documented_entrypoint_counts()
    actual = _package_entrypoint_scope_counts()

    assert len(documented) == 70
    assert sum(documented.values()) == 111
    assert actual == documented
    assert "test_plc9_freezes_named_package_lifecycle_sites_and_occurrences" in (
        _source(BASELINE_TEST)
    )


def test_plc9b_freezes_one_high_cohesion_owner_and_narrow_dependencies() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)

    for required in (
        "one Package lifecycle composition in `loushang.harness.resources.packages`",
        "Authenticated provenance and bounded streaming only",
        "Sole owner of quarantine, limits, inert extraction",
        "never acquires, extracts, publishes, selects, or deletes by itself",
    ):
        assert required in inventory
    assert "does not authenticate Sources, parse archives" in contract
    assert "does not belong in `foundation`" in contract
    assert "does not belong in `foundation`, a transport, a\nProduct adapter" in (
        contract
    )
    for exact_existing_owner in (
        "materializer.py::PackageMaterializer",
        "operations.py::PackageOperationsRuntime",
        "revisions.py::PluginRevisionStore",
        "dependencies.py::PluginDependencyClosureLock",
        "package_lifecycle.py::PluginPackageLifecycleLedger",
    ):
        assert exact_existing_owner in inventory


def test_plc9b_evidence_is_versioned_and_v1_is_never_reinterpreted() -> None:
    contract = _source(CONTRACT)
    dependencies = _source(PLUGIN_DEPENDENCIES)

    for evidence in (
        "authenticated source envelope v1",
        "bounded acquisition receipt v1",
        "quarantine receipt v1",
        "verified wheel artifact v1",
        "dependency closure lock v2",
        "immutable publication receipt v1",
    ):
        assert evidence in contract
    assert 'PLUGIN_DEPENDENCY_LOCK_FORMAT = "loushang.plugin-dependency-lock/v1"' in (
        dependencies
    )
    assert "v1 remains replay-only" in contract
    assert "never satisfies PLC9B recursive verification" in contract
    assert "no reader may decode\nv1 bytes as closure v2" in contract
    assert "unsupported future evidence version fails closed" in contract


def test_plc9b_transaction_never_confuses_publication_with_selection() -> None:
    contract = _source(CONTRACT)

    ordered_phases = (
        "accepted",
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "closure_verified",
        "publishing",
        "published",
        "committed",
    )
    positions = [contract.index(f"  -> {phase}") for phase in ordered_phases[1:]]
    assert positions == sorted(positions)
    for boundary in (
        "remain unselectable until",
        "A crash after an immutable rename",
        "never trusts directory existence alone",
        "cannot implicitly enable a Plugin",
        "same identity with different input fails closed",
    ):
        assert boundary in contract


def test_plc9b_adversarial_matrix_is_complete_and_fail_closed() -> None:
    matrix = _adversarial_matrix()

    assert set(matrix) == EXPECTED_MATRIX_IDS
    for case_id, (stage, adversary, outcome) in matrix.items():
        assert stage, case_id
        assert adversary, case_id
        assert any(
            token in outcome
            for token in (
                "reject",
                "fail closed",
                "fail-closed",
                "terminate",
                "stop",
                "revalidate",
                "converges",
                "inert",
                "zero child process",
            )
        ), case_id
        assert any(
            token in outcome for token in ("no ", "never ", "zero ", "unselectable")
        ), case_id


def test_plc9b_matrix_covers_every_route_and_native_platform_evidence() -> None:
    matrix = _adversarial_matrix()
    entry_case = " ".join(matrix["B-ENTRY-01"])
    contract = _source(CONTRACT)

    for route in (
        "CLI",
        "RPC",
        "Session",
        "startup",
        "operations",
        "direct materializer",
    ):
        assert route in entry_case
    assert "unsupported host emulation cannot count as the only evidence" in contract
    assert "Source distributions are unconditionally rejected" in contract
    assert "zero child process, import, hook, network side effect" in entry_case or (
        "zero child process, import, hook, network side effect" in contract
    )


def test_plc9b_zero_runtime_claim_preserves_visible_unsafe_debt() -> None:
    contract = _source(CONTRACT)
    materializer = _source(PACKAGE_MATERIALIZER)
    operations = _source(PACKAGE_OPERATIONS)
    resolver = _source(PACKAGE_SOURCE_RESOLVER)
    revisions = _source(PLUGIN_REVISIONS)
    lifecycle = _source(PACKAGE_LIFECYCLE)
    author_sdk = _source(AUTHOR_SDK)

    assert "class PythonPackageInstallerBackend:" in materializer
    assert '"pip",\n                    "install",' in materializer
    assert (
        '"-m",\n                    "pip",\n                    "install",'
        in materializer
    )
    assert "--only-binary" not in materializer
    assert "def remove_remote_source(" in materializer
    assert "def forget_remote_source(" in materializer
    assert "def forget_plugin_binding(" in materializer
    assert "def uninstall_sync(" in operations
    assert "materialize_remote_source_sync" in resolver
    assert "class PluginRevisionStore:" in revisions
    assert "class PluginPackageLifecycleLedger:" in lifecycle
    assert "current `PythonPackageInstallerBackend`" in contract
    assert "must remain unavailable or fail closed without mutation" in contract
    assert not (PACKAGE_ROOT / "lifecycle.py").exists()
    for forbidden in (
        "PackageLifecycleOwner",
        "BoundedAcquisitionReceipt",
        "VerifiedWheelArtifact",
        "DependencyClosureLockV2",
    ):
        assert forbidden not in author_sdk


def test_plc9b_rollback_never_restores_the_unsafe_installer() -> None:
    contract = _source(CONTRACT)

    for boundary in (
        "There is no rollback to the\ncurrent installer for Plugin-bound input",
        "disabling the new owner disables the\nartifact command",
        "cannot fall through to\nthe current `uv`/`pip`",
        "rollback disables Plugin artifact operations instead of restoring an unsafe",
    ):
        assert boundary in contract
