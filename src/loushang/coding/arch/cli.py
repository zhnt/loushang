"""Command-line adapter for deterministic import graph analysis."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from loushang.coding.arch.cache import (
    ImportFactCache,
    default_import_fact_cache_path,
)
from loushang.coding.arch.import_graph import (
    ImportGraphAnalyzer,
    query_import_graph,
)
from loushang.coding.arch.model import BoundaryRule
from loushang.coding.arch.providers.python import PYTHON_IMPORT_PROVIDER_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect a source tree's deterministic import graph.",
    )
    parser.add_argument("root", help="Language source root to scan.")
    parser.add_argument(
        "--package-prefix",
        help="Package name represented by the source root, for example loushang.",
    )
    parser.add_argument(
        "--language",
        default="auto",
        help="Language provider id; defaults to automatic detection.",
    )
    parser.add_argument(
        "--granularity",
        choices=("module", "subsystem"),
        default="module",
    )
    parser.add_argument(
        "--imports",
        choices=("eager", "all"),
        default="eager",
        help="Include eager imports only or every classified import.",
    )
    parser.add_argument(
        "--query",
        choices=("summary", "cycles", "edges", "path", "hotspots", "boundaries"),
        default="summary",
    )
    parser.add_argument("--source", help="Source node for edges or path queries.")
    parser.add_argument("--target", help="Target node for edges or path queries.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Exclude a source-relative path glob; may be repeated.",
    )
    parser.add_argument(
        "--deny",
        action="append",
        default=[],
        metavar="SOURCE=TARGET",
        help="Report imports from SOURCE prefix to TARGET prefix as violations.",
    )
    parser.add_argument(
        "--fail-on-violations",
        action="store_true",
        help="Exit with status 1 when a supplied boundary rule is violated.",
    )
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the versioned per-file fact cache.",
    )
    cache_group.add_argument(
        "--cache-dir",
        type=Path,
        help="Store the fact cache below this directory instead of LOUSHANG_HOME.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore reusable facts and rebuild the cache for this scan.",
    )
    parser.add_argument(
        "--cache-info",
        action="store_true",
        help="Include non-deterministic cache telemetry in the JSON response.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rules = tuple(_parse_boundary_rule(value) for value in args.deny)
        cache = _build_cache(args.root, args.no_cache, args.cache_dir)
        graph = ImportGraphAnalyzer(
            cache=cache,
            cache_enabled=cache is not None,
        ).analyze(
            args.root,
            package_prefix=args.package_prefix,
            language=args.language,
            granularity=args.granularity,
            imports=args.imports,
            excludes=args.exclude,
            refresh_cache=args.refresh_cache,
        )
        result = query_import_graph(
            graph,
            args.query,
            source=args.source,
            target=args.target,
            limit=args.limit,
            boundary_rules=rules,
        )
        if args.cache_info:
            result["cache"] = asdict(graph.cache_stats)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2

    print(
        json.dumps(
            result,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    if args.fail_on_violations and rules:
        gate = query_import_graph(
            graph,
            "boundaries",
            limit=1,
            boundary_rules=rules,
        )
        if _has_boundary_violations(gate):
            return 1
    return 0


def _build_cache(
    root: str,
    disabled: bool,
    cache_dir: Path | None,
) -> ImportFactCache | None:
    if disabled:
        return None
    path = default_import_fact_cache_path(
        root,
        language="python",
        provider_version=PYTHON_IMPORT_PROVIDER_VERSION,
        cache_root=cache_dir,
    )
    return ImportFactCache(path)


def _parse_boundary_rule(value: str) -> BoundaryRule:
    source, separator, target = value.partition("=")
    if not separator or not source.strip() or not target.strip():
        raise ValueError(f"invalid boundary rule {value!r}; expected SOURCE=TARGET")
    normalized_source = source.strip()
    normalized_target = target.strip()
    return BoundaryRule(
        source=normalized_source,
        target=normalized_target,
        rule_id=f"deny:{normalized_source}={normalized_target}",
    )


def _has_boundary_violations(result: dict[str, object]) -> bool:
    direct = result.get("results")
    if isinstance(direct, list) and direct:
        return result.get("query") == "boundaries"
    summary = result.get("boundary_violations")
    return isinstance(summary, list) and bool(summary)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
