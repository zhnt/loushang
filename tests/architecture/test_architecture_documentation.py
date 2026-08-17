from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_ROOT = REPOSITORY_ROOT / "docs/internals/architecture"
ARCHITECTURE_METHOD_ROOT = REPOSITORY_ROOT / "docs/internals/architecture-method"
INITIAL_GOVERNED_DOCUMENTS = (
    ARCHITECTURE_METHOD_ROOT / "README.md",
    ARCHITECTURE_METHOD_ROOT / "artifact-model.md",
    ARCHITECTURE_METHOD_ROOT / "component-design.md",
    ARCHITECTURE_METHOD_ROOT / "component-identification.md",
    ARCHITECTURE_METHOD_ROOT / "history/loushang-documentation-model-v1.md",
    ARCHITECTURE_ROOT / "README.md",
    ARCHITECTURE_ROOT / "architecture-overview.md",
    ARCHITECTURE_ROOT / "governance-profile.md",
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
            if not re.search(rf"^- {re.escape(field)}: ({allowed})(?:\s|$)", text, re.M):
                missing.append(
                    f"{_display(path)}: {field} must start with one of {values}"
                )

    assert missing == []


def test_initial_governed_document_links_are_repository_relative_and_valid() -> (
    None
):
    errors: list[str] = []
    for path in INITIAL_GOVERNED_DOCUMENTS:
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


def _display(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()
