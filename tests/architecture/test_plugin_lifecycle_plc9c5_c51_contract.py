from __future__ import annotations

import ast
import json
import re
from pathlib import Path

CONTRACT = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c51-contract.md"
)
BASELINE = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c50-baseline.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c50-inventory.md"
)
MANIFEST = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-evidence-manifest.json"
)
PLUGIN_INDEX = Path("docs/internals/architecture/harness/plugin/README.md")
WORKER_ROOT = Path("src/loushang/harness/worker")
WORKER_FACADE = WORKER_ROOT / "__init__.py"
IMPLEMENTATION = WORKER_ROOT / "product_activation.py"
NATIVE_BRIDGE = WORKER_ROOT / "_native_profile_bridge.py"
CONTRACT_TEST = Path("tests/harness/worker/test_product_activation.py")
VERIFIER = Path("scripts/dev/verify_plc9c5_manifest.py")
VERIFIER_TEST = Path("tests/dev/test_verify_plc9c5_manifest.py")
WORKFLOW = Path(".github/workflows/harness-quality.yml")
MAKEFILE = Path("Makefile")
SOURCE_ROOT = Path("src/loushang")

C51_EXPORTS = {
    "ProductWorkerActivationAuthorityPort",
    "ProductWorkerActivationPolicyV1",
    "ProductWorkerActivationReceiptV1",
}
C51_IMPLEMENTATION_NAMES = C51_EXPORTS | {
    "ProductWorkerActivationCoordinator",
    "WorkerCleanupDebtV1",
    "WorkerCleanupSettlementV1",
    "_AttemptAdmissionLease",
}
C51_CASES = (
    "C51-CURRENT-REQUIREDNESS",
    "C51-INVALID-RECEIPT",
    "C51-STALE-RECEIPT",
    "C51-FOREIGN-RECEIPT",
    "C51-POLICY-CLOSURE-CODEC",
    "C51-PREACQUIRE-FRESHNESS",
    "C51-PREPUBLISH-ATOMIC-CAS",
    "C51-KILLSWITCH-PUBLISH-BLOCKED",
    "C51-RECEIPT-ATTEMPT-CLOSURE",
    "C51-EXACT-RETIRE-CAS",
    "C51-KILLSWITCH-ADMISSION-BLOCKED",
    "C51-RESTART-LATCH",
    "C51-CLEANUP-SETTLED",
    "C51-CLEANUP-DEBT",
    "C51-STICKY-OWNER",
    "C51-NO-FALLBACK",
    "C51-REQUIRED-SUCCESS",
    "C51-OPTIONAL-DEGRADED",
    "C51-PUBLICATION-FENCE",
    "C51-SENTINEL-REDACTION",
)
C51_HARDENING_CASES = (
    "C51-MONOTONIC-SETTLEMENT",
    "C51-DURABLE-POLICY-BUDGET",
    "C51-CAPACITY-PREWRITE",
    "C51-KILLSWITCH-DURABLE-RETRY",
    "C51-GATE-RELEASE-IMMEDIATE",
    "C51-NOEFFECT-NORMAL",
    "C51-NOEFFECT-EXCEPTION",
    "C51-NOEFFECT-EXPLICIT",
    "C51-EFFECT-EXCEPTION",
    "C51-COMMIT-BEFORE-RETURN",
    "C51-DUAL-COORDINATOR-CAS",
    "C51-PUBLISH-THEN-KILL-RACE",
    "C51-KILL-THEN-PUBLISH-RACE",
    "C51-DYNAMIC-PORT-REENTRY",
    "C51-PORT-FAULTS",
    "C51-COUNTERFEIT-EVIDENCE",
    "C51-REGISTERED-RECOVERY",
    "C51-GATE-RELEASE-PREFAULT",
    "C51-GATE-RELEASE-POSTFAULT",
    "C51-CROSS-THREAD-AUTHORITY-REENTRY",
    "C51-CROSS-THREAD-STORE-REENTRY",
    "C51-CROSS-THREAD-EVIDENCE-REENTRY",
    "C51-RELEASE-DEBT-PUBLISH",
    "C51-RELEASE-DEBT-ADMISSION-VALIDATION",
    "C51-RELEASE-DEBT-ADMISSION-CAS",
    "C51-RELEASE-DEBT-DRAIN-JOIN",
    "C51-SHARED-AUTHORITY-DOMAIN",
    "C51-SHARED-STORE-DOMAIN",
    "C51-SHARED-EVIDENCE-DOMAIN",
    "C51-DISJOINT-OWNER-PARALLEL",
    "C51-SHARED-RELEASE-DEBT-DRAIN",
    "C51-CROSS-OWNER-CALLBACK-FENCE",
    "C51-SHARED-DOMAIN-WRAPPERS",
    "C51-DOMAIN-TOKEN-WEAKREF",
    "C51-ENTER-AMBIGUITY-CLEANUP",
    "C51-EXIT-CALLBACK-DRAIN-REENTRY",
    "C51-RETIRE-RELEASE-PREFAULT",
    "C51-RETIRE-RELEASE-POSTFAULT",
    "C51-LATCH-RELEASE-PREFAULT",
    "C51-LATCH-RELEASE-POSTFAULT",
    "C51-HELD-GATE-NO-EARLY-RELEASE",
    "C51-RESERVED-GATE-NO-DRAIN",
    "C51-RELEASING-RETRY-FAILFAST",
    "C51-RELEASE-FAULT-RETRY-TAKEOVER",
    "C51-SHARED-EXIT-CALLBACK-RETRY-REJECT",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _literal_collection(path: Path, name: str) -> set[str]:
    tree = ast.parse(_read(path), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        assert node.value is not None
        result = ast.literal_eval(node.value)
        assert isinstance(result, (tuple, list, set, frozenset))
        return set(result)
    raise AssertionError(f"{name} not found in {path}")


def _qualified_node(path: Path, name: str) -> ast.AST:
    tree = ast.parse(_read(path), filename=str(path))
    scope: list[str] = []

    def visit(node: ast.AST) -> ast.AST | None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.append(node.name)
            if ".".join(scope) == name:
                return node
            for child in node.body:
                found = visit(child)
                if found is not None:
                    return found
            scope.pop()
            return None
        for child in ast.iter_child_nodes(node):
            found = visit(child)
            if found is not None:
                return found
        return None

    result = visit(tree)
    assert result is not None
    return result


def _node_source(path: Path, name: str) -> str:
    node = _qualified_node(path, name)
    result = ast.get_source_segment(_read(path), node)
    assert result is not None
    return result


def _imports(path: Path) -> set[str]:
    relative = path.relative_to(SOURCE_ROOT).with_suffix("")
    current = ["loushang", *relative.parts[1:]]
    if current[-1] == "__init__":
        current.pop()
    else:
        current.pop()
    result: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                prefix = current[: len(current) - (node.level - 1)]
                module = [*prefix, *(node.module or "").split(".")]
                normalized = ".".join(part for part in module if part)
            elif node.module:
                normalized = node.module
            else:
                continue
            result.add(normalized)
            result.update(
                f"{normalized}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            )
    return result


def _call_lines(node: ast.AST, name: str) -> list[int]:
    return sorted(
        call.lineno
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and (
            (isinstance(call.func, ast.Attribute) and call.func.attr == name)
            or (isinstance(call.func, ast.Name) and call.func.id == name)
        )
    )


def _attribute_lines(node: ast.AST, name: str) -> list[int]:
    return sorted(
        item.lineno
        for item in ast.walk(node)
        if isinstance(item, ast.Attribute) and item.attr == name
    )


def test_c51_contract_and_inventory_are_honest_and_indexed() -> None:
    contract = " ".join(_read(CONTRACT).split())
    baseline = _read(BASELINE)
    inventory = " ".join(_read(INVENTORY).split())
    index = _read(PLUGIN_INDEX)
    for token in (
        "Implementation status: implemented",
        "Activation status: closed",
        "Production default: Current",
        "no `await` or user callback",
        "complete active registry",
        "no same-attempt fallback",
        "no native bridge",
        "no Product/Coding/AppHost/presenter/CLI composition",
        "claim_restart is budget accounting, not activation authority",
        "construction-time evidence authority",
        "owner-identity shared callback domains",
        "wrappers over the same backend must pass the same token",
        "stable identity order",
        "registered in the shared authority-domain",
        "never holds the release lock",
        "idempotent-release contract",
        "pending authority-release registry",
        "recover_registered_no_effect",
        "exact 65 case ids",
    ):
        assert token in contract
    assert index.count("(plugin-lifecycle-plc9c5-c51-contract.md)") == 1
    assert "C5.2 Linux native profile binding, and C5.3 Windows" in (
        " ".join(baseline.split())
    )
    assert "mechanics/rejection; C5.4 not-started" in " ".join(baseline.split())
    for token in (
        "C5-C51-RECEIPT-LIFECYCLE",
        "C5-C52-LINUX-NATIVE",
        "retained Linux native report is implemented",
        "no production activation gate is composed",
        "no production recovery route exists",
    ):
        assert token in inventory


def test_c51_facade_exposes_only_closed_value_and_authority_contracts() -> None:
    implementation_all = _literal_collection(IMPLEMENTATION, "__all__")
    assert implementation_all == C51_EXPORTS
    facade_all = _literal_collection(WORKER_FACADE, "__all__")
    assert C51_EXPORTS <= facade_all
    assert not {
        "ProductWorkerActivationCoordinator",
        "WorkerCleanupSettlementV1",
        "WorkerCleanupDebtV1",
        "_ActivationStatusV1",
        "_AttemptAdmissionLease",
        "_MemoryActivationStateStore",
    } & facade_all


def test_c51_implementation_is_product_neutral_and_synchronous() -> None:
    imports = _imports(IMPLEMENTATION)
    assert not any(
        name.startswith(
            (
                "loushang.coding",
                "loushang.apphost",
                "loushang.hosting",
                "loushang.harness.session",
                "loushang.harness.capabilities",
            )
        )
        for name in imports
    )
    tree = ast.parse(_read(IMPLEMENTATION), filename=str(IMPLEMENTATION))
    assert not any(isinstance(node, (ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(tree))
    assert NATIVE_BRIDGE.is_file()
    assert "ProductWorkerNativeProfilePort" not in _read(IMPLEMENTATION)


def test_c51_prepublish_witness_and_cas_have_no_callback_gap() -> None:
    publish_node = _qualified_node(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator.publish",
    )
    assert isinstance(publish_node, ast.FunctionDef)
    gate_lines = _call_lines(publish_node, "_serialized_gate")
    witness_lines = _call_lines(publish_node, "_require_current_locked")
    commit_lines = _call_lines(publish_node, "_commit_locked")
    assert len(gate_lines) == len(witness_lines) == len(commit_lines) == 1
    assert gate_lines[0] < witness_lines[0] < commit_lines[0]
    assert not any(
        isinstance(item, (ast.Await, ast.AsyncFunctionDef))
        for item in ast.walk(publish_node)
    )
    # The sole authority callback is completed by _require_current_locked;
    # publication reaches the common validator/CAS without another port call.
    authority_lines = _attribute_lines(publish_node, "_authority")
    assert authority_lines == []
    current = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator._require_current_locked",
    )
    assert "self._authority.current_witness" in current
    assert "witness != receipt.authority_witness" in current


def test_c51_admission_and_kill_switch_share_the_product_gate() -> None:
    enter = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator._enter_admission",
    )
    latch_node = _qualified_node(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator.latch_kill_switch",
    )
    latch = ast.get_source_segment(_read(IMPLEMENTATION), latch_node)
    assert latch is not None
    assert "_open_serialized_gate()" in enter
    assert enter.index("_require_current_locked") < enter.index("_commit_locked")
    assert len(_call_lines(latch_node, "_serialized_gate")) == 1
    commit_lines = _call_lines(latch_node, "_commit_locked")
    stale_lines = _attribute_lines(latch_node, "latch_kill_switch")
    enumerate_lines = _call_lines(latch_node, "active_attempts")
    assert len(commit_lines) == 2
    assert len(stale_lines) == 1
    assert len(enumerate_lines) == 2
    assert commit_lines[0] < stale_lines[0] < commit_lines[1] < max(enumerate_lines)


def test_c51_state_machine_is_closed_durable_and_common_validated() -> None:
    source = _read(IMPLEMENTATION)
    for token in (
        '"settled": frozenset()',
        '"killSwitchState": "open"',
        '"pending"',
        '"completed"',
        '"restartBudget"',
        '"policyFingerprint"',
        "_MAX_DURABLE_ATTEMPTS",
        "inspect.getattr_static",
        '"evidenceAuthorityId"',
        '"evidenceAuthorityFingerprint"',
        "trusted_evidence_authority_id",
        "_CALLBACK_DOMAINS",
        "pending_releases",
        "_authority_domain_token",
        "_store_domain_token",
        "_evidence_domain_token",
        "weakref.ref",
        "release_condition",
        '"reserved"',
        '"held"',
        '"release_due"',
        '"releasing"',
        '"settled"',
        "_compact_settled_attempts",
    ):
        assert token in source
    commit = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator._commit_locked",
    )
    assert "validated = _validate_state(new_state)" in commit
    assert "self._reload_locked()" in commit
    for method in (
        "publish",
        "record_protocol_terminal",
        "retire_exact",
        "record_cleanup_settlement",
        "record_cleanup_debt",
        "settle_changed_boot_absence",
        "claim_restart",
        "latch_kill_switch",
        "_enter_admission",
        "_mark_effect_started",
        "_settle_without_effect_locked",
    ):
        node = _qualified_node(
            IMPLEMENTATION,
            f"ProductWorkerActivationCoordinator.{method}",
        )
        assert _call_lines(node, "_commit_locked"), method
    recovery = _qualified_node(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator.recover_registered_no_effect",
    )
    assert _call_lines(recovery, "_settle_without_effect_locked")


def test_c51_admission_decision_releases_gate_and_cleanup_requires_owner_proof() -> None:
    for method in ("_mark_effect_started", "_settle_without_effect"):
        node = _qualified_node(
            IMPLEMENTATION,
            f"ProductWorkerActivationCoordinator.{method}",
        )
        assert max(_call_lines(node, "_commit_locked") or _call_lines(node, "_settle_without_effect_locked")) < max(
            _call_lines(node, "_release_admission")
        )
    leave = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator._leave_admission",
    )
    assert "not lease._completed" in leave
    for method in ("record_cleanup_settlement", "settle_changed_boot_absence"):
        node = _qualified_node(
            IMPLEMENTATION,
            f"ProductWorkerActivationCoordinator.{method}",
        )
        assert isinstance(node, ast.FunctionDef)
        source = ast.get_source_segment(_read(IMPLEMENTATION), node)
        assert source is not None
        assert "witness" in source
        assert "_verify_cleanup_witness" in source
        assert "evidence_owner" not in {argument.arg for argument in node.args.kwonlyargs}
    release = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator._release_admission",
    )
    assert release.index("self._release_registered(") < release.index(
        "lease._authority_release_id = None"
    )
    lease_exit = _node_source(IMPLEMENTATION, "_AttemptAdmissionLease.__exit__")
    assert "self._authority_release_id is None" in lease_exit
    assert "self._completed" in lease_exit
    drain = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator.retry_pending_releases",
    )
    assert "domain.pending_releases" in drain
    assert "self._drain_release_due" in drain
    opening = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator._open_serialized_gate",
    )
    assert opening.index("_register_pending_release") < opening.index(
        "            enter()"
    ) < opening.index("_mark_release_held")
    callback = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator._call_external",
    )
    assert callback.count("for domain in self._callback_domains") >= 4
    release_helper = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator._drain_release_due",
    )
    assert 'pending.phase = "releasing"' in release_helper
    assert "_ActivationReason.REENTRANT_CALL" in release_helper
    assert release_helper.index('pending.phase = "releasing"') < release_helper.index(
        "self._call_external("
    ) < release_helper.rindex("with domain.release_condition:")
    assert 'pending.phase in {"reserved", "held"}' in release_helper
    assert 'pending.phase != "release_due"' in release_helper
    assert 'pending.phase = "release_due"' in release_helper
    assert 'pending.phase = "settled"' in release_helper
    assert 'if pending.phase in {"release_due", "releasing"}' in drain


