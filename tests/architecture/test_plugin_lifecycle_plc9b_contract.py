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
OWNER_KERNEL_ROOT = PACKAGE_ROOT / "plugin_lifecycle"
BOUNDED_ACQUISITION = OWNER_KERNEL_ROOT / "acquisition.py"
PHASE_EVIDENCE = OWNER_KERNEL_ROOT / "phase_evidence.py"
ARTIFACT_RUNTIME = OWNER_KERNEL_ROOT / "runtime.py"
WHEEL_VERIFIER = OWNER_KERNEL_ROOT / "wheel.py"
WINDOWS_QUARANTINE = OWNER_KERNEL_ROOT / "windows_quarantine.py"
CLOSURE_VERIFIER = OWNER_KERNEL_ROOT / "closure.py"
CLOSURE_OWNER = OWNER_KERNEL_ROOT / "closure_owner.py"
CLOSURE_JOURNAL = OWNER_KERNEL_ROOT / "closure_journal.py"
CLOSURE_RUNTIME = OWNER_KERNEL_ROOT / "closure_runtime.py"
COMMIT_RECORDS = OWNER_KERNEL_ROOT / "commit_records.py"
TRANSACTION_PINS = OWNER_KERNEL_ROOT / "transaction_pins.py"
TRANSACTION_PIN_RUNTIME = OWNER_KERNEL_ROOT / "transaction_pin_runtime.py"
STAGING = OWNER_KERNEL_ROOT / "staging.py"
COMMITTED_SETS = OWNER_KERNEL_ROOT / "committed_sets.py"
STAGING_SET_RUNTIME = OWNER_KERNEL_ROOT / "staging_set_runtime.py"
TREE_TRANSFER = OWNER_KERNEL_ROOT / "tree_transfer.py"
POSIX_MATERIALIZATION = OWNER_KERNEL_ROOT / "posix_materialization.py"
WINDOWS_MATERIALIZATION = OWNER_KERNEL_ROOT / "windows_materialization.py"
STORE_SETTLEMENTS = OWNER_KERNEL_ROOT / "store_settlements.py"
COMMIT_ADMISSION = OWNER_KERNEL_ROOT / "commit_admission.py"
RETENTION_HANDOFF = OWNER_KERNEL_ROOT / "retention_handoff.py"
EPOCH_FENCE = OWNER_KERNEL_ROOT / "epoch_fence.py"
POSIX_EPOCH_CUTOVER = OWNER_KERNEL_ROOT / "posix_epoch_cutover.py"
WINDOWS_EPOCH_CUTOVER = OWNER_KERNEL_ROOT / "windows_epoch_cutover.py"
OFFLINE_RESTORE = OWNER_KERNEL_ROOT / "offline_restore.py"
POSIX_OFFLINE_RESTORE = OWNER_KERNEL_ROOT / "posix_offline_restore.py"
WINDOWS_OFFLINE_RESTORE = OWNER_KERNEL_ROOT / "windows_offline_restore.py"
LEGACY_ADOPTION = OWNER_KERNEL_ROOT / "adoption.py"
LEGACY_ADOPTION_TRANSACTION = OWNER_KERNEL_ROOT / "adoption_transaction.py"
PRODUCT_LIFECYCLE = Path("src/loushang/harness/resources/packages/product_lifecycle.py")
LINUX_LEGACY_RUNTIME = Path("src/loushang/harness/sandbox/package_legacy_runtime.py")
WINDOWS_LEGACY_RUNTIME = Path(
    "src/loushang/harness/sandbox/package_windows_legacy_runtime.py"
)
CLOSURE_TEST = Path("tests/harness/resources/packages/test_plc9b_closure.py")
CLOSURE_OWNER_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_closure_owner.py"
)
CLOSURE_JOURNAL_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_closure_journal.py"
)
CLOSURE_RUNTIME_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_closure_runtime.py"
)
COMMIT_RECORDS_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_commit_records.py"
)
TRANSACTION_PINS_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_transaction_pins.py"
)
TRANSACTION_PIN_RUNTIME_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_transaction_pin_runtime.py"
)
STAGING_TEST = Path("tests/harness/resources/packages/test_plc9b_staging.py")
COMMITTED_SETS_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_committed_sets.py"
)
STAGING_SET_RUNTIME_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_staging_set_runtime.py"
)
TREE_TRANSFER_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_verified_tree_transfer.py"
)
POSIX_MATERIALIZATION_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_posix_materialization.py"
)
WINDOWS_MATERIALIZATION_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_windows_materialization.py"
)
COMMIT_ADMISSION_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_commit_admission.py"
)
RETENTION_HANDOFF_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_retention_handoff.py"
)
EPOCH_FENCE_TEST = Path("tests/harness/resources/packages/test_plc9b_epoch_fence.py")
POSIX_EPOCH_CUTOVER_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_posix_epoch_cutover.py"
)
WINDOWS_EPOCH_CUTOVER_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_windows_epoch_cutover.py"
)
OFFLINE_RESTORE_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_offline_restore.py"
)
POSIX_OFFLINE_RESTORE_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_posix_offline_restore.py"
)
WINDOWS_OFFLINE_RESTORE_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_windows_offline_restore.py"
)
LEGACY_ADOPTION_TEST = Path("tests/harness/resources/packages/test_plc9b_adoption.py")
LEGACY_ADOPTION_TRANSACTION_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_adoption_transaction.py"
)
ARTIFACT_RUNTIME_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_artifact_owner.py"
)
PYPROJECT = Path("pyproject.toml")
WINDOWS_NATIVE_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_windows_native.py"
)
WINDOWS_WORKFLOW = Path(".github/workflows/windows-shell-compatibility.yml")
ADVERSARIAL_TEST = Path("tests/harness/resources/packages/test_plc9b_adversarial.py")
HARNESS_WORKFLOW = Path(".github/workflows/harness-quality.yml")
PLUGIN_REVISIONS = Path("src/loushang/harness/resources/plugins/revisions.py")
PLUGIN_DEPENDENCIES = Path("src/loushang/harness/resources/plugins/dependencies.py")
PACKAGE_LIFECYCLE = Path("src/loushang/harness/plugin_management/package_lifecycle.py")
AUTHOR_SDK = Path("src/loushang/plugin/__init__.py")

SOURCE_ROOT = Path("src/loushang")
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
PACKAGE_EFFECT_SYMBOLS = {
    "CodingPackageMaterializer",
    "GitPackageMaterializerBackend",
    "PackageMaterializer",
    "PackageOperationsRuntime",
    "PackageSourceResolver",
    "PluginRevisionStore",
    "PythonPackageInstallerBackend",
    "_bind_plugin_packages",
    "_plugin_revision_store",
    "_run_backend_for_record",
    "_run_backend_for_record_sync",
    "bind_plugin_packages",
    "forget_plugin_binding",
    "forget_remote_source",
    "materialize_remote_source",
    "materialize_remote_source_sync",
    "materialize_temporary_remote_source",
    "materialize_temporary_remote_source_sync",
    "prepare_remote_source",
    "publish_all",
    "publish_plugin_packages",
    "rebind_plugin_packages",
    "reopen_plugin_package",
    "remove_remote_source",
    "update_all_remote_sources",
    "update_remote_source",
    "update_remote_source_sync",
}
EXPECTED_MANIFEST_CATEGORY_COUNTS = {
    "ACQ": 7,
    "ADMISSION": 7,
    "ARCH": 5,
    "CLASS": 5,
    "CLOSURE": 7,
    "COMPAT": 15,
    "CONCUR": 3,
    "CRASH": 12,
    "ENTRY": 8,
    "HANDOFF": 6,
    "LIMIT": 6,
    "NOEXEC": 4,
    "PATH": 10,
    "PUB": 13,
    "STATE": 5,
    "TYPE": 7,
    "WHEEL": 7,
}
MANIFEST_FIELDS = (
    "case_id",
    "platform",
    "barrier",
    "fixture",
    "code",
    "disposition",
    "oracles",
    "test_node",
    "workflow",
    "status",
)
PLC9B3E3C1_POSIX_CASES = {
    "B-PUB-PRECREATE",
    "B-PUB-POSIX-ROOT-SWAP",
    "B-PUB-POSIX-ANCESTOR-SWAP",
    "B-PUB-POSIX-HANDLE-SUCCESS",
    "B-PUB-POSIX-HANDLE-REJECT",
}
PLC9B3E3C2_WINDOWS_CASES = {
    "B-PUB-SWAP-WINDOWS",
    "B-PUB-WIN-ROOT-ABA",
    "B-PUB-WIN-ANCESTOR-ABA",
    "B-PUB-WIN-HANDLE-SUCCESS",
    "B-PUB-WIN-HANDLE-REJECT",
}
PLC9B3E3C3_SETTLEMENT_CASES = {
    "B-PUB-COLLISION",
    "B-PUB-REUSE",
}
PLC9B4A_COMMIT_ADMISSION_CASES = {
    "B-PUB-UNCOMMITTED",
    "B-ADMISSION-DEPENDENCY",
    "B-ADMISSION-WRONG-SET",
    "B-ADMISSION-WRONG-REQUEST",
    "B-ADMISSION-WRONG-OPERATION",
    "B-ADMISSION-WRONG-SCOPE",
    "B-ADMISSION-WRONG-PLUGIN",
    "B-ADMISSION-DIGEST-TAMPER",
}
PLC9B4B_RETENTION_HANDOFF_CASES = {
    "B-HANDOFF-BEFORE-DESIRED",
    "B-HANDOFF-AFTER-DESIRED",
    "B-HANDOFF-AFTER-SETTLEMENT",
    "B-HANDOFF-DESIRED-REJECT",
    "B-HANDOFF-STALE-RECEIPT",
    "B-HANDOFF-CONCURRENT-REPLAY",
}
PLC9B4C0_EPOCH_ADMISSION_CASES = {
    "B-COMPAT-EPOCH",
    "B-COMPAT-MIXED",
}
PLC9B4C1_POSIX_EPOCH_CUTOVER_CASES = {
    "B-COMPAT-CUTOVER-POSIX",
    "B-COMPAT-PREFENCE-LIVE-POSIX",
}
PLC9B4C2_WINDOWS_EPOCH_CUTOVER_CASES = {
    "B-COMPAT-CUTOVER-WINDOWS",
    "B-COMPAT-PREFENCE-LIVE-WINDOWS",
}
PLC9B4C3C_LINUX_OFFLINE_RESTORE_CASES = {
    "B-COMPAT-OFFLINE-RESTORE-POSIX",
}
PLC9B4C5_WINDOWS_OFFLINE_RESTORE_CASES = {
    "B-COMPAT-OFFLINE-RESTORE-WINDOWS",
}
PLC9B4C4D_LINUX_ADOPTION_CASES = {
    "B-COMPAT-ADOPT",
}
PLC9B4C4E_LINUX_ADOPTION_FAILURE_CASES = {
    "B-COMPAT-ADOPT-UNAUTHORIZED",
    "B-COMPAT-ADOPT-UNAVAILABLE",
}
PLC9B4C4F_LINUX_ADOPTION_COMMITTED_CRASH_CASES = {
    "B-COMPAT-ADOPT-CRASH-AFTER-COMMITTED",
}
PLC9B4C4G_LINUX_ADOPTION_PRECOMMIT_CRASH_CASES = {
    "B-COMPAT-ADOPT-CRASH",
}
PLC9B4C4G_PRECOMMIT_PHASES = (
    "acquiring",
    "acquired",
    "inspecting",
    "extracted",
    "resolving_closure",
    "closure_verified",
    "transaction_pinned",
    "staging",
    "set_published",
)
ALLOWED_PLATFORMS = {"any", "posix-native", "windows-native"}
ALLOWED_ORACLES = {
    "b_namespace_unreachable",
    "bounded_residue",
    "binding_unchanged",
    "dependency_pins_released",
    "desired_unchanged",
    "exact_pin_set",
    "handle_released",
    "enablement_unchanged",
    "instance_unchanged",
    "legacy_snapshot_exact",
    "no_binding",
    "no_desired",
    "no_extra_network",
    "no_import",
    "no_handle_issued",
    "no_outside_write",
    "no_peer_fallback",
    "no_process",
    "no_publication",
    "no_reopen",
    "no_secret",
    "no_skip",
    "no_zero_pin",
    "pin_visible",
    "same_receipt",
    "single_owner",
    "transaction_pin_released",
}


