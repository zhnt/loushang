from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ci"))
derive = importlib.import_module("derive_junit").derive


class DerivedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source.xml"
        self.output = Path(self.temp.name) / "derived.xml"

    def write(self, cases: str, *, tests: int, skipped: int = 0, failures: int = 0):
        self.source.write_text(
            f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" '
            f'failures="{failures}" errors="0"><properties>'
            '<property name="backend" value="native"/></properties>'
            f'{cases}</testsuite></testsuites>'
        )

    def test_derives_selected_passes_and_properties_without_executing_tests(self):
        self.write('<testcase classname="owner" name="case[G8-X]" time="2"/>'
                   '<testcase classname="other" name="platform"><skipped/></testcase>',
                   tests=2, skipped=1)
        self.assertEqual(derive(self.source, self.output, classes=["owner"], cases=[],
                                name_contains="G8"), 1)
        suite = ET.parse(self.output).find("testsuite")
        self.assertEqual(suite.get("skipped"), "0")
        self.assertEqual(suite.find("properties/property").get("value"), "native")
        self.assertEqual(suite.find("testcase").get("time"), "2")

    def test_missing_selection_and_required_skips_cannot_produce_evidence(self):
        self.write('<testcase classname="owner" name="case"><skipped/></testcase>',
                   tests=1, skipped=1)
        for classes, cases in ((["owner"], []), (["absent"], []),
                               ([], ["owner::absent"]), ([], [])):
            with self.subTest(classes=classes, cases=cases), self.assertRaises(ValueError):
                derive(self.source, self.output, classes=classes, cases=cases)
        self.assertFalse(self.output.exists())

    def test_failed_unselected_case_still_invalidates_the_source_execution(self):
        self.write('<testcase classname="owner" name="pass"/>'
                   '<testcase classname="other" name="fail"><failure/></testcase>',
                   tests=2, failures=1)
        with self.assertRaisesRegex(ValueError, "source execution"):
            derive(self.source, self.output, classes=["owner"], cases=[])

    def test_duplicate_id_and_inconsistent_counts_fail_closed(self):
        case = '<testcase classname="owner" name="case"/>'
        for cases, count in ((case + case, 2), (case, 2)):
            with self.subTest(cases=cases):
                self.write(cases, tests=count)
                with self.assertRaises(ValueError):
                    derive(self.source, self.output, classes=["owner"], cases=[])

    def test_explicit_case_selection_and_source_protection(self):
        self.write('<testcase classname="worker" name="close"/>'
                   '<testcase classname="worker" name="other"/>', tests=2)
        self.assertEqual(derive(self.source, self.output, classes=[], cases=["worker::close"]), 1)
        with self.assertRaisesRegex(ValueError, "overwrite"):
            derive(self.source, self.source, classes=["worker"], cases=[])


if __name__ == "__main__":
    unittest.main()
