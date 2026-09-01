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
ADVERSARIAL_TEST = Path(
    "tests/harness/resources/packages/test_plc9b_adversarial.py"
)
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


def _implemented_b1_manifest_cases() -> set[str]:
    tree = ast.parse(_source(ADVERSARIAL_TEST), filename=str(ADVERSARIAL_TEST))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name)
            and target.id == "IMPLEMENTED_B1_MANIFEST_CASES"
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        assert isinstance(value, tuple)
        assert all(isinstance(case_id, str) for case_id in value)
        return set(value)
    raise AssertionError("PLC9B1 executable manifest set is missing")


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
        selector, domain, transition = (
            cell.strip() for cell in line.split("|", 2)
        )
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
    assert "Contract version: PLC9B.2a" in contract
    assert "PLC9B1 dark Owner Kernel and the unbound PLC9B2a" in contract
    assert "unbound PLC9B2a bounded\n  acquisition component" in contract
    assert "No archive extraction, wheel verification" in contract
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


def test_plc9b_adversarial_manifest_is_structured_and_tracks_exact_b1_progress() -> None:
    manifest = _adversarial_manifest()
    categories = Counter(case_id.split("-", 2)[1] for case_id in manifest)
    implemented = _implemented_b1_manifest_cases()

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
    assert implemented == {
        "B-CLASS-PLUGIN",
        "B-CLASS-NONPLUGIN",
        "B-CLASS-INDETERMINATE",
        "B-CLASS-SPOOF",
        "B-CRASH-ACCEPTED",
        "B-CRASH-CLASSIFIED",
        "B-CONCUR-CONFLICT",
        "B-ENTRY-DISABLED",
    }
    assert len(manifest) - len(implemented) == 119
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
            assert response in {"accepted", "classified", "committed", "settled"}
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
        assert manifest[admission_case]["code"] == (
            "package_commit_admission_denied"
        )
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
        assert "transaction_pin_released" in manifest[settled_case][
            "oracles"
        ].split(";")
    assert "dependency_pins_released" in manifest[
        "B-HANDOFF-DESIRED-REJECT"
    ]["oracles"].split(";")
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
            {"single_owner", "legacy_snapshot_exact", "b_namespace_unreachable", "no_peer_fallback", "no_skip"},
            "harness-quality.yml#plc9b-linux-native",
        ),
        "B-COMPAT-OFFLINE-RESTORE-WINDOWS": (
            "windows-native",
            "accepted",
            "complete_pre_b_restore_exclusive_old_runtime",
            "ok",
            "accepted@offline_restore",
            {"single_owner", "legacy_snapshot_exact", "b_namespace_unreachable", "no_peer_fallback", "no_skip"},
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
    kernel_sources = {
        path: _source(path) for path in OWNER_KERNEL_ROOT.glob("*.py")
    }
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
            if isinstance(node, ast.ImportFrom) and (
                node.module or ""
            ).startswith("loushang.harness.resources.packages.plugin_lifecycle"):
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
    assert "archive/wheel verifier" in contract
    assert "promotes no global adversarial manifest row" in contract

    sink = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "BoundedAcquisitionSinkPort"
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
