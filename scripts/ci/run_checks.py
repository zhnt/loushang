"""Local and CI commands for the inexpensive, independently selectable scopes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from select_checks import ROOT, make_paths

OFFLINE_MARKERS = (
    "not live and not requires_host_runtime and not tui_render_contract "
    "and not tui_terminal_backend and not tui_terminal_contract and not tui_tmux_integration"
)


def commands(
    scope: str, *, root: Path = ROOT, plan: dict | None = None
) -> list[list[str]]:
    python = sys.executable
    pytest = [python, "scripts/dev/run_pytest.py"]
    inventories = make_paths(root)
    coding_ui_paths = sorted(
        {
            path
            for name in ("HARNESSTUI_TEST_PATHS", "CODING_TUI_PRODUCT_TEST_PATHS")
            for path in inventories[name]
            if path.startswith("tests/coding/")
        }
    )
    coding_ignores = [f"--ignore={path}" for path in coding_ui_paths]
    if scope == "host_runtime" and plan is not None:
        packages = (
            "coding",
            "harness",
            "hosting",
            "apphost",
            "appservice",
            "agent",
            "foundation",
        )
        paths = [f"tests/{package}" for package in packages if plan["checks"][package]]
        if plan["checks"]["appservice"]:
            paths.append("tests/appserver")
        if not paths:
            raise ValueError("host-runtime selection has no owning package")
        if all(plan["checks"].values()):
            paths = ["tests"]
        elif plan["checks"]["coding"]:
            paths += coding_ignores
        return [pytest + paths + ["-m", "requires_host_runtime and not live", "-q"]]
    if scope in {"agent", "coding", "foundation"}:
        # Existing packages do not all have established package-wide mypy/lint
        # baselines. Start with their offline regression suites, without inventing
        # new lint thresholds as part of CI routing.
        return [
            pytest
            + (coding_ignores if scope == "coding" else [])
            + [f"tests/{scope}", "-m", OFFLINE_MARKERS, "--skip-host-runtime", "-q"]
        ]
    if scope == "tui_unit":
        return [
            pytest + ["tests/tui", "-m", OFFLINE_MARKERS, "--skip-host-runtime", "-q"]
        ]
    if scope in {"harnesstui", "coding_ui"}:
        all_tests = (
            inventories["HARNESSTUI_TEST_PATHS"]
            + inventories["CODING_TUI_PRODUCT_TEST_PATHS"]
        )
        coding = scope == "coding_ui"
        tests = [
            path for path in all_tests if path.startswith("tests/coding/") == coding
        ]
        source_vars = (
            [
                "HARNESSTUI_CODING_ADAPTERS",
                "CODING_TUI_PRODUCT_SOURCES",
                "HARNESSTUI_TEST_SUPPORT",
            ]
            if coding
            else ["HARNESSTUI_SHARED_SOURCES"]
        )
        sources = [path for name in source_vars for path in inventories[name]]
        typed = [path for path in sources if not path.startswith("tests/")]
        return [
            [python, "-m", "ruff", "check", *sources, *tests],
            [python, "-m", "mypy", "--follow-imports=silent", *typed],
            pytest + tests + ["-m", "not tui_render_contract", "-q"],
        ]
    if scope == "docs":
        return [
            [python, "scripts/ci/check_docs.py", "--plan", ".artifacts/check-plan.json"]
        ]
    if scope == "architecture":
        return [
            [
                python,
                "scripts/architecture/render_current_package_dependencies.py",
                "--check",
            ]
        ]
    if scope == "ci":
        return [[python, "-m", "unittest", "discover", "-s", "tests/ci", "-v"]]
    targets = {
        "ai": "check-ai",
        "harness": "check-harness",
        "hosting": "check-hosting",
        "apphost": "check-apphost",
        "appservice": "check-appservice",
        "tui_playback": "test-tui-render-contract",
    }
    if scope in targets:
        return [["make", targets[scope]]]
    raise ValueError(f"scope {scope!r} requires its platform-specific workflow")


def run(scope: str, *, plan: dict | None = None) -> None:
    for command in commands(scope, plan=plan):
        print("Running:", " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope")
    args = parser.parse_args()
    # Unit/package jobs must not accidentally activate opt-in provider tests.
    os.environ.pop("LOUSHANG_AI_LIVE", None)
    plan = json.loads(os.environ["CI_PLAN"]) if "CI_PLAN" in os.environ else None
    run(args.scope, plan=plan)


if __name__ == "__main__":
    main()
