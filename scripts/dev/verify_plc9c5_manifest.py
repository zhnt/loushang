#!/usr/bin/env python3
"""Verify one PLC9C5 JUnit report against its exact evidence manifest row."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import cast

_CASE_ID = re.compile(r"C5[1-4]-[A-Z0-9-]+")
_REPORT_FIELDS = {"junitPath", "minimumTests", "requiredCaseIds", "status"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("report_id")
    parser.add_argument("report", type=Path)
    return parser


def verify_manifest_report(manifest_path: Path, report_id: str, report: Path) -> str:
    manifest = _read_json(manifest_path)
    if set(manifest) != {"manifestVersion", "reports"}:
        raise ValueError("PLC9C5 evidence manifest has invalid top-level fields")
    if manifest["manifestVersion"] != 1:
        raise ValueError("PLC9C5 evidence manifest version is unsupported")
    reports = _mapping(manifest, "reports")
    row = reports.get(report_id)
    if not isinstance(row, dict) or set(row) != _REPORT_FIELDS:
        raise ValueError(f"PLC9C5 evidence report {report_id!r} is absent or invalid")
    row = cast(dict[str, object], row)
    if row["status"] != "implemented":
        raise ValueError(f"PLC9C5 evidence report {report_id!r} is not implemented")
    junit_path = row["junitPath"]
    minimum_tests = row["minimumTests"]
    required_ids = row["requiredCaseIds"]
    if not isinstance(junit_path, str) or report.as_posix() != junit_path:
        raise ValueError(
            f"PLC9C5 report path must be {junit_path!r}, got {report.as_posix()!r}"
        )
    if type(minimum_tests) is not int or minimum_tests < 1:
        raise ValueError("PLC9C5 minimum test count must be positive")
    if (
        not isinstance(required_ids, list)
        or not required_ids
        or not all(isinstance(item, str) for item in required_ids)
        or len(set(required_ids)) != len(required_ids)
    ):
        raise ValueError("PLC9C5 required case ids must be a unique nonempty array")

    root = ET.parse(report).getroot()
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
        if any(child.tag != "testsuite" for child in root):
            raise ValueError("PLC9C5 JUnit testsuites has unsupported children")
    else:
        raise ValueError("PLC9C5 JUnit root must be testsuite or testsuites")
    if not suites:
        raise ValueError("PLC9C5 JUnit report has no testsuite")
    suite_counts = [_verified_suite_counts(suite) for suite in suites]
    counts = {
        name: sum(item[name] for item in suite_counts)
        for name in ("tests", "skipped", "failures", "errors")
    }
    if root.tag == "testsuites":
        aggregate_names = {"tests", "skipped", "failures", "errors"}
        present = aggregate_names & set(root.attrib)
        if present and present != aggregate_names:
            raise ValueError("PLC9C5 JUnit aggregate counts are incomplete")
        if present:
            declared = {
                name: _integer_attribute(root, name) for name in aggregate_names
            }
            if declared != counts:
                raise ValueError("PLC9C5 JUnit aggregate counts do not match children")
    if counts["tests"] < minimum_tests:
        raise ValueError(
            f"PLC9C5 report needs at least {minimum_tests} tests, got {counts['tests']}"
        )
    for name in ("skipped", "failures", "errors"):
        if counts[name] != 0:
            raise ValueError(f"PLC9C5 report {name} must be zero, got {counts[name]}")
    observed: list[str] = []
    for suite in suites:
        testcases = list(suite.findall("testcase"))
        for testcase in testcases:
            name = testcase.get("name", "")
            observed.extend(_CASE_ID.findall(name))
    expected = cast(list[str], required_ids)
    if set(observed) != set(expected) or len(observed) != len(expected):
        missing = sorted(set(expected) - set(observed))
        unexpected = sorted(set(observed) - set(expected))
        raise ValueError(
            "PLC9C5 report case ids mismatch: "
            f"missing={missing}, unexpected={unexpected}, duplicates="
            f"{len(observed) - len(set(observed))}"
        )
    return ", ".join(f"{name}={value}" for name, value in counts.items())


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read PLC9C5 evidence manifest: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("PLC9C5 evidence manifest must be an object")
    return cast(dict[str, object], value)


def _mapping(value: Mapping[str, object], name: str) -> dict[str, object]:
    item = value.get(name)
    if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
        raise ValueError(f"PLC9C5 manifest {name} must be an object")
    return cast(dict[str, object], item)


def _integer_attribute(element: ET.Element, name: str) -> int:
    raw = element.get(name)
    if raw is None:
        raise ValueError(f"PLC9C5 JUnit {name} count is missing")
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"PLC9C5 JUnit {name}={raw!r} is invalid") from error
    if value < 0:
        raise ValueError(f"PLC9C5 JUnit {name} cannot be negative")
    return value


def _verified_suite_counts(suite: ET.Element) -> dict[str, int]:
    if suite.findall(".//testsuite"):
        raise ValueError("PLC9C5 JUnit nested testsuite is unsupported")
    testcases = list(suite.findall("testcase"))
    observed = {"tests": len(testcases), "skipped": 0, "failures": 0, "errors": 0}
    for testcase in testcases:
        terminals = [
            child.tag
            for child in testcase
            if child.tag in {"skipped", "failure", "error"}
        ]
        if len(terminals) > 1:
            raise ValueError("PLC9C5 JUnit testcase has multiple terminal results")
        if terminals:
            plural = {"skipped": "skipped", "failure": "failures", "error": "errors"}
            observed[plural[terminals[0]]] += 1
    declared = {
        name: _integer_attribute(suite, name)
        for name in ("tests", "skipped", "failures", "errors")
    }
    if declared != observed:
        raise ValueError("PLC9C5 JUnit suite counts do not match testcase children")
    return observed


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = verify_manifest_report(args.manifest, args.report_id, args.report)
    except (OSError, ET.ParseError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"PLC9C5 evidence report passed: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
