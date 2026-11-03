from __future__ import annotations

import loushang.tui.cell_width as cell_width
from loushang.tui import (
    CURSOR_MARKER,
    configure_cell_width_from_environment,
    normalize_box_drawing_diagram,
    normalize_terminal_output,
    set_ambiguous_width,
    slice_by_column,
    slice_with_width,
    strip_control_sequences,
    truncate_to_width,
    visible_width,
    wrap_ansi,
    wrap_cells,
)


def test_visible_width_ignores_ansi_sgr_and_osc8_hyperlinks() -> None:
    text = "\x1b[31mred\x1b[0m \x1b]8;;https://example.test\x1b\\link\x1b]8;;\x1b\\"

    assert strip_control_sequences(text) == "red link"
    assert visible_width(text) == 8


def test_visible_width_styled_ascii_skips_unicode_measurement(monkeypatch) -> None:
    def unexpected_unicode_measurement(_text: str) -> bool:
        raise AssertionError("printable styled ASCII needs no Unicode measurement")

    monkeypatch.setattr(cell_width, "_requires_cluster_measurement", unexpected_unicode_measurement)
    assert visible_width("\x1b[32mgreen\x1b[0m \x1b]8;;https://example.test\x1b\\link\x1b]8;;\x1b\\") == 10


def test_visible_width_printable_sgr_ascii_skips_control_scanner(monkeypatch) -> None:
    def unexpected_control_scan(_text: str) -> str:
        raise AssertionError("printable SGR ASCII needs no general control scan")

    monkeypatch.setattr(cell_width, "strip_control_sequences", unexpected_control_scan)
    assert visible_width("\x1b[38;2;101;202;77munique 798 line\x1b[0m") == 15


def test_visible_width_box_table_ascii_skips_unicode_scanner(monkeypatch) -> None:
    def fail(_text: str) -> int:
        raise AssertionError("box table row used the general Unicode scanner")

    monkeypatch.setattr(cell_width, "_measure_terminal_cells", fail)
    assert visible_width("┌─┬─┐") == 5
    assert visible_width("│ \x1b[32mrow 798\x1b[0m │") == 11


def test_ascii_table_cell_skips_grapheme_scan(monkeypatch) -> None:
    def unexpected_grapheme_scan(_text: str):
        raise AssertionError("printable ASCII has only one-cell clusters")

    monkeypatch.setattr(cell_width, "_display_grapheme_clusters", unexpected_grapheme_scan)
    assert cell_width.max_display_cluster_width("plain table cell") == 1
    assert cell_width.max_display_cluster_width("\x1b[36mstyled table cell\x1b[0m") == 1
    assert cell_width.max_display_cluster_width("\x1b[0m") == 0


def test_visible_width_handles_wide_combining_and_emoji_clusters() -> None:
    assert visible_width("a") == 1
    assert visible_width("中") == 2
    assert visible_width("e\u0301") == 1
    assert visible_width("🙂") == 2
    assert visible_width("👍🏽") == 2
    assert visible_width("👨\u200d👩\u200d👧\u200d👦") == 2
    assert visible_width("🇺") == 2
    assert visible_width("🇺🇸") == 2


def test_visible_width_uses_pinned_terminal_width_rules_for_complex_sequences() -> None:
    expected_widths = {
        "1️⃣": 2,
        "☕︎": 2,
        "A︎": 1,
        "가": 2,
        "한": 2,
        "\U000e0100": 0,
        "木\U000e0100": 2,
        "กั": 1,
        "ກັ": 1,
        "🜀": 1,
        "A️": 1,
        "a\u200d👨": 3,
        "\u200d👨": 2,
        "ক্🙂": 3,
        "Aᅡ्🙂": 3,
        "中ᅡ्🙂": 4,
        "\u200b🇺🇺": 4,
        "🇺\n🇺": 4,
        "👨\u200b\u200b\u200b🏽": 4,
        "❤\u200b\u200b\u200b️": 1,
        "A\u200b\u200b\u200bा": 1,
        "🇸e🇺⃣্🏽າ": 6,
    }

    assert {sample: visible_width(sample) for sample in expected_widths} == expected_widths


