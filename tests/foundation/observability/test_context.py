from __future__ import annotations

from contextvars import copy_context

from loushang.foundation.observability.context import current_context, log_context


def test_log_context_binds_nested_values_and_restores_previous_context() -> None:
    assert current_context().session_id is None

    with log_context(session_id="s1", run_id=4, cwd="/repo", mode="tui"):
        ctx = current_context()
        assert ctx.session_id == "s1"
        assert ctx.run_id == 4
        assert ctx.cwd == "/repo"
        assert ctx.mode == "tui"

        with log_context(run_id=5):
            nested = current_context()
            assert nested.session_id == "s1"
            assert nested.run_id == 5
            assert nested.cwd == "/repo"
            assert nested.mode == "tui"

        restored = current_context()
        assert restored.session_id == "s1"
        assert restored.run_id == 4

    assert current_context().session_id is None
    assert current_context().run_id is None


def test_log_context_isolated_copy_retains_its_captured_value() -> None:
    with log_context(session_id="captured", run_id=1):
        captured = copy_context()

    with log_context(session_id="current", run_id=2):
        assert current_context().session_id == "current"
        assert captured.run(current_context).session_id == "captured"
        assert captured.run(current_context).run_id == 1

    assert current_context().session_id is None
    assert current_context().run_id is None
