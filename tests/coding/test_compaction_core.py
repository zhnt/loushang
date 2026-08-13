import asyncio

import pytest

from loushang.ai import ApiKeyAuth, CallOptions
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.coding.compaction import evaluate_coding_summary_fixture
from loushang.coding.compaction.adapter import (
    execute_coding_branch_summary,
    execute_coding_compaction,
)
from loushang.coding.compaction.profiles import (
    CODING_BRANCH_SUMMARY_PROFILE,
    CODING_COMPACTION_SUMMARY_PROFILE,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.context import SummaryValidationReport, validate_summary
from loushang.harness.context.budget import calculate_compaction_budget
from loushang.harness.transcript import (
    BranchSummaryOutput,
    CompactionPreparation,
    CompactionResult,
    calculate_context_tokens,
    estimate_context_tokens,
)
from loushang.harness.transcript import (
    plan_turn_aware_compaction as plan_compaction,
)
from loushang.harness.transcript import (
    prepare_turn_aware_compaction as prepare_compaction,
)


@pytest.mark.anyio
async def test_complete_text_aggregates_root_stream_with_options(monkeypatch) -> None:
    from loushang.ai import Context
    from loushang.harness.transcript import summarization as summary_module

    captured: dict[str, object] = {}

    message = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="summary text")],
        api="faux",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )

    class FakeEventStream:
        async def result(self):
            captured["result_called"] = True
            return message

    async def fake_stream(model, context, options=None):
        captured["model"] = model
        captured["context"] = context
        captured["options"] = options
        return FakeEventStream()

    monkeypatch.setattr(summary_module, "stream", fake_stream)
    options = CallOptions(auth=ApiKeyAuth("key"), headers={"x-test": "1"})
    context = Context(
        messages=[UserMessage(role="user", content="summarize", timestamp=0.0)]
    )
    model = Model(
        id="stream-model",
        name="Stream Model",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(stream=True),
    )

    result = await summary_module._complete_text(model, context, options)

    assert result == "summary text"
    assert captured == {
        "model": model,
        "context": context,
        "options": options,
        "result_called": True,
    }


@pytest.mark.anyio
async def test_complete_text_uses_complete_for_non_stream_model(monkeypatch) -> None:
    from loushang.ai import Context
    from loushang.harness.transcript import summarization as summary_module

    captured: dict[str, object] = {}
    message = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="non-stream summary")],
        api="faux",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )

    async def fake_complete(model, context, options=None):
        captured["model"] = model
        captured["context"] = context
        captured["options"] = options
        return message

    async def unexpected_stream(*args, **kwargs):
        del args, kwargs
        raise AssertionError("stream() must not be used without stream capability")

    monkeypatch.setattr(summary_module, "complete", fake_complete)
    monkeypatch.setattr(summary_module, "stream", unexpected_stream)
    options = CallOptions(auth=ApiKeyAuth("key"), headers={"x-test": "1"})
    context = Context(
        messages=[UserMessage(role="user", content="summarize", timestamp=0.0)]
    )
    model = Model(
        id="complete-model",
        name="Complete Model",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(stream=False),
    )

    result = await summary_module._complete_text(model, context, options)

    assert result == "non-stream summary"
    assert captured == {"model": model, "context": context, "options": options}


def test_compaction_package_exports_product_symbols() -> None:
    assert CompactionResult is not None
    assert callable(evaluate_coding_summary_fixture)


def test_calculate_context_tokens_prefers_total_tokens() -> None:
    usage = Usage(
        input=1,
        output=2,
        cache_read=3,
        cache_write=4,
        total_tokens=100,
        cost={},
    )
    assert calculate_context_tokens(usage) == 100


def test_estimate_context_tokens_adds_trailing_message_estimate() -> None:
    messages = [
        AssistantMessage(
            endpoint="test-endpoint",
            role="assistant",
            content=[TextPart(type="text", text="done")],
            api="responses",
            provider="faux",
            model="alpha",
            response_id="r1",
            usage=Usage(
                input=40,
                output=10,
                cache_read=5,
                cache_write=0,
                total_tokens=55,
                cost={},
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=1.0,
        ),
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="follow up question")],
            timestamp=2.0,
        ),
    ]

    estimate = estimate_context_tokens(messages)

    assert estimate.usage_tokens == 55
    assert estimate.trailing_tokens > 0
    assert estimate.tokens == estimate.usage_tokens + estimate.trailing_tokens