def test_complex_sequence_width_matches_layout_operations() -> None:
    for sample, width in (
        ("1️⃣", 2),
        ("☕︎", 2),
        ("A︎", 1),
        ("가", 2),
        ("กั", 1),
        ("a\u200d👨", 3),
        ("\u200d👨", 2),
        ("ক্🙂", 3),
        ("Aᅡ्🙂", 3),
        ("中ᅡ्🙂", 4),
        ("\u200b🇺🇺", 4),
        ("👨\u200b\u200b\u200b🏽", 4),
        ("🇸e🇺⃣্🏽າ", 6),
    ):
        assert wrap_cells(sample, width=width) == [sample]
        assert slice_by_column(sample, start=0, length=width).text == sample
        assert truncate_to_width(sample, max_width=width, ellipsis="") == sample

    assert wrap_cells("🇺\n🇺", width=4) == ["🇺", "🇺"]
    assert slice_by_column("🇺\n🇺", start=0, length=4).text == "🇺\n🇺"

    styled_keycap = "\x1b[31m1️⃣\x1b[0m"
    assert visible_width(styled_keycap) == 2
    assert [strip_control_sequences(line) for line in wrap_ansi(styled_keycap, width=2)] == [
        "1️⃣"
    ]
    sliced = slice_by_column(styled_keycap, start=0, length=2)
    assert strip_control_sequences(sliced.text) == "1️⃣"


def test_visible_width_can_treat_east_asian_ambiguous_symbols_as_wide() -> None:
    try:
        assert visible_width("┌─┐") == 3

        set_ambiguous_width(2)

        assert visible_width("┌─┐") == 6
        assert wrap_cells("┌─┐", width=4) == ["┌─", "┐"]
    finally:
        set_ambiguous_width(1)


def test_ambiguous_width_policy_affects_terminal_diagram_wrapping() -> None:
    diagram = "  ┌──┐"
    try:
        assert wrap_cells(diagram, width=5) == ["  ┌──", "┐"]

        set_ambiguous_width(2)

        assert wrap_cells(diagram, width=5) == ["  ┌", "──", "┐"]
    finally:
        set_ambiguous_width(1)


def test_configure_cell_width_from_environment_sets_ambiguous_width() -> None:
    try:
        configure_cell_width_from_environment({"LOUSHANG_TUI_AMBIGUOUS_WIDTH": "2"})
        assert visible_width("┌─┐") == 6

        configure_cell_width_from_environment({"LOUSHANG_TUI_AMBIGUOUS_WIDTH": "1"})
        assert visible_width("┌─┐") == 3
    finally:
        set_ambiguous_width(1)


def test_normalize_box_drawing_diagram_rebalances_cjk_padding() -> None:
    lines = (
        "  ┌─────────────────────────────────────────────────────────┐",
        "  │  loushang-coding  (产品装配层 - CLI/TUI/Workflow)        │",
        "  │  loushang-channel (边界通信协议层)                        │",
        "  └─────────────────────────────────────────────────────────┘",
    )

    fixed = normalize_box_drawing_diagram(lines)

    assert [visible_width(line) for line in fixed] == [61, 61, 61, 61]
    assert fixed[1] == "  │  loushang-coding  (产品装配层 - CLI/TUI/Workflow)       │"
    assert fixed[2] == "  │  loushang-channel (边界通信协议层)                      │"


def test_normalize_box_drawing_diagram_preserves_right_side_annotations() -> None:
    lines = (
        "  ┌─────────────────────────────────────────┐",
        "  │  Layer 6: 应用层 (UI Parts / Surfaces)   │  Composer, TranscriptView, BottomFrame,",
        "  │                                         │  SelectionSurface, ApprovalSurface, ...",
        "  ├─────────────────────────────────────────┤",
        "  │  Layer 5: 组件框架 (Framework)           │  Renderable, Container, Surface, SurfaceHost,",
        "  │                                         │  ScreenRoot, Focusable",
        "  └─────────────────────────────────────────┘",
    )

    fixed = normalize_box_drawing_diagram(lines)

    assert fixed[1] == "  │  Layer 6: 应用层 (UI Parts / Surfaces)  │  Composer, TranscriptView, BottomFrame,"
    assert fixed[2] == "  │                                         │  SelectionSurface, ApprovalSurface, ..."
    assert fixed[4] == "  │  Layer 5: 组件框架 (Framework)          │  Renderable, Container, Surface, SurfaceHost,"
    assert fixed[5] == "  │                                         │  ScreenRoot, Focusable"
    assert [visible_width(line[: line.rindex("│") + 1]) for line in fixed if "│" in line] == [45, 45, 45, 45]


def test_normalize_box_drawing_diagram_preserves_internal_column_separators() -> None:
    lines = (
        "  ┌─────────────────────────────────────────────────────────────┐",
        "  │      │              │               │             │           │",
        "  │   │建议 │  →   │需理由│   →   │需证据│  →  │需审批│ →  │必须 │",
        "  └─────────────────────────────────────────────────────────────┘",
    )

    fixed = normalize_box_drawing_diagram(lines)

    assert fixed[1].startswith("  │      │              │")
    assert fixed[2].startswith("  │   │建议 │")
    assert not any("│                                                             │" in line for line in fixed)


