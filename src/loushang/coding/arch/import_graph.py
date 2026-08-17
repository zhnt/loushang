"""Deterministic import graph construction and query operations."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

from loushang.coding.arch.cache import ImportFactCache
from loushang.coding.arch.model import (
    ArchitectureDiagnostic,
    BoundaryRule,
    ImportCategory,
    ImportGranularity,
    ImportGraph,
    ImportGraphEdge,
    ImportGraphNode,
    ImportGraphQuery,
    ImportKind,
    ImportProviderScan,
    ImportSelection,
    SourceEvidence,
)
from loushang.coding.arch.providers.base import ImportGraphProvider
from loushang.coding.arch.providers.python import PythonImportGraphProvider

IMPORT_GRAPH_SCHEMA_VERSION = 1


class ImportGraphAnalyzer:
    """Select a language provider and project its facts into a stable graph."""

    def __init__(
        self,
        providers: Iterable[ImportGraphProvider] | None = None,
        *,
        cache: ImportFactCache | None = None,
        cache_enabled: bool = True,
    ) -> None:
        supplied = (
            (PythonImportGraphProvider(),) if providers is None else tuple(providers)
        )
        if not supplied:
            raise ValueError("at least one import graph provider is required")
        languages = [provider.language for provider in supplied]
        if any(
            not isinstance(language, str) or not language.strip()
            for language in languages
        ):
            raise ValueError(
                "import graph provider languages must be non-empty strings"
            )
        if len(languages) != len(set(languages)):
            raise ValueError("import graph provider languages must be unique")
        if not cache_enabled and cache is not None:
            raise ValueError("cache cannot be supplied when caching is disabled")
        self._providers = supplied
        self._cache = (
            cache if cache is not None else ImportFactCache() if cache_enabled else None
        )

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(provider.language for provider in self._providers)

    def analyze(
        self,
        root: str | Path,
        *,
        package_prefix: str | None = None,
        language: str = "auto",
        granularity: ImportGranularity = "module",
        imports: ImportSelection = "eager",
        excludes: Iterable[str] = (),
        refresh_cache: bool = False,
    ) -> ImportGraph:
        resolved_root = Path(root).expanduser().resolve()
        if not resolved_root.is_dir():
            raise ValueError(f"import graph root is not a directory: {root}")
        if granularity not in {"module", "subsystem"}:
            raise ValueError(f"unsupported import graph granularity: {granularity!r}")
        if imports not in {"eager", "all"}:
            raise ValueError(f"unsupported import selection: {imports!r}")
        provider = self._select_provider(resolved_root, language)
        scan = provider.scan(
            resolved_root,
            package_prefix=package_prefix,
            excludes=tuple(excludes),
            cache=self._cache,
            refresh_cache=refresh_cache,
        )
        _validate_scan(scan, provider_language=provider.language)
        return _project_scan(
            scan,
            root=resolved_root,
            package_prefix=package_prefix,
            granularity=granularity,
            imports=imports,
        )

    def _select_provider(self, root: Path, language: str) -> ImportGraphProvider:
        if language != "auto":
            for provider in self._providers:
                if provider.language == language:
                    return provider
            available = ", ".join(self.languages)
            raise ValueError(
                f"unsupported import graph language {language!r}; "
                f"available providers: {available}"
            )
        for provider in self._providers:
            if provider.supports(root):
                return provider
        raise ValueError(f"no import graph provider supports root: {root}")


def analyze_import_graph(
    root: str | Path,
    *,
    package_prefix: str | None = None,
    language: str = "auto",
    granularity: ImportGranularity = "module",
    imports: ImportSelection = "eager",
    excludes: Iterable[str] = (),
    providers: Iterable[ImportGraphProvider] | None = None,
    cache: ImportFactCache | None = None,
    cache_enabled: bool = True,
    refresh_cache: bool = False,
) -> ImportGraph:
    """Analyze one source root using a built-in or caller-supplied provider."""

    return ImportGraphAnalyzer(
        providers,
        cache=cache,
        cache_enabled=cache_enabled,
    ).analyze(
        root,
        package_prefix=package_prefix,
        language=language,
        granularity=granularity,
        imports=imports,
        excludes=excludes,
        refresh_cache=refresh_cache,
    )


def query_import_graph(
    graph: ImportGraph,
    query: ImportGraphQuery = "summary",
    *,
    source: str | None = None,
    target: str | None = None,
    limit: int = 100,
    boundary_rules: Iterable[BoundaryRule] = (),
) -> dict[str, object]:
    """Return one bounded, JSON-compatible view of an import graph."""

    if query not in {
        "summary",
        "cycles",
        "edges",
        "path",
        "hotspots",
        "boundaries",
    }:
        raise ValueError(f"unsupported import graph query: {query!r}")
    if limit < 1:
        raise ValueError("query limit must be at least 1")
    rules = tuple(boundary_rules)
    payload = _base_payload(graph, query)

    if query == "summary":
        cycles = _cycles(graph.nodes, graph.edges)
        eager_edges = tuple(edge for edge in graph.edges if edge.category == "eager")
        eager_cycles = _cycles(graph.nodes, eager_edges)
        typing_edges = tuple(edge for edge in graph.edges if edge.category == "typing")
        typing_cycles = _cycles(graph.nodes, typing_edges)
        violations = _boundary_violations(graph.edges, rules)
        payload.update(
            {
                "cycles": [list(cycle) for cycle in cycles[:limit]],
                "cycles_truncated": len(cycles) > limit,
                "eager_cycles": [list(cycle) for cycle in eager_cycles[:limit]],
                "eager_cycles_truncated": len(eager_cycles) > limit,
                "typing_cycles": [list(cycle) for cycle in typing_cycles[:limit]],
                "typing_cycles_truncated": len(typing_cycles) > limit,
                "hotspots": _hotspots(graph.nodes, graph.edges, limit=min(limit, 20)),
                "boundary_violations": violations[:limit],
                "boundary_violations_truncated": len(violations) > limit,
                "external_dependency_count": len(graph.external_dependencies),
                "categories": _category_counts(graph.edges),
                "diagnostics": [
                    asdict(diagnostic) for diagnostic in graph.diagnostics[:limit]
                ],
                "diagnostics_truncated": len(graph.diagnostics) > limit,
            }
        )
        return payload

    if query == "cycles":
        cycles = _cycles(graph.nodes, graph.edges)
        payload.update(
            {
                "cycles": [
                    _cycle_payload(cycle, graph.edges) for cycle in cycles[:limit]
                ],
                "truncated": len(cycles) > limit,
            }
        )
        return payload

    if query == "edges":
        edges = tuple(
            edge
            for edge in graph.edges
            if (source is None or edge.source == source)
            and (target is None or edge.target == target)
        )
        payload.update(
            {
                "results": [_edge_payload(edge) for edge in edges[:limit]],
                "truncated": len(edges) > limit,
            }
        )
        return payload

    if query == "path":
        if not source or not target:
            raise ValueError("path query requires source and target")
        payload.update(_path_payload(graph, source=source, target=target))
        return payload

    if query == "hotspots":
        hotspots = _hotspots(graph.nodes, graph.edges, limit=limit)
        payload.update({"results": hotspots, "truncated": len(graph.nodes) > limit})
        return payload

    violations = _boundary_violations(graph.edges, rules)
    payload.update(
        {
            "results": violations[:limit],
            "truncated": len(violations) > limit,
        }
    )
    return payload


def _project_scan(
    scan: ImportProviderScan,
    *,
    root: Path,
    package_prefix: str | None,
    granularity: ImportGranularity,
    imports: ImportSelection,
) -> ImportGraph:
    modules_by_name = {module.module: module for module in scan.modules}
    resolved_prefix = _resolved_package_prefix(scan, package_prefix)
    node_ids = {
        module: _project_node_id(module, resolved_prefix, granularity)
        for module in modules_by_name
    }
    grouped_nodes: dict[str, list[str]] = {}
    for module, node_id in node_ids.items():
        grouped_nodes.setdefault(node_id, []).append(module)
    nodes = tuple(
        ImportGraphNode(
            id=node_id,
            modules=tuple(sorted(modules)),
            paths=tuple(sorted({modules_by_name[module].path for module in modules})),
        )
        for node_id, modules in sorted(grouped_nodes.items())
    )

    selected_dependencies = tuple(
        dependency
        for dependency in scan.dependencies
        if imports == "all" or dependency.category == "eager"
    )
    external_dependencies = tuple(
        sorted(
            {
                dependency.target
                for dependency in selected_dependencies
                if dependency.target not in modules_by_name
            }
        )
    )
    grouped_edges: dict[
        tuple[str, str, ImportCategory, ImportKind, bool], set[SourceEvidence]
    ] = {}
    for dependency in selected_dependencies:
        if dependency.target not in modules_by_name:
            continue
        source = node_ids[dependency.source]
        target = node_ids[dependency.target]
        if granularity == "subsystem" and source == target:
            continue
        key = (
            source,
            target,
            dependency.category,
            dependency.kind,
            dependency.is_reexport,
        )
        grouped_edges.setdefault(key, set()).add(dependency.evidence)
    edges = tuple(
        ImportGraphEdge(
            source=source,
            target=target,
            category=category,
            kind=kind,
            is_reexport=is_reexport,
            evidence=tuple(sorted(evidence)),
        )
        for (
            source,
            target,
            category,
            kind,
            is_reexport,
        ), evidence in sorted(grouped_edges.items())
    )
    return ImportGraph(
        schema_version=IMPORT_GRAPH_SCHEMA_VERSION,
        root=str(root),
        language=scan.language,
        package_prefix=resolved_prefix,
        granularity=granularity,
        imports=imports,
        nodes=nodes,
        edges=edges,
        external_dependencies=external_dependencies,
        diagnostics=tuple(sorted(scan.diagnostics, key=_diagnostic_sort_key)),
        cache_stats=scan.cache_stats,
    )


def _resolved_package_prefix(
    scan: ImportProviderScan, requested: str | None
) -> str | None:
    if requested:
        return requested.strip().strip(".") or None
    return scan.package_prefix


def _project_node_id(
    module: str,
    package_prefix: str | None,
    granularity: ImportGranularity,
) -> str:
    if granularity == "module":
        return module
    prefix = package_prefix.strip().strip(".") if package_prefix else ""
    if prefix and (module == prefix or module.startswith(f"{prefix}.")):
        remainder = module[len(prefix) :].lstrip(".")
        return prefix if not remainder else f"{prefix}.{remainder.split('.', 1)[0]}"
    return module.split(".", 1)[0]


def _base_payload(graph: ImportGraph, query: ImportGraphQuery) -> dict[str, object]:
    return {
        "schema_version": graph.schema_version,
        "query": query,
        "language": graph.language,
        "root": graph.root,
        "package_prefix": graph.package_prefix,
        "granularity": graph.granularity,
        "imports": graph.imports,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
    }


def _edge_payload(edge: ImportGraphEdge) -> dict[str, object]:
    return {
        "source": edge.source,
        "target": edge.target,
        "category": edge.category,
        "kind": edge.kind,
        "is_reexport": edge.is_reexport,
        **_evidence_payload(edge.evidence),
    }


def _category_counts(edges: Sequence[ImportGraphEdge]) -> dict[str, int]:
    counts: dict[str, int] = {category: 0 for category in _import_categories()}
    for edge in edges:
        counts[edge.category] += 1
    return counts


def _import_categories() -> tuple[ImportCategory, ...]:
    return "eager", "typing", "deferred", "lazy_export"


def _cycles(
    nodes: Sequence[ImportGraphNode],
    edges: Sequence[ImportGraphEdge],
) -> tuple[tuple[str, ...], ...]:
    node_names = tuple(node.id for node in nodes)
    adjacency = _adjacency(node_names, edges)
    reverse: dict[str, list[str]] = {node: [] for node in node_names}
    for source, targets in adjacency.items():
        for target in targets:
            reverse[target].append(source)
    for sources in reverse.values():
        sources.sort()

    visited: set[str] = set()
    finish_order: list[str] = []
    for start in node_names:
        if start in visited:
            continue
        visited.add(start)
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            node, offset = stack[-1]
            targets = adjacency[node]
            if offset < len(targets):
                candidate = targets[offset]
                stack[-1] = (node, offset + 1)
                if candidate not in visited:
                    visited.add(candidate)
                    stack.append((candidate, 0))
                continue
            finish_order.append(node)
            stack.pop()

    components: list[tuple[str, ...]] = []
    visited.clear()
    for start in reversed(finish_order):
        if start in visited:
            continue
        component: list[str] = []
        pending = [start]
        visited.add(start)
        while pending:
            node = pending.pop()
            component.append(node)
            for candidate in reversed(reverse[node]):
                if candidate in visited:
                    continue
                visited.add(candidate)
                pending.append(candidate)
        normalized = tuple(sorted(component))
        if len(normalized) > 1 or start in adjacency[start]:
            components.append(normalized)
    return tuple(sorted(components))


def _adjacency(
    nodes: Sequence[str], edges: Sequence[ImportGraphEdge]
) -> dict[str, tuple[str, ...]]:
    targets: dict[str, set[str]] = {node: set() for node in nodes}
    for edge in edges:
        targets.setdefault(edge.source, set()).add(edge.target)
    return {node: tuple(sorted(values)) for node, values in targets.items()}


def _cycle_payload(
    cycle: tuple[str, ...], edges: Sequence[ImportGraphEdge]
) -> dict[str, object]:
    members = set(cycle)
    cycle_edges = tuple(
        edge for edge in edges if edge.source in members and edge.target in members
    )
    return {
        "nodes": list(cycle),
        "edge_count": len(cycle_edges),
        "categories": _category_counts(cycle_edges),
    }


def _hotspots(
    nodes: Sequence[ImportGraphNode],
    edges: Sequence[ImportGraphEdge],
    *,
    limit: int,
) -> list[dict[str, object]]:
    incoming: dict[str, set[str]] = {node.id: set() for node in nodes}
    outgoing: dict[str, set[str]] = {node.id: set() for node in nodes}
    for edge in edges:
        outgoing[edge.source].add(edge.target)
        incoming[edge.target].add(edge.source)
    ranked = sorted(
        (
            {
                "node": node.id,
                "fan_in": len(incoming[node.id]),
                "fan_out": len(outgoing[node.id]),
                "total": len(incoming[node.id]) + len(outgoing[node.id]),
            }
            for node in nodes
        ),
        key=lambda item: (
            -cast(int, item["total"]),
            -cast(int, item["fan_in"]),
            -cast(int, item["fan_out"]),
            cast(str, item["node"]),
        ),
    )
    return ranked[:limit]


def _path_payload(
    graph: ImportGraph,
    *,
    source: str,
    target: str,
) -> dict[str, object]:
    node_names = {node.id for node in graph.nodes}
    if source not in node_names:
        raise ValueError(f"unknown path source: {source!r}")
    if target not in node_names:
        raise ValueError(f"unknown path target: {target!r}")
    adjacency = _adjacency(tuple(sorted(node_names)), graph.edges)
    parents: dict[str, str | None] = {source: None}
    queue: deque[str] = deque((source,))
    while queue and target not in parents:
        node = queue.popleft()
        for candidate in adjacency[node]:
            if candidate in parents:
                continue
            parents[candidate] = node
            queue.append(candidate)
    if target not in parents:
        return {"found": False, "nodes": [], "edges": []}
    path = [target]
    while parents[path[-1]] is not None:
        path.append(cast(str, parents[path[-1]]))
    path.reverse()
    selected_edges: list[dict[str, object]] = []
    for edge_source, edge_target in zip(path, path[1:]):
        matches = [
            edge
            for edge in graph.edges
            if edge.source == edge_source and edge.target == edge_target
        ]
        selected_edges.append(_edge_payload(matches[0]))
    return {"found": True, "nodes": path, "edges": selected_edges}


def _boundary_violations(
    edges: Sequence[ImportGraphEdge], rules: Sequence[BoundaryRule]
) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    for rule in rules:
        for edge in edges:
            if not _prefix_matches(edge.source, rule.source):
                continue
            if not _prefix_matches(edge.target, rule.target):
                continue
            violations.append(
                {
                    "rule_id": rule.rule_id
                    or f"{rule.source} must not import {rule.target}",
                    "source": edge.source,
                    "target": edge.target,
                    "category": edge.category,
                    **_evidence_payload(edge.evidence),
                }
            )
    return sorted(
        violations,
        key=lambda item: (
            cast(str, item["rule_id"]),
            cast(str, item["source"]),
            cast(str, item["target"]),
            cast(str, item["category"]),
        ),
    )


def _prefix_matches(value: str, prefix: str) -> bool:
    normalized = prefix.strip()
    if normalized == "*":
        return True
    if normalized.endswith(".*"):
        normalized = normalized[:-2]
    normalized = normalized.rstrip(".")
    return value == normalized or value.startswith(f"{normalized}.")


def _evidence_payload(
    evidence: Sequence[SourceEvidence], *, limit: int = 20
) -> dict[str, object]:
    return {
        "evidence": [asdict(item) for item in evidence[:limit]],
        "evidence_truncated": len(evidence) > limit,
    }


def _validate_scan(scan: ImportProviderScan, *, provider_language: str) -> None:
    if scan.language != provider_language:
        raise ValueError(
            f"provider {provider_language!r} returned language {scan.language!r}"
        )
    module_names = [module.module for module in scan.modules]
    if any(not module for module in module_names):
        raise ValueError("import graph providers must return non-empty module ids")
    if len(module_names) != len(set(module_names)):
        raise ValueError("import graph providers must return unique module ids")
    foreign_modules = sorted(
        module.module for module in scan.modules if module.language != scan.language
    )
    if foreign_modules:
        raise ValueError(
            "import graph modules use a different language than their provider: "
            + ", ".join(foreign_modules)
        )
    known_modules = set(module_names)
    missing_sources = sorted(
        {
            dependency.source
            for dependency in scan.dependencies
            if dependency.source not in known_modules
        }
    )
    if missing_sources:
        raise ValueError(
            "import graph dependencies reference unknown source modules: "
            + ", ".join(missing_sources)
        )
    if any(not dependency.target for dependency in scan.dependencies):
        raise ValueError("import graph dependencies must have non-empty targets")


def _diagnostic_sort_key(
    diagnostic: ArchitectureDiagnostic,
) -> tuple[object, ...]:
    return (
        diagnostic.path or "",
        diagnostic.line or 0,
        diagnostic.code,
        diagnostic.message,
    )


__all__ = [
    "IMPORT_GRAPH_SCHEMA_VERSION",
    "ImportGraphAnalyzer",
    "analyze_import_graph",
    "query_import_graph",
]