def _plugin_revision_receiver_token(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and node.attr in {"publish", "publish_all", "reopen"}
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "_plugin_revision_store"
    ):
        return f"PluginRevisionStore.{node.attr}"
    return None


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _QualifiedFunctionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
        self.scopes: list[
            tuple[str, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]
        ] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified = ".".join((*self.scope, node.name))
        self.scopes.append((qualified, node))
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
        self.scopes.append((qualified, node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _node_scope(visitor: _QualifiedFunctionVisitor, node: ast.AST) -> str:
    if not hasattr(node, "lineno"):
        return "<module>"
    enclosing = [
        (qualified, scope)
        for qualified, scope in visitor.scopes
        if scope.lineno <= node.lineno <= scope.end_lineno
    ]
    if not enclosing:
        return "<module>"
    return max(
        enclosing,
        key=lambda item: (
            item[0].count("."),
            -int(item[1].end_lineno - item[1].lineno),
        ),
    )[0]


def _semantic_scope_counts(
    symbols: set[str],
) -> Counter[tuple[Path, str, str]]:
    counts: Counter[tuple[Path, str, str]] = Counter()
    for path in SOURCE_ROOT.rglob("*.py"):
        source = _source(path)
        if not any(symbol in source for symbol in symbols):
            continue
        tree = ast.parse(source, filename=str(path))
        visitor = _QualifiedFunctionVisitor()
        visitor.visit(tree)
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for alias in node.names:
                original = alias.name.rsplit(".", 1)[-1]
                if original in symbols:
                    aliases[alias.asname or original] = original
        for node in ast.walk(tree):
            symbol: str | None = None
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = node.name
            elif isinstance(node, ast.Name):
                symbol = aliases.get(node.id, node.id)
            elif isinstance(node, ast.Attribute):
                symbol = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                symbol = node.value
            elif isinstance(node, ast.alias):
                symbol = node.name.rsplit(".", 1)[-1]
            if symbol in symbols:
                counts[(path, _node_scope(visitor, node), symbol)] += 1
    return counts


def _package_entrypoint_scope_counts() -> Counter[tuple[Path, str, str]]:
    return _semantic_scope_counts(PACKAGE_ENTRYPOINT_SYMBOLS)


def _package_effect_scope_counts() -> Counter[tuple[Path, str, str]]:
    counts = _semantic_scope_counts(PACKAGE_EFFECT_SYMBOLS)
    for path in SOURCE_ROOT.rglob("*.py"):
        source = _source(path)
        if path != PLUGIN_REVISIONS and "_plugin_revision_store" not in source:
            continue
        tree = ast.parse(_source(path), filename=str(path))
        visitor = _QualifiedFunctionVisitor()
        visitor.visit(tree)
        for node in ast.walk(tree):
            token: str | None = None
            scope = _node_scope(visitor, node)
            if (
                path == PLUGIN_REVISIONS
                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and scope
                in {"PluginRevisionStore.publish", "PluginRevisionStore.reopen"}
            ):
                token = scope
            elif (
                path == PLUGIN_REVISIONS
                and scope.startswith("PluginRevisionStore.")
                and isinstance(node, ast.Attribute)
                and node.attr == "publish"
            ):
                token = "PluginRevisionStore.publish"
            else:
                token = _plugin_revision_receiver_token(node)
            if token is not None:
                counts[(path, scope, token)] += 1
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


def _documented_effect_counts() -> Counter[tuple[Path, str, str]]:
    inventory = _source(INVENTORY)
    block = inventory.split("<!-- plc9b-effect-inventory:start -->", 1)[1]
    block = block.split("<!-- plc9b-effect-inventory:end -->", 1)[0]
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


def _adversarial_manifest() -> dict[str, dict[str, str]]:
    contract = _source(CONTRACT)
    block = contract.split("<!-- plc9b-adversarial-manifest:start -->", 1)[1]
    block = block.split("<!-- plc9b-adversarial-manifest:end -->", 1)[0]
    rows: dict[str, dict[str, str]] = {}
    header: tuple[str, ...] | None = None
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line == "```text" or line == "```":
            continue
        cells = tuple(cell.strip() for cell in line.split("|"))
        if header is None:
            header = cells
            assert header == MANIFEST_FIELDS
            continue
        assert len(cells) == len(MANIFEST_FIELDS), cells
        row = dict(zip(MANIFEST_FIELDS, cells, strict=True))
        case_id = row["case_id"]
        assert case_id not in rows, case_id
        rows[case_id] = row
    assert header == MANIFEST_FIELDS
    return rows


def _assert_current_publication_statuses(
    manifest: dict[str, dict[str, str]],
) -> None:
    publication_cases = {
        case_id for case_id in manifest if case_id.startswith("B-PUB-")
    }
    assert len(publication_cases) == 13
    assert {
        case_id
        for case_id in publication_cases
        if manifest[case_id]["status"] == "implemented"
    } == (
        PLC9B3E3C1_POSIX_CASES
        | PLC9B3E3C2_WINDOWS_CASES
        | PLC9B3E3C3_SETTLEMENT_CASES
        | (PLC9B4A_COMMIT_ADMISSION_CASES & publication_cases)
    )
    assert all(
        manifest[case_id]["status"] == "planned"
        for case_id in publication_cases
        - PLC9B3E3C1_POSIX_CASES
        - PLC9B3E3C2_WINDOWS_CASES
        - PLC9B3E3C3_SETTLEMENT_CASES
        - PLC9B4A_COMMIT_ADMISSION_CASES
    )


def _literal_string_tuple(name: str) -> tuple[str, ...]:
    tree = ast.parse(_source(ADVERSARIAL_TEST), filename=str(ADVERSARIAL_TEST))
    for node in tree.body:
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            value_node = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            value_node = node.value
        if value_node is None:
            continue
        value = ast.literal_eval(value_node)
        assert isinstance(value, tuple)
        assert all(isinstance(item, str) for item in value)
        return value
    raise AssertionError(f"PLC9B literal string tuple is missing: {name}")


def _literal_manifest_cases(name: str) -> set[str]:
    return set(_literal_string_tuple(name))


def _implemented_b1_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B1_MANIFEST_CASES")


def _implemented_b2_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B2_MANIFEST_CASES")


def _implemented_b2h_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B2H_MANIFEST_CASES")


def _implemented_b2i_windows_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B2I_WINDOWS_MANIFEST_CASES")


def _implemented_b2j_recovery_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B2J_RECOVERY_MANIFEST_CASES")


def _implemented_b2k_hardlink_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B2K_HARDLINK_MANIFEST_CASES")


def _implemented_b3d_recovery_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B3D_RECOVERY_MANIFEST_CASES")


def _implemented_b3d_limit_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B3D_LIMIT_MANIFEST_CASES")


def _implemented_b3d_integrity_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B3D_INTEGRITY_MANIFEST_CASES")


def _implemented_b3e_pin_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B3E_PIN_MANIFEST_CASES")


def _implemented_b3e_staging_set_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B3E_STAGING_SET_MANIFEST_CASES")


def _implemented_b3e3c1_posix_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B3E3C1_POSIX_MANIFEST_CASES")


def _implemented_b3e3c2_windows_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B3E3C2_WINDOWS_MANIFEST_CASES")


def _implemented_b3e3c3_settlement_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B3E3C3_SETTLEMENT_MANIFEST_CASES")


def _implemented_b4a_commit_admission_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B4A_COMMIT_ADMISSION_MANIFEST_CASES")


def _implemented_b4b_retention_handoff_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B4B_RETENTION_HANDOFF_MANIFEST_CASES")


def _implemented_b4c0_epoch_admission_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B4C0_EPOCH_ADMISSION_MANIFEST_CASES")


def _implemented_b4c1_posix_epoch_cutover_manifest_cases() -> set[str]:
    return _literal_manifest_cases(
        "IMPLEMENTED_B4C1_POSIX_EPOCH_CUTOVER_MANIFEST_CASES"
    )


def _implemented_b4c2_windows_epoch_cutover_manifest_cases() -> set[str]:
    return _literal_manifest_cases(
        "IMPLEMENTED_B4C2_WINDOWS_EPOCH_CUTOVER_MANIFEST_CASES"
    )


def _implemented_b4c3c_linux_offline_restore_manifest_cases() -> set[str]:
    return _literal_manifest_cases(
        "IMPLEMENTED_B4C3C_LINUX_OFFLINE_RESTORE_MANIFEST_CASES"
    )


def _implemented_b4c5_windows_offline_restore_manifest_cases() -> set[str]:
    return _literal_manifest_cases(
        "IMPLEMENTED_B4C5_WINDOWS_OFFLINE_RESTORE_MANIFEST_CASES"
    )


def _implemented_b4c4d_linux_adoption_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B4C4D_LINUX_ADOPTION_MANIFEST_CASES")


def _implemented_b4c4e_linux_adoption_failure_manifest_cases() -> set[str]:
    return _literal_manifest_cases(
        "IMPLEMENTED_B4C4E_LINUX_ADOPTION_FAILURE_MANIFEST_CASES"
    )


def _implemented_b4c4f_linux_adoption_committed_crash_manifest_cases() -> set[str]:
    return _literal_manifest_cases(
        "IMPLEMENTED_B4C4F_LINUX_ADOPTION_COMMITTED_CRASH_MANIFEST_CASES"
    )


def _implemented_b4c4g_linux_adoption_precommit_crash_manifest_cases() -> set[str]:
    return _literal_manifest_cases(
        "IMPLEMENTED_B4C4G_LINUX_ADOPTION_PRECOMMIT_CRASH_MANIFEST_CASES"
    )


def _implemented_b4d_state_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B4D_STATE_MANIFEST_CASES")


def _implemented_b4d_linux_pipeline_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B4D_LINUX_PIPELINE_MANIFEST_CASES")


def _implemented_b5_routing_manifest_cases() -> set[str]:
    return _literal_manifest_cases("IMPLEMENTED_B5_ROUTING_MANIFEST_CASES")


def test_plc9b4d_contract_freezes_recovery_state_and_noexec_scope() -> None:
    contract = _source(CONTRACT)

    assert "## PLC9B4d Accepted Recovery, State, And No-Execution Closure" in contract
    assert "Linux adversarial manifest from 98 to 112 nodes" in contract
    assert "before `transaction_pinned`" in contract
    assert "Subprocess, import-side" in contract
    assert "greater fenced attempt epoch" in contract


def _journal_effect_policy() -> list[tuple[str, str, str]]:
    contract = _source(CONTRACT)
    block = contract.split("<!-- plc9b-journal-effect-policy:start -->", 1)[1]
    block = block.split("<!-- plc9b-journal-effect-policy:end -->", 1)[0]
    policy: list[tuple[str, str, str]] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line in {
            "```text",
            "```",
            "selector | journal_domain | journal_transition",
        }:
            continue
        selector, domain, transition = (cell.strip() for cell in line.split("|", 2))
        policy.append((selector, domain, transition))
    return policy


def _journal_policy_for(case_id: str) -> tuple[str, str]:
    for selector, domain, transition in _journal_effect_policy():
        if selector == "default":
            return domain, transition
        if selector.endswith("*") and case_id.startswith(selector[:-1]):
            return domain, transition
        if selector == case_id:
            return domain, transition
    raise AssertionError(f"no journal policy for {case_id}")


def _journal_domain_authorities() -> dict[str, tuple[str, str, str, str]]:
    contract = _source(CONTRACT)
    block = contract.split("<!-- plc9b-journal-domain-authority:start -->", 1)[1]
    block = block.split("<!-- plc9b-journal-domain-authority:end -->", 1)[0]
    authorities: dict[str, tuple[str, str, str, str]] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line in {
            "```text",
            "```",
            "journal_domain | sole_authority | stable_journal_key | bound_or_expected_cas_value | allowed_writer_port",
        }:
            continue
        domain, authority, stable_key, bound_value, port = (
            cell.strip() for cell in line.split("|", 4)
        )
        assert domain not in authorities, domain
        authorities[domain] = (authority, stable_key, bound_value, port)
    return authorities


def _retry_policy() -> list[tuple[str, str, str, str]]:
    contract = _source(CONTRACT)
    block = contract.split("<!-- plc9b-retry-policy:start -->", 1)[1]
    block = block.split("<!-- plc9b-retry-policy:end -->", 1)[0]
    policy: list[tuple[str, str, str, str]] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line in {
            "```text",
            "```",
            "selector | retryability | retry_domain | retry_action",
        }:
            continue
        policy.append(tuple(cell.strip() for cell in line.split("|", 3)))
    return policy


def _retry_policy_for(code: str) -> tuple[str, str, str]:
    for selector, retryability, domain, action in _retry_policy():
        if selector == code or selector == "default":
            return retryability, domain, action
    raise AssertionError(f"no retry policy for {code}")


def test_plc9b_contract_is_indexed_and_freezes_dark_b1_runtime() -> None:
    contract = _source(CONTRACT)
    index = _source(INDEX)
    inventory = _source(INVENTORY)

    assert index.count("(plugin-lifecycle-plc9b-contract.md)") == 1
    assert inventory.count("(plugin-lifecycle-plc9b-contract.md)") == 1
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B1 dark Owner Kernel and the unbound" in contract
    assert "PLC9B2a/B2b/B2c/B2d/B2e safe" in contract
    assert "PLC9B2e Evidence-Driven Crash Adoption" in contract
    assert "PLC9B2g Accepted Acquisition Manifest Slice" in contract
    assert "PLC9B2h Accepted Archive And Wheel Manifest Slice" in contract
    assert "PLC9B2i Accepted Windows Archive Manifest Slice" in contract
    assert "PLC9B2j Accepted Recovery And Cleanup Manifest Slice" in contract
    assert "PLC9B2k Accepted POSIX Hardlink Normalization Slice" in contract
    assert "PLC9B3a Accepted Dark Closure-v2 Verifier Slice" in contract
    assert "PLC9B3b Accepted Durable Closure Inputs" in contract
    assert "PLC9B3c Accepted Recursive Closure Builder" in contract
    assert "PLC9B3d-1 Accepted Durable Closure Recovery" in contract
    assert "PLC9B3d-2a Accepted Composed Closure Limits" in contract
    assert "PLC9B3d-2b Accepted Composed Closure Integrity" in contract
    assert "PLC9B3e-1 Accepted Typed Commit Records" in contract
    assert "PLC9B3e-3a Accepted Staging And Atomic Set Contracts" in contract
    assert "PLC9B3e-3b Accepted Staging And Set Runtime" in contract
    assert "PLC9B3e-3c0 Accepted Verified-Tree Transfer Contracts" in contract
    assert "PLC9B3e-3c1 Accepted POSIX Verified-Tree Materialization" in contract
    assert "PLC9B3e-2a Accepted Transaction-Pin Contract" in contract
    assert "Harness Quality run `33505702666`" in contract
    assert "Linux\nharness job `99849101216`" in contract
    assert "(ID\n`9799493328`)" in contract
    assert (
        "1022791049963c23171204823fdae22d4d70f1f6a06d505a8d837f2aef426b8d" in contract
    )
    assert "Harness Quality run `33501681463`" in contract
    assert "Linux\nharness job `99836237482`" in contract
    assert "(ID\n`9797945496`)" in contract
    assert (
        "66e889f7c79ad5eaf576cc0107c6438bc4e3d8aa71e8a89c009fd1e1fe2b65ee" in contract
    )
    assert "Harness Quality run `33497159996`" in contract
    assert "Linux harness job `99821888267`" in contract
    assert "Harness Quality run `33493714647`" in contract
    assert "Artifact `plc9b-linux-native-pytest-report` (ID `9794816942`)" in (
        " ".join(contract.split())
    )
    assert "Harness Quality run `33492402119`" in contract
    assert "Artifact `plc9b-linux-native-pytest-report` (ID `9794291799`)" in (contract)
    assert "Windows Shell Compatibility run `33490630717`" in contract
    assert "Artifact `windows-shell-pytest-reports` (ID `9793609340`)" in contract
    assert "Harness Quality run `33489524268`" in contract
    assert "Harness Quality run `33487861156`" in contract
    assert "Artifact `plc9b-linux-native-pytest-report` (ID `9792500305`)" in (
        " ".join(contract.split())
    )
    assert "Artifact `plc9b-linux-native-pytest-report` (ID `9793161479`)" in (
        " ".join(contract.split())
    )
    assert "without calling Source Authority again" in contract
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

    assert len(documented) == 110
    assert sum(documented.values()) == 163
    assert actual == documented
    assert "test_plc9_freezes_named_package_lifecycle_sites_and_occurrences" in (
        _source(BASELINE_TEST)
    )


def test_plc9b_effect_inventory_freezes_owner_and_bypass_capabilities() -> None:
    inventory = _source(INVENTORY)
    documented = _documented_effect_counts()
    actual = _package_effect_scope_counts()

    assert len(documented) == 141
    assert sum(documented.values()) == 157
    assert actual == documented
    assert "141 effect/capability rows\nwith 157 occurrences" in inventory
    for required in (
        (
            PACKAGE_OPERATIONS,
            "PackageOperationsRuntime._materialize_legacy",
            "materialize_remote_source",
        ),
        (
            PACKAGE_MATERIALIZER,
            "PackageMaterializer.publish_plugin_packages",
            "publish_plugin_packages",
        ),
        (
            PACKAGE_MATERIALIZER,
            "PackageMaterializer.remove_remote_source",
            "remove_remote_source",
        ),
        (
            PACKAGE_MATERIALIZER,
            "PackageMaterializer.forget_plugin_binding",
            "forget_plugin_binding",
        ),
        (
            Path("src/loushang/harness/resources/plugins/authority.py"),
            "PluginResolutionAuthority.publish_runtime",
            "publish_plugin_packages",
        ),
        (
            Path("src/loushang/harness/session/bootstrap_configuration.py"),
            "StandardAgentSessionConfigurationRuntime._package_sources",
            "PackageSourceResolver",
        ),
        (
            PACKAGE_MATERIALIZER,
            "PackageMaterializer.materialize_remote_source",
            "prepare_remote_source",
        ),
        (
            PACKAGE_MATERIALIZER,
            "PackageMaterializer.materialize_temporary_remote_source",
            "_run_backend_for_record",
        ),
        (
            PACKAGE_SOURCE_RESOLVER,
            "PackageSourceResolver.prepare_configured_remote_records",
            "prepare_remote_source",
        ),
        (
            PACKAGE_MATERIALIZER,
            "PackageMaterializer.publish_plugin_packages",
            "PluginRevisionStore.publish_all",
        ),
    ):
        assert required in documented


def test_plc9b_effect_scanner_recognizes_private_revision_store_receivers() -> None:
    tree = ast.parse(
        "owner._plugin_revision_store.publish(value)\n"
        "owner._plugin_revision_store.publish_all(values)\n"
        "owner._plugin_revision_store.reopen(ref)\n"
    )

    assert {
        token
        for node in ast.walk(tree)
        if (token := _plugin_revision_receiver_token(node)) is not None
    } == {
        "PluginRevisionStore.publish",
        "PluginRevisionStore.publish_all",
        "PluginRevisionStore.reopen",
    }


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
    assert "neutral artifact store evolution" in contract
    assert "cannot store or designate the Plugin root, commit a graph" in contract
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
        "Plugin-bound classification v1",
        "authenticated source envelope v1",
        "bounded acquisition receipt v1",
        "quarantine receipt v1",
        "verified wheel artifact v1",
        "verified closure plan v2",
        "dependency closure node v2",
        "dependency closure lock v2",
        "typed stable refs v1",
        "retention-pin receipt v1",
        "retention handoff receipt v1",
        "immutable publication receipt v1",
        "Package lifecycle status/failure v1",
    ):
        assert evidence in contract
    assert 'PLUGIN_DEPENDENCY_LOCK_FORMAT = "loushang.plugin-dependency-lock/v1"' in (
        dependencies
    )
    assert "v1 remains replay-only" in contract
    assert "never satisfies PLC9B recursive verification" in contract
    assert "no reader may decode\nv1 bytes as closure v2" in contract
    assert "unsupported future evidence version fails closed" in contract
    assert "exact typed stable refs (never live handles)" in contract
    assert "source-envelope fingerprint" in contract
    assert "acquisition-receipt fingerprint" in contract
    assert "wheel-evidence fingerprint" in contract
    assert "lowercase hexadecimal SHA-256" in contract
    assert "`sha256`, `sha384`, or\n`sha512`" in contract


def test_plc9b_transaction_never_confuses_publication_with_selection() -> None:
    contract = _source(CONTRACT)

    ordered_phases = (
        "accepted",
        "classified",
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
        "transaction_pinned",
        "staging",
        "set_published",
        "committed",
    )
    positions = [contract.index(f"  -> {phase}") for phase in ordered_phases[1:]]
    assert positions == sorted(positions)
    for boundary in (
        "Staged refs are owner-private",
        "one atomic committed-set manifest",
        "Directory existence alone is never admission",
        "Package commit-admission port is the only route",
        "expected-phase compare-and-swap",
        "A stale worker cannot append",
    ):
        assert boundary in contract


def test_plc9b_adversarial_manifest_tracks_exact_accepted_progress() -> None:
    manifest = _adversarial_manifest()
    categories = Counter(case_id.split("-", 2)[1] for case_id in manifest)
    implemented_b1 = _implemented_b1_manifest_cases()
    implemented_b2 = _implemented_b2_manifest_cases()
    implemented_b2h = _implemented_b2h_manifest_cases()
    implemented_b2i = _implemented_b2i_windows_manifest_cases()
    implemented_b2j = _implemented_b2j_recovery_manifest_cases()
    implemented_b2k = _implemented_b2k_hardlink_manifest_cases()
    implemented_b3d = _implemented_b3d_recovery_manifest_cases()
    implemented_b3d_limits = _implemented_b3d_limit_manifest_cases()
    implemented_b3d_integrity = _implemented_b3d_integrity_manifest_cases()
    implemented_b3e_pins = _implemented_b3e_pin_manifest_cases()
    implemented_b3e_staging_sets = _implemented_b3e_staging_set_manifest_cases()
    implemented_b3e3c1_posix = _implemented_b3e3c1_posix_manifest_cases()
    implemented_b3e3c2_windows = _implemented_b3e3c2_windows_manifest_cases()
    implemented_b3e3c3_settlement = _implemented_b3e3c3_settlement_manifest_cases()
    implemented_b4a_admission = _implemented_b4a_commit_admission_manifest_cases()
    implemented_b4b_handoff = _implemented_b4b_retention_handoff_manifest_cases()
    implemented_b4c0_epoch = _implemented_b4c0_epoch_admission_manifest_cases()
    implemented_b4c1_posix = _implemented_b4c1_posix_epoch_cutover_manifest_cases()
    implemented_b4c2_windows = _implemented_b4c2_windows_epoch_cutover_manifest_cases()
    implemented_b4c3c_linux_restore = (
        _implemented_b4c3c_linux_offline_restore_manifest_cases()
    )
    implemented_b4c5_windows_restore = (
        _implemented_b4c5_windows_offline_restore_manifest_cases()
    )
    implemented_b4c4d_linux_adoption = (
        _implemented_b4c4d_linux_adoption_manifest_cases()
    )
    implemented_b4c4e_linux_adoption_failure = (
        _implemented_b4c4e_linux_adoption_failure_manifest_cases()
    )
    implemented_b4c4f_linux_adoption_committed_crash = (
        _implemented_b4c4f_linux_adoption_committed_crash_manifest_cases()
    )
    implemented_b4c4g_linux_adoption_precommit_crash = (
        _implemented_b4c4g_linux_adoption_precommit_crash_manifest_cases()
    )
    implemented_b4d_state = _implemented_b4d_state_manifest_cases()
    implemented_b4d_linux_pipeline = _implemented_b4d_linux_pipeline_manifest_cases()
    implemented_b5_routing = _implemented_b5_routing_manifest_cases()
    implemented = (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
        | implemented_b3e_pins
        | implemented_b3e_staging_sets
        | implemented_b3e3c1_posix
        | implemented_b3e3c2_windows
        | implemented_b3e3c3_settlement
        | implemented_b4a_admission
        | implemented_b4b_handoff
        | implemented_b4c0_epoch
        | implemented_b4c1_posix
        | implemented_b4c2_windows
        | implemented_b4c3c_linux_restore
        | implemented_b4c5_windows_restore
        | implemented_b4c4d_linux_adoption
        | implemented_b4c4e_linux_adoption_failure
        | implemented_b4c4f_linux_adoption_committed_crash
        | implemented_b4c4g_linux_adoption_precommit_crash
        | implemented_b4d_state
        | implemented_b4d_linux_pipeline
        | implemented_b5_routing
    )

    assert len(manifest) == 127
    assert categories == EXPECTED_MANIFEST_CATEGORY_COUNTS
    for case_id, row in manifest.items():
        assert row["platform"] in ALLOWED_PLATFORMS, case_id
        assert row["barrier"], case_id
        assert row["fixture"], case_id
        assert row["code"], case_id
        assert "@" in row["disposition"], case_id
        oracles = set(row["oracles"].split(";"))
        assert oracles <= ALLOWED_ORACLES, case_id
        assert oracles, case_id
        assert row["test_node"].endswith(f"[{case_id}]"), case_id
        assert row["status"] in {"planned", "implemented"}, case_id
        assert "#plc9b-" in row["workflow"], case_id
        if row["platform"] == "windows-native":
            assert row["workflow"].startswith("windows-shell-compatibility.yml"), (
                case_id
            )
            assert "no_skip" in oracles, case_id
        elif row["platform"] == "posix-native":
            assert row["workflow"].startswith("harness-quality.yml"), case_id
            assert "no_skip" in oracles, case_id
    assert {
        case_id for case_id, row in manifest.items() if row["status"] == "implemented"
    } == implemented
    assert implemented_b1 == {
        "B-CLASS-PLUGIN",
        "B-CLASS-NONPLUGIN",
        "B-CLASS-INDETERMINATE",
        "B-CLASS-SPOOF",
        "B-CRASH-ACCEPTED",
        "B-CRASH-CLASSIFIED",
        "B-CONCUR-CONFLICT",
        "B-ENTRY-DISABLED",
    }
    assert implemented_b2 == {
        "B-ACQ-AUTH",
        "B-ACQ-PROVENANCE",
        "B-ACQ-BYTES",
        "B-ACQ-REDIRECT",
        "B-ACQ-TIMEOUT",
        "B-ACQ-DIGEST",
    }
    assert implemented_b1.isdisjoint(implemented_b2)
    assert implemented_b2h == {
        "B-ARCH-TRUNCATED",
        "B-ARCH-HEADERS",
        "B-ARCH-OVERLAP",
        "B-ARCH-COMPRESSION",
        "B-ARCH-TRAILING",
        "B-PATH-ABSOLUTE",
        "B-PATH-TRAVERSAL",
        "B-PATH-EMPTY",
        "B-PATH-COLLISION-SEP",
        "B-PATH-COLLISION-UNICODE",
        "B-TYPE-SYMLINK",
        "B-TYPE-DEVICE",
        "B-TYPE-SOCKET",
        "B-TYPE-FIFO",
        "B-LIMIT-ENTRY",
        "B-LIMIT-MEMORY",
        "B-LIMIT-CPU",
        "B-WHEEL-SDIST",
        "B-WHEEL-ZIP",
        "B-WHEEL-TAGS",
        "B-WHEEL-METADATA",
        "B-WHEEL-RECORD-HASH",
        "B-WHEEL-RECORD-SET",
        "B-WHEEL-RECORD-ALGO",
    }
    assert (implemented_b1 | implemented_b2).isdisjoint(implemented_b2h)
    assert implemented_b2i == {
        "B-PATH-WIN-ROOT",
        "B-PATH-WIN-ADS",
        "B-PATH-WIN-RESERVED",
        "B-PATH-WIN-TRAILING",
        "B-PATH-COLLISION-CASE",
        "B-TYPE-REPARSE",
        "B-TYPE-JUNCTION",
    }
    assert (implemented_b1 | implemented_b2 | implemented_b2h).isdisjoint(
        implemented_b2i
    )
    assert implemented_b2j == {
        "B-ACQ-IDENTITY",
        "B-CRASH-ACQUIRING",
        "B-CRASH-ACQUIRED",
        "B-CRASH-INSPECTING",
        "B-CRASH-EXTRACTED",
        "B-STATE-REJECT-CLEANUP",
    }
    assert (
        implemented_b1 | implemented_b2 | implemented_b2h | implemented_b2i
    ).isdisjoint(implemented_b2j)
    assert implemented_b2k == {"B-TYPE-HARDLINK"}
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
    ).isdisjoint(implemented_b2k)
    assert implemented_b3d == {
        "B-CRASH-RESOLVING",
        "B-CRASH-CLOSURE",
    }
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
    ).isdisjoint(implemented_b3d)
    assert implemented_b3d_limits == {
        "B-LIMIT-GRAPH",
        "B-LIMIT-SOLVER",
        "B-LIMIT-REQUESTS",
    }
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
    ).isdisjoint(implemented_b3d_limits)
    assert implemented_b3d_integrity == {
        "B-CLOSURE-MISSING",
        "B-CLOSURE-DIGEST",
        "B-CLOSURE-ORIGIN",
        "B-CLOSURE-MARKER",
        "B-CLOSURE-NAME",
        "B-CLOSURE-CYCLE",
        "B-CLOSURE-V1",
    }
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
    ).isdisjoint(implemented_b3d_integrity)
    assert implemented_b3e_pins == {"B-CRASH-PINNED"}
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
    ).isdisjoint(implemented_b3e_pins)
    assert implemented_b3e_staging_sets == {
        "B-CRASH-STAGING",
        "B-CRASH-SET",
    }
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
        | implemented_b3e_pins
    ).isdisjoint(implemented_b3e_staging_sets)
    assert implemented_b3e3c1_posix == PLC9B3E3C1_POSIX_CASES
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
        | implemented_b3e_pins
        | implemented_b3e_staging_sets
    ).isdisjoint(implemented_b3e3c1_posix)
    assert implemented_b3e3c2_windows == PLC9B3E3C2_WINDOWS_CASES
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
        | implemented_b3e_pins
        | implemented_b3e_staging_sets
        | implemented_b3e3c1_posix
    ).isdisjoint(implemented_b3e3c2_windows)
    assert implemented_b3e3c3_settlement == PLC9B3E3C3_SETTLEMENT_CASES
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
        | implemented_b3e_pins
        | implemented_b3e_staging_sets
        | implemented_b3e3c1_posix
        | implemented_b3e3c2_windows
    ).isdisjoint(implemented_b3e3c3_settlement)
    assert implemented_b4a_admission == PLC9B4A_COMMIT_ADMISSION_CASES
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
        | implemented_b3e_pins
        | implemented_b3e_staging_sets
        | implemented_b3e3c1_posix
        | implemented_b3e3c2_windows
        | implemented_b3e3c3_settlement
    ).isdisjoint(implemented_b4a_admission)
    assert implemented_b4b_handoff == PLC9B4B_RETENTION_HANDOFF_CASES
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
        | implemented_b3e_pins
        | implemented_b3e_staging_sets
        | implemented_b3e3c1_posix
        | implemented_b3e3c2_windows
        | implemented_b3e3c3_settlement
        | implemented_b4a_admission
    ).isdisjoint(implemented_b4b_handoff)
    assert implemented_b4c0_epoch == PLC9B4C0_EPOCH_ADMISSION_CASES
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
        | implemented_b3e_pins
        | implemented_b3e_staging_sets
        | implemented_b3e3c1_posix
        | implemented_b3e3c2_windows
        | implemented_b3e3c3_settlement
        | implemented_b4a_admission
        | implemented_b4b_handoff
    ).isdisjoint(implemented_b4c0_epoch)
    assert implemented_b4c1_posix == PLC9B4C1_POSIX_EPOCH_CUTOVER_CASES
    assert (
        implemented_b1
        | implemented_b2
        | implemented_b2h
        | implemented_b2i
        | implemented_b2j
        | implemented_b2k
        | implemented_b3d
        | implemented_b3d_limits
        | implemented_b3d_integrity
        | implemented_b3e_pins
        | implemented_b3e_staging_sets
        | implemented_b3e3c1_posix
        | implemented_b3e3c2_windows
        | implemented_b3e3c3_settlement
        | implemented_b4a_admission
        | implemented_b4b_handoff
        | implemented_b4c0_epoch
    ).isdisjoint(implemented_b4c1_posix)
    separator = manifest["B-PATH-COLLISION-SEP"]
    assert separator["fixture"] == "separator_ambiguous_path"
    assert separator["code"] == "package_archive_path_rejected"
    metadata = manifest["B-WHEEL-METADATA"]
    assert metadata["barrier"] == "inspecting"
    assert metadata["disposition"] == "rejected@inspecting"
    hardlink = manifest["B-TYPE-HARDLINK"]
    assert hardlink["platform"] == "posix-native"
    assert hardlink["barrier"] == "extracted"
    assert hardlink["fixture"] == "hardlinked_source_normalized"
    assert hardlink["code"] == "ok"
    assert hardlink["disposition"] == "extracted@independent_regular_files"
    assert hardlink["status"] == "implemented"
    assert implemented_b4c3c_linux_restore == (PLC9B4C3C_LINUX_OFFLINE_RESTORE_CASES)
    assert (implemented - implemented_b4c3c_linux_restore).isdisjoint(
        implemented_b4c3c_linux_restore
    )
    assert implemented_b4c5_windows_restore == (
        PLC9B4C5_WINDOWS_OFFLINE_RESTORE_CASES
    )
    assert (implemented - implemented_b4c5_windows_restore).isdisjoint(
        implemented_b4c5_windows_restore
    )
    assert implemented_b4c4d_linux_adoption == PLC9B4C4D_LINUX_ADOPTION_CASES
    assert (implemented - implemented_b4c4d_linux_adoption).isdisjoint(
        implemented_b4c4d_linux_adoption
    )
    assert (
        implemented_b4c4e_linux_adoption_failure
        == PLC9B4C4E_LINUX_ADOPTION_FAILURE_CASES
    )
    assert (implemented - implemented_b4c4e_linux_adoption_failure).isdisjoint(
        implemented_b4c4e_linux_adoption_failure
    )
    assert (
        implemented_b4c4f_linux_adoption_committed_crash
        == PLC9B4C4F_LINUX_ADOPTION_COMMITTED_CRASH_CASES
    )
    assert (implemented - implemented_b4c4f_linux_adoption_committed_crash).isdisjoint(
        implemented_b4c4f_linux_adoption_committed_crash
    )
    assert (
        implemented_b4c4g_linux_adoption_precommit_crash
        == PLC9B4C4G_LINUX_ADOPTION_PRECOMMIT_CRASH_CASES
    )
    assert (implemented - implemented_b4c4g_linux_adoption_precommit_crash).isdisjoint(
        implemented_b4c4g_linux_adoption_precommit_crash
    )
    assert implemented_b5_routing == {
        "B-ENTRY-CLI",
        "B-ENTRY-RPC",
        "B-ENTRY-SESSION",
        "B-ENTRY-STARTUP",
        "B-ENTRY-OPERATIONS",
        "B-ENTRY-MATERIALIZER",
        "B-ENTRY-PUBLISH",
    }
    assert (implemented - implemented_b5_routing).isdisjoint(implemented_b5_routing)
    assert len(manifest) - len(implemented) == 0
    workflow = _source(HARNESS_WORKFLOW)
    assert "PLC9B Linux native adversarial gate (plc9b-linux-native)" in workflow
    assert "tests/harness/resources/packages/test_plc9b_adversarial.py" in workflow
    assert "verify_pytest_xml.py" in workflow