def test_visible_width_handles_apc_cursor_marker_and_tabs() -> None:
    assert strip_control_sequences(f"a{CURSOR_MARKER}b") == "ab"
    assert visible_width(CURSOR_MARKER) == 0
    assert visible_width("a\tb") == 5


def test_visible_width_matches_pi_osc133_and_thai_lao_fixtures() -> None:
    assert visible_width("\x1b]133;A\x07hello\x1b]133;B\x07") == 5
    assert visible_width("\x1b]133;A\x1b\\hello\x1b]133;B\x1b\\") == 5
    assert visible_width("\t\x1b[31m界\x1b[0m") == 5
    assert visible_width("ำ") == 1
    assert visible_width("ຳ") == 1
    assert visible_width("กำ") == 2
    assert visible_width("ກຳ") == 2


def test_plain_ascii_width_and_truncation_use_fast_path(monkeypatch) -> None:
    def fail_unicode_path(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("plain ASCII should not use Unicode cluster scanning")

    monkeypatch.setattr(cell_width, "_display_grapheme_clusters", fail_unicode_path)
    monkeypatch.setattr(cell_width, "_next_cluster", fail_unicode_path)
    monkeypatch.setattr(cell_width, "_terminal_width", fail_unicode_path)

    assert visible_width("plain ASCII 123") == 15
    assert truncate_to_width("ab", max_width=4, pad=True) == "ab  "
    assert truncate_to_width("abcdef", max_width=4) == "a\x1b[0m...\x1b[0m"


def test_independently_positive_unicode_uses_whole_string_fast_path(monkeypatch) -> None:
    def fail_cluster_path(*_args: object, **_kwargs: object) -> list[str]:
        raise AssertionError("common Unicode text should not require cluster scanning")

    cell_width._visible_width_cached.cache_clear()
    monkeypatch.setattr(cell_width, "_display_grapheme_clusters", fail_cluster_path)

    assert visible_width("fast 中文 🙂") == 12


def test_stateful_or_nonpositive_codepoints_require_cluster_measurement() -> None:
    assert cell_width._requires_cluster_measurement("a‍👨") is True
    assert cell_width._requires_cluster_measurement("‍👨") is True
    assert cell_width._requires_cluster_measurement("ক্🙂") is True
    assert cell_width._requires_cluster_measurement("Aᅡ्🙂") is True
    assert cell_width._requires_cluster_measurement("中ᅡ्🙂") is True
    assert cell_width._requires_cluster_measurement("\u200b🇺🇺") is True
    assert cell_width._requires_cluster_measurement("🇺\n🇺") is True
    assert cell_width._requires_cluster_measurement("👨\u200b\u200b\u200b🏽") is True
    assert cell_width._requires_cluster_measurement("❤\u200b\u200b\u200b️") is True
    assert cell_width._requires_cluster_measurement("A\u200b\u200b\u200bा") is True
    assert cell_width._requires_cluster_measurement("🇸e🇺⃣্🏽າ") is True
    assert cell_width._requires_cluster_measurement("1️⃣") is True
    assert cell_width._requires_cluster_measurement("👨‍💻") is True
    assert cell_width._requires_cluster_measurement("é") is True
    assert cell_width._requires_cluster_measurement("🇺🇸") is True
    assert cell_width._requires_cluster_measurement("👍🏽") is True

    assert cell_width._requires_cluster_measurement("fast 中文 🙂") is False


def test_strip_control_sequences_skips_scan_without_escape(monkeypatch) -> None:
    def fail_extract(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("text without escapes should not scan for control sequences")

    monkeypatch.setattr(cell_width, "_extract_control_sequence", fail_extract)

    assert strip_control_sequences("plain 中文 text") == "plain 中文 text"


def test_repeated_wide_character_width_uses_cache(monkeypatch) -> None:
    cache_clear = getattr(cell_width._cluster_width, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()

    calls = 0
    original = cell_width._terminal_width

    def count_terminal_width(*args: object, **kwargs: object) -> int:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(cell_width, "_terminal_width", count_terminal_width)

    assert wrap_cells("龘龘龘", width=10) == ["龘龘龘"]
    assert wrap_cells("龘龘龘", width=10) == ["龘龘龘"]
    assert calls == 1


def test_normalize_terminal_output_decomposes_thai_lao_am_vowels() -> None:
    assert normalize_terminal_output("\u0e33") == "\u0e4d\u0e32"
    assert normalize_terminal_output("\u0eb3") == "\u0ecd\u0eb2"
    assert visible_width(normalize_terminal_output("ำabc")) == visible_width("ำabc")
    assert visible_width(normalize_terminal_output("ຳabc")) == visible_width("ຳabc")


def test_wrap_cells_printable_ascii_preserves_rows_without_grapheme_scan(
    monkeypatch,
) -> None:
    def fail(_text: str) -> list[str]:
        raise AssertionError("printable ASCII must not scan Unicode graphemes")

    monkeypatch.setattr(cell_width, "_display_grapheme_clusters", fail)
    assert wrap_cells("\x1b[31mabc def  \x1b[0m\n\nxyz\n", width=4) == [
        "abc ",
        "def ",
        " ",
        "",
        "xyz",
        "",
    ]
    assert wrap_cells("", width=1) == [""]
    assert wrap_cells("a" * 20000, width=80) == ["a" * 80] * 250


def test_wrap_cells_preserves_explicit_newlines_and_wraps_by_cell_width() -> None:
    assert wrap_cells("abcd", width=3) == ["abc", "d"]
    assert wrap_cells("中ab", width=3) == ["中a", "b"]
    assert wrap_cells("ab\ncd", width=10) == ["ab", "cd"]


def test_wrap_ansi_preserves_active_style_after_wrapping() -> None:
    lines = wrap_ansi("\x1b[31mred blue\x1b[0m", width=4)

    assert [strip_control_sequences(line) for line in lines] == ["red", "blue"]
    assert lines[0].startswith("\x1b[31m")
    assert lines[1].startswith("\x1b[31m")
    assert all(visible_width(line) <= 4 for line in lines)


def test_wrap_ansi_preserves_style_and_hyperlink_across_unwrapped_line() -> None:
    assert wrap_ansi("\x1b[31mred blue\nnext long text\x1b[0m", width=9) == [
        "\x1b[31mred blue",
        "\x1b[31mnext long",
        "\x1b[31mtext\x1b[0m",
    ]

    open_link = "\x1b]8;;https://x\x07"
    close_link = "\x1b]8;;\x07"
    assert wrap_ansi(f"{open_link}link\nmore link{close_link}", width=8) == [
        f"{open_link}link",
        f"{open_link}more{close_link}",
        f"{open_link}link{close_link}",
    ]


def test_wrap_ansi_does_not_apply_underline_before_styled_text() -> None:
    underline_on = "\x1b[4m"
    underline_off = "\x1b[24m"
    url = "https://example.com/very/long/path/that/will/wrap"

    lines = wrap_ansi(f"read this thread {underline_on}{url}{underline_off}", width=40)

    assert lines[0] == "read this thread"
    assert lines[1].startswith(underline_on)
    assert "https://" in lines[1]


def test_wrap_ansi_preserves_background_without_full_reset_between_lines() -> None:
    text = "\x1b[44mhello world this is blue background text\x1b[0m"

    lines = wrap_ansi(text, width=15)

    assert len(lines) > 1
    assert all(line.startswith("\x1b[44m") for line in lines)
    assert all(not line.endswith("\x1b[0m") for line in lines[:-1])


def test_wrap_ansi_closes_underline_but_keeps_background_active() -> None:
    underline_on = "\x1b[4m"
    underline_off = "\x1b[24m"
    text = f"\x1b[41mprefix {underline_on}UNDERLINED_CONTENT_THAT_WRAPS{underline_off} suffix\x1b[0m"

    lines = wrap_ansi(text, width=20)

    assert len(lines) > 1
    assert all(line.startswith("\x1b[41m") or line.startswith("\x1b[4;41m") for line in lines)
    for line in lines[:-1]:
        if underline_on in line and underline_off not in line:
            assert line.endswith(underline_off)
            assert not line.endswith("\x1b[0m")


def test_wrap_ansi_reopens_and_closes_osc8_hyperlinks_across_lines() -> None:
    url = "https://example.com"
    open_link = f"\x1b]8;;{url}\x1b\\"
    close_link = "\x1b]8;;\x1b\\"

    lines = wrap_ansi(f"{open_link}0123456789{close_link}", width=6)

    assert [strip_control_sequences(line) for line in lines] == ["012345", "6789"]
    assert all(line.startswith(open_link) for line in lines)
    assert lines[0].endswith(close_link)


def test_wrap_ansi_preserves_bel_osc8_terminator_on_continuation_lines() -> None:
    url = f"https://example.com/oauth/{'a' * 32}"
    open_link = f"\x1b]8;;{url}\x07"
    close_link = "\x1b]8;;\x07"

    lines = wrap_ansi(f"{open_link}{url}{close_link}", width=20)

    assert len(lines) > 1
    assert all(open_link in line for line in lines)
    assert all(f"\x1b]8;;{url}\x1b\\" not in line for line in lines)
    assert all(line.endswith(close_link) for line in lines[:-1])


def test_wrap_ansi_matches_pi_regional_indicator_streaming_width_fixture() -> None:
    wrapped = wrap_ansi("      - 🇨", width=9)

    assert [strip_control_sequences(line) for line in wrapped] == ["      -", "🇨"]
    assert [visible_width(line) for line in wrapped] == [7, 2]


def test_wrap_ansi_matches_pi_common_streaming_emoji_width_fixtures() -> None:
    for sample in ("👍", "👍🏻", "✅", "⚡", "⚡️", "👨", "👨\u200d💻", "🏳️\u200d🌈"):
        assert visible_width(sample) == 2


def test_slice_by_column_preserves_whole_wide_clusters() -> None:
    assert slice_by_column("a中bc", start=1, length=2).text == "中"
    assert slice_by_column("a中bc", start=2, length=2).text == "b"
    assert slice_by_column("a中bc", start=2, length=2, strict=False).text == "中b"
    assert slice_with_width("abcdef", start=2, length=3).width == 3


def test_truncate_to_width_uses_cell_width_and_optional_padding() -> None:
    assert truncate_to_width("abcdef", max_width=4) == "a\x1b[0m...\x1b[0m"
    assert truncate_to_width("ab", max_width=4, pad=True) == "ab  "

    red = "\x1b[31mabcdef\x1b[0m"
    truncated = truncate_to_width(red, max_width=4)
    assert visible_width(truncated) == 4
    assert truncated.startswith("\x1b[31m")
    assert truncated.endswith("\x1b[0m...\x1b[0m")


def test_truncate_to_width_brackets_ellipsis_with_resets_like_pi() -> None:
    assert truncate_to_width("abcdef", max_width=1, ellipsis="🙂") == ""
    assert truncate_to_width("abcdef", max_width=2, ellipsis="🙂") == "\x1b[0m🙂\x1b[0m"
    assert truncate_to_width("a", max_width=2, ellipsis="🙂") == "a"
    assert truncate_to_width("界", max_width=2, ellipsis="🙂") == "界"


def test_truncate_to_width_keeps_contiguous_prefix_before_wide_overflow_like_pi() -> None:
    truncated = truncate_to_width("🙂\t界 \x1b_abc\x07", max_width=7, ellipsis="…", pad=True)

    assert truncated == "🙂\t\x1b[0m…\x1b[0m "
    assert visible_width(truncated) == 7


def test_truncate_to_width_matches_pi_large_unicode_and_malformed_escape_fixtures() -> None:
    unicode_truncated = truncate_to_width("🙂界" * 1_000, max_width=40, ellipsis="…")
    malformed_truncated = truncate_to_width(f"abc\x1bnot-ansi {'🙂' * 100}", max_width=20, ellipsis="…")
    no_ellipsis = truncate_to_width(f"\x1b[31m{'hello' * 100}", max_width=10, ellipsis="")

    assert visible_width(unicode_truncated) <= 40
    assert unicode_truncated.endswith("…\x1b[0m")
    assert visible_width(malformed_truncated) <= 20
    assert visible_width(no_ellipsis) <= 10
    assert no_ellipsis.endswith("\x1b[0m")


def test_visible_width_distinguishes_text_and_emoji_presentation() -> None:
    """Text-default symbols (Text_Presentation) are single-width;
    the same symbol with U+FE0F (VS16) becomes emoji-width.
    Symbols whose East_Asian_Width is W remain double-width.
    """
    # Text presentation (no VS16)
    assert visible_width(chr(0x26A0)) == 1  # ⚠
    assert visible_width(chr(0x2600)) == 1  # ☀
    assert visible_width(chr(0x261A)) == 1  # ☚
    # Emoji presentation (with VS16)
    assert visible_width(chr(0x26A0) + chr(0xFE0F)) == 2  # ⚠️
    assert visible_width(chr(0x2600) + chr(0xFE0F)) == 2  # ☀️
    # Default double-width via East_Asian_Width=W
    assert visible_width(chr(0x2615)) == 2  # ☕
    assert visible_width(chr(0x26A1)) == 2  # ⚡
    assert visible_width(chr(0x2705)) == 2  # ✅


def test_wrap_cells_rejects_non_positive_width() -> None:
    try:
        wrap_cells("abc", width=0)
    except ValueError as exc:
        assert str(exc) == "width must be positive"
    else:
        raise AssertionError("expected ValueError")
