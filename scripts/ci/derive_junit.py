"""Derive evidence from one execution; never rerun tests to obtain another report."""
from __future__ import annotations

import argparse
import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def derive(source: Path, output: Path, *, classes: list[str],
           cases: list[str], name_contains: str | None = None) -> int:
    if source.resolve() == output.resolve():
        raise ValueError("derived report must not overwrite its source")
    if not classes and not cases:
        raise ValueError("an explicit test selection is required")
    root = ET.parse(source).getroot()
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites" and all(child.tag == "testsuite" for child in root):
        suites = list(root)
    else:
        raise ValueError("unsupported JUnit structure")
    if not suites:
        raise ValueError("source has no test suite")
    result = ET.Element("testsuites")
    seen: set[str] = set()
    matched_classes: set[str] = set()
    matched_cases: set[str] = set()
    count = 0
    totals = {key: 0 for key in ("tests", "skipped", "failures", "errors")}
    for suite in suites:
        if suite.findall(".//testsuite"):
            raise ValueError("nested suites are unsupported")
        observed = dict.fromkeys(totals, 0)
        derived = ET.Element("testsuite", {"name": suite.get("name", "pytest")})
        properties = suite.find("properties")
        if properties is not None:
            derived.append(copy.deepcopy(properties))
        for case in suite.findall("testcase"):
            observed["tests"] += 1
            terminals = [tag for tag in ("skipped", "failure", "error") if case.find(tag) is not None]
            if len(terminals) > 1:
                raise ValueError("multiple testcase terminal results")
            if terminals:
                observed[{"skipped": "skipped", "failure": "failures", "error": "errors"}[terminals[0]]] += 1
            if case.find("failure") is not None or case.find("error") is not None:
                raise ValueError("source execution has failures or errors")
            classname, name = case.get("classname", ""), case.get("name", "")
            if not classname or not name:
                raise ValueError("testcase identity is missing")
            identity = f"{classname}::{name}"
            if identity in seen:
                raise ValueError(f"duplicate testcase: {identity}")
            seen.add(identity)
            selected = classname in classes or identity in cases
            selected = selected and (name_contains is None or name_contains in name)
            if selected:
                if terminals:
                    raise ValueError(f"required testcase did not pass: {identity}")
                matched_classes.add(classname)
                matched_cases.add(identity)
                derived.append(copy.deepcopy(case))
        for key, value in observed.items():
            if int(suite.get(key, "-1")) != value:
                raise ValueError(f"source suite {key} count is inconsistent")
            totals[key] += value
        selected_count = len(derived.findall("testcase"))
        if selected_count:
            derived.attrib.update(tests=str(selected_count), skipped="0", failures="0", errors="0")
            result.append(derived)
            count += selected_count
    for key, value in totals.items():
        if key in root.attrib and int(root.attrib[key]) != value:
            raise ValueError(f"source aggregate {key} count is inconsistent")
    if not count or set(classes) - matched_classes or set(cases) - matched_cases:
        raise ValueError("required selection is empty or incomplete")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(result).write(output, encoding="utf-8", xml_declaration=True)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--class", dest="classes", action="append", default=[])
    parser.add_argument("--case", dest="cases", action="append", default=[])
    parser.add_argument("--name-contains")
    args = parser.parse_args()
    try:
        count = derive(args.source, args.output, classes=args.classes,
                       cases=args.cases, name_contains=args.name_contains)
    except (OSError, ET.ParseError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Derived {count} passing cases from {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
