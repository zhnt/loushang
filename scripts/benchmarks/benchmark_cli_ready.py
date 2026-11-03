#!/usr/bin/env python3
"""Compare installed CLI welcome and idle latency in fresh private PTYs.

This is a local A/B measurement, not a CI timing gate. Each sample uses a new
home and workspace; alternating order reduces drift from host load and caches.
The default 11 rounds report p50 and nearest-rank p90. Use installed console
scripts built for the same Python version on POSIX.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tests.tui.terminal_process_support import (  # noqa: E402
    spawn_terminal_process,
    terminal_test_environment,
)


def _sample(console_script: Path, *, timeout: float) -> dict[str, float | int]:
    with tempfile.TemporaryDirectory(prefix="loushang-cli-ready-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        workspace.mkdir()
        home = root / "home"
        home.mkdir()
        base = {
            key: value
            for key, value in os.environ.items()
            if key.casefold()
            in {
                "path", "pathext", "systemroot", "windir", "comspec", "temp",
                "tmp", "tmpdir", "ld_library_path", "dyld_library_path",
                "lang", "lc_all", "lc_ctype", "tz", "term", "colorterm",
            }
        }
        base.update(
            HOME=str(home),
            USERPROFILE=str(home),
            LOUSHANG_HOME=str(root / "loushang-home"),
        )
        env = terminal_test_environment(REPO_ROOT, base=base)
        env.pop("PYTHONPATH", None)
        cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.perf_counter()
        with spawn_terminal_process(
            [str(console_script)],
            cwd=workspace,
            env=env,
            columns=80,
            rows=24,
        ) as driver:
            driver.read_until(
                lambda output: "Welcome to Loushang CLI" in output,
                timeout=timeout,
            )
            welcomed = time.perf_counter()
            driver.read_until(
                lambda output: "idle\x1b[22m" in output,
                timeout=timeout,
            )
            ready = time.perf_counter()
            driver.write("/quit\r")
            exit_code = driver.wait(timeout=timeout)
        cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        if exit_code != 0:
            raise RuntimeError(f"CLI exited with {exit_code}: {console_script}")
        return {
            "welcome_s": round(welcomed - started, 4),
            "idle_s": round(ready - started, 4),
            "child_cpu_s": round(
                cpu_after.ru_utime + cpu_after.ru_stime
                - cpu_before.ru_utime - cpu_before.ru_stime,
                4,
            ),
            "exit_code": exit_code,
        }


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=11)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 20 or not 1 <= args.timeout <= 120:
        parser.error("rounds must be 1..20 and timeout must be 1..120 seconds")
    for path in (args.baseline, args.candidate):
        if not path.is_file() or not os.access(path, os.X_OK):
            parser.error(f"installed console script is unavailable: {path}")

    samples: dict[str, list[dict[str, float | int]]] = {
        "baseline": [], "candidate": [],
    }
    for round_index in range(args.rounds):
        order = ("baseline", "candidate") if round_index % 2 == 0 else (
            "candidate", "baseline"
        )
        for label in order:
            sample = _sample(getattr(args, label), timeout=args.timeout)
            samples[label].append(sample)
            print(
                f"round {round_index + 1}/{args.rounds} {label}: "
                f"welcome={sample['welcome_s']}s idle={sample['idle_s']}s "
                f"cpu={sample['child_cpu_s']}s",
                file=sys.stderr,
                flush=True,
            )

    baseline_idle = statistics.median(
        float(sample["idle_s"]) for sample in samples["baseline"]
    )
    candidate_idle = statistics.median(
        float(sample["idle_s"]) for sample in samples["candidate"]
    )
    welcome_medians = {
        label: statistics.median(
            float(sample["welcome_s"]) for sample in group
        )
        for label, group in samples.items()
    }
    child_cpu_medians = {
        label: statistics.median(
            float(sample["child_cpu_s"]) for sample in group
        )
        for label, group in samples.items()
    }
    p90_s = {
        label: {
            metric: _p90([float(sample[metric]) for sample in group])
            for metric in ("welcome_s", "idle_s", "child_cpu_s")
        }
        for label, group in samples.items()
    }
    idle_spread_ratios = {
        label: round(
            max(float(sample["idle_s"]) for sample in group)
            / min(float(sample["idle_s"]) for sample in group),
            3,
        )
        for label, group in samples.items()
    }
    timing_warning = (
        "fewer than eleven samples per build; do not attribute the difference"
        if args.rounds < 11
        else (
            "idle times vary by more than 20% within a build; "
            "do not attribute the difference"
            if any(spread > 1.2 for spread in idle_spread_ratios.values())
            else None
        )
    )
    print(json.dumps({
        "schema_version": 2,
        "measurement": "installed_cli_pty_welcome_and_idle",
        "baseline": str(args.baseline.resolve()),
        "candidate": str(args.candidate.resolve()),
        "rounds": args.rounds,
        "samples": samples,
        "baseline_idle_median_s": baseline_idle,
        "candidate_idle_median_s": candidate_idle,
        "welcome_median_s": welcome_medians,
        "child_cpu_median_s": child_cpu_medians,
        "p90_s": p90_s,
        "idle_spread_ratio": idle_spread_ratios,
        "timing_warning": timing_warning,
        "idle_improvement_percent": round(
            100 * (baseline_idle - candidate_idle) / baseline_idle, 2
        ),
        "os_cache": "not controlled; alternating order only",
        "scope": "fresh private home and cwd; no model request or LSP use",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
