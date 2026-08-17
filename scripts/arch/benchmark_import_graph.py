#!/usr/bin/env python3
"""Gate warm import-graph latency for a long-lived Coding process."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from statistics import median
from time import perf_counter

from loushang.coding.arch import (
    ImportFactCache,
    ImportGraphAnalyzer,
    query_import_graph,
)

BENCHMARK_SCHEMA_VERSION = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark repeated import-graph analysis in one long-lived process."
        )
    )
    parser.add_argument("root", type=Path, help="Language source root to scan.")
    parser.add_argument("--package-prefix")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--warm-max-seconds",
        type=float,
        default=1.0,
        help="Fail when any unchanged warm analysis exceeds this latency.",
    )
    parser.add_argument(
        "--cache-file",
        type=Path,
        help="Exercise atomic disk persistence in addition to the memory cache.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.warm_max_seconds <= 0:
        parser.error("--warm-max-seconds must be greater than 0")

    cache = ImportFactCache(args.cache_file)
    analyzer = ImportGraphAnalyzer(cache=cache)
    analyze_arguments = {
        "package_prefix": args.package_prefix,
        "language": args.language,
        "imports": "all",
    }

    cold_started = perf_counter()
    cold_graph = analyzer.analyze(
        args.root,
        refresh_cache=True,
        **analyze_arguments,
    )
    expected = query_import_graph(cold_graph, "summary")
    cold_seconds = perf_counter() - cold_started

    warm_seconds: list[float] = []
    warm_hits: list[int] = []
    for _ in range(args.runs):
        started = perf_counter()
        graph = analyzer.analyze(args.root, **analyze_arguments)
        actual = query_import_graph(graph, "summary")
        elapsed = perf_counter() - started
        if actual != expected:
            raise RuntimeError("warm import-graph result differs from cold result")
        if (
            graph.cache_stats.misses
            or graph.cache_stats.hits != graph.cache_stats.entries
        ):
            raise RuntimeError("warm import-graph analysis did not fully hit the cache")
        warm_seconds.append(elapsed)
        warm_hits.append(graph.cache_stats.hits)

    warm_max = max(warm_seconds)
    passed = warm_max <= args.warm_max_seconds
    result = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "root": str(args.root.expanduser().resolve()),
        "language": cold_graph.language,
        "modules": len(cold_graph.nodes),
        "edges": len(cold_graph.edges),
        "cache_entries": cold_graph.cache_stats.entries,
        "cold_seconds": round(cold_seconds, 6),
        "warm_runs": args.runs,
        "warm_seconds": {
            "min": round(min(warm_seconds), 6),
            "median": round(median(warm_seconds), 6),
            "max": round(warm_max, 6),
        },
        "warm_cache_hits": min(warm_hits),
        "warm_max_seconds": args.warm_max_seconds,
        "passed": passed,
    }
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["BENCHMARK_SCHEMA_VERSION", "build_parser", "main"]
