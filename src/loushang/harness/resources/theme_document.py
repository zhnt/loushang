"""Bounded v1 Theme Resource document shared by Product admission and screens."""

from __future__ import annotations

import re

from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
_NAMED_COLORS = frozenset({
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "default", "bright_black", "bright_red", "bright_green",
    "bright_yellow", "bright_blue", "bright_magenta", "bright_cyan",
    "bright_white",
})
_STYLE_KEYS = frozenset({"color", "background", "bold", "dim", "italic", "underline"})
_MAX_THEME_BYTES = 16 * 1024
_TOKEN_NAMES = frozenset({
    "markdown.heading", "markdown.link", "markdown.link.url",
    "markdown.code.inline", "markdown.code.block", "markdown.code.block.border",
    "markdown.code.indent", "markdown.quote.text", "markdown.quote.border",
    "markdown.hr", "markdown.list.bullet", "transcript.divider",
    "transcript.error", "transcript.tool.action", "transcript.tool.connector",
    "transcript.tool.error_marker", "transcript.tool.flag",
    "transcript.tool.marker", "transcript.tool.meta", "transcript.tool.verb",
    "welcome.border", "welcome.title", "welcome.logo.person",
    "welcome.logo.roof", "welcome.logo", "welcome.quote",
    "welcome.quote.translation", "welcome.text", "welcome.dim",
    "welcome.field.label", "welcome.value", "welcome.tip.label",
    "welcome.tip",
})


class ThemeDocumentError(ValueError):
    """The Theme body cannot be safely presented under the v1 token contract."""


def parse_theme_document_v1(content: str | bytes | None) -> dict[str, dict[str, str | bool]]:
    """Accept style values only; paths, markup, actions and ANSI are excluded."""

    if isinstance(content, str):
        encoded = content.encode("utf-8")
    elif isinstance(content, bytes):
        encoded = content
    else:
        raise ThemeDocumentError("Theme content is unavailable")
    if not encoded or len(encoded) > _MAX_THEME_BYTES:
        raise ThemeDocumentError("Theme content exceeds budget")
    try:
        document = StrictPluginJsonCodec.decode_bytes(encoded, max_depth=4)
    except ValueError as exc:
        raise ThemeDocumentError("Theme JSON is invalid") from exc
    if (
        type(document) is not dict
        or set(document) != {"schemaVersion", "tokens"}
        or type(document["schemaVersion"]) is not int
        or document["schemaVersion"] != 1
        or type(document["tokens"]) is not dict
        or not document["tokens"]
        or len(document["tokens"]) > len(_TOKEN_NAMES)
    ):
        raise ThemeDocumentError("Theme schema is invalid")
    tokens: dict[str, dict[str, str | bool]] = {}
    for token, style in document["tokens"].items():
        if (
            token not in _TOKEN_NAMES
            or type(style) is not dict
            or not style
            or not set(style) <= _STYLE_KEYS
        ):
            raise ThemeDocumentError("Theme token is unsupported")
        normalized: dict[str, str | bool] = {}
        for key, value in style.items():
            if key in {"color", "background"}:
                if (
                    type(value) is not str
                    or value not in _NAMED_COLORS
                    and _HEX_COLOR.fullmatch(value) is None
                ):
                    raise ThemeDocumentError("Theme color is invalid")
            elif type(value) is not bool:
                raise ThemeDocumentError("Theme style is invalid")
            normalized[key] = value
        tokens[token] = normalized
    return tokens


__all__ = ["ThemeDocumentError", "parse_theme_document_v1"]
