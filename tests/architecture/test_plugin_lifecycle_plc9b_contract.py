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
    } == PLC9B3E3C1_POSIX_CASES
    assert all(
        manifest[case_id]["status"] == "planned"
        for case_id in publication_cases - PLC9B3E3C1_POSIX_CASES
    )


def _literal_manifest_cases(name: str) -> set[str]:
    tree = ast.parse(_source(ADVERSARIAL_TEST), filename=str(ADVERSARIAL_TEST))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        assert isinstance(value, tuple)
        assert all(isinstance(case_id, str) for case_id in value)
        return set(value)
    raise AssertionError(f"PLC9B manifest case set is missing: {name}")


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
    assert "Contract version: PLC9B.3e3c1" in contract
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

    assert len(documented) == 95
    assert sum(documented.values()) == 151
    assert actual == documented
    assert "test_plc9_freezes_named_package_lifecycle_sites_and_occurrences" in (
        _source(BASELINE_TEST)
    )


def test_plc9b_effect_inventory_freezes_owner_and_bypass_capabilities() -> None:
    inventory = _source(INVENTORY)
    documented = _documented_effect_counts()
    actual = _package_effect_scope_counts()

    assert len(documented) == 141
    assert sum(documented.values()) == 156
    assert actual == documented
    assert "141 effect/capability rows with 156 occurrences" in inventory
    for required in (
        (
            PACKAGE_OPERATIONS,
            "PackageOperationsRuntime.materialize",
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
    assert len(manifest) - len(implemented) == 55
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
            "any",
            "committed",
            "authenticated_legacy_reacquisition",
            "ok",
            "committed@committed",
            unchanged | {"same_receipt", "pin_visible"},
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-ADOPT-UNAUTHORIZED": (
            "any",
            "acquiring",
            "legacy_reacquisition_unauthorized",
            "package_source_unauthorized",
            "rejected@acquiring",
            unchanged | {"no_publication", "no_peer_fallback"},
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-ADOPT-UNAVAILABLE": (
            "any",
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
            },
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-ADOPT-CRASH": (
            "any",
            "each_precommit_phase",
            "adoption_crash_and_retry",
            "package_operation_interrupted",
            "retryable_failure@prior_phase",
            unchanged | {"same_receipt", "bounded_residue"},
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-ADOPT-CRASH-AFTER-COMMITTED": (
            "any",
            "committed",
            "adoption_crash_after_committed_edge",
            "ok",
            "committed@committed",
            unchanged | {"same_receipt", "pin_visible"},
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
    assert production_importers == []


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
    assert public_methods == {"stage_and_publish", "resume", "recover"}
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
    assert manifest["B-PUB-UNCOMMITTED"]["status"] == "planned"

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
        "os.rename(",
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
        "does_not_adopt_exact_tree_without_live_owner_evidence",
        "exact_reuse_rejects_unexpected_sparse_member_without_scanning_it",
        "exact_reuse_rejects_new_hardlink_alias",
        "rejects_relative_root_without_using_ambient_cwd",
    ):
        assert evidence in component_tests
    assert "opens_only_recorded_rooted_file_identities" in wheel_tests
    assert "IMPLEMENTED_B3E3C1_POSIX_MANIFEST_CASES" in adversarial_tests
    assert _implemented_b3e3c1_posix_manifest_cases() == PLC9B3E3C1_POSIX_CASES
    _assert_current_publication_statuses(manifest)
    assert manifest["B-PUB-UNCOMMITTED"]["status"] == "planned"

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
        "a0def54b47500bd2aad59669ece3057df7179ab427cf8edd46f0491b1310db3b"
        in contract
    )
    assert "executed exactly 72 manifest nodes" in normalized


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
    assert workflow.count("test_plc9b_adversarial.py::test_manifest_case[B-") == 7
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
