"""Coding Product authority for exact Plugin-owned Tool identities."""

from __future__ import annotations

from loushang.coding.arch.tool import INSPECT_IMPORT_GRAPH_TOOL_NAME
from loushang.coding.lsp.tools import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
)
from loushang.coding.package.worker_tool_identity import (
    CODING_WORKER_QUERY_TOOL_NAME,
)
from loushang.coding.resources.tool_pack import CODING_RESERVED_BASE_TOOL_NAMES
from loushang.harness.tools.workspace.selection import peer_tool_names

CODING_LSP_EXACT_OWNER_TOOL_NAMES: tuple[str, ...] = (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
)
CODING_ARCH_EXACT_OWNER_TOOL_NAMES: tuple[str, ...] = (
    INSPECT_IMPORT_GRAPH_TOOL_NAME,
)
CODING_EXACT_OWNER_TOOL_NAMES: tuple[str, ...] = (
    *CODING_RESERVED_BASE_TOOL_NAMES,
    *CODING_LSP_EXACT_OWNER_TOOL_NAMES,
    *CODING_ARCH_EXACT_OWNER_TOOL_NAMES,
    CODING_WORKER_QUERY_TOOL_NAME,
)


def coding_peer_tool_names(tool_names: tuple[str, ...]) -> tuple[str, ...]:
    """Keep only Tool identities that are not published by exact owners."""

    return peer_tool_names(tool_names, CODING_EXACT_OWNER_TOOL_NAMES)


__all__ = [
    "CODING_EXACT_OWNER_TOOL_NAMES",
    "CODING_ARCH_EXACT_OWNER_TOOL_NAMES",
    "CODING_LSP_EXACT_OWNER_TOOL_NAMES",
    "coding_peer_tool_names",
]
