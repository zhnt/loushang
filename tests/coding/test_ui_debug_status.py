from __future__ import annotations


def _runtime_identity() -> dict[str, object]:
    return {
        "package_version": "0.1.0",
        "entrypoint": "/repo/.venv/bin/loushang",
        "python_executable": "/repo/.venv/bin/python",
        "module_file": "/repo/src/loushang/__init__.py",
        "install_mode": "editable",
        "launch_mode": "virtualenv-console-script",
        "source_git_commit": "abc123",
        "source_git_dirty": True,
        "provenance_schema_version": 1,
        "provenance_scope": "installation",
        "components": {
            "native-screen": {
                "kind": "renderer",
                "availability": "bundled",
                "contract_version": 1,
                "module_file": "/repo/src/loushang/tui/__init__.py",
            }
        },
    }


def test_debug_status_text_includes_paths_scopes_and_diag_export_command(tmp_path) -> None:
    from loushang.coding.diagnostics.debug_status import debug_status_text

    debug_path = tmp_path / "debug.log"

    text = debug_status_text(
        debug_path,
        scopes=("tui", "agent"),
        cwd="/repo",
        runtime_identity=_runtime_identity(),
    )

    assert "Debug logging enabled:" in text
    assert str(debug_path) in text
    assert str(debug_path.parent / "latest") in text
    assert "Scopes: tui,agent" in text
    assert "Runtime provenance:" in text
    assert "entrypoint: /repo/.venv/bin/loushang" in text
    assert "python_executable: /repo/.venv/bin/python" in text
    assert "module_file: /repo/src/loushang/__init__.py" in text
    assert "install_mode: editable" in text
    assert "launch_mode: virtualenv-console-script" in text
    assert "source_git_commit: abc123" in text
    assert "source_git_dirty: True" in text
    assert "provenance_scope: installation" in text
    assert "  native-screen:" in text
    assert "    kind: renderer" in text
    assert "    availability: bundled" in text
    assert "    contract_version: 1" in text
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
    text = debug_status_text(debug_path, runtime_identity=_runtime_identity())

    assert "Recent debug problems:" in text
    assert "WARNING module retrying provider" in text
    assert "provider_request_cancelled" in text
    assert "DEBUG module ignored" not in text
