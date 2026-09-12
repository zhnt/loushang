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

    def test_generated_document_rechecks_source_facts(self):
        self.assertEqual(
            self.selected(
                "docs/internals/architecture/generated/current-package-dependencies.md"
            ),
            {"docs", "architecture"},
        )

    def test_empty_changes_do_not_start_product_checks(self):
        self.assertEqual(self.selected(), {"docs"})

    def test_schedule_and_manual_dispatch_are_full(self):
        for event in ("schedule", "workflow_dispatch"):
            self.assertEqual(selector.event_paths(event, {}), ([], True))
        with self.assertRaises(ValueError):
            selector.event_paths("unknown", {})


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

    def test_failed_selector_cannot_pass_top_level_gate(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/ci/verify_gate.py"),
                "--section",
                "workflows",
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
            jobs = dict(
                re.findall(
                    r"^  ([\w-]+):\n    if: \$\{\{ fromJSON\(inputs.plan\).checks.(\w+) \}\}",
                    text,
                    re.M,
                )
            )
            mapping = json.loads(re.search(r"--jobs '(.*)'", text)[1])
            self.assertEqual(jobs, mapping, path.name)
            all_jobs = set(
                re.findall(r"^  ([\w-]+):", text.split("\njobs:\n")[1], re.M)
            )
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
                    guard.verify({"version": 1, "checks": {"appservice": True}}, needs, mapping)

    def test_compatibility_contexts_require_the_unified_gate(self):
        text = (ROOT / ".github/workflows/quality.yml").read_text()
        for name in (
            "Architecture documentation",
            "ai-quality",
            "harness-quality",
            "harnesstui-quality",
            "tui-cross-platform-contracts",
        ):
            self.assertIn(
                f"    name: {name}\n    if: always()\n    needs: quality-gate", text
            )
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
