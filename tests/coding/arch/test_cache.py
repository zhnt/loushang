from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.coding.arch import (
    IMPORT_FACT_CACHE_SCHEMA_VERSION,
    PYTHON_IMPORT_PROVIDER_VERSION,
    ImportFactCache,
    ImportGraphAnalyzer,
    query_import_graph,
)


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "pkg"
    _write(package, "__init__.py", "from . import api\n")
    _write(package, "api.py", "import pkg.core\n")
    _write(package, "core.py", "VALUE = 1\n")
    return package


def _analyzer(cache: ImportFactCache) -> ImportGraphAnalyzer:
    return ImportGraphAnalyzer(cache=cache)


def test_unchanged_scan_reuses_every_file_and_preserves_query_output(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    analyzer = ImportGraphAnalyzer()

    cold = analyzer.analyze(package, package_prefix="pkg", imports="all")
    warm = analyzer.analyze(package, package_prefix="pkg", imports="all")

    assert cold.cache_stats.hits == 0
    assert cold.cache_stats.misses == 3
    assert warm.cache_stats.hits == 3
    assert warm.cache_stats.misses == 0
    assert warm.cache_stats.invalidated == 0
    assert replace(cold, cache_stats=warm.cache_stats) == warm
    assert query_import_graph(cold) == query_import_graph(warm)


def test_same_size_file_change_only_reparses_changed_file(tmp_path: Path) -> None:
    package = _package(tmp_path)
    _write(package, "other.py", "VALUE = 2\n")
    cache = ImportFactCache()
    analyzer = _analyzer(cache)
    analyzer.analyze(package, package_prefix="pkg", imports="all")

    original = (package / "api.py").read_bytes()
    _write(package, "api.py", "import pkg.othe\n")
    assert len((package / "api.py").read_bytes()) == len(original)
    changed = analyzer.analyze(package, package_prefix="pkg", imports="all")

    assert changed.cache_stats.hits == 3
    assert changed.cache_stats.misses == 1
    assert changed.cache_stats.invalidated == 1
    assert (
        any(
            edge.source == "pkg.api" and edge.target == "pkg.othe"
            for edge in changed.edges
        )
        is False
    )
    assert "pkg.othe" in changed.external_dependencies


def test_deletion_and_rename_invalidate_module_sensitive_facts(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    analyzer = _analyzer(ImportFactCache())
    analyzer.analyze(package, package_prefix="pkg", imports="all")

    (package / "core.py").unlink()
    after_delete = analyzer.analyze(package, package_prefix="pkg", imports="all")

    assert after_delete.cache_stats.invalidated == 3
    assert after_delete.cache_stats.hits == 0
    assert after_delete.cache_stats.misses == 2
    assert {node.id for node in after_delete.nodes} == {"pkg", "pkg.api"}
    assert "pkg.core" in after_delete.external_dependencies

    (package / "api.py").rename(package / "service.py")
    after_rename = analyzer.analyze(package, package_prefix="pkg", imports="all")

    assert after_rename.cache_stats.invalidated == 2
    assert after_rename.cache_stats.hits == 0
    assert after_rename.cache_stats.misses == 2
    assert {node.id for node in after_rename.nodes} == {"pkg", "pkg.service"}


def test_syntax_error_is_cached_and_fixed_source_invalidates_it(tmp_path: Path) -> None:
    package = _package(tmp_path)
    _write(package, "broken.py", "def broken(:\n")
    analyzer = _analyzer(ImportFactCache())

    broken = analyzer.analyze(package, package_prefix="pkg", imports="all")
    warm_broken = analyzer.analyze(package, package_prefix="pkg", imports="all")
    _write(package, "broken.py", "VALUE = 3\n")
    fixed = analyzer.analyze(package, package_prefix="pkg", imports="all")

    assert any(item.code == "python_syntax_error" for item in broken.diagnostics)
    assert warm_broken.cache_stats.hits == 4
    assert fixed.cache_stats.hits == 3
    assert fixed.cache_stats.misses == 1
    assert fixed.cache_stats.invalidated == 1
    assert all(item.code != "python_syntax_error" for item in fixed.diagnostics)


def test_disk_cache_is_reused_across_analyzer_instances(tmp_path: Path) -> None:
    package = _package(tmp_path)
    cache_path = tmp_path / "cache" / "facts.json"

    cold = _analyzer(ImportFactCache(cache_path)).analyze(
        package,
        package_prefix="pkg",
        imports="all",
    )
    preserved_mtime_ns = 1_000_000_000
    os.utime(cache_path, ns=(preserved_mtime_ns, preserved_mtime_ns))
    warm = _analyzer(ImportFactCache(cache_path)).analyze(
        package,
        package_prefix="pkg",
        imports="all",
    )

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cold.cache_stats.misses == 3
    assert warm.cache_stats.hits == 3
    assert warm.cache_stats.misses == 0
    assert cache_path.stat().st_mtime_ns == preserved_mtime_ns
    assert payload["schema_version"] == IMPORT_FACT_CACHE_SCHEMA_VERSION
    assert payload["namespace"]["provider_version"] == PYTHON_IMPORT_PROVIDER_VERSION
    assert str(package.resolve()) not in cache_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("version_field", ["schema_version", "provider_version"])
def test_incompatible_disk_cache_is_rebuilt(
    tmp_path: Path,
    version_field: str,
) -> None:
    package = _package(tmp_path)
    cache_path = tmp_path / "cache" / "facts.json"
    _analyzer(ImportFactCache(cache_path)).analyze(package, package_prefix="pkg")
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    if version_field == "schema_version":
        payload[version_field] = 999
    else:
        payload["namespace"][version_field] = 999
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    rebuilt = _analyzer(ImportFactCache(cache_path)).analyze(
        package,
        package_prefix="pkg",
    )
    rewritten = json.loads(cache_path.read_text(encoding="utf-8"))

    assert rebuilt.cache_stats.hits == 0
    assert rebuilt.cache_stats.misses == 3
    assert rewritten["schema_version"] == IMPORT_FACT_CACHE_SCHEMA_VERSION
    assert rewritten["namespace"]["provider_version"] == PYTHON_IMPORT_PROVIDER_VERSION


def test_corrupt_disk_cache_degrades_to_a_rebuild(tmp_path: Path) -> None:
    package = _package(tmp_path)
    cache_path = tmp_path / "cache" / "facts.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("not-json", encoding="utf-8")

    rebuilt = _analyzer(ImportFactCache(cache_path)).analyze(
        package,
        package_prefix="pkg",
    )

    assert rebuilt.cache_stats.misses == 3
    assert rebuilt.cache_stats.error is not None
    assert json.loads(cache_path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_refresh_cache_reparses_every_file(tmp_path: Path) -> None:
    package = _package(tmp_path)
    analyzer = _analyzer(ImportFactCache())
    analyzer.analyze(package, package_prefix="pkg")

    refreshed = analyzer.analyze(
        package,
        package_prefix="pkg",
        refresh_cache=True,
    )

    assert refreshed.cache_stats.hits == 0
    assert refreshed.cache_stats.misses == 3
    assert refreshed.cache_stats.invalidated == 3
