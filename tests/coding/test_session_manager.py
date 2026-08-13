from __future__ import annotations

import asyncio
import json
from functools import wraps


def _async_test(test):
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))

    return run


@_async_test
async def test_append_entry_advances_leaf_id(tmp_path) -> None:
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=False,
    )

    entry_id = await manager.append_session_info("demo")

    assert manager.get_leaf_id() == entry_id


@_async_test
async def test_commit_observer_receives_exact_receipts_and_skips_idempotent_hits(
    tmp_path,
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import ApplicationMessage

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=False,
    )
    observed = []
    manager.set_commit_observer(observed.append)

    await asyncio.gather(
        manager.append_message(UserMessage(role="user", content="one", timestamp=1.0)),
        manager.append_message(UserMessage(role="user", content="two", timestamp=2.0)),
    )
    application = ApplicationMessage(
        application_message_id="application-1",
        custom_type="notice",
        content="three",
        timestamp=3.0,
    )
    first_application_id = await manager.append_message(application)
    duplicate_application_id = await manager.append_message(application)

    assert duplicate_application_id == first_application_id
    assert [result.receipt.revision for result in observed] == [1, 2, 3]
    assert [result.record_id for result in observed] == [
        record.record_id for record in manager.get_entries()
    ]
    assert all(result.disposition == "committed" for result in observed)
    assert all(result.receipt.committed_at.tzinfo is not None for result in observed)


@_async_test
async def test_load_summary_awaits_session_load(tmp_path) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=True,
    )
    await manager.append_message(
        UserMessage(role="user", content="materialize", timestamp=0.0)
    )
    session_file = manager.get_session_file()
    assert session_file is not None

    summary = await SessionManager.load_summary(session_file)

    assert summary.session_id == manager.get_header().conversation_id


@_async_test
async def test_persistent_session_accepts_pre_release_transcript_format_alias(
    tmp_path,
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd=str(tmp_path),
        persist=True,
    )
    await manager.append_message(
        UserMessage(role="user", content="materialize", timestamp=0.0)
    )
    session_file = manager.get_session_file()
    assert session_file is not None
    await manager.dispose_runtime_profile()

    lines = session_file.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    transcript = next(
        capability
        for capability in header["metadata"]["runtimeProfile"]["capabilities"]
        if capability["slot"] == "agent.transcript_profile"
    )
    transcript["selections"][0]["config"] = {"format": "current"}
    capability_profile = header["metadata"]["capabilityProfile"]
    capability_profile["capabilities"] = [
        capability
        for capability in capability_profile["capabilities"]
        if capability["slot"] != "continuity.provider_packs"
    ]
    lines[0] = json.dumps(header, ensure_ascii=False, separators=(",", ":"))
    session_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    restored = await SessionManager.open(session_file, persist=True)

    assert restored.get_header().conversation_id == manager.get_header().conversation_id
    await restored.dispose_runtime_profile()


@_async_test
async def test_new_session_manager_has_header_and_no_leaf(tmp_path) -> None:
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=False,
    )

    assert manager.get_header().version == 1
    assert manager.get_leaf_id() is None


@_async_test
async def test_new_session_manager_accepts_custom_session_id(tmp_path) -> None:
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=True,
        session_id="my-custom-id",
    )

    assert manager.get_header().conversation_id == "my-custom-id"
    assert (
        manager.get_session_file()
        == tmp_path
        / f"{manager.get_header().created_at.replace(':', '-').replace('.', '-')}_my-custom-id.jsonl"
    )


@_async_test
async def test_in_memory_session_manager_accepts_custom_session_id() -> None:
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.in_memory(
        cwd="/tmp/project", session_id="memory-session"
    )

    assert manager.get_header().conversation_id == "memory-session"
    assert manager.get_session_file() is None


@_async_test
async def test_loaded_non_persistent_session_is_mutable_without_rewriting_source(
    tmp_path,
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager

    source = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=True,
    )
    await source.append_message(
        UserMessage(role="user", content="saved", timestamp=0.0)
    )
    source_file = source.get_session_file()
    assert source_file is not None
    original = source_file.read_bytes()

    detached = await SessionManager.open(
        source_file,
        cwd_override="/tmp/other-project",
        persist=False,
    )
    await detached.append_message(
        UserMessage(role="user", content="memory only", timestamp=1.0)
    )

    assert detached.get_cwd() == "/tmp/other-project"
    assert len(detached.get_entries()) == 2
    assert source_file.read_bytes() == original


@_async_test
async def test_new_session_manager_rejects_blank_custom_session_id(tmp_path) -> None:
    import pytest

    from loushang.coding.session_manager import SessionManager

    with pytest.raises(ValueError, match="session_id must not be blank"):
        await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=False,
            session_id="  ",
        )


