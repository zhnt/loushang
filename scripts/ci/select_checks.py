"""Select checks from Git changes without importing or installing the product.

The plan is shared by local development and GitHub Actions. Rules are additive;
unknown non-document paths deliberately select the full suite.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from test_catalog import (
    MODULE_EXTRA_TESTS,
    all_targeted_test_cases,
    load_catalog,
    reviewed_unit_owner,
    targeted_node_owner,
    targeted_test_cases,
)

ROOT = Path(__file__).resolve().parents[2]
PR_ROUTING_FILES = {
    ".github/workflows/apphost-quality.yml",
    ".github/workflows/hosting-quality.yml",
    ".github/workflows/quality.yml",
    "scripts/ci/check-scopes.json",
    "scripts/ci/select_checks.py",
    "scripts/ci/unit-tests.json",
    "scripts/ci/test-classification.json",
    "scripts/ci/test_catalog.py",
    "scripts/ci/run_targeted_tests.py",
    "tests/ci/test_test_catalog.py",
    "scripts/ci/derive_junit.py",
    "tests/ci/test_derive_junit.py",
    "tests/ci/test_source_imports.py",
    "scripts/ci/verify_module_report.py",
    "tests/ci/test_module_report.py",
    "scripts/dev/verify_pytest_xml.py",
    "tests/dev/test_verify_pytest_xml.py",
    "scripts/ci/verify_gate.py",
    "tests/ci/test_change_gates.py",
    "scripts/ci/reuse_pr_gate.py",
    "tests/ci/test_reuse_pr_gate.py",
}
# Temporarily paused by user request while native Worker execution is optimized.
# Remove this entry to restore the original routing and complete case inventory.
PAUSED_WORKFLOWS = {
    "windows-shell", "hosting", "appservice", "host-runtime", "worker-reboot", "harness",
}
PAUSED_MODULES = {
    "harness": ("harness",), "hosting": ("hosting",),
    "appservice": ("appservice", "appserver"),
}
MODULE_REGRESSION_WORKFLOW = ".github/workflows/package-unit-quality.yml"
SCOPED_WORKFLOWS = {
    ".github/workflows/e2e-smoke-quality.yml": (),
    **{
        f".github/workflows/{filename}.yml": (scope,)
        for filename, scope in (
            ("architecture-quality", "architecture"), ("gui-quality", "gui"),
            ("ai-quality", "ai"),
            ("harness-quality", "harness"),
            ("harnesstui-quality", "harnesstui"), ("tui-render-contract", "tui"),
            ("hosting-quality", "hosting"), ("apphost-quality", "apphost"),
            ("appservice-quality", "appservice"),
            ("host-runtime-quality", "host-runtime"),
            ("windows-shell-compatibility", "windows-shell"),
            ("worker-registered-reboot-drill", "worker-reboot"),
            ("coding-lsp-compatibility", "lsp"),
        )
    },
}
SMOKE_TEST = "tests/coding/test_pr_smoke.py"
FAST_EXCLUDED_PACKAGES = {
    "plugin", "hosting", "apphost", "appservice", "appserver", "foundation",
}
FAST_RISK_CHECKS = {
    "registered_reboot", "windows_shell", "tui_native", "harness_native",
    "lsp", "install", "hosting", "apphost", "appservice",
}
E2E_PATH_PARTS = ("/session/", "/conversation/", "/transcript/")
FAST_RISK_RULE_REASONS = {"AI consumer contracts"}
# Counts are based on observed report durations, not historical gate names.  The
# Coding value uses PR #779's 3,771-case report after owner classification and
# deduplication: four hash shards have a 198.444 s slowest measured case sum,
# leaving setup margin inside the ten-minute PR target while halving runners.
MODULE_SHARD_COUNTS = {"coding": 4, "harness": 4, "harnesstui": 2, "tui": 2}
FULL_TARGETED_SHARDS = {
    "ubuntu-24.04": 8,
    "windows-2022": 2,
    "macos-15": 1,
}
# Full validation keeps these measured heavyweight files alone in three of the
# existing Ubuntu integration buckets. Ordinary PR batches containing them
# need the same runtime allowance when several files share one bucket.
FULL_TARGETED_EXCLUSIVE_PATHS = {
    ("ubuntu-24.04", "integration"): {
        "tests/coding/test_package_cutover_cli.py",
        "tests/coding/test_package_external_data_wheel.py",
        "tests/coding/test_package_worker_candidate_wheel.py",
    },
}
CHECK_MODULE_REGRESSIONS = {
    "agent": "agent",
    "coding": "coding",
    "foundation": "foundation",
}
WINDOWS_GATE_INFRA = (
    ".github/", "scripts/ci/", "tests/ci/", "Makefile", "pyproject.toml",
    "uv.lock", "tests/conftest.py", "scripts/dev/run_pytest.py",
    "scripts/dev/verify_pytest_xml.py",
)
WINDOWS_WORKER_NATIVE_PARTS = (
    "recovery", "crash", "gc", "cleanup", "retire", "lease", "settlement",
    "activation_state",
)
WINDOWS_WORKER_NATIVE_PREFIXES = (
    "src/loushang/coding/package_product_worker_",
    "tests/coding/test_package_product_worker_",
    "src/loushang/coding/package_external_worker_wheel.py",
    "src/loushang/coding/package_product_runtime.py",
    "src/loushang/coding/cli/package_worker_native.py",
    "src/loushang/plugin/_coding_local_worker_wheel.py",
    "src/loushang/harness/worker/", "tests/harness/worker/",
    "src/loushang/hosting/", "tests/hosting/",
    "tests/coding/test_package_worker_candidate_wheel.py",
    "tests/coding/test_package_worker_native_cli.py",
    "tests/coding/test_package_windows_pre_b_snapshot.py",
)
WINDOWS_WORKER_FULL_BOUNDARIES = {
    "src/loushang/hosting/_win32_process.py",
    "src/loushang/hosting/_windows_process.py",
    "tests/hosting/test_win32_process.py",
    "tests/hosting/test_windows_process.py",
    "tests/coding/test_package_windows_pre_b_snapshot.py",
    "tests/coding/test_package_worker_candidate_wheel.py",
    "tests/coding/test_package_worker_native_cli.py",
    "tests/coding/test_plugin_author_smoke.py",
}
WINDOWS_WORKER_FULL_TEST_PREFIXES = (
    "tests/coding/test_package_product_worker_windows_",
    "tests/coding/test_package_worker_windows_",
)
WINDOWS_SHELL_FULL_PARTS = (
    "private_data", "windows_private_acl", "package_pre_b_snapshot",
    "package_epoch_", "package_installation_private_data",
    "package_legacy_", "package_cutover", "package_gc",
    "product_local_wheel_runtime", "plc9b_windows",
)
WINDOWS_SHELL_FULL_PREFIXES = (
    "src/loushang/harness/workspace/", "tests/harness/workspace/",
    "src/loushang/harness/resources/packages/",
    "tests/harness/resources/packages/",
    "src/loushang/harness/sandbox/", "tests/harness/sandbox/",
    "src/loushang/harness/machine_resources/",
    "tests/harness/machine_resources/",
    "src/loushang/hosting/", "tests/hosting/",
    "tests/coding/test_package_windows_",
)
WINDOWS_APPSERVICE_FULL_PARTS = (
    "record", "security", "auth", "recovery", "native", "installed",
)
WINDOWS_APPSERVICE_FULL_PREFIXES = (
    "src/loushang/appserver/", "tests/appserver/",
    "src/loushang/hosting/", "tests/hosting/",
    "tests/coding/_hosted_", "tests/coding/test_mux_",
)
WINDOWS_TUI_FULL_PARTS = (
    "terminal_backends/", "windows_conpty", "terminal_process_support/",
)


def git(*args: str, root: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def changed_paths(base: str, head: str, *, root: Path = ROOT) -> list[str]:
    # Treat renames as delete + add, so both the old and new owners are checked.
    data = git("diff", "--name-only", "--no-renames", "-z", base, head, "--", root=root)
    return sorted({os.fsdecode(path) for path in data.split(b"\0") if path})


def local_paths(base: str, *, root: Path = ROOT) -> list[str]:
    ancestor = git("merge-base", base, "HEAD", root=root).decode().strip()
    paths = changed_paths(ancestor, "HEAD", root=root)
    for args in (
        ("diff", "--name-only", "--no-renames", "-z", "HEAD", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        paths.extend(os.fsdecode(p) for p in git(*args, root=root).split(b"\0") if p)
    return sorted(set(paths))


def make_paths(root: Path = ROOT) -> dict[str, list[str]]:
    text = (root / "Makefile").read_text().replace("\\\n", " ")
    return {
        match[1]: match[2].split()
        for match in re.finditer(r"^(\w+)\s*:=\s*(.*)$", text, re.M)
    }


def make_targeted_jobs(
    cases: set[tuple[str, str, str]], *, full: bool
) -> list[dict]:
    def stable_shard(path: str, count: int, *, salt: str = "") -> int:
        digest = hashlib.sha256(f"{salt}{path}".encode()).digest()
        return int.from_bytes(digest[:8], "big") % count

    reserved: dict[tuple[str, str], set[int]] = {}
    if full:
        available = {(platform, category, path) for path, platform, category in cases}
        for key, paths in FULL_TARGETED_EXCLUSIVE_PATHS.items():
            platform, category = key
            shard_count = FULL_TARGETED_SHARDS[platform]
            selected = sorted(
                path for path in paths if (platform, category, path) in available
            )
            selected_shards = {stable_shard(path, shard_count) for path in selected}
            if len(selected_shards) != len(selected):
                raise ValueError(f"exclusive targeted shard collision: {key}")
            reserved[key] = selected_shards

    buckets: dict[tuple[str, str, int], list[str]] = {}
    for path, platform, category in sorted(cases):
        shard_count = FULL_TARGETED_SHARDS[platform] if full else 1
        shard = stable_shard(path, shard_count)
        key = (platform, category)
        exclusive_paths = FULL_TARGETED_EXCLUSIVE_PATHS.get(key, set())
        reserved_shards = reserved.get(key, set())
        if full and path not in exclusive_paths and shard in reserved_shards:
            alternatives = [
                candidate for candidate in range(shard_count)
                if candidate not in reserved_shards
            ]
            if not alternatives:
                raise ValueError(f"no targeted shard remains beside exclusive paths: {key}")
            shard = alternatives[stable_shard(path, len(alternatives), salt="overflow:")]
        buckets.setdefault((platform, category, shard), []).append(path)
    return [
        {
            "id": index,
            "paths": sorted(paths),
            "os": platform,
            "category": category,
            "timeout_minutes": (
                30
                if full
                or any(
                    path in FULL_TARGETED_EXCLUSIVE_PATHS.get((platform, category), ())
                    for path in paths
                )
                else 15
            ),
        }
        for index, ((platform, category, _), paths) in enumerate(
            sorted(buckets.items())
        )
    ]


def test_tree_module_owner(
    path: str, *, unit_inventory: dict[str, list[str]]
) -> str | None:
    """Return the module that owns an ordinary test-tree-only change."""

    if not path.endswith(".py"):
        return None
    parts = Path(path).parts
    if len(parts) >= 3 and parts[0] == "tests" and parts[1] in unit_inventory:
        return parts[1]
    for module, extras in MODULE_EXTRA_TESTS.items():
        for extra in extras:
            if path == extra or path.startswith(extra.rstrip("/") + "/"):
                return module
    return None


def select(
    paths: list[str], *, full: bool = False, pr_fast: bool = False, root: Path = ROOT
) -> dict:
    rules = json.loads((root / "scripts/ci/check-scopes.json").read_text())
    catalog = load_catalog(root)
    unit_inventory = json.loads((root / "scripts/ci/unit-tests.json").read_text())
    checks = {name: False for name in rules["checks"]}
    reasons: dict[str, list[str]] = {name: [] for name in checks}
    unit_packages: set[str] = set()
    e2e = full

    def enable(names: list[str], reason: str) -> None:
        for name in names:
            if name not in checks:
                raise ValueError(f"unknown check {name!r}")
            checks[name] = True
            if reason not in reasons[name]:
                reasons[name].append(reason)

    enable(["docs"], "repository documentation invariants")
    if full:
        enable(list(checks), "explicit full validation")
    variables = make_paths(root)
    reviewed_test_paths: set[str] = set()
    targeted_test_paths: set[str] = set()
    targeted_cases: set[tuple[str, str, str]] = set()
    if full:
        for test, role in all_targeted_test_cases(catalog=catalog):
            for platform in role["platforms"]:
                targeted_cases.add((test, platform, role["category"]))
    for path in sorted(set(paths)):
        direct_targeted: list[tuple[str, dict]] = []
        if pr_fast and not full:
            direct_targeted = targeted_test_cases(path, catalog=catalog)
            for test, role in direct_targeted:
                for platform in role["platforms"]:
                    targeted_cases.add((test, platform, role["category"]))
        if direct_targeted:
            # A reviewed integration/platform test or its dedicated fixture
            # owns its exact execution.  Test-only changes do not expand into
            # the package regression or unrelated product smoke workflows.
            reviewed_test_paths.add(path)
            node_owner = targeted_node_owner(path, catalog=catalog)
            if node_owner is None:
                targeted_test_paths.add(path)
            else:
                # A mixed file keeps its unlisted unit/contract nodes in the
                # module regression while its reviewed slow nodes run exactly.
                unit_packages.add(node_owner)
            # The catalog is the complete owner for a reviewed test-only path.
            # Do not let older directory or Makefile inventories add product
            # workflows after the exact file/node jobs have been selected.
            continue
        if pr_fast and not full and path != SMOKE_TEST:
            owner = reviewed_unit_owner(path, catalog=catalog) or test_tree_module_owner(
                path, unit_inventory=unit_inventory
            )
            if owner is not None:
                # Test implementation and owned fixture changes validate their
                # package regression only. Product source, shared test support,
                # the core smoke, and explicitly classified targeted tests keep
                # their separate risk routes.
                unit_packages.add(owner)
                reviewed_test_paths.add(path)
                continue
        if (
            path.startswith(WINDOWS_WORKER_FULL_TEST_PREFIXES)
            or path in WINDOWS_WORKER_FULL_BOUNDARIES
            and path.startswith("tests/coding/")
        ):
            enable(["windows_shell"], f"{path}: native Worker test coverage")
        if path.startswith("src/") and path.endswith(".py"):
            enable(["architecture"], f"{path}: source dependency facts")
        if (
            path
            == "docs/internals/architecture/generated/current-package-dependencies.md"
        ):
            enable(["architecture"], f"{path}: generated source dependency facts")
            continue
        ordinary_document = not path.startswith("tests/") and (
            path.startswith("docs/")
            or "/" not in path
            or Path(path).name in {"README.md", "AGENTS.md", "TODO.md"}
        )
        if (path.endswith((".md", ".rst")) and ordinary_document) or path in rules[
            "document_files"
        ]:
            enable(["docs"], f"{path}: documentation")
            continue
        if pr_fast and not full and path == MODULE_REGRESSION_WORKFLOW:
            # This reusable workflow only runs offline module regressions. Gate
            # changes elsewhere still retain broad native validation.
            enable(["ci"], f"{path}: module regression workflow and Actions syntax")
            unit_packages.update(set(unit_inventory) - FAST_EXCLUDED_PACKAGES)
            e2e = True
            continue
        if pr_fast and not full and path == SMOKE_TEST:
            e2e = True
            continue
        if (
            pr_fast
            and not full
            and path in SCOPED_WORKFLOWS
            and path not in PR_ROUTING_FILES
        ):
            owned = [check for scope in SCOPED_WORKFLOWS[path]
                     for check in rules["workflows"][scope]]
            enable(["ci", *owned], f"{path}: validate the changed reusable workflow")
            if not SCOPED_WORKFLOWS[path]:
                # The E2E reusable workflow has no separate check scope; its
                # own existing smoke jobs are the behavior being validated.
                e2e = True
            continue
        if pr_fast and not full and path in PR_ROUTING_FILES:
            enable(["ci"], f"{path}: PR gate routing regression and Actions syntax")
            continue
        if pr_fast and not full and not direct_targeted:
            parts = Path(path).parts
            package = None
            if len(parts) >= 4 and parts[:2] == ("src", "loushang"):
                package = parts[2]
            elif len(parts) >= 3 and parts[0] == "tests":
                package = parts[1]
            if package in unit_inventory and package not in FAST_EXCLUDED_PACKAGES:
                # Non-Python package fixtures that have no registered owner
                # retain the conservative package and product routing.
                test_is_unit = (
                    path.startswith("src/") and path.endswith(".py")
                ) or path in unit_inventory[package]
                matching_rules = [
                    rule for rule in rules["rules"]
                    if any(fnmatch.fnmatchcase(path, p) for p in rule["paths"])
                ]
                matched_checks = {
                    check
                    for rule in matching_rules
                    for check in rule["checks"]
                }
                if (
                    test_is_unit
                    and not (matched_checks & FAST_RISK_CHECKS)
                    and not (package == "coding" and "coding_ui" in matched_checks)
                    and not any(
                        rule["reason"] in FAST_RISK_RULE_REASONS
                        for rule in matching_rules
                    )
                ):
                    unit_packages.add(package)
                    e2e |= any(part in path for part in E2E_PATH_PARTS)
                    e2e |= package == "coding" and "hosted" in Path(path).name
                    continue
        matched = False
        for rule in rules["rules"]:
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in rule.get("exclude_paths", [])):
                continue
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in rule["paths"]):
                enable(rule["checks"], f"{path}: {rule['reason']}")
                if (
                    pr_fast
                    and not full
                    and rule.get("pr_test_only")
                    and path.startswith("tests/")
                ):
                    # Reviewed test/support changes keep their existing owner
                    # and module regressions without unrelated product E2E.
                    reviewed_test_paths.add(path)
                matched = True
        # Reuse the actual coverage inventories instead of copying hundreds of
        # support files into a second, drifting list of path filters.
        for name, variable_names in rules["make_scopes"].items():
            for variable in variable_names:
                if variable not in variables:
                    raise ValueError(f"missing Makefile inventory {variable}")
                if any(
                    path == p or path.startswith(p + "/") for p in variables[variable]
                ):
                    enable([name], f"{path}: {variable}")
                    if (
                        pr_fast
                        and not full
                        and variable.endswith("_TEST_PATHS")
                        and path.startswith("tests/")
                        and path.endswith(".py")
                    ):
                        # The existing Makefile test inventory already runs
                        # this test through its declared owner.  A test-only
                        # edit does not need the unrelated Product E2E smoke.
                        reviewed_test_paths.add(path)
                    matched = True
        for covered in variables["HARNESSTUI_TEST_PATHS"]:
            if path == covered or path.startswith(covered + "/"):
                scope = (
                    "coding_ui" if covered.startswith("tests/coding/") else "harnesstui"
                )
                enable([scope], f"{path}: HARNESSTUI_TEST_PATHS")
                if (
                    pr_fast
                    and not full
                    and path.startswith("tests/")
                    and path.endswith(".py")
                ):
                    reviewed_test_paths.add(path)
                matched = True
        if not matched:
            enable(list(checks), f"{path}: unclassified path (full validation)")

    while True:
        before = checks.copy()
        for check, dependencies in rules["check_dependencies"].items():
            if checks[check]:
                enable(dependencies, f"required by {check}")
        if before == checks:
            break
    ai_source_changed = any(
        path.startswith("src/loushang/ai/") and path.endswith(".py")
        for path in paths
    )
    if pr_fast and not full and ai_source_changed:
        # AI's two local HTTP lifecycle nodes have a separate integration
        # owner. Source changes must retain them after the module and coverage
        # commands deselect them; direct test changes were collected above.
        ai_targeted = catalog.get("targeted_nodes", {}).get("ai", {})
        for path, role in ai_targeted.get("files", {}).items():
            for node in role["nodes"]:
                for platform in role["platforms"]:
                    targeted_cases.add(
                        (f"{path}::{node}", platform, role["category"])
                    )
    # These historical package jobs ran the same offline pytest inventories as
    # the module runner.  Give their selected checks to the one module runner so
    # ordinary, risk and full plans cannot execute the same suite twice.
    targeted_only = bool(targeted_test_paths) and all(
        path in targeted_test_paths
        or path.endswith((".md", ".rst"))
        or path in rules["document_files"]
        for path in paths
    )
    if not targeted_only:
        unit_packages.update(
            module for check, module in CHECK_MODULE_REGRESSIONS.items()
            if checks[check]
        )
    workflows = {
        name: any(checks[check] for check in scopes)
        for name, scopes in rules["workflows"].items()
    }
    if pr_fast and not full:
        # A risk path already running the complete package gate owns the same
        # offline tests; mixed PRs must not launch that module twice.
        unit_packages = {
            package for package in unit_packages
            if (
                package in CHECK_MODULE_REGRESSIONS.values()
                or not checks.get("tui_unit" if package == "tui" else package, False)
            )
        }
    gate_infra = any(
        path.startswith((".github/workflows/", "scripts/ci/"))
        and path != ".github/workflows/e2e-smoke-quality.yml"
        and path not in PR_ROUTING_FILES
        for path in paths
    )
    unscoped_gate_infra = any(
        path.startswith((".github/workflows/", "scripts/ci/"))
        and path not in SCOPED_WORKFLOWS
        and path not in PR_ROUTING_FILES
        for path in paths
    )
    if pr_fast and not full and unscoped_gate_infra:
        # Unclassified gate changes exercise Agent regression and E2E. Scoped
        # reusable workflows already execute their complete owning checks;
        # unrelated product behavior does not validate their orchestration.
        if not checks["agent"]:
            unit_packages.add("agent")
        e2e = True
    if pr_fast and not full and any(
        path.startswith(("src/", "tests/")) and not path.endswith((".md", ".rst"))
        and path not in reviewed_test_paths
        and path not in PR_ROUTING_FILES
        for path in paths
    ):
        e2e = True
    workflows["e2e"] = e2e
    windows = {
        "smoke": False,
        "worker_pr": False,
        "worker_full": False,
        "shell_full": False,
        "appservice_full": False,
        "tui_full": False,
    }
    if not pr_fast or full:
        windows.update({
            "worker_full": checks["windows_shell"],
            "shell_full": checks["windows_shell"],
            "appservice_full": checks["appservice"],
            "tui_full": checks["tui_native"] or checks["tui_playback"],
        })
    else:
        windows["smoke"] = checks["windows_shell"]
        for path in paths:
            # Unknown and gate-infrastructure paths retain the complete native
            # matrix. New Windows owners must be classified before fast routing.
            known = any(
                any(fnmatch.fnmatchcase(path, pattern) for pattern in rule["paths"])
                for rule in rules["rules"]
            ) or any(
                path == entry or path.startswith(entry + "/")
                for entries in variables.values() for entry in entries
            )
            broad = (
                (path.startswith(WINDOWS_GATE_INFRA[:3])
                 and path not in SCOPED_WORKFLOWS and path not in PR_ROUTING_FILES)
                or path in WINDOWS_GATE_INFRA[3:]
                or (not known and not path.endswith((".md", ".rst")))
            )
            workflow_scopes = SCOPED_WORKFLOWS.get(path, ())
            if "windows-shell" in workflow_scopes:
                windows["worker_full"] = windows["shell_full"] = True
            if "appservice" in workflow_scopes:
                windows["appservice_full"] = True
            if "tui" in workflow_scopes:
                windows["tui_full"] = True
            if broad:
                windows.update({
                    "worker_full": checks["windows_shell"],
                    "shell_full": checks["windows_shell"],
                    "appservice_full": checks["appservice"],
                    "tui_full": checks["tui_native"] or checks["tui_playback"],
                })
                continue
            if checks["windows_shell"]:
                worker_native = (
                    path.startswith(WINDOWS_WORKER_NATIVE_PREFIXES)
                    or path.startswith(WINDOWS_WORKER_FULL_TEST_PREFIXES)
                    or path in WINDOWS_WORKER_FULL_BOUNDARIES
                    or ("worker" in path and any(
                        part in path for part in WINDOWS_WORKER_NATIVE_PARTS
                    ))
                )
                if worker_native:
                    if (
                        path in WINDOWS_WORKER_FULL_BOUNDARIES
                        or path.startswith(WINDOWS_WORKER_FULL_TEST_PREFIXES)
                        or (path.startswith("tests/harness/worker/")
                            and "windows" in Path(path).name)
                    ):
                        windows["worker_full"] = True
                    else:
                        windows["worker_pr"] = True
                windows["shell_full"] |= (
                    path.startswith(WINDOWS_SHELL_FULL_PREFIXES)
                    or any(part in path for part in WINDOWS_SHELL_FULL_PARTS)
                )
            if checks["appservice"]:
                windows["appservice_full"] |= (
                    path.startswith(WINDOWS_APPSERVICE_FULL_PREFIXES)
                    or any(part in path for part in WINDOWS_APPSERVICE_FULL_PARTS)
                )
            if checks["tui_native"]:
                windows["tui_full"] |= any(
                    part in path for part in WINDOWS_TUI_FULL_PARTS
                )
        if windows["worker_full"]:
            windows["worker_pr"] = False
    host_runtime_smoke = (
        checks["host_runtime"] and pr_fast and not full and not gate_infra
        and not windows["worker_full"]
        and not any(
            path.startswith("tests/hosting/")
            or path in {
                "tests/coding/test_package_worker_candidate_wheel.py",
                "tests/coding/test_package_worker_native_cli.py",
                "tests/coding/test_plugin_author_smoke.py",
                "tests/harness/conversation/test_json_index.py",
                "tests/harness/transcript/test_file_store_process_exit.py",
                "tests/harness/transcript/test_model_input.py",
            }
            for path in paths
        )
    )
    hosting_worker_pr_smoke = (
        host_runtime_smoke and checks["hosting"]
        and not any(path.startswith((
            "src/loushang/hosting/", "tests/hosting/",
            "src/loushang/harness/worker/", "tests/harness/worker/",
        )) for path in paths)
    )
    # Retain complete offline regressions when a paused native workflow owned them.
    if not targeted_only:
        for workflow, packages in PAUSED_MODULES.items():
            if workflow in PAUSED_WORKFLOWS and workflows[workflow]:
                unit_packages.update(packages)
    unit_jobs = [
        {"package": package, "shard": shard,
         "shards": MODULE_SHARD_COUNTS.get(package, 1)}
        for package in sorted(unit_packages)
        for shard in range(MODULE_SHARD_COUNTS.get(package, 1))
    ]
    targeted_jobs = make_targeted_jobs(targeted_cases, full=full)
    workflows["units"] = bool(unit_jobs or targeted_jobs)
    for workflow in PAUSED_WORKFLOWS:
        workflows[workflow] = False
        reasons.setdefault("ci", []).append(f"{workflow}: temporarily paused by user request")
    return {
        "version": 1,
        "test_policy_version": catalog["version"],
        "paths": sorted(set(paths)),
        "checks": checks,
        "workflows": workflows,
        "unit_packages": sorted(unit_packages),
        "unit_jobs": unit_jobs,
        "module_tests": bool(unit_jobs),
        "targeted_jobs": targeted_jobs,
        "targeted_tests": bool(targeted_jobs),
        "e2e": e2e,
        "e2e_interaction": e2e and (full or gate_infra or all(checks.values())
            or ".github/workflows/e2e-smoke-quality.yml" in paths or any(
            path.startswith((
                "src/loushang/agent/", "tests/agent/",
                "src/loushang/tui/", "tests/tui/",
                "src/loushang/harnesstui/", "tests/harnesstui/",
                "src/loushang/coding/ui/", "tests/coding/test_screen_",
                "src/loushang/coding/session/", "tests/coding/test_agent_session",
                "src/loushang/coding/tools/", "src/loushang/coding/tool_", "tests/coding/test_tool_",
                "src/loushang/coding/session_manager.py",
                "src/loushang/coding/appservice_adapter.py",
                "src/loushang/appservice/execution", "tests/appservice/test_execution",
                "src/loushang/appserver/execution", "tests/appserver/test_execution",
                "src/loushang/coding/policy", "tests/coding/test_policy",
                "src/loushang/harness/session/", "tests/harness/session/",
                "src/loushang/harness/tools/", "tests/harness/tools/",
                "src/loushang/harness/approval/", "tests/harness/approval/",
                "src/loushang/harness/policy/", "tests/harness/policy/",
                "src/loushang/harness/workspace/", "tests/harness/workspace/",
                "src/loushang/coding/hosted", "tests/coding/test_hosted",
                "tests/coding/test_pr_smoke.py",
            )) for path in paths
        )),
        "windows": windows,
        "host_runtime_smoke": host_runtime_smoke,
        "hosting_worker_pr_smoke": hosting_worker_pr_smoke,
        "reasons": reasons,
    }


def workflow_plan(plan: dict) -> dict:
    """Return only the plan fields consumed by downstream workflows.

    Selection reasons can repeat every changed path across many checks.  Keeping
    them in the job output makes large pull requests exceed the runner's
    per-environment-variable size limit when reusable workflows bind the plan to
    ``CI_PLAN``.  The complete plan is still printed in the selector log; jobs
    receive only the executable portion.
    """
    return {
        key: plan[key]
        for key in ("version", "test_policy_version", "paths", "checks", "workflows", "unit_packages", "unit_jobs", "module_tests", "targeted_jobs", "targeted_tests", "e2e", "e2e_interaction", "windows", "host_runtime_smoke", "hosting_worker_pr_smoke")
    }


def event_paths(
    event_name: str, event: dict, *, root: Path = ROOT
) -> tuple[list[str], bool]:
    if event_name in {"schedule", "workflow_dispatch"}:
        return [], True
    if event_name == "pull_request":
        pr = event["pull_request"]
        ancestor = (
            git("merge-base", pr["base"]["sha"], pr["head"]["sha"], root=root)
            .decode()
            .strip()
        )
        return changed_paths(ancestor, pr["head"]["sha"], root=root), False
    if event_name == "push":
        before, after = event["before"], event["after"]
        if before == "0" * 40:
            return [], True
        return changed_paths(before, after, root=root), False
    raise ValueError(f"unsupported event {event_name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--pr-fast", action="store_true")
    parser.add_argument("--event", action="store_true")
    parser.add_argument("--paths", nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    full = args.full
    if args.event:
        paths, event_full = event_paths(
            os.environ["GITHUB_EVENT_NAME"],
            json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()),
        )
        full = full or event_full
    elif args.paths is not None:
        paths = args.paths
    elif args.head:
        paths = changed_paths(args.base, args.head)
    elif full:
        paths = []
    else:
        paths = local_paths(args.base)
    plan = select(
        paths, full=full,
        pr_fast=args.pr_fast or (
            # Post-merge pushes reuse the checked PR route. Scheduled and
            # manual runs retain the complete native and package matrix.
            args.event and os.environ["GITHUB_EVENT_NAME"] in {"pull_request", "push"}
        ),
    )
    if args.output:
        args.output.write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps(plan, indent=2))
    if args.event:
        # Never put filenames in output keys or executable shell text.
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write(
                "plan="
                + json.dumps(workflow_plan(plan), separators=(",", ":"))
                + "\n"
            )
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
            stream.write("## Selected checks\n\n")
            for check, enabled in plan["checks"].items():
                stream.write(f"- {check}: {'run' if enabled else 'not applicable'}\n")
            stream.write("\nPaused workflows: " + ", ".join(sorted(PAUSED_WORKFLOWS)) + "\n")
            stream.write("\nReasons are recorded in the selection job log.\n")


if __name__ == "__main__":
    main()
