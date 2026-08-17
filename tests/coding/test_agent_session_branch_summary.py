from __future__ import annotations

import asyncio

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost={},
    )


def _model(model_id: str = "faux-model") -> Model:
    return Model(
        id=model_id,
        name=model_id,
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _assistant_text_message(
    text: str,
    *,
    model_id: str = "faux-model",
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model=model_id,
        response_id=None,
        usage=_usage(),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def test_navigate_tree_is_noop_when_target_is_current_leaf(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession, TreeNavigationResult
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    leaf_id = asyncio.run(manager.append_message(_assistant_text_message("reply")))
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
    )

    result = asyncio.run(session.navigate_tree(leaf_id))

    assert result == TreeNavigationResult(cancelled=False)
    assert session.session_manager.get_leaf_id() == leaf_id


def test_navigate_tree_to_message_switches_leaf_and_rebuilds_context(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    assistant1_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 1"))
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="follow up")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(manager.append_message(_assistant_text_message("reply 2")))
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
    )

    asyncio.run(session.navigate_tree(assistant1_id))

    assert session.session_manager.get_leaf_id() == assistant1_id
    assert [
        getattr(message, "role", None) for message in session.agent.state.messages
    ] == ["user", "assistant"]
    assert session.agent.state.messages[1].content[0].text == "reply 1"


def test_navigate_tree_restores_target_branch_model_and_thinking(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession, ModelSelection
    from loushang.coding.session_manager import SessionManager

    default_model = _model("default-model")
    first_model = _model("first-model")
    second_model = _model("second-model")
    built_models: list[str] = []

    class ModelRegistry:
        def list_models(self):
            return [
                ModelSelection(
                    endpoint_id="anthropic-messages",
                    provider="faux",
                    model_id=first_model.id,
                ),
                ModelSelection(
                    endpoint_id="anthropic-messages",
                    provider="faux",
                    model_id=second_model.id,
                ),
            ]

        def build_model(self, selection):
            built_models.append(selection.model_id)
            return {
                first_model.id: first_model,
                second_model.id: second_model,
            }[selection.model_id]

    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=False,
        )
    )
    root_id = asyncio.run(
        manager.append_message(UserMessage(role="user", content="root", timestamp=0.0))
    )
    asyncio.run(manager.append_thinking_level_change("low"))
    asyncio.run(
        manager.append_model_change(
            "faux", first_model.id, endpoint_id="anthropic-messages"
        )
    )
    first_branch_leaf = asyncio.run(
        manager.append_message(
            _assistant_text_message("first", model_id=first_model.id)
        )
    )
    manager.branch(root_id)
    asyncio.run(manager.append_thinking_level_change("high"))
    asyncio.run(
        manager.append_model_change(
            "faux", second_model.id, endpoint_id="anthropic-messages"
        )
    )
    asyncio.run(
        manager.append_message(
            _assistant_text_message("second", model_id=second_model.id)
        )
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": default_model,
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        model_registry=ModelRegistry(),  # type: ignore[arg-type]
    )
    assert built_models == [second_model.id]
    assert session.agent.model.id == second_model.id
    assert session.agent.thinking_level == "high"

    asyncio.run(session.navigate_tree(first_branch_leaf))

    assert session.agent.model.id == first_model.id
    assert session.agent.thinking_level == "low"


def test_navigate_tree_to_user_message_returns_editor_text(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    assistant1_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 1"))
    )
    user2_id = asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="draft follow up")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(manager.append_message(_assistant_text_message("reply 2")))
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
    )

    result = asyncio.run(session.navigate_tree(user2_id))

    assert result.cancelled is False
    assert result.editor_text == "draft follow up"
    assert session.session_manager.get_leaf_id() == assistant1_id
    assert [
        getattr(message, "role", None) for message in session.agent.state.messages
    ] == ["user", "assistant"]


def test_navigate_tree_raises_for_unknown_target(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
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
    )

    with pytest.raises(ValueError, match="Entry missing not found"):
        asyncio.run(session.navigate_tree("missing"))


def test_navigate_tree_respects_extension_before_tree_cancellation(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionActionDecision,
    )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    assistant1_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 1"))
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="follow up")],
                timestamp=0.0,
            )
        )
    )
    old_leaf_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 2"))
    )
    events: list[object] = []

    def _before_tree(event, ctx):
        del ctx
        assert event.target_id == assistant1_id
        assert event.old_leaf_id == old_leaf_id
        assert event.summarize is True
        return SessionActionDecision(cancel=True)

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="tree-guard",
                    source_path=tmp_path / "tree_guard.py",
                    hooks={"session_before_tree": [_before_tree]},
                )
            ]
        ),
    )
    session.subscribe(events.append)

    result = asyncio.run(session.navigate_tree(assistant1_id, summarize=True))

    assert result.cancelled is True
    assert result.aborted is False
    assert session.session_manager.get_leaf_id() == old_leaf_id
    assert session.is_compacting is False
    assert session.get_compaction_status().is_compacting is False
    assert events == []


