from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from wcwidth import iter_graphemes as _iter_graphemes
from wcwidth import wcwidth as _codepoint_width
from wcwidth import width as _terminal_width

TAB_WIDTH = 3
AMBIGUOUS_WIDTH_ENV = "LOUSHANG_TUI_AMBIGUOUS_WIDTH"
_THAI_LAO_AM_TRANSLATION = str.maketrans({"\u0e33": "\u0e4d\u0e32", "\u0eb3": "\u0ecd\u0eb2"})
_VISIBLE_WIDTH_CACHE_SIZE = 16_384
_CLUSTER_WIDTH_CACHE_SIZE = 16_384
_ASCII_TOKEN_RUNS = re.compile(r"\s+|\S+")
_ASCII_SGR_CODES = re.compile(r"\x1b\[[0-9;:]*m")
_BOX_DRAWING_GLYPH = re.compile("[┌─┬┐├┼┤│└┴┘]")
_BOX_DRAWING_ASCII_TRANSLATION = str.maketrans(
    {glyph: "|" for glyph in "┌─┬┐├┼┤│└┴┘"}
)
AmbiguousWidth = Literal[1, 2]
_AMBIGUOUS_WIDTH: AmbiguousWidth = 1


@dataclass(frozen=True, slots=True)
class ColumnSlice:
    text: str
    width: int


def strip_control_sequences(text: str) -> str:
    """Remove terminal control sequences that do not occupy cells."""

    if "\x1b" not in text:
        return text

    output: list[str] = []
    index = 0
    while index < len(text):
        escape = text.find("\x1b", index)
        if escape < 0:
            output.append(text[index:])
            break
        output.append(text[index:escape])
        control = _extract_control_sequence(text, escape)
        assert control is not None
        index = escape + control.length
    return "".join(output)


def visible_width(text: str) -> int:
    return _visible_width_cached(text)


def ambiguous_width() -> AmbiguousWidth:
    return _AMBIGUOUS_WIDTH


def set_ambiguous_width(width: AmbiguousWidth) -> None:
    global _AMBIGUOUS_WIDTH
    if width not in (1, 2):
        raise ValueError("ambiguous width must be 1 or 2")
    if _AMBIGUOUS_WIDTH == width:
        return
    _AMBIGUOUS_WIDTH = width
    _visible_width_cached.cache_clear()
    _cluster_width.cache_clear()


def configure_cell_width_from_environment(env: Mapping[str, str] | None = None) -> None:
    source = os.environ if env is None else env
    set_ambiguous_width(_parse_ambiguous_width(source.get(AMBIGUOUS_WIDTH_ENV)))


