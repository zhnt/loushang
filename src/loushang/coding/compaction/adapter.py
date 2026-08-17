"""Coding bindings for the standard Agent transcript summary runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial

from loushang.agent import PrepareModelCallFn
from loushang.ai import PreparedRequestLimits
from loushang.coding.compaction.profiles import (
    CODING_BRANCH_SUMMARY_PROFILE,
    CODING_COMPACTION_SUMMARY_PROFILE,
    CODING_TURN_PREFIX_SUMMARY_PROFILE,
)
from loushang.harness.transcript import (
    BranchSummaryOutput,
    CompactionPreparation,
    CompactionResult,
    SummaryResourceOperationDecorationProfile,
    decorate_summary_resource_operations,
)
from loushang.harness.transcript.summarization import (
    SummaryCompleter,
    default_summary_completer,
    execute_branch_summary,
    execute_transcript_compaction,
)

CODING_SUMMARY_RESOURCE_OPERATION_PROFILE = (
    SummaryResourceOperationDecorationProfile(
        tool_operations={
            "read": "read",
            "write": "modified",
            "edit": "modified",
        },
        detail_keys={
            "read": "readFiles",
            "modified": "modifiedFiles",
        },
        tags={
            "read": "read-files",
            "modified": "modified-files",
        },
        excluded_by={"read": ("modified",)},
    )
)

_decorate_coding_summary = partial(
    decorate_summary_resource_operations,
    profile=CODING_SUMMARY_RESOURCE_OPERATION_PROFILE,
)


async def execute_coding_compaction(
    *,
    preparation: CompactionPreparation,
    model: object,
    api_key: str | None = None,
    headers: Mapping[str, str] | None = None,
    signal: object | None = None,
    custom_instructions: str | None = None,
    completer: SummaryCompleter = default_summary_completer,
    prepare_model_call: PrepareModelCallFn | None = None,
    request_limits: PreparedRequestLimits | None = None,
) -> CompactionResult:
    """Bind Coding prompts and file-operation annotations to Harness compaction."""

    return await execute_transcript_compaction(
        preparation=preparation,
        model=model,
        compaction_profile=CODING_COMPACTION_SUMMARY_PROFILE,
        turn_prefix_profile=CODING_TURN_PREFIX_SUMMARY_PROFILE,
        api_key=api_key,
        headers=headers,
        signal=signal,
        custom_instructions=custom_instructions,
        completer=completer,
        decorate=_decorate_coding_summary,
        prepare_model_call=prepare_model_call,
        request_limits=request_limits,
    )


async def execute_coding_branch_summary(
    entries_or_messages: Sequence[object],
    *,
    model: object,
    api_key: str | None = None,
    headers: Mapping[str, str] | None = None,
    signal: object | None = None,
    custom_instructions: str | None = None,
    replace_instructions: bool = False,
    reserve_tokens: int = 16_384,
    completer: SummaryCompleter = default_summary_completer,
    prepare_model_call: PrepareModelCallFn | None = None,
) -> BranchSummaryOutput:
    """Bind Coding prompts and file-operation annotations to branch summaries."""

    return await execute_branch_summary(
        entries_or_messages,
        model=model,
        profile=CODING_BRANCH_SUMMARY_PROFILE,
        api_key=api_key,
        headers=headers,
        signal=signal,
        custom_instructions=custom_instructions,
        replace_instructions=replace_instructions,
        reserve_tokens=reserve_tokens,
        completer=completer,
        decorate=_decorate_coding_summary,
        prepare_model_call=prepare_model_call,
    )


__all__ = [
    "CODING_SUMMARY_RESOURCE_OPERATION_PROFILE",
    "execute_coding_branch_summary",
    "execute_coding_compaction",
]
