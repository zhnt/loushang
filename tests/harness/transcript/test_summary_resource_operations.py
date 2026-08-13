from __future__ import annotations

from loushang.ai.types import AssistantMessage, ToolCall, Usage
from loushang.harness.transcript import (
    SummaryResourceOperationDecorationProfile,
    collect_summary_resource_operations,
    decorate_summary_resource_operations,
)


def _usage() -> Usage:
    return Usage(
        input=1,
        output=1,
        cache_read=0,
        cache_write=0,
        total_tokens=2,
        cost={},
    )


def _assistant(*calls: ToolCall) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=list(calls),
        api="responses",
        provider="test",
        model="test",
        response_id="response-1",
        usage=_usage(),
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )


def _design_profile() -> SummaryResourceOperationDecorationProfile:
    return SummaryResourceOperationDecorationProfile(
        tool_operations={
            "inspect_slide": "read",
            "update_slide": "modified",
        },
        detail_keys={
            "read": "inspectedSlides",
            "modified": "modifiedSlides",
        },
        tags={
            "read": "inspected-slides",
            "modified": "modified-slides",
        },
        excluded_by={"read": ("modified",)},
        resource_argument="slide_id",
    )


def test_collects_profiled_resource_operations_without_coding_types() -> None:
    messages = (
        _assistant(
            ToolCall(
                type="toolCall",
                id="inspect-1",
                name="inspect_slide",
                arguments={"slide_id": "slide-2"},
            ),
            ToolCall(
                type="toolCall",
                id="inspect-2",
                name="inspect_slide",
                arguments={"slide_id": "slide-1"},
            ),
            ToolCall(
                type="toolCall",
                id="update-1",
                name="update_slide",
                arguments={"slide_id": "slide-2"},
            ),
        ),
    )

    operations = collect_summary_resource_operations(
        messages,
        profile=_design_profile(),
    )

    assert operations.to_dict() == {
        "read": ["slide-1"],
        "modified": ["slide-2"],
    }


def test_decorates_summary_with_profiled_tags_and_detail_keys() -> None:
    messages = (
        _assistant(
            ToolCall(
                type="toolCall",
                id="update-1",
                name="update_slide",
                arguments={"slide_id": "slide-3"},
            ),
        ),
    )

    decoration = decorate_summary_resource_operations(
        messages,
        {"revision": 4},
        profile=_design_profile(),
    )

    assert decoration.suffix == ("\n\n<modified-slides>\nslide-3\n</modified-slides>")
    assert decoration.details == {
        "revision": 4,
        "inspectedSlides": [],
        "modifiedSlides": ["slide-3"],
    }
