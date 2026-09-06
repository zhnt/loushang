from pathlib import Path

DESIGN = Path(
    "docs/internals/architecture/apphost/installed-explicit-canary-g10.md"
)
APPHOST_SCOPE = Path("docs/internals/architecture/apphost/README.md")
ARCHITECTURE = Path("docs/internals/architecture/README.md")
AOD = Path("docs/internals/architecture/architecture-overview.md")
SUBSYSTEM = Path("docs/internals/architecture/subsystem.md")
GAP_LEDGER = Path("docs/internals/architecture/current-target-gap-ledger.md")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    return " ".join(_read(path).split())


def test_g10_0_design_is_accepted_and_adopted_by_common_parent() -> None:
    design = _read(DESIGN)
    for field in (
        "- ID: `HOSTED-PRODUCT-G10-EXPLICIT-CANARY`",
        "- Authority: normative accepted design",
        "- Design status: accepted",
        "- Implementation status: not-started — G10.0 design baseline only",
        "- Activation status: default-dark; no installed entrypoint selects Hosting yet",
    ):
        assert field in design
    for path in (APPHOST_SCOPE, ARCHITECTURE, AOD, SUBSYSTEM, GAP_LEDGER):
        assert "G10" in _read(path), path
    assert "[G10 Installed Explicit Canary](installed-explicit-canary-g10.md)" in _read(
        APPHOST_SCOPE
    )


def test_g10_freezes_requirements_and_non_goals() -> None:
    normalized = _normalized(DESIGN)
    for requirement in (
        "G10-R1-EXACT-OPT-IN",
        "G10-R2-REAL-OWNERSHIP-CHAIN",
        "G10-R3-EPHEMERAL-IDENTITY",
        "G10-R4-DURABLE-SELECTION-CONTROL",
        "G10-R5-NO-FALLBACK",
        "G10-R6-BOUNDED-OBSERVABILITY",
        "G10-R7-SETTLED-LIFECYCLE",
        "G10-R8-CROSS-PLATFORM-EVIDENCE",
        "G10-R9-INDEPENDENT-ROLLBACK",
        "G10-R10-NO-AUTHORITY-EXPANSION",
    ):
        assert f"`{requirement}`" in normalized
    for non_goal in (
        "normal Coding turn runs in a Worker",
        "default owner change",
        "Current deletion",
        "AppServer/AppService runtime",
        "A0.5 launcher",
        "named-mux activation",
    ):
        assert non_goal in normalized


def test_g10_has_explicit_command_control_and_dependency_boundaries() -> None:
    normalized = _normalized(DESIGN)
    for command in (
        "loushang apphost canary status",
        "loushang apphost canary run",
        "loushang apphost canary rollback",
        "loushang apphost canary enable",
    ):
        assert command in normalized
    for boundary in (
        "loushang.coding.cli.apphost",
        "loushang.coding.apphost_canary",
        "loushang.coding._apphost_canary_control",
        "loushang.coding._apphost_canary_child",
        "AppHost core -/-> Coding / Harness / Hosting / AppServer / AppService",
        "Hosting -/-> Coding / AppHost / Harness / AppServer / AppService",
        "Harness journal -/-> Coding / AppHost / Hosting",
    ):
        assert boundary in normalized
    assert "`run` holds the lock from its final enabled-state read" in normalized
    assert "No rollback can race between final selection and spawn" in normalized
    assert "Absence means `unconfigured` at virtual generation zero" in normalized
    assert "Deleting a disabled journal therefore cannot re-enable" in normalized


def test_g10_has_complete_delivery_evidence_and_three_view_review_contract() -> None:
    design = _read(DESIGN)
    for slice_id in ("G10.0", "G10.1", "G10.2", "G10.3", "G10.4"):
        assert f"| {slice_id} |" in design
    evidence = design.split("## Evidence Contract", maxsplit=1)[1].split(
        "## Delivery Slices", maxsplit=1
    )[0]
    observed = {
        line.split("`")[1]
        for line in evidence.splitlines()
        if line.startswith("| `G10-")
    }
    assert observed == {
        "G10-OMISSION-CURRENT",
        "G10-EXACT-COMMAND",
        "G10-STATUS-NO-EFFECT",
        "G10-REAL-NATIVE-RUN",
        "G10-EPHEMERAL-NO-SESSION-IO",
        "G10-ROLLBACK-BEFORE-RUN",
        "G10-RUN-ROLLBACK-LINEARIZATION",
        "G10-ENABLE-NEW-GENERATION",
        "G10-NO-FALLBACK",
        "G10-CANCEL-CLEANUP",
        "G10-REPORT-REDACTION",
        "G10-INVENTORY-V3",
        "G10-DEPENDENCY-GRAPH",
    }
    review = design.split("## Three-View Review Contract", maxsplit=1)[1].split(
        "## Exit Gate", maxsplit=1
    )[0]
    for view in (
        "Architecture and authority",
        "Lifecycle and safety",
        "Entrypoint and evidence",
        "High or medium findings block the next phase",
    ):
        assert view in review


def test_g10_threat_model_covers_activation_race_cleanup_and_claim_control() -> None:
    threat_model = _read(DESIGN).split("## Threat Model", maxsplit=1)[1].split(
        "## Three-View Review Contract", maxsplit=1
    )[0]
    for control in (
        "lazy exact-action dispatch",
        "one exclusive control lock spans final read through complete owner settlement",
        "no Current port exists in the canary composition",
        "unpredictable per-attempt nonce",
        "finite total budget",
        "closed report schema",
        "private regular-file/owner/link checks",
        "fixed minimum OS-bootstrap allowlist",
        "cancellation-shielded, dependency-ordered settlement",
        "unchanged G9.3 `RETAIN`",
    ):
        assert control in threat_model