def test_plc9b_manifest_separates_caller_response_from_journal_effect() -> None:
    manifest = _adversarial_manifest()
    policy = _journal_effect_policy()

    assert policy[-1] == (
        "default",
        "operation",
        "append_once:response_state_then_no_append",
    )
    assert "caller-visible response outcome" in _source(CONTRACT)
    resolved = {case_id: _journal_policy_for(case_id) for case_id in manifest}
    expected_domains = {
        "operation",
        "attempt",
        "handoff_attempt",
        "handoff",
        "cleanup",
        "epoch",
        "none",
    }
    assert {domain for domain, _transition in resolved.values()} <= expected_domains
    authorities = _journal_domain_authorities()
    assert authorities == {
        "operation": (
            "PLC9B Package lifecycle owner",
            "operation_id",
            "request_fingerprint+prior_journal_revision",
            "PackageOperationJournalCAS",
        ),
        "attempt": (
            "PLC9B Package lifecycle owner",
            "operation_id+attempt_epoch",
            "parent_request_fingerprint+parent_journal_revision",
            "PackageAttemptJournalCAS",
        ),
        "handoff_attempt": (
            "retention-handoff owner over PluginPackageLifecycleLedger",
            "handoff_id+attempt_epoch",
            "parent_receipt_fingerprint+parent_handoff_revision",
            "RetentionHandoffJournalCAS",
        ),
        "handoff": (
            "retention-handoff owner over PluginPackageLifecycleLedger",
            "handoff_id",
            "receipt_fingerprint+prior_handoff_revision",
            "RetentionHandoffJournalCAS",
        ),
        "cleanup": (
            "PLC9B Package lifecycle owner",
            "quarantine_tombstone_id",
            "cleanup_revision",
            "PackageCleanupJournalCAS",
        ),
        "epoch": (
            "Package epoch cutover coordinator in Package lifecycle composition",
            "store_root_identity",
            "current_epoch+prior_fence_revision",
            "PackageEpochJournalCAS",
        ),
        "none": ("no authority", "no journal", "no value", "no writer"),
    }
    assert set(authorities) == expected_domains
    for no_append in (
        "B-PUB-UNCOMMITTED",
        "B-ADMISSION-DEPENDENCY",
        "B-ADMISSION-WRONG-SET",
        "B-ADMISSION-WRONG-SCOPE",
        "B-ADMISSION-WRONG-PLUGIN",
        "B-CONCUR-CONFLICT",
        "B-CONCUR-STALE",
        "B-HANDOFF-STALE-RECEIPT",
        "B-ENTRY-PUBLISH",
        "B-ENTRY-DISABLED",
        "B-COMPAT-EPOCH",
        "B-COMPAT-MIXED",
        "B-COMPAT-PREFENCE-LIVE-POSIX",
        "B-COMPAT-PREFENCE-LIVE-WINDOWS",
        "B-COMPAT-OFFLINE-RESTORE-POSIX",
        "B-COMPAT-OFFLINE-RESTORE-WINDOWS",
    ):
        assert resolved[no_append] == ("none", "no_append:unchanged")
    cleanup = manifest["B-STATE-REJECT-CLEANUP"]
    assert cleanup["code"] == "package_quarantine_cleanup_retryable"
    assert resolved["B-STATE-REJECT-CLEANUP"] == (
        "cleanup",
        "append_once:cleanup_retryable_then_no_append",
    )
    assert resolved["B-HANDOFF-DESIRED-REJECT"] == (
        "handoff",
        "append_once:aborted_then_no_append",
    )


def test_plc9b_manifest_freezes_legal_response_code_and_effect_combinations() -> None:
    manifest = _adversarial_manifest()
    legal_states = {
        "operation": {
            "accepted",
            "classified",
            "acquiring",
            "acquired",
            "inspecting",
            "extracted",
            "resolving_closure",
            "closure_verified",
            "transaction_pinned",
            "staging",
            "set_published",
            "committed",
            "rejected",
            "cancelled",
        },
        "attempt": {"retryable_failure"},
        "handoff_attempt": {"retryable_failure"},
        "handoff": {"aborted", "settled"},
        "cleanup": {"cleanup_retryable"},
        "epoch": {"epoch_fenced"},
    }

    for case_id, row in manifest.items():
        response, _stage = row["disposition"].split("@", 1)
        domain, transition = _journal_policy_for(case_id)
        if row["code"] == "ok":
            assert response in {
                "accepted",
                "classified",
                "extracted",
                "committed",
                "settled",
            }
        elif row["code"] == "package_operation_cancelled":
            assert response == "cancelled"
        elif row["code"] in {
            "package_operation_interrupted",
            "package_retention_handoff_interrupted",
        }:
            assert response == "retryable_failure"
        elif row["code"] in {
            "package_acquisition_limit_exceeded",
            "package_operation_timed_out",
        }:
            assert response == "retryable_failure"
        else:
            assert response == "rejected"

        if domain == "none":
            assert transition == "no_append:unchanged"
            continue
        assert transition.startswith("append_once:")
        assert transition.endswith("_then_no_append")
        appended_state = transition.removeprefix("append_once:").removesuffix(
            "_then_no_append"
        )
        if appended_state == "response_state":
            appended_state = response
        assert appended_state in legal_states[domain], (case_id, domain, transition)


def test_plc9b_retry_policy_routes_only_to_the_typed_subject_domain() -> None:
    manifest = _adversarial_manifest()
    policy = _retry_policy()

    assert policy[-1] == ("default", "false", "none", "none")
    selectors = [selector for selector, *_rest in policy]
    assert len(selectors) == len(set(selectors))
    assert selectors.count("default") == 1
    assert _retry_policy_for("package_operation_interrupted") == (
        "true",
        "operation",
        "retry",
    )
    assert _retry_policy_for("package_retention_handoff_interrupted") == (
        "true",
        "handoff",
        "retry",
    )
    assert _retry_policy_for("package_quarantine_cleanup_retryable") == (
        "true",
        "cleanup",
        "repair",
    )
    assert _retry_policy_for("package_retention_handoff_stale") == (
        "false",
        "none",
        "none",
    )
    for case_id, row in manifest.items():
        response = row["disposition"].split("@", 1)[0]
        retryability, domain, _action = _retry_policy_for(row["code"])
        if response == "retryable_failure":
            assert retryability == "true" or retryability.startswith("conditional:")
            expected_domain = (
                "handoff"
                if row["code"] == "package_retention_handoff_interrupted"
                else "operation"
            )
            assert domain == expected_domain, case_id


def test_plc9b_freezes_closure_admission_and_lock_boundaries() -> None:
    contract = _source(CONTRACT)
    normalized = " ".join(contract.split())

    for closure_boundary in (
        "`closure_verified` freezes the complete `VerifiedClosurePlanV2`",
        "without pretending stable refs exist",
        "constructs every immutable closure node",
        "Digested evidence is never patched in place",
    ):
        assert closure_boundary in normalized
    for physical_owner_boundary in (
        "There is no second physical root publication",
        "exactly one `PluginRevisionRefV1`",
        "every dependency node contains exactly one `VerifiedArtifactRefV1`",
        "PLC9D later owns pin-authorized physical deletion",
    ):
        assert physical_owner_boundary in normalized
    for admission_binding in (
        "request and operation fingerprints",
        "Product/scope",
        "Installation/Plugin identities",
        "designated-root role/ref",
        "exact committed-set identity",
        "closure/set digest",
        "A dependency, a ref from another set, or a wrong operation, scope, or Plugin",
    ):
        assert admission_binding in normalized
    for lock_boundary in (
        "No owner holds its lock while calling another owner",
        "No cross-owner locks are nested",
        "calls stores in canonical `(store identity, typed ref)` order",
        "committed-set CAS",
        "operation `committed` CAS",
        "It never calls the desired application",
        "later management command first passes commit admission",
        "retention owner again to record `desired_committed` and `settled`",
    ):
        assert lock_boundary in normalized


def test_plc9b_manifest_covers_every_route_and_native_platform_evidence() -> None:
    manifest = _adversarial_manifest()
    contract = _source(CONTRACT)

    for route_case in (
        "B-ENTRY-CLI",
        "B-ENTRY-RPC",
        "B-ENTRY-SESSION",
        "B-ENTRY-STARTUP",
        "B-ENTRY-OPERATIONS",
        "B-ENTRY-MATERIALIZER",
        "B-ENTRY-PUBLISH",
        "B-ENTRY-DISABLED",
    ):
        assert route_case in manifest
    for phase_case in (
        "B-CRASH-ACCEPTED",
        "B-CRASH-CLASSIFIED",
        "B-CRASH-ACQUIRING",
        "B-CRASH-ACQUIRED",
        "B-CRASH-INSPECTING",
        "B-CRASH-EXTRACTED",
        "B-CRASH-RESOLVING",
        "B-CRASH-CLOSURE",
        "B-CRASH-PINNED",
        "B-CRASH-STAGING",
        "B-CRASH-SET",
        "B-CRASH-COMMITTED",
    ):
        assert phase_case in manifest
    native_publication_contract = {
        "B-PUB-POSIX-ROOT-SWAP": (
            "posix-native",
            "root_rename_replace_swap",
            "package_publication_root_untrusted",
            "rejected@staging",
            {
                "no_outside_write",
                "no_publication",
                "pin_visible",
                "handle_released",
                "no_skip",
            },
        ),
        "B-PUB-POSIX-ANCESTOR-SWAP": (
            "posix-native",
            "ancestor_rename_replace_swap",
            "package_publication_root_untrusted",
            "rejected@staging",
            {
                "no_outside_write",
                "no_publication",
                "pin_visible",
                "handle_released",
                "no_skip",
            },
        ),
        "B-PUB-POSIX-HANDLE-SUCCESS": (
            "posix-native",
            "successful_native_handle_lifecycle",
            "ok",
            "committed@committed",
            {"same_receipt", "pin_visible", "handle_released", "no_skip"},
        ),
        "B-PUB-POSIX-HANDLE-REJECT": (
            "posix-native",
            "rejected_native_handle_lifecycle",
            "package_publication_root_untrusted",
            "rejected@staging",
            {
                "no_outside_write",
                "no_publication",
                "pin_visible",
                "handle_released",
                "no_skip",
            },
        ),
        "B-PUB-SWAP-WINDOWS": (
            "windows-native",
            "ancestor_or_entry_reparse_swap",
            "package_publication_root_untrusted",
            "rejected@staging",
            {
                "no_outside_write",
                "no_publication",
                "pin_visible",
                "handle_released",
                "no_skip",
            },
        ),
        "B-PUB-WIN-ROOT-ABA": (
            "windows-native",
            "root_rename_replace_aba",
            "package_publication_root_untrusted",
            "rejected@staging",
            {
                "no_outside_write",
                "no_publication",
                "pin_visible",
                "handle_released",
                "no_skip",
            },
        ),
        "B-PUB-WIN-ANCESTOR-ABA": (
            "windows-native",
            "ancestor_junction_reparse_aba",
            "package_publication_root_untrusted",
            "rejected@staging",
            {
                "no_outside_write",
                "no_publication",
                "pin_visible",
                "handle_released",
                "no_skip",
            },
        ),
        "B-PUB-WIN-HANDLE-SUCCESS": (
            "windows-native",
            "successful_native_handle_lifecycle",
            "ok",
            "committed@committed",
            {"same_receipt", "pin_visible", "handle_released", "no_skip"},
        ),
        "B-PUB-WIN-HANDLE-REJECT": (
            "windows-native",
            "rejected_native_handle_lifecycle",
            "package_publication_root_untrusted",
            "rejected@staging",
            {
                "no_outside_write",
                "no_publication",
                "pin_visible",
                "handle_released",
                "no_skip",
            },
        ),
    }
    native_publication_barriers = {
        "B-PUB-POSIX-ROOT-SWAP": "staging",
        "B-PUB-POSIX-ANCESTOR-SWAP": "staging",
        "B-PUB-POSIX-HANDLE-SUCCESS": "committed",
        "B-PUB-POSIX-HANDLE-REJECT": "rejected",
        "B-PUB-SWAP-WINDOWS": "staging",
        "B-PUB-WIN-ROOT-ABA": "staging",
        "B-PUB-WIN-ANCESTOR-ABA": "staging",
        "B-PUB-WIN-HANDLE-SUCCESS": "committed",
        "B-PUB-WIN-HANDLE-REJECT": "rejected",
    }
    assert set(native_publication_contract) == set(native_publication_barriers)
    for case_id, expected in native_publication_contract.items():
        platform, fixture, code, disposition, expected_oracles = expected
        row = manifest[case_id]
        assert (
            row["barrier"],
            row["platform"],
            row["fixture"],
            row["code"],
            row["disposition"],
        ) == (
            native_publication_barriers[case_id],
            platform,
            fixture,
            code,
            disposition,
        )
        assert set(row["oracles"].split(";")) == expected_oracles
        expected_workflow = (
            "windows-shell-compatibility.yml#plc9b-windows-native"
            if platform == "windows-native"
            else "harness-quality.yml#plc9b-linux-native"
        )
        assert row["workflow"] == expected_workflow
    handle_probe_contract = _source(CONTRACT)
    for probe in ("rename/delete/open probes", "garbage collection", "process exit"):
        assert probe in handle_probe_contract
    for native_case in (
        "B-COMPAT-CUTOVER-POSIX",
        "B-COMPAT-CUTOVER-WINDOWS",
        "B-COMPAT-PREFENCE-LIVE-POSIX",
        "B-COMPAT-PREFENCE-LIVE-WINDOWS",
    ):
        assert native_case in manifest
        assert "no_skip" in manifest[native_case]["oracles"].split(";")
    for admission_case in (
        "B-ADMISSION-DEPENDENCY",
        "B-ADMISSION-WRONG-SET",
        "B-ADMISSION-WRONG-REQUEST",
        "B-ADMISSION-WRONG-OPERATION",
        "B-ADMISSION-WRONG-SCOPE",
        "B-ADMISSION-WRONG-PLUGIN",
        "B-ADMISSION-DIGEST-TAMPER",
    ):
        assert admission_case in manifest
        assert manifest[admission_case]["code"] == ("package_commit_admission_denied")
        assert {"no_reopen", "no_handle_issued"} <= set(
            manifest[admission_case]["oracles"].split(";")
        )
    assert {"no_reopen", "no_handle_issued"} <= set(
        manifest["B-PUB-UNCOMMITTED"]["oracles"].split(";")
    )
    for handoff_case in (
        "B-HANDOFF-BEFORE-DESIRED",
        "B-HANDOFF-AFTER-DESIRED",
        "B-HANDOFF-AFTER-SETTLEMENT",
        "B-HANDOFF-DESIRED-REJECT",
        "B-HANDOFF-STALE-RECEIPT",
        "B-HANDOFF-CONCURRENT-REPLAY",
    ):
        assert handoff_case in manifest
        assert "exact_pin_set" in manifest[handoff_case]["oracles"].split(";")
        assert "no_zero_pin" in manifest[handoff_case]["oracles"].split(";")
    for settled_case in (
        "B-HANDOFF-AFTER-SETTLEMENT",
        "B-HANDOFF-CONCURRENT-REPLAY",
    ):
        assert "transaction_pin_released" in manifest[settled_case]["oracles"].split(
            ";"
        )
    assert "dependency_pins_released" in manifest["B-HANDOFF-DESIRED-REJECT"][
        "oracles"
    ].split(";")
    unchanged = {
        "legacy_snapshot_exact",
        "desired_unchanged",
        "instance_unchanged",
        "binding_unchanged",
        "enablement_unchanged",
    }
    compatibility_contract = {
        "B-COMPAT-OFFLINE-RESTORE-POSIX": (
            "posix-native",
            "accepted",
            "complete_pre_b_restore_exclusive_old_runtime",
            "ok",
            "accepted@offline_restore",
            {
                "single_owner",
                "legacy_snapshot_exact",
                "b_namespace_unreachable",
                "no_peer_fallback",
                "no_skip",
            },
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-OFFLINE-RESTORE-WINDOWS": (
            "windows-native",
            "accepted",
            "complete_pre_b_restore_exclusive_old_runtime",
            "ok",
            "accepted@offline_restore",
            {
                "single_owner",
                "legacy_snapshot_exact",
                "b_namespace_unreachable",
                "no_peer_fallback",
                "no_skip",
            },
            "windows-shell-compatibility.yml#plc9b-windows-native",
        ),
        "B-COMPAT-ADOPT": (
            "posix-native",
            "committed",
            "authenticated_legacy_reacquisition",
            "ok",
            "committed@committed",
            unchanged | {"same_receipt", "pin_visible", "no_skip"},
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-ADOPT-UNAUTHORIZED": (
            "posix-native",
            "acquiring",
            "legacy_reacquisition_unauthorized",
            "package_source_unauthorized",
            "rejected@acquiring",
            unchanged | {"no_publication", "no_peer_fallback", "no_skip"},
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-ADOPT-UNAVAILABLE": (
            "posix-native",
            "acquiring",
            "registry_network_temporarily_unavailable",
            "package_operation_timed_out",
            "retryable_failure@acquiring",
            unchanged
            | {
                "bounded_residue",
                "no_publication",
                "no_extra_network",
                "no_peer_fallback",
                "no_skip",
            },
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-ADOPT-CRASH": (
            "posix-native",
            "each_precommit_phase",
            "adoption_process_crash_and_resume",
            "ok",
            "committed@committed",
            unchanged | {"same_receipt", "bounded_residue", "no_skip"},
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-ADOPT-CRASH-AFTER-COMMITTED": (
            "posix-native",
            "committed",
            "adoption_crash_after_committed_edge",
            "ok",
            "committed@committed",
            unchanged | {"same_receipt", "pin_visible", "no_skip"},
            "harness-quality.yml#plc9b-linux-native",
        ),
    }
    for case_id, expected in compatibility_contract.items():
        row = manifest[case_id]
        platform, barrier, fixture, code, disposition, oracles, workflow = expected
        assert (
            row["platform"],
            row["barrier"],
            row["fixture"],
            row["code"],
            row["disposition"],
            set(row["oracles"].split(";")),
            row["workflow"],
        ) == (platform, barrier, fixture, code, disposition, oracles, workflow)
    assert "unsupported-host emulation is never the only evidence" in contract
    assert "Source distributions are unconditionally rejected" in contract
    assert set(manifest["B-NOEXEC-IMPORT"]["oracles"].split(";")) >= {
        "no_process",
        "no_import",
        "no_extra_network",
    }


