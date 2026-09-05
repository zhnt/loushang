from __future__ import annotations

import ast
import re
from pathlib import Path

BASELINE = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c50-baseline.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c50-inventory.md"
)
PLC9C = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c0-baseline.md"
)
PLUGIN_INDEX = Path("docs/internals/architecture/harness/plugin/README.md")
DELIVERY_PLAN = Path(
    "docs/internals/architecture/drafts/hosted-product-runtime-v1-plan.md"
)
HOSTED_INVENTORY = Path(
    "docs/internals/architecture/hosting/validation/"
    "hosted-product-runtime-v1-inventory.md"
)

SOURCE_ROOT = Path("src/loushang")
HARNESS_ROOT = SOURCE_ROOT / "harness"
WORKER_ROOT = HARNESS_ROOT / "worker"
SANDBOX_RUNTIME = HARNESS_ROOT / "sandbox/runtime.py"
CODING_ROOT = SOURCE_ROOT / "coding"
HOSTING_ROOT = SOURCE_ROOT / "hosting"
APPHOST_ROOT = SOURCE_ROOT / "apphost"
AUTHOR_ROOT = SOURCE_ROOT / "plugin"

OWNER_SELECTION = WORKER_ROOT / "owner_selection.py"
CAPABILITY_ADAPTER = WORKER_ROOT / "capability_query.py"
HOSTING_ADAPTER = WORKER_ROOT / "hosting_adapter.py"
POSIX_PROFILE = HOSTING_ROOT / "_posix_launch_preparation.py"
WINDOWS_PROFILE = HOSTING_ROOT / "_windows_launch_preparation.py"
WORKER_PUBLIC = WORKER_ROOT / "__init__.py"
NATIVE_PROFILE_BRIDGE = WORKER_ROOT / "_native_profile_bridge.py"
POSIX_NATIVE_TESTS = Path("tests/hosting/test_posix_launch_preparation.py")
WINDOWS_NATIVE_TESTS = Path(
    "tests/hosting/test_windows_launch_preparation_native.py"
)
POSIX_ARCHITECTURE_GUARD = Path(
    "tests/architecture/test_hosting_h6_posix_native.py"
)
WINDOWS_ARCHITECTURE_GUARD = Path(
    "tests/architecture/test_hosting_h6_windows_native.py"
)
HOSTING_WORKFLOW = Path(".github/workflows/hosting-quality.yml")
REPORT_VERIFIER = Path("scripts/dev/verify_pytest_xml.py")
MAKEFILE = Path("Makefile")

EXPECTED_CURRENT_SOURCE_PATHS = {
    "src/loushang/coding/bootstrap.py",
    "src/loushang/coding/cli/__main__.py",
    "src/loushang/coding/session_manager.py",
    "src/loushang/harness/capabilities/component_host.py",
    "src/loushang/harness/capabilities/component_runtime.py",
    "src/loushang/harness/capabilities/owner_component_host.py",
    "src/loushang/harness/machine_resources/control_plane.py",
    "src/loushang/harness/resources/packages/product_activation.py",
    "src/loushang/harness/resources/packages/product_composition.py",
    "src/loushang/harness/resources/packages/product_contract.py",
    "src/loushang/harness/resources/packages/product_runtime.py",
    "src/loushang/harness/resources/plugins/declarations.py",
    "src/loushang/harness/resources/plugins/selection.py",
    "src/loushang/harness/sandbox/runtime.py",
    "src/loushang/harness/session/agent_product.py",
    "src/loushang/harness/session/bootstrap_construction.py",
    "src/loushang/harness/transcript/directory.py",
    "src/loushang/harness/transcript/discovery.py",
    "src/loushang/harness/transcript/runtime_profile.py",
    "src/loushang/harness/transcript/session_catalog.py",
    "src/loushang/harness/worker/capability_query.py",
    "src/loushang/harness/worker/__init__.py",
    "src/loushang/harness/worker/contracts.py",
    "src/loushang/harness/worker/hosting_adapter.py",
    "src/loushang/harness/worker/journal.py",
    "src/loushang/harness/worker/launch.py",
    "src/loushang/harness/worker/owner_selection.py",
    "src/loushang/harness/worker/protocol.py",
    "src/loushang/harness/worker/session.py",
    "src/loushang/harness/worker/supervisor.py",
    "src/loushang/hosting/_child_session_host.py",
    "src/loushang/hosting/_launch_preparation.py",
    "src/loushang/hosting/_posix_launch_preparation.py",
    "src/loushang/hosting/_posix_process.py",
    "src/loushang/hosting/_win32_process.py",
    "src/loushang/hosting/_windows_launch_preparation.py",
    "src/loushang/hosting/_windows_process.py",
}

