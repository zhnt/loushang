from __future__ import annotations

from pathlib import Path

DESIGN = Path("docs/internals/architecture/appserver/hosted-application-g11.md")


def _read() -> str:
    return DESIGN.read_text(encoding="utf-8")


def test_g11_0_design_is_accepted_with_explicit_activation() -> None:
    design = _read()
    for field in (
        "- ID: `HOSTED-APPLICATION-G11-IN-PROCESS`",
        "- Authority: normative accepted design",
        "- Design status: accepted",
        "- Implementation status: not-started — G11.0 accepted design baseline",
        "- Activation status: explicit in-process Hosted Mux Profile only",
    ):
        assert field in design


def test_g11_design_freezes_requirements_evidence_and_non_goals() -> None:
    design = " ".join(_read().split())
    for index in range(1, 13):
        assert f"`G11-R{index}-" in design
    for evidence in (
        "G11-CONTRACT-STRICT",
        "G11-MUX-IDENTITY",
        "G11-ATTACH-BARRIER",
        "G11-MAILBOX-BOUND",
        "G11-AGGREGATE-CONCURRENCY",
        "G11-CLOSE-ORDER",
        "G11-PRODUCT-ADAPTER",
        "G11-SCOPE-COMPAT",
        "G11-HOSTED-PROFILE",
        "G11-EMBEDDED-OMISSION",
        "G11-INVENTORY-V4",
        "G11-DEPENDENCY-GRAPH",
    ):
        assert f"`{evidence}`" in design
    for non_goal in (
        "AppServer listeners",
        "local IPC",
        "daemon continuity",
        "Hosting service control",
        "default profile/owner changes",
        "Current deletion",
    ):
        assert non_goal in design


def test_g11_design_has_closed_ownership_and_three_view_review() -> None:
    design = " ".join(_read().split())
    for boundary in (
        "appserver.protocol -> Python standard library",
        "appservice -> appserver.protocol + appserver.ports",
        "appserver -/-> AppHost / Hosting / Product / Harness / Harnesstui / TUI",
        "appservice -/-> AppHost / Hosting / Product / Harness / Harnesstui / TUI",
        "Harness -/-> AppServer / AppService / AppHost / Harnesstui",
        "Hosting -/-> AppServer / AppService / AppHost / Product / Harnesstui",
        "Architecture and authority",
        "Lifecycle, concurrency, and safety",
        "Contract, presentation, and evidence",
        "No unresolved high or medium finding remains",
    ):
        assert boundary in design
    for slice_id in ("G11.0", "G11.1", "G11.2", "G11.3", "G11.4"):
        assert f"| {slice_id} |" in design
