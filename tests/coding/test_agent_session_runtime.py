from __future__ import annotations

import asyncio
from datetime import date
from functools import wraps
from pathlib import Path

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage


def _async_test(test):
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))

    return run


def _runtime_footer(cwd: Path) -> str:
    return f"Current date: {date.today().isoformat()}\nCurrent working directory: {cwd.as_posix()}"


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost={},
    )


def _user_message(text: str) -> UserMessage:
    return UserMessage(
        role="user",
        content=[TextPart(type="text", text=text)],
        timestamp=0.0,
    )


def _assistant_message(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


@_async_test
async def test_session_publishes_receipt_backed_events_for_every_new_commit(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.harness.events import TranscriptRecordCommitted

    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        persist=False,
    )
    session = await runtime.create_session(cwd=str(tmp_path))
    seen = []
    session.subscribe_runtime_events(seen.append)

    record_id = await session.session_manager.append_custom_entry("demo", {"ok": True})
    await asyncio.sleep(0)

    assert len(seen) == 1
    event = seen[0]
    assert event.kind == "transcript.record_committed"
    assert event.source_record_id == record_id
    assert isinstance(event.payload, TranscriptRecordCommitted)
    assert event.payload.record_id == record_id
    assert event.payload.revision == 1
    assert event.payload.committed_at.tzinfo is not None


@_async_test
async def test_session_uses_one_runtime_stream_with_product_projection(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.harness.events import ConversationMetadataChanged

    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        persist=False,
    )
    session = await runtime.create_session(cwd=str(tmp_path))
    runtime_events = []
    product_events = []
    session.subscribe_runtime_events(runtime_events.append)
    session.subscribe(product_events.append)

    await session.set_session_name("Demo")

    assert [event.kind for event in runtime_events] == [
        "transcript.record_committed",
        "session.session_info_changed",
    ]
    assert [event.sequence for event in runtime_events] == [1, 2]
    assert runtime_events[0].source_record_id == runtime_events[1].source_record_id
    assert isinstance(runtime_events[1].payload, ConversationMetadataChanged)
    assert product_events == [{"type": "session_info_changed", "name": "Demo"}]


@_async_test
async def test_session_normalizes_gateway_audit_sequence_into_runtime_stream(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.harness.events import ToolPolicyAuditEvent

    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        persist=False,
    )
    session = await runtime.create_session(cwd=str(tmp_path))
    runtime_events = []
    product_events = []
    session.subscribe_runtime_events(runtime_events.append)
    session.subscribe(product_events.append)

    event_types = (
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_requested",
        "tool_approval_resolved",
        "tool_execution_started",
        "tool_execution_completed",
        "tool_execution_failed",
    )
    for event_type in event_types:
        await session._dispatch_event(
            {
                "type": event_type,
                "tool_name": "write",
                "action_fingerprint": "f" * 64,
            }
        )

    assert [event.kind for event in runtime_events] == [
        f"session.{event_type}" for event_type in event_types
    ]
    assert [event.payload for event in runtime_events] == [
        ToolPolicyAuditEvent(
            event_type,
            {"tool_name": "write", "action_fingerprint": "f" * 64},
        )
        for event_type in event_types
    ]
    assert product_events == [
        {
            "type": event_type,
            "tool_name": "write",
            "action_fingerprint": "f" * 64,
        }
        for event_type in event_types
    ]


@_async_test
async def test_session_emits_auditable_permission_profile_changes(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import (
        create_agent_session_runtime,
        create_services,
    )
    from loushang.harness.config.agent import SettingsManager
    from loushang.harness.events import PermissionProfileChanged

    settings = SettingsManager(
        global_settings_path=tmp_path / "settings.json",
        project_settings_path=tmp_path / "project-settings.json",
    )
    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        services=create_services(settings_manager=settings),
        persist=False,
    )
    session = await runtime.create_session(cwd=str(tmp_path))
    runtime_events = []
    session.subscribe_runtime_events(runtime_events.append)

    accepted = await session.apply_approval_permission_action(
        "set-profile:project:cautious"
    )

    assert accepted is True
    assert settings.get_permission_profile_id() == "cautious"
    assert runtime_events[-1].kind == "session.permission_profile_changed"
    assert runtime_events[-1].payload == PermissionProfileChanged(
        previous_profile_id="standard",
        requested_profile_id="cautious",
        effective_profile_id="cautious",
        scope="project",
    )


@_async_test
async def test_runtime_listener_failure_does_not_duplicate_agent_message(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        persist=False,
    )
    session = await runtime.create_session(cwd=str(tmp_path))
    commit_events = 0
    failed_message_events = 0

    def fail_first_message_projection(event) -> None:
        nonlocal commit_events, failed_message_events
        if event.kind == "transcript.record_committed":
            commit_events += 1
        if event.kind == "agent.message_end" and failed_message_events == 0:
            failed_message_events += 1
            raise RuntimeError("message projection failed")

    session.subscribe_runtime_events(fail_first_message_projection)
    message = _assistant_message("answer")
    event = {"type": "message_end", "message": message}

    try:
        await session._composition.session_runtime.handle_agent_event(
            event, session.agent.signal
        )
    except RuntimeError as exc:
        assert str(exc) == "message projection failed"
    else:
        raise AssertionError("message projection failure must propagate")
    await session._composition.session_runtime.handle_agent_event(
        event, session.agent.signal
    )

    assert commit_events == 1
    assert failed_message_events == 1
    assert len(session.session_manager.get_entries()) == 1


@_async_test
async def test_runtime_create_switch_and_list_sessions(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()

    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )

    first = await runtime.create_session(cwd=str(project_a))
    await first.session_manager.append_message(_user_message("first"))

    second_manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(project_b.resolve()), persist=True
    )
    await second_manager.append_message(_user_message("second"))
    assert second_manager.session_file is not None

    switched = await runtime.switch_session(second_manager.session_file)
    records = runtime.list_sessions()

    assert runtime.get_current_session() is switched
    assert [
        message.content[0].text for message in switched.get_session_context().messages
    ] == ["second"]
    assert [record.cwd for record in records] == [
        str(project_b.resolve()),
        str(project_a.resolve()),
    ]


@_async_test
async def test_runtime_clone_session_forks_current_leaf(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    session = await runtime.create_session(cwd=str(project))
    await session.session_manager.append_message(_user_message("first"))
    await session.session_manager.append_message(_assistant_message("second"))
    leaf_id = session.session_manager.get_leaf_id()

    cloned = await runtime.clone_session()

    assert runtime.get_current_session() is cloned
    assert cloned.session_manager.session_file != session.session_manager.session_file
    assert cloned.session_manager.get_leaf_id() == leaf_id
    assert [
        message.content[0].text for message in cloned.get_session_context().messages
    ] == ["first", "second"]


@_async_test
async def test_runtime_lists_session_summaries(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    session = await runtime.create_session(cwd=str(project))
    await session.set_session_name("Runtime Summary")
    await session.set_model(_model())
    await session.session_manager.append_message(
        _user_message("summarize runtime sessions")
    )

    summaries = runtime.list_session_summaries()

    assert len(summaries) == 1
    assert summaries[0].session_id == session.session_id
    assert summaries[0].name == "Runtime Summary"
    assert summaries[0].last_message_preview == "summarize runtime sessions"
    assert summaries[0].model == {
        "provider": "faux",
        "endpoint_id": "anthropic-messages",
        "model_id": "faux-model",
    }


@_async_test
async def test_runtime_finds_session_summaries(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.harness.transcript import SessionQuery

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )

    first = await runtime.create_session(cwd=str(project_a))
    await first.set_session_name("Alpha")
    await first.session_manager.append_message(_user_message("alpha repository task"))

    second = await runtime.create_session(
        cwd=str(project_b), parent_session=str(first.get_session_file())
    )
    await second.set_session_name("Beta")
    await second.session_manager.append_message(_user_message("beta follow up"))

    summaries = runtime.find_session_summaries(
        SessionQuery(name="bet", text="follow", limit=1)
    )

    assert [summary.session_id for summary in summaries] == [second.session_id]


@_async_test
async def test_runtime_renames_and_deletes_sessions_by_resolved_reference(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    current = await runtime.create_session(cwd=str(project))

    other_manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(project), persist=True
    )
    await other_manager.append_message(_user_message("other"))
    other_file = other_manager.get_session_file()
    assert other_file is not None

    renamed = await runtime.rename_session(
        other_manager.get_header().conversation_id[:4], "Other Session"
    )
    deleted = await runtime.delete_session(
        other_manager.get_header().conversation_id[:4]
    )

    assert renamed.name == "Other Session"
    assert deleted is True
    assert other_file.exists() is False
    assert current.session_manager.get_session_file() is not None
    assert current.session_manager.get_session_file().exists() is False


@_async_test
async def test_runtime_delete_session_refuses_current_session(tmp_path) -> None:
    import pytest

    from loushang.coding.bootstrap import create_agent_session_runtime

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    current = await runtime.create_session(cwd=str(project))
    await current.session_manager.append_message(_user_message("current"))
    session_file = current.session_manager.get_session_file()
    assert session_file is not None

    with pytest.raises(ValueError, match="currently active session"):
        await runtime.delete_session(session_file)

    assert session_file.exists() is True


@_async_test
async def test_runtime_rename_session_records_failure_diagnostic(tmp_path) -> None:
    import pytest

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.diagnostics_service = None
            self.session_id = manager.get_header().conversation_id

    project = tmp_path / "project"
    project.mkdir()
    diagnostics_service = DiagnosticsService()
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=DummySession,
        persist=True,
        diagnostics_service=diagnostics_service,
    )
    current = await runtime.create_session(cwd=str(project))

    with pytest.raises(FileNotFoundError):
        await runtime.rename_session("missing-session", "New Name")

    records = diagnostics_service.get_diagnostics(
        query=DiagnosticsQuery(code="session_rename_failed")
    )

    assert runtime.get_current_session() is current
    assert len(records) == 1
    assert records[0].session_id == current.session_id
    assert records[0].details == {
        "operation": "rename_session",
        "session_ref": "missing-session",
        "target_session_file": None,
        "name": "New Name",
    }


@_async_test
async def test_runtime_delete_session_records_failure_diagnostic(tmp_path) -> None:
    import pytest

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.diagnostics_service = None
            self.session_id = manager.get_header().conversation_id

    project = tmp_path / "project"
    project.mkdir()
    diagnostics_service = DiagnosticsService()
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=DummySession,
        persist=True,
        diagnostics_service=diagnostics_service,
    )
    current = await runtime.create_session(cwd=str(project))

    with pytest.raises(FileNotFoundError):
        await runtime.delete_session("missing-session")

    records = diagnostics_service.get_diagnostics(
        query=DiagnosticsQuery(code="session_delete_failed")
    )

    assert runtime.get_current_session() is current
    assert len(records) == 1
    assert records[0].session_id == current.session_id
    assert records[0].details == {
        "operation": "delete_session",
        "session_ref": "missing-session",
        "target_session_file": None,
    }


