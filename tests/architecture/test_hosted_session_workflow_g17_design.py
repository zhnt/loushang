"""Design traceability only; these tests do not prove G17 runtime acceptance."""

from __future__ import annotations

import ast
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path("docs/internals/architecture/apphost")


def test_G17_DARWIN_native_entry_supplement_keeps_full_wheel_pending():
    from tests.coding import test_hosted_darwin_evidence as native

    name = "hosted-session-workflow-g17-darwin-native-manifest.json"
    row = json.loads((ROOT / name).read_text())["reports"]["G17-DARWIN-NATIVE"]
    test = native.test_G17_TERMINAL_DARWIN_modes_and_physical_exit
    marker = next(mark for mark in test.pytestmark if mark.name == "parametrize")
    assert row["requiredCaseIds"] == [parameter.id for parameter in marker.args[1]]
    assert row["minimumTests"] == 3
    assert row["requiredProperties"] == {"native_platform": "darwin", "terminal_backend": "posix-pty"}
    wheel = json.loads((ROOT / "hosted-session-workflow-g17-evidence-manifest.json").read_text())
    assert wheel["reports"]["G17-WHEEL-DARWIN"]["status"] == "planned"
    workflow = Path(".github/workflows/appservice-quality.yml").read_text()
    job = workflow.split("  g17-darwin-native:\n", 1)[1].split("\n  g17-darwin-primitives:", 1)[0]
    assert name in job and row["junitPath"] in job
    assert "runs-on: macos-15" in job and "--locked" in job
    assert "tests/coding/test_hosted_darwin_evidence.py" in job
    assert "if: always()" in job and "if-no-files-found: error" in job


def test_G17_DARWIN_primitives_do_not_claim_installed_or_terminal_acceptance():
    from tests.coding import test_hosted_darwin_primitives as native

    name = "hosted-session-workflow-g17-darwin-primitives-manifest.json"
    row = json.loads((ROOT / name).read_text())["reports"]["G17-DARWIN-PRIMITIVES"]
    test = native.test_G17_DARWIN_public_observation_primitives
    marker = next(mark for mark in test.pytestmark if mark.name == "parametrize")
    assert row["requiredCaseIds"] == marker.args[1]
    assert row["minimumTests"] == 5
    assert row["requiredProperties"] == {
        "native_platform": "darwin", "observation_backend": "waitid-kqueue",
    }
    wheel = json.loads((ROOT / "hosted-session-workflow-g17-evidence-manifest.json").read_text())
    assert wheel["reports"]["G17-WHEEL-DARWIN"]["status"] == "planned"
    workflow = Path(".github/workflows/appservice-quality.yml").read_text()
    job = workflow.split("  g17-darwin-primitives:\n", 1)[1].split("\n  g17-wheel-evidence:", 1)[0]
    assert name in job and row["junitPath"] in job
    assert "runs-on: macos-15" in job and "--locked" in job
    assert "tests/coding/test_hosted_darwin_primitives.py" in job
    assert "if: always()" in job and "if-no-files-found: error" in job


def test_G17_WINDOWS_native_supplement_is_not_full_wheel_acceptance() -> None:
    from tests.coding import test_hosted_windows_evidence as native

    name = "hosted-session-workflow-g17-windows-native-manifest.json"
    manifest = json.loads((ROOT / name).read_text())
    row = manifest["reports"]["G17-WINDOWS-NATIVE"]
    test = native.test_G17_TERMINAL_WINDOWS_console_modes_and_physical_exit
    marker = next(mark for mark in test.pytestmark if mark.name == "parametrize")
    assert row["requiredCaseIds"] == [parameter.id for parameter in marker.args[1]]
    assert row["minimumTests"] == 5
    assert row["requiredProperties"] == {
        "native_platform": "win32", "terminal_backend": "conpty",
    }
    wheel = json.loads((ROOT / "hosted-session-workflow-g17-evidence-manifest.json").read_text())
    assert wheel["reports"]["G17-WHEEL-WIN32"]["requiredProperties"]["installation"] == "wheel"
    assert len(wheel["reports"]["G17-WHEEL-WIN32"]["requiredCaseIds"]) == 8
    workflow = Path(".github/workflows/appservice-quality.yml").read_text()
    assert name in workflow and row["junitPath"] in workflow
    assert "tests/coding/test_hosted_windows_evidence.py" in workflow
    assert "architecture: x64" in workflow


