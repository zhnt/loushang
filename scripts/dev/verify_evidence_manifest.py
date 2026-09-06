#!/usr/bin/env python3
"""Verify one zero-skip JUnit report against an exact evidence manifest row."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import cast

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
        raise ValueError("evidence manifest has invalid top-level fields")
    if manifest["manifestVersion"] != 1:
        raise ValueError("evidence manifest version is unsupported")
    reports = _mapping(manifest, "reports")
    row = reports.get(report_id)
    if not isinstance(row, dict) or set(row) != _REPORT_FIELDS:
        raise ValueError(f"evidence report {report_id!r} is absent or invalid")
    row = cast(dict[str, object], row)
    if row["status"] != "implemented":
        raise ValueError(f"evidence report {report_id!r} is not implemented")
    junit_path = row["junitPath"]
    minimum_tests = row["minimumTests"]
    required_ids = row["requiredCaseIds"]
    if not isinstance(junit_path, str) or report.as_posix() != junit_path:
        raise ValueError(
            f"evidence report path must be {junit_path!r}, got {report.as_posix()!r}"
        )
    if type(minimum_tests) is not int or minimum_tests < 1:
        raise ValueError("evidence minimum test count must be positive")
    if (
        not isinstance(required_ids, list)
        or not required_ids
        or not all(isinstance(item, str) and item for item in required_ids)
        or len(set(required_ids)) != len(required_ids)
    ):
        raise ValueError("evidence required case ids must be a unique nonempty array")

    root = ET.parse(report).getroot()
    suites = _suites(root)
    suite_counts = [_verified_suite_counts(suite) for suite in suites]
    counts = {
        name: sum(item[name] for item in suite_counts)
        for name in ("tests", "skipped", "failures", "errors")
    }
    if root.tag == "testsuites":
        _verify_aggregate_counts(root, counts)
    if counts["tests"] < minimum_tests:
        raise ValueError(
            f"evidence report needs at least {minimum_tests} tests, "
            f"got {counts['tests']}"
        )
    for name in ("skipped", "failures", "errors"):
        if counts[name] != 0:
            raise ValueError(f"evidence report {name} must be zero, got {counts[name]}")

    expected = cast(list[str], required_ids)
    namespaces = {case_id.partition("-")[0] for case_id in expected}
    if "" in namespaces or any("-" not in case_id for case_id in expected):
        raise ValueError("evidence case ids must carry a namespace prefix")
    case_pattern = re.compile(
        r"(?<![A-Z0-9])(?:"
        + "|".join(re.escape(namespace) for namespace in sorted(namespaces))
        + r")-[A-Z0-9]+(?:-[A-Z0-9]+)*(?![A-Z0-9-])"
    )
    observed = []
    for suite in suites:
        for testcase in suite.findall("testcase"):
            name = testcase.get("name", "")
            observed.extend(case_pattern.findall(name))
    if set(observed) != set(expected) or len(observed) != len(expected):
        missing = sorted(set(expected) - set(observed))
        unexpected = sorted(set(observed) - set(expected))
        duplicates = len(observed) - len(set(observed))
        raise ValueError(
            "evidence report case ids mismatch: "
            f"missing={missing}, unexpected={unexpected}, duplicates={duplicates}"
        )
    return ", ".join(f"{name}={value}" for name, value in counts.items())


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read evidence manifest: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("evidence manifest must be an object")
    return cast(dict[str, object], value)


def _mapping(value: Mapping[str, object], name: str) -> dict[str, object]:
    item = value.get(name)
    if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
        raise ValueError(f"evidence manifest {name} must be an object")
    return cast(dict[str, object], item)


def _integer_attribute(element: ET.Element, name: str) -> int:
    raw = element.get(name)
    if raw is None:
        raise ValueError(f"evidence JUnit {name} count is missing")
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"evidence JUnit {name}={raw!r} is invalid") from error
    if value < 0:
        raise ValueError(f"evidence JUnit {name} cannot be negative")
    return value


def _suites(root: ET.Element) -> list[ET.Element]:
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
        if any(child.tag != "testsuite" for child in root):
            raise ValueError("evidence JUnit testsuites has unsupported children")
    else:
        raise ValueError("evidence JUnit root must be testsuite or testsuites")
    if not suites:
        raise ValueError("evidence JUnit report has no testsuite")
    return suites


def _verify_aggregate_counts(
    root: ET.Element,
    counts: dict[str, int],
) -> None:
    aggregate_names = {"tests", "skipped", "failures", "errors"}
    present = aggregate_names & set(root.attrib)
    if present and present != aggregate_names:
        raise ValueError("evidence JUnit aggregate counts are incomplete")
    if present:
        declared = {name: _integer_attribute(root, name) for name in aggregate_names}
        if declared != counts:
            raise ValueError("evidence JUnit aggregate counts do not match children")


def _verified_suite_counts(suite: ET.Element) -> dict[str, int]:
    if suite.findall(".//testsuite"):
        raise ValueError("evidence JUnit nested testsuite is unsupported")
    testcases = list(suite.findall("testcase"))
    observed = {"tests": len(testcases), "skipped": 0, "failures": 0, "errors": 0}
    for testcase in testcases:
        terminals = [
            child.tag
            for child in testcase
            if child.tag in {"skipped", "failure", "error"}
        ]
        if len(terminals) > 1:
            raise ValueError("evidence JUnit testcase has multiple terminal results")
        if terminals:
            plural = {"skipped": "skipped", "failure": "failures", "error": "errors"}
            observed[plural[terminals[0]]] += 1
    declared = {
        name: _integer_attribute(suite, name)
        for name in ("tests", "skipped", "failures", "errors")
    }
    if declared != observed:
        raise ValueError("evidence JUnit suite counts do not match testcase children")
    return observed


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = verify_manifest_report(args.manifest, args.report_id, args.report)
    except (OSError, ET.ParseError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Evidence report passed: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
