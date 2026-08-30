from __future__ import annotations

from loushang.coding._cleanup import run_cleanup_steps


def test_cleanup_steps_preserve_primary_failure_and_attempt_every_owner() -> None:
    calls: list[str] = []
    primary = RuntimeError("construction failed")

    def fail_lsp() -> None:
        calls.append("lsp")
        raise OSError("lsp cleanup failed")

    def close_base() -> None:
        calls.append("base")

    settled = run_cleanup_steps(
        primary,
        (
            ("Coding LSP cleanup", fail_lsp),
            ("Coding base cleanup", close_base),
        ),
    )

    assert settled is primary
    assert calls == ["lsp", "base"]
    assert primary.__notes__ == [
        "Coding LSP cleanup also failed: lsp cleanup failed"
    ]
