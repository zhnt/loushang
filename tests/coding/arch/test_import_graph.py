from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from loushang.coding.arch import (
    BoundaryRule,
    ImportDependencyFact,
    ImportGraphAnalyzer,
    ImportModuleFact,
    ImportProviderScan,
    SourceEvidence,
    analyze_import_graph,
    query_import_graph,
)
from loushang.coding.arch.cache import ImportFactCache


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(source).strip() + "\n", encoding="utf-8")


def _python_package(root: Path) -> Path:
    package = root / "pkg"
    _write(
        package,
        "__init__.py",
        """
        from . import api

        def __getattr__(name):
            from . import lazy
            return lazy
        """,
    )
    _write(
        package,
        "api.py",
        """
        from typing import TYPE_CHECKING
        from pkg import core

        if TYPE_CHECKING:
            from pkg import types

        def load():
            from pkg import lazy
            return lazy
        """,
    )
    _write(package, "core.py", "from pkg import api")
    _write(
        package,
        "types.py",
        """
        import typing

        if typing.TYPE_CHECKING:
            from pkg import api
        """,
    )
    _write(package, "lazy.py", "import pkg.core")
    _write(package, "dynamic.py", "VALUE = 1")
    _write(
        package,
        "loader.py",
        """
        import importlib

        def load():
            return importlib.import_module(".dynamic", __package__)
        """,
    )
    return package


def test_python_provider_classifies_imports_and_resolves_relative_modules(
    tmp_path: Path,
) -> None:
    package = _python_package(tmp_path)

    graph = analyze_import_graph(
        package,
        package_prefix="pkg",
        imports="all",
    )

    edges = {
        (edge.source, edge.target, edge.category, edge.kind): edge
        for edge in graph.edges
    }
    assert ("pkg", "pkg.api", "eager", "from_import") in edges
    assert edges[("pkg", "pkg.api", "eager", "from_import")].is_reexport
    assert ("pkg.api", "pkg.core", "eager", "from_import") in edges
    assert ("pkg.api", "pkg.types", "typing", "from_import") in edges
    assert ("pkg.api", "pkg.lazy", "deferred", "from_import") in edges
    assert ("pkg", "pkg.lazy", "lazy_export", "from_import") in edges
    assert (
        "pkg.loader",
        "pkg.dynamic",
        "deferred",
        "dynamic_import",
    ) in edges
    assert (
        edges[("pkg.api", "pkg.core", "eager", "from_import")].evidence[0].statement
        == "from pkg import core"
    )


def test_eager_selection_excludes_typing_deferred_and_lazy_export_edges(
    tmp_path: Path,
) -> None:
    package = _python_package(tmp_path)

    graph = analyze_import_graph(package, package_prefix="pkg")

    assert graph.imports == "eager"
    assert graph.edges
    assert {edge.category for edge in graph.edges} == {"eager"}
    assert ("pkg.api", "pkg.types") not in {
        (edge.source, edge.target) for edge in graph.edges
    }


def test_queries_report_cycles_paths_hotspots_and_boundaries(tmp_path: Path) -> None:
    package = _python_package(tmp_path)
    graph = analyze_import_graph(
        package,
        package_prefix="pkg",
        imports="all",
    )

    summary = query_import_graph(
        graph,
        "summary",
        boundary_rules=(BoundaryRule("pkg.api", "pkg.core", "api-to-core"),),
    )
    assert {"pkg.api", "pkg.core"}.issubset(summary["cycles"][0])
    assert summary["eager_cycles"] == [["pkg.api", "pkg.core"]]
    assert ["pkg.api", "pkg.types"] in summary["typing_cycles"]
    assert summary["boundary_violations"][0]["rule_id"] == "api-to-core"
    assert summary["categories"] == {
        "eager": 4,
        "typing": 2,
        "deferred": 2,
        "lazy_export": 1,
    }

    path = query_import_graph(
        graph,
        "path",
        source="pkg",
        target="pkg.core",
    )
    assert path["found"] is True
    assert path["nodes"] == ["pkg", "pkg.api", "pkg.core"]

    hotspots = query_import_graph(graph, "hotspots", limit=2)
    assert len(hotspots["results"]) == 2
    assert hotspots["results"][0]["node"] == "pkg.api"


def test_subsystem_projection_collapses_modules_and_internal_edges(
    tmp_path: Path,
) -> None:
    package = tmp_path / "pkg"
    _write(package, "__init__.py", "")
    _write(package, "alpha/__init__.py", "")
    _write(package, "alpha/one.py", "from pkg.alpha import two\nfrom pkg import beta")
    _write(package, "alpha/two.py", "VALUE = 1")
    _write(package, "beta.py", "from pkg.alpha import one")

    graph = analyze_import_graph(
        package,
        package_prefix="pkg",
        granularity="subsystem",
    )

    assert [node.id for node in graph.nodes] == ["pkg", "pkg.alpha", "pkg.beta"]
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("pkg.alpha", "pkg.beta"),
        ("pkg.beta", "pkg.alpha"),
    }