def normalize_box_drawing_diagram(lines: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = list(lines)
    index = 0
    while index < len(normalized):
        start = _box_top_inner_width(normalized[index])
        if start is None:
            index += 1
            continue

        indent, inner_width = start
        end_index = _find_box_bottom(normalized, index + 1, indent=indent)
        if end_index is None:
            index += 1
            continue

        for line_index in range(index + 1, end_index):
            normalized[line_index] = _normalize_box_content_line(
                normalized[line_index],
                indent=indent,
                inner_width=inner_width,
            )
        index = end_index + 1
    return tuple(normalized)


def normalize_terminal_output(text: str) -> str:
    return text.translate(_THAI_LAO_AM_TRANSLATION)


def grapheme_clusters(text: str) -> tuple[str, ...]:
    """Return the stable editor units used by input and cursor operations.

    Display layout uses wcwidth's UAX #29 segmentation independently so this
    width correction does not also change existing editor navigation semantics.
    """

    return tuple(_editor_grapheme_clusters(text))


def max_display_cluster_width(text: str) -> int:
    """Return the widest indivisible display cluster in styled text."""

    ascii_width = _printable_sgr_ascii_width(text)
    if ascii_width is not None:
        return 1 if ascii_width else 0
    visible = strip_control_sequences(text)
    return max(
        (_cluster_width(cluster) for cluster in _display_grapheme_clusters(visible)),
        default=0,
    )


def wrap_cells(text: str, *, width: int) -> list[str]:
    if width <= 0:
        raise ValueError("width must be positive")

    wrapped: list[str] = []
    for logical_line in strip_control_sequences(text).split("\n"):
        if not logical_line:
            wrapped.append("")
            continue
        # Printable ASCII has one cell per codepoint and no multi-codepoint
        # graphemes. Preserve spaces and explicit empty rows while slicing in C.
        # Controls, tabs and Unicode retain the general cluster-aware layout.
        if logical_line.isascii() and logical_line.isprintable():
            wrapped.extend(
                logical_line[start : start + width]
                for start in range(0, len(logical_line), width)
            )
            continue
        current = ""
        current_width = 0
        for cluster in _display_grapheme_clusters(logical_line):
            cluster_width = _cluster_width(cluster)
            if current and current_width + cluster_width > width:
                wrapped.append(current)
                current = ""
                current_width = 0
            current += cluster
            current_width += cluster_width
        wrapped.append(current)
    return wrapped


def wrap_ansi(text: str, *, width: int) -> list[str]:
    if width <= 0:
        raise ValueError("width must be positive")
    if text == "":
        return [""]

    wrapped: list[str] = []
    tracker = _StyleTracker()
    for input_line in text.split("\n"):
        current = tracker.active_codes()
        if input_line.isascii():
            plain_width = _plain_ascii_width(strip_control_sequences(input_line))
            if plain_width is not None and plain_width <= width:
                _process_control_sequences(input_line, tracker)
                wrapped.append((current + input_line).rstrip(" "))
                continue
        current_width = 0
        tokens = _ansi_tokens(input_line)
        if not tokens:
            wrapped.append(current.rstrip(" "))
            continue

        for token in tokens:
            token_width = visible_width(token)
            is_whitespace = strip_control_sequences(token).strip() == ""

            if token_width > width and not is_whitespace:
                if current_width > 0:
                    wrapped.append(_close_line(current.rstrip(" "), tracker))
                    current = tracker.active_codes()
                    current_width = 0
                broken = _break_long_ansi_token(token, width=width, tracker=tracker)
                wrapped.extend(broken[:-1])
                current = broken[-1]
                current_width = visible_width(current)
                continue

            if current_width > 0 and current_width + token_width > width:
                wrapped.append(_close_line(current.rstrip(" "), tracker))
                current = tracker.active_codes()
                current_width = 0
                if is_whitespace:
                    _process_control_sequences(token, tracker)
                    continue

            current += token
            current_width += token_width
            _process_control_sequences(token, tracker)

        wrapped.append(current.rstrip(" "))
    return wrapped or [""]


def slice_by_column(text: str, *, start: int, length: int, strict: bool = True) -> ColumnSlice:
    if start < 0:
        raise ValueError("start must be non-negative")
    if length <= 0:
        return ColumnSlice("", 0)

    end = start + length
    result = ""
    pending_controls = ""
    width = 0
    column = 0
    index = 0
    while index < len(text):
        control = _extract_control_sequence(text, index)
        if control is not None:
            if column < start:
                pending_controls += control.code
            elif column < end:
                result += control.code
            index += control.length
            continue

        cluster = _next_cluster(text, index)
        cluster_width = _cluster_width(cluster)
        cluster_start = column
        cluster_end = column + cluster_width
        include = cluster_start >= start and cluster_end <= end
        if not strict:
            include = cluster_start < end and cluster_end > start
        if include:
            if pending_controls:
                result += pending_controls
                pending_controls = ""
            result += cluster
            width += cluster_width
        column = cluster_end
        index += len(cluster)

    return ColumnSlice(result, width)


def slice_with_width(text: str, *, start: int, length: int, strict: bool = True) -> ColumnSlice:
    return slice_by_column(text, start=start, length=length, strict=strict)


def truncate_to_width(text: str, *, max_width: int, ellipsis: str = "...", pad: bool = False) -> str:
    if max_width <= 0:
        return ""
    ascii_text_width = _plain_ascii_width(text)
    ascii_ellipsis_width = _plain_ascii_width(ellipsis)
    if ascii_text_width is not None and ascii_ellipsis_width is not None:
        return _truncate_plain_ascii(
            text,
            text_width=ascii_text_width,
            max_width=max_width,
            ellipsis=ellipsis,
            ellipsis_width=ascii_ellipsis_width,
            pad=pad,
        )

    text_width = visible_width(text)
    if text_width <= max_width:
        return text + (" " * max(0, max_width - text_width) if pad else "")

    ellipsis_width = visible_width(ellipsis)
    if ellipsis_width >= max_width:
        clipped_ellipsis = slice_by_column(ellipsis, start=0, length=max_width).text
        clipped_width = visible_width(clipped_ellipsis)
        if clipped_width == 0:
            return " " * max_width if pad else ""
        return _finalize_truncated_result(
            "",
            prefix_width=0,
            ellipsis=clipped_ellipsis,
            ellipsis_width=clipped_width,
            max_width=max_width,
            pad=pad,
        )

    prefix = slice_by_column(text, start=0, length=max_width - ellipsis_width)
    return _finalize_truncated_result(
        prefix.text,
        prefix_width=prefix.width,
        ellipsis=ellipsis,
        ellipsis_width=ellipsis_width,
        max_width=max_width,
        pad=pad,
    )


def autowrap_safe_width(width: int) -> int:
    if width <= 0:
        return 0
    return max(1, width - 1)


def _finalize_truncated_result(
    prefix: str,
    *,
    prefix_width: int,
    ellipsis: str,
    ellipsis_width: int,
    max_width: int,
    pad: bool,
) -> str:
    if ellipsis:
        result = f"{prefix}\x1b[0m{ellipsis}\x1b[0m"
        result_width = prefix_width + ellipsis_width
    else:
        result = f"{prefix}\x1b[0m"
        result_width = prefix_width
    return result + (" " * max(0, max_width - result_width) if pad else "")


@lru_cache(maxsize=_VISIBLE_WIDTH_CACHE_SIZE)
def _visible_width_cached(text: str) -> int:
    plain_ascii_width = _plain_ascii_width(text)
    if plain_ascii_width is not None:
        return plain_ascii_width
    if _AMBIGUOUS_WIDTH == 1 and not text.isascii() and _BOX_DRAWING_GLYPH.search(text):
        box_ascii = text.translate(_BOX_DRAWING_ASCII_TRANSLATION)
        if box_ascii.isascii():
            box_width = (
                _printable_sgr_ascii_width(box_ascii)
                if "\x1b" in box_ascii
                else _plain_ascii_width(box_ascii)
            )
            if box_width is not None:
                return box_width
    if "\x1b" in text:
        sgr_ascii_width = _printable_sgr_ascii_width(text)
        if sgr_ascii_width is not None:
            return sgr_ascii_width
    visible = strip_control_sequences(text)
    plain_ascii_width = _plain_ascii_width(visible)
    if plain_ascii_width is not None:
        return plain_ascii_width
    if not _requires_cluster_measurement(visible):
        return _measure_terminal_cells(visible)
    return sum(_cluster_width(cluster) for cluster in _display_grapheme_clusters(visible))


def _printable_sgr_ascii_width(text: str) -> int | None:
    if not text.isascii():
        return None
    without_sgr = _ASCII_SGR_CODES.sub("", text)
    if "\x1b" in without_sgr or not without_sgr.isprintable():
        return None
    return len(without_sgr)


def _requires_cluster_measurement(text: str) -> bool:
    # wcwidth's whole-string scanner carries state across zero-width/control
    # characters and has special state for regional indicators and emoji skin
    # tones.  UAX #29 may put those codepoints in separate clusters, so measuring
    # the whole line can then disagree with wrapping and slicing.  Only use the
    # whole-string fast path when every codepoint is independently positive and
    # none belongs to a stateful positive-width class.
    for char in text:
        if (
            _codepoint_width(char) <= 0
            or _is_regional_indicator(char)
            or _is_emoji_modifier(char)
        ):
            return True
    return False


def _plain_ascii_width(text: str) -> int | None:
    if not text.isascii():
        return None
    for char in text:
        if not (" " <= char <= "~"):
            return None
    return len(text)


def _parse_ambiguous_width(value: str | None) -> AmbiguousWidth:
    normalized = (value or "1").strip().lower()
    if normalized in {"", "1", "narrow", "single"}:
        return 1
    if normalized in {"2", "wide", "double"}:
        return 2
    raise ValueError(f"{AMBIGUOUS_WIDTH_ENV} must be 1 or 2")


def _box_top_inner_width(line: str) -> tuple[str, int] | None:
    stripped = line.lstrip(" ")
    indent = line[: len(line) - len(stripped)]
    if not stripped.startswith("┌") or not stripped.endswith("┐"):
        return None
    inner = stripped[1:-1]
    if not inner or any(char != "─" for char in inner):
        return None
    return indent, visible_width(inner)


def _find_box_bottom(lines: list[str], start: int, *, indent: str) -> int | None:
    for index in range(start, len(lines)):
        stripped = lines[index].lstrip(" ")
        current_indent = lines[index][: len(lines[index]) - len(stripped)]
        if current_indent != indent:
            continue
        if stripped.startswith("└") and stripped.endswith("┘") and stripped[1:-1] and all(char == "─" for char in stripped[1:-1]):
            return index
    return None


def _normalize_box_content_line(line: str, *, indent: str, inner_width: int) -> str:
    if not line.startswith(indent):
        return line
    rest = line[len(indent) :]
    if not rest.startswith("│"):
        return line
    right_border_index = _box_content_right_border_index(rest, inner_width=inner_width)
    if right_border_index < 0:
        return line
    body = rest[1:right_border_index].rstrip(" ")
    suffix = rest[right_border_index + 1 :]
    if visible_width(body) > inner_width:
        return line
    return indent + "│" + body + (" " * (inner_width - visible_width(body))) + "│" + suffix


def _box_content_right_border_index(rest: str, *, inner_width: int) -> int:
    for index in range(1, len(rest)):
        if rest[index] != "│":
            continue
        raw_body = rest[1:index]
        body = raw_body.rstrip(" ")
        if visible_width(body) <= inner_width and visible_width(raw_body) >= inner_width:
            return index
    return -1


def _truncate_plain_ascii(
    text: str,
    *,
    text_width: int,
    max_width: int,
    ellipsis: str,
    ellipsis_width: int,
    pad: bool,
) -> str:
    if text_width <= max_width:
        return text + (" " * max(0, max_width - text_width) if pad else "")

    if ellipsis_width >= max_width:
        clipped_ellipsis = ellipsis[:max_width]
        clipped_width = len(clipped_ellipsis)
        if clipped_width == 0:
            return " " * max_width if pad else ""
        return _finalize_truncated_result(
            "",
            prefix_width=0,
            ellipsis=clipped_ellipsis,
            ellipsis_width=clipped_width,
            max_width=max_width,
            pad=pad,
        )

    prefix_width = max_width - ellipsis_width
    return _finalize_truncated_result(
        text[:prefix_width],
        prefix_width=prefix_width,
        ellipsis=ellipsis,
        ellipsis_width=ellipsis_width,
        max_width=max_width,
        pad=pad,
    )


@dataclass(frozen=True, slots=True)
class _ControlSequence:
    code: str
    length: int


@dataclass(frozen=True, slots=True)
class _ActiveHyperlink:
    params: str
    url: str
    terminator: str


def _extract_control_sequence(text: str, start: int) -> _ControlSequence | None:
    if start >= len(text) or text[start] != "\x1b":
        return None
    index = start + 1
    if index >= len(text):
        return _ControlSequence(text[start:], len(text) - start)

    introducer = text[index]
    if introducer == "[":
        index += 1
        while index < len(text):
            if "@" <= text[index] <= "~":
                return _ControlSequence(text[start : index + 1], index + 1 - start)
            index += 1
        return _ControlSequence(text[start:], len(text) - start)

    if introducer in {"]", "_"}:
        index += 1
        while index < len(text):
            if text[index] == "\x07":
                return _ControlSequence(text[start : index + 1], index + 1 - start)
            if text[index] == "\x1b" and index + 1 < len(text) and text[index + 1] == "\\":
                return _ControlSequence(text[start : index + 2], index + 2 - start)
            index += 1
        return _ControlSequence(text[start:], len(text) - start)

    return _ControlSequence(text[start : start + 2], min(2, len(text) - start))


def _ansi_tokens(text: str) -> list[str]:
    if text.isascii():
        return _ansi_tokens_ascii(text)

    tokens: list[str] = []
    current = ""
    current_kind: str | None = None
    pending_controls = ""
    index = 0
    while index < len(text):
        control = _extract_control_sequence(text, index)
        if control is not None:
            pending_controls += control.code
            index += control.length
            continue

        cluster = _next_cluster(text, index)
        kind = "space" if cluster.isspace() else "word"
        if current and current_kind is not None and current_kind != kind:
            tokens.append(current)
            current = ""
        if pending_controls:
            current += pending_controls
            pending_controls = ""
        current += cluster
        current_kind = kind
        index += len(cluster)
    if pending_controls:
        current += pending_controls
    if current:
        tokens.append(current)
    return tokens


def _ansi_tokens_ascii(text: str) -> list[str]:
    tokens: list[str] = []
    current = ""
    current_kind: str | None = None
    pending_controls = ""
    index = 0
    while index < len(text):
        escape = text.find("\x1b", index)
        end = len(text) if escape < 0 else escape
        for match in _ASCII_TOKEN_RUNS.finditer(text, index, end):
            run = match.group()
            kind = "space" if run[0].isspace() else "word"
            if current and current_kind is not None and current_kind != kind:
                tokens.append(current)
                current = ""
            if pending_controls:
                current += pending_controls
                pending_controls = ""
            current += run
            current_kind = kind
        if escape < 0:
            break
        control = _extract_control_sequence(text, escape)
        assert control is not None
        pending_controls += control.code
        index = escape + control.length
    if pending_controls:
        current += pending_controls
    if current:
        tokens.append(current)
    return tokens


def _process_control_sequences(text: str, tracker: _StyleTracker) -> None:
    index = 0
    while index < len(text):
        escape = text.find("\x1b", index)
        if escape < 0:
            return
        control = _extract_control_sequence(text, escape)
        assert control is not None
        tracker.process(control.code)
        index = escape + control.length


def _break_long_ansi_token(token: str, *, width: int, tracker: _StyleTracker) -> list[str]:
    lines: list[str] = []
    current = tracker.active_codes()
    current_width = 0
    index = 0
    while index < len(token):
        control = _extract_control_sequence(token, index)
        if control is not None:
            current += control.code
            tracker.process(control.code)
            index += control.length
            continue

        cluster = _next_cluster(token, index)
        cluster_width = _cluster_width(cluster)
        if current_width > 0 and current_width + cluster_width > width:
            lines.append(_close_line(current.rstrip(" "), tracker))
            current = tracker.active_codes()
            current_width = 0
            if cluster.isspace():
                index += len(cluster)
                continue
        current += cluster
        current_width += cluster_width
        index += len(cluster)
    lines.append(current.rstrip(" "))
    return lines


def _display_grapheme_clusters(text: str) -> list[str]:
    return list(_iter_graphemes(text))


def _editor_grapheme_clusters(text: str) -> list[str]:
    clusters: list[str] = []
    index = 0
    while index < len(text):
        cluster = _next_editor_cluster(text, index)
        clusters.append(cluster)
        index += len(cluster)
    return clusters


def _next_cluster(text: str, index: int) -> str:
    char = text[index]
    next_index = index + 1
    if " " <= char <= "~" and (
        next_index >= len(text) or text[next_index].isascii()
    ):
        return char
    return next(_iter_graphemes(text, start=index), "")


def _next_editor_cluster(text: str, index: int) -> str:
    cluster = text[index]
    index += 1

    if _is_regional_indicator(cluster) and index < len(text) and _is_regional_indicator(text[index]):
        cluster += text[index]
        index += 1
        return cluster

    while index < len(text) and _is_cluster_suffix(text[index]):
        cluster += text[index]
        index += 1

    while index < len(text) and text[index] == "\u200d":
        cluster += text[index]
        index += 1
        if index < len(text):
            cluster += text[index]
            index += 1
        while index < len(text) and _is_cluster_suffix(text[index]):
            cluster += text[index]
            index += 1

    return cluster


def _is_cluster_suffix(char: str) -> bool:
    return (
        unicodedata.combining(char) != 0
        or "\ufe00" <= char <= "\ufe0f"
        or "\U0001f3fb" <= char <= "\U0001f3ff"
    )


@lru_cache(maxsize=_CLUSTER_WIDTH_CACHE_SIZE)
def _cluster_width(cluster: str) -> int:
    return _measure_terminal_cells(cluster)


def _measure_terminal_cells(text: str) -> int:
    # Loushang expands tabs as three literal cells throughout its layout code.
    # Keep that existing contract while delegating Unicode width to one pinned
    # terminal model.  Control sequences are stripped before whole-line calls;
    # ignore mode also makes isolated control characters deterministically zero.
    expanded = text.replace("\t", " " * TAB_WIDTH)
    measured = _terminal_width(
        expanded,
        control_codes="ignore",
        ambiguous_width=_AMBIGUOUS_WIDTH,
        term_program=False,
    )
    if "\ufe0e" not in expanded:
        return measured

    # VS15 requests text presentation, but many deployed terminals (and the
    # previous Loushang/CC width models) keep an East Asian Wide base at two
    # cells.  Preserve that conservative cursor contract without widening a
    # narrow base such as ``A\ufe0e``.
    without_vs15 = expanded.replace("\ufe0e", "")
    return max(
        measured,
        _terminal_width(
            without_vs15,
            control_codes="ignore",
            ambiguous_width=_AMBIGUOUS_WIDTH,
            term_program=False,
        ),
    )


configure_cell_width_from_environment()


def _is_regional_indicator(char: str) -> bool:
    return "\U0001f1e6" <= char <= "\U0001f1ff"


def _is_emoji_modifier(char: str) -> bool:
    return "\U0001f3fb" <= char <= "\U0001f3ff"


class _StyleTracker:
    def __init__(self) -> None:
        self._bold = False
        self._dim = False
        self._italic = False
        self._underline = False
        self._blink = False
        self._inverse = False
        self._hidden = False
        self._strikethrough = False
        self._fg_color: str | None = None
        self._bg_color: str | None = None
        self._active_hyperlink: _ActiveHyperlink | None = None

    def process(self, control: str) -> None:
        hyperlink = _parse_osc8_hyperlink(control)
        if hyperlink is not None:
            self._active_hyperlink = hyperlink
            return
        if _is_osc8_close(control):
            self._active_hyperlink = None
            return
        if not control.startswith("\x1b[") or not control.endswith("m"):
            return
        params = control[2:-1]
        if params in {"", "0"}:
            self._reset_sgr()
            return
        parts = params.split(";")
        index = 0
        while index < len(parts):
            try:
                code = int(parts[index] or "0")
            except ValueError:
                index += 1
                continue

            if code in {38, 48}:
                consumed = self._process_color(code, parts[index:])
                index += consumed
                continue

            self._process_sgr_code(code)
            index += 1

    def active_codes(self) -> str:
        codes: list[str] = []
        if self._bold:
            codes.append("1")
        if self._dim:
            codes.append("2")
        if self._italic:
            codes.append("3")
        if self._underline:
            codes.append("4")
        if self._blink:
            codes.append("5")
        if self._inverse:
            codes.append("7")
        if self._hidden:
            codes.append("8")
        if self._strikethrough:
            codes.append("9")
        if self._fg_color is not None:
            codes.append(self._fg_color)
        if self._bg_color is not None:
            codes.append(self._bg_color)
        sgr = f"\x1b[{';'.join(codes)}m" if codes else ""
        if self._active_hyperlink is not None:
            return f"{sgr}{_format_osc8_hyperlink(self._active_hyperlink)}"
        return sgr

    def line_end_reset(self) -> str:
        reset = ""
        if self._underline:
            reset += "\x1b[24m"
        if self._active_hyperlink is not None:
            reset += _format_osc8_close(self._active_hyperlink.terminator)
        return reset

    def _process_color(self, code: int, parts: list[str]) -> int:
        if len(parts) >= 3 and parts[1] == "5":
            color = ";".join(parts[:3])
            if code == 38:
                self._fg_color = color
            else:
                self._bg_color = color
            return 3
        if len(parts) >= 5 and parts[1] == "2":
            color = ";".join(parts[:5])
            if code == 38:
                self._fg_color = color
            else:
                self._bg_color = color
            return 5
        return 1

    def _process_sgr_code(self, code: int) -> None:
        if code == 0:
            self._reset_sgr()
        elif code == 1:
            self._bold = True
        elif code == 2:
            self._dim = True
        elif code == 3:
            self._italic = True
        elif code == 4:
            self._underline = True
        elif code == 5:
            self._blink = True
        elif code == 7:
            self._inverse = True
        elif code == 8:
            self._hidden = True
        elif code == 9:
            self._strikethrough = True
        elif code == 21:
            self._bold = False
        elif code == 22:
            self._bold = False
            self._dim = False
        elif code == 23:
            self._italic = False
        elif code == 24:
            self._underline = False
        elif code == 25:
            self._blink = False
        elif code == 27:
            self._inverse = False
        elif code == 28:
            self._hidden = False
        elif code == 29:
            self._strikethrough = False
        elif code == 39:
            self._fg_color = None
        elif code == 49:
            self._bg_color = None
        elif 30 <= code <= 37 or 90 <= code <= 97:
            self._fg_color = str(code)
        elif 40 <= code <= 47 or 100 <= code <= 107:
            self._bg_color = str(code)

    def _reset_sgr(self) -> None:
        self._bold = False
        self._dim = False
        self._italic = False
        self._underline = False
        self._blink = False
        self._inverse = False
        self._hidden = False
        self._strikethrough = False
        self._fg_color = None
        self._bg_color = None


def _close_line(line: str, tracker: _StyleTracker) -> str:
    if not line:
        return line
    return f"{line}{tracker.line_end_reset()}"


def _parse_osc8_hyperlink(control: str) -> _ActiveHyperlink | None:
    if not control.startswith("\x1b]8;"):
        return None
    terminator = _osc_terminator(control)
    if terminator is None:
        return None
    body = control[4 : -len(terminator)]
    separator = body.find(";")
    if separator < 0:
        return None
    params = body[:separator]
    url = body[separator + 1 :]
    if not url:
        return None
    return _ActiveHyperlink(params=params, url=url, terminator=terminator)


def _is_osc8_close(control: str) -> bool:
    if not control.startswith("\x1b]8;"):
        return False
    terminator = _osc_terminator(control)
    if terminator is None:
        return False
    body = control[4 : -len(terminator)]
    separator = body.find(";")
    return separator >= 0 and body[separator + 1 :] == ""


def _osc_terminator(control: str) -> str | None:
    if control.endswith("\x07"):
        return "\x07"
    if control.endswith("\x1b\\"):
        return "\x1b\\"
    return None


def _format_osc8_hyperlink(hyperlink: _ActiveHyperlink) -> str:
    return f"\x1b]8;{hyperlink.params};{hyperlink.url}{hyperlink.terminator}"


def _format_osc8_close(terminator: str) -> str:
    return f"\x1b]8;;{terminator}"
