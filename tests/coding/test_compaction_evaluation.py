from __future__ import annotations

import pytest

from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage, UserMessage
from loushang.coding.compaction.adapter import (
    execute_coding_branch_summary,
    execute_coding_compaction,
)
from loushang.coding.compaction.evaluation import evaluate_coding_summary_fixture
from loushang.coding.compaction.profiles import (
    CODING_BRANCH_SUMMARY_PROFILE,
    CODING_COMPACTION_SUMMARY_PROFILE,
)
from loushang.harness.context import (
    SummaryEvaluationCase,
    SummaryResourceOperations,
    evaluate_summary_case,
    evaluate_summary_cases,
    evaluate_summary_fixture,
    load_summary_evaluation_cases,
)
from loushang.harness.transcript import CompactionPreparation


def _usage() -> Usage:
    return Usage(
        input=20,
        output=10,
        cache_read=0,
        cache_write=0,
        total_tokens=30,
        cost={},
    )


def _structured_compaction_summary() -> str:
    return """## Goal
Harden the session index lifecycle and runtime diagnostics.

## Constraints & Preferences
- Keep the changes mode-neutral and non-UI.

## Progress
### Done
- [x] Added runtime diagnostics for rename/delete failures.

### In Progress
- [ ] Continue pi gap evaluation.

### Blocked
- (none)

## Key Decisions
- **Session index lifecycle**: Rebuild stale indexed summaries when cached files disappear.

## Next Steps
1. Run coding regression tests.

## Critical Context
- Runtime diagnostics are recorded without swallowing the original exception."""


def _structured_branch_summary() -> str:
    return """## Goal
Explore branch-specific compaction behavior.

## Constraints & Preferences
- Preserve public session semantics.

## Progress
### Done
- [x] Inspected abandoned branch edits.

### In Progress
- (none)

### Blocked
- (none)

## Key Decisions
- **Return to main path**: Treat the branch as exploratory.

## Next Steps
1. Continue from the main branch."""


def test_evaluate_summary_cases_summarizes_real_workload_batch() -> None:
    passing = SummaryEvaluationCase(
        name="passes",
        summary=_structured_compaction_summary(),
        required_phrases=("runtime diagnostics",),
    )
    failing = SummaryEvaluationCase(
        name="missing-next-step",
        summary=_structured_compaction_summary(),
        required_phrases=("ship the release",),
    )

    result = evaluate_summary_cases(
        [passing, failing],
        profile=CODING_COMPACTION_SUMMARY_PROFILE,
    )

    assert result.total_count == 2
    assert result.passed_count == 1
    assert result.failed_case_names == ("missing-next-step",)
    assert result.ok is False
    assert result.results[0].case_name == "passes"
    assert result.results[0].profile_id == "coding.compaction"
    assert result.results[0].ok is True
    assert result.to_dict()["failed_case_names"] == ["missing-next-step"]


def test_summary_evaluation_fixture_loader_runs_golden_cases() -> None:
    fixture = "tests/coding/fixtures/summary_evaluation_cases.json"

    cases = load_summary_evaluation_cases(fixture)
    result = evaluate_coding_summary_fixture(fixture)
    generic_result = evaluate_summary_fixture(
        fixture,
        profiles={"coding.compaction": CODING_COMPACTION_SUMMARY_PROFILE},
    )

    assert [case.name for case in cases] == [
        "headless-policy-pack",
        "missing-critical-context",
    ]
    assert result.total_count == 2
    assert result.passed_count == 1
    assert result.failed_case_names == ("missing-critical-context",)
    assert result.results[0].case_name == "headless-policy-pack"
    assert result.results[0].profile_id == "coding.compaction"
    assert generic_result == result