def test_plc9b_freezes_single_classification_and_commit_admission_authorities() -> None:
    contract = _source(CONTRACT)

    for boundary in (
        "does not accept a classification result from the caller",
        "exactly one decision: `plugin_bound`, `non_plugin`, or `indeterminate`",
        "Only evidence from a separately accepted non-Plugin authority",
        "It never enters the legacy\ninstaller",
        "rechecks the\nclassification fingerprint before acquisition and before committed-set",
        "Package commit-admission port",
        "current digest/source-only `reopen`",
    ):
        assert boundary in contract


def test_plc9b_freezes_status_redaction_and_transport_conformance() -> None:
    contract = _source(CONTRACT)

    for field in (
        "`code`",
        "`stage`",
        "`retryable`",
        "`retry_domain`",
        "`operator_action`",
        "`subject_kind`",
        "`subject_id`",
        "`operation_id`",
        "`evidence_ref`",
    ):
        assert field in contract
    for action in (
        "`none`",
        "`retry`",
        "`repair`",
        "`upgrade_runtime`",
        "`offline_restore`",
        "`review_policy`",
    ):
        assert action in contract
    assert "CLI emits the code, operation id and evidence reference and exits\n`1`" in (
        contract
    )
    assert "RPC returns the record as its structured command error" in contract
    assert "Session raises one typed\nPackage lifecycle application error" in contract
    assert "Startup emits the same\ndiagnostic and aborts configuration" in contract
    for secret in (
        "authorization headers",
        "URL user-info/query/fragment",
        "private registry tokens",
    ):
        assert secret in contract


def test_plc9b_freezes_retention_transfer_and_downgrade_fence() -> None:
    contract = _source(CONTRACT)
    normalized = " ".join(contract.split())

    for retention in (
        "transaction pin over the root and every dependency",
        "obtains the exact dependency pin set under the handoff identity",
        "atomically records `settled` may it release the transaction pin",
        "never creates a zero-pin gap",
        "expected-revision CAS",
        "Package owner does not import the concrete ledger",
    ):
        assert retention in normalized
    for compatibility in (
        "Package lifecycle epoch and minimum fence-aware runtime",
        "Direct downgrade after any B epoch state exists is unsupported",
        "offline restore of the complete pre-B Package store",
        "mixed-epoch writers are never admitted",
        "`legacy_unverified`",
        "may classify a request as `plugin_bound`",
        "cannot satisfy B recursive closure, commit admission",
        "Adoption requires authenticated reacquisition",
        "already-running pre-fence writer could ignore",
        "fresh identity-pinned B-epoch namespace",
        "does not implicitly change desired, Instance, binding, or enablement state",
    ):
        assert compatibility in normalized


def test_plc9b_transport_surfaces_do_not_import_concrete_effect_owners() -> None:
    transport_paths = (
        Path("src/loushang/harness/cli/package_lifecycle.py"),
        Path("src/loushang/harness/host/rpc/commands/packages.py"),
        Path("src/loushang/harness/session/facade_optional.py"),
        Path("src/loushang/harness/session/lifecycle_adapter.py"),
    )
    forbidden_modules = (
        "loushang.harness.resources.packages.materializer",
        "loushang.harness.resources.plugins.revisions",
        "loushang.harness.plugin_management.package_lifecycle",
    )

    for path in transport_paths:
        source = _source(path)
        assert not any(module in source for module in forbidden_modules), path


def test_plc9b1_dark_kernel_preserves_visible_unsafe_debt() -> None:
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
    assert (OWNER_KERNEL_ROOT / "records.py").is_file()
    assert (OWNER_KERNEL_ROOT / "journal.py").is_file()
    assert (OWNER_KERNEL_ROOT / "owner.py").is_file()
    assert BOUNDED_ACQUISITION.is_file()
    for forbidden in (
        "PackageLifecycleOwner",
        "BoundedAcquisitionReceipt",
        "VerifiedWheelArtifact",
        "DependencyClosureLockV2",
    ):
        assert forbidden not in author_sdk


def test_plc9b1_owner_kernel_stays_internal_dark_and_capability_free() -> None:
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    kernel_sources = {path: _source(path) for path in OWNER_KERNEL_ROOT.glob("*.py")}
    owner = kernel_sources[OWNER_KERNEL_ROOT / "owner.py"]

    assert "enabled: bool = False" in owner
    assert "PackageLifecycleOwner" not in package_facade
    assert "plugin_lifecycle" not in package_facade
    forbidden_modules = (
        "loushang.harness.resources.packages.materializer",
        "loushang.harness.resources.plugins.revisions",
        "loushang.harness.plugin_management",
        "subprocess",
        "urllib.request",
        "httpx",
        "requests",
        "socket",
    )
    for path, source in kernel_sources.items():
        tree = ast.parse(source, filename=str(path))
        imported = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imported
            for forbidden in forbidden_modules
        ), path

    production_importers: list[Path] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        if path.is_relative_to(OWNER_KERNEL_ROOT):
            continue
        tree = ast.parse(_source(path), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "loushang.harness.resources.packages.plugin_lifecycle"
            ):
                production_importers.append(path)
            elif isinstance(node, ast.Import) and any(
                alias.name.startswith(
                    "loushang.harness.resources.packages.plugin_lifecycle"
                )
                for alias in node.names
            ):
                production_importers.append(path)
    assert set(production_importers) == {
        Path("src/loushang/harness/plugin_management/package_product.py"),
        Path("src/loushang/harness/resources/packages/product_activation.py"),
        Path("src/loushang/harness/resources/packages/product_composition.py"),
        Path("src/loushang/harness/resources/packages/product_contract.py"),
        LINUX_LEGACY_RUNTIME,
        PRODUCT_LIFECYCLE,
        WINDOWS_LEGACY_RUNTIME,
    }


def test_plc9b5_product_router_is_capability_poor_and_internal() -> None:
    source = _source(PRODUCT_LIFECYCLE)
    facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    contract = _source(CONTRACT)
    tree = ast.parse(source, filename=str(PRODUCT_LIFECYCLE))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    loushang_imports = {module for module in imported if module.startswith("loushang.")}

    assert loushang_imports == {
        "loushang.harness.resources.packages.plugin_lifecycle.owner",
        "loushang.harness.resources.packages.plugin_lifecycle.records",
        "loushang.harness.resources.packages.product_contract",
    }
    assert "class PackageProductLifecycleRouter:" in source
    assert "class PackageProductLifecycleTransactionPort(Protocol):" in source
    assert (
        '_TRANSACTION_ENTRYPOINTS = frozenset({"cli", "rpc", "session", '
        '"startup", "operations"})' in source
    )
    assert "self._transaction.execute(request, classified=status)" in source
    assert "def refuse_direct_publish(" in source
    for forbidden in (
        "PackageMaterializer",
        "PackageSourceResolver",
        "PluginRevisionStore",
        "publish_plugin_packages",
        "materialize_remote_source",
        "bind_plugin_packages",
        "subprocess",
        "socket",
    ):
        assert forbidden not in source
    for exported in (
        "PackageProductLifecycleRouter",
        "PackageProductLifecycleTransactionPort",
        "PackageProductRouteRequestV1",
        "PackageProductPublishAttemptV1",
    ):
        assert f'"{exported}":' in facade
        assert exported not in author_sdk
    assert "## PLC9B5 Accepted Product Routing And Bypass Closure" in contract
    assert "from 112 to 119 nodes" in contract
    normalized = " ".join(contract.split())
    assert "Harness Quality run `33709473590`" in normalized
    assert "122 tests total" in normalized
    assert "all 23 PR checks passed" in normalized


def test_plc9b2a_acquisition_is_unbound_bounded_and_pathless() -> None:
    contract = _source(CONTRACT)
    source = _source(BOUNDED_ACQUISITION)
    tree = ast.parse(source, filename=str(BOUNDED_ACQUISITION))

    assert "class PackageSourceAuthorityPort(Protocol)" in source
    assert "class BoundedAcquisitionSinkPort(Protocol)" in source
    assert "class PackageQuarantineStore:" in source
    assert "class PackageAcquisitionOwner:" in source
    assert "opaque acquired-candidate capability" in contract
    assert "promote no global adversarial manifest row" in " ".join(contract.split())

    sink = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "BoundedAcquisitionSinkPort"
    )
    assert {
        node.name
        for node in sink.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    } == {"begin_request", "record_redirect", "write"}
    assert not any(
        token in source
        for token in (
            "PythonPackageInstallerBackend",
            "PluginRevisionStore",
            "PluginManagementService",
            "subprocess",
            "urllib.request",
            "httpx",
            "requests.get",
            "socket.socket",
            "zipfile",
            "tarfile",
        )
    )


def test_plc9b3a_closure_verifier_is_dark_pure_and_does_not_promote_rows() -> None:
    contract = _source(CONTRACT)
    source = _source(CLOSURE_VERIFIER)
    component_tests = _source(CLOSURE_TEST)
    package_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    project = _source(PYPROJECT)

    assert CLOSURE_VERIFIER.is_file()
    assert "class PackageClosureVerifier:" in source
    assert "class VerifiedClosurePlanV2:" in source
    assert "class VerifiedClosurePlanNodeV2:" in source
    assert "class PackageResolutionEnvironmentV1:" in source
    assert '"packaging>=24,<27"' in project
    for forbidden_symbol in (
        "PluginRevisionStore",
        "PluginPackageLifecycleLedger",
        "PackageLifecycleOwner",
        "open(",
        "Path(",
    ):
        assert forbidden_symbol not in source
    tree = ast.parse(source, filename=str(CLOSURE_VERIFIER))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden_modules = {
        "httpx",
        "pathlib",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for internal_symbol in (
        "PackageClosureVerifier",
        "VerifiedClosurePlanV2",
        "PackageClosureVerificationRequestV2",
    ):
        assert internal_symbol not in package_facade
        assert internal_symbol not in author_sdk

    component_case_ids = {
        "B-CLOSURE-MISSING",
        "B-CLOSURE-DIGEST",
        "B-CLOSURE-ORIGIN",
        "B-CLOSURE-MARKER",
        "B-CLOSURE-NAME",
        "B-CLOSURE-CYCLE",
        "B-CLOSURE-V1",
    }
    assert all(case_id in component_tests for case_id in component_case_ids)
    assert "component evidence only" in contract
    assert "creates no\ntyped stable ref" in contract


def test_plc9b3b_durable_closure_inputs_are_ordered_dark_and_unpromoted() -> None:
    contract = _source(CONTRACT)
    acquisition = _source(BOUNDED_ACQUISITION)
    evidence = _source(PHASE_EVIDENCE)
    runtime = _source(ARTIFACT_RUNTIME)
    wheel = _source(WHEEL_VERIFIER)
    package_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)

    assert "class PackageAuthenticatedSourceEvidenceV1:" in acquisition
    assert "class _AuthorizedPackageSource:" in acquisition
    assert "def authorize_source(" in acquisition
    assert "def acquire_authorized(" in acquisition
    assert "authenticated_source" in evidence
    assert runtime.index("authorize_source(") < runtime.index("acquire_authorized(")
    assert runtime.index("evidence=source_evidence") < runtime.index(
        "acquire_authorized("
    )
    assert "metadata_claims = _verify_wheel_metadata(" in wheel
    assert "self.requires_dist = requires_dist" in wheel
    assert "self.requires_python = requires_python" in wheel
    assert "self.provides_extra = provides_extra" in wheel
    assert 'package.get_all("Requires-Dist", [])' in wheel
    for forbidden_export in (
        "PackageAuthenticatedSourceEvidenceV1",
        "_AuthorizedPackageSource",
    ):
        assert forbidden_export not in package_facade
        assert forbidden_export not in author_sdk
    assert "Existing\nreceipt-first B2 journals remain replayable" in contract
    assert "creates no typed stable ref" in contract


def test_plc9b3c_recursive_builder_is_selection_only_dark_and_unpromoted() -> None:
    contract = _source(CONTRACT)
    source = _source(CLOSURE_OWNER)
    component_tests = _source(CLOSURE_OWNER_TEST)
    package_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)

    assert CLOSURE_OWNER.is_file()
    for symbol in (
        "class PackageDependencyResolverPort(Protocol):",
        "class PackageDependencySelectionRequestV1:",
        "class PackageDependencySelectionV1:",
        "class PackageRecursiveClosureOwner:",
        "class VerifiedPackageClosureCandidate:",
    ):
        assert symbol in source
    for required_flow in (
        "authorize_source(",
        "acquire_authorized(",
        "self._wheel_verifier.verify(",
        "self._closure_verifier.verify(",
        "requirement.marker_applies(",
    ):
        assert required_flow in source
    for forbidden_symbol in (
        "PackageLifecycleJournal",
        "PackageAttemptJournal",
        "PluginRevisionStore",
        "PluginPackageLifecycleLedger",
        "PluginManagementService",
        "subprocess",
        "urllib.request",
        "httpx",
        "requests.get",
        "socket.socket",
    ):
        assert forbidden_symbol not in source
    tree = ast.parse(source, filename=str(CLOSURE_OWNER))
    resolver = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "PackageDependencyResolverPort"
    )
    assert {
        node.name
        for node in resolver.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    } == {"resolve"}
    for internal_symbol in (
        "PackageDependencyResolverPort",
        "PackageDependencySelectionV1",
        "PackageRecursiveClosureOwner",
        "VerifiedPackageClosureCandidate",
    ):
        assert internal_symbol not in package_facade
        assert internal_symbol not in author_sdk
    for evidence in (
        "reaches_fixpoint_when_incoming_extras_expand_late",
        "rejects_resolver_identity_change_before_dependency_io",
        "enforces_total_request_budget_before_source_call",
        "enforces_depth_budget_before_dependency_source_call",
        "rejects_incompatible_resolver_version_before_source_call",
        "preflights_root_python_before_resolver_or_source_call",
        "preflights_root_extras_before_resolver_or_source_call",
        "rejects_direct_url_requirement_without_resolver_call",
    ):
        assert evidence in component_tests
    assert "B3c is accepted only as a dark component" in contract
    assert "does not journal\n`resolving_closure -> closure_verified`" in contract


def test_plc9b3d_candidate_binds_recovery_before_io_and_remains_dark() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    journal = _source(CLOSURE_JOURNAL)
    owner = _source(CLOSURE_OWNER)
    runtime = _source(CLOSURE_RUNTIME)
    journal_tests = _source(CLOSURE_JOURNAL_TEST)
    owner_tests = _source(CLOSURE_OWNER_TEST)
    runtime_tests = _source(CLOSURE_RUNTIME_TEST)
    manifest = _adversarial_manifest()

    assert CLOSURE_JOURNAL.is_file()
    assert CLOSURE_RUNTIME.is_file()
    for symbol in (
        "class PackageClosureResolutionBasisV1:",
        "class PackageClosureResolutionRecordV1:",
        "class PackageClosureResolutionJournal:",
    ):
        assert symbol in journal
    for symbol in (
        "class PackageClosureExecutionRequestV2:",
        "class PackageClosureExecutionResult:",
        "class PackageClosureLifecycleOwner:",
    ):
        assert symbol in runtime
        assert symbol.removeprefix("class ").removesuffix(":") not in package_facade
    assert runtime.index("bind_basis(") < runtime.index("self._artifact_owner.execute(")
    assert runtime.index("append_plan(") < runtime.index(
        'next_phase="closure_verified"'
    )
    assert owner.index("append_selection(") < owner.index("authorize_source(")
    assert "PackageClosureCleanupOwnerPort" in owner
    assert "PackageDependencyCleanupDebtError" in owner
    assert "credential_reference" not in journal
    for forbidden in (
        "PluginRevisionStore",
        "PluginPackageLifecycleLedger",
        "CommittedPackageSet",
        "TransactionPin",
        "loushang.coding",
        "loushang.foundation",
        "subprocess",
        "urllib.request",
    ):
        assert forbidden not in journal
        assert forbidden not in runtime
    integrity_cases = {
        "B-CLOSURE-MISSING",
        "B-CLOSURE-DIGEST",
        "B-CLOSURE-ORIGIN",
        "B-CLOSURE-MARKER",
        "B-CLOSURE-NAME",
        "B-CLOSURE-CYCLE",
        "B-CLOSURE-V1",
    }
    assert all(
        manifest[case_id]["status"] == "implemented" for case_id in integrity_cases
    )
    assert {
        manifest[case_id]["status"]
        for case_id in {
            "B-CRASH-RESOLVING",
            "B-CRASH-CLOSURE",
            "B-LIMIT-GRAPH",
            "B-LIMIT-SOLVER",
            "B-LIMIT-REQUESTS",
        }
    } == {"implemented"}
    assert manifest["B-LIMIT-REQUESTS"]["barrier"] == "resolving_closure"
    assert manifest["B-LIMIT-REQUESTS"]["disposition"] == "rejected@resolving_closure"
    for evidence in (
        "changed_inputs_fail_closed",
        "without_resolver_or_source_io",
        "durably_records_dependency_cleanup_debt",
        "changed_budget_before_root_or_dependency_io",
        "cancel_wins_final_phase_cas",
    ):
        assert evidence in journal_tests + owner_tests + runtime_tests
    normalized = " ".join(contract.split())
    assert "basis -> selection* -> verified_plan" in normalized
    assert "This remains dark accepted code" in contract
    assert "PLC9B3d-1 accepted dark code binds a complete credential-free" in inventory
    assert "final review-fix head `3ed13f43`" in contract
    assert "Harness Quality run `33512955335`" in contract
    assert "Linux harness job\n`99872863556`" in contract
    assert "artifact ID\n`9802403797`" in contract
    assert "executed exactly 54 manifest nodes" in contract
    assert "B3d-2a was accepted on 2026-09-01 against candidate head `68406b31`" in (
        contract
    )
    assert "Harness Quality run `33515285825`" in normalized
    assert "Linux harness job `99880656864`" in normalized
    assert "artifact ID `9803312387`" in normalized
    assert (
        "58e17cd15e241b62f6d7382b08adcdee0a349ec849ed94a6fd0975d329c2520e" in contract
    )
    assert "executed exactly 57 manifest nodes" in contract
    assert "retained artifact `9803312387` executed exactly 57 native" in (
        " ".join(inventory.split())
    )
    assert "B3d-2b was accepted on 2026-09-01 against candidate head `86858f32`" in (
        contract
    )
    assert "Harness Quality run `33521116497`" in normalized
    assert "Linux harness job `99900313474`" in normalized
    assert "artifact ID `9805712792`" in normalized
    assert (
        "41c3d0111fabf31a22dee0269c51bae36da9e6a5e1e9df03eec78be86dca4780" in contract
    )
    assert "executed exactly 64 manifest nodes" in contract
    assert "cleanup-debt custody for every rejected candidate" in inventory
    assert "retained artifact `9805712792` executed exactly 64 native" in (
        " ".join(inventory.split())
    )


def test_plc9b3e1_typed_commit_records_are_strict_dark_and_unpromoted() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    source = _source(COMMIT_RECORDS)
    component_tests = _source(COMMIT_RECORDS_TEST)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert COMMIT_RECORDS.is_file()
    for symbol in (
        "class VerifiedArtifactRefV1:",
        "class PluginRevisionRefV1:",
        "class DependencyClosureNodeV2:",
        "class DependencyClosureLockV2:",
        "class CommittedPackageSetRefV1:",
    ):
        assert symbol in source
        public_name = symbol.removeprefix("class ").removesuffix(":")
        assert public_name not in package_facade
        assert public_name not in internal_facade
        assert public_name not in author_sdk
    tree = ast.parse(source, filename=str(COMMIT_RECORDS))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "pathlib",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for evidence in (
        "requires_the_exact_typed_node_set",
        "rejects_role_confusion_and_changed_artifact_evidence",
        "revalidates_embedded_plan_instead_of_only_its_digest",
        "reject_extensions_and_future_versions",
        "rejects_root_identity_drift_and_is_credential_free",
        "nested_ref_tampering_is_rejected",
    ):
        assert evidence in component_tests
    assert "B3e-1 freezes the credential-free records" in contract
    assert "PLC9B3e-1 accepted code adds internal strict typed" in inventory
    normalized = " ".join(contract.split())
    assert "B3e-1 was accepted on 2026-09-01 against candidate head `7e9bebba`" in (
        normalized
    )
    assert "Harness Quality run `33521945259`" in normalized
    assert "Linux harness job `99903140145`" in normalized
    assert "artifact ID `9806065559`" in normalized
    assert (
        "0796849b296edb53f9f2a804e7db35b8467dad375a11695870e86e221bf124bd" in contract
    )
    _assert_current_publication_statuses(manifest)


