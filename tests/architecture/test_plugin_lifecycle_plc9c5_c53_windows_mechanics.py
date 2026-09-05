from __future__ import annotations

import ast
import json
from pathlib import Path

WINDOWS_PREPARATION = Path("src/loushang/hosting/_windows_launch_preparation.py")
WIN32_API = Path("src/loushang/hosting/_win32_process.py")
HOSTING_FACADE = Path("src/loushang/hosting/__init__.py")
HOSTING_ROOT = Path("src/loushang/hosting")
SOURCE_ROOT = Path("src/loushang")
NATIVE_TEST = Path("tests/hosting/test_windows_launch_preparation_native.py")
REPORT_TEST = Path("tests/hosting/test_plc9c5_c53_windows_mechanics.py")
DOCUMENT = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc9c5-c53-windows-mechanics.md"
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
MAKEFILE = Path("Makefile")
HOSTING_WORKFLOW = Path(".github/workflows/hosting-quality.yml")

C53_CASES = {
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
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, name: str) -> str:
    source = _read(path)
    for node in ast.parse(source, filename=str(path)).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            result = ast.get_source_segment(source, node)
            assert result is not None
            return result
    raise AssertionError(f"{name} is absent from {path}")


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
    return result


def test_c53_status_manifest_and_index_are_honest() -> None:
    document = " ".join(_read(DOCUMENT).split())
    baseline = " ".join(_read(BASELINE).split())
    inventory = " ".join(_read(INVENTORY).split())
    manifest = json.loads(_read(MANIFEST))["reports"][
        "PLC9C5-C5.3-WINDOWS-MECHANICS"
    ]
    assert "ID: `PLC9C5-C5.3-WINDOWS-MECHANICS`" in document
    assert "Implementation status: implemented" in document
    assert "Activation status: closed" in document
    assert "Production default: Current" in document
    assert "implemented through C5.3" in baseline
    assert "C5-C53-WINDOWS-MECHANICS" in inventory
    assert _read(INDEX).count(
        "(plugin-lifecycle-plc9c5-c53-windows-mechanics.md)"
    ) == 1
    assert manifest["status"] == "implemented"
    assert manifest["minimumTests"] == 12
    assert set(manifest["requiredCaseIds"]) == C53_CASES
    assert _literal_collection(REPORT_TEST, "PLC9C5_C53_CASES") == C53_CASES


def test_c53_builder_is_private_os_sourced_and_environment_closed() -> None:
    builder = _function_source(
        WINDOWS_PREPARATION,
        "_build_windows_restricted_launch_capture_spec",
    )
    api_source = _read(WIN32_API)
    native_source = _read(NATIVE_TEST)
    assert "request.effective_environment" in builder
    assert builder.index("request.effective_environment") < builder.index(
        "_api or _CtypesWin32Api()"
    )
    assert "canonical_system_root" in builder
    assert "os.environ" not in builder
    assert "GetWindowsDirectoryW" in api_source
    assert 'os.environ["SystemRoot"]' not in native_source
    assert "_build_windows_restricted_launch_capture_spec" in native_source
    assert "_build_windows_restricted_launch_capture_spec" not in _read(
        HOSTING_FACADE
    )


def test_c53_has_no_harness_or_product_windows_private_friend() -> None:
    private_module = "loushang.hosting._windows_launch_preparation"
    consumers = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if not path.is_relative_to(HOSTING_ROOT) and private_module in _imports(path)
    }
    assert consumers == set()


def test_c53_required_report_is_windows_only_and_mandatory() -> None:
    report = _read(REPORT_TEST)
    makefile = _read(MAKEFILE)
    workflow = _read(HOSTING_WORKFLOW)
    for token in (
        'os.name != "nt"',
        "LOUSHANG_PLC9C5_C53_REPORT",
        "test_plc9c5_c53_windows_mechanics_case",
        "test_windows_restricted_native_job_reclaims_descendant",
        "test_windows_mechanics_profile_is_rejected_for_product_required_containment",
    ):
        assert token in report
    assert "test-plc9c5-c53-windows-mechanics" in makefile
    assert "check-plc9c5-c53-windows-mechanics" in makefile
    assert "PLC9C5 C5.3 Windows mechanics and rejection gate" in workflow
    assert "PLC9C5-C5.3-WINDOWS-MECHANICS" in workflow
    assert "plc9c5-c53-windows-mechanics.xml" in workflow