RESERVED_TRANSITION_TOKENS = {
    "ProductWorkerActivationPolicyV1",
    "ProductWorkerActivationReceiptV1",
    "ProductWorkerActivationAuthorityPort",
    "ProductWorkerActivationCoordinator",
    "ProductWorkerNativeProfilePort",
    "WorkerCleanupSettlementV1",
    "WorkerCleanupDebtV1",
    "bind_coding_product_worker_canary",
}

CURRENT_WORKER_PUBLIC_EXPORTS = {
    "CAPABILITY_WORKER_ADMISSION_VERSION",
    "CAPABILITY_WORKER_AUTHORITY_VERSION",
    "CAPABILITY_WORKER_BINDING_VERSION",
    "CAPABILITY_WORKER_DESCRIPTOR_VERSION",
    "MAX_CAPABILITY_WORKER_DESCRIPTORS",
    "MAX_CAPABILITY_WORKER_FACETS_PER_DESCRIPTOR",
    "MAX_CAPABILITY_WORKER_IDENTIFIER_LENGTH",
    "WORKER_LAUNCH_EVIDENCE_VERSION",
    "WORKER_LAUNCH_IDENTITY_VERSION",
    "WORKER_LAUNCH_REQUEST_VERSION",
    "WORKER_DIAGNOSTIC_READ_MAX_BYTES",
    "WORKER_HOSTING_ACTIVATION_VERSION",
    "WORKER_HOSTING_ENDPOINT_READ_CHUNK_BYTES",
    "WORKER_HOSTING_SELECTION_VERSION",
    "WORKER_RUNTIME_BINDING_VERSION",
    "WORKER_ATTEMPT_RECORD_VERSION",
    "WORKER_PROTOCOL_MAX_FRAME_BYTES",
    "WORKER_PROTOCOL_MAX_JSON_CONTAINERS",
    "WORKER_PROTOCOL_MAX_JSON_DEPTH",
    "WORKER_PROTOCOL_MESSAGE_VERSION",
    "WORKER_SUPERVISOR_LIMITS_VERSION",
    "WORKER_SUPERVISOR_MAX_ATTEMPTS",
    "WORKER_SUPERVISOR_MAX_IN_FLIGHT",
    "WORKER_SUPERVISOR_MAX_MESSAGES_PER_SESSION",
    "WORKER_SUPERVISOR_MAX_TIMEOUT_SECONDS",
    "WORKER_SUPERVISOR_MAX_TOMBSTONES",
    "WORKER_SUPERVISOR_STATUS_VERSION",
    "AsyncioStreamWorkerTransport",
    "CapabilityQueryWorkerAdapter",
    "CapabilityWorkerAdapterError",
    "CapabilityWorkerAdmissionV1",
    "CapabilityWorkerAuthorityV1",
    "CapabilityWorkerBindingV1",
    "CapabilityWorkerDescriptorV1",
    "bind_capability_query_worker_adapter",
    "bind_current_worker_session_port",
    "HostingManagedWorkerSessionAdapter",
    "ManagedWorkerLaunchPort",
    "ManagedWorkerLaunchRequestV1",
    "ManagedWorkerProcessControl",
    "ManagedWorkerProcess",
    "ManagedWorkerSession",
    "ManagedWorkerSessionLaunchPort",
    "WorkerHostingActivationError",
    "WorkerHostingActivationV1",
    "WorkerHostingSelectionV1",
    "WorkerBindingError",
    "WorkerAttemptPhase",
    "WorkerAttemptRecordV1",
    "WorkerByteTransport",
    "WorkerFrameCodec",
    "WorkerFramedTransport",
    "WorkerLaunchEvidenceV1",
    "WorkerLaunchIdentityV1",
    "WorkerRuntimeBindingV1",
    "WorkerProtocolError",
    "WorkerProtocolMessage",
    "WorkerRemoteFailure",
    "WorkerSessionOwner",
    "WorkerSessionOwnerRouter",
    "WorkerSupervisor",
    "WorkerSupervisorError",
    "WorkerSupervisorJournal",
    "WorkerSupervisorJournalError",
    "WorkerSupervisorLimitsV1",
    "WorkerSupervisorStatusV1",
}