def test_plc9b3e2a_transaction_pin_contract_is_narrow_dark_and_unpromoted() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    source = _source(TRANSACTION_PINS)
    component_tests = _source(TRANSACTION_PINS_TEST)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert TRANSACTION_PINS.is_file()
    for symbol in (
        "class PackageTransactionPinTargetV1:",
        "class PackageTransactionPinRequestV1:",
        "class PackageTransactionPinReceiptV1:",
        "class PackageTransactionPinPort(Protocol):",
        "class PackageTransactionPinRecordV1:",
        "class PackageTransactionPinJournal:",
    ):
        assert symbol in source
        public_name = symbol.removeprefix("class ").split("(", 1)[0].removesuffix(":")
        assert public_name not in package_facade
        assert public_name not in internal_facade
        assert public_name not in author_sdk
    tree = ast.parse(source, filename=str(TRANSACTION_PINS))
    pin_port = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PackageTransactionPinPort"
    )
    assert {
        node.name
        for node in pin_port.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    } == {"acquire", "release"}
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for forbidden_capability in (
        "VerifiedPackageClosureCandidate",
        "PluginRevisionStore",
        "PluginPackageLifecycleLedger",
        "PluginManagementService",
    ):
        assert forbidden_capability not in source
    for evidence in (
        "derives_exact_canonical_targets_from_verified_plan",
        "carry_no_path_credential_or_live_handle",
        "acquire_release_and_transfer_are_strict_round_trips",
        "rejects_stale_or_chained_terminal_transition",
        "appends_acquire_then_release_and_replays_after_restart",
        "rejects_changed_acquisition_without_mutation",
        "rejects_release_without_acquire_or_wrong_predecessor",
        "repairs_partial_tail_but_rejects_duplicate_json_keys",
    ):
        assert evidence in component_tests
    assert "B3e-2a freezes the transaction-retention boundary" in contract
    assert "PLC9B3e-2a accepted code adds exact credential-free" in inventory
    normalized = " ".join(contract.split())
    assert "B3e-2a was accepted on 2026-09-01 against candidate head `712adde3`" in (
        normalized
    )
    assert "Harness Quality run `33526455182`" in normalized
    assert "Linux harness job `99918424525`" in normalized
    assert "artifact ID `9807880155`" in normalized
    assert (
        "a00c4a93f714c662534e7ffac9c9cb619ae18689aafe727b0259e7a462c99e42" in contract
    )
    assert "transaction_pin_runtime" not in source
    _assert_current_publication_statuses(manifest)


def test_plc9b3e2b_transaction_pin_runtime_orders_effects_and_recovers_dark() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    source = _source(TRANSACTION_PIN_RUNTIME)
    component_tests = _source(TRANSACTION_PIN_RUNTIME_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert TRANSACTION_PIN_RUNTIME.is_file()
    for symbol in (
        "class PackageVerifiedClosurePlanEvidencePort(Protocol):",
        "class PackageTransactionPinExecutionResult:",
        "class PackageTransactionPinLifecycleOwner:",
    ):
        assert symbol in source
        public_name = symbol.removeprefix("class ").split("(", 1)[0].removesuffix(":")
        assert public_name not in package_facade
        assert public_name not in internal_facade
        assert public_name not in author_sdk
    tree = ast.parse(source, filename=str(TRANSACTION_PIN_RUNTIME))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    owner = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "PackageTransactionPinLifecycleOwner"
    )
    assert {
        node.name
        for node in owner.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    } == {"pin", "recover"}
    pin_source = ast.get_source_segment(
        source,
        next(
            node
            for node in owner.body
            if isinstance(node, ast.FunctionDef) and node.name == "pin"
        ),
    )
    assert pin_source is not None
    assert (
        pin_source.index("self._retention.acquire")
        < pin_source.index("self._pin_journal.append")
        < pin_source.index("self._kernel.advance")
    )
    for evidence in (
        "acquires_journals_advances_and_exactly_replays",
        "recovers_external_acquire_before_local_receipt",
        "recovers_local_receipt_before_phase_cas",
        "recovers_pinned_operation_without_live_candidate",
        "recovers_interrupted_pinned_operation_and_visible_pin",
        "recovery_rejects_changed_identity_before_retention",
        "recovery_rejects_missing_local_receipt_before_retention",
        "cancel_wins_phase_cas_without_releasing_visible_pin",
        "adopts_prior_attempt_pin_without_double_acquire",
    ):
        assert evidence in component_tests
    assert "IMPLEMENTED_B3E_PIN_MANIFEST_CASES" in adversarial_tests
    assert "physical_acquisitions == 1" in adversarial_tests
    assert "B3e-2b composes the accepted typed pin contract" in contract
    assert "PLC9B3e-2b accepted code composes" in inventory
    normalized = " ".join(contract.split())
    assert "B3e-2b was accepted on 2026-09-01 against candidate head `8f637de7`" in (
        normalized
    )
    assert "Harness Quality run `33532486596`" in normalized
    assert "Linux harness job `99938764642`" in normalized
    assert "artifact ID `9810291887`" in normalized
    assert (
        "e4af1f9c36f060548d634a48b55bd7db6c95e7af9635d6c784596680b065f78c" in contract
    )
    assert "executed exactly 65 manifest nodes" in normalized
    assert manifest["B-CRASH-PINNED"]["status"] == "implemented"
    _assert_current_publication_statuses(manifest)


def test_plc9b3e3a_staging_and_atomic_set_contracts_are_dark_and_role_safe() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    staging_source = _source(STAGING)
    committed_source = _source(COMMITTED_SETS)
    staging_tests = _source(STAGING_TEST)
    committed_tests = _source(COMMITTED_SETS_TEST)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert STAGING.is_file()
    assert COMMITTED_SETS.is_file()
    symbols = (
        "PackagePluginRootTargetV1",
        "PackageArtifactStagingRequestV1",
        "PackageArtifactStagingReceiptV1",
        "PackageDependencyStagingPort",
        "PackagePluginRootStagingPort",
        "PackageArtifactStagingRecordV1",
        "PackageArtifactStagingJournal",
        "PackageCommittedSetRecordV1",
        "PackageCommittedSetJournal",
    )
    combined_source = staging_source + committed_source
    for symbol in symbols:
        assert f"class {symbol}" in combined_source
        assert symbol not in package_facade
        assert symbol not in internal_facade
        assert symbol not in author_sdk

    staging_tree = ast.parse(staging_source, filename=str(STAGING))
    port_methods = {
        node.name: {
            member.name
            for member in node.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in staging_tree.body
        if isinstance(node, ast.ClassDef)
        and node.name
        in {"PackageDependencyStagingPort", "PackagePluginRootStagingPort"}
    }
    assert port_methods == {
        "PackageDependencyStagingPort": {"stage_dependency"},
        "PackagePluginRootStagingPort": {"stage_root"},
    }

    for source, path in (
        (staging_source, STAGING),
        (committed_source, COMMITTED_SETS),
    ):
        tree = ast.parse(source, filename=str(path))
        imported = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        forbidden_modules = (
            "loushang.harness.plugin_management",
            "loushang.harness.resources.plugins.revisions",
            "loushang.coding",
            "loushang.foundation",
            "subprocess",
        )
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imported
            for forbidden in forbidden_modules
        )

    for forbidden_capability in (
        "PluginRevisionStore",
        "PluginPackageLifecycleLedger",
        "PluginManagementService",
        "PackageOperationsRuntime",
    ):
        assert forbidden_capability not in combined_source

    for evidence in (
        "requests_and_receipts_are_exact_role_safe_round_trips",
        "requires_exact_acquired_graph_wide_pin",
        "requires_authoritative_root_target_only_for_root",
        "rejects_role_or_plugin_identity_confusion",
        "wire_is_credential_path_handle_free_and_strict",
        "records_exact_nodes_and_replays_after_restart",
        "rejects_changed_ref_without_mutation",
        "repairs_partial_tail_and_rejects_duplicate_keys",
    ):
        assert evidence in staging_tests
    for evidence in (
        "atomically_records_lock_and_exact_set",
        "serializes_concurrent_exact_publication",
        "rejects_changed_identity_without_mutation",
        "revalidates_full_lock_not_only_projection",
        "wire_is_credential_path_handle_free_and_strict",
        "repairs_partial_tail_and_rejects_duplicate_keys",
    ):
        assert evidence in committed_tests

    normalized = " ".join(contract.split())
    assert "B3e-3a separates physical store ownership" in normalized
    assert (
        "creates the complete `DependencyClosureLockV2`/`CommittedPackageSetRefV1` pair under one durable Package-owner lock"
        in normalized
    )
    assert "PLC9B3e-3a accepted code now separates" in inventory
    assert "PLC9B3e-3a accepted code adds dark" in index
    assert "B3e-3a was accepted on 2026-09-01 against candidate head `c70a39f4`" in (
        normalized
    )
    assert "Harness Quality run `33537324112`" in normalized
    assert "Linux harness job `99954713682`" in normalized
    assert "artifact ID `9812156268`" in normalized
    assert (
        "d8fbdd16b4a84de341ad7244ffa1af5d4dafd79a9c4b097fc612258a0ebf4450" in contract
    )
    _assert_current_publication_statuses(manifest)


def test_plc9b3e3b_runtime_orders_staging_set_effects_and_recovers_dark() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(STAGING_SET_RUNTIME)
    component_tests = _source(STAGING_SET_RUNTIME_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert STAGING_SET_RUNTIME.is_file()
    for symbol in (
        "PackageStagingClosurePlanEvidencePort",
        "PackagePluginRootTargetAuthorityPort",
        "PackageStagingSetExecutionResult",
        "PackageStagingSetLifecycleOwner",
    ):
        assert f"class {symbol}" in source
        assert symbol not in package_facade
        assert symbol not in internal_facade
        assert symbol not in author_sdk

    tree = ast.parse(source, filename=str(STAGING_SET_RUNTIME))
    owner = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "PackageStagingSetLifecycleOwner"
    )
    public_methods = {
        node.name
        for node in owner.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    assert public_methods == {
        "authorize_adoption",
        "stage_and_publish",
        "resume",
        "recover",
    }
    stage_method = next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == "stage_and_publish"
    )
    stage_source = ast.get_source_segment(source, stage_method)
    assert stage_source is not None
    assert 'node.role == "dependency"' in stage_source
    assert 'node.role == "root"' in stage_source
    assert stage_source.index('node.role == "dependency"') < stage_source.index(
        'node.role == "root"'
    )
    assert stage_source.index("self._staging_journal.append") < stage_source.index(
        'next_phase="staging"'
    )
    publish_method = next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == "_publish_from_evidence"
    )
    publish_source = ast.get_source_segment(source, publish_method)
    assert publish_source is not None
    assert (
        publish_source.index("self._classification_recheck.recheck")
        < publish_source.index("self._committed_sets.publish")
        < publish_source.index('next_phase="set_published"')
    )
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for forbidden_capability in (
        "PluginRevisionStore",
        "PluginPackageLifecycleLedger",
        "PluginManagementService",
        "PackageOperationsRuntime",
    ):
        assert forbidden_capability not in source
    for evidence in (
        "stages_journals_rechecks_and_publishes_exact_set",
        "rechecks_classification_after_staging_before_set",
        "rejects_live_candidate_drift_before_store_effect",
        "resumes_receipts_after_crash_before_set",
        "recovers_set_after_crash_without_live_candidate",
        "adopts_prior_attempt_receipts_without_restage",
    ):
        assert evidence in component_tests
    assert "IMPLEMENTED_B3E_STAGING_SET_MANIFEST_CASES" in adversarial_tests
    assert "root_staging.physical_stages == 1" in adversarial_tests
    assert "source_authority.authorize_calls == source_calls == 1" in (
        adversarial_tests
    )
    assert "B3e-3b accepted code composes" in inventory
    assert "PLC9B3e-3b accepted code composes" in index
    normalized = " ".join(contract.split())
    assert "Staging order is dependencies first" in normalized
    assert (
        "classification-recheck Port immediately before creating any committed set"
        in (normalized)
    )
    assert "B3e-3b was accepted on 2026-09-01 against candidate head `0dadf471`" in (
        normalized
    )
    assert "Harness Quality run `33541012780`" in normalized
    assert "Linux harness job `99966966810`" in normalized
    assert "artifact ID `9813586958`" in normalized
    assert (
        "5937ae3e1a55da57edf996537d6c0b547c3769c290dbd7ac9fd59691ab39d2fd" in contract
    )
    assert "executed exactly 67 manifest nodes" in normalized
    assert manifest["B-CRASH-STAGING"]["status"] == "implemented"
    assert manifest["B-CRASH-SET"]["status"] == "implemented"
    _assert_current_publication_statuses(manifest)


