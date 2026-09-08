from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path("docs/internals/architecture/appserver")


def test_G16_DESIGN_inventory_preserves_current_routes_and_platform_scope() -> None:
    inventory = json.loads(
        (ROOT / "detachable-local-workspace-g16-inventory.json").read_text()
    )
    assert inventory["inventoryVersion"] == 1
    assert inventory["profile"] == "local-detachable/v1"
    assert inventory["designStatus"] == "accepted"
    assert inventory["implementationStatus"] == "implemented"
    assert set(inventory["requiredPlatforms"]) == {"linux", "darwin", "win32"}
    entries = inventory["entries"]
    assert len({entry["id"] for entry in entries}) == len(entries)
    for entry in entries:
        assert entry["status"] in {
            "planned", "existing-extend", "existing-retain", "implemented-uncomposed",
            "implemented",
        }
        assert Path(entry["source"]).exists() == (entry["status"] != "planned")
    windows = next(entry for entry in entries if entry["id"] == "appserver.record-windows")
    assert windows["status"] == "implemented"  # Composition, not a native pass claim.
    record_source = Path("src/loushang/appserver/local_record.py").read_text()
    assert "from ._windows_local_record import _WindowsRecordFiles" in record_source
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]
    for name, target in inventory["unchangedScripts"].items():
        assert scripts[name] == target
    assert inventory["implementedScript"] == {
        "loushang-mux": "loushang.coding.cli.mux:main"
    }
    for name, target in inventory["implementedScript"].items():
        assert scripts[name] == target
    assert "retained Git workspaces" in Path(
        "src/loushang/coding/cli/workspace.py"
    ).read_text()


def test_G16_DESIGN_traces_detach_authority_and_real_evidence_requirements() -> None:
    inventory = json.loads(
        (ROOT / "detachable-local-workspace-g16-inventory.json").read_text()
    )
    design = (ROOT / "detachable-local-workspace-g16.md").read_text()
    for requirement in inventory["requirements"]:
        assert f"`{requirement}`" in design
    for boundary in (
        "AppServer -/-> AppService / AppHost / Hosting / Product / UI",
        "AppService -/-> transport / AppHost / Hosting / Product / UI",
        "Three-View Design Review",
        "stop_requested",
        "No required platform case may skip",
        "No encryption is claimed",
        "canonical Session history, not in-flight execution",
    ):
        assert boundary in design
    assert len({item["perspective"] for item in inventory["reviewFindings"]}) == 3
    for finding in inventory["reviewFindings"]:
        assert finding["status"] == "resolved"
        assert f"`{finding['id']}`" in design


def test_G17_BASELINE_indexes_link_delivery_without_activating_g15() -> None:
    design = (ROOT / "detachable-local-workspace-g16.md").read_text()
    assert "## Final Delivery Acceptance" in design
    delivery = design.split("## Final Delivery Acceptance", 1)[1].split("\n## ", 1)[0]
    for evidence in (
        "2455767a", "f05f8cc2", "/pull/567", "/pull/568",
        "34177069952", "G17.0", "G15", "design-only",
    ):
        assert evidence in delivery
    for scope in ("", "apphost", "appserver", "appservice", "harnesstui"):
        index = " ".join((ROOT.parent / scope / "README.md").read_text().split())
        assert "detachable-local-workspace-g16.md#final-delivery-acceptance" in index
        assert "G17.0" in index
        for obsolete in (
            "final platform acceptance pending", "full native platform proof remains pending",
            "isolated-wheel and final platform fault evidence remain pending",
            "final platform acceptance still required", "final cross-platform acceptance pending",
            "cross-platform acceptance is still pending",
            "design-only, not an implemented listener",
        ):
            assert obsolete not in index
    assert "A0.5 remains not-started" in (ROOT.parent / "apphost/README.md").read_text()
