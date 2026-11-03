"""Local and CI commands for the inexpensive, independently selectable scopes."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from select_checks import ROOT, make_paths
from test_catalog import (
    MODULE_EXTRA_TESTS,
    module_is_fully_classified,
    module_targeted_nodeids,
    module_unit_paths,
)

OFFLINE_MARKERS = (
    "not live and not requires_host_runtime and not tui_render_contract "
    "and not tui_terminal_backend and not tui_terminal_contract and not tui_tmux_integration"
)
HOST_RUNTIME_PR_CASES = {
    "coding": (
        "tests/coding/test_plugin_author_smoke.py::"
        "test_author_worker_smoke_proves_admission_and_selection_without_use"
    ),
    "hosting": (
        "tests/hosting/test_posix_release_launcher.py::"
        "test_checked_in_launcher_build_and_native_containment"
    ),
    "harness": (
        "tests/harness/transcript/test_file_store_process_exit.py::"
        "test_file_store_async_create_allows_python_process_to_exit"
    ),
}


def commands(
    scope: str, *, root: Path = ROOT, plan: dict | None = None,
    shard: int = 0, shards: int = 1,
) -> list[list[str]]:
    if shards < 1 or not 0 <= shard < shards:
        raise ValueError(f"invalid regression shard {shard}/{shards}")
    if scope != "coding" and not scope.startswith("unit_") and (shard != 0 or shards != 1):
        raise ValueError("shards are only supported for module regression")
    python = sys.executable
    if scope == "gui":
        return [[shutil.which("pnpm") or "pnpm", "--dir", "gui", "run", "check"]]
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
    if scope.startswith("unit_") or scope == "coding":
        package = scope.removeprefix("unit_")
        unit_paths = json.loads((root / "scripts/ci/unit-tests.json").read_text())
        if package not in unit_paths:
            raise ValueError(f"unknown unit package {package!r}")
        package_dir = root / "tests" / package
        paths = [f"tests/{package}"] if package_dir.is_dir() else unit_paths[package]
        classified = module_unit_paths(package, root=root)
        if classified is not None:
            paths = classified
            if package == "coding":
                # Partial Coding classification expands the directory into
                # explicit files. Pytest's --ignore does not suppress a path
                # that is also passed explicitly, so remove the separately
                # owned TUI inventory before constructing the command.
                paths = [path for path in paths if path not in coding_ui_paths]
        # A complete catalog already expands every extra directory into files.
        # Appending the directory would collect those cases a second time.
        extras = [] if classified is not None else MODULE_EXTRA_TESTS.get(package, [])
        for path in extras:
            if not (root / path).exists():
                raise ValueError(f"missing module regression path {path!r}")
        shard_args = (
            ["-p", "pytest_shard", "--ci-shard-index", str(shard),
             "--ci-shard-count", str(shards)]
            if shards > 1 else []
        )
        deselect_args = [
            f"--deselect={nodeid}"
            for nodeid in module_targeted_nodeids(package, root=root)
        ]
        # Ordinary and risk routes share the complete offline inventory. When
        # the plan schedules a separate E2E job, that job owns the canary.
        markers = OFFLINE_MARKERS
        if scope.startswith("unit_") or (plan is not None and plan.get("e2e")):
            markers += " and not e2e_smoke"
        result = [
            pytest
            + (coding_ignores if package == "coding" else [])
            + paths + extras
            + deselect_args
            + ["-m", markers,
               "--skip-host-runtime", "--strict-markers", "-q", *shard_args]
        ]
        if classified is not None and module_is_fully_classified(package, root=root):
            result.insert(0, [python, "-m", "ruff", "check", f"src/loushang/{package}", *paths])
        return result
    if scope == "e2e_smoke":
        cases = [
            "tests/coding/test_pr_smoke.py::test_real_session_tool_persistence_resume_and_close"
        ]
        if plan is None or plan.get("e2e_interaction"):
            cases.append(
                "tests/coding/test_pr_smoke.py::test_terminal_cancel_tool_then_message_and_exit"
            )
        return [
            pytest
            + cases + [
                "-m", "e2e_smoke and not live", "--strict-markers", "-q",
            ]
        ]
    if scope == "host_runtime" and plan is not None:
        if plan.get("host_runtime_smoke"):
            cases = [
                HOST_RUNTIME_PR_CASES[package]
                for package in ("coding", "hosting", "harness")
                if plan["checks"][package]
            ][:2]
            if not cases:
                cases = [HOST_RUNTIME_PR_CASES["harness"]]
            return [pytest + cases + [
                "-m", "requires_host_runtime and not live", "--strict-markers",
                "--junitxml=.artifacts/host-runtime-pr-smoke.xml", "-q",
            ]]
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
    if scope in {"agent", "foundation"}:
        # Existing packages do not all have established package-wide mypy/lint
        # baselines. Start with their offline regression suites, without inventing
        # new lint thresholds as part of CI routing.
        shard_args = (
            ["-p", "pytest_shard", "--ci-shard-index", str(shard),
             "--ci-shard-count", str(shards)]
            if shards > 1 else []
        )
        return [pytest + (coding_ignores if scope == "coding" else [])
                + [f"tests/{scope}", "-m", OFFLINE_MARKERS,
                   "--skip-host-runtime", "-q", *shard_args]]
    if scope == "tui_unit":
        return [
            pytest + ["tests/tui", "-m", OFFLINE_MARKERS, "--skip-host-runtime", "-q"]
        ]
    if scope in {"harnesstui", "coding_ui", "harnesstui_all"}:
        all_tests = (
            inventories["HARNESSTUI_TEST_PATHS"]
            + inventories["CODING_TUI_PRODUCT_TEST_PATHS"]
        )
        coding = scope == "coding_ui"
        combined = scope == "harnesstui_all"
        tests = all_tests if combined else [
            path for path in all_tests if path.startswith("tests/coding/") == coding
        ]
        if not coding and plan is not None:
            # Shared consumer contracts stay in the Harnesstui-only route.  If
            # their canonical package owner is already selected for this same
            # candidate, execute the identical file there only once.
            if plan["checks"]["tui_unit"]:
                tests = [path for path in tests if not path.startswith("tests/tui/")]
            if "harness" in plan["unit_packages"]:
                tests = [
                    path for path in tests if not path.startswith("tests/harness/")
                ]
        source_vars = (
            [
                "HARNESSTUI_SHARED_SOURCES",
                "HARNESSTUI_CODING_ADAPTERS",
                "CODING_TUI_PRODUCT_SOURCES",
                "HARNESSTUI_TEST_SUPPORT",
            ]
            if combined
            else
            [
                "HARNESSTUI_CODING_ADAPTERS",
                "CODING_TUI_PRODUCT_SOURCES",
                "HARNESSTUI_TEST_SUPPORT",
            ]
            if coding
            else ["HARNESSTUI_SHARED_SOURCES"]
        )
        sources = list(dict.fromkeys(
            path for name in source_vars for path in inventories[name]
        ))
        tests = list(dict.fromkeys(tests))
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


def run(scope: str, *, plan: dict | None = None, shard: int = 0, shards: int = 1) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT / "src"), str(ROOT / "scripts" / "ci"),
                          env.get("PYTHONPATH")) if part
    )
    for command in commands(scope, plan=plan, shard=shard, shards=shards):
        print("Running:", " ".join(command), flush=True)
        completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
        if (
            scope == "host_runtime"
            and plan is not None
            and not all(plan["checks"].values())
            and completed.returncode == 5
        ):
            # A scoped package may have no tests with this opt-in marker.
            print("No host-runtime cases selected in the scoped packages.", flush=True)
            continue
        completed.check_returncode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope")
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    # Unit/package jobs must not accidentally activate opt-in provider tests.
    os.environ.pop("LOUSHANG_AI_LIVE", None)
    plan = json.loads(os.environ["CI_PLAN"]) if "CI_PLAN" in os.environ else None
    run(args.scope, plan=plan, shard=args.shard, shards=args.shards)


if __name__ == "__main__":
    main()
