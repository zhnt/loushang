"""Coding Product authority for exact Plugin-owned Tool identities."""

from __future__ import annotations

from loushang.coding.lsp.tools import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
)
from loushang.coding.tool_pack import CODING_RESERVED_BASE_TOOL_NAMES

CODING_EXACT_OWNER_TOOL_NAMES: tuple[str, ...] = (
    *CODING_RESERVED_BASE_TOOL_NAMES,
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
)


def coding_peer_tool_names(tool_names: tuple[str, ...]) -> tuple[str, ...]:
    """Keep only Tool identities that are not published by exact owners."""

    exact_names = frozenset(CODING_EXACT_OWNER_TOOL_NAMES)
    return tuple(name for name in tool_names if name not in exact_names)


__all__ = ["CODING_EXACT_OWNER_TOOL_NAMES", "coding_peer_tool_names"]
