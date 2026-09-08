"""Run repository documentation invariants without pytest or product imports."""

from __future__ import annotations

import argparse
import json
import re
import runpy
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")


def check_links(path: Path, *, root: Path = ROOT) -> list[str]:
    errors = []
    text = re.sub(
        r"(?ms)^\s*(```|~~~).*?^\s*\1[^\n]*$", "", path.read_text(encoding="utf-8")
    )
    for raw in LINK.findall(text):
        target = raw.strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        resolved = (path.parent / unquote(parsed.path)).resolve()
        if not resolved.is_relative_to(root) or not resolved.exists():
            errors.append(f"{path.relative_to(root)}: invalid repository link {target}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    # These existing invariants are pure, zero-argument assertions. Reuse them
    # without pytest's collection/conftest or importing the product. Source graph
    # freshness has its own job and is intentionally excluded here.
    namespace = runpy.run_path(
        str(ROOT / "tests/architecture/test_architecture_documentation.py")
    )
    functions = [
        value
        for name, value in namespace.items()
        if name.startswith("test_")
        and callable(value)
        and name != "test_generated_current_package_dependencies_are_fresh"
    ]
    if not functions:
        raise RuntimeError("no documentation invariants found")
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestSuite(
            unittest.FunctionTestCase(function) for function in functions
        )
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.plan:
        errors = []
        for relative in json.loads(args.plan.read_text())["paths"]:
            path = ROOT / relative
            if path.suffix == ".md" and path.is_file():
                errors.extend(check_links(path))
        if errors:
            raise SystemExit("\n".join(errors))


if __name__ == "__main__":
    main()
