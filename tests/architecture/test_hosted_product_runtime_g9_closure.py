from __future__ import annotations

import ast
import json
import tomllib
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
G9_ENTRYPOINTS = Path(
    "docs/internals/architecture/apphost/hosted-product-g9-entrypoint-inventory.json"
)
CURRENT_DECISION = Path(
    "docs/internals/architecture/apphost/current-worker-owner-decision-g9.md"
)
PROMOTION_RECORD = Path(
    "docs/internals/architecture/apphost/hosted-product-g9-promotion-record.md"
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


def test_g9_4_design_is_indexed_and_status_honest() -> None:
    design = _read(G9)
    scope = _read(APPHOST_SCOPE)
    plan = _read(PLAN)
    for field in (
        "- ID: `HOSTED-PRODUCT-G9`",
        "- Authority: normative accepted design",
        "- Design status: accepted",
        "- Implementation status: implemented — G9.0--G9.4 complete and promoted",
        "- Activation status: default-dark; omitted Worker owner remains Current",
    ):
        assert field in design
    assert "[G9 V1 Closure](hosted-product-v1-closure-g9.md)" in scope
    assert (
        "[G9.3 Current Owner Decision](current-worker-owner-decision-g9.md)"
        in scope
    )
    assert "[G9 Promotion Record](hosted-product-g9-promotion-record.md)" in scope
    assert (
        "| G9.3 | entrypoint inventory and Current-owner RETAIN/DELETE decision | "
        "implemented; `RETAIN` accepted |"
    ) in scope
    assert (
        "| G9.4 | architecture reconciliation and lane-to-main promotion | "
        "implemented; promoted default-dark |"
    ) in scope
    assert "implemented through G9.4 and promoted to `main`" in plan
    assert "Passing G9.4 grants capability availability only" in design


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
    normalized = " ".join(design.split())
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
        "`hosted-product-g9-evidence-manifest.json` pins the exact case set",
        "two zero-skip JUnit report identities",
    ):
        assert proof in normalized

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


def test_g9_3_accepts_one_retain_decision_and_audits_every_condition() -> None:
    assert CURRENT_DECISION.is_file()
    decision = _read(CURRENT_DECISION)
    status = decision.split("## Decision", maxsplit=1)[0]
    assert status.count("- Conclusion: `RETAIN`") == 1
    assert "Conclusion: `DELETE`" not in status
    assert "The G9.3 conclusion is exactly `RETAIN`." in decision
    assert "permits the separately controlled G9.4" in decision
    assert "This record is not changed in place to `DELETE`." in decision

    audit = decision.split("## Deletion Admission Audit", maxsplit=1)[1].split(
        "## Consequences", maxsplit=1
    )[0]
    rows = [line for line in audit.splitlines() if line.startswith("| ")]
    condition_rows = [line for line in rows if line.split("|")[1].strip().isdigit()]
    assert [line.split("|")[1].strip() for line in condition_rows] == [
        str(index) for index in range(1, 9)
    ]
    assert all("`NOT MET`" in line for line in condition_rows)
    for retained_gap in (
        "Coding bootstrap, installed CLI/TUI, and public SDK remain Current consumers",
        "no replacement rollback strategy is accepted",
        "generic Session identity envelope remains uncomposed",
        "No deletion PR exists",
    ):
        assert retained_gap.casefold() in audit.casefold()


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


def test_g9_4_promotion_record_pins_exact_successful_head_and_controls() -> None:
    assert PROMOTION_RECORD.is_file()
    record = _read(PROMOTION_RECORD)
    status = record.split("## Promotion Identity", maxsplit=1)[0]
    for field in (
        "- ID: `HOSTED-PRODUCT-G9-PROMOTION`",
        "- Authority: descriptive — completed immutable promotion evidence",
        "- Implementation status: implemented — promotion complete",
        "- Promotion status: merged to `main`",
        "- Activation status: default-dark; omitted Worker owner remains Current",
        "- Effect: capability availability only",
    ):
        assert field in status

    normalized = " ".join(record.split())
    for identity in (
        "[#556](https://github.com/zhnt/loushang/pull/556)",
        "`07ad9a9984295449d9fc0db45c4a76d3e8bf8c34`",
        "`445c0fb567163ed92b1163456133ff7545362de9`",
        "head_sha=07ad9a9984295449d9fc0db45c4a76d3e8bf8c34",
        "event `pull_request`",
        "run attempt 1",
        "conclusion `success`",
    ):
        assert identity in normalized

    evidence = record.split("## Exact-Head Gate Evidence", maxsplit=1)[1].split(
        "## Reconciled Result", maxsplit=1
    )[0]
    expected_runs = {
        "Architecture Quality": "34039700017",
        "AI Quality": "34039700020",
        "Harness Quality": "34039700046",
        "AppHost Quality": "34039700011",
        "TUI Cross-platform Contracts": "34039700009",
        "Harnesstui Quality": "34039700021",
        "Host Runtime Quality": "34039700038",
        "Hosting Quality": "34039700010",
        "Windows Shell Compatibility": "34039700014",
    }
    for workflow, run_id in expected_runs.items():
        assert f"`{workflow}` / `{run_id}`" in evidence
    assert evidence.count("| `success` |") == len(expected_runs)

    reconciled = record.split("## Reconciled Result", maxsplit=1)[1]
    for retained_control in (
        "no installed Coding CLI, TUI, SDK, AppServer, hosted, or mux entrypoint",
        "omission remains Current",
        "cannot fall back to Current in that attempt",
        "G9.3 `RETAIN` decision",
        "require later independent changes",
    ):
        assert retained_control in reconciled


