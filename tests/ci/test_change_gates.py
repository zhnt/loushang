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
        plan = selector.select(sorted(selector.PR_ROUTING_FILES), pr_fast=True)
        self.assertEqual(
            {name for name, enabled in plan["checks"].items() if enabled},
            {"docs", "ci"},
        )

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
                self.assertEqual(len(plan["unit_jobs"]), 32)
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
                    for scope in ("smoke", "worker_pr", "worker_pr_extra",
                                  "worker_full", "shell_full", "appservice_full", "tui_full")
                ))

    def test_pr_routing_exception_keeps_build_and_other_ci_files_full(self):
        expected = set(selector.select([], full=True)["checks"])
        for path in (
            "pyproject.toml", ".github/workflows/quality.yml",
            "scripts/ci/run_checks.py", "tests/ci/test_new_gate.py",
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

    def test_pr_code_paths_run_resume_turn_e2e_on_all_platforms(self):
        for path in (
            "src/loushang/ai/pricing.py",
            "src/loushang/ai/types.py",
            "src/loushang/coding/session/agent_session.py",
            "tests/coding/test_hosted_application.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(selector.select([path], pr_fast=True)["e2e"])
        self.assertTrue(selector.select([], full=True, pr_fast=True)["e2e"])
        workflow = (ROOT / ".github/workflows/e2e-smoke-quality.yml").read_text()
        self.assertIn("os: [ubuntu-24.04, macos-15, windows-2022]", workflow)
        self.assertIn("--require-tests-count 1", workflow)
        self.assertIn("uv run python scripts/ci/run_checks.py e2e_smoke", workflow)

    def test_sustained_worker_query_runs_for_its_test_and_full_validation(self):
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
        self.assertTrue(owned_test["checks"]["hosting_sustained"])
        self.assertTrue(full["checks"]["hosting_sustained"])

    def test_empty_changes_do_not_start_product_checks(self):
        self.assertEqual(self.selected(), {"docs"})

    def test_workflow_plan_omits_diagnostic_reasons(self):
        plan = selector.select(["src/loushang/coding/lsp/client.py"])

        compact = selector.workflow_plan(plan)

        self.assertEqual(
            set(compact), {"version", "paths", "checks", "workflows", "unit_packages", "unit_jobs", "e2e", "windows"}
        )
        self.assertEqual(compact["paths"], plan["paths"])
        self.assertEqual(compact["checks"], plan["checks"])
        self.assertEqual(compact["workflows"], plan["workflows"])
        self.assertEqual(compact["unit_packages"], plan["unit_packages"])
        self.assertEqual(compact["unit_jobs"], plan["unit_jobs"])
        self.assertEqual(compact["windows"], plan["windows"])
        self.assertEqual(compact["e2e"], plan["e2e"])
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
        self.assertTrue(worker["smoke"] and worker["worker_pr"] and worker["worker_pr_extra"])
        self.assertEqual(worker["worker_pr_scenario"], "crash")
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
        self.assertFalse(gate["worker_pr"] or gate["worker_pr_extra"])
        self.assertEqual(gate["worker_pr_scenario"], "none")
        full = selector.select([], full=True, pr_fast=True)["windows"]
        self.assertFalse(full["smoke"])
        self.assertFalse(full["worker_pr"] or full["worker_pr_extra"])
        self.assertEqual(full["worker_pr_scenario"], "none")
        self.assertTrue(all(full[name] for name in ("worker_full", "shell_full", "appservice_full", "tui_full")))

    def test_pr_windows_worker_risk_selects_one_extra_or_full_matrix(self):
        cases = (
            ("src/loushang/coding/package_product_worker_windows_launch_intent.py", "none"),
            ("src/loushang/coding/package_product_worker_native_release.py", "none"),
            ("src/loushang/coding/package_product_worker_policy.py", "fence"),
            ("src/loushang/plugin/_coding_local_worker_wheel.py", "none"),
            ("src/loushang/coding/package_product_worker_windows_gc_history.py", "gc_normal"),
            ("src/loushang/coding/package_product_worker_windows_opt_in_owner.py", "fence"),
            ("src/loushang/coding/package_product_worker_windows_activation_state_journal.py", "c5"),
        )
        for path, scenario in cases:
            with self.subTest(path=path):
                windows = selector.select([path], pr_fast=True)["windows"]
                self.assertTrue(windows["worker_pr"])
                self.assertFalse(windows["worker_full"])
                self.assertEqual(windows["worker_pr_scenario"], scenario)
                self.assertEqual(windows["worker_pr_extra"], scenario != "none")
        mixed = selector.select(
            [
                "src/loushang/coding/package_product_worker_windows_crash_cleanup_review.py",
                "src/loushang/coding/package_product_worker_windows_gc_history.py",
            ],
            pr_fast=True,
        )["windows"]
        self.assertTrue(mixed["worker_full"])
        self.assertFalse(mixed["worker_pr"] or mixed["worker_pr_extra"])
        combined_name = selector.select(
            ["src/loushang/coding/package_product_worker_windows_crash_stage_retirement.py"],
            pr_fast=True,
        )["windows"]
        self.assertTrue(combined_name["worker_full"])
        self.assertFalse(combined_name["worker_pr"] or combined_name["worker_pr_extra"])

    def test_windows_worker_session_shards_preserve_every_native_case(self):
        pre_b = worker_sessions.PRE_B
        expected = {
            worker_sessions.ACTIVATION
            + "test_windows_product_c5_state_reopens_and_refuses_complete_record_loss",
            pre_b + "test_windows_public_ordinary_session_preserves_pre_b_without_writing",
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
        self.assertEqual(sum(matrix.values()), 17)
        self.assertEqual(
            {name: len(cases) for name, cases in worker_sessions.PR_CASES.items()},
            {"query": 1, "crash": 1, "gc_normal": 1, "fence": 1, "c5": 1},
        )
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
                    selector.UNIT_SHARD_COUNTS.get(package, 1),
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
        self.assertEqual(plan["unit_packages"], [])
        self.assertEqual(plan["unit_jobs"], [])

    def test_pr_session_change_adds_resume_turn_e2e(self):
        plan = selector.select(["src/loushang/harness/session/queue.py"], pr_fast=True)
        self.assertEqual(plan["unit_packages"], ["harness"])
        self.assertTrue(plan["workflows"]["e2e"])

    def test_pr_platform_and_unclassified_tests_keep_existing_gates(self):
        for path in (
            "src/loushang/ai/types.py",
            "src/loushang/foundation/json.py",
            "src/loushang/coding/package_product_worker_registered_recovery.py",
            "src/loushang/coding/lsp/client.py",
            "src/loushang/tui/terminal_backends/windows.py",
            "src/loushang/coding/ui/plain_renderer.py",
            "src/loushang/coding/schemas/session.json",
            "tests/coding/test_hosted_application.py",
            "tests/coding/test_new_unclassified.py",
        ):
            with self.subTest(path=path):
                plan = selector.select([path], pr_fast=True)
                self.assertEqual(plan["unit_packages"], [])
                self.assertEqual(plan["checks"], selector.select([path])["checks"])

    def test_pr_gate_change_exercises_new_reusable_workflows(self):
        for path in (
            ".github/workflows/quality.yml",
            ".github/workflows/package-quality.yml",
            ".github/workflows/windows-shell-compatibility.yml",
            "scripts/ci/windows_worker_session_cases.py",
        ):
            with self.subTest(path=path):
                plan = selector.select([path], pr_fast=True)
                self.assertEqual(plan["unit_packages"], ["agent"])
                self.assertEqual(
                    plan["unit_jobs"],
                    [{"package": "agent", "shard": 0, "shards": 1}],
                )
                self.assertTrue(plan["e2e"])
                self.assertTrue(all(plan["checks"].values()))

    def test_full_validation_disables_fast_route(self):
        plan = selector.select(["src/loushang/ai/pricing.py"], full=True, pr_fast=True)
        self.assertEqual(plan["unit_packages"], [])
        self.assertTrue(all(plan["checks"].values()))

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
        self.assertIn("verify_pytest_xml.py", workflow)
        for package in ("ai", "agent", "coding", "harness", "harnesstui", "tui"):
            with self.subTest(package=package):
                (command,) = runner.commands("unit_" + package)
                self.assertIn("tests/" + package, command)
                self.assertIn("not e2e_smoke", command[command.index("-m") + 1])
                self.assertIn("--skip-host-runtime", command)
        (coding_shard,) = runner.commands("unit_coding", shard=0, shards=16)
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


class GateTests(unittest.TestCase):
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
        plan = selector.select(["src/loushang/coding/lsp/client.py"])
        (host_command,) = runner.commands("host_runtime", plan=plan)
        self.assertIn(
            "--ignore=tests/coding/test_screen_coding_tui_app.py", host_command
        )

    def test_coding_matrix_partitions_the_complete_existing_offline_suite(self):
        workflow = (ROOT / ".github/workflows/package-quality.yml").read_text()
        coding_job = workflow.split("  coding:\n", 1)[1].split("  foundation:\n", 1)[0]
        self.assertIn(
            "shard: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]",
            coding_job,
        )
        self.assertIn("--shard ${{ matrix.shard }} --shards 16", coding_job)
        self.assertIn("verify_pytest_xml.py", coding_job)
        self.assertIn("--allow-skipped", coding_job)
        original, = runner.commands("coding")
        for index in range(16):
            with self.subTest(shard=index):
                sharded, = runner.commands("coding", shard=index, shards=16)
                self.assertEqual(
                    sharded[:-6], original
                )
                self.assertEqual(
                    sharded[-6:],
                    ["-p", "pytest_shard", "--ci-shard-index", str(index),
                     "--ci-shard-count", "16"],
                )
        with self.assertRaises(ValueError):
            runner.commands("coding", shard=16, shards=16)
        with self.assertRaises(ValueError):
            runner.commands("agent", shard=0, shards=16)
        nodeids = [f"tests/coding/test_example.py::test_case[{index}]" for index in range(100)]
        groups = [
            {nodeid for nodeid in nodeids if shard_hash.shard_for_nodeid(nodeid, 16) == index}
            for index in range(16)
        ]
        self.assertEqual(set().union(*groups), set(nodeids))
        self.assertEqual(sum(map(len, groups)), len(nodeids))

    def test_full_host_runtime_keeps_the_original_repository_wide_collection(self):
        (command,) = runner.commands(
            "host_runtime", plan=selector.select([], full=True)
        )
        self.assertIn("tests", command)

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
        new = "docs/new\nname.md"
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

    def test_reusable_guards_cover_every_expensive_job_with_its_actual_scope(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            if path.name == "quality.yml":
                continue
            text = path.read_text()
            jobs = {
                job: f"{section}.{scope}" if section != "checks" else scope
                for job, section, scope in re.findall(
                    r"^  ([\w-]+):\n    if: \$\{\{ fromJSON\(inputs.plan\).(checks|windows).(\w+) \}\}",
                    text,
                    re.M,
                )
            }
            all_jobs = set(
                re.findall(r"^  ([\w-]+):", text.split("\njobs:\n")[1], re.M)
            )
            single_owner = {
                "architecture-quality.yml": "source-facts",
                "package-unit-quality.yml": "package",
                "e2e-smoke-quality.yml": "resume-turn",
            }.get(path.name)
            if single_owner is not None:
                # The required top-level gate already checks this reusable
                # workflow's result; a second runner adds only queue latency.
                self.assertEqual(all_jobs, {single_owner}, path.name)
                self.assertNotIn("selected-checks:", text)
                continue
            mapping = json.loads(re.search(r"--jobs '(.*)'", text)[1])
            mapped = {
                job: (
                    "windows." + scope
                    if "--section windows" in text and "." not in scope
                    else scope
                )
                for job, scope in mapping.items()
            }
            self.assertEqual(jobs, mapped, path.name)
            self.assertEqual(all_jobs, set(mapping) | {"selected-checks"}, path.name)
            summary = text.split("\n  selected-checks:\n")[1]
            needs = re.search(r"    needs: \[(.*)\]", summary)[1]
            self.assertEqual(set(needs.split(", ")), set(mapping), path.name)
            self.assertIn("    if: always()", text)

    def test_appservice_summary_rejects_each_failed_or_cancelled_g17_family(self):
        text = (ROOT / ".github/workflows/appservice-quality.yml").read_text()
        mapping = json.loads(re.search(r"--jobs '(.*)'", text)[1])
        expected = {"g17-darwin-native", "g17-darwin-primitives",
                    "g17-wheel-evidence", "g17-windows-native"}
        self.assertTrue(expected <= set(mapping))
        for failed in expected:
            for result in ("failure", "cancelled", "skipped"):
                needs = {job: {"result": "success"} for job in mapping}
                needs[failed]["result"] = result
                with self.subTest(job=failed, result=result), self.assertRaises(ValueError):
                    guard.verify(
                        {"version": 1, "checks": {"appservice": True},
                         "windows": {"appservice_full": True}},
                        needs, mapping,
                    )

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
