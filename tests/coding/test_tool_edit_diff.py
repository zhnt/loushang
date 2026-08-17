from __future__ import annotations

import pytest

from loushang.harness.tools.workspace.edit_diff import (
    apply_edits_to_normalized_content,
    apply_text_edits,
    build_unified_diff,
    compute_edits_diff_for_content,
    detect_line_ending,
    first_changed_line,
    fuzzy_find_text,
    generate_diff_string,
    normalize_for_fuzzy_match,
    normalize_to_lf,
    restore_line_endings,
    strip_bom,
)


def test_edit_diff_normalizes_and_restores_line_endings() -> None:
    assert detect_line_ending("alpha\r\nbeta\n") == "\r\n"
    assert detect_line_ending("alpha\nbeta\r\n") == "\n"
    assert normalize_to_lf("alpha\r\nbeta\rgamma\n") == "alpha\nbeta\ngamma\n"
    assert restore_line_endings("alpha\nbeta\n", "\r\n") == "alpha\r\nbeta\r\n"
    assert restore_line_endings("alpha\nbeta\n", "\n") == "alpha\nbeta\n"


def test_edit_diff_strips_bom_without_losing_text() -> None:
    stripped = strip_bom("\ufeffalpha")
    assert stripped.bom == "\ufeff"
    assert stripped.text == "alpha"

    plain = strip_bom("alpha")
    assert plain.bom == ""
    assert plain.text == "alpha"


def test_fuzzy_find_text_normalizes_smart_punctuation_and_trailing_whitespace() -> None:
    content = "message = \u201chello\u201d  \nprice\u00a0=\u00a01\nrange = 1\u20133\n"
    old_text = 'message = "hello"\nprice = 1\nrange = 1-3\n'

    match = fuzzy_find_text(content, old_text)

    assert match.found is True
    assert match.index == 0
    assert match.used_fuzzy_match is True
    assert match.content_for_replacement == normalize_for_fuzzy_match(content)


def test_apply_edits_to_normalized_content_uses_original_content_for_all_offsets() -> (
    None
):
    result = apply_edits_to_normalized_content(
        "alpha = 1\nbeta = 2\ngamma = 3\n",
        [
            {"oldText": "alpha = 1", "newText": "alpha = 10"},
            {"oldText": "gamma = 3", "newText": "gamma = 30"},
        ],
        path="main.py",
    )

    assert result.base_content == "alpha = 1\nbeta = 2\ngamma = 3\n"
    assert result.new_content == "alpha = 10\nbeta = 2\ngamma = 30\n"


def test_apply_text_edits_preserves_bom_and_crlf_line_endings() -> None:
    result = apply_text_edits(
        "\ufeffalpha\r\nbeta\r\n",
        [{"oldText": "alpha\nbeta\n", "newText": "ALPHA\nBETA\n"}],
        path="main.py",
    )

    assert result == "\ufeffALPHA\r\nBETA\r\n"


def test_apply_edits_to_normalized_content_rejects_duplicate_and_overlapping_edits() -> (
    None
):
    with pytest.raises(ValueError, match=r"edits\[0\].*matched more than once"):
        apply_edits_to_normalized_content(
            "repeat\nrepeat\n",
            [{"oldText": "repeat", "newText": "new"}],
            path="main.py",
        )

    with pytest.raises(ValueError, match=r"edits\[0\].*edits\[1\].*overlap"):
        apply_edits_to_normalized_content(
            "one\ntwo\nthree\n",
            [
                {"oldText": "one\ntwo\n", "newText": "ONE\nTWO\n"},
                {"oldText": "two\nthree\n", "newText": "TWO\nTHREE\n"},
            ],
            path="main.py",
        )


def test_build_unified_diff_and_first_changed_line() -> None:
    original = "alpha\nbeta\n"
    updated = "alpha\nBETA\n"

    diff = build_unified_diff("main.py", original, updated)

    assert "--- main.py" in diff
    assert "+++ main.py" in diff
    assert "-beta" in diff
    assert "+BETA" in diff
    assert first_changed_line(original, updated) == 2


def test_generate_diff_string_returns_numbered_preview_diff() -> None:
    result = generate_diff_string("alpha\nbeta\ngamma\n", "alpha\nBETA\ngamma\n")

    assert "-2 beta" in result.diff
    assert "+2 BETA" in result.diff
    assert result.first_changed_line == 2


def test_compute_edits_diff_for_content_returns_preview_without_writing() -> None:
    result = compute_edits_diff_for_content(
        "main.py",
        "\ufeffalpha\r\nbeta\r\n",
        [{"oldText": "beta", "newText": "BETA"}],
    )

    assert "-2 beta" in result.diff
    assert "+2 BETA" in result.diff
    assert result.first_changed_line == 2
