"""Immutable admitted LSP definition catalog."""

from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType

from loushang.coding.lsp.model import LspServerDefinition


class LspCatalog:
    def __init__(self, definitions: Iterable[LspServerDefinition]) -> None:
        by_id: dict[str, LspServerDefinition] = {}
        for definition in definitions:
            if definition.id in by_id:
                raise ValueError(f"duplicate LSP server id: {definition.id!r}")
            by_id[definition.id] = definition
        self._definitions = MappingProxyType(by_id)

    def definition(self, definition_id: str) -> LspServerDefinition:
        try:
            return self._definitions[definition_id]
        except KeyError as exc:
            raise KeyError(f"unknown LSP server definition: {definition_id!r}") from exc

    def definitions(self) -> tuple[LspServerDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


__all__ = ["LspCatalog"]
