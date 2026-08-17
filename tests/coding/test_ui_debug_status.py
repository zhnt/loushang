from __future__ import annotations


def test_debug_status_text_includes_paths_scopes_and_diag_export_command(tmp_path) -> None:
    from loushang.coding.diagnostics.debug_status import debug_status_text

    debug_path = tmp_path / "debug.log"

    text = debug_status_text(debug_path, scopes=("tui", "agent"), cwd="/repo")

    assert "Debug logging enabled:" in text
    assert str(debug_path) in text
    assert str(debug_path.parent / "latest") in text
    assert "Scopes: tui,agent" in text
    assert "Diagnostics bundle:" in text
    assert (
        "loushang diag export --cwd /repo --output /repo/.loushang/diagnostics/loushang-diag.zip "
        f"--debug-file {debug_path}"
    ) in text


def test_debug_status_text_shows_recent_problem_lines_from_debug_file(tmp_path) -> None:
    from loushang.coding.diagnostics.debug_status import debug_status_text
    from loushang.foundation.observability._router import reset_observability

    debug_path = tmp_path / "debug.log"
    debug_path.write_text(
        "\n".join(
            [
                "DEBUG module ignored",
                "2026-05-14T00:00:00Z WARNING module retrying provider",
                "2026-05-14T00:00:00Z PROBLEM error provider_request_cancelled source=provider",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    reset_observability()
    text = debug_status_text(debug_path)

    assert "Recent debug problems:" in text
    assert "WARNING module retrying provider" in text
    assert "provider_request_cancelled" in text
    assert "DEBUG module ignored" not in text
