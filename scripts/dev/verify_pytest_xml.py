#!/usr/bin/env python3
"""Fail closed when a required pytest XML report is empty or non-passing."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--allow-skipped",
        action="store_true",
        help="allow platform-inapplicable skips while still requiring a passed test",
    )
    parser.add_argument(
        "--require-property",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="require a testsuite property; repeat for multiple properties",
    )
    parser.add_argument(
        "--require-tests-count",
        type=int,
        metavar="N",
        help="require exactly N collected tests in the report",
    )
    parser.add_argument(
        "--required-files-json",
        default="[]",
        metavar="JSON",
        help="require at least one passing testcase from every listed test file",
    )
    return parser


def verify_report(
    report: Path,
    required_properties: tuple[str, ...] = (),
    *,
    allow_skipped: bool = False,
    required_tests_count: int | None = None,
    required_files: tuple[str, ...] = (),
) -> str:
    try:
        root = ET.parse(report).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"cannot read pytest XML report {report}: {error}") from error

    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError(f"pytest XML report {report} has no testsuite")

    counts = {
        key: sum(_integer_attribute(suite, key, report) for suite in suites)
        for key in ("tests", "skipped", "failures", "errors")
    }
    problems: list[str] = []
    if counts["tests"] <= 0:
        problems.append("tests must be greater than zero")
    if required_tests_count is not None:
        if required_tests_count <= 0:
            problems.append("required tests count must be greater than zero")
        elif counts["tests"] != required_tests_count:
            problems.append(
                f"tests must be {required_tests_count}, got {counts['tests']}"
            )
    for key in ("failures", "errors"):
        if counts[key] != 0:
            problems.append(f"{key} must be zero, got {counts[key]}")
    if counts["skipped"] != 0 and not allow_skipped:
        problems.append(f"skipped must be zero, got {counts['skipped']}")
    if allow_skipped and counts["tests"] - counts["skipped"] <= 0:
        problems.append("at least one test must pass when skipped tests are allowed")

    passed_cases = {
        (case.get("classname", ""), case.get("name", ""))
        for suite in suites
        for case in suite.findall("testcase")
        if case.find("skipped") is None
        and case.find("failure") is None
        and case.find("error") is None
    }
    for required in required_files:
        parts = required.split("::")
        owner = Path(parts[0]).with_suffix("").as_posix().replace("/", ".")
        if len(parts) == 1:
            matched = any(
                classname == owner or classname.startswith(owner + ".")
                for classname, _name in passed_cases
            )
        elif len(parts) == 2:
            matched = any(
                classname == owner
                and (name == parts[1] or name.startswith(parts[1] + "["))
                for classname, name in passed_cases
            )
        elif len(parts) == 3:
            matched = any(
                classname == f"{owner}.{parts[1]}"
                and (name == parts[2] or name.startswith(parts[2] + "["))
                for classname, name in passed_cases
            )
        else:
            matched = False
        if not matched:
            problems.append(f"required test target has no passing case: {required}")

    properties = {
        (item.get("name") or ""): item.get("value") or ""
        for suite in suites
        for item in suite.findall("./properties/property")
    }
    for requirement in required_properties:
        name, separator, expected = requirement.partition("=")
        if not separator or not name:
            problems.append(
                f"invalid property requirement {requirement!r}; expected NAME=VALUE"
            )
        elif properties.get(name) != expected:
            problems.append(
                f"required property {name!r} must be {expected!r}, "
                f"got {properties.get(name)!r}"
            )

    summary = ", ".join(f"{key}={value}" for key, value in counts.items())
    if problems:
        raise ValueError(f"required pytest report failed ({summary}): {'; '.join(problems)}")
    return summary


def _integer_attribute(suite: ET.Element, name: str, report: Path) -> int:
    raw = suite.get(name, "0")
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(
            f"pytest XML report {report} has invalid {name}={raw!r}"
        ) from error


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        required_files = json.loads(args.required_files_json)
        if (
            not isinstance(required_files, list)
            or not all(isinstance(path, str) and path for path in required_files)
        ):
            raise ValueError("required files must be a JSON string list")
        summary = verify_report(
            args.report,
            tuple(args.require_property),
            allow_skipped=args.allow_skipped,
            required_tests_count=args.require_tests_count,
            required_files=tuple(required_files),
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"required pytest report passed: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