@_async_test
async def test_runtime_lists_all_session_summaries_across_session_dirs(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    sessions_root = tmp_path / "sessions"
    runtime_a = create_agent_session_runtime(
        session_dir=sessions_root / "project-a", model=_model(), persist=True
    )
    runtime_b = create_agent_session_runtime(
        session_dir=sessions_root / "project-b", model=_model(), persist=True
    )

    first = await runtime_a.create_session(cwd=str(project_a))
    await first.set_session_name("Alpha")
    await first.session_manager.append_message(_user_message("alpha"))
    second = await runtime_b.create_session(cwd=str(project_b))
    await second.set_session_name("Beta")
    await second.session_manager.append_message(_user_message("beta"))

    summaries = runtime_a.list_all_session_summaries()

    assert {summary.session_id for summary in summaries} == {
        first.session_id,
        second.session_id,
    }
    assert {summary.name for summary in summaries} == {"Alpha", "Beta"}


@_async_test
async def test_runtime_finds_all_session_summaries_across_session_dirs(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.harness.transcript import SessionQuery

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    sessions_root = tmp_path / "sessions"
    runtime_a = create_agent_session_runtime(
        session_dir=sessions_root / "project-a", model=_model(), persist=True
    )
    runtime_b = create_agent_session_runtime(
        session_dir=sessions_root / "project-b", model=_model(), persist=True
    )

    first = await runtime_a.create_session(cwd=str(project_a))
    await first.set_session_name("Alpha")
    second = await runtime_b.create_session(cwd=str(project_b))
    await second.set_session_name("Beta")
    await second.session_manager.append_message(_user_message("global lookup target"))

    summaries = runtime_a.find_all_session_summaries(SessionQuery(text="lookup target"))

    assert [summary.session_id for summary in summaries] == [second.session_id]


@_async_test
async def test_runtime_exposes_indexed_session_summary_facades(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.harness.transcript import SessionQuery

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    sessions_root = tmp_path / "sessions"
    runtime_a = create_agent_session_runtime(
        session_dir=sessions_root / "project-a", model=_model(), persist=True
    )
    runtime_b = create_agent_session_runtime(
        session_dir=sessions_root / "project-b", model=_model(), persist=True
    )

    first = await runtime_a.create_session(cwd=str(project_a))
    await first.session_manager.append_message(_user_message("indexed alpha"))
    second = await runtime_b.create_session(cwd=str(project_b))
    await second.session_manager.append_message(_user_message("indexed beta"))

    assert [summary.session_id for summary in runtime_a.refresh_session_index()] == [
        first.session_id
    ]
    assert [
        summary.session_id for summary in runtime_a.list_indexed_session_summaries()
    ] == [first.session_id]
    assert [
        summary.session_id
        for summary in runtime_a.find_indexed_session_summaries(
            SessionQuery(text="alpha")
        )
    ] == [first.session_id]
    assert [
        summary.session_id for summary in runtime_a.refresh_all_session_indexes()
    ] == [second.session_id, first.session_id]
    assert [
        summary.session_id
        for summary in runtime_a.find_all_indexed_session_summaries(
            SessionQuery(text="beta")
        )
    ] == [second.session_id]


@_async_test
async def test_runtime_auto_refreshes_session_index_after_replacement(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    runtime.auto_refresh_session_index = True
    runtime.session_index_flush_delay = 0.01

    async def scenario():
        session = await runtime.create_session(cwd=str(project))
        assert not SessionManager.index_file(tmp_path).exists()
        await runtime.drain_session_index_flush()
        return session

    session = await scenario()

    assert SessionManager.index_file(tmp_path).exists()
    assert [
        summary.session_id for summary in runtime.list_indexed_session_summaries()
    ] == []
    session_file = session.session_manager.get_session_file()
    assert session_file is not None
    assert session_file.exists() is False


@_async_test
async def test_runtime_dispose_publishes_latest_session_summary(tmp_path) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        persist=True,
    )
    session = await runtime.create_session(cwd=str(project))
    await session.session_manager.append_message(
        UserMessage(role="user", content="first", timestamp=1.0)
    )
    runtime.refresh_session_index()
    await session.session_manager.append_message(
        UserMessage(role="user", content="hi", timestamp=2.0)
    )

    await runtime.dispose_session_runtime()

    summaries = SessionManager.load_index(tmp_path)
    assert len(summaries) == 1
    assert summaries[0].last_message_preview == "hi"
    assert summaries[0].entry_count == 2


@_async_test
async def test_runtime_incrementally_repairs_current_summary_before_continuity_query(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        persist=True,
    )
    session = await runtime.create_session(cwd=str(tmp_path))
    await session.session_manager.append_message(_user_message("first"))
    runtime.refresh_session_index()
    await session.session_manager.append_message(_user_message("latest"))
    catalog = runtime.session_catalog

    assert catalog.try_query_index_snapshot().index_state == "stale"
    runtime.repair_session_index()

    published = catalog.try_query_index_snapshot()
    assert published.index_state == "fresh"
    assert published.items[0].source_revision == 2
    assert published.items[0].projection.last_message_preview == "latest"

    runtime.repair_session_index()
    unchanged = catalog.try_query_index_snapshot()
    assert unchanged.query_snapshot == published.query_snapshot


@_async_test
async def test_runtime_auto_refreshes_session_index_after_rename_and_delete(
    tmp_path,
) -> None:
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.diagnostics_service = None

    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager),
        persist=True,
        auto_refresh_session_index=True,
        session_index_flush_delay=60.0,
    )
    project = tmp_path / "project"
    project.mkdir()
    first = await SessionManager.new(
        session_dir=tmp_path, cwd=str(project), persist=True
    )
    second = await SessionManager.new(
        session_dir=tmp_path, cwd=str(project), persist=True
    )
    await first.append_message(_user_message("first"))
    await second.append_message(_user_message("second"))

    async def scenario() -> None:
        await runtime.rename_session(first.get_header().conversation_id, "Renamed")
        assert SessionManager.load_index(tmp_path) == []
        await runtime.drain_session_index_flush()
        assert (
            next(
                summary
                for summary in SessionManager.load_index(tmp_path)
                if summary.session_id == first.get_header().conversation_id
            ).name
            == "Renamed"
        )

        await runtime.delete_session(second.get_header().conversation_id)
        await runtime.drain_session_index_flush()

    await scenario()

    assert {summary.session_id for summary in SessionManager.load_index(tmp_path)} == {
        first.get_header().conversation_id
    }


@_async_test
async def test_runtime_auto_index_refresh_uses_debounce_interval(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    runtime.auto_refresh_session_index = True
    runtime.session_index_refresh_interval = 60.0

    async def scenario():
        session = await runtime.create_session(cwd=str(project))
        await session.session_manager.append_message(_user_message("materialize"))
        await runtime.drain_session_index_flush()
        return session

    session = await scenario()
    index_file = SessionManager.index_file(tmp_path)
    first_mtime = index_file.stat().st_mtime_ns

    await session.session_manager.append_message(_user_message("not refreshed yet"))
    summaries = runtime.list_indexed_session_summaries()

    assert index_file.stat().st_mtime_ns == first_mtime
    assert [summary.session_id for summary in summaries] == [session.session_id]
    assert "not refreshed yet" not in summaries[0].all_messages_text


@_async_test
async def test_runtime_list_sessions_ignores_default_jsonl_exports(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    session = await runtime.create_session(cwd=str(project_root))
    await session.session_manager.append_message(_user_message("first"))

    export_path = session.export_to_jsonl()
    records = runtime.list_sessions()

    assert Path(export_path).name.startswith("session-")
    assert Path(export_path).parent == project_root
    assert [record.session_id for record in records] == [session.session_id]
    assert records[0].session_file != export_path


@_async_test
async def test_runtime_list_sessions_skips_invalid_session_files(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    session = await runtime.create_session(cwd=str(project))
    await session.session_manager.append_message(_user_message("hello"))

    (tmp_path / "broken.jsonl").write_text("not json\n", encoding="utf-8")
    (tmp_path / "not-session.jsonl").write_text("{}\n", encoding="utf-8")

    records = runtime.list_sessions()

    assert [record.session_id for record in records] == [session.session_id]


@_async_test
async def test_runtime_fork_session_switches_to_selected_branch(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project_root = tmp_path / "project"
    nested = project_root / "app"
    nested.mkdir(parents=True)
    (project_root / "AGENTS.md").write_text("Keep edits minimal.", encoding="utf-8")

    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        system_prompt="Base instructions.",
        persist=True,
    )
    session = await runtime.create_session(cwd=str(nested))

    first_id = await session.session_manager.append_message(_user_message("root"))
    second_id = await session.session_manager.append_message(
        _assistant_message("answer")
    )
    await session.session_manager.append_message(_user_message("tail"))
    original_file = session.session_manager.session_file

    forked = await runtime.fork_session(second_id)

    assert runtime.get_current_session() is forked
    assert original_file is not None
    assert forked.session_manager.session_file is not None
    assert forked.session_manager.session_file != original_file
    assert forked.session_manager.get_header().metadata.get("parentSession") == str(
        original_file
    )
    assert [entry.record_id for entry in forked.session_manager.get_branch()] == [
        first_id,
        second_id,
    ]
    assert [
        message.content[0].text for message in forked.get_session_context().messages
    ] == ["root", "answer"]
    expected_context = (
        "# Project Context\n\n"
        "Project-specific instructions and guidelines:\n\n"
        f"## {project_root / 'AGENTS.md'}\n\n"
        "Keep edits minimal."
    )
    assert forked.agent.system_prompt == (
        f"Base instructions.\n\n{expected_context}\n\n{_runtime_footer(nested)}"
    )


@_async_test
async def test_runtime_fork_session_before_user_message_returns_selected_text(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    session = await runtime.create_session(cwd=str(project_root))
    first_id = await session.session_manager.append_message(_user_message("root"))
    second_id = await session.session_manager.append_message(
        _assistant_message("answer")
    )
    third_id = await session.session_manager.append_message(_user_message("tail"))

    fork_result = await runtime.fork_session_operation(
        third_id,
        position="before",
    )
    forked = fork_result.current
    selected_text = fork_result.payload

    assert forked is not None
    assert runtime.get_current_session() is forked
    assert selected_text == "tail"
    assert [entry.record_id for entry in forked.session_manager.get_branch()] == [
        first_id,
        second_id,
    ]


@_async_test
async def test_runtime_fork_before_requires_user_message(tmp_path) -> None:
    import pytest

    from loushang.coding.bootstrap import create_agent_session_runtime

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    session = await runtime.create_session(cwd=str(project_root))
    await session.session_manager.append_message(_user_message("root"))
    assistant_id = await session.session_manager.append_message(
        _assistant_message("answer")
    )

    with pytest.raises(ValueError, match="requires a user message entry"):
        await runtime.fork_session_operation(assistant_id, position="before")


@_async_test
async def test_runtime_exposes_standard_lifecycle_operations(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    session = await runtime.create_session(cwd=str(project_root))
    first_id = await session.session_manager.append_message(_user_message("root"))
    second_id = await session.session_manager.append_message(
        _assistant_message("answer")
    )
    third_id = await session.session_manager.append_message(_user_message("tail"))
    first_session_file = session.session_manager.session_file
    assert first_session_file is not None

    fork_result = await runtime.fork_session_operation(third_id, position="before")
    forked = runtime.get_current_session()
    assert fork_result.cancelled is False
    assert fork_result.payload == "tail"
    assert forked is not None
    assert [entry.record_id for entry in forked.session_manager.get_branch()] == [
        first_id,
        second_id,
    ]

    switch_result = await runtime.switch_session(first_session_file)
    assert switch_result is runtime.get_current_session()
    assert runtime.get_current_session() is not forked

    new_result = await runtime.new_session(parent_session=str(first_session_file))
    assert new_result is runtime.get_current_session()
    assert runtime.get_current_session().session_manager.get_header().metadata.get(
        "parentSession"
    ) == str(first_session_file)


@_async_test
async def test_runtime_new_session_operation_runs_setup_and_with_session(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    session = await runtime.create_session(cwd=str(project_root))
    first_session_file = session.session_manager.session_file
    assert first_session_file is not None
    events: list[tuple[str, object]] = []

    async def _setup(manager):
        events.append(("setup", manager.get_cwd()))
        await manager.append_message(_user_message("initialized from setup"))

    async def _with_session(ctx):
        events.append(
            (
                "withSession",
                (
                    ctx.cwd,
                    ctx.session_manager
                    is runtime.get_current_session().session_manager,
                ),
            )
        )

    result = await runtime.new_session_operation(
        parent_session=str(first_session_file),
        setup=_setup,
        with_session=_with_session,
    )
    created = runtime.get_current_session()

    assert result.cancelled is False
    assert created is not None
    assert created is not session
    assert created.session_manager.get_header().metadata.get("parentSession") == str(
        first_session_file
    )
    assert [
        message.content[0].text for message in created.get_session_context().messages
    ] == ["initialized from setup"]
    assert [message.content[0].text for message in created.agent.state.messages] == [
        "initialized from setup"
    ]
    assert events == [
        ("setup", str(project_root.resolve())),
        ("withSession", (str(project_root.resolve()), True)),
    ]


@_async_test
async def test_runtime_restore_and_fork_operations_run_with_session(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    session = await runtime.create_session(cwd=str(project_root))
    user_id = await session.session_manager.append_message(_user_message("root"))
    await session.session_manager.append_message(_assistant_message("answer"))

    target_manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(project_root), persist=True
    )
    await target_manager.append_message(_user_message("target"))
    target_file = target_manager.session_file
    assert target_file is not None

    events: list[tuple[str, object]] = []

    async def _switch_with_session(ctx):
        events.append(
            (
                "switch",
                [
                    message.content[0].text
                    for message in ctx.session_manager.build_session_context().messages
                ],
            )
        )

    async def _fork_with_session(ctx):
        events.append(
            ("fork", [entry.record_id for entry in ctx.session_manager.get_branch()])
        )

    switch_result = await runtime.restore_session_operation(
        target_file, with_session=_switch_with_session
    )
    switch_session = runtime.get_current_session()
    assert switch_session is not None

    await runtime.switch_session(session.session_manager.session_file)
    fork_result = await runtime.fork_session_operation(
        user_id, position="at", with_session=_fork_with_session
    )

    assert switch_result.cancelled is False
    assert fork_result.cancelled is False
    assert events == [
        ("switch", ["target"]),
        ("fork", [user_id]),
    ]


@_async_test
async def test_runtime_switches_from_provisional_session_without_persisting_it(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager

    project_root = tmp_path / "project"
    project_root.mkdir()
    historical = await SessionManager.new(
        session_dir=tmp_path,
        cwd=str(project_root),
        persist=True,
    )
    await historical.append_message(_user_message("historical"))
    historical_file = historical.get_session_file()
    assert historical_file is not None

    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        persist=True,
    )
    provisional = await runtime.create_session(cwd=str(project_root))
    provisional_file = provisional.get_session_file()
    assert provisional_file is not None
    assert provisional_file.exists() is False

    result = await runtime.restore_session_operation(historical_file)

    current = runtime.get_current_session()
    assert result.cancelled is False
    assert current is not None
    assert current.session_id == historical.get_header().conversation_id
    assert provisional_file.exists() is False
    assert provisional_file.with_name(f"{provisional_file.name}.lock").exists() is False


@_async_test
async def test_runtime_replacement_callbacks_require_async_callables(tmp_path) -> None:
    import pytest

    from loushang.coding.bootstrap import create_agent_session_runtime

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    await runtime.create_session(cwd=str(project_root))

    def _sync_setup(manager):
        del manager

    with pytest.raises(TypeError, match="setup callback must be an async callable"):
        await runtime.new_session_operation(setup=_sync_setup)


@_async_test
async def test_runtime_replacement_callback_failures_keep_replacement_and_record_diagnostics(
    tmp_path,
) -> None:
    import pytest

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.session_id = manager.get_header().conversation_id
            self.extension_runner = None
            self.diagnostics_service = diagnostics_service
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    diagnostics_service = DiagnosticsService()
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=DummySession,
        persist=True,
        diagnostics_service=diagnostics_service,
    )
    project_root = tmp_path / "project"
    target_root = tmp_path / "target"
    project_root.mkdir()
    target_root.mkdir()
    target_manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(target_root), persist=True
    )
    await target_manager.append_message(_user_message("target"))
    target_file = target_manager.session_file
    assert target_file is not None

    async def _setup(manager: SessionManager) -> None:
        assert manager.get_cwd() == str(project_root.resolve())
        raise RuntimeError("setup boom")

    with pytest.raises(RuntimeError, match="setup boom"):
        await runtime.new_session_operation(cwd=project_root, setup=_setup)

    setup_session = runtime.get_current_session()
    assert setup_session is not None
    assert setup_session.session_manager.get_cwd() == str(project_root.resolve())

    async def _with_session(ctx) -> None:
        assert ctx.cwd == str(target_root.resolve())
        raise RuntimeError("withSession boom")

    with pytest.raises(RuntimeError, match="withSession boom"):
        await runtime.restore_session_operation(target_file, with_session=_with_session)

    current = runtime.get_current_session()
    records = diagnostics_service.get_diagnostics(
        query=DiagnosticsQuery(code="session_replacement_callback_failed")
    )

    assert current is not None
    assert current.session_manager.session_file == target_file
    assert [(record.message, record.details["callback"]) for record in records] == [
        ("setup boom", "setup"),
        ("withSession boom", "withSession"),
    ]
    assert records[0].session_id == setup_session.session_id
    assert records[1].session_id == current.session_id


@_async_test
async def test_runtime_import_from_jsonl_copies_and_switches_session(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager

    project_root = tmp_path / "project"
    project_root.mkdir()
    import_dir = tmp_path / "imports"
    import_dir.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path / "sessions", model=_model(), persist=True
    )
    original = await runtime.create_session(cwd=str(project_root))
    await original.session_manager.append_message(_user_message("original"))

    imported_manager = await SessionManager.new(
        session_dir=import_dir, cwd=str(project_root), persist=True
    )
    await imported_manager.append_message(_user_message("imported"))
    imported_file = imported_manager.session_file
    assert imported_file is not None

    result = await runtime.import_from_jsonl(str(imported_file))
    current = runtime.get_current_session()

    assert result == {"cancelled": False}
    assert current is not None
    assert current is not original
    assert (
        current.session_manager.session_file
        == (tmp_path / "sessions" / imported_file.name).resolve()
    )
    assert current.session_manager.session_file.exists()
    assert [
        message.content[0].text for message in current.get_session_context().messages
    ] == ["imported"]


@_async_test
async def test_runtime_import_from_jsonl_does_not_overwrite_existing_same_name_session(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager

    project_root = tmp_path / "project"
    import_dir = tmp_path / "imports"
    session_dir = tmp_path / "sessions"
    project_root.mkdir()
    import_dir.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=session_dir, model=_model(), persist=True
    )
    existing = await runtime.create_session(cwd=str(project_root))
    await existing.session_manager.append_message(_user_message("existing session"))
    existing_file = existing.session_manager.session_file
    assert existing_file is not None

    imported_manager = await SessionManager.new(
        session_dir=import_dir, cwd=str(project_root), persist=True
    )
    await imported_manager.append_message(_user_message("imported same basename"))
    imported_file = imported_manager.session_file
    assert imported_file is not None
    import_source = import_dir / existing_file.name
    imported_file.rename(import_source)

    result = await runtime.import_from_jsonl(str(import_source))
    current = runtime.get_current_session()
    reloaded_existing = await SessionManager.open(existing_file)

    assert result == {"cancelled": False}
    assert current is not None
    assert current.session_manager.session_file != existing_file
    assert current.session_manager.session_file is not None
    assert current.session_manager.session_file.exists()
    assert [
        message.content[0].text
        for message in current.session_manager.build_session_context().messages
    ] == ["imported same basename"]
    assert [
        message.content[0].text
        for message in reloaded_existing.build_session_context().messages
    ] == ["existing session"]


@_async_test
async def test_runtime_import_from_jsonl_retries_when_unique_destination_is_claimed_before_copy(
    tmp_path,
    monkeypatch,
) -> None:
    import errno

    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.runtime import agent_session_runtime as runtime_module
    from loushang.coding.session_manager import SessionManager

    project_root = tmp_path / "project"
    import_dir = tmp_path / "imports"
    session_dir = tmp_path / "sessions"
    project_root.mkdir()
    import_dir.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=session_dir, model=_model(), persist=True
    )
    existing = await runtime.create_session(cwd=str(project_root))
    await existing.session_manager.append_message(_user_message("existing session"))
    existing_file = existing.session_manager.session_file
    assert existing_file is not None

    imported_manager = await SessionManager.new(
        session_dir=import_dir, cwd=str(project_root), persist=True
    )
    await imported_manager.append_message(_user_message("imported after race"))
    imported_file = imported_manager.session_file
    assert imported_file is not None
    import_source = import_dir / existing_file.name
    imported_file.rename(import_source)

    real_copy = runtime_module._copy_import_file
    copy_attempts: list[Path] = []

    def _copy_with_external_race(source: Path, destination: Path) -> None:
        copy_attempts.append(destination)
        if len(copy_attempts) == 1:
            destination.write_text("external winner\n", encoding="utf-8")
            raise FileExistsError(errno.EEXIST, "File exists", str(destination))
        real_copy(source, destination)

    monkeypatch.setattr(runtime_module, "_copy_import_file", _copy_with_external_race)

    result = await runtime.import_from_jsonl(str(import_source))
    current = runtime.get_current_session()
    stem = existing_file.stem
    suffix = existing_file.suffix

    assert result == {"cancelled": False}
    assert current is not None
    assert copy_attempts == [
        (session_dir / f"{stem}-import-1{suffix}").resolve(),
        (session_dir / f"{stem}-import-2{suffix}").resolve(),
    ]
    assert copy_attempts[0].read_text(encoding="utf-8") == "external winner\n"
    assert current.session_manager.session_file == copy_attempts[1]
    assert [
        message.content[0].text
        for message in current.session_manager.build_session_context().messages
    ] == ["imported after race"]


@_async_test
async def test_runtime_import_from_jsonl_race_retry_emits_before_switch_once_for_final_destination(
    tmp_path,
    monkeypatch,
) -> None:
    import errno

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.runtime import agent_session_runtime as runtime_module
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    class DummySession:
        def __init__(self, manager: SessionManager, runner: ExtensionRunner) -> None:
            self.session_manager = manager
            self.extension_runner = runner
            self.diagnostics_service = None
            self.session_id = manager.get_header().conversation_id

        def set_extension_runtime_host(self, _host) -> None:
            return None

        async def start_extension_runtime(self, *, reason: str) -> None:
            del reason

        async def dispose(self) -> None:
            return None

    project_root = tmp_path / "project"
    import_dir = tmp_path / "imports"
    session_dir = tmp_path / "sessions"
    project_root.mkdir()
    import_dir.mkdir()
    seen_targets: list[str | None] = []

    def _before_switch(event, ctx):
        del ctx
        seen_targets.append(event.target_session_file)
        return None

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/demo.py"),
                hooks={"session_before_switch": [_before_switch]},
            )
        ]
    )
    runtime = AgentSessionRuntime(
        session_dir=session_dir,
        session_factory=lambda manager: DummySession(manager, runner),
        persist=True,
    )
    existing = await runtime.create_session(cwd=str(project_root))
    await existing.session_manager.append_message(_user_message("existing session"))
    existing_file = existing.session_manager.session_file
    assert existing_file is not None

    imported_manager = await SessionManager.new(
        session_dir=import_dir, cwd=str(project_root), persist=True
    )
    await imported_manager.append_message(_user_message("imported after race"))
    imported_file = imported_manager.session_file
    assert imported_file is not None
    import_source = import_dir / existing_file.name
    imported_file.rename(import_source)

    real_copy = runtime_module._copy_import_file
    copy_attempts: list[Path] = []

    def _copy_with_external_race(source: Path, destination: Path) -> None:
        copy_attempts.append(destination)
        if len(copy_attempts) == 1:
            destination.write_text("external winner\n", encoding="utf-8")
            raise FileExistsError(errno.EEXIST, "File exists", str(destination))
        real_copy(source, destination)

    monkeypatch.setattr(runtime_module, "_copy_import_file", _copy_with_external_race)

    result = await runtime.import_from_jsonl(str(import_source))
    current = runtime.get_current_session()
    final_destination = copy_attempts[1]

    assert result == {"cancelled": False}
    assert current is not None
    assert current.session_manager.session_file == final_destination
    assert seen_targets == [str(final_destination)]


@_async_test
async def test_runtime_import_from_jsonl_cleans_copied_file_when_stored_cwd_is_missing(
    tmp_path,
) -> None:
    import pytest

    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.session import MissingSessionCwdError

    project_root = tmp_path / "project"
    missing_cwd = tmp_path / "missing-project"
    import_dir = tmp_path / "imports"
    session_dir = tmp_path / "sessions"
    project_root.mkdir()
    import_dir.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=session_dir, model=_model(), persist=True
    )
    current = await runtime.create_session(cwd=str(project_root))
    imported_manager = await SessionManager.new(
        session_dir=import_dir, cwd=str(missing_cwd), persist=True
    )
    await imported_manager.append_message(_user_message("missing cwd import"))
    imported_file = imported_manager.session_file
    assert imported_file is not None

    with pytest.raises(MissingSessionCwdError):
        await runtime.import_from_jsonl(str(imported_file))

    assert runtime.get_current_session() is current
    assert imported_file.exists()
    assert (session_dir / imported_file.name).exists() is False


