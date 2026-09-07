from __future__ import annotations

from pathlib import Path

DESIGN = Path(
    "docs/internals/architecture/apphost/durable-hosted-application-continuity-g13.md"
)
APPHOST = Path("docs/internals/architecture/apphost/README.md")
APPSERVICE = Path("docs/internals/architecture/appservice/README.md")
AOD = Path("docs/internals/architecture/architecture-overview.md")
LEDGER = Path("docs/internals/architecture/current-target-gap-ledger.md")


def _read() -> str:
    return DESIGN.read_text(encoding="utf-8")


def test_g13_design_is_accepted_and_tracks_implementation() -> None:
    design = _read()
    for field in (
        "- ID: `DURABLE-HOSTED-APPLICATION-CONTINUITY-G13`",
        "- Authority: normative accepted design",
        "- Design status: accepted",
        "- Implementation status:",
        "- Activation status: explicit process-local recoverable library only",
    ):
        assert field in design


def test_g13_design_freezes_requirements_evidence_and_non_goals() -> None:
    design = " ".join(_read().split())
    for index in range(1, 13):
        assert f"`G13-R{index}-" in design
    for evidence in (
        "G13-EXPLICIT-CONTINUITY",
        "G13-LEASE-FENCE",
        "G13-STRICT-RECORD",
        "G13-ATOMIC-MUTATION",
        "G13-CANONICAL-RECOVERY",
        "G13-ALL-OR-NOTHING",
        "G13-FRESH-AUTHORITY",
        "G13-DETACH-RETENTION",
        "G13-MULTI-RECORD",
        "G13-SHUTDOWN-LEASE-ORDER",
        "G13-RESTART-CANARY",
        "G13-INVENTORY-V6",
    ):
        assert f"`{evidence}`" in design
    for non_goal in (
        "AppServer transport",
        "local listener",
        "Hosting service control",
        "OS-detached process",
        "installed daemon",
        "default-path migration",
        "active-execution crash continuation",
        "multi-client takeover",
        "Current deletion",
    ):
        assert non_goal in design


def test_g13_design_has_closed_ownership_and_recovery_order() -> None:
    design = " ".join(_read().split())
    for boundary in (
        "appservice.continuity -> appserver.protocol + standard library",
        "appservice.runtime -> appservice.continuity + appserver.protocol",
        "appservice.continuity -/-> AppHost / Hosting / Product / Harness / Harnesstui / TUI",
        "AppServer -/-> appservice.continuity / AppHost / Hosting / Product / UI",
        "lease.commit(expected_revision, next_record)",
        "publish live dictionaries/member order/revision",
        "Resume each member Session through the injected resolver",
        "AppService close (record retained)",
        "continuity lease close",
        "Architecture and authority",
        "Lifecycle, concurrency and safety",
        "Contract, compatibility and evidence",
        "No unresolved high or medium finding remains",
    ):
        assert boundary in design
    for slice_id in ("G13.0", "G13.1", "G13.2", "G13.3", "G13.4"):
        assert f"| {slice_id} |" in design
    assert "foundation JSON" not in design


def test_g13_accepted_target_is_adopted_with_current_scope() -> None:
    design_name = "durable-hosted-application-continuity-g13.md"
    assert design_name in _read_path(APPHOST)
    assert design_name in _read_path(APPSERVICE)
    assert "partially implemented G13" in _read_path(AOD)
    ledger = _read_path(LEDGER)
    assert "complete the accepted G13 outer continuity owner" in ledger
    assert "G13.1--G13.2" in ledger


def _read_path(path: Path) -> str:
    return path.read_text(encoding="utf-8")