def test_G17_WHEEL_ci_composes_full_linux_and_windows_without_smoke():
    workflow = Path(".github/workflows/appservice-quality.yml").read_text()
    job = workflow.split("  g17-wheel-evidence:\n", 1)[1].split("\n  g17-windows-native:", 1)[0]
    assert "- os: ubuntu-24.04\n            platform: linux" in job
    assert "- os: windows-latest\n            platform: win32" in job
    assert job.count("- os:") == 2
    assert "run_g17_installed_evidence.py" in job and "--smoke" not in job
    assert "--locked" in job and "build --wheel" in job
    assert "if: always()" in job and "if-no-files-found: error" in job
    assert "path: .artifacts/g17-wheel-${{ matrix.platform }}.xml" in job


def test_G17_COMMAND_is_one_optional_product_composition_with_fixed_dependencies() -> None:
    path = Path("src/loushang/coding/cli/hosted_client.py")
    source = path.read_text()
    tree = ast.parse(source)
    assert len(source.splitlines()) <= 450
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(item.name.split(".")[0] in sys.stdlib_module_names for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not node.level and node.module.split(".")[0] in sys.stdlib_module_names
    project_imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            project_imports.update(
                item.name for item in node.names
                if item.name.split(".")[0] not in sys.stdlib_module_names
            )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                assert node.level == 2 and node.module == "hosted_bootstrap"
                project_imports.add("loushang.coding.hosted_bootstrap")
            elif node.module.startswith("loushang."):
                project_imports.add(node.module)
    assert project_imports == {
        "loushang.apphost.launcher", "loushang.appserver.protocol",
        "loushang.appserver.protocol.connection_profile",
        "loushang.hosting.contracts", "loushang.hosting.runtime",
        "loushang.harnesstui.mux.shell", "loushang.harnesstui.mux.terminal",
        "loushang.coding.hosted_bootstrap",
    }
    for entry in (
        "src/loushang/coding/cli/__main__.py", "src/loushang/coding/ui/cli.py",
        "src/loushang/coding/__init__.py", "src/loushang/coding/cli/__init__.py",
        "src/loushang/apphost/__init__.py", "src/loushang/appservice/__init__.py",
        "src/loushang/coding/cli/mux.py", "src/loushang/coding/cli/hosted.py",
    ):
        assert "hosted_client" not in Path(entry).read_text()


def test_G17_LAUNCH_owner_has_exact_optional_imports_and_reviewability_budget() -> None:
    path = Path("src/loushang/apphost/launcher.py")
    source = path.read_text()
    assert len(source.splitlines()) <= 550
    allowed = {
        "loushang.hosting.contracts",
        "loushang.appserver.client",
        "loushang.appserver.framing",
        "loushang.appserver.remote_client",
        "loushang.appserver.protocol",
        "loushang.appserver.protocol.connection_profile",
    }
    imports: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    assert {name for name in imports if name.startswith("loushang.")} == allowed
    assert all(
        name in allowed or name.split(".")[0] in sys.stdlib_module_names
        for name in imports
    )
    assert not {name.split(".")[0] for name in imports}.intersection(
        {"os", "pathlib", "subprocess", "socket", "importlib", "shutil", "tempfile"}
    )
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "eval", "exec", "__import__"}
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "create_subprocess_exec", "create_subprocess_shell"
                }


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
        assert entry["status"] in {"existing-extend", "planned", "implemented-uncomposed", "partially-composed", "implemented"}
        assert Path(entry["source"]).exists() == (entry["status"] != "planned")
        assert set(entry["requirements"]) <= requirements
        covered.update(entry["requirements"])
    assert covered == requirements
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]
    for name, target in inventory["unchangedScripts"].items():
        assert scripts[name] == target
    for name, target in inventory["implementedScript"].items():
        assert scripts[name] == target


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
        assert report["status"] == ("planned" if platform == "darwin" else "implemented")
        assert report["requiredProperties"] == {
            "native_platform": platform,
            "installation": "wheel",
            "terminal_backend": "conpty" if platform == "win32" else "posix-pty",
        }
    for case_id in required:
        assert f"`{case_id}`" in design
