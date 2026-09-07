from __future__ import annotations

from pathlib import Path

DESIGN = Path(
    "docs/internals/architecture/apphost/foreground-hosted-application-g12.md"
)


def _read() -> str:
    return DESIGN.read_text(encoding="utf-8")


def test_g12_design_and_implementation_are_complete() -> None:
    design = _read()
    for field in (
        "- ID: `FOREGROUND-HOSTED-APPLICATION-G12`",
        "- Authority: normative accepted design",
        "- Design status: accepted",
        "- Implementation status: implemented — G12.0--G12.4 complete",
        "- Activation status: explicit process-local library only",
    ):
        assert field in design


def test_g12_design_freezes_requirements_evidence_and_non_goals() -> None:
    design = " ".join(_read().split())
    for index in range(1, 13):
        assert f"`G12-R{index}-" in design
    for evidence in (
        "G12-OPTIONAL-EDGE",
        "G12-EXPLICIT-ACTIVATION",
        "G12-CANONICAL-ROUTING",
        "G12-GENERATION-PIN",
        "G12-FOREGROUND-PRODUCT",
        "G12-SCOPE-COMPAT",
        "G12-LEASE-CLOSE",
        "G12-APPLICATION-CLOSE",
        "G12-CANCELLATION",
        "G12-CLIENT-ONLY-TUI",
        "G12-VERTICAL-CANARY",
        "G12-INVENTORY-V5",
    ):
        assert f"`{evidence}`" in design
    for non_goal in (
        "AppServer listener",
        "local IPC",
        "authentication",
        "daemon continuity",
        "Hosting service control",
        "installed hosted route",
        "default profile/owner change",
        "Current deletion",
        "multi-client takeover",
        "AppHost crash recovery",
    ):
        assert non_goal in design


def test_g12_design_has_closed_ownership_and_reviewed_lifecycle() -> None:
    design = " ".join(_read().split())
    for boundary in (
        "apphost core -> Python standard library",
        "apphost.application -> apphost runtime/contracts + appservice + appserver.client",
        "apphost core -/-> AppService / AppServer protocol / Coding / Harness / Hosting / UI",
        "apphost.application -/-> Coding / Harness / Hosting / Harnesstui / TUI",
        "coding.hosted_application -/-> Hosting / Harnesstui / TUI / AppServer transport",
        "fence application admission",
        "AppService.close()",
        "AppHostRuntime.shutdown(budget)",
        "foreground Coding Product factory.close()",
        "optional requested continuity and discovery scope",
        "Router validates both before Product factory effect",
        "Architecture and authority",
        "Lifecycle, concurrency and safety",
        "Contract, compatibility and evidence",
        "No unresolved high or medium finding remains",
    ):
        assert boundary in design
    for slice_id in ("G12.0", "G12.1", "G12.2", "G12.3", "G12.4"):
        assert f"| {slice_id} |" in design