def test_compaction_budget_keeps_reserve_threshold_behavior() -> None:
    budget = calculate_compaction_budget(
        context_window=100_000,
        compact_percent=100,
        reserve_tokens=8_192,
    )
    assert 95_000 > budget.threshold_tokens
    assert 90_000 <= budget.threshold_tokens


def test_prepare_compaction_returns_first_kept_entry_and_messages_to_summarize(
    tmp_path,
) -> None:
    session = asyncio.run(
        SessionManager.new(tmp_path, cwd=str(tmp_path), persist=False)
    )
    asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older context to summarize")],
                timestamp=1.0,
            )
        )
    )
    asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="older assistant context")],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r2",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            )
        )
    )
    latest_entry_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="latest context to keep")],
                timestamp=3.0,
            )
        )
    )

    preparation = prepare_compaction(session.get_branch(), keep_recent_tokens=1)

    assert preparation.first_kept_entry_id == latest_entry_id
    assert preparation.tokens_before >= 30
    assert len(preparation.messages_to_summarize) == 2
    assert preparation.messages_to_summarize[0].role == "user"
    assert preparation.messages_to_summarize[1].role == "assistant"
    assert preparation.turn_prefix_messages == []
    assert preparation.is_split_turn is False


def test_plan_compaction_records_summarized_and_kept_entry_ids(tmp_path) -> None:
    session = asyncio.run(
        SessionManager.new(tmp_path, cwd=str(tmp_path), persist=False)
    )
    older_user_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older user " * 20)],
                timestamp=1.0,
            )
        )
    )
    older_assistant_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="older assistant " * 20)],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r1",
                usage=Usage(
                    input=40,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=50,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            )
        )
    )
    recent_user_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="new")], timestamp=3.0
            )
        )
    )
    recent_assistant_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="ok")],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r2",
                usage=Usage(
                    input=60,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=70,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=4.0,
            )
        )
    )

    plan = plan_compaction(session.get_branch(), keep_recent_tokens=2)

    assert plan.previous_compaction_id is None
    assert plan.previous_first_kept_entry_id is None
    assert plan.first_kept_entry_id == recent_user_id
    assert plan.summarized_entry_ids == (older_user_id, older_assistant_id)
    assert plan.turn_prefix_entry_ids == ()
    assert plan.kept_entry_ids == (recent_user_id, recent_assistant_id)
    assert plan.is_split_turn is False
    assert plan.keep_recent_tokens == 2
    assert plan.tokens_before >= 70


def test_plan_compaction_records_previous_boundary_and_split_turn_ids(tmp_path) -> None:
    session = asyncio.run(
        SessionManager.new(tmp_path, cwd=str(tmp_path), persist=False)
    )
    asyncio.run(
        session.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="old")], timestamp=1.0
            )
        )
    )
    previous_kept_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="kept from previous compaction")],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r1",
                usage=Usage(
                    input=10,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=20,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            )
        )
    )
    previous_compaction_id = asyncio.run(
        session.append_compaction(
            summary="previous summary",
            first_kept_entry_id=previous_kept_id,
            tokens_before=100,
        )
    )
    turn_prefix_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="new request")],
                timestamp=3.0,
            )
        )
    )
    latest_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="latest reply " * 20)],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r2",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=4.0,
            )
        )
    )

    plan = plan_compaction(session.get_branch(), keep_recent_tokens=5)

    assert plan.previous_compaction_id == previous_compaction_id
    assert plan.previous_first_kept_entry_id == previous_kept_id
    assert plan.first_kept_entry_id == latest_id
    assert plan.summarized_entry_ids == (previous_kept_id,)
    assert plan.turn_prefix_entry_ids == (turn_prefix_id,)
    assert plan.kept_entry_ids == (latest_id,)
    assert plan.is_split_turn is True


