from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ci"))
verify = importlib.import_module("verify_module_report").verify
CATALOG_VERSION = importlib.import_module("test_catalog").CATALOG_VERSION


class ModuleReportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "scripts/ci").mkdir(parents=True)
        (self.root / "tests/demo").mkdir(parents=True)
        files = ["tests/demo/test_one.py", "tests/demo/test_two.py"]
        for file in files:
            (self.root / file).write_text("def test_case(): pass\n")
        catalog = {"version": CATALOG_VERSION, "modules": {"demo": {
            "complete": True, "files": {file: {
                "category": "unit", "assertion": "necessary behavior"} for file in files}}}}
        (self.root / "scripts/ci/test-classification.json").write_text(json.dumps(catalog))
        (self.root / "scripts/ci/unit-tests.json").write_text(json.dumps({"demo": [], "legacy": []}))
        self.report = self.root / "report.xml"

    def write(self, *, cases: str | None = None, tests: int = 2,
              skipped: int = 0, failures: int = 0):
        if cases is None:
            cases = ('<testcase classname="tests.demo.test_one" name="test_case"/>'
                     '<testcase classname="tests.demo.test_two.Suite" name="test_case"/>')
        self.report.write_text(
            f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" '
            f'failures="{failures}" errors="0">{cases}</testsuite></testsuites>')

    def test_complete_reviewed_report_and_parameterized_class_cases_pass(self):
        self.write()
        self.assertIn("tests=2", verify("demo", self.report, root=self.root))

    def test_reviewed_skip_fails_even_when_another_case_passes(self):
        self.write(cases='<testcase classname="tests.demo.test_one" name="test_case"/>'
                        '<testcase classname="tests.demo.test_two" name="test_case"><skipped/></testcase>',
                   skipped=1)
        with self.assertRaisesRegex(ValueError, "must not skip"):
            verify("demo", self.report, root=self.root)
        self.assertIn("skipped=1", verify("legacy", self.report, root=self.root))

    def test_partial_classification_retains_platform_skip_allowance(self):
        catalog = {
            "version": CATALOG_VERSION,
            "modules": {},
            "targeted_overrides": {
                "demo": {
                    "review": "incremental",
                    "files": {
                        "tests/demo/test_two.py": {
                            "category": "platform",
                            "assertion": "native platform behavior",
                            "platforms": ["windows-2022"],
                        }
                    },
                }
            },
        }
        (self.root / "scripts/ci/test-classification.json").write_text(
            json.dumps(catalog)
        )
        self.write(
            cases=(
                '<testcase classname="tests.demo.test_one" name="test_pass"/>'
                '<testcase classname="tests.demo.test_one" name="test_platform">'
                "<skipped/></testcase>"
            ),
            skipped=1,
        )
        self.assertIn("skipped=1", verify("demo", self.report, root=self.root))

        self.write(
            cases=(
                '<testcase classname="tests.demo.test_one" name="test_platform">'
                "<skipped/></testcase>"
            ),
            tests=1,
            skipped=1,
        )
        with self.assertRaisesRegex(ValueError, "no passing tests"):
            verify("demo", self.report, root=self.root)

    def test_missing_file_fails_but_valid_shard_does_not_claim_other_files(self):
        self.write(cases='<testcase classname="tests.demo.test_one" name="test_case"/>', tests=1)
        with self.assertRaisesRegex(ValueError, "files are missing"):
            verify("demo", self.report, root=self.root)
        self.assertIn("tests=1", verify("demo", self.report, root=self.root, shards=2))

    def test_forged_counts_empty_and_failed_reports_cannot_pass(self):
        rows = [dict(tests=99), dict(cases="", tests=0),
                dict(cases='<testcase classname="tests.demo.test_one" name="test_case"><failure/></testcase>',
                     tests=1, failures=1)]
        for row in rows:
            with self.subTest(row=row):
                self.write(**row)
                with self.assertRaises(ValueError):
                    verify("demo", self.report, root=self.root)

    def test_duplicates_and_unowned_results_cannot_replace_required_cases(self):
        for classname in ("tests.demo.test_one", "tests.other.test_two"):
            with self.subTest(classname=classname):
                self.write(cases='<testcase classname="tests.demo.test_one" name="test_case"/>'
                                 f'<testcase classname="{classname}" name="test_case"/>')
                with self.assertRaises(ValueError):
                    verify("demo", self.report, root=self.root)

    def test_missing_report_unknown_module_and_invalid_shard_fail(self):
        with self.assertRaises(OSError):
            verify("demo", self.report, root=self.root)
        for module, shards in (("typo", 1), ("demo", 0)):
            with self.subTest(module=module, shards=shards), self.assertRaises(ValueError):
                verify(module, self.report, root=self.root, shards=shards)


if __name__ == "__main__":
    unittest.main()
