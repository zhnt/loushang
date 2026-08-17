from __future__ import annotations

from types import SimpleNamespace


def test_session_label_falls_back_when_session_name_property_fails() -> None:
    from loushang.harnesstui.conversation.session_view import session_label

    class BrokenSessionName:
        session_id = "fallback-session"

        @property
        def session_name(self):
            raise ValueError("broken")

    assert session_label(BrokenSessionName()) == "fallback-session"


def test_is_running_reads_common_session_state_shapes() -> None:
    from loushang.harnesstui.conversation.session_view import is_running

    assert is_running(SimpleNamespace(isStreaming=True)) is True
    assert is_running(SimpleNamespace(is_streaming=True)) is True
    assert is_running(SimpleNamespace(isStreaming=False, is_streaming=False)) is False
    assert is_running(SimpleNamespace(is_running=lambda: True)) is True


def test_session_error_message_checks_session_agent_and_agent_state() -> None:
    from loushang.harnesstui.conversation.session_view import session_error_message

    assert session_error_message(SimpleNamespace(error_message="session failed")) == "session failed"
    assert session_error_message(SimpleNamespace(agent=SimpleNamespace(error_message="agent failed"))) == "agent failed"
    assert (
        session_error_message(SimpleNamespace(agent=SimpleNamespace(state=SimpleNamespace(error_message="state failed"))))
        == "state failed"
    )
    assert session_error_message(SimpleNamespace()) is None


def test_session_cwd_prefers_session_manager_then_runtime(tmp_path) -> None:
    from loushang.harnesstui.conversation.session_view import session_cwd

    session_cwd_path = tmp_path / "session"
    runtime_cwd_path = tmp_path / "runtime"

    session = SimpleNamespace(session_manager=SimpleNamespace(get_cwd=lambda: session_cwd_path))
    runtime = SimpleNamespace(get_cwd=lambda: runtime_cwd_path)

    assert session_cwd(session=session, runtime=runtime) == str(session_cwd_path)
    assert session_cwd(session=SimpleNamespace(), runtime=runtime) == str(runtime_cwd_path)

