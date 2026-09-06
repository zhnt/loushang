from __future__ import annotations

import ast
import json
from pathlib import Path

G8 = Path("docs/internals/architecture/apphost/product-worker-join-g8.md")
APPHOST_SCOPE = Path("docs/internals/architecture/apphost/README.md")
PLAN = Path("docs/internals/architecture/drafts/hosted-product-runtime-v1-plan.md")
APPHOST = Path("src/loushang/apphost")
CODING_JOIN = Path("src/loushang/coding/apphost_product.py")
EVIDENCE = Path(
    "docs/internals/architecture/apphost/hosted-product-g8-evidence-manifest.json"
)
MAKEFILE = Path("Makefile")
APPHOST_WORKFLOW = Path(".github/workflows/apphost-quality.yml")
HARNESS_WORKFLOW = Path(".github/workflows/harness-quality.yml")
HOSTING_WORKFLOW = Path(".github/workflows/hosting-quality.yml")

G8_REPORT_CASES = {
    "G8-EXACT-RECEIPT",
    "G8-RECEIPT-MISMATCH",
    "G8-RECOVERY-FIRST",
    "G8-REQUIRED-READY",
    "G8-OPTIONAL-DEGRADED",
    "G8-UNRELATED-WORKER-FREE",
    "G8-MULTIPROFILE-SINGLE-FLIGHT",
    "G8-MULTISESSION-ISOLATION",
    "G8-DETACH-NONOWNING",
    "G8-STALE-DETACH",
    "G8-CANCEL-COMPENSATION",
    "G8-START-FAIL-NO-FALLBACK",
    "G8-CLOSE-DEBT-RETRY",
    "G8-SHUTDOWN-ORDER",
    "G8-CROSS-ENTRYPOINT",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    package = path.parent.relative_to("src").parts
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            retained = len(package) - (node.level - 1) if node.level else 0
            base = (
                (*package[:retained], *(node.module or "").split("."))
                if node.level
                else tuple((node.module or "").split("."))
            )
            normalized = tuple(part for part in base if part)
            if normalized:
                imported.add(".".join(normalized))
    return imported


def test_g8_design_is_indexed_and_status_honest() -> None:
    design = _read(G8)
    scope = _read(APPHOST_SCOPE)
    plan = _read(PLAN)
    normalized = " ".join(design.split())

    for field in (
        "- ID: `HOSTED-PRODUCT-G8`",
        "- Authority: normative accepted design",
        "- Design status: accepted",
        "- Implementation status: implemented — G8.1--G8.3 complete",
        "- Activation status: default-dark; no installed entrypoint or default Product route",
    ):
        assert field in design
    assert "[G8 Product/Worker Join](product-worker-join-g8.md)" in scope
    assert "implemented G8.0--G8.3 default-dark" in plan
    assert "G7 is closed" in plan
    assert "Normal close is not rollback" in normalized


def test_g8_freezes_dependency_and_activation_boundaries() -> None:
    design = _read(G8)
    normalized = " ".join(design.split())
    for proof in (
        "The concrete Product owns the join",
        "The activation receipt is the join authority",
        "One AppHost live binding owns one Worker attempt",
        "Recovery precedes effect",
        "Profiles borrow facts, not authority",
        "A Worker-free Product is genuinely Worker-free",
        "no installed entrypoint or current Coding bootstrap imports the G8 module",
    ):
        assert proof in normalized
    assert "loushang.coding.apphost_product -> loushang.apphost public facade" in design
    assert "loushang.apphost -/-> loushang.coding" in design
    assert "Current owner deletion and G9 remain forbidden" in normalized


def test_g8_has_exact_delivery_and_evidence_matrix() -> None:
    design = _read(G8)
    for slice_id in ("G8.0", "G8.1", "G8.2", "G8.3"):
        assert f"| {slice_id} |" in design
    for case_id in (
        "G8-EXACT-RECEIPT",
        "G8-RECEIPT-MISMATCH",
        "G8-RECOVERY-FIRST",
        "G8-REQUIRED-READY",
        "G8-OPTIONAL-DEGRADED",
        "G8-UNRELATED-WORKER-FREE",
        "G8-MULTIPROFILE-SINGLE-FLIGHT",
        "G8-MULTISESSION-ISOLATION",
        "G8-DETACH-NONOWNING",
        "G8-STALE-DETACH",
        "G8-CANCEL-COMPENSATION",
        "G8-START-FAIL-NO-FALLBACK",
        "G8-CLOSE-DEBT-RETRY",
        "G8-SHUTDOWN-ORDER",
        "G8-CROSS-ENTRYPOINT",
        "G8-LINUX-RETAINED",
        "G8-WINDOWS-RETAINED",
    ):
        assert f"`{case_id}`" in design


def test_g8_concrete_join_preserves_dependency_and_activation_boundaries() -> None:
    assert CODING_JOIN.is_file()
    imports = _imports(CODING_JOIN)
    assert "loushang.apphost" in imports
    assert "loushang.harness.worker" in imports
    assert not any(
        name.startswith(
            (
                "loushang.appserver",
                "loushang.appservice",
                "loushang.hosting",
                "loushang.harnesstui",
                "loushang.harnessgui",
                "loushang.harnesswebui",
            )
        )
        for name in imports
    )
    assert not any(
        name.startswith("loushang.apphost.")
        for name in imports
    )
    for path in APPHOST.rglob("*.py"):
        imports = _imports(path)
        assert "loushang.coding" not in imports
        assert not any(name.startswith("loushang.coding.") for name in imports)
    for path in (
        Path("src/loushang/coding/bootstrap.py"),
        Path("src/loushang/coding/cli/__main__.py"),
        Path("src/loushang/coding/ui/cli.py"),
    ):
        assert "apphost_product" not in _read(path)


def test_g8_join_adopts_before_inspection_and_recovers_before_effect() -> None:
    source = _read(CODING_JOIN)
    assert source.index("owner = _WorkerAttemptOwner(raw)") < source.index(
        "receipt = owner.receipt()"
    )
    assert source.index("await owner.recover()") < source.index(
        "status = await owner.start("
    )
    assert "self._active: set[_WorkerAttemptOwner]" in source
    assert "self._debt: set[_WorkerAttemptOwner]" in source
    assert "await self.settle_pending_cleanup()" in source
    assert "product_factory: CodingAppHostProductFactoryV1" in source
    assert "attempt_factory: CodingAppHostWorkerAttemptFactoryV1" not in source[
        source.index("def coding_apphost_product_registration(") :
    ]


def test_g8_profile_projection_is_frozen_pathless_and_noncontrolling() -> None:
    module = ast.parse(_read(CODING_JOIN), filename=str(CODING_JOIN))
    projection = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and node.name == "CodingAppHostProductBindingV1"
    )
    fields = {
        node.target.id
        for node in projection.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    }
    assert fields == {
        "binding_key",
        "receipt_fingerprint",
        "attempt_id",
        "owner_generation",
        "required",
        "requested_owner",
        "effective_owner",
        "readiness",
        "status_code",
        "join_version",
    }
    assert fields.isdisjoint(
        {
            "canary",
            "supervisor",
            "process",
            "native_profile",
            "receipt",
            "rollback",
            "close",
            "path",
        }
    )