@_async_test
async def test_branch_changes_active_leaf_without_losing_existing_path(
    tmp_path,
) -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=False,
    )

    first_id = await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="root")],
            timestamp=0.0,
        )
    )
    second_id = await manager.append_message(
        AssistantMessage(
            endpoint="kimi-code-anthropic",
            role="assistant",
            content=[TextPart(type="text", text="middle")],
            api="anthropic-messages",
            provider="faux",
            model="faux-model",
            response_id=None,
            usage=Usage(
                input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=0.0,
        )
    )
    third_id = await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="tail")],
            timestamp=0.0,
        )
    )

    manager.branch(first_id)
    branch_leaf_id = await manager.append_session_info("forked")

    assert [entry.record_id for entry in manager.get_branch()] == [
        first_id,
        branch_leaf_id,
    ]
    assert [entry.record_id for entry in manager.get_branch(third_id)] == [
        first_id,
        second_id,
        third_id,
    ]
    assert manager.get_entry(branch_leaf_id).parent_id == first_id


@_async_test
async def test_create_branched_session_persists_only_selected_path(tmp_path) -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=True,
    )

    first_id = await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="root")],
            timestamp=0.0,
        )
    )
    second_id = await manager.append_message(
        AssistantMessage(
            endpoint="kimi-code-anthropic",
            role="assistant",
            content=[TextPart(type="text", text="answer")],
            api="anthropic-messages",
            provider="faux",
            model="faux-model",
            response_id=None,
            usage=Usage(
                input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=0.0,
        )
    )
    await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="tail")],
            timestamp=0.0,
        )
    )

    branched_file = await manager.create_branched_session(second_id)
    assert branched_file is not None

    forked = await SessionManager.load(branched_file)

    assert [entry.record_id for entry in forked.get_branch()] == [first_id, second_id]
    assert forked.get_header().metadata["parentSession"] == str(manager.session_file)


@_async_test
async def test_append_message_rejects_non_transcript_messages(tmp_path) -> None:
    import pytest

    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=False,
    )

    with pytest.raises(TypeError, match="Unsupported transcript message"):
        await manager.append_message(object())


@_async_test
async def test_session_manager_rejects_non_json_custom_metadata(tmp_path) -> None:
    from pathlib import Path

    import pytest

    from loushang.coding.session_manager import SessionManager
    from loushang.foundation.json import JsonValueError

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=False,
    )

    with pytest.raises(JsonValueError) as exc_info:
        await manager.append_custom_entry("demo", {"path": Path("notes.txt")})

    assert exc_info.value.path == "custom_entry.data.path"


@_async_test
async def test_branch_with_summary_creates_projected_branch_entry(tmp_path) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import (
        CONTEXT_BRANCH_SUMMARY_KIND,
        BranchContextSummary,
    )

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=False,
    )

    root_id = await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="root")],
            timestamp=0.0,
        )
    )
    tail_id = await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="tail")],
            timestamp=0.0,
        )
    )

    summary_id = await manager.branch_with_summary(root_id, "forked away from tail")

    summary_entry = manager.get_entry(summary_id)

    assert summary_entry.kind == CONTEXT_BRANCH_SUMMARY_KIND
    assert isinstance(summary_entry.payload, BranchContextSummary)
    assert manager.get_leaf_id() == summary_id
    assert summary_entry.parent_id == root_id
    assert summary_entry.payload.from_record_id == root_id
    assert [entry.record_id for entry in manager.get_branch()] == [root_id, summary_id]
    assert [entry.record_id for entry in manager.get_branch(tail_id)] == [
        root_id,
        tail_id,
    ]
    assert [message.role for message in manager.build_session_context().messages] == [
        "user",
        "user",
    ]


@_async_test
async def test_branch_summary_commit_failure_restores_selected_leaf(
    tmp_path, monkeypatch
) -> None:
    import pytest

    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=False,
    )
    root_id = await manager.append_message(
        UserMessage(role="user", content="root", timestamp=0.0)
    )
    tail_id = await manager.append_message(
        UserMessage(role="user", content="tail", timestamp=1.0)
    )

    async def fail_append(*args, **kwargs):
        del args, kwargs
        raise OSError("backend unavailable")

    monkeypatch.setattr(manager._transcript, "append_branch_summary", fail_append)

    with pytest.raises(OSError, match="backend unavailable"):
        await manager.branch_with_summary(root_id, "summary")

    assert manager.get_leaf_id() == tail_id


@_async_test
async def test_get_tree_and_children_reflect_current_branches(tmp_path) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=False,
    )

    root_id = await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="root")],
            timestamp=0.0,
        )
    )
    first_child_id = await manager.append_session_info("main")
    manager.branch(root_id)
    second_child_id = await manager.append_session_info("fork")

    assert manager.get_leaf_entry() is not None
    assert manager.get_leaf_entry().record_id == second_child_id
    assert [entry.record_id for entry in manager.get_children(root_id)] == [
        first_child_id,
        second_child_id,
    ]

    tree = manager.get_tree()

    assert [node.record.record_id for node in tree] == [root_id]
    assert [child.record.record_id for child in tree[0].children] == [
        first_child_id,
        second_child_id,
    ]