@_async_test
async def test_runtime_import_from_jsonl_records_failure_diagnostic(tmp_path) -> None:
    import pytest

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService
    from loushang.harness.session import MissingSessionCwdError

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.extension_runner = None
            self.diagnostics_service = None
            self.session_id = manager.get_header().conversation_id

        def set_extension_runtime_host(self, _host) -> None:
            return None

        async def start_extension_runtime(self, *, reason: str) -> None:
            del reason

        async def dispose(self) -> None:
            return None

    project_root = tmp_path / "project"
    missing_cwd = tmp_path / "missing-project"
    import_dir = tmp_path / "imports"
    session_dir = tmp_path / "sessions"
    project_root.mkdir()
    import_dir.mkdir()
    diagnostics_service = DiagnosticsService()
    runtime = AgentSessionRuntime(
        session_dir=session_dir,
        session_factory=DummySession,
        persist=True,
        diagnostics_service=diagnostics_service,
    )
    current = await runtime.create_session(cwd=str(project_root))
    imported_manager = await SessionManager.new(
        session_dir=import_dir, cwd=str(missing_cwd), persist=True
    )
    await imported_manager.append_message(_user_message("imported"))
    imported_file = imported_manager.session_file
    assert imported_file is not None

    with pytest.raises(MissingSessionCwdError):
        await runtime.import_from_jsonl(str(imported_file))

    records = diagnostics_service.get_diagnostics(
        query=DiagnosticsQuery(code="session_import_failed")
    )

    assert runtime.get_current_session() is current
    assert len(records) == 1
    assert records[0].session_id == current.session_id
    assert records[0].details["operation"] == "import_from_jsonl"
    assert records[0].details["input_path"] == str(imported_file)
    assert records[0].details["source_path"] == str(imported_file.resolve())
    assert records[0].details["target_session_file"] == str(
        (session_dir / imported_file.name).resolve()
    )
    assert records[0].details["cwd_override"] is None


