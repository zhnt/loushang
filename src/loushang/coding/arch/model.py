"""Language-neutral facts and results for Coding architecture analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ImportCategory = Literal["eager", "typing", "deferred", "lazy_export"]
ImportKind = Literal["import", "from_import", "dynamic_import"]
ImportGranularity = Literal["module", "subsystem"]
ImportSelection = Literal["eager", "all"]
ImportGraphQuery = Literal[
    "summary",
    "cycles",
    "edges",
    "path",
    "hotspots",
    "boundaries",
]
DiagnosticSeverity = Literal["error", "warning"]


@dataclass(frozen=True, order=True)
class SourceEvidence:
    """One source location supporting a dependency fact."""

    path: str
    line: int
    column: int
    statement: str = ""


@dataclass(frozen=True)
class ArchitectureDiagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity = "warning"
    path: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class ImportModuleFact:
    """One importable source module discovered by a language provider."""

    module: str
    path: str
    language: str
    is_package: bool = False


@dataclass(frozen=True)
class ImportDependencyFact:
    """One provider-normalized import relation before graph projection."""

    source: str
    target: str
    category: ImportCategory
    kind: ImportKind
    evidence: SourceEvidence
    is_reexport: bool = False


@dataclass(frozen=True)
class ImportCacheStats:
    enabled: bool = False
    hits: int = 0
    misses: int = 0
    invalidated: int = 0
    entries: int = 0
    error: str | None = None


@dataclass(frozen=True)
class ImportProviderScan:
    """Deterministic output returned by an import-graph language provider."""

    language: str
    modules: tuple[ImportModuleFact, ...]
    dependencies: tuple[ImportDependencyFact, ...]
    package_prefix: str | None = None
    diagnostics: tuple[ArchitectureDiagnostic, ...] = ()
    cache_stats: ImportCacheStats = field(default_factory=ImportCacheStats)


@dataclass(frozen=True)
class ImportGraphNode:
    id: str
    modules: tuple[str, ...]
    paths: tuple[str, ...]


@dataclass(frozen=True)
class ImportGraphEdge:
    source: str
    target: str
    category: ImportCategory
    kind: ImportKind
    evidence: tuple[SourceEvidence, ...]
    is_reexport: bool = False


@dataclass(frozen=True)
class ImportGraph:
    schema_version: int
    root: str
    language: str
    package_prefix: str | None
    granularity: ImportGranularity
    imports: ImportSelection
    nodes: tuple[ImportGraphNode, ...]
    edges: tuple[ImportGraphEdge, ...]
    external_dependencies: tuple[str, ...] = ()
    diagnostics: tuple[ArchitectureDiagnostic, ...] = ()
    cache_stats: ImportCacheStats = field(default_factory=ImportCacheStats)


@dataclass(frozen=True)
class BoundaryRule:
    """A deterministic deny rule over module or subsystem prefixes."""

    source: str
    target: str
    rule_id: str = ""

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.target.strip():
            raise ValueError("boundary source and target must be non-empty")


__all__ = [
    "ArchitectureDiagnostic",
    "BoundaryRule",
    "DiagnosticSeverity",
    "ImportCategory",
    "ImportCacheStats",
    "ImportDependencyFact",
    "ImportGranularity",
    "ImportGraph",
    "ImportGraphEdge",
    "ImportGraphNode",
    "ImportGraphQuery",
    "ImportKind",
    "ImportModuleFact",
    "ImportProviderScan",
    "ImportSelection",
    "SourceEvidence",
]
