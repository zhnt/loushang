"""Reusable summary execution for the optional Agent transcript profile.

Harness owns transcript-summary mechanics: message projection, prompt execution,
turn-prefix handling, and normalized compaction or branch outputs.  A Product
selects prompt profiles and may decorate a summary with domain facts such as
code-file activity; it does not reimplement the transcript algorithm.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import cast

from loushang.agent.types import AgentMessage
from loushang.ai import ApiKeyAuth, CallOptions, Context, Model, complete, stream
from loushang.ai.trace import emit_trace
from loushang.ai.types import AssistantMessage, TextPart, UserMessage
from loushang.foundation.json import JSONValue, require_json_value
from loushang.harness.context import (
    SummaryProfile,
    SummaryResourceOperations,
    build_summary_prompt,
)
from loushang.harness.conversation import ConversationRecord
from loushang.harness.transcript.interaction import BranchSummaryOutput
from loushang.harness.transcript.maintenance import (
    CompactionPreparation,
    CompactionResult,
)
from loushang.harness.transcript.profile import (
    context_item_to_model_message,
    record_to_context_item,
)
from loushang.harness.transcript.types import AgentTranscriptRecord

TOOL_RESULT_MAX_CHARS = 2_000
DEFAULT_BRANCH_SUMMARY_PREAMBLE = """The user explored a different conversation branch before returning here.
Summary of that exploration:

"""

SummaryCompleter = Callable[[object, Context, CallOptions | None], Awaitable[str]]


@dataclass(frozen=True)
class SummaryDecoration:
    """A Product-provided, JSON-safe annotation of one generated summary."""

    suffix: str = ""
    details: JSONValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.suffix, str):
            raise TypeError("summary decoration suffix must be a string")
        object.__setattr__(
            self,
            "details",
            require_json_value(self.details, name="summary decoration details"),
        )


SummaryDecorator = Callable[[Sequence[AgentMessage], JSONValue], SummaryDecoration]


@dataclass(frozen=True)
class SummaryResourceOperationDecorationProfile:
    """Project Agent tool calls into structured summary resource evidence."""

    tool_operations: Mapping[str, str]
    detail_keys: Mapping[str, str]
    tags: Mapping[str, str]
    excluded_by: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    resource_argument: str = "path"

    def __post_init__(self) -> None:
        tool_operations = _non_empty_string_mapping(
            self.tool_operations,
            name="tool_operations",
        )
        detail_keys = _non_empty_string_mapping(
            self.detail_keys,
            name="detail_keys",
        )
        tags = _non_empty_string_mapping(self.tags, name="tags")
        operations = frozenset(tool_operations.values())
        if operations != detail_keys.keys() or operations != tags.keys():
            raise ValueError(
                "summary resource operation profile must declare matching "
                "operations, detail keys, and tags"
            )
        excluded_by: dict[str, tuple[str, ...]] = {}
        for operation, exclusions in self.excluded_by.items():
            if operation not in operations:
                raise ValueError(
                    "summary resource operation exclusions must target a "
                    "declared operation"
                )
            normalized = tuple(exclusions)
            if not normalized or any(item not in operations for item in normalized):
                raise ValueError(
                    "summary resource operation exclusions must reference "
                    "declared operations"
                )
            excluded_by[operation] = normalized
        if not isinstance(self.resource_argument, str) or not self.resource_argument:
            raise TypeError("summary resource argument must be a non-empty string")
        object.__setattr__(
            self,
            "tool_operations",
            MappingProxyType(tool_operations),
        )
        object.__setattr__(self, "detail_keys", MappingProxyType(detail_keys))
        object.__setattr__(self, "tags", MappingProxyType(tags))
        object.__setattr__(self, "excluded_by", MappingProxyType(excluded_by))


def collect_summary_resource_operations(
    messages: Sequence[AgentMessage],
    *,
    profile: SummaryResourceOperationDecorationProfile,
) -> SummaryResourceOperations:
    """Collect ordered, deduplicated resource operations from Agent tool calls."""

    resources: dict[str, set[str]] = {
        operation: set() for operation in profile.detail_keys
    }
    for message in messages:
        if not isinstance(message, AssistantMessage):
            continue
        for block in message.content:
            operation = profile.tool_operations.get(getattr(block, "name", ""))
            if operation is None:
                continue
            arguments = getattr(block, "arguments", None)
            if not isinstance(arguments, Mapping):
                continue
            resource = arguments.get(profile.resource_argument)
            if isinstance(resource, str) and resource:
                resources[operation].add(resource)

    for operation, excluded_operations in profile.excluded_by.items():
        excluded_resources: set[str] = set()
        for excluded_operation in excluded_operations:
            excluded_resources.update(resources[excluded_operation])
        resources[operation].difference_update(excluded_resources)
    return SummaryResourceOperations.from_mapping(
        {
            operation: tuple(sorted(operation_resources))
            for operation, operation_resources in resources.items()
        }
    )


def decorate_summary_resource_operations(
    messages: Sequence[AgentMessage],
    existing_details: JSONValue,
    *,
    profile: SummaryResourceOperationDecorationProfile,
) -> SummaryDecoration:
    """Render structured resource evidence into summary suffix and details."""

    operations = collect_summary_resource_operations(messages, profile=profile)
    projected_details: dict[str, JSONValue] = {
        profile.detail_keys[item.operation]: require_json_value(
            list(item.resources),
            name=f"summary resource operation {item.operation!r}",
        )
        for item in operations.operations
    }
    suffix_sections = [
        f"<{profile.tags[item.operation]}>\n"
        + "\n".join(item.resources)
        + f"\n</{profile.tags[item.operation]}>"
        for item in operations.operations
        if item.resources
    ]
    non_empty_details = {
        key: resources for key, resources in projected_details.items() if resources
    }
    if not non_empty_details:
        details = existing_details
    elif isinstance(existing_details, Mapping):
        details = {**existing_details, **projected_details}
    else:
        details = projected_details
    return SummaryDecoration(
        suffix="" if not suffix_sections else "\n\n" + "\n\n".join(suffix_sections),
        details=details,
    )


@dataclass(frozen=True)
class BranchSummaryPreparation:
    """The visible branch messages selected within a Product token budget."""

    messages: tuple[AgentMessage, ...]
    record_ids: tuple[str, ...]
    total_tokens: int


@dataclass(frozen=True)
class BranchSummaryDelta:
    """The abandoned branch path used as summary input during navigation."""

    records: tuple[object, ...]
    common_ancestor_id: str | None


def default_summary_completer(
    model: object,
    context: Context,
    options: CallOptions | None = None,
) -> Awaitable[str]:
    """Use the model's declared completion mode and return assistant text."""

    return _complete_text(model, context, options)


