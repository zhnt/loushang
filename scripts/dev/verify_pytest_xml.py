#!/usr/bin/env python3
"""Fail closed when a required pytest XML report is empty or non-passing."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--require-property",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="require a testsuite property; repeat for multiple properties",
    )
    return parser


def verify_report(report: Path, required_properties: tuple[str, ...] = ()) -> str:
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
    for key in ("skipped", "failures", "errors"):
        if counts[key] != 0:
            problems.append(f"{key} must be zero, got {counts[key]}")

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
        summary = verify_report(args.report, tuple(args.require_property))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"required pytest report passed: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