@_async_test
async def test_runtime_restore_rejects_session_when_stored_cwd_is_missing(
    tmp_path,
) -> None:
    import pytest

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.session import MissingSessionCwdError

    missing_cwd = tmp_path / "missing-project"
    manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(missing_cwd), persist=True
    )
    await manager.append_message(_user_message("stored"))
    session_file = manager.session_file
    assert session_file is not None
    created: list[SessionManager] = []

    def _factory(next_manager: SessionManager):
        created.append(next_manager)
        return object()

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )

    with pytest.raises(MissingSessionCwdError) as exc_info:
        await runtime.restore_session(session_file)

    assert exc_info.value.issue.session_cwd == str(missing_cwd)
    assert exc_info.value.issue.session_ref == str(session_file)
    assert created == []
    assert runtime.get_current_session() is None


@_async_test
async def test_runtime_restore_session_records_failure_diagnostic(tmp_path) -> None:
    import pytest

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService
    from loushang.harness.session import MissingSessionCwdError

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.extension_runner = None
            self.diagnostics_service = None
            self.session_id = manager.get_header().conversation_id

        def set_extension_runtime_host(self, _host) -> None:
            return None

        async def start_extension_runtime(self, *, reason: str) -> None:
            del reason

        async def dispose(self) -> None:
            return None

    project_root = tmp_path / "project"
    missing_cwd = tmp_path / "missing-project"
    session_dir = tmp_path / "sessions"
    project_root.mkdir()
    diagnostics_service = DiagnosticsService()
    target_manager = await SessionManager.new(
        session_dir=session_dir, cwd=str(missing_cwd), persist=True
    )
    await target_manager.append_message(_user_message("target"))
    target_file = target_manager.session_file
    assert target_file is not None
    runtime = AgentSessionRuntime(
        session_dir=session_dir,
        session_factory=DummySession,
        persist=True,
        diagnostics_service=diagnostics_service,
    )
    current = await runtime.create_session(cwd=str(project_root))

    with pytest.raises(MissingSessionCwdError):
        await runtime.restore_session(target_file)

    records = diagnostics_service.get_diagnostics(
        query=DiagnosticsQuery(code="session_restore_failed")
    )

    assert runtime.get_current_session() is current
    assert len(records) == 1
    assert records[0].session_id == current.session_id
    assert records[0].details["operation"] == "restore_session"
    assert records[0].details["session_ref"] == str(target_file)
    assert records[0].details["target_session_file"] == str(target_file.resolve())
    assert records[0].details["fallback_cwd"] is None
    assert records[0].details["missing_cwd"] == "error"


@_async_test
async def test_runtime_restore_can_fallback_when_stored_cwd_is_missing(
    tmp_path,
) -> None:
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager

    project_root = tmp_path / "project"
    missing_cwd = tmp_path / "missing-project"
    project_root.mkdir()
    manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(missing_cwd), persist=True
    )
    await manager.append_message(_user_message("hello"))
    session_file = manager.session_file
    assert session_file is not None
    created: list[SessionManager] = []

    class DummySession:
        def __init__(self, next_manager: SessionManager) -> None:
            self.session_manager = next_manager
            self.extension_runner = None
            self.diagnostics_service = None
            self.session_id = next_manager.get_header().conversation_id

        def set_extension_runtime_host(self, _host) -> None:
            return None

        async def dispose(self) -> None:
            return None

    def _factory(next_manager: SessionManager):
        created.append(next_manager)
        return DummySession(next_manager)

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )

    restored = await runtime.restore_session(
        session_file,
        fallback_cwd=project_root,
        missing_cwd="fallback",
    )

    assert restored.session_manager.get_cwd() == str(project_root.resolve())
    assert created == [restored.session_manager]