def test_package_prefix_is_inferred_for_subsystem_projection(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    _write(package, "__init__.py", "")
    _write(package, "alpha/one.py", "from pkg import beta")
    _write(package, "beta.py", "VALUE = 1")

    graph = analyze_import_graph(package, granularity="subsystem")

    assert graph.package_prefix == "pkg"
    assert [node.id for node in graph.nodes] == ["pkg", "pkg.alpha", "pkg.beta"]


def test_provider_is_replaceable_without_changing_graph_queries(tmp_path: Path) -> None:
    class ExampleProvider:
        language = "example"

        def supports(self, root: Path) -> bool:
            return root.is_dir()

        def scan(
            self,
            root: Path,
            *,
            package_prefix: str | None = None,
            excludes: tuple[str, ...] = (),
            cache: ImportFactCache | None = None,
            refresh_cache: bool = False,
        ) -> ImportProviderScan:
            del root, package_prefix, excludes, cache, refresh_cache
            return ImportProviderScan(
                language=self.language,
                modules=(
                    ImportModuleFact("alpha", "alpha.src", self.language),
                    ImportModuleFact("beta", "beta.src", self.language),
                ),
                dependencies=(
                    ImportDependencyFact(
                        source="alpha",
                        target="beta",
                        category="eager",
                        kind="import",
                        evidence=SourceEvidence("alpha.src", 1, 1, "use beta"),
                    ),
                ),
            )

    graph = ImportGraphAnalyzer((ExampleProvider(),)).analyze(
        tmp_path,
        language="example",
    )

    assert graph.language == "example"
    assert query_import_graph(graph, "edges")["results"][0]["target"] == "beta"


def test_cycle_query_handles_graphs_deeper_than_python_recursion_limit(
    tmp_path: Path,
) -> None:
    module_names = tuple(f"module_{index:04d}" for index in range(1_100))

    class LargeProvider:
        language = "large"

        def supports(self, root: Path) -> bool:
            return root.is_dir()

        def scan(
            self,
            root: Path,
            *,
            package_prefix: str | None = None,
            excludes: tuple[str, ...] = (),
            cache: ImportFactCache | None = None,
            refresh_cache: bool = False,
        ) -> ImportProviderScan:
            del root, package_prefix, excludes, cache, refresh_cache
            return ImportProviderScan(
                language=self.language,
                modules=tuple(
                    ImportModuleFact(name, f"{name}.src", self.language)
                    for name in module_names
                ),
                dependencies=tuple(
                    ImportDependencyFact(
                        source=name,
                        target=module_names[(index + 1) % len(module_names)],
                        category="eager",
                        kind="import",
                        evidence=SourceEvidence(f"{name}.src", 1, 1),
                    )
                    for index, name in enumerate(module_names)
                ),
            )

    graph = ImportGraphAnalyzer((LargeProvider(),)).analyze(tmp_path)
    result = query_import_graph(graph, "cycles")

    assert len(result["cycles"]) == 1
    assert result["cycles"][0]["nodes"] == list(module_names)


def test_edge_query_bounds_repeated_source_evidence(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    _write(package, "__init__.py", "")
    _write(package, "core.py", "VALUE = 1")
    _write(package, "api.py", "\n".join(["import pkg.core"] * 25))

    graph = analyze_import_graph(package, package_prefix="pkg")
    result = query_import_graph(graph, "edges", source="pkg.api")

    assert len(result["results"][0]["evidence"]) == 20
    assert result["results"][0]["evidence_truncated"] is True


def test_scan_reports_syntax_errors_and_honors_excludes(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    _write(package, "__init__.py", "")
    _write(package, "broken.py", "def broken(")
    _write(package, "generated/ignored.py", "import pkg.broken")

    graph = analyze_import_graph(
        package,
        package_prefix="pkg",
        excludes=("generated/*",),
    )

    assert {node.id for node in graph.nodes} == {"pkg", "pkg.broken"}
    assert graph.diagnostics[0].code == "python_syntax_error"
    assert graph.diagnostics[0].path == "broken.py"


def test_scan_does_not_follow_source_symlinks(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    _write(package, "__init__.py", "")
    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    (package / "linked.py").symlink_to(outside)

    graph = analyze_import_graph(package, package_prefix="pkg")

    assert [node.id for node in graph.nodes] == ["pkg"]