@_async_test
async def test_labels_are_indexed_and_rebuilt_on_reload(tmp_path) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=True,
    )

    root_id = await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="root")],
            timestamp=0.0,
        )
    )
    await manager.append_label(root_id, "bookmark")

    assert manager.get_label(root_id) == "bookmark"
    assert manager.get_tree()[0].label == "bookmark"

    reloaded = await SessionManager.load(manager.get_session_file())

    assert reloaded.get_label(root_id) == "bookmark"
    assert reloaded.get_tree()[0].label == "bookmark"


@_async_test
async def test_list_skips_invalid_session_files(tmp_path) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="hello")],
            timestamp=0.0,
        )
    )

    (tmp_path / "broken.jsonl").write_text("not jsonl content\n", encoding="utf-8")
    (tmp_path / "not-session.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "bad-session-line.jsonl").write_text(
        '{"type":"session","timestamp":"x","cwd":"/tmp"}\n{invalid}\n', encoding="utf-8"
    )

    records = SessionManager.list(tmp_path)

    assert len(records) == 1
    assert records[0].session_id == manager.get_session_record().session_id


@_async_test
async def test_session_summary_includes_context_metadata(tmp_path) -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await manager.append_session_info("Demo Session")
    await manager.append_model_change(
        "moonshot", "kimi-k2.5", endpoint_id="kimi-code-anthropic"
    )
    await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="please inspect the repository")],
            timestamp=0.0,
        )
    )
    await manager.append_message(
        AssistantMessage(
            endpoint="kimi-code-anthropic",
            role="assistant",
            content=[TextPart(type="text", text="repository inspection complete")],
            api="anthropic-messages",
            provider="moonshot",
            model="kimi-k2.5",
            response_id=None,
            usage=Usage(
                input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=0.0,
        )
    )

    summary = manager.get_session_summary()

    assert summary.session_id == manager.get_header().conversation_id
    assert summary.cwd == "/tmp/project"
    assert summary.name == "Demo Session"
    assert summary.message_count == 2
    assert summary.entry_count == 4
    assert summary.first_message == "please inspect the repository"
    assert (
        summary.all_messages_text
        == "please inspect the repository repository inspection complete"
    )
    assert summary.last_message_preview == "repository inspection complete"
    assert summary.model == {
        "provider": "moonshot",
        "endpoint_id": "kimi-code-anthropic",
        "model_id": "kimi-k2.5",
    }


@_async_test
async def test_list_summaries_and_find_sessions_query_across_session_files(
    tmp_path,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import SessionQuery

    first = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project-a", persist=True
    )
    await first.append_session_info("Alpha")
    await first.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="alpha repository task")],
            timestamp=0.0,
        )
    )

    second = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project-b",
        persist=True,
        parent_session=str(first.get_session_file()),
    )
    await second.append_session_info("Beta")
    await second.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="beta follow up")],
            timestamp=0.0,
        )
    )

    summaries = SessionManager.list_summaries(tmp_path)

    assert {summary.session_id for summary in summaries} == {
        first.get_header().conversation_id,
        second.get_header().conversation_id,
    }
    assert [
        summary.name
        for summary in SessionManager.find_sessions(
            tmp_path, SessionQuery(cwd="/tmp/project-a")
        )
    ] == ["Alpha"]
    assert [
        summary.name
        for summary in SessionManager.find_sessions(tmp_path, SessionQuery(name="bet"))
    ] == ["Beta"]
    assert [
        summary.name
        for summary in SessionManager.find_sessions(
            tmp_path, SessionQuery(text="repository")
        )
    ] == ["Alpha"]
    assert [
        summary.name
        for summary in SessionManager.find_sessions(
            tmp_path, SessionQuery(parent_session=str(first.get_session_file()))
        )
    ] == ["Beta"]
    assert len(SessionManager.find_sessions(tmp_path, SessionQuery(limit=1))) == 1


@_async_test
async def test_list_summaries_skips_one_projection_failure(
    tmp_path, monkeypatch
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import session_catalog as catalog_module

    good = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/good",
        persist=True,
        session_id="good",
    )
    bad = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/bad",
        persist=True,
        session_id="bad",
    )
    await good.append_message(UserMessage(role="user", content="good", timestamp=0.0))
    await bad.append_message(UserMessage(role="user", content="bad", timestamp=0.0))
    original = catalog_module.project_agent_transcript_session_summary

    def project(header, records, leaf_id, source_path, *, locator=None):
        if header.conversation_id == "bad":
            raise ValueError("bad product projection")
        return original(
            header,
            records,
            leaf_id,
            source_path,
            locator=locator,
        )

    monkeypatch.setattr(
        catalog_module,
        "project_agent_transcript_session_summary",
        project,
    )

    assert [
        summary.session_id for summary in SessionManager.list_summaries(tmp_path)
    ] == ["good"]