@_async_test
async def test_runtime_import_from_jsonl_cwd_override_bypasses_missing_stored_cwd(
    tmp_path,
) -> None:
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager

    project_root = tmp_path / "project"
    missing_cwd = tmp_path / "missing-project"
    import_dir = tmp_path / "imports"
    project_root.mkdir()
    import_dir.mkdir()
    imported_manager = await SessionManager.new(
        session_dir=import_dir, cwd=str(missing_cwd), persist=True
    )
    await imported_manager.append_message(_user_message("imported"))
    imported_file = imported_manager.session_file
    assert imported_file is not None

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.extension_runner = None
            self.diagnostics_service = None
            self.session_id = manager.get_header().conversation_id

        def set_extension_runtime_host(self, _host) -> None:
            return None

        async def start_extension_runtime(self, *, reason: str) -> None:
            del reason

        async def dispose(self) -> None:
            return None

    runtime = AgentSessionRuntime(
        session_dir=tmp_path / "sessions", session_factory=DummySession, persist=True
    )

    result = await runtime.import_from_jsonl(
        str(imported_file), cwd_override=str(project_root)
    )
    current = runtime.get_current_session()

    assert result == {"cancelled": False}
    assert current is not None
    assert current.session_manager.get_cwd() == str(project_root.resolve())
    assert [
        message.content[0].text
        for message in current.session_manager.build_session_context().messages
    ] == ["imported"]


@_async_test
async def test_runtime_import_from_jsonl_respects_before_switch_cancellation(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionActionDecision,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    import_dir = tmp_path / "imports"
    import_dir.mkdir()
    imported_manager = await SessionManager.new(
        session_dir=import_dir, cwd=str(project_root), persist=True
    )
    await imported_manager.append_message(_user_message("imported"))
    imported_file = imported_manager.session_file
    assert imported_file is not None
    events: list[str | None] = []

    def _cancel_switch(event, ctx):
        del ctx
        events.append(event.target_session_file)
        return SessionActionDecision(cancel=True)

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="demo",
                        source_path=Path("/tmp/demo.py"),
                        hooks={"session_before_switch": [_cancel_switch]},
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path / "sessions", session_factory=_factory, persist=True
    )
    current = await runtime.create_session(cwd=str(project_root))

    result = await runtime.import_from_jsonl(str(imported_file))

    assert result == {"cancelled": True}
    assert runtime.get_current_session() is current
    assert events == [str((tmp_path / "sessions" / imported_file.name).resolve())]
    assert not (tmp_path / "sessions" / imported_file.name).exists()


@_async_test
async def test_runtime_import_from_jsonl_records_before_switch_failure_and_flushes_index(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    project_root = tmp_path / "project"
    import_dir = tmp_path / "imports"
    session_dir = tmp_path / "sessions"
    project_root.mkdir()
    import_dir.mkdir()
    diagnostics_service = DiagnosticsService()

    imported_manager = await SessionManager.new(
        session_dir=import_dir, cwd=str(project_root), persist=True
    )
    await imported_manager.append_message(_user_message("imported"))
    imported_file = imported_manager.session_file
    assert imported_file is not None

    def _before_switch(event, ctx):
        del event, ctx
        raise RuntimeError("before switch boom")

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            diagnostics_service=diagnostics_service,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="broken",
                        source_path=Path("/tmp/broken.py"),
                        hooks={"session_before_switch": [_before_switch]},
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=session_dir,
        session_factory=_factory,
        persist=True,
        diagnostics_service=diagnostics_service,
        auto_refresh_session_index=True,
        session_index_flush_delay=60.0,
    )

    async def scenario() -> None:
        await runtime.create_session(cwd=str(project_root))
        result = await runtime.import_from_jsonl(str(imported_file))
        assert result == {"cancelled": False}
        await runtime.drain_session_index_flush()

    await scenario()
    current = runtime.get_current_session()
    records = diagnostics_service.get_diagnostics(
        query=DiagnosticsQuery(code="extension_session_before_switch_failed")
    )

    assert current is not None
    assert (
        current.session_manager.session_file
        == (session_dir / imported_file.name).resolve()
    )
    assert current.session_id in {
        summary.session_id for summary in SessionManager.load_index(session_dir)
    }
    assert len(records) == 1
    assert (
        records[0].message
        == "Extension hook 'session_before_switch' failed: before switch boom"
    )


@_async_test
async def test_runtime_lifecycle_operations_report_cancellation(tmp_path) -> None:
    from pathlib import Path

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionActionDecision,
    )

    class DummySession:
        def __init__(self, manager: SessionManager, runner: ExtensionRunner) -> None:
            self.session_manager = manager
            self.extension_runner = runner
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    def _cancel_switch(event, ctx):
        del event, ctx
        return SessionActionDecision(cancel=True)

    def _cancel_fork(event, ctx):
        del event, ctx
        return SessionActionDecision(cancel=True)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/demo.py"),
                hooks={
                    "session_before_switch": [_cancel_switch],
                    "session_before_fork": [_cancel_fork],
                },
            )
        ]
    )
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager, runner),
        persist=False,
    )
    project = tmp_path / "project"
    project.mkdir()
    current = await runtime.create_session(cwd=str(project))
    entry_id = await current.session_manager.append_message(_user_message("root"))

    assert (await runtime.new_session_operation()).cancelled is True
    assert (
        await runtime.fork_session_operation(entry_id, position="at")
    ).cancelled is True
    assert runtime.get_current_session() is current
    assert current.disposed is False


