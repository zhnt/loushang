"""Model-facing import-graph tool over the deterministic analyzer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from loushang.coding.arch.import_graph import (
    ImportGraphAnalyzer,
    query_import_graph,
)
from loushang.coding.arch.model import (
    BoundaryRule,
    ImportGranularity,
    ImportGraphQuery,
    ImportSelection,
)
from loushang.harness.tools.authoring import (
    FilesystemActionAdapter,
    ToolContext,
    authorized_tool,
)
from loushang.harness.tools.core import ToolDefinition, tool

INSPECT_IMPORT_GRAPH_TOOL_NAME = "inspect_import_graph"
MAX_INSPECT_IMPORT_GRAPH_LIMIT = 200
MAX_INSPECT_IMPORT_GRAPH_EXCLUDES = 100
MAX_INSPECT_IMPORT_GRAPH_BOUNDARY_RULES = 100


class BoundaryRuleInput(TypedDict):
    source: str
    target: str
    rule_id: NotRequired[str]


@dataclass
class ImportGraphToolRuntime:
    """Keep one analyzer and its versioned per-file fact cache warm."""

    analyzer: ImportGraphAnalyzer = field(default_factory=ImportGraphAnalyzer)

    def inspect(
        self,
        *,
        workspace: str | Path,
        root: str = ".",
        package_prefix: str | None = None,
        language: str = "auto",
        granularity: str = "module",
        imports: str = "eager",
        query: str = "summary",
        source: str | None = None,
        target: str | None = None,
        limit: int = 100,
        excludes: list[str] | None = None,
        boundary_rules: list[BoundaryRuleInput] | None = None,
        refresh_cache: bool = False,
    ) -> dict[str, object]:
        resolved_root = _resolve_workspace_root(workspace, root)
        _validate_request(
            granularity=granularity,
            imports=imports,
            query=query,
            limit=limit,
            excludes=excludes,
            boundary_rules=boundary_rules,
        )
        graph = self.analyzer.analyze(
            resolved_root,
            package_prefix=package_prefix,
            language=language,
            granularity=cast(ImportGranularity, granularity),
            imports=cast(ImportSelection, imports),
            excludes=tuple(excludes or ()),
            refresh_cache=refresh_cache,
        )
        result = query_import_graph(
            graph,
            cast(ImportGraphQuery, query),
            source=source,
            target=target,
            limit=limit,
            boundary_rules=_boundary_rules(boundary_rules or []),
        )
        _bound_tool_payload(result, query=cast(ImportGraphQuery, query), limit=limit)
        result["cache"] = asdict(graph.cache_stats)
        return result


def create_inspect_import_graph_tool_definition(
    *,
    runtime: ImportGraphToolRuntime | None = None,
) -> ToolDefinition:
    """Create the optional Coding architecture tool definition."""

    shared_runtime = runtime or ImportGraphToolRuntime()

    @tool(
        name=INSPECT_IMPORT_GRAPH_TOOL_NAME,
        label="Inspect Import Graph",
        description=(
            "Inspect a bounded, deterministic import dependency view within the "
            "current coding workspace. Query summaries, cycles, edges, paths, "
            "hotspots, or boundary violations without returning the full graph."
        ),
        prompt_snippet=(
            "- inspect_import_graph: Query architecture dependency facts for a "
            "workspace source tree; prefer summary first and narrow follow-up queries."
        ),
        prompt_guidelines=(
            "Use inspect_import_graph for verifiable import dependencies, cycles, "
            "paths, hotspots, and boundary violations.",
            "Start with query=summary, then use bounded focused queries instead of "
            "requesting a complete dependency graph.",
        ),
        schema_overrides={
            "properties": {
                "root": {
                    "type": "string",
                    "description": (
                        "Workspace-relative source root, or an absolute path contained "
                        "by the current coding workspace."
                    ),
                },
                "language": {
                    "type": "string",
                    "description": "Language provider id, or auto to detect one.",
                },
                "granularity": {"type": "string", "enum": ["module", "subsystem"]},
                "imports": {"type": "string", "enum": ["eager", "all"]},
                "query": {
                    "type": "string",
                    "enum": [
                        "summary",
                        "cycles",
                        "edges",
                        "path",
                        "hotspots",
                        "boundaries",
                    ],
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_INSPECT_IMPORT_GRAPH_LIMIT,
                },
            }
        },
    )
    def inspect_import_graph(
        ctx: ToolContext,
        root: str,
        package_prefix: str | None = None,
        language: str = "auto",
        granularity: str = "module",
        imports: str = "eager",
        query: str = "summary",
        source: str | None = None,
        target: str | None = None,
        limit: int = 100,
        excludes: list[str] | None = None,
        boundary_rules: list[BoundaryRuleInput] | None = None,
        refresh_cache: bool = False,
    ) -> dict[str, object]:
        if ctx.cwd is None:
            raise RuntimeError("inspect_import_graph requires a coding workspace")
        return shared_runtime.inspect(
            workspace=ctx.cwd,
            root=root,
            package_prefix=package_prefix,
            language=language,
            granularity=granularity,
            imports=imports,
            query=query,
            source=source,
            target=target,
            limit=limit,
            excludes=excludes,
            boundary_rules=boundary_rules,
            refresh_cache=refresh_cache,
        )

    definition = authorized_tool(
        inspect_import_graph,
        action=FilesystemActionAdapter(
            operation="read",
            path_argument="root",
            default_path=".",
        ),
    )
    return replace(definition, execution_mode="sequential")


def _resolve_workspace_root(workspace: str | Path, root: str) -> Path:
    if not isinstance(root, str) or not root.strip():
        raise ValueError("import graph root must be a non-empty path")
    workspace_root = Path(workspace).expanduser().resolve()
    candidate = Path(root).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(workspace_root):
        raise PermissionError("import graph root must stay within the coding workspace")
    return resolved


def _validate_request(
    *,
    granularity: str,
    imports: str,
    query: str,
    limit: int,
    excludes: list[str] | None,
    boundary_rules: list[BoundaryRuleInput] | None,
) -> None:
    if granularity not in {"module", "subsystem"}:
        raise ValueError(f"unsupported import graph granularity: {granularity!r}")
    if imports not in {"eager", "all"}:
        raise ValueError(f"unsupported import selection: {imports!r}")
    if query not in {"summary", "cycles", "edges", "path", "hotspots", "boundaries"}:
        raise ValueError(f"unsupported import graph query: {query!r}")
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("query limit must be an integer")
    if not 1 <= limit <= MAX_INSPECT_IMPORT_GRAPH_LIMIT:
        raise ValueError(
            f"query limit must be between 1 and {MAX_INSPECT_IMPORT_GRAPH_LIMIT}"
        )
    if excludes is not None and len(excludes) > MAX_INSPECT_IMPORT_GRAPH_EXCLUDES:
        raise ValueError(
            f"too many exclude patterns; maximum is {MAX_INSPECT_IMPORT_GRAPH_EXCLUDES}"
        )
    if excludes is not None and any(not isinstance(value, str) for value in excludes):
        raise TypeError("exclude patterns must be strings")
    if (
        boundary_rules is not None
        and len(boundary_rules) > MAX_INSPECT_IMPORT_GRAPH_BOUNDARY_RULES
    ):
        raise ValueError(
            "too many boundary rules; maximum is "
            f"{MAX_INSPECT_IMPORT_GRAPH_BOUNDARY_RULES}"
        )


def _boundary_rules(values: list[BoundaryRuleInput]) -> tuple[BoundaryRule, ...]:
    rules: list[BoundaryRule] = []
    for value in values:
        if not isinstance(value, dict):
            raise TypeError("boundary rules must be objects")
        source = value.get("source")
        target = value.get("target")
        rule_id = value.get("rule_id", "")
        if not isinstance(source, str) or not isinstance(target, str):
            raise TypeError("boundary rule source and target must be strings")
        if not isinstance(rule_id, str):
            raise TypeError("boundary rule id must be a string")
        rules.append(BoundaryRule(source=source, target=target, rule_id=rule_id))
    return tuple(rules)


def _bound_tool_payload(
    payload: dict[str, object],
    *,
    query: ImportGraphQuery,
    limit: int,
) -> None:
    cycle_member_limit = min(limit, 20)
    if query == "summary":
        members_truncated = False
        for key in ("cycles", "eager_cycles", "typing_cycles"):
            cycles = payload.get(key)
            if not isinstance(cycles, list):
                continue
            for index, cycle in enumerate(cycles):
                if not isinstance(cycle, list):
                    continue
                members_truncated = members_truncated or len(cycle) > cycle_member_limit
                cycles[index] = cycle[:cycle_member_limit]
        payload["cycle_members_truncated"] = members_truncated
        return
    if query == "cycles":
        cycles = payload.get("cycles")
        if not isinstance(cycles, list):
            return
        for cycle in cycles:
            if not isinstance(cycle, dict):
                continue
            nodes = cycle.get("nodes")
            if not isinstance(nodes, list):
                continue
            cycle["nodes"] = nodes[:cycle_member_limit]
            cycle["nodes_truncated"] = len(nodes) > cycle_member_limit
        return
    if query == "path":
        nodes = payload.get("nodes")
        edges = payload.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return
        payload["nodes"] = nodes[:limit]
        payload["edges"] = edges[: max(0, limit - 1)]
        payload["truncated"] = len(nodes) > limit


__all__ = [
    "INSPECT_IMPORT_GRAPH_TOOL_NAME",
    "MAX_INSPECT_IMPORT_GRAPH_LIMIT",
    "BoundaryRuleInput",
    "ImportGraphToolRuntime",
    "create_inspect_import_graph_tool_definition",
]