@pytest.mark.anyio
async def test_evaluate_summary_case_accepts_fixed_compaction_workload() -> None:
    async def fake_completer(*args: object) -> str:
        del args
        return _structured_compaction_summary()

    result = await execute_coding_compaction(
        preparation=CompactionPreparation(
            first_kept_entry_id="keep-1",
            messages_to_summarize=[
                UserMessage(
                    role="user",
                    content=[
                        TextPart(type="text", text="Harden session index lifecycle.")
                    ],
                    timestamp=1.0,
                ),
                AssistantMessage(
                    endpoint="test-endpoint",
                    role="assistant",
                    content=[
                        ToolCall(
                            type="toolCall",
                            id="read-1",
                            name="read",
                            arguments={
                                "path": "docs/architecture/coding/component-interfaces/runtime.md"
                            },
                        ),
                        ToolCall(
                            type="toolCall",
                            id="edit-1",
                            name="edit",
                            arguments={
                                "path": "src/loushang/coding/runtime/agent_session_runtime.py"
                            },
                        ),
                    ],
                    api="responses",
                    provider="faux",
                    model="alpha",
                    response_id="r1",
                    usage=_usage(),
                    stop_reason="stop",
                    error_message=None,
                    timestamp=2.0,
                ),
            ],
            turn_prefix_messages=[],
            is_split_turn=False,
            tokens_before=42,
        ),
        model=object(),
        api_key="",
        completer=fake_completer,
    )

    report = evaluate_summary_case(
        SummaryEvaluationCase(
            name="runtime-store-stress",
            summary=result.summary,
            profile_id="coding.compaction",
            required_phrases=("session index lifecycle", "runtime diagnostics"),
            expected_resource_operations=SummaryResourceOperations.from_mapping(
                {
                    "read": (
                        "docs/architecture/coding/component-interfaces/runtime.md",
                    ),
                    "modified": (
                        "src/loushang/coding/runtime/agent_session_runtime.py",
                    ),
                }
            ),
        ),
        profile=CODING_COMPACTION_SUMMARY_PROFILE,
    )

    assert report.ok is True
    assert report.resource_operations.to_dict() == {
        "read": ["docs/architecture/coding/component-interfaces/runtime.md"],
        "modified": ["src/loushang/coding/runtime/agent_session_runtime.py"],
    }


@pytest.mark.anyio
async def test_evaluate_summary_case_accepts_fixed_branch_workload() -> None:
    async def fake_completer(*args: object) -> str:
        del args
        return _structured_branch_summary()

    result = await execute_coding_branch_summary(
        [
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="Try branch behavior.")],
                timestamp=1.0,
            ),
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[
                    ToolCall(
                        type="toolCall",
                        id="read-1",
                        name="read",
                        arguments={
                            "path": "src/loushang/coding/compaction/compaction.py"
                        },
                    ),
                    ToolCall(
                        type="toolCall",
                        id="write-1",
                        name="write",
                        arguments={
                            "path": "docs/architecture/coding/component-interfaces/compaction.md"
                        },
                    ),
                ],
                api="responses",
                provider="faux",
                model="alpha",
                response_id="r1",
                usage=_usage(),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            ),
        ],
        model=object(),
        api_key="",
        reserve_tokens=1024,
        completer=fake_completer,
    )

    report = evaluate_summary_case(
        SummaryEvaluationCase(
            name="branch-compaction",
            summary=result.summary,
            profile_id="coding.branch",
            required_phrases=("branch-specific compaction",),
            expected_resource_operations=SummaryResourceOperations.from_mapping(
                {
                    "read": ("src/loushang/coding/compaction/compaction.py",),
                    "modified": (
                        "docs/architecture/coding/component-interfaces/compaction.md",
                    ),
                }
            ),
        ),
        profile=CODING_BRANCH_SUMMARY_PROFILE,
    )

    assert result.details == {
        "readFiles": ["src/loushang/coding/compaction/compaction.py"],
        "modifiedFiles": [
            "docs/architecture/coding/component-interfaces/compaction.md"
        ],
    }
    assert report.ok is True


def test_evaluate_summary_case_reports_missing_required_signals() -> None:
    report = evaluate_summary_case(
        SummaryEvaluationCase(
            name="weak-summary",
            summary="""## Goal
Do work.

## Progress
### Done
- [x] Something changed.
""",
            profile_id="coding.compaction",
            required_phrases=("runtime diagnostics",),
            expected_resource_operations=SummaryResourceOperations.from_mapping(
                {"read": ("README.md",), "modified": ("src/app.py",)}
            ),
        ),
        profile=CODING_COMPACTION_SUMMARY_PROFILE,
    )

    assert report.ok is False
    assert report.validation.missing_sections == (
        "Constraints & Preferences",
        "Key Decisions",
        "Next Steps",
        "Critical Context",
    )
    assert report.missing_phrases == ("runtime diagnostics",)
    assert report.missing_resource_operations.to_dict() == {
        "read": ["README.md"],
        "modified": ["src/app.py"],
    }
