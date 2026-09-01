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
    "bind_plugin_packages",
    "forget_plugin_binding",
    "forget_remote_source",
    "materialize_remote_source",
    "materialize_remote_source_sync",
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
    "ARCH": 5,
    "CLASS": 5,
    "CLOSURE": 7,
    "COMPAT": 4,
    "CONCUR": 3,
    "CRASH": 12,
    "ENTRY": 8,
    "LIMIT": 6,
    "NOEXEC": 4,
    "PATH": 10,
    "PUB": 5,
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
ALLOWED_PLATFORMS = {"any", "posix-native", "windows-native"}
ALLOWED_ORACLES = {
    "bounded_residue",
    "no_binding",
    "no_desired",
    "no_extra_network",
    "no_import",
    "no_outside_write",
    "no_peer_fallback",
    "no_process",
    "no_publication",
    "no_secret",
    "no_skip",
    "pin_visible",
    "same_receipt",
    "single_owner",
}


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
    for path in (PACKAGE_MATERIALIZER, PLUGIN_REVISIONS):
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
            elif (
                path == PACKAGE_MATERIALIZER
                and isinstance(node, ast.Attribute)
                and node.attr == "reopen"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "_plugin_revision_store"
            ):
                token = "PluginRevisionStore.reopen"
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

    assert len(documented) == 95
    assert sum(documented.values()) == 151
    assert actual == documented
    assert "test_plc9_freezes_named_package_lifecycle_sites_and_occurrences" in (
        _source(BASELINE_TEST)
    )


def test_plc9b_effect_inventory_freezes_owner_and_bypass_capabilities() -> None:
    documented = _documented_effect_counts()
    actual = _package_effect_scope_counts()

    assert len(documented) == 117
    assert sum(documented.values()) == 132
    assert actual == documented
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
    ):
        assert required in documented


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
        "Plugin-bound classification v1",
        "authenticated source envelope v1",
        "bounded acquisition receipt v1",
        "quarantine receipt v1",
        "verified wheel artifact v1",
        "dependency closure node v2",
        "dependency closure lock v2",
        "retention-pin receipt v1",
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
    assert "exact stable published revision refs (never live handles)" in contract
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


def test_plc9b_adversarial_manifest_is_structured_countable_and_planned() -> None:
    manifest = _adversarial_manifest()
    categories = Counter(case_id.split("-", 2)[1] for case_id in manifest)

    assert len(manifest) == 95
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
        assert row["status"] == "planned", case_id
        assert "#plc9b-" in row["workflow"], case_id
        if row["platform"] == "windows-native":
            assert row["workflow"].startswith("windows-shell-compatibility.yml"), (
                case_id
            )
            assert "no_skip" in oracles, case_id
        elif row["platform"] == "posix-native":
            assert row["workflow"].startswith("harness-quality.yml"), case_id
            assert "no_skip" in oracles, case_id


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
        "`operator_action`",
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
        "obtains dependency-retention pins under one handoff identity",
        "atomically records handoff completion and releases the transaction pin",
        "a crash leaves both pins, never a zero-pin gap",
        "Package owner does not import the concrete ledger",
    ):
        assert retention in normalized
    for compatibility in (
        "Package lifecycle epoch and minimum fence-aware runtime",
        "Direct downgrade after any B epoch state exists is unsupported",
        "offline restore of the complete pre-B Package store",
        "mixed-epoch writers are never admitted",
        "`legacy_unverified`",
        "never satisfy B classification, recursive closure, commit admission",
        "Adoption requires authenticated reacquisition",
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
    normalized = " ".join(contract.split())

    for boundary in (
        "There is no rollback to the current installer for Plugin-bound input",
        "disabling the new owner disables the artifact command",
        "cannot fall through to the current `uv`/`pip`",
        "rollback disables Plugin artifact operations instead of restoring an unsafe",
    ):
        assert boundary in normalized
