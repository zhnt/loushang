from __future__ import annotations

import json
import runpy
from collections.abc import Callable
from pathlib import Path


def test_warm_latency_benchmark_checks_full_cache_hits(
    tmp_path: Path,
    capsys,
) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from . import module_0\n", encoding="utf-8")
    for index in range(40):
        target = (index + 1) % 40
        (package / f"module_{index}.py").write_text(
            f"import pkg.module_{target}\n",
            encoding="utf-8",
        )
    namespace = runpy.run_path("scripts/arch/benchmark_import_graph.py")
    main = namespace["main"]
    assert isinstance(main, Callable)

    exit_code = main(
        (
            str(package),
            "--package-prefix",
            "pkg",
            "--runs",
            "2",
            "--warm-max-seconds",
            "10",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["cache_entries"] == 41
    assert payload["warm_cache_hits"] == 41
    assert payload["warm_runs"] == 2