EXPECTED_FUTURE_REPORTS = (
    (
        "PLC9C5-C5.1-CONTRACT",
        ".artifacts/plc9c5-c51-contract.xml",
        20,
        (
            "C51-CURRENT-REQUIREDNESS",
            "C51-INVALID-RECEIPT",
            "C51-STALE-RECEIPT",
            "C51-FOREIGN-RECEIPT",
            "C51-POLICY-CLOSURE-CODEC",
            "C51-PREACQUIRE-FRESHNESS",
            "C51-PREPUBLISH-ATOMIC-CAS",
            "C51-KILLSWITCH-PUBLISH-RACE",
            "C51-RECEIPT-ATTEMPT-CLOSURE",
            "C51-EXACT-RETIRE-CAS",
            "C51-KILLSWITCH-ADMISSION-RACE",
            "C51-RESTART-LATCH",
            "C51-CLEANUP-SETTLED",
            "C51-CLEANUP-DEBT",
            "C51-STICKY-OWNER",
            "C51-NO-FALLBACK",
            "C51-REQUIRED-SUCCESS",
            "C51-OPTIONAL-DEGRADED",
            "C51-PUBLICATION-FENCE",
            "C51-SENTINEL-REDACTION",
        ),
    ),
    (
        "PLC9C5-C5.2-LINUX-NATIVE",
        ".artifacts/plc9c5-c52-linux-native.xml",
        14,
        (
            "C52-EXACT-CLOSURE",
            "C52-CATALOG-MISMATCH",
            "C52-POLICY-CLOSURE-MISMATCH",
            "C52-EXEC-CLOSURE-MISMATCH",
            "C52-WSL-MICROSOFT-REJECT",
            "C52-UNKNOWN-CLASSIFIER-REJECT",
            "C52-NON-X86-REJECT",
            "C52-FD-SUBSTITUTION",
            "C52-CANCEL-PRE-EFFECT",
            "C52-CANCEL-POST-EFFECT",
            "C52-DESCENDANT-CLEANUP",
            "C52-SAMEBOOT-DEBT",
            "C52-CHANGEDBOOT-ABSENCE",
            "C52-SENTINEL-REDACTION",
        ),
    ),
    (
        "PLC9C5-C5.3-WINDOWS-MECHANICS",
        ".artifacts/plc9c5-c53-windows-mechanics.xml",
        12,
        (
            "C53-REQUIRED-CONTAINMENT-REJECT",
            "C53-LOCKED-IDENTITY-SUBSTITUTION",
            "C53-TRUSTED-SYSTEMROOT",
            "C53-AMBIENT-SYSTEMROOT-POISONING",
            "C53-CALLER-ENVIRONMENT-REJECT",
            "C53-DISCARDED-STDERR",
            "C53-RESTRICTED-TOKEN",
            "C53-JOB-TREE-CLEANUP",
            "C53-HANDLE-SUBSTITUTION",
            "C53-CANCEL-PRE-POST-EFFECT",
            "C53-RESTART-UNCERTAINTY",
            "C53-SENTINEL-REDACTION",
        ),
    ),
    (
        "PLC9C5-C5.4-LINUX-PRODUCT",
        ".artifacts/plc9c5-c54-linux-product.xml",
        25,
        (
            "C54-PRODUCT-SELECTED",
            "C54-PRODUCT-MISSING",
            "C54-PRODUCT-WRONG",
            "C54-PRODUCT-DISABLED",
            "C54-SESSION-CANONICAL",
            "C54-SESSION-CWD",
            "C54-SESSION-HOME",
            "C54-SESSION-TAMPERED",
            "C54-SESSION-ALIAS",
            "C54-SESSION-CONFLICT",
            "C54-SESSION-CHANGED",
            "C54-REQUIRED-SUCCESS",
            "C54-REQUIRED-FAILURE",
            "C54-OPTIONAL-SUCCESS",
            "C54-OPTIONAL-DEGRADED",
            "C54-CLOSURE-FRESHNESS",
            "C54-HANDSHAKE-HEALTH-PUBLICATION",
            "C54-UNSUPPORTED-WINDOWS",
            "C54-UNSUPPORTED-WSL",
            "C54-UNSUPPORTED-NON-X86",
            "C54-UNSUPPORTED-MACOS",
            "C54-ORDERED-ROLLBACK",
            "C54-RECOVERY-MATRIX",
            "C54-SHARED-ENTRYPOINT-RECEIPT",
            "C54-SENTINEL-REDACTION",
        ),
    ),
)