@_async_test
async def test_session_manager_rename_session_file_appends_session_info(
    tmp_path,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="hello")],
            timestamp=1000.0,
        )
    )
    session_file = manager.get_session_file()
    assert session_file is not None

    renamed = await SessionManager.rename_session(session_file, "  Renamed Session  ")
    cleared = await SessionManager.rename_session(session_file, "  ")

    assert renamed.name == "Renamed Session"
    assert cleared.name is None
    reloaded = await SessionManager.load(session_file)
    assert reloaded.get_session_summary().name is None


@_async_test
async def test_session_manager_delete_session_file_preserves_stable_lock(
    tmp_path,
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager

    manager = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await manager.append_message(
        UserMessage(role="user", content="materialize", timestamp=0.0)
    )
    session_file = manager.get_session_file()
    assert session_file is not None
    lock_file = session_file.with_name(f"{session_file.name}.lock")
    await SessionManager.load(session_file)
    assert lock_file.exists()

    assert await SessionManager.delete_session(session_file) is True
    assert session_file.exists() is False
    assert lock_file.exists() is True
    assert await SessionManager.delete_session(session_file) is False


@_async_test
async def test_session_manager_rename_and_delete_refresh_existing_index(
    tmp_path,
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager

    first = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    second = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await first.append_message(UserMessage(role="user", content="first", timestamp=0.0))
    await second.append_message(
        UserMessage(role="user", content="second", timestamp=0.0)
    )
    first_file = first.get_session_file()
    second_file = second.get_session_file()
    assert first_file is not None
    assert second_file is not None
    SessionManager.refresh_index(tmp_path)

    await SessionManager.rename_session(first_file, "Indexed Name")
    renamed_index = SessionManager.list_indexed_summaries(tmp_path)
    await SessionManager.delete_session(second_file)
    deleted_index = SessionManager.list_indexed_summaries(tmp_path)

    assert (
        next(
            summary
            for summary in renamed_index
            if summary.session_id == first.get_header().conversation_id
        ).name
        == "Indexed Name"
    )
    assert {summary.session_id for summary in deleted_index} == {
        first.get_header().conversation_id
    }


@_async_test
async def test_current_session_rename_incrementally_updates_existing_index(
    tmp_path, monkeypatch
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import AgentTranscriptSessionCatalog

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=True,
    )
    await manager.append_message(
        UserMessage(role="user", content="hello", timestamp=1.0)
    )
    SessionManager.refresh_index(tmp_path)

    def fail_repair(_self):
        raise AssertionError("rename must not rebuild the full index")

    monkeypatch.setattr(AgentTranscriptSessionCatalog, "repair_index", fail_repair)

    await manager.append_session_info("Renamed now")

    snapshot = AgentTranscriptSessionCatalog(tmp_path).try_query_index_snapshot()
    assert snapshot.index_state == "fresh"
    assert len(snapshot.items) == 1
    assert snapshot.items[0].projection.name == "Renamed now"
    assert snapshot.items[0].source_revision == 2


@_async_test
async def test_renaming_empty_session_does_not_materialize_transcript(tmp_path) -> None:
    from loushang.coding.session_manager import SessionManager

    SessionManager.refresh_index(tmp_path)
    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=True,
    )

    await manager.append_session_info("Still empty")

    assert manager.is_persisted() is False
    assert list(tmp_path.glob("*.jsonl")) == []
    assert SessionManager.list_indexed_summaries(tmp_path) == []


@_async_test
async def test_session_manager_dispose_upserts_changed_summary_into_existing_index(
    tmp_path,
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import AgentTranscriptSessionCatalog

    manager = await SessionManager.new(
        session_dir=tmp_path,
        cwd="/tmp/project",
        persist=True,
    )
    await manager.append_message(
        UserMessage(role="user", content="first", timestamp=1.0)
    )
    SessionManager.refresh_index(tmp_path)
    await manager.append_message(UserMessage(role="user", content="hi", timestamp=2.0))
    expected = manager.get_session_summary()

    await manager.dispose_runtime_profile()

    snapshot = AgentTranscriptSessionCatalog(tmp_path).try_query_index_snapshot()
    assert snapshot.index_state == "fresh"
    assert len(snapshot.items) == 1
    indexed = snapshot.items[0]
    assert indexed.source_revision == 2
    assert indexed.projection.updated_at == expected.updated_at
    assert indexed.projection.last_message_preview == "hi"


@_async_test
async def test_session_manager_rename_and_delete_survive_index_refresh_failure(
    tmp_path, monkeypatch
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager

    first = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    second = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await first.append_message(UserMessage(role="user", content="first", timestamp=0.0))
    await second.append_message(
        UserMessage(role="user", content="second", timestamp=0.0)
    )
    first_file = first.get_session_file()
    second_file = second.get_session_file()
    assert first_file is not None
    assert second_file is not None
    SessionManager.refresh_index(tmp_path)

    def _fail_refresh_index(cls, session_dir):
        del cls, session_dir
        raise RuntimeError("index boom")

    monkeypatch.setattr(
        SessionManager, "refresh_index", classmethod(_fail_refresh_index)
    )

    renamed = await SessionManager.rename_session(first_file, "Renamed Anyway")
    deleted = await SessionManager.delete_session(second_file)

    assert renamed.name == "Renamed Anyway"
    assert deleted is True
    reloaded = await SessionManager.load(first_file)
    assert reloaded.get_session_summary().name == "Renamed Anyway"
    assert second_file.exists() is False


@_async_test
async def test_session_manager_delete_session_file_refuses_current_session_alias(
    tmp_path,
) -> None:
    import pytest

    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager

    real_dir = tmp_path / "real"
    alias_dir = tmp_path / "alias"
    real_dir.mkdir()
    alias_dir.symlink_to(real_dir, target_is_directory=True)
    manager = await SessionManager.new(
        session_dir=real_dir, cwd="/tmp/project", persist=True
    )
    await manager.append_message(
        UserMessage(role="user", content="materialize", timestamp=0.0)
    )
    session_file = manager.get_session_file()
    assert session_file is not None
    aliased_file = alias_dir / session_file.name

    with pytest.raises(ValueError, match="currently active session"):
        await SessionManager.delete_session(
            aliased_file, current_session_file=session_file
        )

    assert session_file.exists() is True


@_async_test
async def test_find_sessions_matches_parent_session_across_symlink_aliases(
    tmp_path,
) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import SessionQuery

    real_dir = tmp_path / "real"
    alias_a = tmp_path / "alias-a"
    alias_b = tmp_path / "alias-b"
    real_dir.mkdir()
    alias_a.symlink_to(real_dir, target_is_directory=True)
    alias_b.symlink_to(real_dir, target_is_directory=True)

    parent = await SessionManager.new(
        session_dir=alias_a, cwd="/tmp/project", persist=True
    )
    parent_file = parent.get_session_file()
    assert parent_file is not None
    child = await SessionManager.new(
        session_dir=alias_b,
        cwd="/tmp/project",
        parent_session=str(parent_file),
        persist=True,
    )
    await child.append_session_info("Child")
    await child.append_message(UserMessage(role="user", content="child", timestamp=0.0))

    matched = SessionManager.find_sessions(
        real_dir, SessionQuery(parent_session=str(alias_b / parent_file.name))
    )

    assert [summary.session_id for summary in matched] == [
        child.get_header().conversation_id
    ]


@_async_test
async def test_find_sessions_supports_quoted_phrase_regex_and_named_filter(
    tmp_path,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import SessionQuery

    first = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await first.append_session_info("Named")
    await first.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="node\n\n   cve was discussed")],
            timestamp=2000.0,
        )
    )
    second = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await second.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="bravery is not brave")],
            timestamp=3000.0,
        )
    )

    assert [
        summary.session_id
        for summary in SessionManager.find_sessions(
            tmp_path, SessionQuery(text='"node cve"')
        )
    ] == [first.get_header().conversation_id]
    assert [
        summary.session_id
        for summary in SessionManager.find_sessions(
            tmp_path, SessionQuery(text=r"re:\bbrave\b")
        )
    ] == [second.get_header().conversation_id]
    assert [
        summary.session_id
        for summary in SessionManager.find_sessions(tmp_path, SessionQuery(named=True))
    ] == [first.get_header().conversation_id]
    assert SessionManager.find_sessions(tmp_path, SessionQuery(text="re:(")) == []


