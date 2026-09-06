from __future__ import annotations

import ast
from pathlib import Path

G9 = Path("docs/internals/architecture/apphost/hosted-product-v1-closure-g9.md")
APPHOST_SCOPE = Path("docs/internals/architecture/apphost/README.md")
PLAN = Path("docs/internals/architecture/drafts/hosted-product-runtime-v1-plan.md")
INVENTORY = Path(
    "docs/internals/architecture/hosting/validation/"
    "hosted-product-runtime-v1-inventory.md"
)
AOD = Path("docs/internals/architecture/architecture-overview.md")
GAP_LEDGER = Path("docs/internals/architecture/current-target-gap-ledger.md")
APPHOST = Path("src/loushang/apphost")
APPHOST_CORE = {
    APPHOST / "__init__.py",
    APPHOST / "_ownership.py",
    APPHOST / "catalog.py",
    APPHOST / "contracts.py",
    APPHOST / "errors.py",
    APPHOST / "router.py",
    APPHOST / "runtime.py",
}
OWNER_SELECTION = Path("src/loushang/harness/worker/owner_selection.py")
TARGET_COMPOSITION = Path("src/loushang/coding/apphost_composition.py")
G9_EVIDENCE = Path(
    "docs/internals/architecture/apphost/hosted-product-g9-evidence-manifest.json"
)
CURRENT_DECISION = Path(
    "docs/internals/architecture/apphost/current-worker-owner-decision-g9.md"
)
INSTALLED_CODING_ROOTS = (
    Path("src/loushang/coding/bootstrap.py"),
    Path("src/loushang/coding/cli/__main__.py"),
    Path("src/loushang/coding/ui/cli.py"),
)