async def execute_transcript_compaction(
    *,
    preparation: CompactionPreparation,
    model: object,
    compaction_profile: SummaryProfile,
    turn_prefix_profile: SummaryProfile,
    api_key: str | None = None,
    headers: Mapping[str, str] | None = None,
    signal: object | None = None,
    custom_instructions: str | None = None,
    completer: SummaryCompleter = default_summary_completer,
    decorate: SummaryDecorator | None = None,
) -> CompactionResult:
    """Execute a standard transcript-compaction plan with Product prompt policy."""

    if preparation.is_split_turn and preparation.turn_prefix_messages:
        history_summary = (
            await _summarize_messages(
                preparation=preparation,
                model=model,
                profile=compaction_profile,
                api_key=api_key,
                headers=headers,
                signal=signal,
                custom_instructions=custom_instructions,
                completer=completer,
            )
            if preparation.messages_to_summarize
            else "No prior history."
        )
        turn_prefix_summary = await _summarize_turn_prefix(
            messages=preparation.turn_prefix_messages,
            model=model,
            profile=turn_prefix_profile,
            api_key=api_key,
            headers=headers,
            signal=signal,
            completer=completer,
        )
        summary = (
            f"{history_summary}\n\n---\n\n**Turn Context (split turn):**\n\n"
            f"{turn_prefix_summary}"
        )
    else:
        summary = await _summarize_messages(
            preparation=preparation,
            model=model,
            profile=compaction_profile,
            api_key=api_key,
            headers=headers,
            signal=signal,
            custom_instructions=custom_instructions,
            completer=completer,
        )

    messages = (
        *preparation.messages_to_summarize,
        *preparation.turn_prefix_messages,
    )
    existing_details = _json_details(preparation.details)
    decoration = (
        decorate(messages, existing_details)
        if decorate is not None
        else SummaryDecoration(details=existing_details)
    )
    return CompactionResult(
        summary=f"{summary}{decoration.suffix}",
        first_kept_entry_id=preparation.first_kept_entry_id,
        tokens_before=preparation.tokens_before,
        details=decoration.details,
    )