@_async_test
async def test_find_sessions_relevance_sort_scores_earlier_matches_before_recent(
    tmp_path,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import SessionQuery

    early_match = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await early_match.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="brave xxxx")],
            timestamp=1000.0,
        )
    )
    later_match = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await later_match.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="xxxx brave")],
            timestamp=3000.0,
        )
    )

    result = SessionManager.find_sessions(
        tmp_path, SessionQuery(text='"brave"', sort_by="relevance")
    )

    assert [summary.session_id for summary in result] == [
        early_match.get_header().conversation_id,
        later_match.get_header().conversation_id,
    ]


@_async_test
async def test_session_summary_searches_all_messages_and_uses_message_modified_time(
    tmp_path,
) -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import SessionQuery

    first = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project-a", persist=True
    )
    await first.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="initial alpha task")],
            timestamp=1000.0,
        )
    )
    await first.append_message(
        AssistantMessage(
            endpoint="test-endpoint",
            role="assistant",
            content=[TextPart(type="text", text="middle-only searchable needle")],
            api="anthropic-messages",
            provider="faux",
            model="faux-model",
            response_id=None,
            usage=Usage(
                input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=2000.0,
        )
    )
    await first.append_session_info("Renamed Later")
    await first.append_custom_entry(
        "diagnostic", {"code": "later_metadata", "level": "warning"}
    )

    second = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project-b", persist=True
    )
    await second.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="newer conversation")],
            timestamp=3000.0,
        )
    )

    summary = first.get_session_summary()

    assert summary.first_message == "initial alpha task"
    assert (
        summary.all_messages_text == "initial alpha task middle-only searchable needle"
    )
    assert summary.updated_at == "1970-01-01T00:33:20Z"
    assert [
        item.session_id
        for item in SessionManager.find_sessions(
            tmp_path, SessionQuery(text="middle-only")
        )
    ] == [first.get_header().conversation_id]
    assert [item.session_id for item in SessionManager.list_summaries(tmp_path)] == [
        second.get_header().conversation_id,
        first.get_header().conversation_id,
    ]