def test_g8_zero_skip_manifest_and_cross_platform_gates_are_mandatory() -> None:
    manifest = json.loads(_read(EVIDENCE))
    assert set(manifest) == {"manifestVersion", "reports"}
    assert manifest["manifestVersion"] == 1
    report = manifest["reports"]["HOSTED-PRODUCT-G8-JOIN"]
    assert set(report) == {
        "junitPath",
        "minimumTests",
        "requiredCaseIds",
        "status",
    }
    assert report["junitPath"] == ".artifacts/hosted-product-g8.xml"
    assert report["minimumTests"] == 18
    assert report["status"] == "implemented"
    assert set(report["requiredCaseIds"]) == G8_REPORT_CASES
    assert len(report["requiredCaseIds"]) == len(G8_REPORT_CASES)

    makefile = _read(MAKEFILE)
    apphost_workflow = _read(APPHOST_WORKFLOW)
    for source in (makefile, apphost_workflow):
        assert "tests/coding/test_apphost_product.py" in source
        assert "hosted-product-g8.xml" in source
        assert "verify_evidence_manifest.py" in source
        assert "HOSTED-PRODUCT-G8-JOIN" in source
    assert "runs-on: windows-2022" in apphost_workflow

    harness_workflow = _read(HARNESS_WORKFLOW)
    hosting_workflow = _read(HOSTING_WORKFLOW)
    assert "PLC9C5-C5.4-LINUX-PRODUCT" in harness_workflow
    assert "PLC9C5-C5.5B-WINDOWS-LPAC-NATIVE" in hosting_workflow
    assert "PLC9C5-C5.5C-WINDOWS-PRODUCT" in hosting_workflow
