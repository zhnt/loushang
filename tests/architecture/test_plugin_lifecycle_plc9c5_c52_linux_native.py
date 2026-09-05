from __future__ import annotations

import ast
import json
from pathlib import Path

BRIDGE = Path("src/loushang/harness/worker/_native_profile_bridge.py")
HOSTING_ADAPTER = Path("src/loushang/harness/worker/hosting_adapter.py")
WORKER_FACADE = Path("src/loushang/harness/worker/__init__.py")
WORKER_ROOT = Path("src/loushang/harness/worker")
HOSTING_ROOT = Path("src/loushang/hosting")
SOURCE_ROOT = Path("src/loushang")
DOCUMENT = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c52-linux-native.md"
)
BASELINE = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c50-baseline.md"
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
BEHAVIOR = Path("tests/harness/worker/test_native_profile_bridge.py")
MAKEFILE = Path("Makefile")
HARNESS_WORKFLOW = Path(".github/workflows/harness-quality.yml")
HOSTING_WORKFLOW = Path(".github/workflows/hosting-quality.yml")

C52_CASES = {
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
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _literal_collection(path: Path, name: str) -> set[str]:
    tree = ast.parse(_read(path), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            assert node.value is not None
            value = ast.literal_eval(node.value)
            assert isinstance(value, (tuple, list, set, frozenset))
            return set(value)
    raise AssertionError(f"{name} is absent from {path}")


def _imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
            result.update(f"{node.module}.{alias.name}" for alias in node.names)
    return result


def _imported_names(path: Path, module: str) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            result.update(alias.name for alias in node.names)
    return result


def _class_source(path: Path, name: str) -> str:
    source = _read(path)
    for node in ast.parse(source, filename=str(path)).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            result = ast.get_source_segment(source, node)
            assert result is not None
            return result
    raise AssertionError(f"{name} is absent from {path}")


def test_c52_status_inventory_and_index_are_honest() -> None:
    document = " ".join(_read(DOCUMENT).split())
    baseline = " ".join(_read(BASELINE).split())
    inventory = " ".join(_read(INVENTORY).split())
    index = _read(INDEX)
    for token in (
        "ID: `PLC9C5-C5.2-LINUX-NATIVE`",
        "Implementation status: implemented",
        "Activation status: closed",
        "Production default: Current",
        "no production Product composition exists",
        "single-use",
        "Same-boot uncertainty remains durable cleanup debt",
    ):
        assert token in document
    assert "implemented through C5.4" in baseline
    assert "C5.2 Linux native profile binding" in baseline
    assert "C5-C52-LINUX-NATIVE" in inventory
    assert "no Product, Coding, AppHost, CLI, presenter, or Session composition" in document
    assert index.count("(plugin-lifecycle-plc9c5-c52-linux-native.md)") == 1


def test_c52_public_surface_is_one_handle_free_port() -> None:
    assert _literal_collection(BRIDGE, "__all__") == {
        "ProductWorkerNativeProfilePort"
    }
    assert "ProductWorkerNativeProfilePort" in _literal_collection(
        WORKER_FACADE,
        "__all__",
    )
    protocol = _class_source(BRIDGE, "ProductWorkerNativeProfilePort")
    for member in (
        "receipt_fingerprint",
        "worker_request_fingerprint",
        "native_profile_id",
        "native_profile_catalog_revision",
        "realized_native_policy_closure_fingerprint",
        "execution_closure_fingerprint",
        "capture_native",
        "verify_current",
        "close",
    ):
        assert member in protocol
    for forbidden in (
        "_PosixStaticContainedLaunchCaptureSpec",
        "_PosixStaticLaunchCaptureBackend",
        "_LaunchCapturePort",
        "_ManagedLaunchPreparationResult",
    ):
        assert forbidden not in protocol


def test_c52_private_imports_are_exact_lazy_and_one_way() -> None:
    private_posix = "loushang.hosting._posix_launch_preparation"
    private_windows = "loushang.hosting._windows_launch_preparation"
    private_managed = "loushang.hosting._launch_preparation"
    assert _imported_names(BRIDGE, private_posix) == {
        "_PosixStaticContainedLaunchCaptureSpec",
        "_PosixStaticLaunchCaptureBackend",
    }
    top_level_imports = {
        node.module
        for node in ast.parse(_read(BRIDGE), filename=str(BRIDGE)).body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert private_posix not in top_level_imports
    posix_consumers = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if not path.is_relative_to(HOSTING_ROOT) and private_posix in _imports(path)
    }
    windows_consumers = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if not path.is_relative_to(HOSTING_ROOT) and private_windows in _imports(path)
    }
    managed_consumers = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if not path.is_relative_to(HOSTING_ROOT) and private_managed in _imports(path)
    }
    assert posix_consumers == {BRIDGE}
    assert windows_consumers == set()
    assert managed_consumers == {HOSTING_ADAPTER}
    imports = _imports(BRIDGE)
    assert not any(
        name.startswith(("loushang.coding", "loushang.apphost")) for name in imports
    )
    bridge = _read(BRIDGE)
    for forbidden in ("os.environ", "subprocess", "ctypes", "_win32_process"):
        assert forbidden not in bridge