@_async_test
async def test_session_metadata_accepts_message_timestamps_in_milliseconds(
    tmp_path,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.foundation.observability import log_context
    from loushang.foundation.observability._router import (
        get_problem_store,
        reset_observability,
    )

    session = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await session.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="millisecond timestamp")],
            timestamp=1_000_000_000_000.0,
        )
    )

    reset_observability()
    try:
        with log_context(session_id="session-1", cwd="/tmp/project", mode="metadata"):
            assert session.load_metadata().updated_at == "2001-09-09T01:46:40Z"

        records = get_problem_store().all()
        assert len(records) == 1
        assert records[0].code == "session_timestamp_normalized"
        assert records[0].severity == "warning"
        assert records[0].source == "session"
        assert records[0].recoverable is True
        assert records[0].details == {
            "normalized_timestamp": 1_000_000_000.0,
            "original_timestamp": 1_000_000_000_000.0,
            "unit": "milliseconds",
        }
        assert records[0].session_id == "session-1"
        assert records[0].mode == "metadata"
    finally:
        reset_observability()


@_async_test
async def test_session_summary_indexes_diagnostic_custom_entries(tmp_path) -> None:
    from loushang.ai.types import UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import SessionQuery

    clean = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/clean", persist=True
    )
    await clean.append_session_info("Clean")
    await clean.append_message(UserMessage(role="user", content="clean", timestamp=0.0))

    flagged = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/flagged", persist=True
    )
    await flagged.append_session_info("Flagged")
    await flagged.append_custom_entry(
        "diagnostic",
        {
            "code": "model_auth_unresolved",
            "level": "warning",
            "message": "Provider demo has no configured API key.",
        },
    )
    await flagged.append_custom_entry(
        "diagnostic",
        {
            "code": "assistant_response_error",
            "level": "error",
            "message": "provider failed",
        },
    )
    await flagged.append_message(
        UserMessage(role="user", content="flagged", timestamp=0.0)
    )

    summary = flagged.get_session_summary()

    assert summary.has_diagnostics is True
    assert summary.diagnostic_count == 2
    assert summary.last_diagnostic_code == "assistant_response_error"
    assert summary.last_diagnostic_level == "error"
    assert [
        item.name
        for item in SessionManager.find_sessions(
            tmp_path, SessionQuery(has_diagnostics=True)
        )
    ] == ["Flagged"]
    assert [
        item.name
        for item in SessionManager.find_sessions(
            tmp_path, SessionQuery(has_diagnostics=False)
        )
    ] == ["Clean"]
    assert [
        item.name
        for item in SessionManager.find_sessions(
            tmp_path, SessionQuery(text="assistant_response_error")
        )
    ] == ["Flagged"]


@_async_test
async def test_session_manager_writes_and_queries_session_index(tmp_path) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import SessionQuery

    first = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project-a", persist=True
    )
    await first.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="indexable alpha task")],
            timestamp=1000.0,
        )
    )

    nested_dir = tmp_path / "nested"
    nested = await SessionManager.new(
        session_dir=nested_dir, cwd="/tmp/project-b", persist=True
    )
    await nested.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="nested beta task")],
            timestamp=2000.0,
        )
    )

    root_summaries = SessionManager.refresh_index(tmp_path)
    nested_summaries = SessionManager.refresh_index(nested_dir)

    assert SessionManager.index_file(tmp_path).exists()
    assert [summary.session_id for summary in SessionManager.load_index(tmp_path)] == [
        summary.session_id for summary in root_summaries
    ]
    assert [
        summary.session_id
        for summary in SessionManager.find_indexed_sessions(
            tmp_path, SessionQuery(text="alpha")
        )
    ] == [first.get_header().conversation_id]
    assert [
        summary.session_id
        for summary in SessionManager.find_all_indexed_sessions(
            tmp_path, SessionQuery(text="beta")
        )
    ] == [nested.get_header().conversation_id]
    assert [
        summary.session_id
        for summary in SessionManager.list_all_indexed_summaries(tmp_path)
    ] == [
        nested_summaries[0].session_id,
        root_summaries[0].session_id,
    ]


