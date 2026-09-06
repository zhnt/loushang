from __future__ import annotations

import ast
import json
from pathlib import Path

CANARY = Path("src/loushang/coding/_product_worker_canary.py")
CODING_ROOT = Path("src/loushang/coding")
WORKER_ROOT = Path("src/loushang/harness/worker")
HOSTING_ROOT = Path("src/loushang/hosting")
BEHAVIOR = Path("tests/harness/worker/test_coding_product_worker_canary.py")
DOCUMENT = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c54-linux-product.md"
)
BASELINE = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c5-c50-baseline.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c50-inventory.md"
)
INDEX = Path("docs/internals/architecture/harness/plugin/README.md")
MANIFEST = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-evidence-manifest.json"
)
MAKEFILE = Path("Makefile")
WORKFLOW = Path(".github/workflows/harness-quality.yml")

C54_CASES = {
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
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _literal_collection(path: Path, name: str) -> tuple[str, ...]:
    tree = ast.parse(_read(path), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        if any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            assert node.value is not None
            value = ast.literal_eval(node.value)
            assert isinstance(value, (tuple, list))
            return tuple(value)
    raise AssertionError(f"{name} is absent from {path}")


def _function_source(path: Path, name: str) -> str:
    source = _read(path)
    for node in ast.parse(source, filename=str(path)).body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            result = ast.get_source_segment(source, node)
            assert result is not None
            return result
    raise AssertionError(f"{name} is absent from {path}")


def _class_method_source(path: Path, class_name: str, method_name: str) -> str:
    source = _read(path)
    tree = ast.parse(source, filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                child.name == method_name
            ):
                result = ast.get_source_segment(source, child)
                assert result is not None
                return result
    raise AssertionError(f"{class_name}.{method_name} is absent from {path}")


def test_c54_status_inventory_manifest_and_index_are_honest() -> None:
    document = " ".join(_read(DOCUMENT).split())
    baseline = " ".join(_read(BASELINE).split())
    inventory = " ".join(_read(INVENTORY).split())
    report = json.loads(_read(MANIFEST))["reports"]["PLC9C5-C5.4-LINUX-PRODUCT"]
    for token in (
        "ID: `PLC9C5-C5.4-LINUX-PRODUCT`",
        "Design status: accepted",
        "Implementation status: implemented",
        "Production default: Current",
        "G7 remains open",
        "zero skips, failures, and errors",
    ):
        assert token in document
    assert "implemented through C5.5c" in baseline
    assert "C5-C54-LINUX-PRODUCT" in inventory
    assert _read(INDEX).count("(plugin-lifecycle-plc9c5-c54-linux-product.md)") == 1
    assert report["status"] == "implemented"
    assert report["minimumTests"] == 25
    assert set(report["requiredCaseIds"]) == C54_CASES
    assert set(_literal_collection(BEHAVIOR, "PLC9C5_C54_CASES")) == C54_CASES


def test_c54_has_one_product_root_and_one_way_dependencies() -> None:
    source = _read(CANARY)
    assert source.count("def bind_coding_product_worker_canary(") == 1
    worker_consumers = {
        path
        for path in CODING_ROOT.rglob("*.py")
        if any(
            imported.startswith("loushang.harness.worker")
            for imported in _imports(path)
        )
    }
    assert worker_consumers == {CANARY}
    assert not any(
        imported.startswith("loushang.hosting") for imported in _imports(CANARY)
    )
    assert {
        "loushang.harness.worker._native_profile_bridge",
        "loushang.harness.worker.product_activation",
    }.issubset(_imports(CANARY))
    private_profiles = {
        "loushang.hosting._posix_launch_preparation",
        "loushang.hosting._windows_launch_preparation",
    }
    private_consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if not path.is_relative_to(HOSTING_ROOT) and _imports(path) & private_profiles
    }
    assert private_consumers == {WORKER_ROOT / "_native_profile_bridge.py"}
    for forbidden in (
        "os.environ",
        "subprocess",
        "ctypes",
        "_PosixStaticContainedLaunchCaptureSpec",
        "_WindowsRestrictedLaunchCaptureSpec",
    ):
        assert forbidden not in source


def test_c54_default_is_current_and_selection_is_exact() -> None:
    binding = _function_source(CANARY, "bind_coding_product_worker_canary")
    selected = _function_source(CANARY, "_validate_selected_components")
    assert "policy: ProductWorkerActivationPolicyV1 | None = None" in binding
    assert 'code="coding_worker_product_missing"' in binding
    assert "policy.product_id != CODING_PRODUCT_ID" in binding
    assert "policy.enabled" in binding
    assert "receipt.policy != policy" in binding
    assert "CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID" in selected
    assert "ProductWorkerActivationCoordinator(" in binding
    assert "_bind_posix_static_contained_product_worker_profile(" in binding
    assert binding.index(
        "_bind_posix_static_contained_product_worker_profile("
    ) < binding.index("ProductWorkerActivationCoordinator(")
    assert 'WorkerHostingActivationV1(owner="hosting")' in binding
    assert "HostingManagedWorkerSessionAdapter(" in binding
    assert "os.environ" not in binding


def test_c54_session_and_entrypoint_evidence_are_pathless_and_shared() -> None:
    session = _function_source(CANARY, "_validate_session")
    fingerprint = _function_source(
        CANARY,
        "coding_product_worker_session_fingerprint",
    )
    entrypoint = _class_method_source(
        CANARY,
        "CodingProductWorkerCanary",
        "receipt_for_entrypoint",
    )
    for token in (
        "validate_product_session",
        "session_discovery.resumable",
        "session_discovery.conflicts",
        "locator.conversation_id",
        "locator.revision",
        "coding_product_worker_session_fingerprint",
    ):
        assert token in session
    assert "discovery.to_dict()" in fingerprint
    assert "return self._receipt" in entrypoint
    assert "CODING_PRODUCT_WORKER_CANARY_ENTRYPOINTS" in entrypoint
    status = _class_method_source(
        CANARY,
        "CodingProductWorkerCanaryStatusV1",
        "to_dict",
    )
    for forbidden in ("path", "cwd", "sessionFile", "environment", "handle"):
        assert forbidden not in status


def test_c54_health_precedes_domain_publication_and_ambiguity_is_reclaimed() -> None:
    start = _class_method_source(CANARY, "CodingProductWorkerCanary", "start")
    assert start.index("supervisor.start_session(") < start.index("adapter.admit()")
    assert start.index("adapter.admit()") < start.index("coordinator.publish(")
    assert start.index("coordinator.publish(") < start.index("domain.publish(")
    assert start.index("domain_publish_started = True") < start.index(
        "await domain.publish("
    )
    reclaim = _class_method_source(
        CANARY,
        "CodingProductWorkerCanary",
        "_reclaim_failed_attempt",
    )
    for token in (
        "domain.fence_attempt",
        "domain.revoke_and_drain",
        "coordinator.retire_exact",
        "supervisor.fence",
        "coordinator.record_protocol_terminal",
        "cleanup.settle",
    ):
        assert token in reclaim


def test_c54_rollback_recovery_and_no_fallback_are_fixed() -> None:
    assert _literal_collection(CANARY, "_ROLLBACK_STEPS") == (
        "R1-LATCH-FUTURE",
        "R2-FENCE-ATTEMPTS",
        "R3-REVOKE-DRAIN",
        "R4-TERMINATE-TREE",
        "R5-SETTLE-OR-DEBT",
        "R6-SETTLE-READINESS",
        "R7-ISSUE-CURRENT",
    )
    assert _literal_collection(CANARY, "_RECOVERY_STEPS") == (
        "V1-PRIOR-ABSENT",
        "V2-EXACT-REAPED",
        "V3-SAMEBOOT-UNKNOWN",
        "V4-CHANGEDBOOT-ABSENT",
        "V5-BUDGET-EXHAUSTED",
        "V6-HOST-RESTART",
    )
    rollback = _class_method_source(CANARY, "CodingProductWorkerCanary", "rollback")
    calls = (
        "coordinator.latch_kill_switch(",
        "domain.fence_attempt(",
        "domain.revoke_and_drain(",
        "coordinator.retire_exact(",
        "supervisor.fence(",
        "cleanup.settle(",
        "domain.settle_readiness(",
        "domain.issue_current(",
    )
    assert tuple(rollback.index(call) for call in calls) == tuple(
        sorted(rollback.index(call) for call in calls)
    )
    assert "current_owner.start" not in rollback
    recover = _class_method_source(CANARY, "CodingProductWorkerCanary", "recover")
    assert "steps != _RECOVERY_STEPS" in recover
    assert "coding_worker_recovery_incomplete" in recover


def test_c54_required_report_is_mandatory_in_linux_gate() -> None:
    makefile = _read(MAKEFILE)
    workflow = _read(WORKFLOW)
    for token in (
        "test-plc9c5-c54-linux-product",
        "check-plc9c5-c54-linux-product",
        "plc9c5-c54-linux-product.xml",
        "PLC9C5-C5.4-LINUX-PRODUCT",
    ):
        assert token in makefile
    for token in (
        "PLC9C5 C5.4 Linux Coding Product canary",
        "tests/harness/worker/test_coding_product_worker_canary.py",
        "plc9c5-c54-linux-product.xml",
        "PLC9C5-C5.4-LINUX-PRODUCT",
        "if-no-files-found: error",
    ):
        assert token in workflow