def test_plan_compaction_never_uses_tool_result_as_cut_point(tmp_path) -> None:
    session = asyncio.run(
        SessionManager.new(tmp_path, cwd=str(tmp_path), persist=False)
    )
    old_user_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="old request")],
                timestamp=1.0,
            )
        )
    )
    old_assistant_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="old answer")],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r1",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            )
        )
    )
    current_user_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="current request")],
                timestamp=3.0,
            )
        )
    )
    current_assistant_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[
                    ToolCall(
                        type="toolCall",
                        id="call-1",
                        name="read",
                        arguments={"path": "README.md"},
                    )
                ],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r2",
                usage=Usage(
                    input=30,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=40,
                    cost={},
                ),
                stop_reason="toolUse",
                error_message=None,
                timestamp=4.0,
            )
        )
    )
    tool_result_id = asyncio.run(
        session.append_message(
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call-1",
                tool_name="read",
                content=[TextPart(type="text", text="README contents " * 200)],
                is_error=False,
                timestamp=5.0,
            )
        )
    )

    plan = plan_compaction(session.get_branch(), keep_recent_tokens=5)

    assert plan.first_kept_entry_id == current_assistant_id
    assert tool_result_id in plan.kept_entry_ids
    assert plan.summarized_entry_ids == (old_user_id, old_assistant_id)
    assert plan.turn_prefix_entry_ids == (current_user_id,)
    assert plan.is_split_turn is True


def test_prepare_compaction_starts_after_previous_compaction_boundary(tmp_path) -> None:
    session = asyncio.run(
        SessionManager.new(tmp_path, cwd=str(tmp_path), persist=False)
    )
    asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="old request")],
                timestamp=1.0,
            )
        )
    )
    kept_from_previous_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="kept from previous compaction")],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r1",
                usage=Usage(
                    input=10,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=20,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            )
        )
    )
    asyncio.run(
        session.append_compaction(
            summary="previous summary",
            first_kept_entry_id=kept_from_previous_id,
            tokens_before=100,
        )
    )
    asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="new request")],
                timestamp=3.0,
            )
        )
    )
    latest_entry_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="latest reply")],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r2",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=4.0,
            )
        )
    )

    preparation = prepare_compaction(session.get_branch(), keep_recent_tokens=2)

    assert preparation.previous_summary == "previous summary"
    assert preparation.first_kept_entry_id == latest_entry_id
    summarized_text = [
        block.text
        for message in preparation.messages_to_summarize
        for block in getattr(message, "content", [])
        if getattr(block, "type", None) == "text"
    ]
    assert summarized_text == ["kept from previous compaction"]
    assert preparation.turn_prefix_messages == [
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="new request")],
            timestamp=3.0,
        )
    ]
    assert preparation.is_split_turn is True


def test_prepare_compaction_detects_split_turn_cut_point(tmp_path) -> None:
    session = asyncio.run(
        SessionManager.new(tmp_path, cwd=str(tmp_path), persist=False)
    )
    asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="old request")],
                timestamp=1.0,
            )
        )
    )
    asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="old reply")],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r1",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            )
        )
    )
    current_request_id = asyncio.run(
        session.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="current request")],
                timestamp=3.0,
            )
        )
    )
    latest_entry_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="latest reply " * 20)],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r2",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=4.0,
            )
        )
    )

    preparation = prepare_compaction(session.get_branch(), keep_recent_tokens=5)

    assert preparation.first_kept_entry_id == latest_entry_id
    assert preparation.is_split_turn is True
    assert preparation.messages_to_summarize[0].role == "user"
    assert preparation.messages_to_summarize[1].role == "assistant"
    assert preparation.turn_prefix_messages == [
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="current request")],
            timestamp=3.0,
        )
    ]
    assert current_request_id != preparation.first_kept_entry_id


def test_plan_compaction_keeps_metadata_attached_to_cut_group(tmp_path) -> None:
    session = asyncio.run(
        SessionManager.new(tmp_path, cwd=str(tmp_path), persist=False)
    )
    old_user_id = asyncio.run(
        session.append_message(
            UserMessage(role="user", content="old request", timestamp=1.0)
        )
    )
    old_assistant_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="old reply")],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r1",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            )
        )
    )
    model_change_id = asyncio.run(
        session.append_model_change("faux", "beta", endpoint_id="responses")
    )
    recent_user_id = asyncio.run(
        session.append_message(
            UserMessage(role="user", content="new request", timestamp=3.0)
        )
    )
    recent_assistant_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="new reply")],
                api="responses",
                provider="faux",
                model="beta",
                response_id="r2",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=4.0,
            )
        )
    )

    plan = plan_compaction(session.get_branch(), keep_recent_tokens=5)

    assert plan.first_kept_entry_id == model_change_id
    assert plan.summarized_entry_ids == (old_user_id, old_assistant_id)
    assert plan.kept_entry_ids == (recent_user_id, recent_assistant_id)