def prepare_branch_summary(
    entries: Sequence[object], *, token_budget: int = 0
) -> BranchSummaryPreparation:
    """Select visible Agent transcript messages for a branch summary."""

    messages: list[AgentMessage] = []
    record_ids: list[str] = []
    total_tokens = 0
    for entry in reversed(entries):
        message = _record_to_agent_message(entry)
        if message is None:
            continue
        tokens = estimate_agent_message_tokens(message)
        if token_budget > 0 and messages and total_tokens + tokens > token_budget:
            break
        messages.insert(0, message)
        record_ids.insert(0, cast(ConversationRecord[object], entry).record_id)
        total_tokens += tokens

    if not messages and entries:
        message = _record_to_agent_message(entries[-1])
        if message is not None:
            messages.append(message)
            record_ids.append(cast(ConversationRecord[object], entries[-1]).record_id)
            total_tokens = estimate_agent_message_tokens(message)

    return BranchSummaryPreparation(
        messages=tuple(messages),
        record_ids=tuple(record_ids),
        total_tokens=total_tokens,
    )


def collect_branch_summary_delta(
    session: object,
    *,
    old_leaf_id: str | None,
    target_id: str,
) -> BranchSummaryDelta:
    """Read the divergent path for a transcript branch without Product policy."""

    if old_leaf_id is None:
        return BranchSummaryDelta(records=(), common_ancestor_id=None)
    get_branch_delta = getattr(session, "get_branch_delta", None)
    if not callable(get_branch_delta):
        raise TypeError("session must provide get_branch_delta")
    delta = get_branch_delta(old_leaf_id, target_id)
    records = getattr(delta, "divergent_records", None)
    common_ancestor_id = getattr(delta, "common_ancestor_id", None)
    if not isinstance(records, Sequence) or isinstance(records, str):
        raise TypeError("branch delta divergent_records must be a sequence")
    if common_ancestor_id is not None and not isinstance(common_ancestor_id, str):
        raise TypeError("branch delta common_ancestor_id must be a string or None")
    return BranchSummaryDelta(
        records=tuple(records),
        common_ancestor_id=common_ancestor_id,
    )


def normalize_branch_summary_output(
    value: object,
    *,
    from_hook: bool,
) -> BranchSummaryOutput:
    """Normalize a Product or extension summary result for transcript storage."""

    if isinstance(value, BranchSummaryOutput):
        return replace(value, from_hook=from_hook)
    summary = getattr(value, "summary", None)
    details = getattr(value, "details", None)
    aborted = getattr(value, "aborted", False)
    error = getattr(value, "error", None)
    if summary is not None and not isinstance(summary, str):
        raise TypeError("branch summary must be a string or None")
    if not isinstance(aborted, bool):
        raise TypeError("branch summary aborted must be a boolean")
    if error is not None and not isinstance(error, str):
        raise TypeError("branch summary error must be a string or None")
    return BranchSummaryOutput(
        summary=summary,
        details=require_json_value(details, name="branch summary details"),
        from_hook=from_hook,
        aborted=aborted,
        error=error,
    )