@_async_test
async def test_extension_command_context_fork_uses_runtime_host(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    results: list[object] = []

    async def _fork_command(args: str, ctx):
        result = await ctx.fork(args, {"position": "at"})
        results.append(result)

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="fork-ext",
                        source_path=Path("/tmp/fork-ext.py"),
                        commands={
                            "fork": RegisteredCommand(
                                name="fork",
                                handler=_fork_command,
                                description="Fork the session",
                            )
                        },
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    session = await runtime.create_session(cwd=str(project))
    first_id = await session.session_manager.append_message(_user_message("root"))
    second_id = await session.session_manager.append_message(
        _assistant_message("answer")
    )
    await session.session_manager.append_message(_user_message("tail"))

    result = await session.execute_command_async("fork", second_id)
    forked = runtime.get_current_session()

    assert result.result is None
    assert results == [{"cancelled": False}]
    assert forked is not None
    assert forked is not session
    assert [entry.record_id for entry in forked.session_manager.get_branch()] == [
        first_id,
        second_id,
    ]


@_async_test
async def test_extension_command_context_fork_supports_before_position(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    results: list[object] = []
    seen_branches: list[list[str]] = []

    async def _fork_command(args: str, ctx):
        result = await ctx.fork(args, {"position": "before"})
        results.append(result)

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="fork-ext",
                        source_path=Path("/tmp/fork-ext.py"),
                        commands={
                            "fork": RegisteredCommand(
                                name="fork",
                                handler=_fork_command,
                                description="Fork the session",
                            )
                        },
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    session = await runtime.create_session(cwd=str(project))
    first_id = await session.session_manager.append_message(_user_message("root"))
    second_id = await session.session_manager.append_message(
        _assistant_message("answer")
    )
    third_id = await session.session_manager.append_message(_user_message("tail"))

    result = await session.execute_command_async("fork", third_id)
    forked = runtime.get_current_session()
    assert forked is not None
    seen_branches.append(
        [entry.record_id for entry in forked.session_manager.get_branch()]
    )

    assert result.result is None
    assert results == [{"cancelled": False, "selected_text": "tail"}]
    assert forked is not session
    assert seen_branches == [[first_id, second_id]]


@_async_test
async def test_extension_command_context_fork_defaults_to_before_position(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    results: list[object] = []

    async def _fork_command(args: str, ctx):
        results.append(await ctx.fork(args))

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="fork-ext",
                        source_path=Path("/tmp/fork-ext.py"),
                        commands={
                            "fork": RegisteredCommand(
                                name="fork",
                                handler=_fork_command,
                                description="Fork the session",
                            )
                        },
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    session = await runtime.create_session(cwd=str(project))
    first_id = await session.session_manager.append_message(_user_message("root"))
    second_id = await session.session_manager.append_message(
        _assistant_message("answer")
    )
    third_id = await session.session_manager.append_message(_user_message("tail"))

    result = await session.execute_command_async("fork", third_id)
    forked = runtime.get_current_session()

    assert result.result is None
    assert results == [{"cancelled": False, "selected_text": "tail"}]
    assert forked is not None
    assert [entry.record_id for entry in forked.session_manager.get_branch()] == [
        first_id,
        second_id,
    ]


@_async_test
async def test_extension_command_context_fork_before_runs_with_session_on_new_fork(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    seen: list[tuple[str, list[str]]] = []

    async def _fork_command(args: str, ctx):
        async def _with_session(replaced_ctx):
            seen.append(
                (
                    replaced_ctx.cwd,
                    [
                        entry.record_id
                        for entry in replaced_ctx.session_manager.get_branch()
                    ],
                )
            )

        await ctx.fork(args, {"position": "before", "withSession": _with_session})

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="fork-ext",
                        source_path=Path("/tmp/fork-ext.py"),
                        commands={
                            "fork": RegisteredCommand(
                                name="fork",
                                handler=_fork_command,
                                description="Fork the session",
                            )
                        },
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    session = await runtime.create_session(cwd=str(project))
    first_id = await session.session_manager.append_message(_user_message("root"))
    second_id = await session.session_manager.append_message(
        _assistant_message("answer")
    )
    third_id = await session.session_manager.append_message(_user_message("tail"))

    result = await session.execute_command_async("fork", third_id)

    assert result.result is None
    assert seen == [(str(project.resolve()), [first_id, second_id])]


@_async_test
async def test_extension_command_context_new_session_uses_runtime_host(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    callback_events: list[tuple[str, object]] = []

    async def _new_command(args: str, ctx):
        del args

        async def _setup(manager):
            callback_events.append(("setup", manager.get_cwd()))
            await manager.append_message(_user_message("initialized"))

        async def _with_session(replaced_ctx):
            callback_events.append(
                (
                    "withSession",
                    (replaced_ctx.cwd, replaced_ctx.session_manager is not None),
                )
            )

        await ctx.new_session(
            {"parentSession": "parent-1", "setup": _setup, "withSession": _with_session}
        )

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="new-ext",
                        source_path=Path("/tmp/new-ext.py"),
                        commands={
                            "new": RegisteredCommand(
                                name="new",
                                handler=_new_command,
                                description="New session",
                            )
                        },
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    session = await runtime.create_session(cwd=str(project))

    result = await session.execute_command_async("new", "")
    created = runtime.get_current_session()

    assert result.result is None
    assert created is not None
    assert created is not session
    assert (
        created.session_manager.get_header().metadata.get("parentSession") == "parent-1"
    )
    assert created.session_manager.get_cwd() == str(project.resolve())
    assert [
        message.content[0].text for message in created.get_session_context().messages
    ] == ["initialized"]
    assert callback_events == [
        ("setup", str(project.resolve())),
        ("withSession", (str(project.resolve()), True)),
    ]


@_async_test
async def test_extension_command_new_session_with_session_gets_fresh_context_and_stales_old_context(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    events: list[tuple[str, object]] = []

    async def _new_command(args: str, ctx):
        del args
        old_ctx = ctx

        async def _with_session(replaced_ctx):
            events.append(
                ("fresh", (replaced_ctx.cwd, replaced_ctx.session_manager is not None))
            )
            try:
                old_ctx.cwd
            except RuntimeError as exc:
                events.append(("stale", str(exc)))

        await ctx.new_session({"withSession": _with_session})

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="new-ext",
                        source_path=Path("/tmp/new-ext.py"),
                        commands={
                            "new": RegisteredCommand(
                                name="new",
                                handler=_new_command,
                                description="New session",
                            )
                        },
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    session = await runtime.create_session(cwd=str(project))

    result = await session.execute_command_async("new", "")

    assert result.result is None
    assert events == [
        ("fresh", (str(project.resolve()), True)),
        ("stale", "Extension context is stale after session replacement or shutdown."),
    ]


@_async_test
async def test_replaced_session_context_send_message_becomes_stale_after_next_replacement(
    tmp_path,
) -> None:
    from pathlib import Path

    import pytest

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    captured: dict[str, object] = {}

    async def _new_command(args: str, ctx):
        del args

        async def _with_session(replaced_ctx):
            captured["ctx"] = replaced_ctx
            await replaced_ctx.send_message(
                {"customType": "demo", "content": "fresh", "display": True}
            )

        await ctx.new_session({"withSession": _with_session})

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="new-ext",
                        source_path=Path("/tmp/new-ext.py"),
                        commands={
                            "new": RegisteredCommand(
                                name="new",
                                handler=_new_command,
                                description="New session",
                            )
                        },
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    session = await runtime.create_session(cwd=str(project))

    result = await session.execute_command_async("new", "")
    replaced_ctx = captured["ctx"]
    current = runtime.get_current_session()
    assert result.result is None
    assert current is not None
    assert [
        entry.payload.custom_type for entry in current.session_manager.get_entries()
    ] == ["demo"]

    await runtime.new_session()

    with pytest.raises(RuntimeError, match="stale"):
        await replaced_ctx.send_message(
            {"customType": "demo", "content": "stale", "display": True}
        )
    with pytest.raises(RuntimeError, match="stale"):
        await replaced_ctx.send_user_message("stale user text")


@_async_test
async def test_agent_session_exposes_pi_style_replaced_session_context(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    project = tmp_path / "project"
    project.mkdir()
    session = AgentSession(
        agent=Agent(),
        session_manager=await SessionManager.new(
            session_dir=tmp_path, cwd=str(project), persist=True
        ),
        extension_runner=ExtensionRunner(
            [LoadedExtension(name="demo", source_path=Path("/tmp/demo.py"))]
        ),
    )

    context = session.create_replaced_session_context()

    assert context.cwd == str(project.resolve())
    assert context.session_manager is session.session_manager
    assert context.get_session_name() is None


@_async_test
async def test_extension_command_context_switch_session_uses_runtime_host(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    callback_events: list[tuple[str, object]] = []

    async def _switch_command(args: str, ctx):
        async def _with_session(replaced_ctx):
            callback_events.append(
                (
                    "withSession",
                    (replaced_ctx.cwd, replaced_ctx.session_manager is not None),
                )
            )

        await ctx.switch_session(args, {"withSession": _with_session})

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="switch-ext",
                        source_path=Path("/tmp/switch-ext.py"),
                        commands={
                            "switch": RegisteredCommand(
                                name="switch",
                                handler=_switch_command,
                                description="Switch session",
                            )
                        },
                    )
                ]
            ),
        )

    project = tmp_path / "project"
    project.mkdir()
    first_manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(project), persist=True
    )
    second_manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(project), persist=True
    )
    await second_manager.append_message(_user_message("restored"))
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=_factory,
        persist=True,
        current_session=_factory(first_manager),
    )
    session = runtime.get_current_session()
    assert session is not None

    result = await session.execute_command_async(
        "switch", str(second_manager.session_file)
    )
    switched = runtime.get_current_session()

    assert result.result is None
    assert switched is not None
    assert switched is not session
    assert [
        message.content[0].text for message in switched.get_session_context().messages
    ] == ["restored"]
    assert callback_events == [("withSession", (str(project.resolve()), True))]


@_async_test
async def test_extension_command_replacement_callbacks_require_async_callables(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    async def _new_command(args: str, ctx):
        del args

        def _with_session(replaced_ctx):
            del replaced_ctx

        await ctx.new_session({"withSession": _with_session})

    diagnostics_service = DiagnosticsService()

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            diagnostics_service=diagnostics_service,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="new-ext",
                        source_path=Path("/tmp/new-ext.py"),
                        commands={
                            "new": RegisteredCommand(name="new", handler=_new_command)
                        },
                    )
                ]
            ),
        )

    project = tmp_path / "project"
    project.mkdir()
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=_factory,
        persist=True,
        diagnostics_service=diagnostics_service,
    )
    session = await runtime.create_session(cwd=str(project))

    result = await session.execute_command_async("new", "")

    assert result is not None
    assert result.result is None
    assert [
        diagnostic.code for diagnostic in diagnostics_service.get_diagnostics()
    ] == ["extension_command_failed"]


@_async_test
async def test_runtime_exposes_diagnostics_snapshot(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime, create_services
    from loushang.harness.diagnostics import DiagnosticsQuery

    services = create_services()
    services.diagnostics_service.record(
        services.diagnostics_service.normalize_exception(
            code="startup_warning",
            exc="heads up",
            phase="startup",
            source="bootstrap",
            level="warning",
        )
    )
    services.diagnostics_service.record(
        services.diagnostics_service.normalize_exception(
            code="runtime_error",
            exc="boom",
            phase="runtime",
            source="session",
            level="error",
        )
    )

    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        services=services,
        persist=False,
    )

    assert [record.code for record in runtime.get_last_diagnostics()] == [
        "startup_warning",
        "runtime_error",
    ]
    assert [
        record.code
        for record in runtime.get_diagnostics(
            DiagnosticsQuery(phase="runtime", source="session")
        )
    ] == ["runtime_error"]
    assert runtime.get_last_error_report() is not None
    assert runtime.get_last_error_report().primary.code == "runtime_error"


@_async_test
async def test_runtime_exposes_current_session_diagnostics(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime, create_services
    from loushang.harness.diagnostics import DiagnosticsQuery

    services = create_services()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path,
        model=_model(),
        services=services,
        persist=False,
    )
    session = await runtime.create_session(cwd=str(tmp_path))
    services.diagnostics_service.record(
        services.diagnostics_service.normalize_exception(
            code="current_runtime_error",
            exc="boom",
            phase="runtime",
            source="session",
            session_id=session.session_id,
        )
    )
    services.diagnostics_service.record(
        services.diagnostics_service.normalize_exception(
            code="other_runtime_error",
            exc="other",
            phase="runtime",
            source="session",
            session_id="other-session",
        )
    )

    assert [
        record.code
        for record in runtime.get_session_diagnostics(DiagnosticsQuery(level="error"))
    ] == ["current_runtime_error"]
    assert [
        record.code
        for record in runtime.get_session_diagnostics(
            DiagnosticsQuery(code="current_runtime_error")
        )
    ] == ["current_runtime_error"]
    summary = runtime.get_session_diagnostics_summary(DiagnosticsQuery(level="error"))
    assert summary.total_count == 1
    assert summary.by_code == {"current_runtime_error": 1}
    assert summary.latest_error is not None
    assert summary.latest_error.code == "current_runtime_error"