def test_plan_compaction_partitions_do_not_overlap_when_all_context_is_kept(
    tmp_path,
) -> None:
    session = asyncio.run(
        SessionManager.new(tmp_path, cwd=str(tmp_path), persist=False)
    )
    user_id = asyncio.run(
        session.append_message(
            UserMessage(role="user", content="short request", timestamp=1.0)
        )
    )
    assistant_id = asyncio.run(
        session.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="short answer")],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r1",
                usage=Usage(
                    input=2,
                    output=1,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=3,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            )
        )
    )

    preparation = prepare_compaction(
        session.get_branch(),
        keep_recent_tokens=10_000,
    )

    assert preparation.messages_to_summarize == []
    assert preparation.turn_prefix_messages == []
    assert preparation.plan is not None
    assert preparation.plan.summarized_entry_ids == ()
    assert preparation.plan.kept_entry_ids == (user_id, assistant_id)


def test_harness_exports_turn_aware_compaction_surface() -> None:
    from loushang.harness.transcript import (
        CompactionResult as HarnessCompactionResult,
    )
    from loushang.harness.transcript import (
        prepare_turn_aware_compaction,
    )

    assert HarnessCompactionResult is CompactionResult
    assert callable(prepare_turn_aware_compaction)


def test_validate_summary_accepts_structured_compaction_summary_with_resource_tags() -> (
    None
):
    summary = """## Goal
Continue aligning loushang coding with pi coding.

## Constraints & Preferences
- Exclude UI and naming style from gap scoring.

## Progress
### Done
- [x] Added runtime diagnostics.

### In Progress
- [ ] Build compaction harness.

### Blocked
- (none)

## Key Decisions
- **Python boundary**: Keep snake_case for Python objects.

## Next Steps
1. Run focused regression tests.

## Critical Context
- tests/coding/test_compaction_core.py owns this harness.

<read-files>
README.md
</read-files>

<modified-files>
src/loushang/harness/context/summary_evaluation.py
</modified-files>"""

    report = validate_summary(summary, CODING_COMPACTION_SUMMARY_PROFILE)

    assert report == SummaryValidationReport(profile_id="coding.compaction")


def test_validate_summary_reports_missing_and_placeholder_sections() -> None:
    summary = """## Goal
[What is the user trying to accomplish?]

## Progress
### Done
- [x] Something happened.
"""

    report = validate_summary(summary, CODING_COMPACTION_SUMMARY_PROFILE)

    assert report.ok is False
    assert report.missing_sections == (
        "Constraints & Preferences",
        "Key Decisions",
        "Next Steps",
        "Critical Context",
    )
    assert report.placeholder_sections == ("Goal",)


def test_validate_summary_accepts_branch_summary_without_critical_context() -> None:
    summary = """The user explored a different conversation branch before returning here.
Summary of that exploration:

## Goal
Try a branch-specific refactor.

## Constraints & Preferences
- Keep public API stable.

## Progress
### Done
- [x] Inspected alternate branch.

### In Progress
- (none)

### Blocked
- (none)

## Key Decisions
- **Do not merge branch**: It was exploratory.

## Next Steps
1. Return to the main branch.
"""

    report = validate_summary(summary, CODING_BRANCH_SUMMARY_PROFILE)

    assert report.ok is True
    assert report.missing_sections == ()
    assert report.placeholder_sections == ()


def test_top_level_package_exports_branch_summary_surface() -> None:
    import loushang.coding as coding
    from loushang.harness.transcript import (
        BranchSummaryOutput as HarnessBranchSummaryOutput,
    )
    from loushang.harness.transcript import (
        execute_branch_summary,
    )

    assert not hasattr(coding, "BranchSummaryDetails")
    assert HarnessBranchSummaryOutput is BranchSummaryOutput
    assert callable(execute_branch_summary)


def test_tree_navigation_result_is_exported() -> None:
    from loushang.coding.session import TreeNavigationResult

    assert TreeNavigationResult is not None


