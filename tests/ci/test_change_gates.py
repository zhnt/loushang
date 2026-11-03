from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ci"))


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/ci/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


selector = load_script("select_checks")
guard = load_script("verify_gate")
docs = load_script("check_docs")
runner = load_script("run_checks")
worker_sessions = load_script("windows_worker_session_cases")
shard_hash = load_script("shard_hash")


class ScopeTests(unittest.TestCase):
    def test_app_protocol_schema_selects_only_direct_consumers(self):
        path = "docs/internals/architecture/appserver/app-protocol-v1.schema.json"
        actual = self.selected(path)

        self.assertEqual(
            actual,
            {
                "docs",
                "gui",
                "architecture",
                "coding",
                "apphost",
                "appservice",
                "host_runtime",
            },
        )
        self.assertFalse(
            {
                "ai",
                "agent",
                "harness",
                "harness_native",
                "harnesstui",
                "coding_ui",
                "tui_unit",
                "tui_playback",
                "tui_native",
                "hosting",
                "windows_shell",
                "install",
                "lsp",
                "foundation",
            }
            & actual
        )

    def test_gui_code_and_tooling_select_only_gui_and_docs(self):
        for path in ("gui/src/App.tsx", "gui/src-tauri/Cargo.lock", "gui/pnpm-lock.yaml", "scripts/gui/run.mjs"):
            with self.subTest(path=path):
                self.assertEqual(self.selected(path), {"docs", "gui"})
                self.assertTrue(selector.select([path])["workflows"]["gui"])
        self.assertEqual(self.selected("gui/README.md"), {"docs"})

    def test_gui_runner_uses_the_package_check_without_make(self):
        (command,) = runner.commands("gui")
        self.assertEqual(command[1:], ["--dir", "gui", "run", "check"])
        self.assertIn("pnpm", command[0])

    def test_gui_workflow_does_not_select_runtime_suites(self):
        self.assertEqual(self.selected(".github/workflows/gui-quality.yml"), {"docs", "gui", "ci"})

    def test_gui_does_not_hide_shared_or_mixed_changes(self):
        self.assertEqual(self.selected("gui/src/App.tsx", "scripts/ci/select_checks.py"), set(selector.select([], full=True)["checks"]))
        runtime = self.selected("src/loushang/harness/example.py")
        self.assertEqual(self.selected("gui/src/App.tsx", "src/loushang/harness/example.py"), runtime | {"gui"})

    def test_gui_default_workflow_stays_lightweight(self):
        workflow = (ROOT / ".github/workflows/gui-quality.yml").read_text()
        self.assertIn("pnpm --dir gui run check", workflow)
        for heavy in ("rustup", "test:layout", "build:fixture-native", "check:full"):
            self.assertNotIn(heavy, workflow)
    def setUp(self):
        # Retain the underlying routing contracts for eventual gate restoration.
        pause = patch.object(selector, "PAUSED_WORKFLOWS", set())
        pause.start()
        self.addCleanup(pause.stop)

    def selected(self, *paths):
        return {
            name
            for name, enabled in selector.select(list(paths))["checks"].items()
            if enabled
        }

    def test_gui_documents_do_not_start_product_or_installation_checks(self):
        self.assertEqual(
            self.selected(
                "docs/internals/architecture/drafts/gui-requirements.md",
                "docs/internals/architecture/drafts/gui-engineering-bootstrap-plan.md",
                "docs/internals/architecture/drafts/README.md",
            ),
            {"docs"},
        )

    def test_ai_readme_is_documentation(self):
        self.assertEqual(self.selected("src/loushang/ai/README.md"), {"docs"})

    def test_coding_internal_change_does_not_test_its_dependencies(self):
        actual = self.selected("src/loushang/coding/lsp/client.py")
        self.assertEqual(
            actual, {"docs", "architecture", "coding", "lsp", "host_runtime"}
        )

    def test_coding_ui_does_not_run_ai_agent_or_full_harness(self):
        actual = self.selected("src/loushang/coding/ui/plain_renderer.py")
        self.assertTrue({"coding", "coding_ui", "tui_playback"} <= actual)
        self.assertFalse({"ai", "agent", "harness", "tui_native", "install"} & actual)

    def test_ai_internal_change_only_runs_ai_and_source_facts(self):
        self.assertEqual(
            self.selected("src/loushang/ai/pricing.py"), {"docs", "architecture", "ai"}
        )

    def test_ai_contract_change_reaches_agent_consumers(self):
        actual = self.selected("src/loushang/ai/types.py")
        self.assertTrue({"ai", "agent", "harness", "coding"} <= actual)
        self.assertNotIn("install", actual)

    def test_agent_does_not_run_ai_full_suite(self):
        actual = self.selected("src/loushang/agent/agent_loop.py")
        self.assertIn("agent", actual)
        self.assertIn("harness", actual)
        self.assertNotIn("ai", actual)

    def test_widget_does_not_provision_native_terminals(self):
        actual = self.selected("src/loushang/tui/ui_parts/widgets/button.py")
        self.assertTrue(
            {"tui_unit", "tui_playback", "harnesstui", "coding_ui"} <= actual
        )
        self.assertFalse({"tui_native", "ai", "agent", "harness", "install"} & actual)

    def test_terminal_change_requires_native_matrix(self):
        actual = self.selected("src/loushang/tui/terminal_backends/windows.py")
        self.assertTrue({"tui_native", "tui_playback", "tui_unit"} <= actual)

    def test_harnesstui_change_does_not_run_underlying_package_suites(self):
        actual = self.selected("src/loushang/harnesstui/surface/transcript.py")
        self.assertTrue({"harnesstui", "coding_ui", "tui_playback"} <= actual)
        self.assertFalse({"ai", "agent", "harness", "tui_unit", "tui_native"} & actual)

    def test_existing_cross_package_support_paths_keep_their_owner(self):
        self.assertIn(
            "harness", self.selected("src/loushang/coding/_product_worker_canary.py")
        )
        self.assertIn(
            "appservice", self.selected("src/loushang/coding/appservice_adapter.py")
        )
        self.assertIn(
            "harnesstui", self.selected("tests/harness/session/test_footer.py")
        )
        self.assertIn("coding_ui", self.selected("tests/coding/test_ui_status_line.py"))

    def test_cli_application_move_keeps_lint_and_catalog_guard_ownership(self):
        inventories = selector.make_paths()
        application = "src/loushang/coding/cli/application.py"
        catalog_guard = "tests/architecture/test_resource_catalog_rcp5_contract.py"
        self.assertIn(application, inventories["APPHOST_LINT_SUPPORT"])
        self.assertIn(catalog_guard, inventories["HARNESS_TEST_PATHS"])
        self.assertTrue({"coding", "apphost"} <= self.selected(application))
        self.assertIn("harness", self.selected(catalog_guard))
        self.assertNotIn("ai", self.selected(catalog_guard))

    def test_g18_collector_has_selection_and_actual_test_lint_ownership(self):
        makefile = (ROOT / "Makefile").read_text()
        lint = makefile.split("\nlint-appservice:\n", 1)[1].split("\ntypecheck-appservice:", 1)[0]
        for script, test in (
            ("scripts/dev/_g18_provenance.py", "tests/dev/test_g18_provenance.py"),
            ("scripts/dev/_g18_recovery.py", "tests/dev/test_g18_recovery.py"),
            ("scripts/dev/_g18_slot.py", "tests/dev/test_g18_slot.py"),
            ("scripts/dev/_g18_bytecode.py", "tests/dev/test_g18_bytecode.py"),
            ("scripts/dev/_g18_checkpoint.py", "tests/dev/test_g18_checkpoint.py"),
            ("scripts/dev/_g18_comparison.py", "tests/dev/test_g18_comparison.py"),
            ("scripts/dev/measure_g18_startup.py", "tests/dev/test_measure_g18_startup.py"),
            ("scripts/dev/measure_g18_native.py", "tests/dev/test_measure_g18_native.py"),
            ("tests/coding/_interactive_startup_probe.py", "tests/dev/test_interactive_startup_probe.py"),
            ("scripts/dev/_interactive_campaign.py", "tests/dev/test_interactive_campaign.py"),
        ):
            with self.subTest(script=script, test=test):
                for path in (script, test):
                    expected = {"docs", "appservice", "host_runtime"}
                    if path == "tests/coding/_interactive_startup_probe.py":
                        expected.add("coding")
                    self.assertEqual(self.selected(path), expected)
                self.assertIn(test, selector.make_paths()["APPSERVICE_TEST_PATHS"])
                self.assertIn(f"ruff check {script}", lint)
        for evidence in (
            "startup-performance-g18-linux-aa-baseline.json",
            "startup-performance-g18-linux-native-warm-aa-baseline.json",
            "startup-performance-g18-linux-absent-aa-failure.json",
        ):
            with self.subTest(evidence=evidence):
                self.assertEqual(
                    self.selected(f"docs/internals/architecture/harness/{evidence}"),
                    {"docs", "appservice", "host_runtime"},
                )
        self.assertIn("$(APPSERVICE_TEST_PATHS)", lint)
        self.assertIn("$(PYTEST_RUNNER) $(APPSERVICE_TEST_PATHS)", makefile)
        # No broad tests/dev exception: unknown tools still get full validation.
        self.assertEqual(self.selected("tests/dev/test_unknown_tool.py"),
                         set(selector.select([], full=True)["checks"]))

    def test_coding_facade_checks_all_entry_consumers_additively(self):
        self.assertTrue({"coding", "architecture", "host_runtime", "coding_ui",
                         "tui_native", "apphost", "appservice", "install"}
                        <= self.selected("src/loushang/coding/__init__.py"))

    def test_g17_evidence_and_hosting_providers_select_native_application_consumers(self):
        paths = (
            "tests/coding/_hosted_darwin_observer.py",
            "tests/coding/_hosted_owned_group.py",
            "tests/coding/_hosted_windows_witness.py",
            "tests/coding/_hosted_primitive_child.py",
            "tests/coding/test_hosted_darwin_primitives.py",
            "tests/coding/test_hosted_installed_evidence.py",
            "tests/tui/terminal_process_support/posix_pty.py",
            "tests/tui/terminal_process_support/windows_conpty.py",
            "tests/coding/test_mux_native_evidence.py",
            "tests/coding/test_mux_installed_evidence.py",
            "scripts/dev/run_g16_installed_evidence.py",
            "scripts/dev/run_g17_installed_evidence.py",
            "scripts/dev/_evidence_process.py",
            "scripts/dev/_evidence_observation.py",
            "scripts/dev/_evidence_windows.py",
            "scripts/dev/verify_evidence_manifest.py",
            "src/loushang/hosting/_posix_process.py",
            "src/loushang/hosting/_windows_process.py",
            "src/loushang/hosting/runtime.py",
            "src/loushang/hosting/contracts.py",
        )
        for path in paths:
            with self.subTest(path=path):
                plan = selector.select([path])
                self.assertTrue(plan["checks"]["appservice"])
                self.assertTrue(plan["workflows"]["appservice"])

    def test_machine_consumed_docs_are_not_skipped(self):
        actual = self.selected(
            "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c5-evidence-manifest.json"
        )
        self.assertTrue({"harness", "hosting", "windows_shell"} <= actual)

    def test_coding_package_windows_paths_select_native_windows_gate(self):
        for path in (
            "src/loushang/coding/package_pre_b_snapshot.py",
            "src/loushang/coding/package_installation_private_data.py",
            "src/loushang/coding/package_legacy_windows_receipt.py",
            "src/loushang/coding/package_external_worker_wheel.py",
            "src/loushang/coding/cli/package_cutover.py",
            "tests/coding/test_package_windows_pre_b_snapshot.py",
            "tests/coding/test_package_cutover_cli.py",
        ):
            with self.subTest(path=path):
                plan = selector.select([path])
                self.assertTrue(plan["checks"]["windows_shell"])
                self.assertTrue(plan["workflows"]["windows-shell"])

    def test_windows_product_private_owner_changes_select_native_gate(self):
        for path in (
            "src/loushang/coding/package_private_data_windows_preview.py",
            "src/loushang/coding/package_private_data_windows_backup.py",
            "src/loushang/coding/package_private_data_windows_backup_expiry_owner.py",
            "src/loushang/coding/package_private_data_windows_backup_expiry_recovery.py",
            "src/loushang/coding/package_private_data_backup_records.py",
            "src/loushang/foundation/windows_private_acl.py",
            "src/loushang/harness/package_product/product_local_wheel_runtime.py",
        ):
            with self.subTest(path=path):
                plan = selector.select([path])
                self.assertTrue(plan["checks"]["windows_shell"])
                self.assertTrue(plan["workflows"]["windows-shell"])

    def test_coding_worker_product_changes_select_native_platform_gates(self):
        for path in (
            "src/loushang/coding/package_product_worker_payload.py",
            "src/loushang/coding/package_product_worker_windows_provisioning.py",
            "src/loushang/coding/package_product_worker_windows_provisioning_journal.py",
            "src/loushang/coding/cli/package_worker_native.py",
            "src/loushang/plugin/_coding_local_worker_wheel.py",
            "tests/coding/test_package_product_worker_discovery.py",
            "tests/coding/test_package_product_worker_opt_in.py",
            "tests/coding/test_package_worker_candidate_wheel.py",
            "tests/coding/test_package_worker_native_cli.py",
        ):
            with self.subTest(path=path):
                plan = selector.select([path])
                self.assertTrue(plan["checks"]["hosting"])
                self.assertTrue(plan["workflows"]["hosting"])
                self.assertTrue(plan["checks"]["windows_shell"])
                self.assertTrue(plan["workflows"]["windows-shell"])

    def test_plugin_sdk_sources_select_owners_without_full_validation(self):
        expected = {"docs", "architecture", "coding", "harness", "host_runtime"}
        native = {"__init__.py", "__main__.py", "_coding_local_worker_wheel.py"}
        for path in sorted((ROOT / "src/loushang/plugin").glob("*.py")):
            with self.subTest(path=path.name):
                actual = self.selected(path.relative_to(ROOT).as_posix())
                if path.name in native:
                    self.assertEqual(actual, expected | {"hosting", "windows_shell"})
                else:
                    self.assertEqual(actual, expected)
        self.assertEqual(
            self.selected("src/loushang/plugin/new_native_entry.py"),
            set(selector.select([], full=True)["checks"]),
        )

    def test_registered_worker_recovery_changes_select_real_reboot_gate(self):
        for path in (
            ".github/workflows/worker-registered-reboot-drill.yml",
            "scripts/dev/worker_registered_reboot_drill.py",
            "scripts/dev/worker_registered_qemu_reboot_drill.sh",
            "src/loushang/coding/package_product_worker_registered_recovery.py",
            "tests/coding/test_package_worker_candidate_wheel.py",
        ):
            with self.subTest(path=path):
                plan = selector.select([path])
                self.assertTrue(plan["checks"]["registered_reboot"])
                self.assertTrue(plan["workflows"]["worker-reboot"])

    def test_ordinary_worker_session_changes_select_native_gates(self):
        for path in (
            "src/loushang/coding/_tool_authority.py",
            "src/loushang/coding/bootstrap.py",
            "src/loushang/coding/composition_provenance.py",
            "src/loushang/coding/composition_sets.py",
            "src/loushang/coding/runtime/agent_session_runtime.py",
            "src/loushang/coding/session/agent_session.py",
            "src/loushang/coding/session_manager.py",
        ):
            with self.subTest(path=path):
                plan = selector.select([path])
                self.assertTrue(plan["checks"]["hosting"])
                self.assertTrue(plan["workflows"]["hosting"])
                self.assertTrue(plan["checks"]["windows_shell"])
                self.assertTrue(plan["workflows"]["windows-shell"])

    def test_ordinary_worker_linux_cli_changes_select_native_gate(self):
        for path in (
            "src/loushang/coding/cli/application.py",
            "src/loushang/coding/cli/args.py",
            "src/loushang/coding/cli/composition_choice.py",
            "src/loushang/coding/cli/profile.py",
            "tests/coding/test_plugin_p4_worker_turn.py",
        ):
            with self.subTest(path=path):
                plan = selector.select([path])
                self.assertTrue(plan["checks"]["hosting"])
                self.assertTrue(plan["workflows"]["hosting"])

    def test_markdown_test_fixtures_are_not_ordinary_documentation(self):
        self.assertIn("tui_playback", self.selected("tests/tui/fixtures/table.md"))

    def test_packaged_prompts_and_skills_are_product_inputs(self):
        for path in (
            "src/loushang/coding/_plugins/coding_base/prompts/standard.md",
            "src/loushang/coding/_plugins/coding_base/skills/standard/SKILL.md",
        ):
            self.assertIn("coding", self.selected(path))

    def test_dependency_and_unknown_paths_select_every_configured_check(self):
        expected = set(selector.select([], full=True)["checks"])
        for path in (
            "uv.lock",
            "pyproject.toml",
            "Makefile",
            "requirements-dev.txt",
            "scripts/ci/select_checks.py",
            "tests/conftest.py",
            "src/loushang/new_package/foo.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.selected(path), expected)

    def test_pr_routing_files_use_ci_contract_gate(self):
        for path in selector.PR_ROUTING_FILES:
            with self.subTest(path=path):
                plan = selector.select([path], pr_fast=True)
                self.assertEqual(
                    {name for name, enabled in plan["checks"].items() if enabled},
                    {"docs", "ci"},
                )
                self.assertEqual(
                    {name for name, enabled in plan["workflows"].items() if enabled},
                    set(),
                )
                self.assertEqual(plan["unit_packages"], [])
                self.assertFalse(plan["e2e"])
        plan = selector.select(sorted(selector.PR_ROUTING_FILES), pr_fast=True)
        self.assertEqual(
            {name for name, enabled in plan["checks"].items() if enabled},
            {"docs", "ci"},
        )
        self.assertEqual(
            {name for name, enabled in plan["workflows"].items() if enabled},
            set(),
        )
        self.assertEqual(plan["unit_packages"], [])
        self.assertFalse(plan["e2e"])

    def test_smoke_workflow_only_runs_ci_and_both_platform_smokes(self):
        plan = selector.select([".github/workflows/e2e-smoke-quality.yml"], pr_fast=True)
        self.assertEqual({k for k, v in plan["checks"].items() if v}, {"docs", "ci"})
        self.assertEqual({k for k, v in plan["workflows"].items() if v}, {"e2e"})
        self.assertTrue(plan["e2e_interaction"])
        self.assertFalse(plan["windows"]["worker_full"])

    def test_smoke_test_change_runs_its_own_cases_without_unrelated_suites(self):
        plan = selector.select([selector.SMOKE_TEST], pr_fast=True)
        self.assertEqual({k for k, v in plan["checks"].items() if v}, {"docs"})
        self.assertEqual({k for k, v in plan["workflows"].items() if v}, {"e2e"})
        self.assertTrue(plan["e2e_interaction"])
        self.assertTrue(all(selector.select([selector.SMOKE_TEST], full=True)["checks"].values()))

    def test_reusable_workflows_validate_their_complete_owned_scope(self):
        rules = json.loads((ROOT / "scripts/ci/check-scopes.json").read_text())
        for path, scopes in selector.SCOPED_WORKFLOWS.items():
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())
                if path in selector.PR_ROUTING_FILES:
                    continue
                if not scopes:
                    # Covered by the dedicated E2E workflow contract above.
                    continue
                plan = selector.select([path], pr_fast=True)
                expected = {"docs", "ci"} | {c for scope in scopes
                                                    for c in rules["workflows"][scope]}
                if set(scopes) & {"harness", "hosting", "apphost", "appservice"}:
                    expected.add("host_runtime")
                self.assertEqual({k for k, v in plan["checks"].items() if v}, expected)
                expected_workflows = set(scopes)
                if "host_runtime" in expected:
                    expected_workflows.add("host-runtime")
                self.assertEqual({k for k, v in plan["workflows"].items() if v}, expected_workflows)
                self.assertEqual(plan["unit_packages"], [])
                self.assertFalse(plan["e2e"])
        plan = selector.select([".github/workflows/windows-shell-compatibility.yml"], pr_fast=True)
        self.assertTrue(plan["windows"]["worker_full"])
        self.assertTrue(plan["windows"]["shell_full"])

    def test_smoke_workflow_does_not_expand_a_mixed_windows_change(self):
        source = "src/loushang/coding/package_product_worker_catalog.py"
        baseline = selector.select([source], pr_fast=True)
        mixed = selector.select([source, ".github/workflows/e2e-smoke-quality.yml"], pr_fast=True)
        self.assertEqual(mixed["windows"], baseline["windows"])
        self.assertEqual(mixed["host_runtime_smoke"], baseline["host_runtime_smoke"])
        self.assertTrue(mixed["e2e_interaction"])

    def test_root_unknown_and_scheduled_workflows_stay_full(self):
        for path in (".github/workflows/new.yml",):
            self.assertTrue(all(selector.select([path], pr_fast=True)["checks"].values()))
        self.assertTrue(all(selector.select([".github/workflows/e2e-smoke-quality.yml"],
                                            pr_fast=True, full=True)["checks"].values()))
        mixed = selector.select([".github/workflows/e2e-smoke-quality.yml", "uv.lock"], pr_fast=True)
        self.assertTrue(all(mixed["checks"].values()))

    def test_module_regression_workflow_change_runs_its_complete_inventory(self):
        for paths in (
            [selector.MODULE_REGRESSION_WORKFLOW],
            [selector.MODULE_REGRESSION_WORKFLOW, "scripts/ci/select_checks.py",
             "scripts/ci/unit-tests.json", "tests/work/test_package_boundaries.py"],
        ):
            with self.subTest(paths=paths):
                plan = selector.select(paths, pr_fast=True)
                self.assertEqual(
                    plan["unit_packages"],
                    ["agent", "ai", "channel", "coding", "harness", "harnesstui",
                     "harnesswork", "method", "ontology", "resource", "tui", "work"],
                )
                self.assertEqual(len(plan["unit_jobs"]), 20)
                self.assertEqual(
                    {name for name, enabled in plan["checks"].items() if enabled},
                    {"docs", "ci"},
                )
                self.assertEqual(
                    {name for name, enabled in plan["workflows"].items() if enabled},
                    {"units", "e2e"},
                )
                self.assertFalse(any(
                    plan["windows"][scope]
                    for scope in ("smoke", "worker_pr", "worker_full",
                                  "shell_full", "appservice_full", "tui_full")
                ))

    def test_pr_routing_exception_keeps_build_and_other_ci_files_full(self):
        expected = set(selector.select([], full=True)["checks"])
        for path in (
            "pyproject.toml", "scripts/ci/run_checks.py", "tests/ci/test_new_gate.py",
        ):
            with self.subTest(path=path):
                actual = selector.select([path], pr_fast=True)["checks"]
                self.assertEqual({name for name, enabled in actual.items() if enabled}, expected)

    def test_generated_document_rechecks_source_facts(self):
        path = "docs/internals/architecture/generated/current-package-dependencies.md"
        self.assertEqual(self.selected(path), {"docs", "architecture"})
        self.assertTrue(selector.select([path], pr_fast=True)["workflows"]["architecture"])

    def test_ordinary_docs_only_pr_needs_no_reusable_workflow(self):
        plan = selector.select(["docs/guide.md", "README.md"], pr_fast=True)
        self.assertEqual(
            {name for name, enabled in plan["checks"].items() if enabled},
            {"docs"},
        )
        self.assertFalse(any(plan["workflows"].values()))
        self.assertFalse(plan["host_runtime_smoke"])

    def test_pr_code_paths_run_resume_turn_e2e_on_all_platforms(self):
        for path in (
            "src/loushang/ai/pricing.py",
            "src/loushang/ai/types.py",
            "src/loushang/coding/session/agent_session.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(selector.select([path], pr_fast=True)["e2e"])
        self.assertTrue(selector.select([], full=True, pr_fast=True)["e2e"])
        workflow = (ROOT / ".github/workflows/e2e-smoke-quality.yml").read_text()
        self.assertIn("os: [ubuntu-24.04, macos-15, windows-2022]", workflow)
        self.assertIn('--require-tests-count "$SMOKE_CASE_COUNT"', workflow)
        self.assertIn("CI_PLAN: ${{ inputs.plan }}", workflow)
        self.assertIn("fromJSON(inputs.plan).e2e_interaction && 2 || 1", workflow)
        report_step = workflow.split("- name: Verify every selected smoke case ran and passed", 1)[1]
        self.assertIn("shell: bash", report_step.split("- uses:", 1)[0])
        self.assertIn("uv run python scripts/ci/run_checks.py e2e_smoke", workflow)
        self.assertIn("tests/coding/test_resume_darwin.py", workflow)
        self.assertIn("--require-tests-count 2", workflow)
        self.assertIn("--require-property native_platform=darwin", workflow)
        self.assertIn("--require-property resume_route=session-lifecycle", workflow)

    def test_interaction_smoke_is_selected_for_control_paths_only(self):
        for path in (
            "src/loushang/agent/agent.py",
            "src/loushang/coding/session/agent_session.py",
            "src/loushang/coding/ui/screen_input.py",
            "src/loushang/harness/tools/core.py",
            "src/loushang/harnesstui/conversation/control.py",
        ):
            with self.subTest(path=path):
                plan = selector.select([path], pr_fast=True)
                self.assertTrue(plan["e2e_interaction"])
                self.assertTrue(selector.workflow_plan(plan)["e2e_interaction"])
                command, = runner.commands("e2e_smoke", plan=plan)
                self.assertIn("tests/coding/test_pr_smoke.py::test_terminal_cancel_tool_then_message_and_exit", command)
        for path in ("docs/guide.md", "src/loushang/ai/pricing.py"):
            with self.subTest(path=path):
                plan = selector.select([path], pr_fast=True)
                self.assertFalse(plan["e2e_interaction"])
                command, = runner.commands("e2e_smoke", plan=plan)
                self.assertNotIn("tests/coding/test_pr_smoke.py::test_terminal_cancel_tool_then_message_and_exit", command)
        self.assertTrue(selector.select([], full=True)["e2e_interaction"])

    def test_sustained_worker_query_does_not_expand_targeted_test(self):
        ordinary = selector.select(
            ["src/loushang/coding/session/agent_session.py"], pr_fast=True
        )
        worker = selector.select(
            ["src/loushang/coding/package_product_worker_windows_crash_cleanup.py"],
            pr_fast=True,
        )
        owned_test = selector.select(
            ["tests/coding/test_package_worker_candidate_wheel.py"], pr_fast=True
        )
        full = selector.select([], full=True, pr_fast=True)
        self.assertFalse(ordinary["checks"]["hosting_sustained"])
        self.assertFalse(worker["checks"]["hosting_sustained"])
        self.assertFalse(owned_test["checks"]["hosting_sustained"])
        self.assertTrue(full["checks"]["hosting_sustained"])

    def test_empty_changes_do_not_start_product_checks(self):
        self.assertEqual(self.selected(), {"docs"})



    def test_workflow_plan_omits_diagnostic_reasons(self):
        plan = selector.select(["src/loushang/coding/lsp/client.py"])

        compact = selector.workflow_plan(plan)

        self.assertEqual(
            set(compact), {"version", "test_policy_version", "paths", "checks", "workflows", "unit_packages", "unit_jobs", "module_tests", "targeted_jobs", "targeted_tests", "e2e", "e2e_interaction", "windows", "host_runtime_smoke", "hosting_worker_pr_smoke"}
        )
        self.assertEqual(compact["paths"], plan["paths"])
        self.assertEqual(compact["checks"], plan["checks"])
        self.assertEqual(compact["workflows"], plan["workflows"])
        self.assertEqual(compact["unit_packages"], plan["unit_packages"])
        self.assertEqual(compact["unit_jobs"], plan["unit_jobs"])
        self.assertEqual(compact["targeted_jobs"], plan["targeted_jobs"])
        self.assertEqual(compact["targeted_tests"], plan["targeted_tests"])
        self.assertEqual(compact["windows"], plan["windows"])
        self.assertEqual(compact["e2e"], plan["e2e"])
        self.assertEqual(compact["host_runtime_smoke"], plan["host_runtime_smoke"])
        self.assertEqual(compact["hosting_worker_pr_smoke"], plan["hosting_worker_pr_smoke"])
        self.assertNotIn("reasons", compact)

    def test_pr_windows_smoke_and_full_domains(self):
        ordinary = selector.select(
            ["src/loushang/coding/session/agent_session.py"], pr_fast=True
        )["windows"]
        self.assertTrue(ordinary["smoke"])
        self.assertFalse(ordinary["worker_full"] or ordinary["worker_pr"] or ordinary["shell_full"])

        worker = selector.select(
            ["src/loushang/coding/package_product_worker_windows_crash_cleanup_review.py"],
            pr_fast=True,
        )["windows"]
        self.assertTrue(worker["smoke"] and worker["worker_pr"])
        self.assertFalse(worker["worker_full"])
        self.assertFalse(worker["shell_full"])

        acl = selector.select(
            ["src/loushang/foundation/windows_private_acl.py"], pr_fast=True
        )["windows"]
        self.assertTrue(acl["smoke"] and acl["shell_full"])
        self.assertFalse(acl["worker_full"] or acl["worker_pr"])

    def test_pr_appservice_tui_and_gate_risk_keep_native_owners(self):
        appservice = selector.select(
            ["src/loushang/appservice/client.py"], pr_fast=True
        )["windows"]
        self.assertFalse(appservice["appservice_full"])
        record = selector.select(
            ["src/loushang/appserver/local_record.py"], pr_fast=True
        )["windows"]
        self.assertTrue(record["appservice_full"])
        tui = selector.select(
            ["src/loushang/tui/terminal_backends/windows.py"], pr_fast=True
        )["windows"]
        self.assertTrue(tui["tui_full"])
        gate = selector.select(
            [".github/workflows/windows-shell-compatibility.yml"], pr_fast=True
        )["windows"]
        self.assertTrue(gate["smoke"] and gate["worker_full"] and gate["shell_full"])
        self.assertFalse(gate["worker_pr"])
        full = selector.select([], full=True, pr_fast=True)["windows"]
        self.assertFalse(full["smoke"])
        self.assertFalse(full["worker_pr"])
        self.assertTrue(all(full[name] for name in ("worker_full", "shell_full", "appservice_full", "tui_full")))

    def test_pr_windows_worker_risk_selects_one_native_query(self):
        paths = (
            "src/loushang/coding/package_product_worker_windows_launch_intent.py",
            "src/loushang/coding/package_product_worker_native_release.py",
            "src/loushang/coding/package_product_worker_policy.py",
            "src/loushang/plugin/_coding_local_worker_wheel.py",
            "src/loushang/coding/package_product_worker_windows_gc_history.py",
            "src/loushang/coding/package_product_worker_windows_opt_in_owner.py",
            "src/loushang/coding/package_product_worker_windows_activation_state_journal.py",
            "src/loushang/coding/package_product_worker_windows_crash_cleanup_review.py",
        )
        for path in paths:
            with self.subTest(path=path):
                windows = selector.select([path], pr_fast=True)["windows"]
                self.assertTrue(windows["worker_pr"])
                self.assertFalse(windows["worker_full"])
        mixed = selector.select(
            [
                "src/loushang/coding/package_product_worker_windows_crash_cleanup_review.py",
                "src/loushang/coding/package_product_worker_windows_gc_history.py",
            ],
            pr_fast=True,
        )["windows"]
        self.assertTrue(mixed["worker_pr"])
        self.assertFalse(mixed["worker_full"])
        combined_name = selector.select(
            ["src/loushang/coding/package_product_worker_windows_crash_stage_retirement.py"],
            pr_fast=True,
        )["windows"]
        self.assertTrue(combined_name["worker_pr"])
        self.assertFalse(combined_name["worker_full"])

    def test_pr_worker_source_boundaries_keep_full_native_matrix(self):
        for path in (
            "src/loushang/hosting/_win32_process.py",
            "src/loushang/hosting/_windows_process.py",
        ):
            with self.subTest(path=path):
                windows = selector.select([path], pr_fast=True)["windows"]
                self.assertTrue(windows["worker_full"])
                self.assertFalse(windows["worker_pr"])

    def test_windows_worker_session_shards_preserve_every_native_case(self):
        pre_b = worker_sessions.PRE_B
        expected = {
            worker_sessions.ACTIVATION
            + "test_windows_product_c5_state_reopens_and_refuses_complete_record_loss",
            pre_b + "test_windows_ordinary_selection_preserves_pre_b_without_writing",
            pre_b + "test_windows_public_ordinary_session_enters_fresh_b_product",
            pre_b + "test_windows_public_runtime_session_enters_fresh_b_product",
            pre_b + "test_windows_ordinary_orphan_repair_refuses_worker_evidence",
            worker_sessions.HOSTED
            + "test_windows_hosted_ordinary_session_enters_fresh_b_product",
            pre_b + "test_windows_worker_public_session_disable_fences_pinned_product",
            pre_b + "test_windows_worker_public_coding_session_reaches_selected_product",
            pre_b + "test_windows_worker_hosted_first_session_reaches_selected_product",
            pre_b
            + "test_windows_worker_public_session_crash_reopens_and_retires_product_attempt[direct]",
            pre_b
            + "test_windows_worker_public_session_crash_reopens_and_retires_product_attempt[hosted]",
            pre_b + "test_windows_worker_native_normal_exit_c5_cleanup_evidence",
        }
        groups = worker_sessions.CASE_GROUPS
        actual = [case for cases in groups.values() for case in cases]
        self.assertEqual(len(actual), len(set(actual)))
        self.assertEqual(set(actual), expected)
        workflow = (ROOT / ".github/workflows/windows-shell-compatibility.yml").read_text()
        self.assertNotIn("  windows-worker-pr-extra:", workflow)
        self.assertIn("  windows-worker-gc-crash:", workflow)
        matrix = dict(
            (group, int(count))
            for group, count in re.findall(
                r"- group: (\w+)\n\s+expected_count: (\d+)", workflow
            )
        )
        self.assertEqual(
            matrix,
            {"direct": 1, "recovery_hosted": 2, "recovery_direct": 2, "lifecycle": 12},
        )
        self.assertEqual(set(matrix), set(groups))

        update_gc = pre_b + "test_windows_worker_update_gc_keeps_selected_revision"
        gc_job = workflow.split("  windows-worker-gc-normal:", 1)[1].split(
            "\n  windows-worker-gc-crash:", 1
        )[0]
        shell_job = workflow.split("  windows-shell:", 1)[1].split(
            "\n  summary:", 1
        )[0]
        self.assertIn(update_gc, gc_job)
        self.assertIn('LOUSHANG_WINDOWS_BACKEND_REVIEW: "1"', gc_job)
        self.assertIn("--deselect=" + update_gc, shell_job)
        self.assertEqual(sum(matrix.values()), 17)
        self.assertEqual(worker_sessions.PR_CASES, {
            "query": (pre_b + "test_windows_worker_hosted_first_session_reaches_selected_product",)
        })
        smoke = workflow.split("  windows-pr-smoke:", 1)[1].split("  windows-worker:", 1)[0]
        self.assertNotIn("test_windows_worker_hosted_first_session_reaches_selected_product", smoke)
        self.assertIn("--require-tests-count 2", smoke)

    def test_pr_ordinary_package_change_selects_only_owner_units(self):
        for path, package in (
            ("src/loushang/ai/pricing.py", "ai"),
            ("src/loushang/agent/agent_loop.py", "agent"),
            ("src/loushang/coding/compaction.py", "coding"),
            ("src/loushang/harness/tools/core.py", "harness"),
            ("tests/coding/test_compaction_core.py", "coding"),
            ("tests/work/test_package_boundaries.py", "work"),
        ):
            with self.subTest(path=path):
                plan = selector.select([path], pr_fast=True)
                self.assertEqual(plan["unit_packages"], [package])
                self.assertEqual(
                    len(plan["unit_jobs"]),
                    selector.MODULE_SHARD_COUNTS.get(package, 1),
                )
                self.assertFalse(plan["checks"]["coding"])
                self.assertFalse(plan["checks"]["host_runtime"])
                self.assertTrue(plan["workflows"]["units"])

    def test_pr_multi_package_change_keeps_each_owner(self):
        plan = selector.select(
            ["src/loushang/ai/pricing.py", "src/loushang/coding/compaction.py"],
            pr_fast=True,
        )
        self.assertEqual(plan["unit_packages"], ["ai", "coding"])

    def test_pr_mixed_coding_risk_uses_full_package_once(self):
        plan = selector.select(
            ["src/loushang/coding/compaction.py", "src/loushang/coding/lsp/client.py"],
            pr_fast=True,
        )
        self.assertTrue(plan["checks"]["coding"])
        self.assertIn("coding", plan["unit_packages"])
        self.assertEqual(sum(job["package"] == "coding" for job in plan["unit_jobs"]), 4)
        self.assertEqual(len(plan["unit_jobs"]), 4)

    def test_pr_session_change_adds_resume_turn_e2e(self):
        plan = selector.select(["src/loushang/harness/session/queue.py"], pr_fast=True)
        self.assertEqual(plan["unit_packages"], ["harness"])
        self.assertTrue(plan["workflows"]["e2e"])

    def test_pr_platform_sources_keep_existing_gates(self):
        for path in (
            "src/loushang/ai/types.py",
            "src/loushang/foundation/json.py",
            "src/loushang/coding/package_product_worker_registered_recovery.py",
            "src/loushang/coding/lsp/client.py",
            "src/loushang/tui/terminal_backends/windows.py",
            "src/loushang/coding/ui/plain_renderer.py",
            "src/loushang/coding/schemas/session.json",
        ):
            with self.subTest(path=path):
                plan = selector.select([path], pr_fast=True)
                self.assertEqual(plan["checks"], selector.select([path])["checks"])
                self.assertTrue({
                    module
                    for check, module in selector.CHECK_MODULE_REGRESSIONS.items()
                    if plan["checks"][check]
                } <= set(plan["unit_packages"]))

    def test_pr_gate_change_exercises_new_reusable_workflows(self):
        for path in ("scripts/ci/windows_worker_session_cases.py",):
            with self.subTest(path=path):
                plan = selector.select([path], pr_fast=True)
                self.assertTrue({"agent", "coding", "foundation"}
                                <= set(plan["unit_packages"]))
                self.assertTrue(plan["unit_jobs"])
                self.assertTrue(plan["e2e"])
                self.assertTrue(all(plan["checks"].values()))

    def test_full_validation_disables_fast_route(self):
        plan = selector.select(["src/loushang/ai/pricing.py"], full=True, pr_fast=True)
        self.assertTrue({"agent", "coding", "foundation"}
                        <= set(plan["unit_packages"]))
        self.assertTrue(all(plan["checks"].values()))

    def test_full_targeted_shards_isolate_measured_heavy_files_without_more_jobs(self):
        heavy = selector.FULL_TARGETED_EXCLUSIVE_PATHS[
            ("ubuntu-24.04", "integration")
        ]
        companions = {
            f"tests/coding/test_companion_{index}.py"
            for index in range(32)
        }
        cases = {
            (path, "ubuntu-24.04", "integration")
            for path in {*heavy, *companions}
        }

        full = selector.make_targeted_jobs(cases, full=True)
        self.assertLessEqual(len(full), selector.FULL_TARGETED_SHARDS["ubuntu-24.04"])
        for path in heavy:
            self.assertEqual(
                [job["paths"] for job in full if path in job["paths"]],
                [[path]],
            )
        self.assertEqual(
            {path for job in full for path in job["paths"]},
            {*heavy, *companions},
        )
        self.assertEqual(sum(len(job["paths"]) for job in full), len(cases))

        ordinary = selector.make_targeted_jobs(cases, full=False)
        self.assertEqual(len(ordinary), 1)
        self.assertEqual(set(ordinary[0]["paths"]), {*heavy, *companions})
        self.assertEqual(ordinary[0]["timeout_minutes"], 30)

    def test_unit_inventory_is_explicit_existing_and_unique(self):
        inventory = json.loads((ROOT / "scripts/ci/unit-tests.json").read_text())
        self.assertTrue(inventory)
        for package, paths in inventory.items():
            with self.subTest(package=package):
                self.assertRegex(package, r"^[a-z][a-z0-9_]*$")
                self.assertTrue(paths)
                self.assertEqual(paths, sorted(set(paths)))
                for path in paths:
                    self.assertTrue(path.startswith("tests/"))
                    self.assertTrue((ROOT / path).is_file(), path)

    def test_fast_unit_jobs_run_complete_offline_package_directories(self):
        workflow = (ROOT / ".github/workflows/package-unit-quality.yml").read_text()
        self.assertIn("include: ${{ fromJSON(inputs.plan).unit_jobs }}", workflow)
        self.assertIn("--shard ${{ matrix.shard }} --shards ${{ matrix.shards }}", workflow)
        self.assertIn("verify_module_report.py", workflow)
        self.assertIn("include: ${{ fromJSON(inputs.plan).targeted_jobs }}", workflow)
        self.assertIn(
            'name: "Targeted ${{ matrix.category }} '
            '(${{ matrix.os }} #${{ matrix.id }})"',
            workflow,
        )
        self.assertIn("TARGET_TEST_PATHS_JSON: ${{ toJSON(matrix.paths) }}", workflow)
        self.assertIn("uv run python scripts/ci/run_targeted_tests.py", workflow)
        self.assertIn("verify_pytest_xml.py", workflow)
        self.assertIn("--allow-skipped", workflow)
        self.assertIn("--required-files-json", workflow)
        self.assertNotIn("matrix.allow_skipped", workflow)
        for package in ("ai", "agent", "coding", "harness", "harnesstui", "tui"):
            with self.subTest(package=package):
                command = runner.commands("unit_" + package)[-1]
                classified = runner.module_unit_paths(package, root=ROOT)
                if classified is None:
                    self.assertIn("tests/" + package, command)
                else:
                    separately_owned = set()
                    if package == "coding":
                        inventories = selector.make_paths()
                        separately_owned = {
                            path
                            for name in (
                                "HARNESSTUI_TEST_PATHS",
                                "CODING_TUI_PRODUCT_TEST_PATHS",
                            )
                            for path in inventories[name]
                            if path.startswith("tests/coding/")
                        }
                    for path in classified:
                        if path in separately_owned:
                            self.assertNotIn(path, command)
                        else:
                            self.assertIn(path, command)
                self.assertIn("not e2e_smoke", command[command.index("-m") + 1])
                self.assertIn("--skip-host-runtime", command)
        (coding_shard,) = runner.commands("unit_coding", shard=0, shards=4)
        self.assertIn("--ci-shard-count", coding_shard)
        self.assertIn("--ignore=tests/coding/test_screen_coding_tui_app.py", coding_shard)
        (plugin,) = runner.commands("unit_plugin")
        self.assertIn("tests/harness/plugin_authoring/test_public_sdk.py", plugin)

    def test_schedule_and_manual_dispatch_are_full(self):
        for event in ("schedule", "workflow_dispatch"):
            self.assertEqual(selector.event_paths(event, {}), ([], True))
        with self.assertRaises(ValueError):
            selector.event_paths("unknown", {})

    def test_push_event_uses_pr_route_while_schedule_is_full(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event_file = root / "event.json"
            event_file.write_text("{}")
            for event, paths, event_full in (
                ("push", ["src/loushang/ai/pricing.py"], False),
                ("schedule", [], True),
            ):
                with self.subTest(event=event):
                    output = root / "output"
                    output.write_text("")
                    with (
                        patch.object(selector, "event_paths", return_value=(paths, event_full)),
                        patch.object(sys, "argv", ["select_checks.py", "--event"]),
                        patch.dict(os.environ, {
                            "GITHUB_EVENT_NAME": event,
                            "GITHUB_EVENT_PATH": str(event_file),
                            "GITHUB_OUTPUT": str(output),
                            "GITHUB_STEP_SUMMARY": str(root / "summary"),
                        }),
                        contextlib.redirect_stdout(io.StringIO()),
                    ):
                        selector.main()
                    plan = json.loads(output.read_text().removeprefix("plan="))
                    if event == "push":
                        self.assertEqual(plan["unit_packages"], ["ai"])
                        self.assertTrue(plan["e2e"])
                        self.assertFalse(plan["windows"]["worker_full"])
                    else:
                        self.assertTrue(all(plan["checks"].values()))
                        self.assertTrue(plan["windows"]["worker_full"])


class PauseTests(unittest.TestCase):
    def test_windows_shell_pause_applies_to_pr_push_and_full_validation(self):
        for full, fast in ((False, True), (True, True), (True, False), (False, False)):
            with self.subTest(full=full, fast=fast):
                plan = selector.select([".github/workflows/windows-shell-compatibility.yml",
                                        ".github/workflows/new.yml"],
                                       full=full, pr_fast=fast)
                self.assertFalse(plan["workflows"]["windows-shell"])
                self.assertFalse(selector.workflow_plan(plan)["workflows"]["windows-shell"])
                # Other selected jobs remain required and fail closed.
                with contextlib.redirect_stdout(io.StringIO()):
                    guard.verify(plan, {"windows-shell": {"result": "skipped"},
                                        "apphost": {"result": "success"}},
                                 {"windows-shell": "windows-shell", "apphost": "apphost"},
                                 section="workflows")
                with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
                    guard.verify(plan, {"windows-shell": {"result": "skipped"},
                                        "apphost": {"result": "failure"}},
                                 {"windows-shell": "windows-shell", "apphost": "apphost"},
                                 section="workflows")

    def test_long_gates_pause_but_complete_module_regressions_remain(self):
        for full, fast in ((False, True), (True, True), (True, False)):
            with self.subTest(full=full, fast=fast):
                plan = selector.select([".github/workflows/new.yml"], full=full, pr_fast=fast)
                self.assertTrue(all(not plan["workflows"][w] for w in selector.PAUSED_WORKFLOWS))
                self.assertTrue({"harness", "hosting", "appservice", "appserver"}
                                <= set(plan["unit_packages"]))
                self.assertEqual(sum(j["package"] == "harness" for j in plan["unit_jobs"]), 4)
                self.assertTrue(plan["workflows"]["units"])
                self.assertTrue(plan["e2e"])
                self.assertTrue(plan["workflows"]["apphost"])
                self.assertTrue({"agent", "coding", "foundation"}
                                <= set(plan["unit_packages"]))



class GateTests(unittest.TestCase):
    def test_reused_gate_requires_all_jobs_skipped(self):
        plan = {"version": 1, "workflows": {"e2e": True}}
        with contextlib.redirect_stdout(io.StringIO()):
            guard.verify(plan, {"e2e": {"result": "skipped"}}, {"e2e": "e2e"},
                         section="workflows", reused=True)
        for result in ("success", "failure", "cancelled", None):
            with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
                guard.verify(plan, {"e2e": {"result": result}}, {"e2e": "e2e"},
                             section="workflows", reused=True)
        with self.assertRaises(ValueError):
            guard.verify({"version": 1, "checks": {}}, {}, {}, reused=True)

    def verify(self, selected, result):
        with contextlib.redirect_stdout(io.StringIO()):
            guard.verify(
                {"version": 1, "checks": {"ai": selected}},
                {"ai-tests": {"result": result}},
                {"ai-tests": "ai"},
            )

    def test_selected_success_and_intentional_skip_pass(self):
        self.verify(True, "success")
        self.verify(False, "skipped")

    def test_selected_failure_cancellation_missing_and_skip_fail(self):
        for result in ("failure", "cancelled", "skipped", None, ""):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.verify(True, result)

    def test_false_or_malformed_green_is_rejected(self):
        for selected, result in (
            (False, "success"),
            (False, "failure"),
            (None, "skipped"),
            ("false", "skipped"),
        ):
            with (
                self.subTest(selected=selected, result=result),
                self.assertRaises(ValueError),
            ):
                self.verify(selected, result)

    def test_missing_job_is_rejected(self):
        with self.assertRaises(ValueError):
            guard.verify({"version": 1, "checks": {"ai": True}}, {}, {"ai-tests": "ai"})

    def test_missing_plan_is_rejected(self):
        with self.assertRaises(ValueError):
            guard.verify({}, {}, {})

    def test_mixed_appservice_windows_job_must_match_its_own_selection(self):
        plan = {
            "version": 1,
            "checks": {"appservice": True},
            "windows": {"appservice_full": False},
        }
        jobs = {"quality": "appservice", "native": "windows.appservice_full"}
        needs = {"quality": {"result": "success"}, "native": {"result": "skipped"}}
        with contextlib.redirect_stdout(io.StringIO()):
            guard.verify(plan, needs, jobs)
        needs["native"]["result"] = "success"
        with self.assertRaises(ValueError):
            guard.verify(plan, needs, jobs)

    def test_failed_selector_cannot_pass_top_level_gate(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/ci/verify_gate.py"),
                "--section",
                "workflows",
                "--require-changes",
                "--jobs",
                "{}",
            ],
            env={
                **os.environ,
                "CI_PLAN": json.dumps(selector.select([])),
                "CI_NEEDS": json.dumps({"changes": {"result": "failure"}}),
            },
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("change selection failed", completed.stderr)

    def test_reusable_workflow_gate_has_no_selector_job(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/ci/verify_gate.py"),
                "--section", "workflows",
                "--jobs", '{"resume-turn":"e2e"}',
            ],
            env={
                **os.environ,
                "CI_PLAN": json.dumps({"version": 1, "workflows": {"e2e": True}}),
                "CI_NEEDS": json.dumps({"resume-turn": {"result": "success"}}),
            },
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class SuiteSelectionTests(unittest.TestCase):
    def assert_non_overlapping_test_paths(self, paths):
        roots = [Path(path.split("::", 1)[0]) for path in paths]
        for index, left in enumerate(roots):
            for right in roots[index + 1:]:
                self.assertFalse(
                    left.is_relative_to(right) or right.is_relative_to(left),
                    f"overlapping pytest collection paths: {left}, {right}",
                )

    def test_apphost_inventory_collects_the_whole_package_without_overlap(self):
        paths = selector.make_paths()["APPHOST_TEST_PATHS"]
        self.assertEqual(paths.count("tests/apphost"), 1)
        self.assert_non_overlapping_test_paths(paths)

    def test_collection_overlap_guard_uses_path_boundaries_in_both_orders(self):
        parent = "tests/apphost"
        child = "tests/apphost/test_launcher.py"
        for paths in ((parent, child), (child, parent)):
            with self.subTest(paths=paths), self.assertRaises(AssertionError):
                self.assert_non_overlapping_test_paths(paths)
        self.assert_non_overlapping_test_paths(
            (parent, "tests/apphost_extra/test_launcher.py")
        )

    def test_apphost_directory_keeps_launcher_and_sibling_consumer_routing(self):
        service_paths = selector.make_paths()["APPSERVICE_TEST_PATHS"]
        self.assertIn("tests/apphost/test_launcher.py", service_paths)
        paths = sorted((ROOT / "tests/apphost").glob("test_*.py"))
        self.assertTrue(paths)
        for path in paths:
            relative = path.relative_to(ROOT).as_posix()
            checks = selector.select([relative])["checks"]
            with self.subTest(path=relative):
                self.assertTrue(checks["apphost"])
                if relative in service_paths:
                    self.assertTrue(checks["appservice"])

    def test_coding_backend_excludes_the_separately_owned_ui_inventory(self):
        (command,) = runner.commands("coding")
        self.assertIn("--ignore=tests/coding/test_screen_coding_tui_app.py", command)
        for path in (
            "tests/coding/test_ui_import_boundaries.py",
            "tests/coding/test_screen_coding_tui_app.py",
            "tests/coding/test_prompt_command.py",
        ):
            self.assertNotIn(path, command)
        plan = selector.select(["src/loushang/coding/lsp/client.py"])
        (host_command,) = runner.commands("host_runtime", plan=plan)
        self.assertIn(
            "--ignore=tests/coding/test_screen_coding_tui_app.py", host_command
        )

    def test_coding_module_matrix_partitions_the_complete_offline_suite(self):
        self.assertFalse((ROOT / ".github/workflows/package-quality.yml").exists())
        self.assertEqual(selector.MODULE_SHARD_COUNTS["coding"], 4)
        plan = selector.select(["src/loushang/coding/lsp/client.py"], pr_fast=True)
        self.assertEqual(plan["unit_packages"], ["coding"])
        self.assertEqual(
            plan["unit_jobs"],
            [{"package": "coding", "shard": index, "shards": 4}
             for index in range(4)],
        )
        original, = runner.commands("coding")
        for index in range(4):
            with self.subTest(shard=index):
                sharded, = runner.commands("coding", shard=index, shards=4)
                self.assertEqual(
                    sharded[:-6], original
                )
                self.assertEqual(
                    sharded[-6:],
                    ["-p", "pytest_shard", "--ci-shard-index", str(index),
                     "--ci-shard-count", "4"],
                )
        with self.assertRaises(ValueError):
            runner.commands("coding", shard=4, shards=4)
        with self.assertRaises(ValueError):
            runner.commands("agent", shard=0, shards=4)
        nodeids = [f"tests/coding/test_example.py::test_case[{index}]" for index in range(100)]
        groups = [
            {nodeid for nodeid in nodeids if shard_hash.shard_for_nodeid(nodeid, 4) == index}
            for index in range(4)
        ]
        self.assertEqual(set().union(*groups), set(nodeids))
        self.assertEqual(sum(map(len, groups)), len(nodeids))

    def test_coding_risk_and_ordinary_prs_use_the_same_offline_inventory(self):
        plan = selector.select([
            "src/loushang/coding/package_product_worker_windows_crash_cleanup_review.py"
        ], pr_fast=True)
        self.assertIn("coding", plan["unit_packages"])
        self.assertEqual(sum(job["package"] == "coding" for job in plan["unit_jobs"]), 4)
        self.assertNotIn("packages", plan["workflows"])
        ordinary, = runner.commands("unit_coding", shard=0, shards=4)
        risk, = runner.commands("coding", plan=plan, shard=0, shards=4)
        self.assertEqual(risk, ordinary)
        self.assertIn("tests/examples/test_coding_examples.py", risk)
        full, = runner.commands("coding")
        self.assertIn("tests/examples/test_coding_examples.py", full)
        self.assertNotIn("not e2e_smoke", full[full.index("-m") + 1])

    def test_ai_quality_executes_each_owned_example_test_once(self):
        makefile = (ROOT / "Makefile").read_text()
        check_ai = makefile.split("check-ai:", 1)[1].split("\ncheck-harness:", 1)[0]
        self.assertNotIn("check-ai-examples", check_ai)
        coverage = check_ai.split("check-ai-coverage:", 1)[1]
        self.assertEqual(coverage.count("tests/examples/test_ai_examples.py"), 1)
        self.assertEqual(coverage.count("tests/examples/test_auth_examples.py"), 1)
        self.assertNotIn("tests/examples -q", coverage)
        for nodeid in (
            "tests/ai/test_auth_api.py::test_login_returns_session_without_opening_browser",
            "tests/ai/test_auth_oauth_lifecycle.py::test_real_authlib_login_store_resolve_refresh_lifecycle",
        ):
            self.assertEqual(makefile.count(f"--deselect={nodeid}"), 1)
        self.assertEqual(makefile.count("$(AI_TARGETED_DESELECTS)"), 1)
        self.assertNotIn("$(AI_TARGETED_DESELECTS)", coverage)

    def test_full_host_runtime_keeps_the_original_repository_wide_collection(self):
        (command,) = runner.commands(
            "host_runtime", plan=selector.select([], full=True)
        )
        self.assertIn("tests", command)

    def test_pr_host_runtime_uses_two_explicit_smokes_and_checks_xml(self):
        plan = selector.select(
            ["src/loushang/coding/package_product_worker_windows_crash_cleanup_review.py"],
            pr_fast=True,
        )
        self.assertTrue(plan["host_runtime_smoke"])
        (command,) = runner.commands("host_runtime", plan=plan)
        self.assertEqual(
            [item for item in command if "::test_" in item],
            [runner.HOST_RUNTIME_PR_CASES["coding"],
             runner.HOST_RUNTIME_PR_CASES["hosting"]],
        )
        self.assertIn("--junitxml=.artifacts/host-runtime-pr-smoke.xml", command)
        workflow = (ROOT / ".github/workflows/host-runtime-quality.yml").read_text()
        self.assertIn("verify_pytest_xml.py", workflow)
        self.assertIn("fromJSON(inputs.plan).host_runtime_smoke", workflow)

    def test_pr_host_runtime_keeps_full_native_test_and_gate_coverage(self):
        for path in (
            "tests/coding/test_package_worker_candidate_wheel.py",
            "tests/hosting/test_posix_release_launcher.py",
            "tests/harness/transcript/test_file_store_process_exit.py",
            ".github/workflows/host-runtime-quality.yml",
        ):
            with self.subTest(path=path):
                plan = selector.select([path], pr_fast=True)
                self.assertFalse(plan["host_runtime_smoke"])
        plan = selector.select([], full=True, pr_fast=True)
        self.assertFalse(plan["host_runtime_smoke"])

    def test_pr_linux_worker_uses_one_hosted_session_without_losing_full_suite(self):
        worker = selector.select(
            ["src/loushang/coding/package_product_worker_windows_crash_cleanup_review.py"],
            pr_fast=True,
        )
        self.assertTrue(worker["hosting_worker_pr_smoke"])
        for path in (
            "src/loushang/hosting/_posix_process.py",
            "tests/hosting/test_posix_release_launcher.py",
            "tests/coding/test_package_worker_candidate_wheel.py",
            ".github/workflows/hosting-quality.yml",
        ):
            with self.subTest(path=path):
                self.assertFalse(selector.select([path], pr_fast=True)["hosting_worker_pr_smoke"])
        self.assertFalse(selector.select([], full=True, pr_fast=True)["hosting_worker_pr_smoke"])
        workflow = (ROOT / ".github/workflows/hosting-quality.yml").read_text()
        self.assertIn("fromJSON(inputs.plan).hosting_worker_pr_smoke", workflow)
        self.assertIn("--require-tests-count 1", workflow)
        self.assertIn("--require-tests-count 4", workflow)
        self.assertIn(
            "test_explicit_worker_hosted_first_session_reaches_installed_product",
            workflow,
        )

    def test_coding_host_runtime_does_not_collect_harness_tests(self):
        plan = selector.select(["src/loushang/coding/lsp/client.py"])
        (command,) = runner.commands("host_runtime", plan=plan)
        self.assertIn("tests/coding", command)
        self.assertNotIn("tests/harness", command)
        self.assertNotIn("--skip-host-runtime", command)
        self.assertIn("requires_host_runtime and not live", command)

    def test_scoped_host_runtime_can_have_no_marked_cases(self):
        plan = selector.select(["src/loushang/tui/terminal_session.py"])
        self.assertTrue(plan["checks"]["host_runtime"])
        with patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=5),
        ) as run:
            runner.run("host_runtime", plan=plan)
        run.assert_called_once()
        self.assertEqual(
            run.call_args.kwargs["env"]["PYTHONPATH"].split(os.pathsep)[0],
            str(ROOT / "src"),
        )

    def test_full_host_runtime_keeps_empty_collection_as_failure(self):
        plan = selector.select([], full=True)
        with patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=5),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                runner.run("host_runtime", plan=plan)

    def test_harnesstui_split_preserves_the_original_test_inventory(self):
        variables = selector.make_paths()
        original = set(
            variables["HARNESSTUI_TEST_PATHS"]
            + variables["CODING_TUI_PRODUCT_TEST_PATHS"]
        )
        core = {
            path
            for path in runner.commands("harnesstui")[-1]
            if path.startswith("tests/")
        }
        coding = {
            path
            for path in runner.commands("coding_ui")[-1]
            if path.startswith("tests/")
        }
        self.assertFalse(core & coding)
        self.assertEqual(core | coding, original)
        combined = {
            path
            for path in runner.commands("harnesstui_all")[-1]
            if path.startswith("tests/")
        }
        self.assertEqual(combined, original)

    def test_harnesstui_reuses_selected_tui_and_harness_package_owners(self):
        tui_plan = selector.select(["src/loushang/tui/input.py"], pr_fast=True)
        tui_command = runner.commands("harnesstui", plan=tui_plan)[-1]
        tui_combined = runner.commands("harnesstui_all", plan=tui_plan)[-1]
        self.assertTrue(tui_plan["checks"]["tui_unit"])
        self.assertFalse(any(path.startswith("tests/tui/") for path in tui_command))
        self.assertFalse(any(path.startswith("tests/tui/") for path in tui_combined))
        self.assertIn("tests/harness/session/test_footer.py", tui_command)
        self.assertIn("tests/coding/test_ui_controller.py", tui_combined)

        harness_plan = selector.select(
            ["src/loushang/harness/session/footer.py"], pr_fast=True
        )
        harness_command = runner.commands("harnesstui", plan=harness_plan)[-1]
        harness_combined = runner.commands(
            "harnesstui_all", plan=harness_plan
        )[-1]
        self.assertIn("harness", harness_plan["unit_packages"])
        self.assertFalse(
            any(path.startswith("tests/harness/") for path in harness_command)
        )
        self.assertFalse(
            any(path.startswith("tests/harness/") for path in harness_combined)
        )
        self.assertIn("tests/coding/test_ui_controller.py", harness_combined)

    def test_harnesstui_only_route_keeps_shared_consumer_contracts(self):
        plan = selector.select(
            ["src/loushang/harnesstui/surface/transcript.py"], pr_fast=True
        )
        command = runner.commands("harnesstui", plan=plan)[-1]
        self.assertFalse(plan["checks"]["tui_unit"])
        self.assertNotIn("harness", plan["unit_packages"])
        self.assertIn("tests/tui/test_launch.py", command)
        self.assertIn("tests/harness/session/test_footer.py", command)

    def test_harnesstui_workflow_passes_the_selection_plan_to_runner(self):
        workflow = (ROOT / ".github/workflows/harnesstui-quality.yml").read_text()
        self.assertIn("CI_PLAN: ${{ inputs.plan }}", workflow)
        self.assertIn("run_checks.py harnesstui_all", workflow)
        self.assertIn("--junitxml=.artifacts/harnesstui-all.xml", workflow)

    def test_offline_suites_keep_provider_and_native_tests_out(self):
        for scope in ("agent", "coding", "foundation", "tui_unit"):
            (command,) = runner.commands(scope)
            self.assertIn("scripts/dev/run_pytest.py", command)
            self.assertIn("--skip-host-runtime", command)
            self.assertIn("not live", command[command.index("-m") + 1])


class GitRangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "CI routing test")
        self.git("config", "user.email", "ci@example.invalid")
        self.commit_file("base", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        return (
            subprocess.check_output(
                ["git", *args], cwd=self.root, env=env, stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )

    def commit_file(self, path, content):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
        self.git("add", "--", path)
        self.git("-c", "commit.gpgsign=false", "commit", "-m", "fixture")

    def test_pr_diff_excludes_unrelated_base_branch_commits(self):
        self.git("checkout", "-b", "topic")
        self.commit_file("docs/change.md", "topic")
        head = self.git("rev-parse", "HEAD")
        self.git("checkout", "main")
        self.commit_file("src/loushang/ai/types.py", "unrelated main change")
        base = self.git("rev-parse", "HEAD")
        paths, full = selector.event_paths(
            "pull_request",
            {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}},
            root=self.root,
        )
        self.assertEqual(paths, ["docs/change.md"])
        self.assertFalse(full)

    def test_push_checks_the_whole_pushed_range(self):
        self.commit_file("one", "one")
        self.commit_file("two", "two")
        paths, full = selector.event_paths(
            "push",
            {"before": self.base, "after": self.git("rev-parse", "HEAD")},
            root=self.root,
        )
        self.assertEqual(paths, ["one", "two"])
        self.assertFalse(full)

    def test_rename_preserves_both_owners_and_unusual_filenames(self):
        old = "src/loushang/ai/旧 文件.py"
        # Windows forbids control characters in filenames; retain spaces and
        # Unicode there, while POSIX still exercises newline-delimited hazards.
        new = "docs/new 名称.md" if os.name == "nt" else "docs/new\nname.md"
        self.commit_file(old, "same contents")
        base = self.git("rev-parse", "HEAD")
        (self.root / "docs").mkdir()
        self.git("mv", "--", old, new)
        self.git("-c", "commit.gpgsign=false", "commit", "-m", "rename")
        paths = selector.changed_paths(base, "HEAD", root=self.root)
        self.assertEqual(set(paths), {old, new})
        self.assertTrue(selector.select(paths)["checks"]["ai"])

    def test_local_plan_includes_staged_unstaged_and_untracked_changes(self):
        (self.root / "base").write_text("changed")
        (self.root / "staged").write_text("staged")
        self.git("add", "staged")
        (self.root / "untracked").write_text("untracked")
        self.assertEqual(
            selector.local_paths("main", root=self.root),
            ["base", "staged", "untracked"],
        )

    def test_missing_base_fails_instead_of_selecting_nothing(self):
        with self.assertRaises(subprocess.CalledProcessError):
            selector.changed_paths("missing", "HEAD", root=self.root)


class WorkflowContractTests(unittest.TestCase):
    def test_only_one_workflow_owns_pr_push_and_schedule_triggers(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text()
            if path.name == "quality.yml":
                self.assertIn("  pull_request:", text)
                self.assertIn("  schedule:", text)
            else:
                self.assertNotRegex(text, r"(?m)^  (pull_request|push|schedule):")
                self.assertIn("  workflow_call:", text)

    def test_reusable_jobs_are_guarded_and_use_the_single_root_aggregate(self):
        rules = json.loads((ROOT / "scripts/ci/check-scopes.json").read_text())
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            if path.name == "quality.yml":
                continue
            text = path.read_text()
            jobs = {
                job: f"{section}.{scope}" if section != "checks" else scope
                for job, section, scope in re.findall(
                    r"^  ([\w-]+):\n    if: \$\{\{ fromJSON\(inputs.plan\).(checks|windows|workflows).([\w-]+)(?: [^}]*)? \}\}",
                    text,
                    re.M,
                )
            }
            all_jobs = set(
                re.findall(r"^  ([\w-]+):", text.split("\njobs:\n")[1], re.M)
            )
            self.assertNotIn("selected-checks:", text)
            if path.name in {"package-unit-quality.yml", "e2e-smoke-quality.yml"}:
                # Dynamic module matrices and the multiline E2E condition are
                # covered by their dedicated selection tests below.
                continue
            self.assertEqual(all_jobs, set(jobs), path.name)
            workflow_scopes = selector.SCOPED_WORKFLOWS[path.relative_to(ROOT).as_posix()]
            allowed_checks = {
                check for scope in workflow_scopes
                for check in rules["workflows"][scope]
            }
            for section_scope in jobs.values():
                section, separator, scope = section_scope.partition(".")
                if separator:
                    if section == "windows":
                        self.assertEqual(workflow_scopes, ("windows-shell",))
                    else:
                        self.assertEqual(section, "workflows", path.name)
                        self.assertEqual(workflow_scopes, (scope,), path.name)
                else:
                    self.assertIn(section, allowed_checks, path.name)

    def test_appservice_historical_jobs_are_grouped_by_capability(self):
        text = (ROOT / ".github/workflows/appservice-quality.yml").read_text()
        jobs = set(re.findall(r"^  ([\w-]+):", text.split("\njobs:\n")[1], re.M))
        self.assertEqual(jobs, {"native-service", "installed-service"})
        for historical in (
            "  g16-native-evidence:", "  g16-wheel-evidence:",
            "  g17-darwin-native:", "  g17-darwin-primitives:",
            "  g17-wheel-evidence:", "  g17-windows-native:",
            "  appservice-quality:", "  selected-checks:",
        ):
            self.assertNotIn(historical, text)
        self.assertEqual(text.count("build --wheel"), 1)
        self.assertIn("run_g16_installed_evidence.py", text)
        self.assertIn("run_g17_installed_evidence.py", text)
        self.assertIn("--require-tests-count 2", text)
        self.assertNotIn("make check-appservice", text)
        self.assertEqual(text.count("timeout-minutes: 15"), 2)
        self.assertEqual(text.count("if-no-files-found: error"), 2)

    def test_documentation_runs_in_selector_before_the_unified_gate(self):
        text = (ROOT / ".github/workflows/quality.yml").read_text()
        changes = text.split("\n  changes:\n", 1)[1].split("\n  architecture:\n", 1)[0]
        self.assertIn("python scripts/ci/check_docs.py --plan-env", changes)
        self.assertIn("CI_PLAN: ${{ steps.select.outputs.plan }}", changes)
        for name in (
            "Architecture documentation",
            "ai-quality",
            "harness-quality",
            "harnesstui-quality",
            "tui-cross-platform-contracts",
        ):
            self.assertNotIn(f"    name: {name}\n", text)
        self.assertIn("    name: quality-gate\n    if: always()", text)
        mapping = json.loads(re.search(r"--jobs '(.*)'", text)[1])
        self.assertEqual(set(mapping), set(selector.select([])["workflows"]))
        summary = text.split("\n  quality-gate:\n")[1]
        needs = re.search(r"    needs: \[(.*)\]", summary)[1]
        self.assertEqual(set(needs.split(", ")), set(mapping) | {"changes"})


class DocumentationTests(unittest.TestCase):
    def test_missing_link_is_caught_without_importing_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "README.md"
            path.write_text(
                "[missing](missing.md)\n[external](https://example.invalid)\n"
            )
            self.assertEqual(len(docs.check_links(path, root=root)), 1)

    def test_directory_and_encoded_space_links_are_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "folder").mkdir()
            (root / "file name.md").write_text("content")
            path = root / "README.md"
            path.write_text("[folder](folder/)\n[file](file%20name.md)\n")
            self.assertEqual(docs.check_links(path, root=root), [])


if __name__ == "__main__":
    unittest.main()