@_async_test
async def test_agent_session_runtime_create_restore_and_fork_reconstruct_extension_start_hooks(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    events: list[str] = []

    def _session_start(event, ctx):
        del event
        events.append(ctx.cwd)

    def _factory(manager: SessionManager) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="demo",
                        source_path=Path("/tmp/demo.py"),
                        hooks={"session_start": [_session_start]},
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    session = await runtime.create_session(cwd=str(project))
    await session.session_manager.append_message(_user_message("materialize"))
    restored = await runtime.restore_session(session.get_session_file())
    await restored.session_manager.append_message(_user_message("branch me"))
    fork_entry_id = restored.session_manager.get_entries()[0].record_id
    await runtime.fork_session(fork_entry_id)

    assert events == [
        str(project.resolve()),
        str(project.resolve()),
        str(project.resolve()),
    ]


@_async_test
async def test_runtime_replacement_emits_shutdown_before_next_session_start(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    events: list[tuple[str, str | None, str | None]] = []

    def _before_switch(event, ctx):
        del event, ctx
        events.append(("before_switch", None, None))

    def _session_shutdown(event, ctx):
        del ctx
        events.append(("shutdown", event.reason, event.target_session_file))

    def _session_start(event, ctx):
        del ctx
        events.append(("start", event.reason, event.previous_session_file))

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="demo",
                        source_path=Path("/tmp/demo.py"),
                        hooks={
                            "session_before_switch": [_before_switch],
                            "session_shutdown": [_session_shutdown],
                            "session_start": [_session_start],
                        },
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    first = await runtime.create_session(cwd=str(project))
    first_session_file = first.session_manager.session_file
    assert first_session_file is not None
    events.clear()

    await runtime.new_session()

    assert runtime.get_current_session() is not None
    assert events == [
        ("before_switch", None, None),
        (
            "shutdown",
            "new",
            str(runtime.get_current_session().session_manager.session_file),
        ),
        ("start", "new", str(first_session_file)),
    ]


@_async_test
async def test_runtime_syncs_extension_lifecycle_failure_diagnostics(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    diagnostics_service = DiagnosticsService()

    def _broken(name: str):
        def _hook(event, ctx):
            del event, ctx
            raise RuntimeError(f"{name} boom")

        return _hook

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            diagnostics_service=diagnostics_service,
            extension_runner=ExtensionRunner(
                [
                    LoadedExtension(
                        name="broken",
                        source_path=Path("/tmp/broken.py"),
                        hooks={
                            "session_before_switch": [_broken("before switch")],
                            "session_before_fork": [_broken("before fork")],
                            "session_shutdown": [_broken("shutdown")],
                        },
                    )
                ]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=_factory,
        persist=True,
        diagnostics_service=diagnostics_service,
    )
    project = tmp_path / "project"
    project.mkdir()

    first = await runtime.create_session(cwd=str(project))
    second = await runtime.new_session()
    fork_entry_id = await second.session_manager.append_message(
        _user_message("fork root")
    )
    await runtime.fork_session(fork_entry_id)

    records_by_code = {
        record.code: record
        for record in diagnostics_service.get_diagnostics()
        if record.code.startswith("extension_session_")
    }

    assert first is not second
    assert {
        "extension_session_before_switch_failed",
        "extension_session_before_fork_failed",
        "extension_session_shutdown_failed",
    }.issubset(records_by_code)
    assert records_by_code["extension_session_before_switch_failed"].message == (
        "Extension hook 'session_before_switch' failed: before switch boom"
    )
    assert records_by_code["extension_session_before_fork_failed"].message == (
        "Extension hook 'session_before_fork' failed: before fork boom"
    )
    assert records_by_code["extension_session_shutdown_failed"].message == (
        "Extension hook 'session_shutdown' failed: shutdown boom"
    )


@_async_test
async def test_runtime_new_session_reuses_current_cwd_and_disposes_previous_session(
    tmp_path,
) -> None:
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager),
        persist=False,
    )
    project = tmp_path / "project"
    project.mkdir()

    first = await runtime.create_session(cwd=str(project))
    second = await runtime.new_session()

    assert runtime.get_current_session() is second
    assert second.session_manager.get_cwd() == str(project.resolve())
    assert first.disposed is True
    assert second.disposed is False
    assert (
        second.session_manager.get_header().conversation_id
        != first.session_manager.get_header().conversation_id
    )


@_async_test
async def test_builtin_new_command_replaces_current_session_without_materializing_empty_files(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    session_dir = tmp_path / "sessions"
    runtime = create_agent_session_runtime(
        session_dir=session_dir,
        model=_model(),
        persist=True,
    )
    first = await runtime.create_session(cwd=str(tmp_path))

    execution = await first.execute_command_async("new", "")
    current = runtime.get_current_session()

    assert execution.result == {
        "source": "builtin",
        "command": "new",
        "status": "ok",
        "result": {"cancelled": False},
        "message": "Started a new session.",
    }
    assert current is not None
    assert current is not first
    assert current.session_manager.get_cwd() == str(tmp_path.resolve())
    assert list(session_dir.glob("*.jsonl")) == []


@_async_test
async def test_runtime_session_replacement_keeps_shared_approval_presenter(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    project = tmp_path / "project"
    project.mkdir()
    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    presented: list[dict[str, object]] = []
    presentation = asyncio.Event()

    def present(payload: dict[str, object]) -> None:
        presented.append(payload)
        presentation.set()

    resolver.set_request_presenter(present)
    runtime = create_agent_session_runtime(
        session_dir=tmp_path / "sessions",
        model=_model(),
        persist=False,
        approval_resolver=resolver,
    )

    async def run() -> None:
        await runtime.create_session(cwd=str(project))
        first_pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="first-session-approval",
                )
            )
        )
        await asyncio.wait_for(presentation.wait(), timeout=0.5)

        second = await runtime.new_session()
        first_decision = await first_pending
        assert first_decision.disposition == "deny"
        assert first_decision.reason == "Session closed before approval was resolved"
        assert second is runtime.get_current_session()

        presentation.clear()
        second_pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="second-session-approval",
                )
            )
        )
        await asyncio.wait_for(presentation.wait(), timeout=0.5)
        assert presented[-1]["action_id"] == "second-session-approval"
        await second.handle_screen_approval(
            {"action_id": "second-session-approval", "approved": True}
        )
        assert (await second_pending).disposition == "allow"
        await second.dispose()

    await run()
    resolver.dispose()


@_async_test
async def test_runtime_direct_replacement_reactivates_shared_approval_presenter(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    project = tmp_path / "project"
    project.mkdir()
    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    presented: list[dict[str, object]] = []
    presentation = asyncio.Event()

    def present(payload: dict[str, object]) -> None:
        presented.append(payload)
        presentation.set()

    resolver.set_request_presenter(present)
    runtime = create_agent_session_runtime(
        session_dir=tmp_path / "sessions",
        model=_model(),
        persist=False,
        approval_resolver=resolver,
    )

    async def run() -> None:
        await runtime.create_session(cwd=str(project))
        first_pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="direct-first-approval",
                )
            )
        )
        await asyncio.wait_for(presentation.wait(), timeout=0.5)

        replacement_manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project),
            persist=False,
        )
        replacement = runtime.session_factory(replacement_manager)
        await runtime.replace_current_session(replacement)
        assert (await first_pending).disposition == "deny"
        assert runtime.get_current_session() is replacement

        presentation.clear()
        second_pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="direct-second-approval",
                )
            )
        )
        await asyncio.wait_for(presentation.wait(), timeout=0.5)
        assert presented[-1]["action_id"] == "direct-second-approval"
        await replacement.handle_screen_approval(
            {"action_id": "direct-second-approval", "approved": True}
        )
        assert (await second_pending).disposition == "allow"
        await replacement.dispose()

    await run()
    resolver.dispose()


@_async_test
async def test_runtime_injected_current_session_reopens_shared_approval_resolver(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.approval import (
        ApprovalRequest,
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    presented = asyncio.Event()
    resolver.set_request_presenter(lambda payload: presented.set())
    resolver.close_session("previous session closed")
    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd=str(tmp_path),
        persist=False,
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        approval_resolver=resolver,
    )
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda _manager: session,
        persist=False,
        current_session=session,
    )

    async def run() -> None:
        pending = asyncio.create_task(
            resolver.resolve(
                ApprovalRequest(
                    tool_name="write",
                    arguments={},
                    action_id="injected-current-approval",
                )
            )
        )
        await asyncio.wait_for(presented.wait(), timeout=0.5)
        await session.handle_screen_approval(
            {"action_id": "injected-current-approval", "approved": True}
        )
        assert (await pending).disposition == "allow"
        await runtime.dispose()

    await run()
    resolver.dispose()


@_async_test
async def test_runtime_replacement_disposes_agent_session_local_resources(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=True
    )
    project = tmp_path / "project"
    project.mkdir()
    first = await runtime.create_session(cwd=str(project))
    first.footer_data_provider.set_extension_status("demo", "running")
    first.footer_data_provider.start_git_watcher(
        poll_interval_seconds=0.01, debounce_seconds=0
    )
    assert first.footer_data_provider.is_git_watcher_running()

    second = await runtime.new_session()

    assert runtime.get_current_session() is second
    assert second is not first
    assert first.footer_data_provider.get_extension_statuses() == {}
    assert first.footer_data_provider.is_git_watcher_running() is False


@_async_test
async def test_runtime_replacement_records_shutdown_emit_failure_and_keeps_replacement(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    class BrokenShutdownRunner(ExtensionRunner):
        async def emit_session_shutdown(self, event) -> None:
            del event
            raise RuntimeError("shutdown transport boom")

    diagnostics_service = DiagnosticsService()

    def _factory(manager: SessionManager, *, session_start_event=None) -> AgentSession:
        return AgentSession(
            agent=Agent(),
            session_manager=manager,
            session_start_event=session_start_event,
            diagnostics_service=diagnostics_service,
            extension_runner=BrokenShutdownRunner(
                [LoadedExtension(name="demo", source_path=Path("/tmp/demo.py"))]
            ),
        )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=_factory,
        persist=True,
        diagnostics_service=diagnostics_service,
    )
    project = tmp_path / "project"
    project.mkdir()
    first = await runtime.create_session(cwd=str(project))
    first.footer_data_provider.set_extension_status("demo", "running")

    second = await runtime.new_session()
    records = diagnostics_service.get_diagnostics(
        query=DiagnosticsQuery(code="session_shutdown_failed")
    )

    assert runtime.get_current_session() is second
    assert second is not first
    assert first.footer_data_provider.get_extension_statuses() == {}
    assert len(records) == 1
    assert records[0].message == "shutdown transport boom"
    assert records[0].session_id == first.session_id
    assert records[0].details["reason"] == "new"
    assert records[0].details["target_session_file"] == str(
        second.session_manager.session_file
    )


@_async_test
async def test_runtime_new_session_factory_failure_keeps_current_session_alive(
    tmp_path,
) -> None:
    import pytest

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    created = 0

    def _factory(manager: SessionManager) -> DummySession:
        nonlocal created
        created += 1
        if created == 2:
            raise RuntimeError("factory boom")
        return DummySession(manager)

    runtime = AgentSessionRuntime(
        session_dir=tmp_path, session_factory=_factory, persist=False
    )
    project = tmp_path / "project"
    project.mkdir()
    first = await runtime.create_session(cwd=str(project))

    with pytest.raises(RuntimeError, match="factory boom"):
        await runtime.new_session()

    assert runtime.get_current_session() is first
    assert first.disposed is False


@_async_test
async def test_runtime_replacements_are_serialized(tmp_path) -> None:
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.diagnostics_service = None
            self.disposed = False
            self.dispose_calls = 0
            self.dispose_started: asyncio.Event | None = None
            self.dispose_release: asyncio.Event | None = None

        async def dispose(self) -> None:
            self.dispose_calls += 1
            self.disposed = True
            if self.dispose_started is not None:
                self.dispose_started.set()
            if self.dispose_release is not None:
                await self.dispose_release.wait()

    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager),
        persist=False,
    )
    project = tmp_path / "project"
    project.mkdir()

    async def scenario():
        first = await runtime.create_session(cwd=str(project))
        first.dispose_started = asyncio.Event()
        first.dispose_release = asyncio.Event()
        first_replacement = asyncio.create_task(runtime.new_session())
        await first.dispose_started.wait()
        second_replacement = asyncio.create_task(runtime.new_session())
        await asyncio.sleep(0)
        first.dispose_release.set()
        second, third = await asyncio.gather(first_replacement, second_replacement)
        return first, second, third

    first, second, third = await scenario()

    assert first.dispose_calls == 1
    assert second.dispose_calls == 1
    assert third.dispose_calls == 0
    assert runtime.get_current_session() is third