def test_c51_cleanup_and_restart_are_durable_exact_attempt_joins() -> None:
    source = _read(IMPLEMENTATION)
    for token in (
        "WorkerCleanupSettlementV1",
        "WorkerCleanupDebtV1",
        "protocolTerminal",
        "domainRetired",
        "treeSettled",
        "hostIdentity",
        "bootIdentity",
        "cleanupSettlement",
        "cleanupDebt",
        "restartOrdinal",
        "compare_and_swap",
    ):
        assert token in source
    restart = _node_source(
        IMPLEMENTATION,
        "ProductWorkerActivationCoordinator.claim_restart",
    )
    assert all(
        token in restart
        for token in (
            'attempt["protocolTerminal"]',
            'attempt["domainRetired"]',
            'attempt["cleanupSettlement"]',
            'attempt["cleanupDebt"]',
            'self._state["restartBudget"]',
            "_commit_locked",
        )
    )


def test_c51_required_manifest_and_test_ids_are_exact() -> None:
    manifest = json.loads(_read(MANIFEST))
    assert manifest["manifestVersion"] == 1
    reports = manifest["reports"]
    assert set(reports) == {
        "PLC9C5-C5.1-CONTRACT",
        "PLC9C5-C5.2-LINUX-NATIVE",
        "PLC9C5-C5.3-WINDOWS-MECHANICS",
        "PLC9C5-C5.4-LINUX-PRODUCT",
    }
    c51 = reports["PLC9C5-C5.1-CONTRACT"]
    assert c51 == {
        "junitPath": ".artifacts/plc9c5-c51-contract.xml",
        "minimumTests": 65,
        "requiredCaseIds": [*C51_CASES, *C51_HARDENING_CASES],
        "status": "implemented",
    }
    assert reports["PLC9C5-C5.2-LINUX-NATIVE"]["status"] == "implemented"
    assert (
        reports["PLC9C5-C5.3-WINDOWS-MECHANICS"]["status"] == "implemented"
    )
    assert reports["PLC9C5-C5.4-LINUX-PRODUCT"]["status"] == "planned"
    assert _literal_collection(CONTRACT_TEST, "PLC9C5_C51_CASES") == set(C51_CASES)
    assert _literal_collection(
        CONTRACT_TEST,
        "PLC9C5_C51_HARDENING_CASES",
    ) == set(C51_HARDENING_CASES)
    contract_test_source = _read(CONTRACT_TEST)
    for case_id in C51_HARDENING_CASES:
        assert contract_test_source.count(case_id) == 2
    for token in (
        "threading.Barrier",
        "threading.Event",
        "_AlwaysTrueEvidenceAuthority",
        "_OrphaningStore",
        "_FaultingGateAuthority",
        "_SpawnJoinAuthority",
        "_SpawnJoinStore",
        "_SpawnJoinEvidenceAuthority",
        "_RegistrationRaceStoreView",
        "_ParallelWitnessAuthority",
        "retry_pending_releases",
        "_EnterAfterAcquireFaultAuthority",
        "_ExitSpawnJoinAuthority",
        "_DomainToken",
        "_PauseFirstEnterAuthority",
    ):
        assert token in contract_test_source
    test_node = _qualified_node(CONTRACT_TEST, "test_plc9c5_c51_contract_case")
    assert isinstance(test_node, ast.FunctionDef)
    assert not any("skip" in ast.unparse(item) for item in test_node.decorator_list)