async def execute_branch_summary(
    entries_or_messages: Sequence[object],
    *,
    model: object,
    profile: SummaryProfile,
    api_key: str | None = None,
    headers: Mapping[str, str] | None = None,
    signal: object | None = None,
    custom_instructions: str | None = None,
    replace_instructions: bool = False,
    reserve_tokens: int = 16_384,
    preamble: str = DEFAULT_BRANCH_SUMMARY_PREAMBLE,
    completer: SummaryCompleter = default_summary_completer,
    decorate: SummaryDecorator | None = None,
) -> BranchSummaryOutput:
    """Generate one normalized branch summary without mutating a transcript."""

    if _is_aborted(signal):
        return BranchSummaryOutput(aborted=True)
    try:
        messages = _normalize_branch_messages(entries_or_messages, reserve_tokens)
        if not messages:
            return BranchSummaryOutput(summary="No content to summarize")
        prompt = build_summary_prompt(
            profile,
            serialize_agent_conversation(_model_messages(messages)),
            mode="branch",
            custom_instructions=(None if replace_instructions else custom_instructions),
            prompt_override=(
                custom_instructions
                if custom_instructions and replace_instructions
                else None
            ),
        )
        summary = await completer(
            model,
            Context(
                system_prompt=prompt.system_prompt,
                messages=[
                    UserMessage(
                        role="user",
                        content=[TextPart(type="text", text=prompt.user_prompt)],
                        timestamp=0.0,
                    )
                ],
            ),
            _call_options(api_key=api_key, headers=headers, signal=signal),
        )
        if _is_aborted(signal):
            return BranchSummaryOutput(aborted=True)
        decoration = (
            decorate(messages, None) if decorate is not None else SummaryDecoration()
        )
        return BranchSummaryOutput(
            summary=f"{preamble}{summary or 'No summary generated'}{decoration.suffix}",
            details=decoration.details,
        )
    except Exception as exc:
        return BranchSummaryOutput(error=str(exc))


async def _summarize_messages(
    *,
    preparation: CompactionPreparation,
    model: object,
    profile: SummaryProfile,
    api_key: str | None,
    headers: Mapping[str, str] | None,
    signal: object | None,
    custom_instructions: str | None,
    completer: SummaryCompleter,
) -> str:
    mode = "update" if preparation.previous_summary else "initial"
    prompt = build_summary_prompt(
        profile,
        serialize_agent_conversation(
            _model_messages(preparation.messages_to_summarize)
        ),
        mode=mode,
        previous_summary=preparation.previous_summary,
        custom_instructions=custom_instructions,
    )
    return await completer(
        model,
        _summary_context(prompt.system_prompt, prompt.user_prompt),
        _call_options(api_key=api_key, headers=headers, signal=signal),
    )


async def _summarize_turn_prefix(
    *,
    messages: Sequence[AgentMessage],
    model: object,
    profile: SummaryProfile,
    api_key: str | None,
    headers: Mapping[str, str] | None,
    signal: object | None,
    completer: SummaryCompleter,
) -> str:
    prompt = build_summary_prompt(
        profile,
        serialize_agent_conversation(_model_messages(messages)),
        mode="turn-prefix",
    )
    return await completer(
        model,
        _summary_context(prompt.system_prompt, prompt.user_prompt),
        _call_options(api_key=api_key, headers=headers, signal=signal),
    )


async def _complete_text(
    model: object,
    context: Context,
    options: CallOptions | None,
) -> str:
    typed_model = cast(Model, model)
    mode = "stream" if typed_model.supports_stream else "complete"
    emit_trace(
        options,
        {
            "type": "summary:request",
            "mode": mode,
            "api": typed_model.api,
            "provider": typed_model.provider_id,
            "endpoint": typed_model.endpoint_id,
            "model": typed_model.id,
        },
    )
    if typed_model.supports_stream:
        event_stream = await stream(typed_model, context, options)
        message = await event_stream.result()
    else:
        message = await complete(typed_model, context, options)
    return "".join(
        part.text
        for part in getattr(message, "content", ())
        if getattr(part, "type", None) == "text" and hasattr(part, "text")
    )


def _summary_context(system_prompt: str, user_prompt: str) -> Context:
    return Context(
        system_prompt=system_prompt,
        messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text=user_prompt)],
                timestamp=0.0,
            )
        ],
    )


def _call_options(
    *, api_key: str | None, headers: Mapping[str, str] | None, signal: object | None
) -> CallOptions:
    return CallOptions(
        auth=ApiKeyAuth(api_key) if api_key else None,
        headers=dict(headers or {}),
        cancellation=signal,
    )


