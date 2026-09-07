from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path("docs/internals/architecture/appserver")


def test_G14_DESIGN_inventory_separates_planned_edges_from_current_defaults() -> None:
    inventory = json.loads(
        (ROOT / "foreground-stdio-hosted-app-g14-inventory.json").read_text()
    )
    assert inventory["inventoryVersion"] == 7
    entries = inventory["entries"]
    assert len({row["id"] for row in entries}) == len(entries)
    for row in entries:
        assert row["status"] in {
            "planned",
            "implemented",
            "existing-extend",
            "existing-retain",
        }
        if row["status"] != "planned":
            assert Path(row["source"]).exists()
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]
    for name, target in inventory["unchangedDefaultScripts"].items():
        assert scripts[name] == target
    for name, target in inventory["explicitScript"].items():
        assert scripts[name] == target
    assert inventory["activation"] == "explicit-foreground-stdio-only"
    assert set(inventory["notGranted"]) == {
        "listener",
        "daemon",
        "reconnect",
        "active-turn-replay",
        "default-owner-change",
    }


def test_G14_DESIGN_keeps_separate_ownership_and_native_evidence_requirements() -> None:
    design = (ROOT / "foreground-stdio-hosted-app-g14.md").read_text()
    for requirement in (
        "G14-WIRE",
        "G14-CORRELATION",
        "G14-CONTROL",
        "G14-BACKPRESSURE",
        "G14-OWNERSHIP",
        "G14-PRODUCT",
        "G14-RECOVERY",
        "G14-PLATFORMS",
        "G14-BOUNDARIES",
    ):
        assert f"`{requirement}`" in design
    assert "Three-View Design Review" in design
    assert (
        "AppServer -/-> AppService / AppHost / Hosting / Harness / Coding / UI"
        in design
    )
    assert "No new top-level package" in design
