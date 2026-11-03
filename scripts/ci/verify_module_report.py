"""Validate actual module results and reject skips in reviewed necessary sets."""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from test_catalog import module_is_fully_classified, module_unit_paths

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/dev"))
# Use the same strict JUnit structure/count checks as the evidence manifests.
from verify_evidence_manifest import (  # noqa: E402
    _suites,
    _verified_suite_counts,
    _verify_aggregate_counts,
)


def verify(module: str, report: Path, *, root: Path = ROOT, shards: int = 1) -> str:
    if shards < 1:
        raise ValueError("shards must be positive")
    inventory = json.loads((root / "scripts/ci/unit-tests.json").read_text())
    if module not in inventory:
        raise ValueError(f"unknown module: {module}")
    paths = module_unit_paths(module, root=root)
    fully_classified = module_is_fully_classified(module, root=root)
    xml = ET.parse(report).getroot()
    suites = _suites(xml)
    counts = dict.fromkeys(("tests", "skipped", "failures", "errors"), 0)
    identities = set()
    seen_files = set()
    owners = {Path(path).with_suffix("").as_posix().replace("/", ".")
              for path in paths or []}
    for suite in suites:
        observed = _verified_suite_counts(suite)
        for key, value in observed.items():
            counts[key] += value
        for case in suite.findall("testcase"):
            classname, name = case.get("classname", ""), case.get("name", "")
            if not classname or not name:
                raise ValueError("testcase identity is missing")
            identity = (classname, name)
            if identity in identities:
                raise ValueError(f"duplicate testcase: {identity}")
            identities.add(identity)
            if paths is not None:
                matched = {owner for owner in owners
                           if classname == owner or classname.startswith(owner + ".")}
                if not matched:
                    raise ValueError(f"testcase is outside reviewed module: {classname}")
                seen_files.update(matched)
    if xml.tag == "testsuites":
        _verify_aggregate_counts(xml, counts)
    if not counts["tests"] or counts["failures"] or counts["errors"]:
        raise ValueError(f"empty or failing module report: {counts}")
    if paths is not None and fully_classified:
        if counts["skipped"]:
            raise ValueError("reviewed necessary module cases must not skip")
        if shards == 1 and seen_files != owners:
            raise ValueError(f"reviewed files are missing: {sorted(owners - seen_files)}")
    elif counts["tests"] == counts["skipped"]:
        # Legacy and partially classified suites retain their platform skip
        # allowance until every remaining file has been reviewed.
        raise ValueError("legacy module report has no passing tests")
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module")
    parser.add_argument("report", type=Path)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    try:
        summary = verify(args.module, args.report, shards=args.shards)
    except (OSError, ET.ParseError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Verified module {args.module}: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
