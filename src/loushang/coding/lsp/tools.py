"""Bounded model-facing semantic queries over the Coding LSP runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import unquote, urlparse

from loushang.coding.lsp.documents import DocumentSnapshot, LspDocumentManager
from loushang.coding.lsp.model import (
    CodeHover,
    CodeLocation,
    CodePosition,
    CodeQueryResult,
    CodeSymbol,
    DocumentOutlineResult,
    LspInvalidInputError,
    LspProtocolError,
)
from loushang.coding.lsp.positions import (
    fallback_public_range as _fallback_public_range,
)
from loushang.coding.lsp.positions import parse_lsp_range as _parse_lsp_range
from loushang.coding.lsp.positions import to_lsp_position as _to_lsp_position
from loushang.coding.lsp.positions import to_public_range as _to_public_range
from loushang.coding.lsp.selector import LspSelector
from loushang.coding.lsp.supervisor import LspRuntimeHandle, LspServerSupervisor
from loushang.harness.tools.authoring import ToolContext, direct_tool
from loushang.harness.tools.core import ToolDefinition, tool

INSPECT_SYMBOL_TOOL_NAME = "inspect_symbol"
DOCUMENT_OUTLINE_TOOL_NAME = "document_outline"
MAX_INSPECT_SYMBOL_RESULTS = 50
MAX_HOVER_CONTENT_CHARACTERS = 12_000
MAX_DOCUMENT_OUTLINE_DEPTH = 8
MAX_DOCUMENT_OUTLINE_RESULTS = 200
_MAX_OUTLINE_PROTOCOL_SYMBOLS = 2_000
_MAX_HOVER_CONTENT_PARTS = 64

_QUERY_METHODS = {
    "definition": "textDocument/definition",
    "references": "textDocument/references",
    "hover": "textDocument/hover",
    "implementation": "textDocument/implementation",
}
_QUERY_CAPABILITIES = {
    "definition": "definitionProvider",
    "references": "referencesProvider",
    "hover": "hoverProvider",
    "implementation": "implementationProvider",
}

_SYMBOL_KIND_NAMES = (
    "file",
    "module",
    "namespace",
    "package",
    "class",
    "method",
    "property",
    "field",
    "constructor",
    "enum",
    "interface",
    "function",
    "variable",
    "constant",
    "string",
    "number",
    "boolean",
    "array",
    "object",
    "key",
    "null",
    "enum_member",
    "struct",
    "event",
    "operator",
    "type_parameter",
)


class InspectSymbolRuntime(Protocol):
    async def inspect_symbol(
        self,
        *,
        path: str,
        line: int,
        character: int,
        query: str = "definition",
        include_declaration: bool = True,
        limit: int = 50,
        correlation_id: str,
        signal: object | None = None,
    ) -> CodeQueryResult: ...

    async def document_outline(
        self,
        *,
        path: str,
        depth: int = 4,
        limit: int = 200,
        correlation_id: str,
        signal: object | None = None,
    ) -> DocumentOutlineResult: ...


@dataclass(slots=True)
class CodingLspTools:
    selector: LspSelector
    supervisor: LspServerSupervisor
    documents: LspDocumentManager

    async def inspect_symbol(
        self,
        *,
        path: str,
        line: int,
        character: int,
        query: str = "definition",
        include_declaration: bool = True,
        limit: int = 50,
        correlation_id: str,
        signal: object | None = None,
    ) -> CodeQueryResult:
        _validate_query_input(
            line=line,
            character=character,
            query=query,
            include_declaration=include_declaration,
            limit=limit,
        )
        selection = self.selector.select(path)
        runtime = await self.supervisor.ensure_runtime(
            selection,
            correlation_id=correlation_id,
            signal=signal,
        )
        if not _supports_capability(
            runtime.client.server_capabilities,
            _QUERY_CAPABILITIES[query],
        ):
            return CodeQueryResult(
                items=(),
                count=0,
                truncated=False,
                server_id=selection.definition_id,
                document_version=None,
                readiness="unsupported",
                warnings=(f"language server does not advertise {query} support",),
            )
        document = await self.documents.ensure_document(
            runtime,
            selection.file_path,
            language_id=selection.language_id,
        )
        lsp_position = _to_lsp_position(
            document.content,
            CodePosition(line=line, character=character),
        )
        params: dict[str, object] = {
            "textDocument": {"uri": document.uri},
            "position": lsp_position,
        }
        if query == "references":
            params["context"] = {"includeDeclaration": include_declaration}
        raw_result = await runtime.client.request(_QUERY_METHODS[query], params)
        if query == "hover":
            hover, truncated, warnings = _normalize_hover(
                raw_result,
                source_document=document,
            )
            return CodeQueryResult(
                items=() if hover is None else (hover,),
                count=0 if hover is None else 1,
                truncated=truncated,
                server_id=selection.definition_id,
                document_version=document.version,
                warnings=warnings,
            )
        locations, total, warnings = await self._normalize_locations(
            raw_result,
            runtime=runtime,
            source_document=document,
            limit=limit,
        )
        return CodeQueryResult(
            items=locations,
            count=total,
            truncated=total > len(locations),
            server_id=selection.definition_id,
            document_version=document.version,
            warnings=warnings,
        )

    async def document_outline(
        self,
        *,
        path: str,
        depth: int = 4,
        limit: int = 200,
        correlation_id: str,
        signal: object | None = None,
    ) -> DocumentOutlineResult:
        _validate_outline_input(depth=depth, limit=limit)
        selection = self.selector.select(path)
        runtime = await self.supervisor.ensure_runtime(
            selection,
            correlation_id=correlation_id,
            signal=signal,
        )
        if not _supports_capability(
            runtime.client.server_capabilities,
            "documentSymbolProvider",
        ):
            return DocumentOutlineResult(
                items=(),
                count=0,
                truncated=False,
                server_id=selection.definition_id,
                document_version=None,
                readiness="unsupported",
                warnings=(
                    "language server does not advertise document symbol support",
                ),
            )
        document = await self.documents.ensure_document(
            runtime,
            selection.file_path,
            language_id=selection.language_id,
        )
        raw_result = await runtime.client.request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": document.uri}},
        )
        normalizer = _OutlineNormalizer(
            content=document.content,
            document_uri=document.uri,
            depth=depth,
            limit=limit,
        )
        items = normalizer.normalize(raw_result)
        return DocumentOutlineResult(
            items=items,
            count=normalizer.count,
            truncated=normalizer.truncated,
            server_id=selection.definition_id,
            document_version=document.version,
            warnings=tuple(normalizer.warnings),
        )

    async def _normalize_locations(
        self,
        raw_result: object,
        *,
        runtime: LspRuntimeHandle,
        source_document: DocumentSnapshot,
        limit: int,
    ) -> tuple[tuple[CodeLocation, ...], int, tuple[str, ...]]:
        if raw_result is None:
            return (), 0, ()
        raw_locations = raw_result if isinstance(raw_result, list) else [raw_result]
        warnings: list[str] = []
        normalized: list[CodeLocation] = []
        for raw_location in raw_locations[:limit]:
            normalized.append(
                await self._normalize_location(
                    raw_location,
                    runtime=runtime,
                    source_document=source_document,
                    warnings=warnings,
                )
            )
        return tuple(normalized), len(raw_locations), tuple(dict.fromkeys(warnings))

    async def _normalize_location(
        self,
        raw_location: object,
        *,
        runtime: LspRuntimeHandle,
        source_document: DocumentSnapshot,
        warnings: list[str],
    ) -> CodeLocation:
        del runtime  # Runtime identity is retained in the enclosing result.
        if not isinstance(raw_location, Mapping):
            raise LspProtocolError("semantic location result items must be objects")
        uri = raw_location.get("uri", raw_location.get("targetUri"))
        raw_range = raw_location.get(
            "range",
            raw_location.get("targetSelectionRange", raw_location.get("targetRange")),
        )
        if not isinstance(uri, str) or not isinstance(raw_range, Mapping):
            raise LspProtocolError("semantic location result is missing a URI or range")
        lsp_range = _parse_lsp_range(raw_range)

        target_path = _file_uri_path(uri)
        if target_path is None:
            warnings.append("semantic query target uses a non-file URI")
            return CodeLocation(
                path=None,
                uri=uri,
                range=_fallback_public_range(lsp_range),
                external=True,
                readable=False,
            )
        target_path = target_path.resolve()
        workspace_root = self.selector.workspace_root
        if not target_path.is_relative_to(workspace_root):
            warnings.append("semantic query target is outside the Coding workspace")
            return CodeLocation(
                path=None,
                uri=uri,
                range=_fallback_public_range(lsp_range),
                external=True,
                readable=False,
            )

        try:
            content = (
                source_document.content
                if target_path == source_document.path
                else await self.documents.read_path(target_path)
            )
            public_range = _to_public_range(content, lsp_range)
        except (OSError, UnicodeError, LspInvalidInputError):
            warnings.append(
                "semantic query target could not be read for position conversion"
            )
            return CodeLocation(
                path=target_path.relative_to(workspace_root).as_posix(),
                uri=uri,
                range=_fallback_public_range(lsp_range),
                readable=False,
            )
        return CodeLocation(
            path=target_path.relative_to(workspace_root).as_posix(),
            uri=uri,
            range=public_range,
        )


def _supports_capability(
    capabilities: Mapping[str, object],
    capability_name: str,
) -> bool:
    value = capabilities.get(capability_name)
    return value is True or isinstance(value, Mapping)


def _normalize_hover(
    raw_result: object,
    *,
    source_document: DocumentSnapshot,
) -> tuple[CodeHover | None, bool, tuple[str, ...]]:
    if raw_result is None:
        return None, False, ()
    if not isinstance(raw_result, Mapping):
        raise LspProtocolError("hover result must be an object or null")
    if "contents" not in raw_result:
        raise LspProtocolError("hover result is missing contents")

    contents, kind, truncated = _normalize_hover_contents(raw_result["contents"])
    raw_range = raw_result.get("range")
    public_range = None
    if raw_range is not None:
        if not isinstance(raw_range, Mapping):
            raise LspProtocolError("hover range must be an object")
        public_range = _to_public_range(
            source_document.content,
            _parse_lsp_range(raw_range),
        )
    warnings = (
        ("hover contents were truncated to the configured content limits",)
        if truncated
        else ()
    )
    return (
        CodeHover(contents=contents, kind=kind, range=public_range),
        truncated,
        warnings,
    )


def _normalize_hover_contents(
    raw_contents: object,
) -> tuple[str, Literal["markdown", "plaintext"], bool]:
    if isinstance(raw_contents, str):
        contents, truncated = _bound_hover_content(raw_contents)
        return contents, "markdown", truncated
    if isinstance(raw_contents, Mapping):
        if "kind" in raw_contents:
            kind = raw_contents.get("kind")
            value = raw_contents.get("value")
            if kind not in {"markdown", "plaintext"} or not isinstance(value, str):
                raise LspProtocolError(
                    "hover MarkupContent requires a supported kind and string value"
                )
            contents, truncated = _bound_hover_content(value)
            return contents, kind, truncated
        contents = _normalize_marked_string(raw_contents)
        contents, truncated = _bound_hover_content(contents)
        return contents, "markdown", truncated
    if isinstance(raw_contents, list):
        protocol_truncated = len(raw_contents) > _MAX_HOVER_CONTENT_PARTS
        parts = [
            item if isinstance(item, str) else _normalize_marked_string(item)
            for item in raw_contents[:_MAX_HOVER_CONTENT_PARTS]
        ]
        contents, content_truncated = _bound_hover_content("\n\n".join(parts))
        return contents, "markdown", protocol_truncated or content_truncated
    raise LspProtocolError("hover contents use an unsupported LSP shape")


def _normalize_marked_string(raw_value: object) -> str:
    if not isinstance(raw_value, Mapping):
        raise LspProtocolError("hover MarkedString items must be strings or objects")
    language = raw_value.get("language")
    value = raw_value.get("value")
    if not isinstance(language, str) or not isinstance(value, str):
        raise LspProtocolError(
            "hover MarkedString objects require language and value strings"
        )
    normalized_language = language.strip()
    if len(normalized_language) > 64 or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+-.#"
        for character in normalized_language
    ):
        normalized_language = ""
    return f"```{normalized_language}\n{value}\n```"


def _bound_hover_content(contents: str) -> tuple[str, bool]:
    if len(contents) <= MAX_HOVER_CONTENT_CHARACTERS:
        return contents, False
    return contents[:MAX_HOVER_CONTENT_CHARACTERS], True


def create_inspect_symbol_tool_definition(
    runtime: InspectSymbolRuntime,
) -> ToolDefinition:
    """Create the bounded semantic-query tool over an injected binding."""

    @tool(
        name=INSPECT_SYMBOL_TOOL_NAME,
        label="Inspect Symbol",
        description=(
            "Resolve a bounded semantic symbol query using the admitted language "
            "server for a file in the current Coding workspace."
        ),
        prompt_snippet=(
            "- inspect_symbol: Query definitions, references, hover information, or "
            "implementations at a one-based workspace source position."
        ),
        prompt_guidelines=(
            "Use inspect_symbol when language-semantic symbol information is more "
            "reliable than textual search. The limit bounds location results.",
        ),
        schema_overrides={
            "properties": {
                "line": {"type": "integer", "minimum": 1},
                "character": {"type": "integer", "minimum": 1},
                "query": {
                    "type": "string",
                    "enum": [
                        "definition",
                        "references",
                        "hover",
                        "implementation",
                    ],
                },
                "include_declaration": {"type": "boolean"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_INSPECT_SYMBOL_RESULTS,
                },
            }
        },
    )
    async def inspect_symbol(
        ctx: ToolContext,
        path: str,
        line: int,
        character: int,
        query: str = "definition",
        include_declaration: bool = True,
        limit: int = 50,
    ) -> dict[str, object]:
        result = await runtime.inspect_symbol(
            path=path,
            line=line,
            character=character,
            query=query,
            include_declaration=include_declaration,
            limit=limit,
            correlation_id=ctx.tool_call_id,
            signal=ctx.signal,
        )
        return asdict(result)

    return direct_tool(inspect_symbol)


def create_document_outline_tool_definition(
    runtime: InspectSymbolRuntime,
) -> ToolDefinition:
    """Create the bounded, hierarchy-preserving document outline tool."""

    @tool(
        name=DOCUMENT_OUTLINE_TOOL_NAME,
        label="Document Outline",
        description=(
            "Return a bounded semantic hierarchy of symbols in one workspace file "
            "using its admitted language server."
        ),
        prompt_snippet=(
            "- document_outline: Inspect the semantic symbol hierarchy of one "
            "workspace file."
        ),
        prompt_guidelines=(
            "Use document_outline to understand a file's classes, functions, and "
            "nested members without reading the entire file.",
        ),
        schema_overrides={
            "properties": {
                "depth": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_DOCUMENT_OUTLINE_DEPTH,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_DOCUMENT_OUTLINE_RESULTS,
                },
            }
        },
    )
    async def document_outline(
        ctx: ToolContext,
        path: str,
        depth: int = 4,
        limit: int = 200,
    ) -> dict[str, object]:
        result = await runtime.document_outline(
            path=path,
            depth=depth,
            limit=limit,
            correlation_id=ctx.tool_call_id,
            signal=ctx.signal,
        )
        return asdict(result)

    return direct_tool(document_outline)


def _validate_query_input(
    *,
    line: int,
    character: int,
    query: str,
    include_declaration: bool,
    limit: int,
) -> None:
    if not isinstance(query, str) or query not in _QUERY_METHODS:
        supported = ", ".join(_QUERY_METHODS)
        raise LspInvalidInputError(f"query must be one of: {supported}")
    if not isinstance(include_declaration, bool):
        raise LspInvalidInputError("include_declaration must be a boolean")
    for name, value in (("line", line), ("character", character)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise LspInvalidInputError(f"{name} must be a positive integer")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_INSPECT_SYMBOL_RESULTS
    ):
        raise LspInvalidInputError(
            f"limit must be between 1 and {MAX_INSPECT_SYMBOL_RESULTS}"
        )


def _validate_outline_input(*, depth: int, limit: int) -> None:
    if (
        not isinstance(depth, int)
        or isinstance(depth, bool)
        or not 1 <= depth <= MAX_DOCUMENT_OUTLINE_DEPTH
    ):
        raise LspInvalidInputError(
            f"depth must be between 1 and {MAX_DOCUMENT_OUTLINE_DEPTH}"
        )
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_DOCUMENT_OUTLINE_RESULTS
    ):
        raise LspInvalidInputError(
            f"limit must be between 1 and {MAX_DOCUMENT_OUTLINE_RESULTS}"
        )


class _OutlineNormalizer:
    def __init__(
        self,
        *,
        content: str,
        document_uri: str,
        depth: int,
        limit: int,
    ) -> None:
        self._content = content
        self._document_uri = document_uri
        self._depth = depth
        self._limit = limit
        self.count = 0
        self._emitted = 0
        self.truncated = False
        self.warnings: list[str] = []

    def normalize(self, raw_result: object) -> tuple[CodeSymbol, ...]:
        if raw_result is None:
            return ()
        if not isinstance(raw_result, list):
            raise LspProtocolError("documentSymbol result must be an array or null")
        return self._visit(raw_result, level=1)

    def _visit(self, raw_items: list[object], *, level: int) -> tuple[CodeSymbol, ...]:
        items: list[CodeSymbol] = []
        for raw_item in raw_items:
            if not self._reserve_protocol_item():
                break
            if not isinstance(raw_item, Mapping):
                raise LspProtocolError("documentSymbol items must be objects")
            raw_children = raw_item.get("children", ())
            if not isinstance(raw_children, list | tuple):
                raise LspProtocolError("documentSymbol children must be an array")
            children_values = list(raw_children)
            if level > self._depth or self._emitted >= self._limit:
                self.truncated = True
                self._count_omitted(children_values)
                continue

            self._emitted += 1
            children: tuple[CodeSymbol, ...] = ()
            if children_values:
                if level == self._depth:
                    self.truncated = True
                    self._count_omitted(children_values)
                else:
                    children = self._visit(children_values, level=level + 1)
            items.append(self._parse_symbol(raw_item, children=children))
        return tuple(items)

    def _reserve_protocol_item(self) -> bool:
        if self.count >= _MAX_OUTLINE_PROTOCOL_SYMBOLS:
            self.truncated = True
            warning = "language server returned too many document symbols"
            if warning not in self.warnings:
                self.warnings.append(warning)
            return False
        self.count += 1
        return True

    def _count_omitted(self, raw_items: list[object]) -> None:
        pending = list(reversed(raw_items))
        while pending:
            raw_item = pending.pop()
            if not self._reserve_protocol_item():
                return
            if isinstance(raw_item, Mapping):
                raw_children = raw_item.get("children", ())
                if isinstance(raw_children, list | tuple):
                    pending.extend(reversed(raw_children))

    def _parse_symbol(
        self,
        raw_symbol: Mapping[str, object],
        *,
        children: tuple[CodeSymbol, ...],
    ) -> CodeSymbol:
        name = raw_symbol.get("name")
        kind = raw_symbol.get("kind")
        if not isinstance(name, str) or not name:
            raise LspProtocolError("documentSymbol name must be a non-empty string")
        if (
            not isinstance(kind, int)
            or isinstance(kind, bool)
            or not 1 <= kind <= len(_SYMBOL_KIND_NAMES)
        ):
            raise LspProtocolError("documentSymbol kind is outside the LSP range")

        raw_range = raw_symbol.get("range")
        raw_selection_range = raw_symbol.get("selectionRange")
        container_name = raw_symbol.get("containerName")
        if raw_range is None:
            raw_location = raw_symbol.get("location")
            if not isinstance(raw_location, Mapping):
                raise LspProtocolError(
                    "documentSymbol item is missing range or location"
                )
            if raw_location.get("uri") != self._document_uri:
                raise LspProtocolError(
                    "documentSymbol location must refer to the requested document"
                )
            raw_range = raw_location.get("range")
            raw_selection_range = raw_range
        if not isinstance(raw_range, Mapping) or not isinstance(
            raw_selection_range, Mapping
        ):
            raise LspProtocolError("documentSymbol ranges must be objects")
        detail = raw_symbol.get("detail")
        if detail is not None and not isinstance(detail, str):
            raise LspProtocolError("documentSymbol detail must be a string")
        if container_name is not None and not isinstance(container_name, str):
            raise LspProtocolError("documentSymbol containerName must be a string")
        return CodeSymbol(
            name=name,
            kind=kind,
            kind_name=_SYMBOL_KIND_NAMES[kind - 1],
            range=_to_public_range(self._content, _parse_lsp_range(raw_range)),
            selection_range=_to_public_range(
                self._content,
                _parse_lsp_range(raw_selection_range),
            ),
            detail=detail,
            container_name=container_name,
            children=children,
        )


def _file_uri_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    return Path(unquote(parsed.path))


__all__ = [
    "CodingLspTools",
    "DOCUMENT_OUTLINE_TOOL_NAME",
    "INSPECT_SYMBOL_TOOL_NAME",
    "InspectSymbolRuntime",
    "MAX_DOCUMENT_OUTLINE_DEPTH",
    "MAX_DOCUMENT_OUTLINE_RESULTS",
    "MAX_HOVER_CONTENT_CHARACTERS",
    "MAX_INSPECT_SYMBOL_RESULTS",
    "create_document_outline_tool_definition",
    "create_inspect_symbol_tool_definition",
]