def serialize_agent_conversation(messages: Sequence[object]) -> str:
    """Render stable, concise Agent messages for a summary prompt."""

    parts: list[str] = []
    for message in messages:
        role = getattr(message, "role", None)
        if role == "user":
            text = _content_text(getattr(message, "content", ""))
            if text:
                parts.append(f"[User]: {text}")
        elif role == "assistant":
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[str] = []
            for block in getattr(message, "content", ()):
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    text_parts.append(block.text)
                elif block_type == "thinking":
                    thinking_parts.append(block.thinking)
                elif block_type == "toolCall":
                    tool_calls.append(_format_tool_call(block))
            if thinking_parts:
                parts.append("[Assistant thinking]: " + "\n".join(thinking_parts))
            if text_parts:
                parts.append("[Assistant]: " + "\n".join(text_parts))
            if tool_calls:
                parts.append(f"[Assistant tool calls]: {'; '.join(tool_calls)}")
        elif role == "toolResult":
            text = _content_text(getattr(message, "content", ""))
            if text:
                parts.append(f"[Tool result]: {_truncate_for_summary(text)}")
    return "\n\n".join(parts)


def estimate_agent_message_tokens(message: AgentMessage) -> int:
    """Use the standard transcript estimator for one visible Agent message."""

    from loushang.harness.transcript.context_usage import estimate_message_tokens

    return estimate_message_tokens(message)


def _normalize_branch_messages(
    entries_or_messages: Sequence[object], reserve_tokens: int
) -> tuple[AgentMessage, ...]:
    if not entries_or_messages:
        return ()
    if all(hasattr(item, "role") for item in entries_or_messages):
        return tuple(cast(AgentMessage, item) for item in entries_or_messages)
    return prepare_branch_summary(
        entries_or_messages,
        token_budget=max(reserve_tokens, 0),
    ).messages


def _record_to_agent_message(entry: object) -> AgentMessage | None:
    if not isinstance(entry, ConversationRecord):
        return None
    return record_to_context_item(cast(AgentTranscriptRecord, entry))


def _model_messages(messages: Sequence[AgentMessage]) -> list[object]:
    return [
        projected
        for message in messages
        if (projected := context_item_to_model_message(message)) is not None
    ]


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.text)
            for block in content
            if getattr(block, "type", None) == "text"
        )
    return ""


def _format_tool_call(block: object) -> str:
    arguments = getattr(block, "arguments", {}) or {}
    if isinstance(arguments, Mapping):
        args = ", ".join(f"{key}={value!r}" for key, value in arguments.items())
    else:
        args = repr(arguments)
    return f"{getattr(block, 'name', '')}({args})"


def _truncate_for_summary(text: str) -> str:
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    truncated_chars = len(text) - TOOL_RESULT_MAX_CHARS
    return f"{text[:TOOL_RESULT_MAX_CHARS]}\n\n[... {truncated_chars} more characters truncated]"


def _json_details(value: object | None) -> JSONValue:
    return require_json_value(value, name="compaction preparation details")


def _non_empty_string_mapping(
    value: Mapping[str, str],
    *,
    name: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise TypeError(f"{name} keys must be non-empty strings")
        if not isinstance(item, str) or not item:
            raise TypeError(f"{name} values must be non-empty strings")
        normalized[key] = item
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _is_aborted(signal: object | None) -> bool:
    return bool(signal is not None and getattr(signal, "aborted", False))


__all__ = [
    "DEFAULT_BRANCH_SUMMARY_PREAMBLE",
    "BranchSummaryPreparation",
    "BranchSummaryDelta",
    "SummaryDecoration",
    "SummaryDecorator",
    "SummaryCompleter",
    "SummaryResourceOperationDecorationProfile",
    "collect_summary_resource_operations",
    "decorate_summary_resource_operations",
    "default_summary_completer",
    "collect_branch_summary_delta",
    "estimate_agent_message_tokens",
    "execute_branch_summary",
    "execute_transcript_compaction",
    "normalize_branch_summary_output",
    "prepare_branch_summary",
    "serialize_agent_conversation",
]