def test_plc9b3e3c0_freezes_pathless_role_separated_transfer_contracts() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(TREE_TRANSFER)
    wheel = _source(WHEEL_VERIFIER)
    component_tests = _source(TREE_TRANSFER_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert TREE_TRANSFER.is_file()
    assert TREE_TRANSFER_TEST.is_file()
    symbols = (
        "PackageVerifiedTreeEntryV1",
        "PackageVerifiedTreeManifestV1",
        "PackageVerifiedTreeFileSinkPort",
        "PackageVerifiedTreeSinkPort",
        "PackageVerifiedTreeTransferPort",
        "PackageDependencyMaterializationRootPort",
        "PackagePluginRootMaterializationRootPort",
    )
    for symbol in symbols:
        assert f"class {symbol}" in source
        assert symbol not in package_facade
        assert symbol not in internal_facade
        assert symbol not in author_sdk

    tree = ast.parse(source, filename=str(TREE_TRANSFER))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "os",
        "pathlib",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for forbidden_capability in (
        "PluginRevisionStore",
        "PluginPackageLifecycleLedger",
        "PackageOperationsRuntime",
        "PythonPackageInstallerBackend",
    ):
        assert forbidden_capability not in source

    assert "PackageVerifiedTreeManifestV1.create" in wheel
    assert "def transfer_manifest" in wheel
    for evidence in (
        "manifest_binds_canonical_files_to_verified_wheel_evidence",
        "entry_rejects_nonportable_or_ambiguous_logical_paths",
        "manifest_rejects_order_tree_or_evidence_drift",
        "manifest_wire_is_strict_and_contains_no_physical_authority",
        "transfer_contracts_keep_source_store_and_root_roles_separate",
    ):
        assert evidence in component_tests
    assert "PLANNED_B3E3C_MATERIALIZATION_MANIFEST_CASES" in adversarial_tests
    assert "PLANNED_B4_COMMIT_ADMISSION_MANIFEST_CASES" in adversarial_tests

    publication_cases = {
        case_id for case_id in manifest if case_id.startswith("B-PUB-")
    }
    assert len(publication_cases) == 13
    _assert_current_publication_statuses(manifest)
    assert manifest["B-PUB-UNCOMMITTED"]["status"] == "implemented"

    normalized = " ".join(contract.split())
    assert "B3e-3c0 closes the missing data-plane contract" in normalized
    assert "The manifest is deliberately files-only" in normalized
    assert "all 13 `B-PUB-*` rows remain `planned`" in normalized
    assert "B-PUB-UNCOMMITTED` remains a PLC9B4 commit-admission gate" in normalized
    assert "PLC9B3e-3c0 accepted code adds a strict files-only" in inventory
    assert "PLC9B3e-3c0 accepted contracts bind a files-only" in index
    assert "B3e-3c0 was accepted on 2026-09-01 against candidate head `1b00b8cd`" in (
        normalized
    )
    assert "Harness Quality run `33545076092`" in normalized
    assert "Linux harness job `99980454997`" in normalized
    assert "artifact ID `9815136763`" in normalized
    assert (
        "16f5c3d4ab46c10b42ef32e88024299c295ca51406f99f71348c571251d1c5f1" in contract
    )
    assert "executed the unchanged 67 manifest nodes" in normalized


def test_plc9b3e3c1_posix_materialization_is_rooted_role_safe_and_executable() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    acquisition = _source(BOUNDED_ACQUISITION)
    transfer = _source(TREE_TRANSFER)
    posix_store = _source(POSIX_MATERIALIZATION)
    runtime = _source(STAGING_SET_RUNTIME)
    component_tests = _source(POSIX_MATERIALIZATION_TEST)
    wheel_tests = _source(Path("tests/harness/resources/packages/test_plc9b_wheel.py"))
    adversarial_tests = _source(ADVERSARIAL_TEST)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert POSIX_MATERIALIZATION.is_file()
    assert POSIX_MATERIALIZATION_TEST.is_file()
    for symbol, source in (
        ("PackagePhysicalStagingError", transfer),
        ("PackageVerifiedTreeTransferOwner", transfer),
        ("PosixPackageDependencyMaterializationStore", posix_store),
        ("PosixPackagePluginRootMaterializationStore", posix_store),
    ):
        assert f"class {symbol}" in source
        assert symbol not in package_facade
        assert symbol not in internal_facade
        assert symbol not in author_sdk

    assert "def _open_verified_tree_file" in acquisition
    assert "candidate._open_verified_tree_file(entry)" in transfer
    assert "destination.finish()" in transfer
    assert "sink.abort()" in transfer
    for rooted_primitive in (
        "os.open(",
        "os.O_NOFOLLOW",
        "dir_fd=",
        "os.fsync(",
        "_rename_directory_noreplace(",
        "follow_symlinks=False",
        "threading.RLock()",
        "st_nlink",
        "is_absolute()",
    ):
        assert rooted_primitive in posix_store
    assert "Path.rename" not in posix_store
    assert ".resolve(" not in posix_store
    assert "PackagePhysicalStagingError as error" in runtime
    assert 'stage="staging"' in runtime

    tree = ast.parse(posix_store, filename=str(POSIX_MATERIALIZATION))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for forbidden_capability in (
        "PluginRevisionStore",
        "PluginPackageLifecycleLedger",
        "PackageOperationsRuntime",
        "PythonPackageInstallerBackend",
    ):
        assert forbidden_capability not in posix_store

    for evidence in (
        "publish_exact_trees_and_reuse_same_receipts",
        "rejects_precreated_staging_namespace_without_writing",
        "rejects_root_swap_and_releases_every_handle",
        "rejects_ancestor_swap_and_releases_every_handle",
        "aborts_partial_tree_and_closes_source_and_store_handles",
        "does_not_adopt_exact_tree_without_settlement_authority",
        "exact_reuse_rejects_unexpected_sparse_member_without_scanning_it",
        "exact_reuse_rejects_new_hardlink_alias",
        "rejects_relative_root_without_using_ambient_cwd",
    ):
        assert evidence in component_tests
    assert "opens_only_recorded_rooted_file_identities" in wheel_tests
    assert "IMPLEMENTED_B3E3C1_POSIX_MANIFEST_CASES" in adversarial_tests
    assert _implemented_b3e3c1_posix_manifest_cases() == PLC9B3E3C1_POSIX_CASES
    _assert_current_publication_statuses(manifest)
    assert manifest["B-PUB-UNCOMMITTED"]["status"] == "implemented"

    normalized = " ".join(contract.split())
    assert "B3e-3c1 implements the first native consumer" in normalized
    assert "pins the complete absolute ancestor chain" in normalized
    assert "replacement Store instance cannot infer ownership" in normalized
    assert "Linux-native report must execute 72 manifest nodes" in normalized
    assert "Windows root/ABA/handle rows remain planned" in normalized
    assert "PLC9B3e-3c1 accepted code implements" in inventory
    assert "PLC9B3e-3c1 accepted code adds" in index
    assert "B3e-3c1 was accepted on 2026-09-01 against candidate head `43441992`" in (
        normalized
    )
    assert "Harness Quality run `33550211162`" in normalized
    assert "Linux harness job `99997508982`" in normalized
    assert "artifact ID `9817127845`" in normalized
    assert (
        "a0def54b47500bd2aad59669ece3057df7179ab427cf8edd46f0491b1310db3b" in contract
    )
    assert "executed exactly 72 manifest nodes" in normalized


def test_plc9b3e3c2_windows_materialization_is_rooted_role_safe_and_native() -> None:
    contract = _source(CONTRACT)
    windows_primitives = _source(WINDOWS_QUARANTINE)
    windows_store = _source(WINDOWS_MATERIALIZATION)
    component_tests = _source(WINDOWS_MATERIALIZATION_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    workflow = _source(WINDOWS_WORKFLOW)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert WINDOWS_MATERIALIZATION.is_file()
    assert WINDOWS_MATERIALIZATION_TEST.is_file()
    for symbol in (
        "WindowsPackageDependencyMaterializationStore",
        "WindowsPackagePluginRootMaterializationStore",
    ):
        assert f"class {symbol}" in windows_store
        assert symbol not in package_facade
        assert symbol not in internal_facade
        assert symbol not in author_sdk

    for rooted_primitive in (
        "_PinnedWindowsRoot",
        "open_windows_directory",
        "share_delete=True",
        "windows_rename_at",
        "windows_flush_file",
        "windows_listdir_at",
        "windows_stat_at",
        "threading.RLock()",
        "st_nlink",
        "is_absolute()",
    ):
        assert rooted_primitive in windows_store
    assert "SetFileInformationByHandle" in windows_primitives
    assert "NtSetInformationFile" in windows_primitives
    assert "Path.rename" not in windows_store
    assert ".resolve(" not in windows_store

    tree = ast.parse(windows_store, filename=str(WINDOWS_MATERIALIZATION))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for evidence in (
        "publish_exact_trees_and_reuse_same_receipts",
        "handle_relative_rename_preserves_directory_identity",
        "rejects_configured_root_replacement_before_sink",
        "rejects_root_replacement_aba_and_releases_handles",
        "rejects_ancestor_reparse_without_outside_write",
        "rejects_nested_reparse_before_namespace_rename",
        "rejects_staging_handle_swap_and_closes_every_handle",
        "aborts_partial_tree_and_releases_handles",
        "does_not_adopt_tree_without_settlement_authority",
        "rejects_relative_root_without_ambient_cwd",
    ):
        assert evidence in component_tests
    assert "IMPLEMENTED_B3E3C2_WINDOWS_MANIFEST_CASES" in adversarial_tests
    assert _implemented_b3e3c2_windows_manifest_cases() == PLC9B3E3C2_WINDOWS_CASES
    for case_id in PLC9B3E3C2_WINDOWS_CASES:
        assert f"test_manifest_case[{case_id}]" in workflow
    assert "test_plc9b_windows_materialization.py" in workflow
    assert workflow.count("test_plc9b_adversarial.py::test_manifest_case[B-") == 15
    _assert_current_publication_statuses(manifest)
    assert manifest["B-PUB-UNCOMMITTED"]["status"] == "implemented"

    normalized = " ".join(contract.split())
    assert "PLC9B3e-3c2 Accepted Windows Verified-Tree Materialization" in normalized
    assert "pins the complete visible Windows ancestor chain" in normalized
    assert "Windows-native report executes all five" in normalized
    assert "collision/reuse remain B3e-3c3" in normalized
    assert "B3e-3c2 was accepted on 2026-09-01 against candidate head `d2beba3e`" in (
        normalized
    )
    assert "Windows Shell Compatibility run `33554991102`" in normalized
    assert "native job `100013505482`" in normalized
    assert "artifact ID `9818964189`" in normalized
    assert (
        "a21ad27b18a117350817b5640566b04d66cb599b026b67d30657a20433cc5adb" in contract
    )
    assert "native-component XML executed exactly 15 tests" in normalized
    assert "manifest XML executed exactly 12 nodes" in normalized
    assert "PLC9B3e-3c2 accepted code adds the two role-separated" in _source(INVENTORY)
    assert "PLC9B3e-3c2 accepted code adds corresponding" in _source(INDEX)


def test_plc9b3e3c3_settlement_authority_is_durable_exact_and_store_private() -> None:
    contract = _source(CONTRACT)
    settlement = _source(STORE_SETTLEMENTS)
    posix_store = _source(POSIX_MATERIALIZATION)
    windows_store = _source(WINDOWS_MATERIALIZATION)
    posix_tests = _source(POSIX_MATERIALIZATION_TEST)
    windows_tests = _source(WINDOWS_MATERIALIZATION_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert STORE_SETTLEMENTS.is_file()
    for symbol in (
        "PackageStoreNativeIdentityV1",
        "PackageStoreEntryIdentityV1",
        "PackageStoreSettlementRecordV1",
        "PackageStoreSettlementJournal",
    ):
        assert f"class {symbol}" in settlement
        assert symbol not in package_facade
        assert symbol not in internal_facade
        assert symbol not in author_sdk
    for evidence in (
        "PACKAGE_STORE_NATIVE_IDENTITY_VERSION = 1",
        "PACKAGE_STORE_ENTRY_IDENTITY_VERSION = 1",
        "PACKAGE_STORE_SETTLEMENT_RECORD_VERSION = 1",
        "root_identities",
        "tree_identity",
        "directory_identities",
        "file_identities",
        "manifest",
        "receipt",
        "append_jsonl_record",
        "journal_file_lock",
        'lock_suffix=".owner.lock"',
        "settlements_for_receipt",
        "validate_store_root",
    ):
        assert evidence in settlement

    tree = ast.parse(settlement, filename=str(STORE_SETTLEMENTS))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for store in (posix_store, windows_store):
        assert "settlement_journal: PackageStoreSettlementJournal" in store
        assert "self._settlement_journal.owner_lock()" in store
        assert "self._settlement_journal.authorize(" in store
        assert "self._settlement_journal.authorizes(" in store
        assert "settlements_for_receipt(" in store
        assert "validate_dependency_receipt" in store
        assert "validate_root_receipt" in store
        assert "receipt_probe" in store
        assert "_settled" not in store
    assert "renameat2" in posix_store
    assert "RENAME_NOREPLACE" in posix_store

    for tests in (posix_tests, windows_tests):
        for evidence in (
            "reuses_exact_tree_after_owner_restart_without_journal_append",
            "recovers_renamed_tree_when_receipt_delivery_is_lost",
            "durable_reuse_rejects_same_bytes_with_different_tree_identity",
            "settlement_journal_rejects_store_root_rebinding",
        ):
            assert evidence in tests
    assert "IMPLEMENTED_B3E3C3_SETTLEMENT_MANIFEST_CASES" in adversarial_tests
    assert (
        _implemented_b3e3c3_settlement_manifest_cases() == PLC9B3E3C3_SETTLEMENT_CASES
    )
    collision = manifest["B-PUB-COLLISION"]
    assert collision["barrier"] == "staging"
    assert collision["code"] == "package_publication_collision"
    assert collision["status"] == "implemented"
    reuse = manifest["B-PUB-REUSE"]
    assert reuse["barrier"] == "set_published"
    assert reuse["code"] == "ok"
    assert reuse["status"] == "implemented"
    _assert_current_publication_statuses(manifest)
    assert {
        case_id
        for case_id in manifest
        if case_id.startswith("B-PUB-") and manifest[case_id]["status"] == "planned"
    } == set()

    normalized = " ".join(contract.split())
    assert "PLC9B3e-3c3 Accepted Durable Settlement" in normalized
    assert "Store-private durable settlement authority" in normalized
    assert "authorization is durable before namespace rename" in normalized
    assert "candidate-free receipt validation" in normalized.lower()
    assert "Its XML executed exactly 74 manifest nodes" in normalized
    assert "native-component XML executed exactly 19 tests" in normalized
    assert "B3e-3c3 was accepted on 2026-09-01 against candidate head `94390869`" in (
        normalized
    )
    assert "Harness Quality run `33562831782`" in normalized
    assert "Linux harness job `100039113895`" in normalized
    assert "artifact ID `9821924161`" in normalized
    assert "Windows Shell Compatibility run `33562831700`" in normalized
    assert "native job `100039113787`" in normalized
    assert "artifact ID `9821946893`" in normalized
    assert (
        "1a5b51eeef36ebac93c29ff98898d00cdcc6816a270628c80cfcd4f9b2b53647" in contract
    )
    assert (
        "d69e337d062601c55641166cca1d0a193017b12ca49dcf1ef2b5f2ca0fab2ac4" in contract
    )
    assert "PLC9B3e-3c3 accepted code adds Store-private" in _source(INVENTORY)
    assert "PLC9B3e-3c3 accepted code adds a durable" in _source(INDEX)


def test_plc9b4a_commit_admission_is_dark_read_only_and_exact() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(COMMIT_ADMISSION)
    component_tests = _source(COMMIT_ADMISSION_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    manifest = _adversarial_manifest()

    assert COMMIT_ADMISSION.is_file()
    assert COMMIT_ADMISSION_TEST.is_file()
    for symbol in (
        "PackagePublicationReceiptV1",
        "PackageCommitAdmissionRequestV1",
        "PackageCommitAdmissionFailureV1",
        "PackageCommitAdmissionReceiptV1",
        "PackageCommitAdmissionResultV1",
        "PackageCommitAdmissionPort",
        "PackageCommitLifecycleOwner",
        "PackageCommitAdmissionOwner",
        "package_operation_fingerprint",
    ):
        assert symbol in source

    tree = ast.parse(source, filename=str(COMMIT_ADMISSION))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "os",
        "pathlib",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )

    visitor = _QualifiedFunctionVisitor()
    visitor.visit(tree)
    function_nodes = dict(visitor.functions)
    admit = function_nodes["PackageCommitAdmissionOwner.admit"]
    commit = function_nodes["PackageCommitLifecycleOwner.commit"]

    def called_names(node: ast.AST) -> list[str]:
        return [
            (
                call.func.attr
                if isinstance(call.func, ast.Attribute)
                else call.func.id
                if isinstance(call.func, ast.Name)
                else ""
            )
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        ]

    admission_calls = called_names(admit)
    assert not (
        {"advance", "append", "publish", "reopen", "open"} & set(admission_calls)
    )
    assert called_names(commit).count("advance") == 1
    assert "PackagePublicationReceiptV1.create" in source
    assert 'pin_receipt.state != "acquired"' in source
    assert "isinstance(request.claimed_root_ref, PluginRevisionRefV1)" in source
    assert "request.publication_receipt == expected" in source

    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    for symbol in (
        "PackageCommitLifecycleOwner",
        "PackageCommitAdmissionOwner",
        "PackageCommitAdmissionPort",
        "PackagePublicationReceiptV1",
    ):
        assert symbol not in internal_facade
        assert symbol not in package_facade
        assert symbol not in author_sdk

    for evidence in (
        "durably_closes_set_and_reconstructs_exact_receipt",
        "exact_committed_root_is_admitted_without_store_or_state_capability",
        "rejects_cross_context_claims_without_any_mutation",
        "stable_ref_without_durable_commit_receipt_is_never_admitted",
        "fails_closed_after_transaction_pin_is_no_longer_live",
        "reject_extensions_and_forged_fingerprints",
    ):
        assert evidence in component_tests
    assert "IMPLEMENTED_B4A_COMMIT_ADMISSION_MANIFEST_CASES" in adversarial_tests
    assert (
        _implemented_b4a_commit_admission_manifest_cases()
        == PLC9B4A_COMMIT_ADMISSION_CASES
    )
    for case_id in PLC9B4A_COMMIT_ADMISSION_CASES:
        row = manifest[case_id]
        assert row["status"] == "implemented"
        assert row["code"] == "package_commit_admission_denied"
        assert _journal_policy_for(case_id) == ("none", "no_append:unchanged")
        assert {"no_reopen", "no_handle_issued", "pin_visible"} <= set(
            row["oracles"].split(";")
        )
    _assert_current_publication_statuses(manifest)

    normalized = " ".join(contract.split())
    assert "PLC9B4a Accepted Commit Admission" in normalized
    assert "sole `set_published -> committed` CAS owner" in normalized
    assert "candidate-free read-only commit-admission owner" in normalized
    assert "never a path, store capability, reopened object, or live handle" in (
        normalized
    )
    assert "B4a was accepted on 2026-09-01 against candidate head `4aa314db`" in (
        normalized
    )
    assert "Harness Quality run `33566570578`" in normalized
    assert "Linux harness job `100051011649`" in normalized
    assert "artifact ID `9823339334`" in normalized
    assert (
        "1635536cd35bb7dcb2138ab723bade9cd807d5379de7db3a31b798b3fff289bd" in contract
    )
    assert "XML executed exactly 82 manifest nodes" in normalized
    assert "PLC9B4a accepted code closes the logical commit-admission" in inventory
    assert "PLC9B4a accepted code adds the dark terminal commit owner" in index


def test_plc9b4b_retention_handoff_is_dark_exact_and_no_zero_pin() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(RETENTION_HANDOFF)
    component_tests = _source(RETENTION_HANDOFF_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    manifest = _adversarial_manifest()

    assert RETENTION_HANDOFF.is_file()
    assert RETENTION_HANDOFF_TEST.is_file()
    for symbol in (
        "PackageDesiredStateCommitRequestV1",
        "PackageDesiredStateCommitReceiptV1",
        "PackageDesiredStateCommitFailureV1",
        "PackageDesiredStateCommitResultV1",
        "PackageDesiredStateCommitPort",
        "PackageDependencyPinRequestV1",
        "PackageDependencyPinReceiptV1",
        "PackageRetentionSettlementPort",
        "PackageRetentionHandoffRequestV1",
        "PackageRetentionHandoffReceiptV1",
        "PackageRetentionHandoffFailureV1",
        "PackageRetentionHandoffResultV1",
        "PackageRetentionHandoffRecordV1",
        "PackageRetentionHandoffJournal",
        "PackageRetentionHandoffOwner",
    ):
        assert symbol in source

    tree = ast.parse(source, filename=str(RETENTION_HANDOFF))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "os",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for forbidden_symbol in (
        "PluginPackageLifecycleLedger",
        "PluginDesiredStateLedger",
        "PluginPackageRevisionRefV1",
        "VerifiedRevisionHandle",
    ):
        assert forbidden_symbol not in source

    visitor = _QualifiedFunctionVisitor()
    visitor.visit(tree)
    execute = dict(visitor.functions)["PackageRetentionHandoffOwner.execute"]
    called = {
        call.func.attr
        if isinstance(call.func, ast.Attribute)
        else call.func.id
        if isinstance(call.func, ast.Name)
        else ""
        for call in ast.walk(execute)
        if isinstance(call, ast.Call)
    }
    assert {"admit", "acquire", "commit", "abort", "settle"} <= called
    assert "journal_file_lock" not in called
    assert "dependency_pins_live" in source
    assert 'transaction.state != "released"' in source
    assert 'transaction.state != "acquired"' in source

    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    for symbol in (
        "PackageRetentionHandoffOwner",
        "PackageRetentionHandoffJournal",
        "PackageRetentionSettlementPort",
        "PackageDesiredStateCommitPort",
        "PackageRetentionHandoffRequestV1",
    ):
        assert symbol not in internal_facade
        assert symbol not in package_facade
        assert symbol not in author_sdk

    for evidence in (
        "test_b4b_retention_handoff_contract_is_dark_and_versioned",
        "test_handoff_journal_rejects_duplicate_json_keys_with_stable_error",
    ):
        assert evidence in component_tests
    for evidence in (
        "settle_postcommit_crashes",
        "zero_pin_observed",
        "expected_receipt=opened",
        "physical_acquisitions == 1",
        "physical_settlements == 1",
        "physical_commits == 1",
    ):
        assert evidence in adversarial_tests
    assert "IMPLEMENTED_B4B_RETENTION_HANDOFF_MANIFEST_CASES" in adversarial_tests
    assert (
        _implemented_b4b_retention_handoff_manifest_cases()
        == PLC9B4B_RETENTION_HANDOFF_CASES
    )
    policies = {
        "B-HANDOFF-BEFORE-DESIRED": (
            "handoff_attempt",
            "append_once:retryable_failure_then_no_append",
        ),
        "B-HANDOFF-AFTER-DESIRED": (
            "handoff_attempt",
            "append_once:retryable_failure_then_no_append",
        ),
        "B-HANDOFF-AFTER-SETTLEMENT": ("none", "no_append:unchanged"),
        "B-HANDOFF-DESIRED-REJECT": (
            "handoff",
            "append_once:aborted_then_no_append",
        ),
        "B-HANDOFF-STALE-RECEIPT": ("none", "no_append:unchanged"),
        "B-HANDOFF-CONCURRENT-REPLAY": (
            "handoff",
            "append_once:settled_then_no_append",
        ),
    }
    for case_id in PLC9B4B_RETENTION_HANDOFF_CASES:
        row = manifest[case_id]
        assert row["status"] == "implemented"
        assert _journal_policy_for(case_id) == policies[case_id]
        assert {"exact_pin_set", "no_zero_pin"} <= set(row["oracles"].split(";"))

    normalized = " ".join(contract.split())
    assert "PLC9B.5-accepted." in contract
    assert "PLC9B4b Accepted Retention Handoff" in normalized
    assert "opened -> dependency_pinned -> desired_committed -> settled" in normalized
    assert "No journal lock is held" in normalized
    assert "process stops before the local settled projection" in normalized
    assert "PLC9B4b accepted code adds the dark retention-handoff" in inventory
    assert "PLC9B4b accepted code adds strict Desired-CAS" in index
    assert "B4b was accepted on 2026-09-01 against candidate head `282b4af7`" in (
        normalized
    )
    assert "Harness Quality run `33571393925`" in normalized
    assert "Linux harness job `100065909160`" in normalized
    assert "artifact ID `9825049355`" in normalized
    assert (
        "311c66abff263261b430955ea1aef27bef58db3a0a74079593e40d9909846974" in normalized
    )
    assert "executed exactly 88 manifest nodes" in normalized
    assert "B4c native cutover remains the next closed gate" in normalized


def test_plc9b4c0_epoch_admission_is_dark_read_only_and_fail_closed() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(EPOCH_FENCE)
    component_tests = _source(EPOCH_FENCE_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    manifest = _adversarial_manifest()

    assert EPOCH_FENCE.is_file()
    assert EPOCH_FENCE_TEST.is_file()
    for symbol in (
        "PackageEpochFenceRequestV1",
        "PackageEpochFenceReceiptV1",
        "PackageEpochFenceRecordV1",
        "PackageEpochRuntimeLeaseV1",
        "PackageEpochLeaseSnapshotV1",
        "PackageEpochRuntimeAdmissionRequestV1",
        "PackageEpochRuntimeAdmissionReceiptV1",
        "PackageEpochRuntimeAdmissionFailureV1",
        "PackageEpochRuntimeAdmissionResultV1",
        "PackageEpochFenceReadPort",
        "PackageEpochLeaseSnapshotPort",
        "PackageEpochFenceJournal",
        "PackageEpochRuntimeAdmissionOwner",
    ):
        assert symbol in source

    tree = ast.parse(source, filename=str(EPOCH_FENCE))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins.revisions",
        "loushang.coding",
        "loushang.foundation",
        "os",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for forbidden_symbol in (
        "PluginPackageLifecycleLedger",
        "PluginDesiredStateLedger",
        "PackageMaterializer",
        "VerifiedRevisionHandle",
    ):
        assert forbidden_symbol not in source

    visitor = _QualifiedFunctionVisitor()
    visitor.visit(tree)
    admit = dict(visitor.functions)["PackageEpochRuntimeAdmissionOwner.admit"]
    called = {
        call.func.attr
        if isinstance(call.func, ast.Attribute)
        else call.func.id
        if isinstance(call.func, ast.Name)
        else ""
        for call in ast.walk(admit)
        if isinstance(call, ast.Call)
    }
    assert {"current", "snapshot"} <= called
    assert "publish" not in called
    assert "journal_file_lock" not in called

    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    for symbol in (
        "PackageEpochFenceJournal",
        "PackageEpochRuntimeAdmissionOwner",
        "PackageEpochFenceReadPort",
        "PackageEpochLeaseSnapshotPort",
        "PackageEpochRuntimeAdmissionRequestV1",
    ):
        assert symbol not in internal_facade
        assert symbol not in package_facade
        assert symbol not in author_sdk

    for evidence in (
        "test_b4c0_epoch_contract_is_dark_versioned_and_exactly_replayable",
        "test_epoch_runtime_admission_rejects_newer_epoch_before_lease_authority",
        "test_epoch_runtime_admission_rejects_mixed_active_epoch_without_mutation",
        "test_epoch_runtime_admission_accepts_exact_current_single_epoch_snapshot",
        "test_epoch_runtime_admission_rechecks_fence_after_lease_snapshot",
        "test_epoch_runtime_admission_rejects_invalid_lease_owner_projection",
        "test_epoch_journal_concurrent_exact_publish_appends_each_epoch_once",
        "test_epoch_journal_repairs_only_an_incomplete_final_record",
        "test_epoch_journal_rejects_duplicate_json_keys_with_stable_error",
    ):
        assert evidence in component_tests
    assert "IMPLEMENTED_B4C0_EPOCH_ADMISSION_MANIFEST_CASES" in adversarial_tests
    assert (
        _implemented_b4c0_epoch_admission_manifest_cases()
        == PLC9B4C0_EPOCH_ADMISSION_CASES
    )
    for case_id in PLC9B4C0_EPOCH_ADMISSION_CASES:
        row = manifest[case_id]
        assert row["status"] == "implemented"
        assert row["code"] == "package_runtime_epoch_unsupported"
        assert _journal_policy_for(case_id) == ("none", "no_append:unchanged")
        assert {"no_publication", "no_peer_fallback"} <= set(row["oracles"].split(";"))

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c0 Accepted Epoch Admission" in normalized
    assert "human-readable minimum runtime version is diagnostic evidence" in (
        normalized
    )
    assert "checks the exact fence, root identity, runtime epoch" in normalized
    assert "durable fence is read again after the lease snapshot" in normalized
    assert "B-COMPAT-EPOCH` and `B-COMPAT-MIXED` are executable" in normalized
    assert "mypy passed over 642 source files" in normalized
    assert "pytest completed 3,824 tests" in normalized
    assert "137-test focused regression" in normalized
    assert "Candidate `18f0bab8` passed all 23 PR checks" in normalized
    assert "Harness Quality run `33576206559`" in normalized
    assert "Linux job `100080609111`" in normalized
    assert "retained artifact `9826705491`" in normalized
    assert "exactly 90 manifest nodes" in normalized
    assert "zero skips, failures, or errors" in normalized
    assert "Accepted PLC9B4c0 code adds an evidence-only" in inventory
    assert "Accepted PLC9B4c0 code adds the dark adjacent" in index


def test_plc9b4c1_posix_cutover_has_one_native_owner_and_one_visibility_edge() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(POSIX_EPOCH_CUTOVER)
    component_tests = _source(POSIX_EPOCH_CUTOVER_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    manifest = _adversarial_manifest()

    assert POSIX_EPOCH_CUTOVER.is_file()
    assert POSIX_EPOCH_CUTOVER_TEST.is_file()
    for symbol in (
        "PackageEpochCutoverQuiescenceReceiptV1",
        "PackageEpochCutoverSnapshotReceiptV1",
        "PackageEpochCutoverCoordinationPort",
        "PackageEpochCutoverSnapshotPort",
        "PackagePosixEpochCutoverRequestV1",
        "PackagePosixEpochRootSwitchReceiptV1",
        "PackagePosixEpochCutoverFailureV1",
        "PackagePosixEpochCutoverResultV1",
        "PackagePosixEpochCutoverOwner",
    ):
        assert symbol in source

    tree = ast.parse(source, filename=str(POSIX_EPOCH_CUTOVER))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins",
        "loushang.coding",
        "loushang.foundation",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for forbidden_symbol in (
        "PluginPackageLifecycleLedger",
        "PluginDesiredStateLedger",
        "PackageMaterializer",
        "subprocess",
        "active-root",
    ):
        assert forbidden_symbol not in source
    assert "os.O_NOFOLLOW" in source
    assert "dir_fd=epochs_fd" in source
    assert "os.fsync" in source
    assert "self._journal.publish(epoch_request)" in source

    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    for symbol in (
        "PackagePosixEpochCutoverOwner",
        "PackagePosixEpochCutoverRequestV1",
        "PackageEpochCutoverCoordinationPort",
        "PackageEpochCutoverSnapshotPort",
    ):
        assert symbol not in internal_facade
        assert symbol not in package_facade
        assert symbol not in author_sdk

    for evidence in (
        "test_posix_cutover_uses_epoch_append_as_the_only_atomic_root_pointer",
        "test_posix_cutover_advances_only_from_the_exact_current_namespace",
        "test_posix_cutover_concurrent_exact_requests_converge_once",
        "test_posix_cutover_refuses_live_pre_fence_writer_before_native_mutation",
        "test_posix_cutover_refuses_fence_aware_live_lease_without_append",
        "test_posix_cutover_rejects_precreated_namespace_without_trusting_it",
        "test_posix_cutover_detects_authority_root_swap_before_fence_and_cleans_residue",
        "test_posix_cutover_detects_epochs_directory_swap_before_fence",
        "test_posix_cutover_detects_authority_permission_drift_before_fence",
        "test_posix_cutover_releases_every_native_descriptor",
        "test_posix_cutover_records_reject_extended_or_forged_wire_values",
    ):
        assert evidence in component_tests
    assert "IMPLEMENTED_B4C1_POSIX_EPOCH_CUTOVER_MANIFEST_CASES" in (adversarial_tests)
    assert (
        _implemented_b4c1_posix_epoch_cutover_manifest_cases()
        == PLC9B4C1_POSIX_EPOCH_CUTOVER_CASES
    )
    assert manifest["B-COMPAT-CUTOVER-POSIX"]["status"] == "implemented"
    assert manifest["B-COMPAT-PREFENCE-LIVE-POSIX"]["status"] == "implemented"
    assert _journal_policy_for("B-COMPAT-CUTOVER-POSIX") == (
        "epoch",
        "append_once:epoch_fenced_then_no_append",
    )
    assert _journal_policy_for("B-COMPAT-PREFENCE-LIVE-POSIX") == (
        "none",
        "no_append:unchanged",
    )
    for case_id in (
        "B-COMPAT-CUTOVER-WINDOWS",
        "B-COMPAT-PREFENCE-LIVE-WINDOWS",
    ):
        assert manifest[case_id]["status"] == "implemented"

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c1 Accepted POSIX Native Cutover" in normalized
    assert "no second `active-root` file" in normalized
    assert "sole Product-root pointer" in normalized
    assert "before snapshot access, namespace creation, or epoch append" in normalized
    assert "expected collection from 90 to 92" in normalized
    assert "concrete snapshot/restore store" in normalized
    assert "mypy passed over 643 source files" in normalized
    assert "pytest completed 3,837 tests" in normalized
    assert "142-test focused regression" in normalized
    assert "exact test passed in isolation" in normalized
    assert "subsequent complete gate passed" in normalized
    assert "B4c1 was accepted on 2026-09-02 against candidate head `e99945d2`" in (
        normalized
    )
    assert "Harness Quality run `33581165668`" in normalized
    assert "Linux job `100095571513`" in normalized
    assert "retained artifact `9828433273`" in normalized
    assert (
        "b0b616a4e408d8b2b959d9d736d232c26892dc42c3132f4001b0eb0e7c9de2e3" in contract
    )
    assert "exactly 92 manifest nodes" in normalized
    assert "zero skips, failures, or errors" in normalized
    assert "PLC9B4c1 accepted code adds the dark POSIX-native" in inventory
    assert "PLC9B4c1 accepted code adds a dark POSIX-native" in index


def test_plc9b4c2_windows_cutover_is_rooted_native_and_non_skippable() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(WINDOWS_EPOCH_CUTOVER)
    component_tests = _source(WINDOWS_EPOCH_CUTOVER_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    workflow = _source(WINDOWS_WORKFLOW)
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert WINDOWS_EPOCH_CUTOVER.is_file()
    assert WINDOWS_EPOCH_CUTOVER_TEST.is_file()
    for symbol in (
        "PackageWindowsEpochCutoverError",
        "PackageWindowsEpochCutoverRequestV1",
        "PackageWindowsEpochRootSwitchReceiptV1",
        "PackageWindowsEpochCutoverFailureV1",
        "PackageWindowsEpochCutoverResultV1",
        "PackageWindowsEpochCutoverOwner",
    ):
        assert symbol in source
    for rooted_primitive in (
        "open_windows_directory",
        "windows_flush_directory",
        "windows_listdir_at",
        "windows_rmdir_at",
    ):
        assert rooted_primitive in source
    assert "self._journal.publish(epoch_request)" in source
    assert "PackageWindowsEpochCutoverRequestV1: TypeAlias" in source
    assert "NtFlushBuffersFileEx" in _source(WINDOWS_QUARANTINE)
    assert "PackagePosixEpochCutoverOwner" not in source
    assert "active-root" not in source

    tree = ast.parse(source, filename=str(WINDOWS_EPOCH_CUTOVER))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins",
        "loushang.coding",
        "loushang.foundation",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for symbol in (
        "PackageWindowsEpochCutoverOwner",
        "PackageWindowsEpochCutoverRequestV1",
    ):
        assert symbol not in internal_facade
        assert symbol not in package_facade
        assert symbol not in author_sdk

    for evidence in (
        "test_windows_cutover_uses_epoch_append_as_the_only_atomic_root_pointer",
        "test_windows_cutover_advances_only_from_the_exact_current_namespace",
        "test_windows_cutover_concurrent_exact_requests_converge_once",
        "test_windows_cutover_refuses_live_writer_before_native_mutation",
        "test_windows_cutover_rejects_precreated_namespace_without_trusting_it",
        "test_windows_cutover_blocks_namespace_swap_and_cleans_residue",
        "test_windows_cutover_releases_every_native_descriptor",
        "test_windows_cutover_records_reject_extended_or_forged_wire_values",
    ):
        assert evidence in component_tests
    assert "IMPLEMENTED_B4C2_WINDOWS_EPOCH_CUTOVER_MANIFEST_CASES" in (
        adversarial_tests
    )
    assert (
        _implemented_b4c2_windows_epoch_cutover_manifest_cases()
        == PLC9B4C2_WINDOWS_EPOCH_CUTOVER_CASES
    )
    for case_id in PLC9B4C2_WINDOWS_EPOCH_CUTOVER_CASES:
        assert manifest[case_id]["status"] == "implemented"
        assert manifest[case_id]["platform"] == "windows-native"
        assert manifest[case_id]["workflow"].startswith(
            "windows-shell-compatibility.yml#"
        )
        assert f"test_manifest_case[{case_id}]" in workflow
    assert "tests/harness/resources/packages/test_plc9b_windows_epoch_cutover.py" in (
        workflow
    )
    assert workflow.count("scripts/dev/verify_pytest_xml.py") >= 5

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c2 Accepted Windows Native Cutover" in normalized
    assert "same fingerprint domain" in normalized
    assert "rooted `NtCreateFile`" in normalized
    assert "there is no second `active-root` file" in normalized
    assert "Linux collection skips it" in normalized
    assert "B4c3 still owns complete offline restore" in normalized
    assert "mypy passed over 644 source files" in normalized
    assert "pytest completed 3,837 tests with 33 expected skips" in normalized
    assert "132-passed, 10-skipped focused regression" in normalized
    assert "B4c2 was accepted on 2026-09-02 against candidate head `3d5d4394`" in (
        normalized
    )
    assert "after all 23 PR checks passed" in normalized
    assert "Windows Shell Compatibility run `33584494760`" in normalized
    assert "native job `100105659525`" in normalized
    assert "retained artifact `9829593062`" in normalized
    assert (
        "2967396b3f0888379f6dbda3504c8dd4ee465b61e35fff36ad1f91f0f3a76e5a" in normalized
    )
    assert "executed exactly 29 tests, including all ten B4c2" in normalized
    assert "executed exactly 14 nodes" in normalized
    assert "PLC9B4c2 accepted code adds the corresponding dark" in inventory
    assert "PLC9B4c2 accepted code adds the symmetric dark" in index


def test_plc9b4c3a_offline_restore_stays_dark_and_unpromoted() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(OFFLINE_RESTORE)
    component_tests = _source(OFFLINE_RESTORE_TEST)
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert OFFLINE_RESTORE.is_file()
    assert OFFLINE_RESTORE_TEST.is_file()
    for symbol in (
        "PackageOfflineRestoreSnapshotEvidenceV1",
        "PackageOfflineRestoreRequestV1",
        "PackageOfflineRestoreMaterializationReceiptV1",
        "PackageLegacyRuntimeActivationReceiptV1",
        "PackageOfflineRestoreFailureV1",
        "PackageOfflineRestoreResultV1",
        "PackageOfflineRestoreSnapshotEvidencePort",
        "PackageOfflineRestoreMaterializationPort",
        "PackageLegacyRuntimeActivationPort",
        "PackageOfflineRestoreOwner",
    ):
        assert f"class {symbol}" in source
        assert symbol not in internal_facade
        assert symbol not in package_facade
        assert symbol not in author_sdk

    tree = ast.parse(source, filename=str(OFFLINE_RESTORE))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    for forbidden in (
        "os",
        "pathlib",
        "subprocess",
        "loushang.coding",
        "loushang.harness.plugin_management",
        "loushang.plugin",
    ):
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imported
        )
    for forbidden_capability in (
        "PackageMaterializer",
        "PackageOperationsRuntime",
        "PluginRevisionStore",
        "PackageRetentionHandoffOwner",
        "PackageCommitLifecycleOwner",
        "PackageLifecycleOwner",
        "self._journal.publish",
    ):
        assert forbidden_capability not in source

    assert "PACKAGE_PRE_B_SNAPSHOT_DOMAINS" in source
    for domain in (
        "store_bytes",
        "source_configuration",
        "lock_history",
        "binding_history",
        "desired_state",
        "instance_state",
        "enablement_state",
        "legacy_root_pointer",
        "fence_record",
    ):
        assert f'"{domain}"' in source
    assert "with exclusive as quiescence" in source
    assert source.count("not self._fences_match(request)") == 3
    assert "self._deactivate(activation)" in source
    assert "self._discard(materialization)" in source
    assert "legacy_snapshot_exact" in source
    assert "b_namespace_unreachable" in source

    for evidence in (
        "binds_genesis_snapshot_and_exactly_replays",
        "refuses_live_writer_before_snapshot_or_restore",
        "rejects_stale_current_fence_before_effect",
        "rejects_snapshot_substitution_under_exclusive_lock",
        "discards_isolated_tree_when_epoch_drifts",
        "deactivates_mismatched_old_runtime_and_discards_tree",
        "deactivates_runtime_and_discards_tree_when_epoch_drifts",
        "concurrent_exact_requests_converge_on_one_effect",
        "wire_records_reject_extensions_and_forgery",
    ):
        assert evidence in component_tests

    assert (
        manifest["B-COMPAT-OFFLINE-RESTORE-WINDOWS"]["status"] == "implemented"
    )
    assert manifest["B-COMPAT-ADOPT"]["status"] == "implemented"
    assert "IMPLEMENTED_B4C3" not in component_tests

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c3a Accepted Offline Restore Protocol" in normalized
    assert "does not reinterpret the opaque B4c1 snapshot identifier" in normalized
    assert "closed coverage tuple" in normalized
    assert "deliberately supplied no POSIX or Windows filesystem materializer" in (
        normalized
    )
    assert "all five `B-COMPAT-ADOPT*` rows remain planned" in normalized
    assert "PLC9B4c3a accepted code adds strict offline-restore" in inventory
    assert "PLC9B4c3a accepted code adds the dark, pathless" in index


def test_plc9b4c3b_posix_materializer_is_rooted_exact_and_dark() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(POSIX_OFFLINE_RESTORE)
    component_tests = _source(POSIX_OFFLINE_RESTORE_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    workflow = _source(HARNESS_WORKFLOW)
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert POSIX_OFFLINE_RESTORE.is_file()
    assert POSIX_OFFLINE_RESTORE_TEST.is_file()
    assert "class PackagePosixOfflineRestoreMaterializer" in source
    for rooted_primitive in (
        "O_NOFOLLOW",
        "dir_fd=",
        "_PinnedRoot",
        "_rename_directory_noreplace",
        "flock",
        "os.fsync",
    ):
        assert rooted_primitive in source
    for invariant in (
        "PACKAGE_PRE_B_SNAPSHOT_DOMAINS",
        "snapshot_tree_digest",
        "state_manifest_digest",
        "current_b_authority_root",
        "PackageOfflineRestoreMaterializationReceiptV1.create",
        "_directory_identity",
        "package_offline_restore_cleanup_failed",
    ):
        assert invariant in source
    assert "__all__ = ()" in source

    tree = ast.parse(source, filename=str(POSIX_OFFLINE_RESTORE))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden_modules = (
        "loushang.harness.plugin_management",
        "loushang.harness.resources.plugins",
        "loushang.coding",
        "loushang.foundation",
        "subprocess",
    )
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_modules
    )
    for forbidden_capability in (
        "PackageEpochFenceJournal",
        "PackageLifecycleOwner",
        "PackageMaterializer",
        "PackageOperationsRuntime",
        "PluginRevisionStore",
        "self._journal.publish",
        "subprocess",
    ):
        assert forbidden_capability not in source
    for symbol in ("PackagePosixOfflineRestoreMaterializer",):
        assert symbol not in internal_facade
        assert symbol not in package_facade
        assert symbol not in author_sdk

    for evidence in (
        "materializes_exact_isolated_tree_and_replays",
        "rejects_substituted_snapshot_without_residue",
        "rejects_aliased_or_special_snapshot_member",
        "rejects_extended_snapshot_bundle",
        "rejects_oversized_snapshot_metadata",
        "rejects_foreign_precreated_namespace",
        "rejects_untrusted_lock_permissions",
        "atomic_publish_rejects_racing_namespace",
        "cleans_exact_namespace_after_injected_failure",
        "reports_cleanup_debt_without_deleting_unknown_state",
        "concurrent_owners_converge_on_one_tree",
        "cross_process_lock_publishes_only_once",
        "discard_removes_only_exact_owned_tree",
        "discard_fails_closed_after_tree_tamper",
        "rejects_noncanonical_durable_receipt",
        "revalidates_authority_before_publish",
        "revalidates_current_b_after_final_tree_check",
        "requires_request_bound_current_b_identity",
        "rejects_configured_authority_replacement",
        "rejects_nested_authorities",
        "rejects_nonprivate_authority",
        "rejects_current_b_nested_in_restore_authority",
        "rejects_snapshot_over_configured_budget_before_effect",
        "rejects_tree_over_configured_depth",
        "closes_source_descriptor_when_target_open_fails",
        "releases_native_descriptors",
    ):
        assert evidence in component_tests
    assert "IMPLEMENTED_B4C3C_LINUX_OFFLINE_RESTORE_MANIFEST_CASES" in (
        adversarial_tests
    )
    assert "test_posix_offline_restore_candidate_composes_pathless_protocol" in (
        component_tests
    )
    assert "candidate_discards_real_tree_after_fence_drift" in component_tests
    row = manifest["B-COMPAT-OFFLINE-RESTORE-POSIX"]
    assert row["status"] == "implemented"
    assert row["platform"] == "posix-native"
    assert row["workflow"] == "harness-quality.yml#plc9b-linux-native"
    assert _journal_policy_for("B-COMPAT-OFFLINE-RESTORE-POSIX") == (
        "none",
        "no_append:unchanged",
    )
    assert {
        "single_owner",
        "legacy_snapshot_exact",
        "b_namespace_unreachable",
        "no_peer_fallback",
        "no_skip",
    } <= set(row["oracles"].split(";"))
    assert "tests/harness/resources/packages/test_plc9b_adversarial.py" in workflow
    assert "scripts/dev/verify_pytest_xml.py" in workflow
    assert manifest["B-COMPAT-OFFLINE-RESTORE-WINDOWS"]["status"] == "implemented"
    assert manifest["B-COMPAT-ADOPT"]["status"] == "implemented"

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c3b Accepted POSIX Offline Restore Materialization" in normalized
    assert "authenticated snapshot authority" in normalized
    assert "requires its native directory identity" in normalized
    assert "process-level unreachability remains" in normalized
    assert "entry, byte, and depth limits" in normalized
    assert "atomic no-replace visibility edge" in normalized
    assert "does not launch a legacy process" in normalized
    assert "remains at 92 manifest nodes" in normalized
    assert "not proof that an old-runtime process started" in normalized
    assert "PLC9B4c3b accepted code adds the dark POSIX-native" in inventory
    assert "PLC9B4c3b accepted code adds rooted POSIX" in index


def test_plc9b4c3c_linux_activation_is_native_exclusive_dark_and_promoted() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(LINUX_LEGACY_RUNTIME)
    component_tests = _source(POSIX_OFFLINE_RESTORE_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    workflow = _source(HARNESS_WORKFLOW)
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    sandbox_facade = _source(Path("src/loushang/harness/sandbox/__init__.py"))
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert LINUX_LEGACY_RUNTIME.is_file()
    assert "class PackageLinuxLegacyRuntimeActivationOwner" in source
    assert LINUX_LEGACY_RUNTIME.parent == Path("src/loushang/harness/sandbox")
    assert "def _prepare_guarded_command(" in _source(
        Path("src/loushang/harness/sandbox/backends/linux.py")
    )
    for invariant in (
        "LinuxBubblewrapBackend",
        "SandboxScopeRequest",
        "subprocess.Popen",
        "LOUSHANG_LEGACY_RUNTIME_READY_FD",
        "flock",
        "/proc/{marker.sandbox.pid}/root",
        "_process_children",
        "_namespace_identity",
        "_open_matching_pidfd",
        "_spawn_guarded_process",
        "_directory_identity(payload_fd)",
        "package_offline_restore_cleanup_failed",
    ):
        assert invariant in source
    for namespace in ("mnt", "pid", "net", "ipc", "uts", "user"):
        assert f'"{namespace}"' in source
    for forbidden_capability in (
        "PackageEpochFenceJournal",
        "PackageLifecycleOwner",
        "PackageMaterializer",
        "PackageOperationsRuntime",
        "PluginRevisionStore",
        "self._journal.publish",
        "loushang.coding",
        "loushang.foundation",
        "loushang.harness.plugin_management",
    ):
        assert forbidden_capability not in source
    assert "__all__ = ()" in source
    for facade in (internal_facade, sandbox_facade, package_facade, author_sdk):
        assert "PackageLinuxLegacyRuntimeActivationOwner" not in facade

    for evidence in (
        "activates_replays_and_deactivates_real_process",
        "rejects_missing_readiness_without_process_residue",
        "rejects_second_sandbox_profile_while_active",
        "rejects_restore_over_independent_activation_budget",
        "tampered_marker_refuses_cleanup_without_signalling",
        "concurrent_owners_publish_one_live_process",
        "native_process_composition_converges_exactly",
    ):
        assert evidence in component_tests
    assert "IMPLEMENTED_B4C3C_LINUX_OFFLINE_RESTORE_MANIFEST_CASES" in (
        adversarial_tests
    )
    assert "_manifest_linux_offline_restore_fixture" in adversarial_tests
    row = manifest["B-COMPAT-OFFLINE-RESTORE-POSIX"]
    assert row["status"] == "implemented"
    assert row["platform"] == "posix-native"
    assert row["workflow"] == "harness-quality.yml#plc9b-linux-native"
    assert "Install PLC9B Linux native isolation dependency" in workflow
    assert "sudo apt-get install --yes bubblewrap" in workflow
    assert workflow.index("sudo apt-get install --yes bubblewrap") < workflow.index(
        "PLC9B Linux native adversarial gate (plc9b-linux-native)"
    )
    assert manifest["B-COMPAT-OFFLINE-RESTORE-WINDOWS"]["status"] == "implemented"
    assert manifest["B-COMPAT-ADOPT"]["status"] == "implemented"

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c3c Accepted Linux Legacy Runtime Activation" in normalized
    assert "owned by `loushang.harness.sandbox`" in normalized
    assert "the resource kernel remains backend-free" in inventory
    assert "single real sandbox child" in normalized
    assert "distinct mount, PID, network, IPC, UTS, and user namespaces" in normalized
    assert "The Linux manifest now contains 93 nodes" in normalized
    assert "3,890 tests with 33 expected platform skips" in normalized
    assert "PLC9B4c3c accepted code adds the concrete Linux/Bubblewrap" in inventory
    assert "PLC9B4c3c accepted code adds one dark Linux/Bubblewrap" in index


def test_plc9b4c4a_adoption_protocol_is_pathless_and_stays_internal() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(LEGACY_ADOPTION)
    component_tests = _source(LEGACY_ADOPTION_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    management_facade = _source(PACKAGE_LIFECYCLE)
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert LEGACY_ADOPTION.is_file()
    assert LEGACY_ADOPTION_TEST.is_file()
    for symbol in (
        "PackageLegacyStateEvidenceV1",
        "PackageLegacyAdoptionRequestV1",
        "PackageLegacyAdoptionTransactionResultV1",
        "PackageLegacyAdoptionReceiptV1",
        "PackageLegacyAdoptionFailureV1",
        "PackageLegacyAdoptionResultV1",
        "PackageLegacyStateEvidencePort",
        "PackageLegacyAdoptionTransactionPort",
        "PackageLegacyAdoptionOwner",
    ):
        assert f"class {symbol}" in source
        assert symbol not in internal_facade
        assert symbol not in package_facade
        assert symbol not in management_facade
        assert symbol not in author_sdk

    tree = ast.parse(source, filename=str(LEGACY_ADOPTION))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    for forbidden in (
        "os",
        "pathlib",
        "socket",
        "subprocess",
        "urllib",
        "httpx",
        "requests",
        "loushang.coding",
        "loushang.foundation",
        "loushang.harness.plugin_management",
    ):
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imported
        )
    for invariant in (
        "PACKAGE_PRE_B_SNAPSHOT_DOMAINS",
        "transaction_request_fingerprint",
        "expected_classification_fingerprint",
        "expected_attempt_epoch",
        "PackagePublicationReceiptV1",
        'classification.decision != "plugin_bound"',
        "after != before",
        "_transaction_matches_request",
        "__all__ = ()",
    ):
        assert invariant in source
    assert source.count("self._fence_matches(request)") == 2
    assert source.count("self._legacy_state.observe(") == 2

    for evidence in (
        "replays_exact_committed_receipt_without_legacy_mutation",
        "rejects_stale_fence_before_legacy_or_transaction",
        "rejects_legacy_root_outside_current_fence",
        "rejects_changed_legacy_before_transaction",
        "rejects_changed_classification_evidence",
        "rejects_legacy_drift_after_transaction",
        "rejects_fence_drift_after_transaction",
        "preserves_transaction_failure_semantics",
        "preserves_cancelled_transaction_as_rejection",
        "rejects_cross_request_transaction_result",
        "concurrent_replay_converges_to_one_receipt",
        "rejects_extended_wire_objects",
    ):
        assert evidence in component_tests

    assert manifest["B-COMPAT-ADOPT"]["status"] == "implemented"
    assert "IMPLEMENTED_B4C4D_LINUX_ADOPTION_MANIFEST_CASES" in adversarial_tests

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c4a Accepted Legacy Adoption Protocol" in normalized
    assert "complete immutable legacy-state observation" in normalized
    assert "does not itself reacquire, stage, publish, or commit" in normalized
    assert "all five adoption manifest rows remain planned" in normalized
    assert "57 focused adoption/architecture tests" in normalized
    assert "105 cross-module lifecycle" in normalized
    assert "mypy over 648 source files" in normalized
    assert "3,903 tests with 33 expected platform skips" in normalized
    assert "PLC9B4c4a accepted code adds the dark, pathless" in inventory
    assert "PLC9B4c4a accepted code freezes a dark, pathless" in index


def test_plc9b4c4c_pinned_reacquisition_is_evidence_only_and_stays_dark() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(LEGACY_ADOPTION_TRANSACTION)
    component_tests = _source(LEGACY_ADOPTION_TRANSACTION_TEST)
    artifact_source = _source(ARTIFACT_RUNTIME)
    closure_owner_source = _source(CLOSURE_OWNER)
    closure_runtime_source = _source(CLOSURE_RUNTIME)
    artifact_tests = _source(ARTIFACT_RUNTIME_TEST)
    closure_owner_tests = _source(CLOSURE_OWNER_TEST)
    closure_tests = _source(CLOSURE_RUNTIME_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    management_facade = _source(PACKAGE_LIFECYCLE)
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert LEGACY_ADOPTION_TRANSACTION.is_file()
    assert LEGACY_ADOPTION_TRANSACTION_TEST.is_file()
    for symbol in (
        "PackageLegacyClosureExecutionPort",
        "PackageLegacyPinExecutionPort",
        "PackageLegacyStagingExecutionPort",
        "PackageLegacyCommitExecutionPort",
        "PackageLegacyAdoptionTransactionAdapter",
    ):
        assert f"class {symbol}" in source
        assert symbol not in internal_facade
        assert symbol not in package_facade
        assert symbol not in management_facade
        assert symbol not in author_sdk

    tree = ast.parse(source, filename=str(LEGACY_ADOPTION_TRANSACTION))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    for forbidden in (
        "os",
        "pathlib",
        "socket",
        "subprocess",
        "urllib",
        "httpx",
        "requests",
        "loushang.coding",
        "loushang.foundation",
        "loushang.harness.plugin_management",
        "loushang.harness.sandbox",
    ):
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imported
        )
    for invariant in (
        "PackageClosureExecutionRequestV2",
        "PackageCommitEvidenceError",
        "_CLOSURE_PHASES",
        "_STAGING_RECOVERY_PHASES",
        "self._kernel.status(request.operation_id)",
        "lifecycle_request.product_id == request.product_id",
        "lifecycle_request.scope_id == request.scope_id",
        "lifecycle_request.requested_plugin_id == request.plugin_id",
        "request.expected_classification_fingerprint",
        "self._closure.reacquire(self._execution)",
        "self._staging.authorize_adoption(request) is not True",
        "adoption_request=request",
        "__all__ = ()",
    ):
        assert invariant in source
    assert "def __repr__" not in source
    assert source.index("self._closure.execute") < source.index("self._pins.pin")
    assert source.index("self._pins.pin") < source.index(
        "self._staging.stage_and_publish"
    )
    assert source.index("self._staging.stage_and_publish") < source.index(
        "self._commit.commit"
    )

    for evidence in (
        "composes_exact_complete_b_sequence_and_replays",
        "preserves_acquisition_failure_without_later_effects",
        "refuses_product_substitution_before_effect",
        "resumes_set_published_without_prior_phase_replay",
        "reacquires_bare_transaction_pin_and_commits",
        "resumes_staging_after_receipts_are_durable",
        "suspends_candidate_when_staging_crashes",
        "crash_after_commit_replays_without_prior_effects",
        "rejects_phase_result_not_owned_by_kernel",
    ):
        assert evidence in component_tests

    assert manifest["B-COMPAT-ADOPT"]["status"] == "implemented"
    assert "IMPLEMENTED_B4C4D_LINUX_ADOPTION_MANIFEST_CASES" in adversarial_tests

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c4b Accepted Adoption Transaction Adapter" in normalized
    assert "PLC9B4c4c Accepted Pinned-Candidate Reacquisition" in normalized
    assert "one-operation least-authority capability" in normalized
    assert "closure -> pin -> staging/set -> commit" in normalized
    assert "journal-confirmed status after every owner return" in normalized
    assert "It is not a second download" in normalized
    assert "never falling back to resolver or Source authority" in normalized
    assert "all five adoption manifest rows remain planned" in normalized
    assert "69 focused adoption/architecture tests" in normalized
    assert "116 cross-module lifecycle tests" in normalized
    assert "mypy over 649 source files" in normalized
    assert "3,914 tests with 33 expected platform skips" in normalized
    assert "PLC9B4c4b accepted code composes the existing" in inventory
    assert "PLC9B4c4b accepted code adds a one-operation" in index
    assert "PLC9B4c4c accepted code adds explicit recovery-only" in inventory
    assert "PLC9B4c4c accepted code supplies that seam" in index
    assert "def reacquire(" in artifact_source
    assert 'status.phase != "transaction_pinned"' in artifact_source
    assert "self._acquisition_owner.reopen_acquired" in artifact_source
    assert "def reacquire(" in closure_owner_source
    assert "durable_only=True" in closure_owner_source
    assert "if durable_only:" in closure_owner_source
    assert "def reacquire(" in closure_runtime_source
    assert "durable_basis != expected_basis" in closure_runtime_source
    assert "revalidated_plan != durable_plan" in closure_runtime_source
    assert "closure.plan != revalidated_plan" in closure_runtime_source
    assert "kernel.status(status.operation_id) == status" in artifact_tests
    assert "evidence_is_incomplete" in artifact_tests
    assert "never_falls_back_to_resolver_or_source" in closure_owner_tests
    assert "without_journal_mutation" in closure_tests
    assert "without_durable_plan" in closure_tests
    assert "revalidates_resolution_journal_after_reacquisition" in closure_tests
    assert "authority.payloads.clear()" in closure_tests
    assert "resolver.selections.clear()" in closure_tests


def test_plc9b4c4d_positive_adoption_uses_native_composition_and_is_promoted() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    workflow = _source(HARNESS_WORKFLOW)
    manifest = _adversarial_manifest()

    row = manifest["B-COMPAT-ADOPT"]
    assert row["status"] == "implemented"
    assert row["platform"] == "posix-native"
    assert row["workflow"] == "harness-quality.yml#plc9b-linux-native"
    assert {
        "same_receipt",
        "pin_visible",
        "legacy_snapshot_exact",
        "desired_unchanged",
        "instance_unchanged",
        "binding_unchanged",
        "enablement_unchanged",
        "no_skip",
    } == set(row["oracles"].split(";"))
    for evidence in (
        "IMPLEMENTED_B4C4D_LINUX_ADOPTION_MANIFEST_CASES",
        "_manifest_native_adoption_fixture",
        "PackageLegacyAdoptionOwner",
        "PackageLegacyAdoptionTransactionAdapter",
        "PackageClosureLifecycleOwner",
        "PackageTransactionPinLifecycleOwner",
        "PosixPackagePluginRootMaterializationStore",
        "PackageStagingSetLifecycleOwner",
        "PackageCommitLifecycleOwner",
        "fixture.source_authority.authorize_calls == 1",
        "fixture.root_targets.calls == 2",
        "fixture.retention.physical_acquisitions == 1",
        "fixture.fence_reader.calls == 4",
        "fixture.legacy_state.calls == 4",
        "legacy_root_identity=_manifest_directory_identity(self.root)",
        "current_fence.fenced_root_identity == _manifest_directory_identity(",
        "fixture.product_projection_before == product_projection_after_first",
        "metadata = path.lstat()",
        "secret not in os.readlink(path)",
        "test_native_adoption_rejects_wrong_physical_authority_before_source",
        "package_store_id=store_id",
    ):
        assert evidence in adversarial_tests
    assert "PLC9B Linux native adversarial gate (plc9b-linux-native)" in workflow
    assert "scripts/dev/verify_pytest_xml.py" in workflow

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c4d Accepted Native Positive Adoption Evidence" in normalized
    assert "production lifecycle, authenticated acquisition" in normalized
    assert "POSIX-native revision Store" in normalized
    assert "making it Linux manifest node 94" in normalized
    assert "cumulative retained gate below supplies" in normalized
    assert "complete 140-test PLC9B architecture/manifest regression" in normalized
    assert "all 94 Linux manifest nodes with no skips" in normalized
    assert "pytest passed 3,920 tests with 33 expected platform skips" in normalized
    assert "The complete three-test benchmark file then passed" in normalized
    assert "PLC9B4c4d accepted evidence composes the positive" in inventory
    assert "increasing the Linux native manifest from 93 to 94 nodes" in " ".join(
        inventory.split()
    )
    assert "PLC9B4c4d accepted evidence composes the positive" in index
    assert "now executes as Linux native node 94" in index


def test_plc9b4c4e_adoption_source_failures_are_bounded_and_promoted() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    tests = _source(ADVERSARIAL_TEST)
    manifest = _adversarial_manifest()

    expected = {
        "B-COMPAT-ADOPT-UNAUTHORIZED": (
            "package_source_unauthorized",
            "rejected@acquiring",
        ),
        "B-COMPAT-ADOPT-UNAVAILABLE": (
            "package_operation_timed_out",
            "retryable_failure@acquiring",
        ),
    }
    for case_id, (code, disposition) in expected.items():
        row = manifest[case_id]
        assert row["status"] == "implemented"
        assert row["platform"] == "posix-native"
        assert row["code"] == code
        assert row["disposition"] == disposition
        assert "no_skip" in row["oracles"].split(";")

    for evidence in (
        "IMPLEMENTED_B4C4E_LINUX_ADOPTION_FAILURE_MANIFEST_CASES",
        '"B-COMPAT-ADOPT-UNAUTHORIZED"',
        '"B-COMPAT-ADOPT-UNAVAILABLE"',
        "fixture.source_authority.authorize_calls == 1",
        "fixture.retention.physical_acquisitions == 0",
        "fixture.root_staging.calls == 0",
        "fixture.quarantine.total_residue_bytes() == 0",
        "fixture.product_projections.capture() == product_before",
        "_assert_manifest_secret_absent(tmp_path, fixture.secret)",
    ):
        assert evidence in tests
    normalized = " ".join(contract.split())
    assert "PLC9B4c4e Accepted Adoption Source Failure Evidence" in normalized
    assert "Linux manifest nodes 95 and 96" in normalized
    assert "grows from 94 to 96 nodes" in " ".join(inventory.split())
    assert "Linux native nodes 95 and 96" in " ".join(index.split())


def test_plc9b4c4f_crash_after_committed_replays_exact_receipt() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    tests = _source(ADVERSARIAL_TEST)
    row = _adversarial_manifest()["B-COMPAT-ADOPT-CRASH-AFTER-COMMITTED"]

    assert row["status"] == "implemented"
    assert row["platform"] == "posix-native"
    assert row["code"] == "ok"
    assert row["disposition"] == "committed@committed"
    assert "same_receipt" in row["oracles"].split(";")
    assert "no_skip" in row["oracles"].split(";")
    for evidence in (
        "IMPLEMENTED_B4C4F_LINUX_ADOPTION_COMMITTED_CRASH_MANIFEST_CASES",
        "_ManifestCrashAfterCommittedCommitOwner",
        "with pytest.raises(_ManifestCrashAfterCommitted)",
        'assert (committed.phase, committed.disposition) == ("committed", "committed")',
        "_restart_manifest_native_adoption_fixture(fixture)",
        "crashed_commit.pre_crash_receipt is not None",
        "recovered.receipt.publication == crashed_commit.pre_crash_receipt",
        'pin is not None and pin.state == "acquired"',
        "assert recovered == replay",
        "assert after_crash == (",
    ):
        assert evidence in tests
    normalized = " ".join(contract.split())
    assert "PLC9B4c4f Accepted Crash-After-Committed Evidence" in normalized
    assert "Linux manifest node 97" in normalized
    assert "Linux native node 97" in " ".join(inventory.split())
    assert "Linux native node 97" in " ".join(index.split())


def test_plc9b4c4g_every_precommit_adoption_phase_rebuilds_and_recovers() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    tests = _source(ADVERSARIAL_TEST)
    manifest = _adversarial_manifest()
    row = manifest["B-COMPAT-ADOPT-CRASH"]

    assert row["status"] == "implemented"
    assert row["platform"] == "posix-native"
    assert row["barrier"] == "each_precommit_phase"
    assert row["fixture"] == "adoption_process_crash_and_resume"
    assert row["code"] == "ok"
    assert row["disposition"] == "committed@committed"
    assert {
        "same_receipt",
        "bounded_residue",
        "legacy_snapshot_exact",
        "desired_unchanged",
        "instance_unchanged",
        "binding_unchanged",
        "enablement_unchanged",
        "no_skip",
    } == set(row["oracles"].split(";"))
    assert (
        _literal_string_tuple("ADOPTION_PRECOMMIT_CRASH_PHASES")
        == PLC9B4C4G_PRECOMMIT_PHASES
    )
    assert all(
        manifest[case_id]["status"] == "implemented"
        for case_id in (
            "B-COMPAT-ADOPT",
            "B-COMPAT-ADOPT-UNAUTHORIZED",
            "B-COMPAT-ADOPT-UNAVAILABLE",
            "B-COMPAT-ADOPT-CRASH",
            "B-COMPAT-ADOPT-CRASH-AFTER-COMMITTED",
        )
    )
    for evidence in (
        "IMPLEMENTED_B4C4G_LINUX_ADOPTION_PRECOMMIT_CRASH_MANIFEST_CASES",
        "ADOPTION_PRECOMMIT_CRASH_PHASES",
        "with pytest.raises(_ManifestCrashEdge, match=phase)",
        'assert (crashed.phase, crashed.disposition) == (phase, "active")',
        "_restart_manifest_native_adoption_fixture(fixture)",
        "assert fixture.owner is not prior_owner",
        "assert fixture.kernel is not prior_kernel",
        "assert recovered == replay, phase",
        "fixture.source_authority.authorize_calls == 1",
        "fixture.product_projections.capture()",
        "_assert_manifest_secret_absent(",
    ):
        assert evidence in tests

    normalized = " ".join(contract.split())
    assert "Contract version: PLC9B.5-accepted." in contract
    assert "PLC9B4c4g Accepted Every-Precommit Crash Evidence" in normalized
    assert "complete Package kernel, artifact/closure, pin, staging," in normalized
    assert "same still-active attempt" in normalized
    assert "does not synthesize `package_operation_interrupted`" in normalized
    assert "Linux manifest node 98" in normalized
    assert "all five adoption rows" in " ".join(inventory.split()).lower()
    assert "Linux native node 98" in " ".join(inventory.split())
    assert "all five adoption rows" in " ".join(index.split()).lower()
    assert "Linux native node 98" in " ".join(index.split())


def test_plc9b4c5_windows_restore_is_rooted_isolated_and_promoted() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)
    source = _source(WINDOWS_OFFLINE_RESTORE)
    runtime_source = _source(WINDOWS_LEGACY_RUNTIME)
    component_tests = _source(WINDOWS_OFFLINE_RESTORE_TEST)
    adversarial_tests = _source(ADVERSARIAL_TEST)
    workflow = _source(WINDOWS_WORKFLOW)
    internal_facade = _source(OWNER_KERNEL_ROOT / "__init__.py")
    package_facade = _source(PACKAGE_ROOT / "__init__.py")
    author_sdk = _source(AUTHOR_SDK)
    manifest = _adversarial_manifest()

    assert WINDOWS_OFFLINE_RESTORE.is_file()
    assert WINDOWS_OFFLINE_RESTORE_TEST.is_file()
    assert "class PackageWindowsOfflineRestoreMaterializer" in source
    for rooted_primitive in (
        "open_windows_directory",
        "open_windows_regular_file_at",
        "windows_listdir_at",
        "windows_rename_at",
        "windows_flush_directory",
        "windows_rmdir_at",
        "windows_unlink_at",
        "_PinnedWindowsRoot",
        "_msvcrt",
    ):
        assert rooted_primitive in source
    for invariant in (
        "PACKAGE_PRE_B_SNAPSHOT_DOMAINS",
        "snapshot_tree_digest",
        "state_manifest_digest",
        "current_b_authority_root",
        "PackageOfflineRestoreMaterializationReceiptV1.create",
        "package_offline_restore_cleanup_failed",
        "expected_identities=self._current_b_identities",
        "__all__ = ()",
    ):
        assert invariant in source
    for facade in (internal_facade, package_facade, author_sdk):
        assert "PackageWindowsOfflineRestoreMaterializer" not in facade
        assert "PackageWindowsLegacyRuntimeActivationOwner" not in facade

    tree = ast.parse(source, filename=str(WINDOWS_OFFLINE_RESTORE))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    for forbidden in (
        "loushang.coding",
        "loushang.foundation",
        "loushang.harness.plugin_management",
        "loushang.harness.sandbox",
        "subprocess",
    ):
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imported
        )

    for evidence in (
        "materializes_exact_tree_replays_and_discards",
        "concurrent_owners_converge_on_one_tree",
        "rejects_snapshot_tamper_without_restore_residue",
        "rejects_replaced_current_b_authority",
        "appcontainer_activation_is_exclusive_replayable_and_reversible",
    ):
        assert evidence in component_tests
    for invariant in (
        "PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES",
        "CreateAppContainerProfile",
        "CreateProcessAsUserW",
        "AssignProcessToJobObject",
        "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
        "TOKEN_IS_APP_CONTAINER",
        "TOKEN_CAPABILITIES",
        "CapabilityCount = 0",
        "restored_root",
        "current_b_root",
    ):
        assert invariant in runtime_source
    assert "test_plc9b_windows_offline_restore.py" in workflow
    assert "IMPLEMENTED_B4C5_WINDOWS_OFFLINE_RESTORE_MANIFEST_CASES" in (
        adversarial_tests
    )
    assert (
        _implemented_b4c5_windows_offline_restore_manifest_cases()
        == PLC9B4C5_WINDOWS_OFFLINE_RESTORE_CASES
    )
    assert "test_manifest_case[B-COMPAT-OFFLINE-RESTORE-WINDOWS]" in workflow
    row = manifest["B-COMPAT-OFFLINE-RESTORE-WINDOWS"]
    assert row["status"] == "implemented"
    assert row["platform"] == "windows-native"
    assert row["workflow"] == "windows-shell-compatibility.yml#plc9b-windows-native"

    normalized = " ".join(contract.split())
    assert "PLC9B4c5 Accepted Windows Offline Restore And Activation" in normalized
    assert "complete visible ancestor chain" in normalized
    assert "handle-relative atomic no-replace rename" in normalized
    assert "zero-capability AppContainer" in normalized
    assert "kill-on-close Job Object" in normalized
    assert "Windows Shell Compatibility run `33709473605`" in normalized
    assert "all 15 Windows manifest nodes" in normalized
    assert "artifact ID `9876434660`" in normalized
    assert "PLC9B4c5 accepted code adds a dark Windows" in inventory
    assert "PLC9B4c5 accepted code adds the dark Windows" in index


def test_plc9b2f_windows_backend_is_rooted_and_has_a_nonskippable_native_gate() -> None:
    contract = _source(CONTRACT)
    acquisition = _source(BOUNDED_ACQUISITION)
    windows = _source(WINDOWS_QUARANTINE)
    native_tests = _source(WINDOWS_NATIVE_TEST)
    workflow = _source(WINDOWS_WORKFLOW)
    normalized_contract = " ".join(contract.split())

    assert "PLC9B2f Accepted Native Windows Quarantine" in normalized_contract
    assert "Windows Shell Compatibility run `33486925218`" in normalized_contract
    assert (
        "`5 passed`, `0 skipped`, `0 failures`, and `0 errors`" in normalized_contract
    )
    assert (
        "artifact `windows-shell-pytest-reports` (ID `9792151355`)"
        in normalized_contract
    )
    assert "NtCreateFile" in windows
    assert "root_directory" in windows
    assert "_FILE_OPEN_REPARSE_POINT" in windows
    assert "_FILE_FLAG_OPEN_REPARSE_POINT" in windows
    assert "SetFileInformationByHandle" in windows
    assert "GetFinalPathNameByHandleW" in windows
    assert "open_windows_regular_file_at" in acquisition
    assert "loushang.coding" not in windows
    assert "loushang.foundation" not in windows
    assert native_tests.count("def test_windows_native_") == 5
    assert "test_plc9b_windows_native.py" in workflow
    assert "windows-shell-plc9b-native.xml" in workflow
    assert "include-hidden-files: true" in workflow
    assert workflow.count("test_plc9b_adversarial.py::test_manifest_case[B-") == 15
    for case_id in _implemented_b2i_windows_manifest_cases():
        assert f"test_manifest_case[{case_id}]" in workflow
    assert "windows-shell-plc9b-manifest.xml" in workflow
    assert (
        "verify_pytest_xml.py\n          .artifacts/windows-shell-plc9b-manifest.xml"
        in workflow
    )
    assert (
        "verify_pytest_xml.py\n          .artifacts/windows-shell-plc9b-native.xml"
        in workflow
    )


def test_plc9b_rollback_never_restores_the_unsafe_installer() -> None:
    contract = _source(CONTRACT)
    normalized = " ".join(contract.split())

    for boundary in (
        "There is no rollback to the current installer for Plugin-bound input",
        "disabling the new owner disables the artifact command",
        "cannot fall through to the current `uv`/`pip`",
        "rollback disables Plugin artifact operations instead of restoring an unsafe",
    ):
        assert boundary in normalized
