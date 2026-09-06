from __future__ import annotations

import ast
from pathlib import Path

G8 = Path("docs/internals/architecture/apphost/product-worker-join-g8.md")
APPHOST_SCOPE = Path("docs/internals/architecture/apphost/README.md")
PLAN = Path("docs/internals/architecture/drafts/hosted-product-runtime-v1-plan.md")
APPHOST = Path("src/loushang/apphost")
CODING_JOIN = Path("src/loushang/coding/apphost_product.py")


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


def test_g8_0_design_is_indexed_and_status_honest() -> None:
    design = _read(G8)
    scope = _read(APPHOST_SCOPE)
    plan = _read(PLAN)
    normalized = " ".join(design.split())

    for field in (
        "- ID: `HOSTED-PRODUCT-G8`",
        "- Authority: normative accepted design",
        "- Design status: accepted",
        "- Implementation status: not-started — G8.0 design accepted; G8.1 not started",
        "- Activation status: default-dark; no installed entrypoint or default Product route",
    ):
        assert field in design
    assert "[G8 Product/Worker Join](product-worker-join-g8.md)" in scope
    assert "accepted G8.0 design; G8.1--G8.3" in plan
    assert "G7 is closed" in plan
    assert "Normal close is not rollback" in normalized


def test_g8_0_freezes_dependency_and_activation_boundaries() -> None:
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


def test_g8_0_has_exact_delivery_and_evidence_matrix() -> None:
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


def test_g8_0_changes_no_production_source_or_entrypoint() -> None:
    assert not CODING_JOIN.exists()
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
