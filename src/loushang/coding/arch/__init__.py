"""Deterministic, language-extensible architecture analysis for Coding."""

from loushang.coding.arch.cache import (
    IMPORT_FACT_CACHE_SCHEMA_VERSION,
    ImportFactCache,
    default_import_fact_cache_path,
)
from loushang.coding.arch.import_graph import (
    IMPORT_GRAPH_SCHEMA_VERSION,
    ImportGraphAnalyzer,
    analyze_import_graph,
    query_import_graph,
)
from loushang.coding.arch.model import (
    ArchitectureDiagnostic,
    BoundaryRule,
    ImportCacheStats,
    ImportCategory,
    ImportDependencyFact,
    ImportGranularity,
    ImportGraph,
    ImportGraphEdge,
    ImportGraphNode,
    ImportGraphQuery,
    ImportKind,
    ImportModuleFact,
    ImportProviderScan,
    ImportSelection,
    SourceEvidence,
)
from loushang.coding.arch.providers import (
    PYTHON_IMPORT_PROVIDER_VERSION,
    ImportGraphProvider,
    PythonImportGraphProvider,
)
from loushang.coding.arch.tool import (
    INSPECT_IMPORT_GRAPH_TOOL_NAME,
    MAX_INSPECT_IMPORT_GRAPH_LIMIT,
    ImportGraphToolRuntime,
    create_inspect_import_graph_tool_definition,
)
from loushang.coding.arch.tool_pack import (
    CODING_ARCH_TOOL_PACK,
    register_coding_arch_tools,
)

__all__ = [
    "IMPORT_GRAPH_SCHEMA_VERSION",
    "IMPORT_FACT_CACHE_SCHEMA_VERSION",
    "PYTHON_IMPORT_PROVIDER_VERSION",
    "ArchitectureDiagnostic",
    "CODING_ARCH_TOOL_PACK",
    "INSPECT_IMPORT_GRAPH_TOOL_NAME",
    "MAX_INSPECT_IMPORT_GRAPH_LIMIT",
    "BoundaryRule",
    "ImportCategory",
    "ImportCacheStats",
    "ImportDependencyFact",
    "ImportGranularity",
    "ImportGraph",
    "ImportGraphAnalyzer",
    "ImportGraphEdge",
    "ImportGraphNode",
    "ImportGraphProvider",
    "ImportGraphToolRuntime",
    "ImportGraphQuery",
    "ImportKind",
    "ImportModuleFact",
    "ImportProviderScan",
    "ImportFactCache",
    "ImportSelection",
    "PythonImportGraphProvider",
    "SourceEvidence",
    "analyze_import_graph",
    "create_inspect_import_graph_tool_definition",
    "default_import_fact_cache_path",
    "query_import_graph",
    "register_coding_arch_tools",
]