EXPECTED_DRILL_LEDGER = (
    ("R1-LATCH-FUTURE", "atomically latch future Hosting admission closed and stale its generation"),
    ("R2-FENCE-ATTEMPTS", "fence every exact attempt in the complete active registry"),
    ("R3-REVOKE-DRAIN", "revoke and drain only each attempt's exact domain generation"),
    ("R4-TERMINATE-TREE", "terminate each exact owner's complete process tree"),
    ("R5-SETTLE-OR-DEBT", "durably record tree settlement or cleanup debt"),
    ("R6-SETTLE-READINESS", "settle required/optional Product readiness"),
    ("R7-ISSUE-CURRENT", "only now issue a new Current-owner receipt"),
    ("V1-PRIOR-ABSENT", "no prior attempt exists"),
    ("V2-EXACT-REAPED", "the exact prior tree has a settlement witness"),
    (
        "V3-SAMEBOOT-UNKNOWN",
        "same-boot uncertainty remains durable debt and blocks restart",
    ),
    (
        "V4-CHANGEDBOOT-ABSENT",
        "trusted changed-boot identity proves the old local tree absent",
    ),
    ("V5-BUDGET-EXHAUSTED", "restart budget exhaustion remains terminal"),
    (
        "V6-HOST-RESTART",
        "durable latch, receipt, generation, settlement/debt, and budget facts reconstruct the decision",
    ),
    ("S1-POLICY-REJECTION", "policy/receipt rejection"),
    ("S2-NATIVE-REJECTION", "native preparation rejection"),
    ("S3-LAUNCH-FAILURE", "launch failure"),
    ("S4-PROTOCOL-FAILURE", "protocol or health failure"),
    ("S5-CLEANUP-DEBT", "cleanup debt serialization"),
    ("S6-STATUS-SERIALIZATION", "final Product/status serialization"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    assert marker in text
    return text.split(marker, maxsplit=1)[1].split("\n## ", maxsplit=1)[0]


def _status(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    current: str | None = None
    for line in _section(_read(path), "Status").splitlines():
        if line.startswith("- ") and ":" in line:
            name, value = line[2:].split(":", maxsplit=1)
            current = name
            result[name] = value.strip().strip("`")
            continue
        if current is not None and line.startswith("  "):
            result[current] = f"{result[current]} {line.strip()}"
    return result


def _table_rows(section: str) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip().strip("`") for cell in line.strip("|").split("|"))
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return tuple(rows[1:])


def _documented_sources(text: str) -> set[str]:
    return set(re.findall(r"`(src/loushang/[^`]+\.py)`", text))


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> set[str]:
    module = node.module or ""
    if node.level:
        package = list(path.with_suffix("").parts[1:-1])
        retained = len(package) - (node.level - 1)
        assert retained >= 0
        base = (*package[:retained], *module.split(".")) if module else tuple(
            package[:retained]
        )
        module = ".".join(base)
    result = {module} if module else set()
    result.update(
        f"{module}.{alias.name}" if module else alias.name
        for alias in node.names
        if alias.name != "*"
    )
    return result


def _imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.update(_resolve_import_from(path, node))
    return result


def _qualified_definitions(path: Path) -> set[str]:
    result: set[str] = set()
    scope: list[str] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.append(node.name)
            result.add(".".join(scope))
            for child in node.body:
                visit(child)
            scope.pop()
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(ast.parse(_read(path), filename=str(path)))
    return result


def _literal_string_collection(path: Path, name: str) -> set[str]:
    tree = ast.parse(_read(path), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        value = node.value
        assert value is not None
        result = ast.literal_eval(value)
        assert isinstance(result, (list, tuple, set, frozenset))
        assert all(isinstance(item, str) for item in result)
        return set(result)
    raise AssertionError(f"{name} not found in {path}")


def _top_level_test_functions(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in ast.parse(_read(path), filename=str(path)).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def _future_report_rows(section: str) -> tuple[
    tuple[str, str, int, tuple[str, ...]], ...
]:
    rows: list[tuple[str, str, int, tuple[str, ...]]] = []
    for line in section.splitlines():
        if not line.startswith("| `PLC9C5-"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        assert len(cells) == 4
        rows.append(
            (
                cells[0].strip("`"),
                cells[1].strip("`"),
                int(cells[2]),
                tuple(re.findall(r"`([^`]+)`", cells[3])),
            )
        )
    return tuple(rows)


def _drill_ledger_rows(section: str) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for line in section.splitlines():
        if not re.match(r"\| `[RVS][0-9]-", line):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        assert len(cells) == 2
        rows.append((cells[0].strip("`"), cells[1]))
    return tuple(rows)


def _function_source(path: Path, qualified_name: str) -> str:
    source = _read(path)
    tree = ast.parse(source, filename=str(path))
    scope: list[str] = []

    def visit(node: ast.AST) -> str | None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.append(node.name)
            if ".".join(scope) == qualified_name:
                return ast.get_source_segment(source, node)
            for child in node.body:
                result = visit(child)
                if result is not None:
                    return result
            scope.pop()
            return None
        for child in ast.iter_child_nodes(node):
            result = visit(child)
            if result is not None:
                return result
        return None

    result = visit(tree)
    assert result is not None
    return result


def test_c50_status_is_honest_and_documents_are_indexed_once() -> None:
    assert _status(BASELINE) == {
        "ID": "PLC9C5-C5.0",
        "Scope": (
            "loushang.harness` Worker activation boundary plus one Product-owned "
            "canary composition"
        ),
        "Parent": "PLC9C",
        "Authority": "normative accepted design",
        "Design status": "accepted",
        "Implementation status": (
            "implemented — C5.0 documentation/guards only; C5.1--C5.4 "
            "not-started"
        ),
        "Activation status": "closed; every production route remains default-dark",
        "Observation base": "cb01f723",
        "Owner": (
            "Harness Worker architecture with Product, Hosting, and domain-owner "
            "review"
        ),
    }
    inventory_status = _status(INVENTORY)
    assert inventory_status["ID"] == "PLC9C5-C5.0-INVENTORY"
    assert inventory_status["Authority"] == (
        "descriptive — source-backed Current inventory"
    )
    assert inventory_status["Design status"] == "not-applicable"
    assert inventory_status["Implementation status"] == "not-applicable"
    assert inventory_status["Effect"] == (
        "none; this inventory grants no runtime or activation authority"
    )
    index = _read(PLUGIN_INDEX)
    assert index.count("(plugin-lifecycle-plc9c5-c50-baseline.md)") == 1
    assert index.count("(plugin-lifecycle-plc9c5-c50-inventory.md)") == 2
    for related in (PLC9C, DELIVERY_PLAN, HOSTED_INVENTORY):
        text = _read(related)
        assert "PLC9C5 C5.0" in text
        assert "default-dark" in text or "activation" in text


def test_c50_current_inventory_source_set_is_exact_and_present() -> None:
    documented = _documented_sources(
        _section(_read(INVENTORY), "Exact Current Source Set")
    )
    assert documented == EXPECTED_CURRENT_SOURCE_PATHS
    assert all(Path(path).is_file() for path in documented)
    identifiers = tuple(
        row[0]
        for row in _table_rows(_section(_read(INVENTORY), "Exact Current Source Set"))
    )
    assert identifiers == (
        "C5-CUR-DECL",
        "C5-CUR-PRODUCT-CORE",
        "C5-CUR-CODING-PRODUCT",
        "C5-CUR-PACKAGE-PRODUCT",
        "C5-CUR-SESSION-PROFILE",
        "C5-CUR-SESSION-DISCOVERY",
        "C5-CUR-WORKER-PUBLIC",
        "C5-CUR-WORKER-IDENTITY",
        "C5-CUR-CURRENT-LAUNCH",
        "C5-CUR-WORKER-SESSION",
        "C5-CUR-DOMAIN-CANARY",
        "C5-CUR-DOMAIN-GENERATION",
        "C5-CUR-HOSTING-BRIDGE",
        "C5-CUR-H6-CORE",
        "C5-CUR-H6-LINUX",
        "C5-CUR-H6-WINDOWS",
    )


def test_c50_reproduces_the_complete_parent_g7_matrix() -> None:
    parent_rows = _table_rows(_section(_read(DELIVERY_PLAN), "G7 Canary Acceptance Matrix"))
    child_rows = _table_rows(_section(_read(BASELINE), "G7 Acceptance Coverage"))
    assert all(len(row) == 3 and row[2] for row in child_rows)
    assert tuple(row[:2] for row in child_rows) == parent_rows
    assert tuple(row[0] for row in child_rows) == (
        "Product route",
        "Session route",
        "contribution policy",
        "native platform",
        "preparation",
        "lifecycle",
        "recovery",
        "publication",
        "rollback",
        "entrypoint",
    )
    assert tuple(
        row[0] for row in _table_rows(_section(_read(BASELINE), "Delivery Slices"))
    ) == ("C5.0", "C5.1", "C5.2", "C5.3", "C5.4")
    required_evidence = {
        "Product route": ("C5.1", "C5.4", "Coding Product composition"),
        "Session route": ("C5.4", "stable locator", "AppHost"),
        "contribution policy": ("C5.1", "C5.4", "readiness"),
        "native platform": (
            "C5.2",
            "Linux native report",
            "C5.3",
            "Windows mechanics",
            "G7 stays open",
        ),
        "preparation": ("C5.2/C5.3", "adversarial native", "C5.4"),
        "lifecycle": ("C5.2/C5.3", "platform ownership", "C5.4"),
        "recovery": ("C5.1", "C5.2/C5.3", "C5.4", "adoption remains forbidden"),
        "publication": ("C5.1", "C5.4", "Capability owner"),
        "rollback": ("C5.1", "active-registry", "C5.4", "rollback drill"),
        "entrypoint": ("C5.4", "entrypoint receipt", "early-dispatch"),
    }
    evidence_by_dimension = {row[0]: row[2] for row in child_rows}
    for dimension, tokens in required_evidence.items():
        assert all(token in evidence_by_dimension[dimension] for token in tokens)


def test_c50_freezes_dependency_and_native_shape_decisions() -> None:
    baseline = " ".join(_read(BASELINE).split())
    inventory = " ".join(_read(INVENTORY).split())
    for statement in (
        "Selection is authority, detection is not",
        "The receipt is the join",
        "A profile is an admitted capability, not configuration text",
        "One attempt has one owner",
        "Health precedes semantic visibility",
        "Rollback changes future policy",
        "Recovery proves absence before restart",
        "Entrypoints share composition, not flags",
        "cannot downgrade a declared required contribution to optional",
        "opaque fingerprint of the exact selected source/locator/revision",
        "immutable native-profile catalog revision",
        "opaque native-policy-closure fingerprint",
        "loushang.worker.native-policy-closure.v1",
        "same-domain expected and realized policy-closure fingerprints",
        "never directly compared with the policy-closure fingerprint",
        "separate full `execution_closure` fingerprint",
        "serialized admission lease",
        "current-witness verification and the domain-owner publication CAS occur inside one lease",
        "durable cleanup settlement/debt contract",
        "protocol terminal record is not cleanup settlement",
        "the prior receipt becomes stale",
        "no same-attempt fallback",
        "generic pre-routing AppHost behavior remains G5/G8",
        "The first Product canary is therefore Linux-only",
        "G7 stays open until a separate Windows required-containment profile",
        "GetWindowsDirectoryW",
        "Ambient `SystemRoot` poisoning is ignored",
        "caller-supplied environment/SystemRoot is rejected",
        "_native_profile_bridge.py",
    ):
        assert statement in baseline
    for mismatch in (
        "static launcher digest",
        "containment-profile digest",
        "generic `st_dev/st_ino` fields",
        "one absolute `SystemRoot` environment entry",
        "ambient `os.environ[\"SystemRoot\"]`",
        "discarded stderr",
        "restricted-token/Job/direct-import mechanics",
        "selector currently accepts WSL",
        "current profile is explicitly rejected for Product required containment",
        "no cleanup settlement/debt contract",
        "no Product activation gate or complete active-attempt registry",
        "no Product-level rollback coordinator exists",
    ):
        assert mismatch in inventory

    future_evidence = _section(
        _read(BASELINE), "Future Evidence Manifest And Drill Ledger"
    )
    normalized_evidence = " ".join(future_evidence.split())
    assert "zero skips, failures, and errors" in normalized_evidence
    assert "ambient-environment sentinels" in normalized_evidence
    assert _future_report_rows(future_evidence) == EXPECTED_FUTURE_REPORTS
    assert _drill_ledger_rows(future_evidence) == EXPECTED_DRILL_LEDGER


def test_c50_runtime_contract_and_product_composition_remain_absent() -> None:
    production_sources = tuple(SOURCE_ROOT.rglob("*.py"))
    source = "\n".join(_read(path) for path in production_sources)
    assert RESERVED_TRANSITION_TOKENS.isdisjoint(source.split())
    for token in RESERVED_TRANSITION_TOKENS:
        assert token not in source

    composition_names = {
        "HostingManagedWorkerSessionAdapter",
        "WorkerHostingActivationV1",
        "WorkerSessionOwnerRouter",
        "bind_capability_query_worker_adapter",
    }
    outside_worker = {
        path
        for path in production_sources
        if not path.is_relative_to(WORKER_ROOT)
        and any(name in _read(path) for name in composition_names)
    }
    assert outside_worker == set()

    worker_consumers = {
        path
        for path in HARNESS_ROOT.rglob("*.py")
        if not path.is_relative_to(WORKER_ROOT)
        and any(
            imported.startswith("loushang.harness.worker")
            for imported in _imports(path)
        )
    }
    assert worker_consumers == {SANDBOX_RUNTIME}
    assert _literal_string_collection(WORKER_PUBLIC, "__all__") == (
        CURRENT_WORKER_PUBLIC_EXPORTS
    )
    assert not NATIVE_PROFILE_BRIDGE.exists()


def test_c50_keeps_private_profiles_confined_and_product_layers_clean() -> None:
    profile_modules = {
        "loushang.hosting._posix_launch_preparation",
        "loushang.hosting._windows_launch_preparation",
    }
    profile_consumers = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if not path.is_relative_to(HOSTING_ROOT)
        and _imports(path) & profile_modules
    }
    assert profile_consumers == set()

    private_preparation = "loushang.hosting._launch_preparation"
    preparation_consumers = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if not path.is_relative_to(HOSTING_ROOT)
        and private_preparation in _imports(path)
    }
    assert preparation_consumers == {HOSTING_ADAPTER}

    posix = _read(POSIX_PROFILE).lower()
    assert "wsl" not in posix
    assert "microsoft" not in posix

    forbidden_product_imports = (
        "loushang.harness.worker",
        "loushang.hosting",
    )
    for root in (CODING_ROOT, APPHOST_ROOT):
        if not root.is_dir():
            continue
        imports = {
            imported for path in root.rglob("*.py") for imported in _imports(path)
        }
        assert not any(
            imported.startswith(forbidden_product_imports) for imported in imports
        )


def test_c50_import_guard_resolves_relative_and_parent_alias_forms() -> None:
    probes = {
        "from ...hosting._posix_launch_preparation import "
        "_PosixStaticContainedLaunchCaptureSpec": (
            "loushang.hosting._posix_launch_preparation"
        ),
        "from loushang.hosting import _windows_launch_preparation": (
            "loushang.hosting._windows_launch_preparation"
        ),
        "from ...hosting import _launch_preparation": (
            "loushang.hosting._launch_preparation"
        ),
    }
    for source, expected in probes.items():
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.ImportFrom)
        assert expected in _resolve_import_from(HOSTING_ADAPTER, node)


def test_c50_owner_selection_is_default_current_and_has_no_retry() -> None:
    selection = _read(OWNER_SELECTION)
    start = _function_source(OWNER_SELECTION, "WorkerSessionOwnerRouter.start")
    assert 'owner: WorkerSessionOwner = "current"' in selection
    assert "os.environ" not in selection
    assert "getenv" not in selection
    assert start.count("return await port.start(") == 1
    assert "except" not in start
    assert "_current.start" not in start
    assert "_hosting.start" not in start

    adapter_bind = _function_source(
        CAPABILITY_ADAPTER,
        "bind_capability_query_worker_adapter",
    )
    assert "enabled: bool = False" in adapter_bind
    assert "worker_disabled_by_policy" in adapter_bind


def test_c50_deletion_fences_retain_exact_owners_and_oracles() -> None:
    expected_definitions = {
        WORKER_ROOT / "launch.py": {"ManagedWorkerLaunchPort"},
        SANDBOX_RUNTIME: {
            "SandboxExecutionRuntime.bind_managed_worker_launch_port"
        },
        OWNER_SELECTION: {
            "WorkerSessionOwnerRouter",
            "WorkerSessionOwnerRouter.rollback_to_current",
        },
        WORKER_ROOT / "supervisor.py": {
            "WorkerSupervisor",
            "WorkerSupervisor.start_session",
        },
        CAPABILITY_ADAPTER: {"bind_capability_query_worker_adapter"},
        HARNESS_ROOT / "capabilities/component_host.py": {
            "CapabilityComponentHost"
        },
        HARNESS_ROOT / "capabilities/owner_component_host.py": {
            "CapabilityOwnerComponentHost"
        },
        HARNESS_ROOT / "capabilities/component_runtime.py": {
            "CapabilityOwnerComponentBinder",
            "CapabilityOwnerComponentRuntime",
        },
        HARNESS_ROOT / "transcript/runtime_profile.py": {
            "AgentTranscriptProfileRuntime.validate_snapshot"
        },
        POSIX_PROFILE: {"_PosixStaticContainedLaunchCaptureSpec"},
        WINDOWS_PROFILE: {"_WindowsRestrictedLaunchCaptureSpec"},
    }
    for path, definitions in expected_definitions.items():
        assert path.is_file()
        assert definitions <= _qualified_definitions(path)

    for oracle in (
        POSIX_NATIVE_TESTS,
        WINDOWS_NATIVE_TESTS,
        POSIX_ARCHITECTURE_GUARD,
        WINDOWS_ARCHITECTURE_GUARD,
        Path("tests/architecture/test_hosting_h5_worker_adapter.py"),
        Path("tests/architecture/test_hosting_h6_harness_parity.py"),
        REPORT_VERIFIER,
    ):
        assert oracle.is_file()

    required_native_tests = {
        POSIX_NATIVE_TESTS: {
            "test_posix_contained_profile_pins_launcher_payload_and_applies_profile",
            "test_posix_contained_profile_blocks_descendant_group_escape",
            "test_posix_static_native_early_exit_rolls_back_before_publication",
            "test_posix_static_cancellation_after_os_create_reclaims_process",
        },
        WINDOWS_NATIVE_TESTS: {
            "test_windows_restricted_native_locks_identity_and_runs_restricted",
            "test_windows_restricted_native_job_reclaims_descendant",
        },
    }
    for path, names in required_native_tests.items():
        functions = _top_level_test_functions(path)
        assert names <= functions.keys()
        for name in names:
            assert not any(
                "skip" in ast.unparse(decorator)
                for decorator in functions[name].decorator_list
            )

    posix_guard = _read(POSIX_ARCHITECTURE_GUARD)
    windows_guard = _read(WINDOWS_ARCHITECTURE_GUARD)
    assert "native_adversarial_gate_is_retained_and_non_skippable" in posix_guard
    assert "windows_native_oracle_and_report_are_retained" in windows_guard

    workflow = _read(HOSTING_WORKFLOW)
    for required in (
        "ubuntu-24.04",
        "windows-2022",
        "H6.2 Linux native adversarial gate",
        "H6.3 Windows native adversarial gate",
        "tests/hosting/test_posix_launch_preparation.py",
        "tests/hosting/test_windows_launch_preparation_native.py",
        ".artifacts/h6-posix-native.xml",
        ".artifacts/h6-windows-native.xml",
        "scripts/dev/verify_pytest_xml.py",
        "actions/upload-artifact@v4",
        "tests/architecture/test_plugin_lifecycle_plc9c5_c50_baseline.py",
    ):
        assert required in workflow
    makefile = _read(MAKEFILE)
    assert makefile.count(
        "tests/architecture/test_plugin_lifecycle_plc9c5_c50_baseline.py"
    ) == 2

    declarations = _read(
        HARNESS_ROOT / "resources/plugins/declarations.py"
    )
    author = "\n".join(_read(path) for path in AUTHOR_ROOT.rglob("*.py"))
    assert "remote_service" not in declarations
    assert "remote_service" not in author
    assert "local_worker" not in author