@_async_test
async def test_session_manager_rebuilds_invalid_session_index(tmp_path) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    session = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await session.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="fresh index")],
            timestamp=1000.0,
        )
    )
    SessionManager.index_file(tmp_path).write_text("not-json\n", encoding="utf-8")

    summaries = SessionManager.list_indexed_summaries(tmp_path)

    assert [summary.session_id for summary in summaries] == [
        session.get_header().conversation_id
    ]
    assert (
        SessionManager.load_index(tmp_path)[0].session_id
        == session.get_header().conversation_id
    )


@_async_test
async def test_session_manager_preserves_corrupt_index_for_diagnostics(
    tmp_path,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    session = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project", persist=True
    )
    await session.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="recover me")],
            timestamp=1000.0,
        )
    )
    index_file = SessionManager.index_file(tmp_path)
    index_file.write_text("not-json\n", encoding="utf-8")

    summaries = SessionManager.list_indexed_summaries(tmp_path)

    assert [summary.session_id for summary in summaries] == [
        session.get_header().conversation_id
    ]
    corrupt_files = sorted(tmp_path.glob(".session-index.json.corrupt-*"))
    assert len(corrupt_files) == 1
    assert corrupt_files[0].read_text(encoding="utf-8") == "not-json\n"


@_async_test
async def test_session_manager_rebuilds_stale_index_when_indexed_session_file_disappears(
    tmp_path,
) -> None:
    import json

    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    first = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project-a", persist=True
    )
    await first.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="keep me")],
            timestamp=1000.0,
        )
    )
    second = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/project-b", persist=True
    )
    await second.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="delete me")],
            timestamp=2000.0,
        )
    )
    second_file = second.get_session_file()
    assert second_file is not None
    SessionManager.refresh_index(tmp_path)

    second_file.unlink()
    summaries = SessionManager.list_indexed_summaries(tmp_path)
    raw_index = json.loads(
        SessionManager.index_file(tmp_path).read_text(encoding="utf-8")
    )

    assert [summary.session_id for summary in summaries] == [
        first.get_header().conversation_id
    ]
    assert [item["projection"]["session_id"] for item in raw_index["items"]] == [
        first.get_header().conversation_id
    ]


@_async_test
async def test_session_manager_rebuilds_nested_stale_indexes_during_all_index_query(
    tmp_path,
) -> None:
    import json

    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    root = await SessionManager.new(
        session_dir=tmp_path, cwd="/tmp/root-project", persist=True
    )
    await root.append_message(
        UserMessage(
            role="user", content=[TextPart(type="text", text="root")], timestamp=1000.0
        )
    )
    nested_dir = tmp_path / "nested"
    nested = await SessionManager.new(
        session_dir=nested_dir, cwd="/tmp/nested-project", persist=True
    )
    await nested.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="nested")],
            timestamp=2000.0,
        )
    )
    nested_file = nested.get_session_file()
    assert nested_file is not None
    SessionManager.refresh_all_indexes(tmp_path)

    nested_file.unlink()
    summaries = SessionManager.list_all_indexed_summaries(tmp_path)
    nested_index = json.loads(
        SessionManager.index_file(nested_dir).read_text(encoding="utf-8")
    )

    assert [summary.session_id for summary in summaries] == [
        root.get_header().conversation_id
    ]
    assert nested_index["items"] == []


@_async_test
async def test_find_sessions_rejects_negative_limit(tmp_path) -> None:
    import pytest

    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import SessionQuery

    with pytest.raises(ValueError, match="limit"):
        SessionManager.find_sessions(tmp_path, SessionQuery(limit=-1))


@_async_test
async def test_session_manager_open_can_override_session_dir_and_cwd(tmp_path) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    source_dir = tmp_path / "source"
    future_dir = tmp_path / "future"
    manager = await SessionManager.new(
        session_dir=source_dir, cwd="/tmp/original", persist=True
    )
    await manager.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="hello")],
            timestamp=0.0,
        )
    )

    opened = await SessionManager.open(
        manager.get_session_file(), session_dir=future_dir, cwd_override="/tmp/current"
    )

    assert opened.get_cwd() == "/tmp/current"
    assert opened.get_session_dir() == future_dir
    assert opened.get_session_file() == manager.get_session_file()
    assert opened.get_header().metadata["cwd"] == "/tmp/original"