def test_g9_3_inventory_disposes_every_supported_surface_and_retains_current() -> None:
    assert TARGET_COMPOSITION.is_file()
    assert G9_EVIDENCE.is_file()
    assert G9_ENTRYPOINTS.is_file()
    assert CURRENT_DECISION.is_file()
    for path in INSTALLED_CODING_ROOTS:
        source = _read(path)
        assert "apphost_composition" not in source

    inventory = json.loads(_read(G9_ENTRYPOINTS))
    assert set(inventory) == {"inventoryVersion", "decision", "entries"}
    assert inventory["inventoryVersion"] == 2
    assert inventory["decision"] == "RETAIN"
    rows = {row["entrypointId"]: row for row in inventory["entries"]}
    assert set(rows) == {
        "coding.apphost.composition",
        "apphost.hosted",
        "appserver.package",
        "coding.arch.module-cli",
        "coding.bootstrap",
        "coding.cli",
        "coding.sdk",
        "coding.tui",
        "harnesstui.named-mux",
        "plugin.cli",
    }
    assert rows["coding.apphost.composition"]["disposition"] == "explicit-hosting"
    assert rows["coding.apphost.composition"]["importsComposition"] is True
    assert rows["coding.apphost.composition"]["source"] == TARGET_COMPOSITION.as_posix()
    assert rows["coding.apphost.composition"]["omissionOwner"] is None
    for entrypoint_id in (
        "coding.bootstrap",
        "coding.cli",
        "coding.sdk",
        "coding.tui",
    ):
        assert rows[entrypoint_id]["disposition"] == "current-only"
        assert rows[entrypoint_id]["importsComposition"] is False
        assert rows[entrypoint_id]["omissionOwner"] == "current"

    assert rows["appserver.package"]["disposition"] == (
        "contract-only-no-entrypoint"
    )
    assert rows["apphost.hosted"]["disposition"] == "binder-only-no-entrypoint"
    assert rows["harnesstui.named-mux"]["disposition"] == (
        "design-only-no-entrypoint"
    )
    for entrypoint_id in ("coding.arch.module-cli", "plugin.cli"):
        assert rows[entrypoint_id]["disposition"] == "non-product-tool"
        assert rows[entrypoint_id]["omissionOwner"] is None

    for row in rows.values():
        assert set(row) == {
            "disposition",
            "entrypointId",
            "importsComposition",
            "omissionOwner",
            "packagingBinding",
            "source",
            "supportStatus",
            "surface",
        }
        assert Path(row["source"]).is_file()

    assert {row["surface"] for row in rows.values()} == {
        "appserver",
        "bootstrap",
        "cli",
        "composition",
        "hosted",
        "mux",
        "sdk",
        "tui",
    }
    assert {
        entrypoint_id: (row["surface"], row["supportStatus"])
        for entrypoint_id, row in rows.items()
    } == {
        "apphost.hosted": ("hosted", "binder-only"),
        "appserver.package": ("appserver", "contract-only"),
        "coding.apphost.composition": ("composition", "explicit-library"),
        "coding.arch.module-cli": ("cli", "supported-module"),
        "coding.bootstrap": ("bootstrap", "supported-library"),
        "coding.cli": ("cli", "installed"),
        "coding.sdk": ("sdk", "supported-library"),
        "coding.tui": ("tui", "installed"),
        "harnesstui.named-mux": ("mux", "design-only"),
        "plugin.cli": ("cli", "installed"),
    }

    project = tomllib.loads(_read(Path("pyproject.toml")))
    scripts = project["project"]["scripts"]
    assert scripts == {
        "loushang": "loushang.coding.cli.__main__:main",
        "loushang-plugin": "loushang.plugin.__main__:main",
        "loushang-tui": "loushang.coding.ui.cli:main",
    }
    bindings = {
        row["packagingBinding"]: row["entrypointId"]
        for row in rows.values()
        if row["packagingBinding"] is not None
    }
    assert bindings == {
        "project.scripts.loushang": "coding.cli",
        "project.scripts.loushang-plugin": "plugin.cli",
        "project.scripts.loushang-tui": "coding.tui",
    }

    assert "loushang.coding.bootstrap" in _imports(
        Path("src/loushang/coding/__init__.py")
    )
    assert "loushang.coding.bootstrap" in _imports(
        Path("src/loushang/coding/cli/__main__.py")
    )
    assert "loushang.coding.cli.__main__" in _imports(
        Path("src/loushang/coding/ui/cli.py")
    )
    assert {path.name for path in Path("src/loushang/appserver").glob("*.py")} == {
        "__init__.py",
        "ports.py",
    }
    assert not any(
        "mux" in path.name.casefold()
        for path in Path("src/loushang/harnesstui").rglob("*.py")
    )
    for entrypoint_id in ("appserver.package", "apphost.hosted"):
        source = _read(Path(rows[entrypoint_id]["source"]))
        module = ast.parse(source, filename=rows[entrypoint_id]["source"])
        assert not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
            for node in module.body
        )

    expected_imports = {
        "__future__",
        "asyncio",
        "contextlib",
        "dataclasses",
        "inspect",
        "loushang.apphost",
        "loushang.coding.apphost_product",
        "loushang.coding.product_plan",
        "re",
        "typing",
    }
    assert _imports(TARGET_COMPOSITION) == expected_imports
    for path in Path("src/loushang").rglob("*.py"):
        if path != TARGET_COMPOSITION:
            assert "apphost_composition" not in _read(path)


