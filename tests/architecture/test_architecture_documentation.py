from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_ROOT = REPOSITORY_ROOT / "docs/internals/architecture"
ARCHITECTURE_METHOD_ROOT = REPOSITORY_ROOT / "docs/internals/architecture-method"
GAP_LEDGER = ARCHITECTURE_ROOT / "current-target-gap-ledger.md"
INITIAL_GOVERNED_DOCUMENTS = (
    ARCHITECTURE_METHOD_ROOT / "README.md",
    ARCHITECTURE_METHOD_ROOT / "artifact-model.md",
    ARCHITECTURE_METHOD_ROOT / "architecture-decisions.md",
    ARCHITECTURE_METHOD_ROOT / "architecture-review.md",
    ARCHITECTURE_METHOD_ROOT / "verification-and-validation.md",
    ARCHITECTURE_METHOD_ROOT / "change-tailoring.md",
    ARCHITECTURE_METHOD_ROOT / "design-guidance.md",
    ARCHITECTURE_METHOD_ROOT / "key-designs.md",
    ARCHITECTURE_METHOD_ROOT / "domain-data-modeling.md",
    ARCHITECTURE_METHOD_ROOT / "deployment-views.md",
    ARCHITECTURE_METHOD_ROOT / "component-design.md",
    ARCHITECTURE_METHOD_ROOT / "component-identification.md",
    ARCHITECTURE_METHOD_ROOT / "history/loushang-documentation-model-v1.md",
    ARCHITECTURE_ROOT / "README.md",
    ARCHITECTURE_ROOT / "architecture-overview.md",
    ARCHITECTURE_ROOT / "governance-profile.md",
    ARCHITECTURE_ROOT / "decisions/README.md",
    ARCHITECTURE_ROOT / "loushang-architecture-principles.md",
    ARCHITECTURE_ROOT / "loushang-documentation-model.md",
    ARCHITECTURE_ROOT / "current-target-gap-ledger.md",
    ARCHITECTURE_ROOT / "subsystem.md",
    ARCHITECTURE_ROOT / "subsystem-diagram.md",
    ARCHITECTURE_ROOT / "generated/current-package-dependencies.md",
    ARCHITECTURE_ROOT / "coding/README.md",
    ARCHITECTURE_ROOT / "coding/loushang-coding-system-context.md",
    ARCHITECTURE_ROOT / "coding/lsp/README.md",
    ARCHITECTURE_ROOT / "coding/lsp/traceability.md",
    ARCHITECTURE_ROOT / "coding/arch/README.md",
    ARCHITECTURE_ROOT / "coding/arch/requirements.md",
    ARCHITECTURE_ROOT / "coding/arch/system-context.md",
    ARCHITECTURE_ROOT / "coding/arch/component-model.md",
    ARCHITECTURE_ROOT / "coding/arch/traceability.md",
    ARCHITECTURE_ROOT / "hosting/README.md",
    ARCHITECTURE_ROOT / "hosting/requirements.md",
    ARCHITECTURE_ROOT / "hosting/system-context.md",
    ARCHITECTURE_ROOT / "hosting/component-model.md",
    ARCHITECTURE_ROOT / "hosting/contract-model-h0.md",
    ARCHITECTURE_ROOT / "hosting/traceability.md",
    ARCHITECTURE_ROOT / "hosting/managed-launch-preparation-h6.md",
    ARCHITECTURE_ROOT
    / "hosting/validation/managed-launch-preparation-h6-feasibility.md",
    ARCHITECTURE_ROOT
    / "hosting/validation/managed-launch-preparation-h6-posix-native.md",
    ARCHITECTURE_ROOT
    / "hosting/validation/managed-launch-preparation-h6-windows-native.md",
    ARCHITECTURE_ROOT / "hosting/validation/hosted-product-runtime-v1-inventory.md",
    ARCHITECTURE_ROOT / "harness/plugin/plugin-lifecycle-plc9c5-c50-baseline.md",
    ARCHITECTURE_ROOT / "harness/plugin/plugin-lifecycle-plc9c5-c50-inventory.md",
    ARCHITECTURE_ROOT / "hosting/key-designs/hosted-application-support-boundary.md",
    ARCHITECTURE_ROOT / "apphost/README.md",
    ARCHITECTURE_ROOT / "apphost/contract-model-a0.md",
    ARCHITECTURE_ROOT / "apphost/product-worker-join-g8.md",
    ARCHITECTURE_ROOT / "apphost/hosted-product-v1-closure-g9.md",
    ARCHITECTURE_ROOT / "appserver/README.md",
    ARCHITECTURE_ROOT / "drafts/apphost-top-level-placement.md",
    ARCHITECTURE_ROOT / "drafts/apphost-component-discovery-a0.md",
    ARCHITECTURE_ROOT / "drafts/apphost-contract-baseline-a0.md",
    ARCHITECTURE_ROOT / "drafts/hosted-product-runtime-v1-plan.md",
    ARCHITECTURE_ROOT / "drafts/application-service-refactor.md",
    ARCHITECTURE_ROOT / "drafts/appservice-embedded-tui-hosted-boundary-plan.md",
    ARCHITECTURE_ROOT / "decisions/ARD-002-hosting-top-level-placement.md",
    ARCHITECTURE_ROOT / "hosting/validation/component-discovery.md",
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
STATUS_VALUES = {
    "Authority": ("normative", "descriptive", "generated", "historical"),
    "Design status": (
        "draft",
        "proposed",
        "accepted",
        "superseded",
        "rejected",
        "not-applicable",
    ),
    "Implementation status": (
        "not-started",
        "partial",
        "implemented",
        "deviated",
        "retired",
        "not-applicable",
    ),
}


def test_generated_current_package_dependencies_are_fresh() -> None:
    subprocess.run(
        [
            sys.executable,
            "scripts/architecture/render_current_package_dependencies.py",
            "--check",
        ],
        check=True,
        cwd=REPOSITORY_ROOT,
    )


def test_initial_governed_documents_declare_authority_and_status() -> None:
    missing: list[str] = []
    for path in INITIAL_GOVERNED_DOCUMENTS:
        text = path.read_text(encoding="utf-8")
        for field, values in STATUS_VALUES.items():
            allowed = "|".join(re.escape(value) for value in values)
            if not re.search(
                rf"^- {re.escape(field)}: ({allowed})(?:\s|$)", text, re.M
            ):
                missing.append(
                    f"{_display(path)}: {field} must start with one of {values}"
                )

    assert missing == []


def test_initial_governed_document_links_are_repository_relative_and_valid() -> None:
    errors: list[str] = []
    link_documents = (
        *INITIAL_GOVERNED_DOCUMENTS,
        *sorted((ARCHITECTURE_METHOD_ROOT / "templates").glob("*.md")),
    )
    for path in link_documents:
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            relative_target = target.split("#", maxsplit=1)[0]
            if Path(relative_target).is_absolute() or re.match(
                r"^[A-Za-z]:[\\/]", relative_target
            ):
                errors.append(
                    f"{_display(path)}: link must be repository-relative: {target}"
                )
                continue
            resolved = (path.parent / relative_target).resolve()
            if not resolved.is_relative_to(REPOSITORY_ROOT):
                errors.append(
                    f"{_display(path)}: link escapes repository root: {target}"
                )
                continue
            if not resolved.is_file():
                errors.append(f"{_display(path)}: missing link target {target}")

    assert errors == []


def test_current_architecture_entrypoints_do_not_restore_retired_mode_claims() -> None:
    current_documents = (
        ARCHITECTURE_ROOT / "architecture-overview.md",
        ARCHITECTURE_ROOT / "subsystem.md",
        ARCHITECTURE_ROOT / "subsystem-diagram.md",
        ARCHITECTURE_ROOT / "coding/README.md",
        ARCHITECTURE_ROOT / "coding/loushang-coding-system-context.md",
    )
    stale_positive_claims = (
        "`loushang.coding.mode.RpcMode` remains",
        "`loushang.coding.mode.RpcMode` 仍",
        "current RPC implementation remains the transitional",
        "loushang-channel (target, future package)",
    )

    offenders = [
        f"{_display(path)}: {claim}"
        for path in current_documents
        for claim in stale_positive_claims
        if claim in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_superseded_coding_mode_decisions_are_not_current_authority() -> None:
    rpc_ard = (
        ARCHITECTURE_ROOT
        / "coding/ARD-005-rpc-mode-transitional-channel-positioning.md"
    ).read_text(encoding="utf-8")
    rpc_surface = (
        ARCHITECTURE_ROOT / "coding/loushang-coding-rpc-mode-surface.md"
    ).read_text(encoding="utf-8")

    assert "## Status\n\nSuperseded." in rpc_ard
    assert "Authority: historical compatibility contract" in rpc_surface
    assert "Superseded by: `loushang.harness.host.rpc`" in rpc_surface


def test_target_deltas_have_explicit_acceptance_and_accepted_design_evidence() -> None:
    rows = _ledger_table("Accepted Target Deltas")
    for row in rows:
        assert row["Acceptance"] == "accepted", row["Area"]
        assert row["Classification"] in {"missing", "partial", "deviated"}, row
        assert row["Current"] and row["Accepted Target"], row["Area"]
        evidence_links = MARKDOWN_LINK.findall(row["Acceptance evidence / owner"])
        assert evidence_links, f"{row['Area']}: missing acceptance record"
        evidence_paths = tuple(
            (GAP_LEDGER.parent / target.split("#", maxsplit=1)[0]).resolve()
            for target in evidence_links
        )
        for path in evidence_paths:
            assert path.is_relative_to(ARCHITECTURE_ROOT.parent), path
            assert path.is_file(), path
        assert any(_is_accepted_design(path) for path in evidence_paths), (
            f"{row['Area']}: Target requires an accepted design record; "
            "a proposal, Current report or ledger cannot grant acceptance"
        )


def test_candidate_directions_have_no_implementation_gap_classification() -> None:
    rows = _ledger_table("Candidate Directions")
    for row in rows:
        assert row["Acceptance"] == "not-accepted", row["Area"]
        assert "Classification" not in row and "Accepted Target" not in row, row
        assert row["Current context"], row["Area"]
        assert row["Candidate direction / decision needed"], row["Area"]
        assert row["Context / decision owner"], row["Area"]


def _ledger_table(heading: str) -> list[dict[str, str]]:
    text = GAP_LEDGER.read_text(encoding="utf-8")
    marker = f"\n## {heading}\n"
    assert marker in text, f"missing ledger section: {heading}"
    section = text.split(marker, maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    assert len(lines) >= 3, f"missing ledger table or rows: {heading}"
    headers = tuple(cell.strip() for cell in lines[0].strip("|").split("|"))
    assert len(set(headers)) == len(headers), heading
    rows = []
    for line in lines[2:]:
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        assert len(cells) == len(headers), line
        rows.append(dict(zip(headers, cells, strict=True)))
    areas = [row["Area"] for row in rows]
    assert len(areas) == len(set(areas)), f"duplicate ledger areas: {heading}"
    return rows


def _is_accepted_design(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    status = re.search(r"^- Design status: ([a-z-]+)\b", text, re.M)
    if status is not None:
        return status.group(1) == "accepted" and bool(
            re.search(r"^- Authority: normative\b", text, re.M)
        )
    # Older accepted ARDs and scope documents predate the structured status block.
    return bool(re.search(r"^Status: (?:\*\*)?accepted\b", text, re.M | re.I))


def _display(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()