G9_DRILL_CASES = {
    "G9-COMPOSE-EXPLICIT",
    "G9-OMISSION-CURRENT",
    "G9-ROLLBACK-BEFORE-EFFECT",
    "G9-ROLLBACK-INFLIGHT-STICKY",
    "G9-ROLLBACK-NO-FALLBACK",
    "G9-ROLLBACK-DRAIN-ORDER",
    "G9-CRASH-RECOVERY",
    "G9-CLEANUP-DEBT-RETRY",
    "G9-MULTIPROFILE-SINGLE-FLIGHT",
    "G9-MULTISESSION-ISOLATION",
    "G9-RESTART-GENERATION",
    "G9-ENTRYPOINT-INVENTORY",
    "G9-DEPENDENCY-GRAPH",
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


def test_g9_0_design_is_indexed_and_status_honest() -> None:
    design = _read(G9)
    scope = _read(APPHOST_SCOPE)
    plan = _read(PLAN)
    for field in (
        "- ID: `HOSTED-PRODUCT-G9`",
        "- Authority: normative accepted design",
        "- Design status: accepted",
        "- Implementation status: partial — G9.0 design and executable guards only",
        "- Activation status: default-dark; omitted Worker owner remains Current",
    ):
        assert field in design
    assert "[G9 V1 Closure](hosted-product-v1-closure-g9.md)" in scope
    assert "accepted G9.0 closure baseline; G9.1--G9.4 remain" in plan
    assert "Passing G9.0 permits G9.1 implementation" in design


def test_g9_freezes_independent_control_points_and_owners() -> None:
    normalized = " ".join(_read(G9).split())
    for requirement in (
        "G9-R1-EXPLICIT-COMPOSITION",
        "G9-R2-NO-IMPLICIT-ACTIVATION",
        "G9-R3-OPERABLE-ROLLBACK",
        "G9-R4-EVIDENCE-BASED-DELETION",
        "G9-R5-INDEPENDENT-PROMOTION",
        "G9-R6-TRACEABLE-CLOSURE",
    ):
        assert f"`{requirement}`" in normalized
    for proof in (
        "code availability on `main` is not activation",
        "activation is not a default change",
        "a default change is not authority to delete Current",
        "installed Product composition and explicit selection",
        "concrete Product package",
        "Product/runtime binding and phased shutdown",
        "Current-retention decision and lane promotion",
        "common-parent architecture owner",
    ):
        assert proof in normalized


def test_g9_has_exact_delivery_and_operational_drill_matrix() -> None:
    design = _read(G9)
    for slice_id in ("G9.0", "G9.1", "G9.2", "G9.3", "G9.4"):
        assert f"| {slice_id} |" in design
    drill = design.split("### Required drill cases", maxsplit=1)[1].split(
        "## Current Owner Retention Or Deletion Gate", maxsplit=1
    )[0]
    observed = {
        line.split("`")[1]
        for line in drill.splitlines()
        if line.startswith("| `G9-")
    }
    assert observed == G9_DRILL_CASES
    for proof in (
        "uses controlled process doubles where live native execution is unsafe",
        "retains Linux and Windows reports separately",
        "future `hosted-product-g9-evidence-manifest.json`",
        "two zero-skip JUnit report identities",
    ):
        assert proof in design

    traceability = design.split("## Traceability", maxsplit=1)[1].split(
        "## Threat Model", maxsplit=1
    )[0]
    for requirement in (
        "G9-R1-EXPLICIT-COMPOSITION",
        "G9-R2-NO-IMPLICIT-ACTIVATION",
        "G9-R3-OPERABLE-ROLLBACK",
        "G9-R4-EVIDENCE-BASED-DELETION",
        "G9-R5-INDEPENDENT-PROMOTION",
        "G9-R6-TRACEABLE-CLOSURE",
    ):
        assert f"| `{requirement}` |" in traceability


def test_g9_current_deletion_is_an_explicit_all_conditions_gate() -> None:
    decision = _read(G9).split(
        "## Current Owner Retention Or Deletion Gate", maxsplit=1
    )[1].split("## Main Promotion Plan", maxsplit=1)[0]
    normalized = " ".join(decision.split())
    for proof in (
        "exactly one conclusion: `RETAIN` or `DELETE`",
        "`RETAIN` is a successful G9 decision and does not block V1 promotion",
        "AST/import/composition inventory proves zero production Current-owner consumers",
        "every installed and supported CLI, TUI, SDK, AppServer, hosted, and mux entrypoint",
        "a separately accepted replacement rollback strategy exists",
        "the deletion is a dedicated PR",
        "If any condition is false or unknown, the required result is `RETAIN`",
    ):
        assert proof in normalized
    numbered_conditions = [
        line for line in decision.splitlines() if line[:1].isdigit() and ". " in line
    ]
    assert len(numbered_conditions) == 8


def test_g9_main_promotion_does_not_grant_activation_or_deletion() -> None:
    promotion = _read(G9).split("## Main Promotion Plan", maxsplit=1)[1].split(
        "## Delivery Slices", maxsplit=1
    )[0]
    normalized = " ".join(promotion.split())
    for proof in (
        "G9 baseline on `lane/harness`",
        "closure implementation on `lane/harness`",
        "`lane/harness -> main` PR",
        "route activation merely because code is on `main`",
        "preserve default-dark semantics",
        "Local `main` is refreshed only after the remote merge is complete",
        "`make check-apphost`",
        "`make check-harness`",
        "`make check-hosting`",
        "`make check-architecture-docs`",
        "`make test-plc9c5-c54-linux-product`",
        "same immutable PR head",
    ):
        assert proof in normalized


def test_g9_0_keeps_composition_evidence_and_deletion_artifacts_absent() -> None:
    assert not TARGET_COMPOSITION.exists()
    assert not G9_EVIDENCE.exists()
    assert not CURRENT_DECISION.exists()
    for path in INSTALLED_CODING_ROOTS:
        source = _read(path)
        assert "apphost_product" not in source
        assert "apphost_composition" not in source


def test_g9_0_keeps_current_as_omission_and_has_no_same_attempt_retry() -> None:
    source = _read(OWNER_SELECTION)
    module = ast.parse(source, filename=str(OWNER_SELECTION))
    activation = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and node.name == "WorkerHostingActivationV1"
    )
    owner_field = next(
        node
        for node in activation.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "owner"
    )
    assert isinstance(owner_field.value, ast.Constant)
    assert owner_field.value.value == "current"
    assert _imports(OWNER_SELECTION).isdisjoint({"os", "platform"})
    assert "environ" not in source
    assert "getenv" not in source

    router = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "WorkerSessionOwnerRouter"
    )
    start = next(
        node
        for node in router.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "start"
    )
    start_source = ast.get_source_segment(source, start)
    assert start_source is not None
    assert start_source.count("await port.start(") == 1
    assert "except" not in start_source


def test_g9_0_retains_apphost_core_and_current_inventory_fences() -> None:
    for path in APPHOST.rglob("*.py"):
        imports = _imports(path)
        assert not any(
            name == "loushang.coding" or name.startswith("loushang.coding.")
            for name in imports
        )
        assert not any(
            name == "loushang.hosting" or name.startswith("loushang.hosting.")
            for name in imports
        )
    for path in APPHOST_CORE:
        source = _read(path)
        imports = _imports(path)
        assert not any(
            name == prefix or name.startswith(f"{prefix}.")
            for name in imports
            for prefix in ("os", "platform", "importlib")
        )
        calls = {
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            for node in ast.walk(ast.parse(source, filename=str(path)))
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        assert calls.isdisjoint({"getenv", "environ", "entry_points", "__import__"})
    inventory = _read(INVENTORY)
    assert "has no installed entrypoint consumer" in inventory
    assert "`src/loushang/coding/apphost_composition.py` remains absent" in inventory
    assert "omission remains Current" in inventory
    assert "G9.1--G9.4 still own composition" in inventory

    aod = _read(AOD)
    ledger = _read(GAP_LEDGER)
    assert "G9.0 accepts separate gates" in aod
    assert "Current remains unchanged" in aod
    assert "G9.0 accepts the closure gates but adds no production composition" in ledger


def test_g9_guard_is_part_of_the_apphost_quality_gate() -> None:
    makefile = _read(Path("Makefile"))
    assert "tests/architecture/test_hosted_product_runtime_g9_closure.py" in makefile
    assert "check-apphost: lint-apphost typecheck-apphost test-apphost" in makefile
