from __future__ import annotations

import html
import re
from dataclasses import dataclass

_ANSI_COLORS = [
    "#000000",
    "#800000",
    "#008000",
    "#808000",
    "#000080",
    "#800080",
    "#008080",
    "#c0c0c0",
    "#808080",
    "#ff0000",
    "#00ff00",
    "#ffff00",
    "#0000ff",
    "#ff00ff",
    "#00ffff",
    "#ffffff",
]
_ANSI_RE = re.compile(r"\x1b\[([\d;]*)m")


@dataclass
class _TextStyle:
    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False

    def reset(self) -> None:
        self.fg = None
        self.bg = None
        self.bold = False
        self.dim = False
        self.italic = False
        self.underline = False

    def to_css(self) -> str:
        parts: list[str] = []
        if self.fg is not None:
            parts.append(f"color:{self.fg}")
        if self.bg is not None:
            parts.append(f"background-color:{self.bg}")
        if self.bold:
            parts.append("font-weight:bold")
        if self.dim:
            parts.append("opacity:0.6")
        if self.italic:
            parts.append("font-style:italic")
        if self.underline:
            parts.append("text-decoration:underline")
        return ";".join(parts)


def render_ansi_pre(text: str) -> str:
    return '<pre class="ansi-rendered">' + ansi_to_html(text) + "</pre>"


def ansi_to_html(text: str) -> str:
    style = _TextStyle()
    output: list[str] = []
    last_index = 0
    open_span = False

    for match in _ANSI_RE.finditer(text):
        before = text[last_index : match.start()]
        if before:
            output.append(html.escape(before))

        if open_span:
            output.append("</span>")
            open_span = False

        _apply_codes(_parse_codes(match.group(1)), style)
        css = style.to_css()
        if css:
            output.append(f'<span style="{html.escape(css, quote=True)}">')
            open_span = True
        last_index = match.end()

    tail = text[last_index:]
    if tail:
        output.append(html.escape(tail))
    if open_span:
        output.append("</span>")
    return "".join(output)


def _parse_codes(value: str) -> list[int]:
    if not value:
        return [0]
    codes: list[int] = []
    for part in value.split(";"):
        try:
            codes.append(int(part or "0"))
        except ValueError:
            codes.append(0)
    return codes


def _apply_codes(codes: list[int], style: _TextStyle) -> None:
    index = 0
    while index < len(codes):
        code = codes[index]
        if code == 0:
            style.reset()
        elif code == 1:
            style.bold = True
        elif code == 2:
            style.dim = True
        elif code == 3:
            style.italic = True
        elif code == 4:
            style.underline = True
        elif code == 22:
            style.bold = False
            style.dim = False
        elif code == 23:
            style.italic = False
        elif code == 24:
            style.underline = False
        elif 30 <= code <= 37:
            style.fg = _ANSI_COLORS[code - 30]
        elif code == 38:
            index += _apply_extended_color(codes, index, foreground=True, style=style)
        elif code == 39:
            style.fg = None
        elif 40 <= code <= 47:
            style.bg = _ANSI_COLORS[code - 40]
        elif code == 48:
            index += _apply_extended_color(codes, index, foreground=False, style=style)
        elif code == 49:
            style.bg = None
        elif 90 <= code <= 97:
            style.fg = _ANSI_COLORS[code - 90 + 8]
        elif 100 <= code <= 107:
            style.bg = _ANSI_COLORS[code - 100 + 8]
        index += 1


def _apply_extended_color(
    codes: list[int], index: int, *, foreground: bool, style: _TextStyle
) -> int:
    if len(codes) > index + 2 and codes[index + 1] == 5:
        color = _color_256_to_hex(codes[index + 2])
        if foreground:
            style.fg = color
        else:
            style.bg = color
        return 2
    if len(codes) > index + 4 and codes[index + 1] == 2:
        color = f"rgb({codes[index + 2]},{codes[index + 3]},{codes[index + 4]})"
        if foreground:
            style.fg = color
        else:
            style.bg = color
        return 4
    return 0


def _color_256_to_hex(value: int) -> str:
    index = max(0, min(255, value))
    if index < 16:
        return _ANSI_COLORS[index]
    if index < 232:
        cube_index = index - 16
        red = cube_index // 36
        green = (cube_index % 36) // 6
        blue = cube_index % 6
        return "#" + "".join(_cube_component(part) for part in (red, green, blue))
    gray = 8 + (index - 232) * 10
    return f"#{gray:02x}{gray:02x}{gray:02x}"


def _cube_component(value: int) -> str:
    component = 0 if value == 0 else 55 + value * 40
    return f"{component:02x}"