@_async_test
async def test_session_manager_open_rejects_invalid_empty_session_file(
    tmp_path,
) -> None:
    import pytest

    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript.jsonl_file import (
        AgentTranscriptFileError as SessionFileError,
    )

    session_file = tmp_path / "empty.jsonl"
    session_file.write_text("", encoding="utf-8")

    with pytest.raises(SessionFileError) as exc_info:
        await SessionManager.open(
            session_file,
            session_dir=tmp_path / "future",
            cwd_override="/tmp/current",
            persist=True,
        )

    assert exc_info.value.code == "empty_session_file"


@_async_test
async def test_session_manager_open_rejects_invalid_header_session_file(
    tmp_path,
) -> None:
    import pytest

    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript.jsonl_file import (
        AgentTranscriptFileError as SessionFileError,
    )

    session_file = tmp_path / "broken.jsonl"
    session_file.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(SessionFileError, match="header is not valid JSON"):
        await SessionManager.open(
            session_file, cwd_override="/tmp/current", persist=True
        )

    assert session_file.read_text(encoding="utf-8") == "not-json\n"


@_async_test
async def test_session_manager_open_rejects_missing_header_session_file(
    tmp_path,
) -> None:
    import pytest

    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript.jsonl_file import (
        AgentTranscriptFileError as SessionFileError,
    )

    session_file = tmp_path / "not-session.jsonl"
    session_file.write_text(
        '{"type":"message","id":"e1","timestamp":"x"}\n', encoding="utf-8"
    )

    with pytest.raises(SessionFileError, match="format is not supported"):
        await SessionManager.open(
            session_file, cwd_override="/tmp/current", persist=True
        )

    assert session_file.read_text(encoding="utf-8") == (
        '{"type":"message","id":"e1","timestamp":"x"}\n'
    )


@_async_test
async def test_session_manager_rejects_session_v3_without_rewriting_it(
    tmp_path,
) -> None:
    import json

    import pytest

    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript.jsonl_file import (
        AgentTranscriptFileError as SessionFileError,
    )

    session_file = tmp_path / "session-v3.jsonl"
    values = [
        {
            "type": "session",
            "version": 3,
            "id": "session-1",
            "timestamp": "2026-07-16T00:00:00Z",
            "cwd": "/tmp/project",
            "parentSession": None,
        }
    ]
    session_file.write_text(
        "".join(json.dumps(value) + "\n" for value in values),
        encoding="utf-8",
    )
    original = session_file.read_bytes()

    with pytest.raises(SessionFileError, match="format is not supported"):
        await SessionManager.open(session_file, persist=True)

    assert session_file.read_bytes() == original


@_async_test
async def test_session_manager_continue_recent_uses_latest_summary_or_creates_new(
    tmp_path,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    empty = await SessionManager.continue_recent(
        session_dir=tmp_path / "empty", cwd="/tmp/project"
    )
    assert empty.get_cwd() == "/tmp/project"
    assert empty.get_session_file() is not None

    older = await SessionManager.new(session_dir=tmp_path, cwd="/tmp/old", persist=True)
    await older.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="older")],
            timestamp=1000.0,
        )
    )
    newer = await SessionManager.new(session_dir=tmp_path, cwd="/tmp/new", persist=True)
    await newer.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="newer")],
            timestamp=2000.0,
        )
    )

    continued = await SessionManager.continue_recent(
        session_dir=tmp_path, cwd="/tmp/current"
    )

    assert continued.get_session_file() == newer.get_session_file()
    assert continued.get_cwd() == "/tmp/current"
    assert continued.get_header().metadata["cwd"] == "/tmp/new"


@_async_test
async def test_session_manager_in_memory_and_fork_from(tmp_path) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.session_manager import SessionManager

    memory = await SessionManager.in_memory(cwd="/tmp/memory")
    assert memory.get_cwd() == "/tmp/memory"
    assert memory.get_session_file() is None
    assert memory.is_persisted() is False

    source = await SessionManager.new(
        session_dir=tmp_path / "source", cwd="/tmp/source", persist=True
    )
    await source.append_message(
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="copy me")],
            timestamp=0.0,
        )
    )

    forked = await SessionManager.fork_from(
        source.get_session_file(),
        target_cwd="/tmp/target",
        session_dir=tmp_path / "target",
    )

    assert forked.get_cwd() == "/tmp/target"
    assert forked.get_session_file() is not None
    assert forked.get_session_file().parent == tmp_path / "target"
    assert forked.get_header().metadata["parentSession"] == str(
        source.get_session_file()
    )
    assert [entry.record_id for entry in forked.get_entries()] == [
        entry.record_id for entry in source.get_entries()
    ]