def test_c51_ci_makefile_and_manifest_verifier_are_required() -> None:
    workflow = _read(WORKFLOW)
    makefile = _read(MAKEFILE)
    for token in (
        "PLC9C5 C5.1 receipt and lifecycle contract",
        "tests/harness/worker/test_product_activation.py",
        ".artifacts/plc9c5-c51-contract.xml",
        "verify_pytest_xml.py",
        "verify_plc9c5_manifest.py",
        "PLC9C5-C5.1-CONTRACT",
        "actions/upload-artifact@v4",
    ):
        assert token in workflow
    for token in (
        "check-plc9c5-c51-contract",
        "test-plc9c5-c51-contract",
        "tests/architecture/test_plugin_lifecycle_plc9c5_c51_contract.py",
        "tests/dev/test_verify_plc9c5_manifest.py",
        "verify_plc9c5_manifest.py",
    ):
        assert token in makefile
    assert VERIFIER.is_file()
    assert VERIFIER_TEST.is_file()
    verifier = _read(VERIFIER)
    verifier_tests = _read(VERIFIER_TEST)
    assert all(
        token in verifier
        for token in (
            "minimumTests",
            "requiredCaseIds",
            "set(observed) != set(expected)",
            "duplicates",
        )
    )
    for behavior_test in (
        "accepts_exact_required_case_set",
        "rejects_substituted_case",
        "rejects_duplicate_case",
        "rejects_skipped_or_failing_report",
        "rejects_planned_report",
        "rejects_untrusted_junit_aggregates",
    ):
        assert behavior_test in verifier_tests