@_async_test
async def test_runtime_dispose_records_session_index_flush_failure(
    tmp_path, monkeypatch
) -> None:
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsQuery, DiagnosticsService
    from loushang.harness.transcript import AgentTranscriptSessionCatalog

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    diagnostics_service = DiagnosticsService()
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager),
        persist=False,
        diagnostics_service=diagnostics_service,
        auto_refresh_session_index=True,
        session_index_flush_delay=60.0,
    )
    project = tmp_path / "project"
    project.mkdir()

    async def scenario() -> DummySession:
        session = await runtime.create_session(cwd=str(project))

        def _fail_refresh_index(self):
            del self
            raise RuntimeError("index boom")

        monkeypatch.setattr(
            AgentTranscriptSessionCatalog,
            "refresh_index",
            _fail_refresh_index,
        )
        await runtime.dispose()
        return session

    session = await scenario()
    records = diagnostics_service.get_diagnostics(
        query=DiagnosticsQuery(code="session_index_refresh_failed")
    )

    assert runtime.get_current_session() is None
    assert session.disposed is True
    assert len(records) == 1
    assert records[0].message == "index boom"
    assert records[0].details == {"all_sessions": False, "session_dir": str(tmp_path)}


@_async_test
async def test_runtime_exposes_current_session_and_cwd_properties(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=False
    )

    session = await runtime.create_session(cwd=str(project))

    assert runtime.session is session
    assert runtime.current_session is session
    assert runtime.cwd == str(project.resolve())


@_async_test
async def test_runtime_replacement_callbacks_run_before_with_session(tmp_path) -> None:
    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager

    class DummySession:
        def __init__(self, manager: SessionManager) -> None:
            self.session_manager = manager
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager),
        persist=False,
    )
    project = tmp_path / "project"
    project.mkdir()
    first = await runtime.create_session(cwd=str(project))
    events: list[tuple[str, object]] = []

    async def _rebind(session):
        events.append(("rebind", session is runtime.get_current_session()))

    def _before_invalidate() -> None:
        events.append(("before", first.disposed))

    async def _with_session(ctx):
        events.append(
            (
                "withSession",
                ctx.session_manager is runtime.get_current_session().session_manager,
            )
        )

    runtime.set_rebind_session(_rebind)
    runtime.set_before_session_invalidate(_before_invalidate)

    await runtime.new_session_operation(with_session=_with_session)

    assert events == [
        ("before", False),
        ("rebind", True),
        ("withSession", True),
    ]
    assert first.disposed is True


@_async_test
async def test_runtime_restore_session_accepts_session_id(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )

    created = await runtime.create_session(cwd=str(project))
    await created.session_manager.append_message(_user_message("materialize"))
    restored = await runtime.restore_session(created.session_id)

    assert restored.session_id == created.session_id
    assert restored.session_manager.get_cwd() == str(project.resolve())


@_async_test
async def test_runtime_restore_session_accepts_session_id_prefix(tmp_path) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )

    created = await runtime.create_session(cwd=str(project))
    await created.session_manager.append_message(_user_message("materialize"))
    restored = await runtime.restore_session(created.session_id[:8])

    assert restored.session_id == created.session_id


@_async_test
async def test_runtime_restore_session_rejects_ambiguous_session_id_prefix(
    tmp_path,
) -> None:
    import pytest

    from loushang.coding.bootstrap import create_agent_session_runtime
    from loushang.harness.conversation import ConversationHeader
    from loushang.harness.transcript.jsonl_file import (
        write_agent_transcript_export as write_session_file,
    )

    project = tmp_path / "project"
    project.mkdir()
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=True
    )
    timestamp = "2026-05-01T00:00:00Z"
    for session_id in ("abcdef01", "abcdef02"):
        write_session_file(
            tmp_path / f"{timestamp}_{session_id}.jsonl",
            ConversationHeader(
                conversation_id=session_id,
                version=1,
                created_at=timestamp,
                metadata={"cwd": str(project)},
            ),
            [],
        )

    with pytest.raises(ValueError, match="Ambiguous session reference"):
        await runtime.restore_session("abcdef")


@_async_test
async def test_runtime_create_session_normalizes_cwd_and_rejects_missing_paths(
    tmp_path,
) -> None:
    from loushang.coding.bootstrap import create_agent_session_runtime

    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    runtime = create_agent_session_runtime(
        session_dir=tmp_path, model=_model(), persist=False
    )

    created = await runtime.create_session(cwd=str(nested / ".."))

    assert created.session_manager.get_cwd() == str(project.resolve())

    try:
        await runtime.create_session(cwd=str(tmp_path / "missing"))
    except FileNotFoundError as exc:
        assert exc.filename == str(tmp_path / "missing")
    else:
        raise AssertionError("create_session should reject missing cwd paths")


@_async_test
async def test_runtime_new_session_respects_extension_before_switch_cancellation(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionActionDecision,
    )

    class DummySession:
        def __init__(self, manager: SessionManager, runner: ExtensionRunner) -> None:
            self.session_manager = manager
            self.extension_runner = runner
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    seen: list[tuple[str, str, str | None]] = []

    def _before_switch(event, ctx):
        seen.append((event.reason, ctx.cwd, event.target_session_file))
        return SessionActionDecision(cancel=True)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/demo.py"),
                hooks={"session_before_switch": [_before_switch]},
            )
        ]
    )
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager, runner),
        persist=False,
    )
    project = tmp_path / "project"
    project.mkdir()

    first = await runtime.create_session(cwd=str(project))
    second = await runtime.new_session()

    assert second is first
    assert runtime.get_current_session() is first
    assert first.disposed is False
    assert seen == [("new", str(project.resolve()), None)]


@_async_test
async def test_runtime_fork_session_respects_extension_before_fork_cancellation(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionActionDecision,
    )

    class DummySession:
        def __init__(self, manager: SessionManager, runner: ExtensionRunner) -> None:
            self.session_manager = manager
            self.extension_runner = runner
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    seen: list[str] = []

    def _before_fork(event, ctx):
        del ctx
        seen.append(event.entry_id)
        return SessionActionDecision(cancel=True)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/demo.py"),
                hooks={"session_before_fork": [_before_fork]},
            )
        ]
    )
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager, runner),
        persist=False,
    )
    project = tmp_path / "project"
    project.mkdir()

    current = await runtime.create_session(cwd=str(project))
    first_entry_id = await current.session_manager.append_message(_user_message("root"))
    forked = await runtime.fork_session(first_entry_id)

    assert forked is current
    assert runtime.get_current_session() is current
    assert current.disposed is False
    assert seen == [first_entry_id]


@_async_test
async def test_runtime_new_session_allows_extension_non_cancel_decision(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionActionDecision,
    )

    class DummySession:
        def __init__(self, manager: SessionManager, runner: ExtensionRunner) -> None:
            self.session_manager = manager
            self.extension_runner = runner
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    seen: list[tuple[str, str, str | None]] = []

    def _before_switch(event, ctx):
        del ctx
        seen.append((event.reason, event.cwd, event.target_session_file))
        return SessionActionDecision(cancel=False)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/demo.py"),
                hooks={"session_before_switch": [_before_switch]},
            )
        ]
    )
    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager, runner),
        persist=False,
    )
    project = tmp_path / "project"
    project.mkdir()

    first = await runtime.create_session(cwd=str(project))
    second = await runtime.new_session()

    assert second is not first
    assert runtime.get_current_session() is second
    assert first.disposed is True
    assert seen == [("new", str(project.resolve()), None)]


@_async_test
async def test_runtime_restore_session_allows_extension_non_cancel_decision(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionActionDecision,
    )

    class DummySession:
        def __init__(self, manager: SessionManager, runner: ExtensionRunner) -> None:
            self.session_manager = manager
            self.extension_runner = runner
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    seen: list[tuple[str, str, str]] = []

    def _before_switch(event, ctx):
        del ctx
        seen.append((event.reason, event.cwd, event.target_session_file))
        return SessionActionDecision(cancel=False)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/demo.py"),
                hooks={"session_before_switch": [_before_switch]},
            )
        ]
    )

    project = tmp_path / "project"
    target = tmp_path / "target"
    project.mkdir()
    target.mkdir()
    current_manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(project), persist=True
    )
    target_manager = await SessionManager.new(
        session_dir=tmp_path, cwd=str(target), persist=True
    )
    await target_manager.append_message(_user_message("from target"))

    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager, runner),
        persist=False,
        current_session=DummySession(current_manager, runner),
    )
    current = runtime.get_current_session()
    assert current is not None

    restored = await runtime.restore_session(target_manager.session_file)

    assert restored is not current
    assert current.disposed is True
    assert runtime.get_current_session() is restored
    assert isinstance(restored, DummySession)
    assert [entry.record_id for entry in restored.session_manager.get_entries()] == [
        target_manager.get_entries()[0].record_id
    ]
    assert seen == [
        ("resume", str(project.resolve()), str(target_manager.session_file))
    ]


@_async_test
async def test_runtime_fork_session_allows_extension_non_cancel_decision(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.coding.runtime import AgentSessionRuntime
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionActionDecision,
    )

    class DummySession:
        def __init__(self, manager: SessionManager, runner: ExtensionRunner) -> None:
            self.session_manager = manager
            self.extension_runner = runner
            self.diagnostics_service = None
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    seen: list[tuple[str, str]] = []

    def _before_fork(event, ctx):
        del ctx
        seen.append((event.entry_id, event.cwd))
        return SessionActionDecision(cancel=False)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/demo.py"),
                hooks={"session_before_fork": [_before_fork]},
            )
        ]
    )

    runtime = AgentSessionRuntime(
        session_dir=tmp_path,
        session_factory=lambda manager: DummySession(manager, runner),
        persist=False,
    )
    project = tmp_path / "project"
    project.mkdir()

    current = await runtime.create_session(cwd=str(project))
    fork_entry = await current.session_manager.append_message(_user_message("root"))
    forked = await runtime.fork_session(fork_entry)

    assert forked is not current
    assert runtime.get_current_session() is forked
    assert current.disposed is True
    assert [entry.record_id for entry in forked.session_manager.get_branch()] == [
        fork_entry
    ]
    assert seen == [(fork_entry, str(project.resolve()))]