def test_navigate_tree_with_summary_appends_branch_summary_and_emits_events(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import BranchSummaryOutput

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    assistant1_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 1"))
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="follow up")],
                timestamp=0.0,
            )
        )
    )
    old_leaf_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 2"))
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
    )

    events: list[object] = []

    async def _fake_generate(entries_or_messages, **kwargs):
        assert len(entries_or_messages) == 2
        assert "api_key" not in kwargs
        return BranchSummaryOutput(
            summary="branch return summary",
            details={"readFiles": ["README.md"], "modifiedFiles": ["src/app.py"]},
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session.execute_coding_branch_summary",
        _fake_generate,
    )
    session.subscribe(events.append)

    result = asyncio.run(session.navigate_tree(assistant1_id, summarize=True))

    assert result.cancelled is False
    assert result.summary_entry_id is not None
    assert session.session_manager.get_leaf_id() == result.summary_entry_id
    summary_entry = session.session_manager.get_entry(result.summary_entry_id)
    assert summary_entry is not None
    assert summary_entry.kind == "context.branch_summary"
    assert summary_entry.parent_id == assistant1_id
    assert summary_entry.payload.summary == "branch return summary"
    assert summary_entry.payload.details == {
        "readFiles": ["README.md"],
        "modifiedFiles": ["src/app.py"],
    }
    assert [
        getattr(message, "role", None) for message in session.agent.state.messages
    ] == [
        "user",
        "assistant",
        "user",
    ]
    assert events[0] == {
        "type": "branch_summary_start",
        "target_id": assistant1_id,
        "old_leaf_id": old_leaf_id,
        "summarize": True,
    }
    assert events[-1] == {
        "type": "branch_summary_end",
        "target_id": assistant1_id,
        "old_leaf_id": old_leaf_id,
        "new_leaf_id": result.summary_entry_id,
        "summary_entry_id": result.summary_entry_id,
        "cancelled": False,
        "aborted": False,
    }


def test_navigate_tree_uses_extension_before_tree_summary_override(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionBeforeTreeResult,
    )
    from loushang.harness.transcript import BranchSummaryOutput

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    assistant1_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 1"))
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="follow up")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(manager.append_message(_assistant_text_message("reply 2")))
    old_leaf_id = manager.get_leaf_id()
    assert old_leaf_id is not None

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="tree-summary-hook",
                    source_path=tmp_path / "tree_summary_hook.py",
                    hooks={
                        "session_before_tree": [
                            lambda event, ctx: SessionBeforeTreeResult(
                                summary=BranchSummaryOutput(
                                    summary="extension summary",
                                    details={"source": "tree"},
                                ),
                                custom_instructions="from-extension",
                                replace_instructions=True,
                                label="from-extension",
                            )
                        ],
                    },
                )
            ]
        ),
    )

    generate_called = False

    async def _fake_generate(entries_or_messages, **kwargs):
        nonlocal generate_called
        generate_called = True
        del entries_or_messages
        del kwargs
        raise AssertionError(
            "generate_branch_summary should not be called when extension provides summary"
        )

    monkeypatch.setattr(
        "loushang.coding.session.agent_session.execute_coding_branch_summary",
        _fake_generate,
    )

    result = asyncio.run(
        session.navigate_tree(
            assistant1_id, summarize=True, custom_instructions="original"
        )
    )

    assert result.cancelled is False
    assert result.aborted is False
    assert generate_called is False
    assert result.summary_entry_id is not None
    summary_entry_id = result.summary_entry_id
    assert session.session_manager.get_leaf_id() == manager.get_entries()[-1].record_id
    summary_entry = session.session_manager.get_entry(summary_entry_id)
    assert summary_entry is not None
    assert summary_entry.kind == "context.branch_summary"
    assert summary_entry.payload.summary == "extension summary"
    assert summary_entry.payload.from_hook is True
    assert session.session_manager.get_label(summary_entry_id) == "from-extension"
    assert [
        getattr(message, "role", None) for message in session.agent.state.messages
    ] == [
        "user",
        "assistant",
        "user",
    ]
    assert manager.get_entries()[-1].record_id != summary_entry_id


def test_abort_branch_summary_cancels_inflight_navigation(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.transcript import BranchSummaryOutput

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    assistant1_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 1"))
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="follow up")],
                timestamp=0.0,
            )
        )
    )
    old_leaf_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 2"))
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
    )

    events: list[object] = []
    started = asyncio.Event()

    async def _fake_generate(entries_or_messages, **kwargs):
        del entries_or_messages
        signal = kwargs["signal"]
        started.set()
        while not signal.aborted:
            await asyncio.sleep(0)
        return BranchSummaryOutput(aborted=True)

    monkeypatch.setattr(
        "loushang.coding.session.agent_session.execute_coding_branch_summary",
        _fake_generate,
    )
    session.subscribe(events.append)

    async def scenario():
        task = asyncio.create_task(session.navigate_tree(assistant1_id, summarize=True))
        await started.wait()
        session.abort_branch_summary()
        return await task

    result = asyncio.run(scenario())

    assert result.cancelled is True
    assert result.aborted is True
    assert result.summary_entry_id is None
    assert session.session_manager.get_leaf_id() == old_leaf_id
    assert events[-1] == {
        "type": "branch_summary_end",
        "target_id": assistant1_id,
        "old_leaf_id": old_leaf_id,
        "new_leaf_id": old_leaf_id,
        "summary_entry_id": None,
        "cancelled": True,
        "aborted": True,
    }


def test_navigate_tree_records_branch_summary_failure_in_diagnostics(
    tmp_path, monkeypatch
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.diagnostics import DiagnosticsService

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    assistant1_id = asyncio.run(
        manager.append_message(_assistant_text_message("reply 1"))
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="follow up")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(manager.append_message(_assistant_text_message("reply 2")))
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        diagnostics_service=DiagnosticsService(),
    )

    async def _failing_generate(entries_or_messages, **kwargs):
        del entries_or_messages, kwargs
        raise RuntimeError("branch summary boom")

    monkeypatch.setattr(
        "loushang.coding.session.agent_session.execute_coding_branch_summary",
        _failing_generate,
    )

    with pytest.raises(RuntimeError, match="branch summary boom"):
        asyncio.run(session.navigate_tree(assistant1_id, summarize=True))

    report = session.diagnostics_service.get_last_error_report()
    assert report is not None
    assert report.primary.code == "branch_summary_failed"
