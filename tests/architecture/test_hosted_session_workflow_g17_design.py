"""Design traceability only; these tests do not prove G17 runtime acceptance."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path("docs/internals/architecture/apphost")


def test_G17_DISCOVERY_owner_has_an_independent_exact_reviewability_budget() -> None:
    root = Path("src/loushang/appservice")
    paths = [root / name for name in ("discovery_ports.py", "session_discovery.py")]
    assert sum(len(path.read_text().splitlines()) for path in paths) <= 500


def test_G17_DESIGN_inventory_separates_accepted_baseline_from_target() -> None:
    inventory = json.loads(
        (ROOT / "hosted-session-workflow-g17-inventory.json").read_text()
    )
    assert inventory["inventoryVersion"] == 1
    assert inventory["designId"] == "HOSTED-SESSION-WORKFLOW-G17"
    assert inventory["implementationStatus"] == "partial"
    assert inventory["trackingIssue"] == 572
    assert set(inventory["requiredPlatforms"]) == {"linux", "darwin", "win32"}
    entries = inventory["entries"]
    assert len({item["id"] for item in entries}) == len(entries)
    requirements = set(inventory["requirements"])
    covered: set[str] = set()
    for entry in entries:
        assert entry["status"] in {"existing-extend", "planned", "implemented-uncomposed"}
        assert Path(entry["source"]).exists() == (entry["status"] != "planned")
        assert set(entry["requirements"]) <= requirements
        covered.update(entry["requirements"])
    assert covered == requirements
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]
    for name, target in inventory["unchangedScripts"].items():
        assert scripts[name] == target
    assert not set(inventory["plannedScript"]).intersection(scripts)


def test_G17_DESIGN_traces_profiles_lifetimes_and_complete_delivery() -> None:
    inventory = json.loads(
        (ROOT / "hosted-session-workflow-g17-inventory.json").read_text()
    )
    design = (ROOT / "hosted-session-workflow-g17.md").read_text()
    for requirement in inventory["requirements"]:
        assert f"`{requirement}`" in design
    for profile in (*inventory["legacyProfiles"], *inventory["optionalProfiles"]):
        assert f"`{profile}`" in design or profile in design
    for boundary in (
        "AppServer -/-> Hosting / AppService / AppHost / Product / UI",
        "AppService -/-> transport / AppHost / Hosting / Product / UI",
        "AppHost core -/-> optional launcher / Product / UI",
        "listing does not grant resume",
        "complete=false",
        "snapshot_required",
        "No failed or lost open response is automatically resubmitted",
        "required cases\n   have zero skips",
        "not runtime acceptance",
    ):
        assert boundary in design
    reviews = inventory["reviews"]
    assert {review["perspective"] for review in reviews} == {
        "architecture-authority", "lifecycle-concurrency", "contract-user-evidence"
    }
    assert inventory["designStatus"] in {"pending-review", "accepted"}
    if inventory["designStatus"] == "accepted":
        assert all(review["status"] == "approved" for review in reviews)
        assert "Design status: accepted" in design
    else:
        assert "Design status: pending" in design


def test_G17_DESIGN_requires_own_installed_cases_on_each_native_platform() -> None:
    manifest = json.loads(
        (ROOT / "hosted-session-workflow-g17-evidence-manifest.json").read_text()
    )
    design = (ROOT / "hosted-session-workflow-g17.md").read_text()
    assert manifest["manifestVersion"] == 1
    assert set(manifest["reports"]) == {
        "G17-WHEEL-LINUX", "G17-WHEEL-DARWIN", "G17-WHEEL-WIN32"
    }
    required = {
        "G17-INSTALLED-ENTRY", "G17-INSTALLED-CWD", "G17-INSTALLED-HOME",
        "G17-INSTALLED-LOCAL", "G17-INSTALLED-LEGACY", "G17-PRODUCT-INTERACTION",
        "G17-NATIVE-START-CANCEL", "G17-NATIVE-FORCED-EXIT",
    }
    for name, report in manifest["reports"].items():
        platform = name.removeprefix("G17-WHEEL-").lower()
        assert set(report["requiredCaseIds"]) == required
        assert len(report["requiredCaseIds"]) == len(required)
        assert report["minimumTests"] >= len(required)
        assert report["status"] == "planned"
        assert report["requiredProperties"] == {
            "native_platform": platform,
            "installation": "wheel",
            "terminal_backend": "conpty" if platform == "win32" else "posix-pty",
        }
    for case_id in required:
        assert f"`{case_id}`" in design