@pytest.mark.anyio
async def test_generate_branch_summary_returns_summary_text() -> None:
    captured: dict[str, object] = {}

    async def _fake_complete(model, context, options=None):
        del model, context
        captured["options"] = options
        return "branch summary"

    result = await execute_coding_branch_summary(
        [UserMessage(role="user", content="old summary", timestamp=0.0)],
        model=object(),
        signal=None,
        reserve_tokens=1024,
        completer=_fake_complete,
    )

    assert result == BranchSummaryOutput(
        summary="The user explored a different conversation branch before returning here.\n"
        "Summary of that exploration:\n\nbranch summary",
        details=None,
    )
    options = captured["options"]
    assert isinstance(options, CallOptions)
    assert options.auth is None


@pytest.mark.anyio
async def test_generate_branch_summary_uses_serialized_prompt_and_file_details() -> (
    None
):
    captured: dict[str, object] = {}

    async def _fake_complete(model, context, options=None):
        captured["model"] = model
        captured["context"] = context
        captured["options"] = options
        return "branch summary"

    signal = object()
    result = await execute_coding_branch_summary(
        [
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="Explore branch")],
                timestamp=1.0,
            ),
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[
                    ToolCall(
                        type="toolCall",
                        id="call-1",
                        name="read",
                        arguments={"path": "README.md"},
                    ),
                    ToolCall(
                        type="toolCall",
                        id="call-2",
                        name="edit",
                        arguments={"path": "src/app.py"},
                    ),
                ],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r2",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            ),
        ],
        model="model",
        api_key="branch-key",
        headers={"x-branch": "1"},
        signal=signal,
        custom_instructions="Keep exact paths.",
        reserve_tokens=1024,
        completer=_fake_complete,
    )

    context = captured["context"]
    prompt = context.messages[0].content[0].text
    assert "<conversation>" in prompt
    assert "[User]: Explore branch" in prompt
    assert (
        "[Assistant tool calls]: read(path='README.md'); edit(path='src/app.py')"
        in prompt
    )
    assert "Additional focus: Keep exact paths." in prompt
    assert "Do NOT continue the conversation" in context.system_prompt
    options = captured["options"]
    assert isinstance(options, CallOptions)
    assert options.auth == ApiKeyAuth("branch-key")
    assert options.headers == {"x-branch": "1"}
    assert options.cancellation is signal
    assert result.summary.endswith(
        "<read-files>\nREADME.md\n</read-files>\n\n<modified-files>\nsrc/app.py\n</modified-files>"
    )
    assert result.details == {
        "readFiles": ["README.md"],
        "modifiedFiles": ["src/app.py"],
    }


@pytest.mark.anyio
async def test_compact_returns_summary_result() -> None:
    async def fake_completer(model, context, options=None):
        del model, context
        assert isinstance(options, CallOptions)
        assert options.auth == ApiKeyAuth("test-key")
        return "summary text"

    preparation = CompactionPreparation(
        first_kept_entry_id="e2",
        messages_to_summarize=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older")],
                timestamp=1.0,
            )
        ],
        turn_prefix_messages=[],
        is_split_turn=False,
        tokens_before=42,
    )

    result = await execute_coding_compaction(
        preparation=preparation,
        model=object(),
        api_key="test-key",
        completer=fake_completer,
    )

    assert result == CompactionResult(
        summary="summary text",
        first_kept_entry_id="e2",
        tokens_before=42,
        details=None,
    )


@pytest.mark.anyio
async def test_compact_passes_custom_instructions_to_summarizer() -> None:
    captured: dict[str, object] = {}

    async def fake_completer(model, context, options=None):
        del model, options
        captured["prompt"] = context.messages[0].content[0].text
        return "summary text"

    preparation = CompactionPreparation(
        first_kept_entry_id="e2",
        messages_to_summarize=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older")],
                timestamp=1.0,
            )
        ],
        turn_prefix_messages=[],
        is_split_turn=False,
        tokens_before=42,
    )

    result = await execute_coding_compaction(
        preparation=preparation,
        model=object(),
        api_key="test-key",
        custom_instructions="Keep API details.",
        completer=fake_completer,
    )

    assert result.summary == "summary text"
    assert "Additional focus: Keep API details." in captured["prompt"]