def test_c52_bridge_has_one_explicit_product_consumer_and_adapter_stays_blind() -> None:
    factory = "_bind_posix_static_contained_product_worker_profile"
    consumers = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if path != BRIDGE and factory in _read(path)
    }
    assert consumers == {Path("src/loushang/coding/_product_worker_canary.py")}
    adapter = _read(HOSTING_ADAPTER)
    assert "ProductWorkerNativeProfilePort" in adapter
    for forbidden in (
        "_PosixStaticContainedLaunchCaptureSpec",
        "_PosixStaticLaunchCaptureBackend",
        "posix-static-contained-elf-v1",
    ):
        assert forbidden not in adapter
    owner_selection = _read(WORKER_ROOT / "owner_selection.py")
    assert 'owner: WorkerSessionOwner = "current"' in owner_selection
    assert "os.environ" not in owner_selection


def test_c52_required_report_and_native_oracle_are_retained() -> None:
    manifest = json.loads(_read(MANIFEST))
    report = manifest["reports"]["PLC9C5-C5.2-LINUX-NATIVE"]
    assert report == {
        "junitPath": ".artifacts/plc9c5-c52-linux-native.xml",
        "minimumTests": 14,
        "requiredCaseIds": [
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
        ],
        "status": "implemented",
    }
    assert _literal_collection(BEHAVIOR, "PLC9C5_C52_CASES") == C52_CASES
    behavior = _read(BEHAVIOR)
    for oracle in (
        "test_posix_contained_launcher_rejects_profile_substitution_before_payload",
        "test_posix_static_cancellation_after_os_create_reclaims_process",
        "test_posix_contained_profile_blocks_descendant_group_escape",
        "_PosixStaticLaunchCaptureBackend",
        "test_c52_profile_port_joins_existing_managed_h6_seam",
    ):
        assert oracle in behavior
    test_node = next(
        node
        for node in ast.parse(behavior, filename=str(BEHAVIOR)).body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_plc9c5_c52_linux_native_case"
    )
    assert not any("skip" in ast.unparse(item) for item in test_node.decorator_list)


def test_c52_local_and_remote_gates_are_required() -> None:
    makefile = _read(MAKEFILE)
    harness_workflow = _read(HARNESS_WORKFLOW)
    hosting_workflow = _read(HOSTING_WORKFLOW)
    for token in (
        "test-plc9c5-c52-linux-native",
        "tests/harness/worker/test_native_profile_bridge.py",
        ".artifacts/plc9c5-c52-linux-native.xml",
        "PLC9C5-C5.2-LINUX-NATIVE",
        "verify_plc9c5_manifest.py",
    ):
        assert token in makefile
    for token in (
        "tests/harness/worker/test_native_profile_bridge.py",
        ".artifacts/plc9c5-c52-linux-native.xml",
        "PLC9C5-C5.2-LINUX-NATIVE",
        "verify_plc9c5_manifest.py",
    ):
        assert token in harness_workflow
    for token in (
        "src/loushang/harness/worker/_native_profile_bridge.py",
        "tests/harness/worker/test_native_profile_bridge.py",
        "tests/architecture/test_plugin_lifecycle_plc9c5_c52_linux_native.py",
    ):
        assert token in hosting_workflow
