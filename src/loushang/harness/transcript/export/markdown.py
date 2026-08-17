from __future__ import annotations

import html
import re

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

_FENCE_RE = re.compile(r"```([A-Za-z0-9_+.#-]*)[^\n]*\n(.*?)```", re.DOTALL)
_LANGUAGE_RE = re.compile(r"[^A-Za-z0-9_+.#-]+")
_FORMATTER = HtmlFormatter(nowrap=True)


def render_markdown(text: str) -> str:
    fragments: list[str] = []
    cursor = 0
    for match in _FENCE_RE.finditer(text):
        fragments.extend(_render_paragraphs(text[cursor : match.start()]))
        fragments.append(_render_code_block(match.group(2), language=match.group(1)))
        cursor = match.end()
    fragments.extend(_render_paragraphs(text[cursor:]))
    return '<div class="markdown-content">' + "".join(fragments) + "</div>"


def _render_paragraphs(text: str) -> list[str]:
    blocks = [block.strip("\n") for block in re.split(r"\n{2,}", text) if block.strip()]
    return [
        "<p>" + _render_inline(block).replace("\n", "<br />") + "</p>"
        for block in blocks
    ]


def _render_inline(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    while True:
        start = text.find("`", cursor)
        if start < 0:
            parts.append(html.escape(text[cursor:]))
            break
        end = text.find("`", start + 1)
        if end < 0:
            parts.append(html.escape(text[cursor:]))
            break
        parts.append(html.escape(text[cursor:start]))
        parts.append("<code>" + html.escape(text[start + 1 : end]) + "</code>")
        cursor = end + 1
    return "".join(parts)


def _render_code_block(code: str, *, language: str) -> str:
    normalized_language = _normalize_language(language)
    highlighted = _highlight_code(code, language=normalized_language)
    class_name = "highlight"
    if normalized_language:
        class_name += f" language-{html.escape(normalized_language)}"
    return f'<pre><code class="{class_name}">{highlighted}</code></pre>'


def _highlight_code(code: str, *, language: str) -> str:
    lexer = TextLexer()
    if language:
        try:
            lexer = get_lexer_by_name(language)
        except ClassNotFound:
            lexer = TextLexer()
    return highlight(code.rstrip("\n"), lexer, _FORMATTER)


def _normalize_language(language: str) -> str:
    return _LANGUAGE_RE.sub("-", language.strip().lower()).strip("-")