@pytest.mark.anyio
async def test_compact_serializes_conversation_and_previous_summary_for_llm() -> None:
    captured: dict[str, object] = {}

    async def fake_complete(model, context, options=None):
        captured["model"] = model
        captured["context"] = context
        captured["options"] = options
        return "summary text"

    preparation = CompactionPreparation(
        first_kept_entry_id="e2",
        messages_to_summarize=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="Please inspect README.md")],
                timestamp=1.0,
            ),
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call-1",
                tool_name="read",
                content=[TextPart(type="text", text="README contents")],
                is_error=False,
                timestamp=2.0,
            ),
        ],
        turn_prefix_messages=[],
        is_split_turn=False,
        tokens_before=42,
        previous_summary="Earlier summary",
    )

    signal = object()
    result = await execute_coding_compaction(
        preparation=preparation,
        model="model",
        headers={"x-test": "1"},
        signal=signal,
        custom_instructions="Keep exact file paths.",
        completer=fake_complete,
    )

    context = captured["context"]
    assert result.summary == "summary text"
    assert len(context.messages) == 1
    prompt = context.messages[0].content[0].text
    assert "<conversation>" in prompt
    assert "[User]: Please inspect README.md" in prompt
    assert "[Tool result]: README contents" in prompt
    assert "<previous-summary>\nEarlier summary\n</previous-summary>" in prompt
    assert "Additional focus: Keep exact file paths." in prompt
    assert "Do NOT continue the conversation" in context.system_prompt
    options = captured["options"]
    assert isinstance(options, CallOptions)
    assert options.auth is None
    assert options.headers == {"x-test": "1"}
    assert options.cancellation is signal


@pytest.mark.anyio
async def test_compact_split_turn_forwards_call_options_to_both_summaries() -> None:
    captured: list[tuple[object, object, object | None]] = []

    async def fake_complete(model, context, options=None):
        captured.append((model, context, options))
        return f"summary-{len(captured)}"

    preparation = CompactionPreparation(
        first_kept_entry_id="e2",
        messages_to_summarize=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="older")],
                timestamp=1.0,
            )
        ],
        turn_prefix_messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="current turn")],
                timestamp=2.0,
            )
        ],
        is_split_turn=True,
        tokens_before=42,
    )

    signal = object()
    result = await execute_coding_compaction(
        preparation=preparation,
        model="model",
        api_key="test-key",
        headers={"x-test": "1"},
        signal=signal,
        completer=fake_complete,
    )

    assert (
        result.summary
        == "summary-1\n\n---\n\n**Turn Context (split turn):**\n\nsummary-2"
    )
    assert len(captured) == 2
    assert [model for model, _, _ in captured] == ["model", "model"]
    prompts = [context.messages[0].content[0].text for _, context, _ in captured]
    assert "[User]: older" in prompts[0]
    assert "[User]: current turn" in prompts[1]
    for _, _, options in captured:
        assert isinstance(options, CallOptions)
        assert options.auth == ApiKeyAuth("test-key")
        assert options.headers == {"x-test": "1"}
        assert options.cancellation is signal


@pytest.mark.anyio
async def test_compact_appends_file_operation_summary_details() -> None:
    async def fake_completer(model, context, options=None):
        del model, context, options
        return "summary text"

    preparation = CompactionPreparation(
        first_kept_entry_id="e2",
        messages_to_summarize=[
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[
                    ToolCall(
                        type="toolCall",
                        id="call-1",
                        name="read",
                        arguments={"path": "README.md"},
                    ),
                    ToolCall(
                        type="toolCall",
                        id="call-2",
                        name="write",
                        arguments={"path": "src/app.py"},
                    ),
                ],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r2",
                usage=Usage(
                    input=20,
                    output=10,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            )
        ],
        turn_prefix_messages=[],
        is_split_turn=False,
        tokens_before=42,
    )

    result = await execute_coding_compaction(
        preparation=preparation,
        model=object(),
        api_key="test-key",
        completer=fake_completer,
    )

    assert (
        result.summary
        == "summary text\n\n<read-files>\nREADME.md\n</read-files>\n\n<modified-files>\nsrc/app.py\n</modified-files>"
    )
    assert result.details == {
        "readFiles": ["README.md"],
        "modifiedFiles": ["src/app.py"],
    }
