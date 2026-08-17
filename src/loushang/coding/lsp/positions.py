"""Shared UTF-16/LSP and public code-point position conversion."""

from __future__ import annotations

from collections.abc import Mapping

from loushang.coding.lsp.model import (
    CodePosition,
    CodeRange,
    LspInvalidInputError,
    LspProtocolError,
)


def to_lsp_position(content: str, position: CodePosition) -> dict[str, int]:
    lines = content.split("\n")
    if position.line > len(lines):
        raise LspInvalidInputError("line is outside the current document")
    line = lines[position.line - 1]
    if line.endswith("\r"):
        line = line[:-1]
    offset = position.character - 1
    if offset > len(line):
        raise LspInvalidInputError("character is outside the current line")
    utf16_character = len(line[:offset].encode("utf-16-le")) // 2
    return {"line": position.line - 1, "character": utf16_character}


def parse_lsp_range(
    raw_range: Mapping[str, object],
) -> tuple[tuple[int, int], tuple[int, int]]:
    def position(name: str) -> tuple[int, int]:
        raw = raw_range.get(name)
        if not isinstance(raw, Mapping):
            raise LspProtocolError(f"LSP range {name!r} must be an object")
        line = raw.get("line")
        character = raw.get("character")
        if (
            not isinstance(line, int)
            or isinstance(line, bool)
            or line < 0
            or not isinstance(character, int)
            or isinstance(character, bool)
            or character < 0
        ):
            raise LspProtocolError("LSP positions must be non-negative integers")
        return line, character

    start = position("start")
    end = position("end")
    if end < start:
        raise LspProtocolError("LSP range end precedes its start")
    return start, end


def to_public_range(
    content: str,
    value: tuple[tuple[int, int], tuple[int, int]],
) -> CodeRange:
    return CodeRange(
        start=to_public_position(content, value[0]),
        end=to_public_position(content, value[1]),
    )


def to_public_position(content: str, value: tuple[int, int]) -> CodePosition:
    line_number, utf16_character = value
    lines = content.split("\n")
    if line_number >= len(lines):
        raise LspProtocolError("LSP result line is outside the target document")
    line = lines[line_number]
    if line.endswith("\r"):
        line = line[:-1]
    consumed = 0
    code_points = 0
    for character in line:
        if consumed == utf16_character:
            break
        width = len(character.encode("utf-16-le")) // 2
        if consumed + width > utf16_character:
            raise LspProtocolError("LSP position splits a UTF-16 surrogate pair")
        consumed += width
        code_points += 1
    if consumed != utf16_character:
        raise LspProtocolError("LSP result character is outside the target line")
    return CodePosition(line=line_number + 1, character=code_points + 1)


def fallback_public_range(
    value: tuple[tuple[int, int], tuple[int, int]],
) -> CodeRange:
    return CodeRange(
        start=CodePosition(line=value[0][0] + 1, character=value[0][1] + 1),
        end=CodePosition(line=value[1][0] + 1, character=value[1][1] + 1),
    )


__all__ = [
    "fallback_public_range",
    "parse_lsp_range",
    "to_lsp_position",
    "to_public_position",
    "to_public_range",
]