def test_g9_2_keeps_current_as_omission_and_has_no_same_attempt_retry() -> None:
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


def test_g9_4_retains_apphost_core_and_current_inventory_fences() -> None:
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
    assert "explicit installed composition owner" in inventory
    assert "`src/loushang/coding/apphost_composition.py`" in inventory
    assert "omission remains Current" in inventory
    assert "G9.3 records the" in inventory
    assert "accepted `RETAIN` decision" in inventory
    assert "G9.4 promotes" in inventory

    aod = _read(AOD)
    ledger = _read(GAP_LEDGER)
    assert "G9.1--G9.2 implement the explicit composition and drill" in aod
    assert "G9.3 accepts a source-backed `RETAIN` decision" in aod
    assert "Current remains unchanged" in aod
    assert "G8--G9.4 are implemented and promoted default-dark" in ledger
    assert "all eight deletion conditions were unmet" in ledger


def test_g9_2_evidence_manifest_and_platform_gates_are_exact() -> None:
    manifest = json.loads(_read(G9_EVIDENCE))
    assert set(manifest) == {"manifestVersion", "reports"}
    assert manifest["manifestVersion"] == 1
    assert set(manifest["reports"]) == {
        "HOSTED-PRODUCT-G9-LINUX",
        "HOSTED-PRODUCT-G9-WINDOWS",
    }
    for report in manifest["reports"].values():
        assert report["minimumTests"] == 13
        assert set(report["requiredCaseIds"]) == G9_DRILL_CASES
        assert report["status"] == "implemented"

    makefile = _read(Path("Makefile"))
    workflow = _read(Path(".github/workflows/apphost-quality.yml"))
    assert "test-hosted-product-g9-linux-evidence" in makefile
    assert "HOSTED-PRODUCT-G9-LINUX" in makefile
    assert "HOSTED-PRODUCT-G9-LINUX" in workflow
    assert "HOSTED-PRODUCT-G9-WINDOWS" in workflow
    assert ".artifacts/hosted-product-g9-windows.xml" in workflow


def test_g9_guard_is_part_of_the_apphost_quality_gate() -> None:
    makefile = _read(Path("Makefile"))
    assert "tests/architecture/test_hosted_product_runtime_g9_closure.py" in makefile
    assert "check-apphost: lint-apphost typecheck-apphost test-apphost" in makefile
    assert "test-hosted-product-g9-linux-evidence" in makefile
