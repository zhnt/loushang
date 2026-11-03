from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ci"))

commands = importlib.import_module("run_checks").commands
select = importlib.import_module("select_checks").select
catalog_module = importlib.import_module("test_catalog")
all_targeted_test_cases = catalog_module.all_targeted_test_cases
target_paths = importlib.import_module("run_targeted_tests").target_paths
load_catalog = catalog_module.load_catalog
module_unit_paths = catalog_module.module_unit_paths
module_targeted_nodeids = catalog_module.module_targeted_nodeids
module_is_fully_classified = catalog_module.module_is_fully_classified
targeted_node_owner = catalog_module.targeted_node_owner
targeted_test_cases = catalog_module.targeted_test_cases
CATALOG_VERSION = catalog_module.CATALOG_VERSION


class CatalogTests(unittest.TestCase):
    def test_reviewed_modules_cover_their_complete_current_test_directories(self):
        catalog = load_catalog(ROOT)
        self.assertEqual(catalog["version"], CATALOG_VERSION)
        self.assertEqual(set(catalog["modules"]), {
            "channel", "resource", "work", "agent", "harnesswork", "method",
            "foundation", "ontology", "appserver", "appservice",
        })
        for module, entry in catalog["modules"].items():
            discovered = {
                p.relative_to(ROOT).as_posix()
                for p in (ROOT / "tests" / module).rglob("test_*.py")
            }
            discovered.update(catalog_module.MODULE_EXTRA_TESTS.get(module, []))
            self.assertEqual(set(entry["files"]), discovered)

    def test_pure_test_changes_do_not_schedule_product_integration_or_e2e(self):
        for path in ("tests/resource/test_frontmatter.py", "tests/channel/test_host.py",
                     "tests/channel/test_session_work_adapter.py", "tests/work/test_runtime.py",
                     "tests/work/test_event_log.py", "tests/agent/test_proxy.py",
                     "tests/agent/test_agent_loop.py", "tests/examples/test_agent_examples.py",
                     "tests/examples/test_ai_examples.py",
                     "tests/protocols/test_protocol_contracts.py",
                     "tests/coding/test_package_product_worker_windows_activation_state.py",
                     "tests/harnesswork/integrations/test_session.py",
                     "tests/ontology/test_typed_query.py",
                     "tests/harnesswork/fixtures/legacy_coding_plan.jsonl",
                     "tests/harnesswork/fixtures/legacy_coding_plan_projection.json",
                     "tests/method/test_method_loader.py", "tests/method/test_runtime.py",
                     "tests/foundation/test_json_contract.py",
                     "tests/foundation/observability/test_sinks.py",
                     "tests/harness/workspace/test_exec_capture.py",
                     "tests/hosting/test_posix_release_launcher.py",
                     "tests/apphost/test_launcher.py",
                     "tests/appserver/test_connection_protocol.py",
                     "tests/appserver/fixtures/execution_v1.json",
                     "tests/appservice/test_execution_guard.py"):
            with self.subTest(path=path):
                plan = select([path], root=ROOT, pr_fast=True)
                self.assertFalse(plan["e2e"])
                self.assertEqual([k for k, enabled in plan["checks"].items() if enabled], ["docs"])
                self.assertEqual([k for k, enabled in plan["workflows"].items() if enabled], ["units"])
                self.assertFalse(plan["targeted_tests"])

    def test_mixed_source_test_and_shared_fixture_changes_keep_necessary_coverage(self):
        test = "tests/resource/test_frontmatter.py"
        for change in ("src/loushang/resource/frontmatter.py", "tests/conftest.py",
                       "tests/coding/test_pr_smoke.py"):
            with self.subTest(change=change):
                self.assertTrue(select([test, change], root=ROOT, pr_fast=True)["e2e"])
        unknown = select(["tests/coding/test_new_integration.py"], root=ROOT, pr_fast=True)
        self.assertFalse(unknown["e2e"])
        self.assertEqual(unknown["unit_packages"], ["coding"])
        self.assertEqual(
            [name for name, enabled in unknown["workflows"].items() if enabled],
            ["units"],
        )
        for targeted in (
            "tests/appserver/test_local.py",
            "tests/appserver/_stdio_child.py",
            "tests/appserver/test_local_record_windows.py",
            "tests/appservice/test_continuity.py",
            "tests/appservice/test_local_deployment.py",
        ):
            with self.subTest(targeted=targeted):
                plan = select([targeted], root=ROOT, pr_fast=True)
                self.assertFalse(plan["e2e"])
                self.assertTrue(plan["targeted_tests"])
                self.assertTrue(plan["targeted_jobs"])
                self.assertTrue(plan["workflows"]["units"])
                self.assertFalse(plan["module_tests"])
        fixture = "tests/harnesswork/fixtures/legacy_coding_plan.jsonl"
        self.assertTrue(select([fixture, "src/loushang/harnesswork/runtime.py"], root=ROOT, pr_fast=True)["e2e"])
        self.assertTrue(select([fixture, "tests/conftest.py"], root=ROOT, pr_fast=True)["e2e"])
        self.assertTrue(select(["tests/harnesswork/fixtures/new_shared.json"], root=ROOT, pr_fast=True)["e2e"])

    def test_classified_module_runner_has_static_checks_and_full_reviewed_set(self):
        for module in (
            "channel", "resource", "work", "agent", "harnesswork", "method",
            "foundation", "appserver", "appservice",
        ):
            planned = commands(f"unit_{module}", root=ROOT)
            self.assertEqual(len(planned), 2)
            self.assertIn("ruff", planned[0])
            for path in module_unit_paths(module, root=ROOT):
                self.assertIn(path, planned[1])
                self.assertEqual(planned[1].count(path), 1)
            self.assertIn("--skip-host-runtime", planned[1])
            self.assertIn("--strict-markers", planned[1])
            self.assertIn("not live", planned[1][planned[1].index("-m") + 1])

    def test_new_unclassified_file_and_deleted_stale_file_fail_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts/ci").mkdir(parents=True)
            (root / "tests/demo").mkdir(parents=True)
            file = root / "tests/demo/test_one.py"
            file.write_text("def test_one(): pass\n")
            catalog = {"version": CATALOG_VERSION, "modules": {"demo": {
                "complete": True, "files": {"tests/demo/test_one.py": {
                    "category": "unit", "assertion": "one behavior"}}}}}
            (root / "scripts/ci/test-classification.json").write_text(json.dumps(catalog))
            self.assertIsNotNone(module_unit_paths("demo", root=root))
            extra = root / "tests/demo/test_new.py"
            extra.write_text("def test_new(): pass\n")
            with self.assertRaisesRegex(ValueError, "missing=.*test_new"):
                load_catalog(root)
            extra.unlink()
            file.unlink()
            with self.assertRaisesRegex(ValueError, "stale=.*test_one"):
                load_catalog(root)

    def test_owned_extra_tests_are_required_and_directory_extras_expand_to_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts/ci").mkdir(parents=True)
            (root / "tests/demo").mkdir(parents=True)
            (root / "tests/contracts").mkdir(parents=True)
            files = ["tests/demo/test_one.py", "tests/contracts/test_extra.py"]
            for file in files:
                (root / file).write_text("def test_example(): pass\n")
            entry = {"complete": True, "files": {
                file: {"category": "contract", "assertion": "reviewed behavior"} for file in files}}
            path = root / "scripts/ci/test-classification.json"
            path.write_text(json.dumps({"version": CATALOG_VERSION, "modules": {"demo": entry}}))
            with patch.dict(catalog_module.MODULE_EXTRA_TESTS, {"demo": ["tests/contracts"]}):
                self.assertEqual(module_unit_paths("demo", root=root), sorted(files))
                entry["files"].pop(files[1])
                path.write_text(json.dumps({"version": CATALOG_VERSION, "modules": {"demo": entry}}))
                with self.assertRaisesRegex(ValueError, "missing=.*test_extra"):
                    load_catalog(root)
            with patch.dict(catalog_module.MODULE_EXTRA_TESTS, {"demo": ["tests/absent.py"]}):
                with self.assertRaisesRegex(ValueError, "missing module regression"):
                    load_catalog(root)

    def test_classified_directory_extras_are_not_collected_again(self):
        paths = ["tests/ai/test_auth.py", "tests/protocols/test_protocol_contracts.py",
                 "tests/examples/test_ai_examples.py", "tests/examples/test_auth_examples.py"]
        with (
            patch("run_checks.module_unit_paths", return_value=paths),
            patch("run_checks.module_is_fully_classified", return_value=True),
        ):
            command = commands("unit_ai", root=ROOT)[-1]
        self.assertNotIn("tests/protocols", command)
        for path in paths:
            self.assertEqual(command.count(path), 1)

    def test_dedicated_fixture_requires_existing_path_and_reviewed_consumers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts/ci").mkdir(parents=True)
            (root / "tests/demo").mkdir(parents=True)
            test = "tests/demo/test_one.py"
            fixture = "tests/demo/golden.json"
            (root / test).write_text("def test_one(): pass\n")
            (root / fixture).write_text("{}")
            role = {"category": "contract", "assertion": "golden contract", "consumers": [test]}
            entry = {"complete": True, "files": {test: {
                "category": "unit", "assertion": "one behavior"}}, "fixtures": {fixture: role}}
            path = root / "scripts/ci/test-classification.json"
            def write():
                path.write_text(json.dumps({"version": CATALOG_VERSION, "modules": {"demo": entry}}))
            write()
            self.assertEqual(catalog_module.reviewed_unit_owner(fixture, catalog=load_catalog(root)), "demo")
            self.assertEqual(module_unit_paths("demo", root=root), [test])
            for consumers in ([], ["tests/other/test_two.py"], [test, test], test):
                role["consumers"] = consumers
                write()
                with self.subTest(consumers=consumers), self.assertRaises(ValueError):
                    load_catalog(root)
            role["consumers"] = [test]
            write()
            (root / fixture).unlink()
            with self.assertRaisesRegex(ValueError, "missing dedicated fixture"):
                load_catalog(root)

    def test_schema_and_category_errors_do_not_create_an_empty_green_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts/ci").mkdir(parents=True)
            path = root / "scripts/ci/test-classification.json"
            for catalog in ([], {"version": CATALOG_VERSION + 1, "modules": {}},
                            {"version": CATALOG_VERSION, "modules": {"demo": []}},
                            {"version": CATALOG_VERSION, "modules": {"demo": {"complete": False}}},
                            {"version": CATALOG_VERSION, "modules": {"demo": {"complete": True, "files": {}}}}):
                with self.subTest(catalog=catalog):
                    path.write_text(json.dumps(catalog))
                    with self.assertRaises(ValueError):
                        load_catalog(root)

    def test_targeted_files_complete_inventory_without_entering_module_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts/ci").mkdir(parents=True)
            (root / "tests/demo").mkdir(parents=True)
            unit = "tests/demo/test_unit.py"
            integration = "tests/demo/test_integration.py"
            (root / unit).write_text("def test_unit(): pass\n")
            (root / integration).write_text("def test_integration(): pass\n")
            catalog = {"version": CATALOG_VERSION, "modules": {"demo": {
                "complete": True,
                "files": {
                    unit: {"category": "unit", "assertion": "isolated behavior"},
                    integration: {"category": "integration", "assertion": "service boundary",
                                  "platforms": ["ubuntu-24.04"]},
                },
            }}}
            (root / "scripts/ci/test-classification.json").write_text(
                json.dumps(catalog)
            )
            loaded = load_catalog(root)
            self.assertEqual(module_unit_paths("demo", root=root), [unit])
            self.assertTrue(module_is_fully_classified("demo", root=root))
            self.assertEqual(catalog_module.reviewed_unit_owner(
                unit, catalog=loaded
            ), "demo")
            self.assertIsNone(catalog_module.reviewed_unit_owner(
                integration, catalog=loaded
            ))
            self.assertEqual(
                targeted_test_cases(integration, catalog=loaded),
                [(integration, catalog["modules"]["demo"]["files"][integration])],
            )

            helper = "tests/demo/integration_child.py"
            (root / helper).write_text("pass\n")
            catalog["modules"]["demo"]["fixtures"] = {helper: {
                "category": "integration",
                "assertion": "subprocess fixture",
                "platforms": ["ubuntu-24.04"],
                "consumers": [integration],
            }}
            (root / "scripts/ci/test-classification.json").write_text(
                json.dumps(catalog)
            )
            loaded = load_catalog(root)
            self.assertIsNone(catalog_module.reviewed_unit_owner(
                helper, catalog=loaded
            ))
            self.assertEqual(
                targeted_test_cases(helper, catalog=loaded)[0][0], integration
            )
            for invalid in (
                {"category": "integration", "assertion": "missing runners"},
                {"category": "platform", "assertion": "unknown runner",
                 "platforms": ["unknown-os"]},
                {"category": "unit", "assertion": "unit cannot select runners",
                 "platforms": ["ubuntu-24.04"]},
            ):
                catalog["modules"]["demo"]["files"][integration] = invalid
                (root / "scripts/ci/test-classification.json").write_text(
                    json.dumps(catalog)
                )
                with self.subTest(invalid=invalid), self.assertRaisesRegex(
                    ValueError, "platforms"
                ):
                    load_catalog(root)

    def test_partial_targeted_overrides_shrink_only_reviewed_module_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts/ci").mkdir(parents=True)
            (root / "tests/demo").mkdir(parents=True)
            unit = "tests/demo/test_unit.py"
            integration = "tests/demo/test_integration.py"
            for path in (unit, integration):
                (root / path).write_text("def test_case(): pass\n")
            role = {
                "category": "integration",
                "assertion": "reviewed real service boundary",
                "platforms": ["ubuntu-24.04"],
            }
            catalog = {
                "version": CATALOG_VERSION,
                "modules": {},
                "targeted_overrides": {
                    "demo": {"review": "incremental", "files": {integration: role}}
                },
            }
            (root / "scripts/ci/test-classification.json").write_text(
                json.dumps(catalog)
            )
            loaded = load_catalog(root)
            self.assertEqual(module_unit_paths("demo", root=root), [unit])
            self.assertFalse(module_is_fully_classified("demo", root=root))
            self.assertIsNone(catalog_module.reviewed_unit_owner(
                unit, catalog=loaded
            ))
            self.assertEqual(
                targeted_test_cases(integration, catalog=loaded),
                [(integration, role)],
            )

            (root / integration).unlink()
            with self.assertRaisesRegex(ValueError, "missing targeted override"):
                load_catalog(root)

    def test_reviewed_coding_integration_overrides_leave_unknown_tests_conservative(self):
        unit_paths = module_unit_paths("coding", root=ROOT)
        self.assertIsNotNone(unit_paths)
        self.assertFalse(module_is_fully_classified("coding", root=ROOT))
        self.assertIn("tests/coding/test_agent_session_runtime.py", unit_paths)
        for mixed in (
            "tests/coding/arch/test_activation.py",
            "tests/coding/test_bootstrap.py",
            "tests/coding/test_cli.py",
            "tests/coding/test_lmux_command.py",
            "tests/coding/test_lmux_selector.py",
            "tests/coding/test_lmux_stop_all.py",
            "tests/coding/test_package_materializer.py",
            "tests/coding/test_resume_activation_plan.py",
            "tests/coding/test_tool_registry.py",
        ):
            self.assertIn(mixed, unit_paths)
        reviewed = "tests/coding/test_package_cutover_cli.py"
        self.assertNotIn(reviewed, unit_paths)
        plan = select([reviewed], root=ROOT, pr_fast=True)
        self.assertFalse(plan["e2e"])
        self.assertFalse(plan["module_tests"])
        self.assertEqual(
            [(job["paths"], job["os"], job["category"])
             for job in plan["targeted_jobs"]],
            [([reviewed], "ubuntu-24.04", "integration")],
        )

    def test_mixed_file_nodes_run_separately_without_losing_unit_nodes(self):
        mixed = "tests/coding/arch/test_activation.py"
        nodeids = module_targeted_nodeids("coding", root=ROOT)
        selected = [nodeid for nodeid in nodeids if nodeid.startswith(mixed + "::")]
        self.assertEqual(len(selected), 5)
        self.assertIn(mixed, module_unit_paths("coding", root=ROOT))

        catalog = load_catalog(ROOT)
        self.assertEqual(targeted_node_owner(mixed, catalog=catalog), "coding")
        self.assertEqual(
            {nodeid for nodeid, _role in targeted_test_cases(mixed, catalog=catalog)},
            set(selected),
        )

        command = commands("unit_coding", root=ROOT)[-1]
        for nodeid in selected:
            self.assertIn(f"--deselect={nodeid}", command)
        self.assertIn(mixed, command)

        plan = select([mixed], root=ROOT, pr_fast=True)
        self.assertFalse(plan["e2e"])
        self.assertTrue(plan["module_tests"])
        self.assertEqual(plan["unit_packages"], ["coding"])
        self.assertEqual(
            {path for job in plan["targeted_jobs"] for path in job["paths"]},
            set(selected),
        )

    def test_ai_loopback_nodes_have_exact_ubuntu_integration_owners(self):
        auth_api = (
            "tests/ai/test_auth_api.py::"
            "test_login_returns_session_without_opening_browser"
        )
        lifecycle = (
            "tests/ai/test_auth_oauth_lifecycle.py::"
            "test_real_authlib_login_store_resolve_refresh_lifecycle"
        )
        expected = {auth_api, lifecycle}
        self.assertEqual(set(module_targeted_nodeids("ai", root=ROOT)), expected)

        command = commands("unit_ai", root=ROOT)[-1]
        for nodeid in expected:
            self.assertIn(f"--deselect={nodeid}", command)

        plan = select(
            ["tests/ai/test_auth_api.py"], root=ROOT, pr_fast=True
        )
        self.assertEqual(plan["unit_packages"], ["ai"])
        self.assertFalse(plan["e2e"])
        self.assertEqual(
            [(job["paths"], job["os"], job["category"])
             for job in plan["targeted_jobs"]],
            [([auth_api], "ubuntu-24.04", "integration")],
        )

        source_plan = select(
            ["src/loushang/ai/pricing.py"], root=ROOT, pr_fast=True
        )
        self.assertEqual(
            {path for job in source_plan["targeted_jobs"] for path in job["paths"]},
            expected,
        )
        self.assertEqual(
            {(job["os"], job["category"]) for job in source_plan["targeted_jobs"]},
            {("ubuntu-24.04", "integration")},
        )

    def test_targeted_node_schema_rejects_missing_nodes_and_whole_file_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts/ci").mkdir(parents=True)
            (root / "tests/demo").mkdir(parents=True)
            test = "tests/demo/test_mixed.py"
            (root / test).write_text(
                "def test_unit(): pass\nasync def test_integration(): pass\n"
            )
            role = {
                "category": "integration",
                "assertion": "reviewed slow boundary",
                "platforms": ["ubuntu-24.04"],
                "nodes": ["test_integration"],
            }
            catalog = {
                "version": CATALOG_VERSION,
                "modules": {},
                "targeted_overrides": {},
                "targeted_nodes": {
                    "demo": {"review": "incremental", "files": {test: role}}
                },
            }
            catalog_path = root / "scripts/ci/test-classification.json"
            catalog_path.write_text(json.dumps(catalog))
            loaded = load_catalog(root)
            self.assertEqual(module_targeted_nodeids("demo", root=root), [
                f"{test}::test_integration"
            ])
            self.assertEqual(targeted_node_owner(test, catalog=loaded), "demo")

            role["nodes"] = ["test_missing"]
            catalog_path.write_text(json.dumps(catalog))
            with self.assertRaisesRegex(ValueError, "missing targeted test nodes"):
                load_catalog(root)

            role["nodes"] = ["test_integration"]
            catalog["targeted_overrides"] = {
                "demo": {"review": "whole", "files": {test: {
                    "category": "integration",
                    "assertion": "whole file",
                    "platforms": ["ubuntu-24.04"],
                }}}
            }
            catalog_path.write_text(json.dumps(catalog))
            with self.assertRaisesRegex(ValueError, "overlaps whole-file"):
                load_catalog(root)

    def test_full_validation_runs_every_offline_targeted_owner(self):
        catalog = load_catalog(ROOT)
        expected = {
            (path, platform, role["category"])
            for path, role in all_targeted_test_cases(catalog=catalog)
            for platform in role["platforms"]
        }
        plan = select([], root=ROOT, full=True, pr_fast=True)
        actual = {
            (path, job["os"], job["category"])
            for job in plan["targeted_jobs"]
            for path in job["paths"]
        }
        self.assertEqual(actual, expected)
        self.assertLess(len(plan["targeted_jobs"]), len(expected))
        self.assertTrue(plan["targeted_tests"])
        self.assertTrue(plan["workflows"]["units"])
        for heavy in (
            "tests/coding/test_package_cutover_cli.py",
            "tests/coding/test_package_external_data_wheel.py",
            "tests/coding/test_package_worker_candidate_wheel.py",
        ):
            with self.subTest(heavy=heavy):
                self.assertEqual(
                    [job["paths"] for job in plan["targeted_jobs"]
                     if heavy in job["paths"]],
                    [[heavy]],
                )

    def test_targeted_batch_paths_are_json_and_repository_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test = root / "tests/demo/test_example.py"
            test.parent.mkdir(parents=True)
            test.write_text("def test_case(): pass\n")
            self.assertEqual(
                target_paths(
                    json.dumps(["tests/demo/test_example.py::test_case"]),
                    root=root,
                ),
                ["tests/demo/test_example.py::test_case"],
            )
            for invalid in (
                "",
                "null",
                "[]",
                '["tests/demo/test_example.py", "tests/demo/test_example.py"]',
                '["../test_example.py"]',
                '["tests/demo/missing.py"]',
            ):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    target_paths(invalid, root=root)


if __name__ == "__main__":
    unittest.main()