def test_c51_has_no_production_consumer_or_native_side_effect() -> None:
    consumers: set[Path] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        if path in {IMPLEMENTATION, WORKER_FACADE}:
            continue
        text = _read(path)
        imports = _imports(path)
        if (
            "loushang.harness.worker.product_activation" in imports
            or any(name in text for name in C51_IMPLEMENTATION_NAMES)
        ):
            consumers.add(path)
    assert consumers == {NATIVE_BRIDGE}
    for path in WORKER_ROOT.rglob("*.py"):
        if path in {IMPLEMENTATION, WORKER_FACADE, NATIVE_BRIDGE}:
            continue
        assert "loushang.harness.worker.product_activation" not in _imports(path)
        assert not any(name in _read(path) for name in C51_IMPLEMENTATION_NAMES)
    implementation = _read(IMPLEMENTATION)
    for forbidden in (
        "subprocess",
        "os.environ",
        "create_subprocess",
        "Popen",
        "_PosixStaticContainedLaunchCaptureSpec",
        "_PosixStaticLaunchCaptureBackend",
        "bind_coding_product_worker_canary",
        "remote_service",
    ):
        assert forbidden not in implementation
    assert re.search(r'owner: WorkerSessionOwner = "current"', _read(WORKER_ROOT / "owner_selection.py"))
