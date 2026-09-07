from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path("docs/internals/architecture/apphost")


def test_G15_DESIGN_inventory_records_design_not_runtime_activation() -> None:
    inventory = json.loads(
        (ROOT / "foreground-hosted-tui-g15-inventory.json").read_text()
    )
    assert inventory["inventoryVersion"] == 1
    assert inventory["delivery"] == "design-only"
    entries = inventory["entries"]
    assert len({entry["id"] for entry in entries}) == len(entries)
    assert {entry["status"] for entry in entries} == {"existing-retain", "planned"}
    for entry in entries:
        assert Path(entry["source"]).exists() == (
            entry["status"] == "existing-retain"
        ), "reconcile the inventory when a planned responsibility is implemented"
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]
    for name, target in inventory["unchangedScripts"].items():
        assert scripts[name] == target
    assert set(inventory["notGranted"]) == {
        "daemon",
        "listener",
        "reconnect",
        "active-turn-replay",
        "default-owner-change",
        "image-transfer",
    }


def test_G15_DESIGN_requirements_have_explicit_ownership_and_evidence_gaps() -> None:
    inventory = json.loads(
        (ROOT / "foreground-hosted-tui-g15-inventory.json").read_text()
    )
    design = (ROOT / "foreground-hosted-tui-g15.md").read_text()
    for requirement in inventory["requirements"]:
        assert f"`{requirement}`" in design
    for boundary in (
        "Design status: accepted",
        "Implementation status: not-started",
        "AppHost core -/-> optional launcher / Product / UI",
        "AppServer -/-> Hosting / AppService / AppHost / Product / UI",
        "Harnesstui -/-> Hosting / AppHost / Product / AppService",
        "Design Review And Acceptance Gate",
        "Handoff To G16",
        "It does not prove a",
    ):
        assert boundary in design
    findings = inventory["reviewFindings"]
    assert len({item["perspective"] for item in findings}) == 3
    for finding in findings:
        assert finding["status"] == "resolved"
        assert f"`{finding['id']}`" in design
        assert set(finding["requirements"]) <= set(inventory["requirements"])
