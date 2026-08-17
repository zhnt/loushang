"""Reusable summary execution for the optional Agent transcript profile.

Harness owns transcript-summary mechanics: message projection, prompt execution,
turn-prefix handling, and normalized compaction or branch outputs.  A Product
selects prompt profiles and may decorate a summary with domain facts such as
code-file activity; it does not reimplement the transcript algorithm.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal, TypeAlias, cast

from loushang.agent.types import (
    AgentMessage,
    ModelCallPreparation,
    PrepareModelCallFn,
)
from loushang.ai import (
    ApiKeyAuth,
    CallOptions,
    Context,
    Model,
    PreparedRequestLimits,
    complete,
    stream,
)
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
SUMMARY_MAX_CANONICAL_BYTES = 512 * 1024
SUMMARY_SOURCE_TARGET_BYTES = 384 * 1024
SUMMARY_REQUEST_OVERHEAD_BYTES = 64 * 1024
SUMMARY_MAX_SOURCE_BYTES = 8 * 1024 * 1024
SUMMARY_MAX_BATCHES = 16
SUMMARY_MAX_MERGE_DEPTH = 4
SUMMARY_MAX_CALLS = 32
SUMMARY_MAX_OUTPUT_TOKENS = 8_192
SUMMARY_TOKEN_SAFETY_RESERVE = 512
DEFAULT_BRANCH_SUMMARY_PREAMBLE = """The user explored a different conversation branch before returning here.
Summary of that exploration:

"""

SummaryCompleter = Callable[[object, Context, CallOptions | None], Awaitable[str]]
SummaryImagePolicy: TypeAlias = Literal["placeholder", "refuse"]


class SummaryImagePolicyError(ValueError):
    """Summary input contains an image forbidden by the selected policy."""


class SummaryCapacityPlanError(ValueError):
    """Summary input cannot be placed into the bounded execution plan."""


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


@dataclass(frozen=True)
class _SummaryCallResult:
    text: str


@dataclass
class _SummaryExecutionState:
    calls: int = 0
    next_sequence: int = 1
    snapshot_ids: list[str] = field(default_factory=list)

    def allocate_sequence(self) -> int:
        if self.calls >= SUMMARY_MAX_CALLS:
            raise SummaryCapacityPlanError(
                f"summary execution exceeds {SUMMARY_MAX_CALLS} model calls"
            )
        sequence = self.next_sequence
        self.calls += 1
        self.next_sequence += 1
        return sequence


@dataclass(frozen=True)
class _SummarySourceBudget:
    bytes: int
    tokens: int | None


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
    prepare_model_call: PrepareModelCallFn | None = None,
    request_limits: PreparedRequestLimits | None = None,
    image_policy: SummaryImagePolicy = "placeholder",
) -> CompactionResult:
    """Execute a standard transcript-compaction plan with Product prompt policy."""

    execution = _SummaryExecutionState()
    if preparation.is_split_turn and preparation.turn_prefix_messages:
        history_result = (
            await _summarize_messages(
                preparation=preparation,
                model=model,
                profile=compaction_profile,
                api_key=api_key,
                headers=headers,
                signal=signal,
                custom_instructions=custom_instructions,
                completer=completer,
                model_call_purpose="compaction_history",
                prepare_model_call=prepare_model_call,
                request_limits=request_limits,
                image_policy=image_policy,
                execution=execution,
            )
            if preparation.messages_to_summarize
            else _SummaryCallResult("No prior history.")
        )
        turn_prefix_result = await _summarize_turn_prefix(
            messages=preparation.turn_prefix_messages,
            model=model,
            profile=turn_prefix_profile,
            api_key=api_key,
            headers=headers,
            signal=signal,
            completer=completer,
            prepare_model_call=prepare_model_call,
            request_limits=request_limits,
            image_policy=image_policy,
            execution=execution,
        )
        summary = (
            f"{history_result.text}\n\n---\n\n"
            f"**Turn Context (split turn):**\n\n{turn_prefix_result.text}"
        )
    else:
        result = await _summarize_messages(
            preparation=preparation,
            model=model,
            profile=compaction_profile,
            api_key=api_key,
            headers=headers,
            signal=signal,
            custom_instructions=custom_instructions,
            completer=completer,
            model_call_purpose="compaction_history",
            prepare_model_call=prepare_model_call,
            request_limits=request_limits,
            image_policy=image_policy,
            execution=execution,
        )
        summary = result.text

    messages = (
        *preparation.messages_to_summarize,
        *preparation.turn_prefix_messages,
    )
    existing_details = _json_details(preparation.details)
    existing_details = _with_image_omission_diagnostic(
        existing_details,
        messages,
        image_policy=image_policy,
    )
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
        model_input_snapshot_ids=tuple(execution.snapshot_ids),
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
    model_input_snapshot_ids = getattr(value, "model_input_snapshot_ids", ())
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
        model_input_snapshot_ids=tuple(model_input_snapshot_ids),
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
    prepare_model_call: PrepareModelCallFn | None = None,
    request_limits: PreparedRequestLimits | None = None,
    image_policy: SummaryImagePolicy = "placeholder",
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
            serialize_agent_conversation(
                _model_messages(messages),
                image_policy=image_policy,
            ),
            mode="branch",
            custom_instructions=(None if replace_instructions else custom_instructions),
            prompt_override=(
                custom_instructions
                if custom_instructions and replace_instructions
                else None
            ),
        )
        context = Context(
            system_prompt=prompt.system_prompt,
            messages=[
                UserMessage(
                    role="user",
                    content=[TextPart(type="text", text=prompt.user_prompt)],
                    timestamp=0.0,
                )
            ],
        )
        options = await _prepare_summary_options(
            model,
            context,
            _call_options(
                model=model,
                api_key=api_key,
                headers=headers,
                signal=signal,
                request_limits=request_limits,
            ),
            purpose="branch_summary",
            sequence=1,
            prepare_model_call=prepare_model_call,
        )
        summary = await completer(model, context, options)
        if _is_aborted(signal):
            return BranchSummaryOutput(aborted=True)
        details = _with_image_omission_diagnostic(
            None,
            messages,
            image_policy=image_policy,
        )
        decoration = (
            decorate(messages, details)
            if decorate is not None
            else SummaryDecoration(details=details)
        )
        return BranchSummaryOutput(
            summary=f"{preamble}{summary or 'No summary generated'}{decoration.suffix}",
            details=decoration.details,
            model_input_snapshot_ids=_model_input_snapshot_ids(options),
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
    model_call_purpose: str,
    prepare_model_call: PrepareModelCallFn | None,
    request_limits: PreparedRequestLimits | None,
    image_policy: SummaryImagePolicy,
    execution: _SummaryExecutionState,
) -> _SummaryCallResult:
    mode = "update" if preparation.previous_summary else "initial"
    units = _serialized_conversation_turns(
        preparation.messages_to_summarize,
        image_policy=image_policy,
    )
    source_budget = _summary_source_budget(
        profile,
        model=model,
        mode=mode,
        previous_summary=preparation.previous_summary,
        custom_instructions=custom_instructions,
        request_limits=request_limits,
        enforce_model_context=completer is default_summary_completer,
    )
    batches = _pack_summary_units(units, source_budget=source_budget)
    partials: list[str] = []
    for index, conversation in enumerate(batches):
        partials.append(
            await _run_summary_call(
                conversation=conversation,
                model=model,
                profile=profile,
                mode=mode if index == 0 else "initial",
                previous_summary=(
                    preparation.previous_summary if index == 0 else None
                ),
                custom_instructions=custom_instructions,
                api_key=api_key,
                headers=headers,
                signal=signal,
                completer=completer,
                purpose=model_call_purpose,
                prepare_model_call=prepare_model_call,
                request_limits=request_limits,
                execution=execution,
            )
        )
    return _SummaryCallResult(
        await _merge_partial_summaries(
            partials,
            model=model,
            profile=profile,
            api_key=api_key,
            headers=headers,
            signal=signal,
            custom_instructions=custom_instructions,
            completer=completer,
            prepare_model_call=prepare_model_call,
            request_limits=request_limits,
            execution=execution,
        )
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
    prepare_model_call: PrepareModelCallFn | None,
    request_limits: PreparedRequestLimits | None,
    image_policy: SummaryImagePolicy,
    execution: _SummaryExecutionState,
) -> _SummaryCallResult:
    conversation = serialize_agent_conversation(
        _model_messages(messages),
        image_policy=image_policy,
    )
    source_budget = _summary_source_budget(
        profile,
        model=model,
        mode="turn-prefix",
        previous_summary=None,
        custom_instructions=None,
        request_limits=request_limits,
        enforce_model_context=completer is default_summary_completer,
    )
    if (
        len(conversation.encode("utf-8")) > source_budget.bytes
        or (
            source_budget.tokens is not None
            and _estimate_summary_tokens(conversation) > source_budget.tokens
        )
    ):
        raise SummaryCapacityPlanError(
            "turn-prefix summary has no legal cut under the request budget"
        )
    return _SummaryCallResult(
        await _run_summary_call(
            conversation=conversation,
            model=model,
            profile=profile,
            mode="turn-prefix",
            previous_summary=None,
            custom_instructions=None,
            api_key=api_key,
            headers=headers,
            signal=signal,
            completer=completer,
            purpose="compaction_turn_prefix",
            prepare_model_call=prepare_model_call,
            request_limits=request_limits,
            execution=execution,
        )
    )


async def _run_summary_call(
    *,
    conversation: str,
    model: object,
    profile: SummaryProfile,
    mode: str,
    previous_summary: str | None,
    custom_instructions: str | None,
    api_key: str | None,
    headers: Mapping[str, str] | None,
    signal: object | None,
    completer: SummaryCompleter,
    purpose: str,
    prepare_model_call: PrepareModelCallFn | None,
    request_limits: PreparedRequestLimits | None,
    execution: _SummaryExecutionState,
) -> str:
    prompt = build_summary_prompt(
        profile,
        conversation,
        mode=mode,
        previous_summary=previous_summary,
        custom_instructions=custom_instructions,
    )
    context = _summary_context(prompt.system_prompt, prompt.user_prompt)
    options = await _prepare_summary_options(
        model,
        context,
        _call_options(
            model=model,
            api_key=api_key,
            headers=headers,
            signal=signal,
            request_limits=request_limits,
        ),
        purpose=purpose,
        sequence=execution.allocate_sequence(),
        prepare_model_call=prepare_model_call,
    )
    text = await completer(model, context, options)
    execution.snapshot_ids.extend(_model_input_snapshot_ids(options))
    return text


async def _merge_partial_summaries(
    partials: Sequence[str],
    *,
    model: object,
    profile: SummaryProfile,
    api_key: str | None,
    headers: Mapping[str, str] | None,
    signal: object | None,
    custom_instructions: str | None,
    completer: SummaryCompleter,
    prepare_model_call: PrepareModelCallFn | None,
    request_limits: PreparedRequestLimits | None,
    execution: _SummaryExecutionState,
) -> str:
    current = list(partials)
    for depth in range(SUMMARY_MAX_MERGE_DEPTH + 1):
        if len(current) == 1:
            return current[0]
        if depth == SUMMARY_MAX_MERGE_DEPTH:
            break
        units = tuple(
            f"[Partial summary {index}]\n{text}"
            for index, text in enumerate(current, start=1)
        )
        source_budget = _summary_source_budget(
            profile,
            model=model,
            mode="initial",
            previous_summary=None,
            custom_instructions=custom_instructions,
            request_limits=request_limits,
            enforce_model_context=completer is default_summary_completer,
        )
        batches = _pack_summary_units(units, source_budget=source_budget)
        merged: list[str] = []
        for conversation in batches:
            merged.append(
                await _run_summary_call(
                    conversation=conversation,
                    model=model,
                    profile=profile,
                    mode="initial",
                    previous_summary=None,
                    custom_instructions=custom_instructions,
                    api_key=api_key,
                    headers=headers,
                    signal=signal,
                    completer=completer,
                    purpose="compaction_merge",
                    prepare_model_call=prepare_model_call,
                    request_limits=request_limits,
                    execution=execution,
                )
            )
        current = merged
    raise SummaryCapacityPlanError(
        f"summary merge exceeds maximum depth {SUMMARY_MAX_MERGE_DEPTH}"
    )


def _serialized_conversation_turns(
    messages: Sequence[AgentMessage],
    *,
    image_policy: SummaryImagePolicy,
) -> tuple[str, ...]:
    turns: list[list[AgentMessage]] = []
    current: list[AgentMessage] = []
    for message in messages:
        if getattr(message, "role", None) in {"user", "application"} and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)
    serialized = tuple(
        rendered
        for turn in turns
        if (
            rendered := serialize_agent_conversation(
                _model_messages(turn),
                image_policy=image_policy,
            )
        )
    )
    return serialized or ("[No visible conversation content]",)


def _summary_source_budget(
    profile: SummaryProfile,
    *,
    model: object,
    mode: str,
    previous_summary: str | None,
    custom_instructions: str | None,
    request_limits: PreparedRequestLimits | None,
    enforce_model_context: bool,
) -> _SummarySourceBudget:
    limits = _summary_request_limits(request_limits)
    maximum = limits.max_canonical_bytes
    assert maximum is not None
    empty_prompt = build_summary_prompt(
        profile,
        "",
        mode=mode,
        previous_summary=previous_summary,
        custom_instructions=custom_instructions,
    )
    prompt_bytes = len(empty_prompt.system_prompt.encode("utf-8")) + len(
        empty_prompt.user_prompt.encode("utf-8")
    )
    available = maximum - SUMMARY_REQUEST_OVERHEAD_BYTES - prompt_bytes
    if available <= 0:
        raise SummaryCapacityPlanError(
            "summary prompt overhead exceeds the prepared-request capacity limit"
        )
    maximum_input_tokens = limits.max_estimated_input_tokens
    context_window = getattr(model, "context_window", None)
    if (
        enforce_model_context
        and isinstance(context_window, int)
        and not isinstance(context_window, bool)
        and context_window > 0
    ):
        context_input_tokens = (
            context_window
            - _summary_max_output_tokens(model)
            - SUMMARY_TOKEN_SAFETY_RESERVE
        )
        maximum_input_tokens = (
            context_input_tokens
            if maximum_input_tokens is None
            else min(maximum_input_tokens, context_input_tokens)
        )
    source_tokens: int | None = None
    if maximum_input_tokens is not None:
        prompt_tokens = _estimate_summary_tokens(empty_prompt.system_prompt) + (
            _estimate_summary_tokens(empty_prompt.user_prompt)
        )
        source_tokens = maximum_input_tokens - prompt_tokens
        if source_tokens <= 0:
            raise SummaryCapacityPlanError(
                "summary prompt overhead exceeds the input-token capacity limit"
            )
    return _SummarySourceBudget(
        bytes=min(SUMMARY_SOURCE_TARGET_BYTES, available),
        tokens=source_tokens,
    )


def _pack_summary_units(
    units: Sequence[str],
    *,
    source_budget: _SummarySourceBudget,
) -> tuple[str, ...]:
    total_bytes = sum(len(unit.encode("utf-8")) for unit in units)
    if total_bytes > SUMMARY_MAX_SOURCE_BYTES:
        raise SummaryCapacityPlanError(
            f"summary source exceeds {SUMMARY_MAX_SOURCE_BYTES} bytes"
        )
    batches: list[str] = []
    current: list[str] = []
    current_bytes = 0
    current_tokens = 0
    separator_bytes = len("\n\n".encode())
    separator_tokens = _estimate_summary_tokens("\n\n")
    for unit in units:
        unit_bytes = len(unit.encode("utf-8"))
        unit_tokens = _estimate_summary_tokens(unit)
        if unit_bytes > source_budget.bytes or (
            source_budget.tokens is not None and unit_tokens > source_budget.tokens
        ):
            raise SummaryCapacityPlanError(
                "one conversation turn has no legal cut under the request budget"
            )
        added_bytes = unit_bytes + (separator_bytes if current else 0)
        added_tokens = unit_tokens + (separator_tokens if current else 0)
        exceeds_tokens = (
            source_budget.tokens is not None
            and current_tokens + added_tokens > source_budget.tokens
        )
        if current and (
            current_bytes + added_bytes > source_budget.bytes or exceeds_tokens
        ):
            batches.append("\n\n".join(current))
            current = []
            current_bytes = 0
            current_tokens = 0
            added_bytes = unit_bytes
            added_tokens = unit_tokens
        current.append(unit)
        current_bytes += added_bytes
        current_tokens += added_tokens
    if current:
        batches.append("\n\n".join(current))
    if not batches:
        batches.append("[No visible conversation content]")
    if len(batches) > SUMMARY_MAX_BATCHES:
        raise SummaryCapacityPlanError(
            f"summary plan exceeds {SUMMARY_MAX_BATCHES} batches"
        )
    return tuple(batches)


async def _prepare_summary_options(
    model: object,
    context: Context,
    options: CallOptions,
    *,
    purpose: str,
    sequence: int,
    prepare_model_call: PrepareModelCallFn | None,
) -> CallOptions:
    if prepare_model_call is None:
        return options
    result = prepare_model_call(
        ModelCallPreparation(
            purpose=purpose,
            sequence=sequence,
            model=cast(Model, model),
            context=context,
            options=options,
        )
    )
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, CallOptions):
        raise TypeError("prepare_model_call must return CallOptions")
    return result


def _model_input_snapshot_ids(options: CallOptions) -> tuple[str, ...]:
    committer = options.prepared_request_committer
    raw = getattr(committer, "model_input_snapshot_ids", ())
    if not isinstance(raw, tuple) or any(
        not isinstance(item, str) or not item.strip() for item in raw
    ):
        raise TypeError("prepared-request committer returned invalid Model Input lineage")
    return raw


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
    *,
    model: object,
    api_key: str | None,
    headers: Mapping[str, str] | None,
    signal: object | None,
    request_limits: PreparedRequestLimits | None,
) -> CallOptions:
    return CallOptions(
        auth=ApiKeyAuth(api_key) if api_key else None,
        headers=dict(headers or {}),
        cancellation=signal,
        max_output_tokens=_summary_max_output_tokens(model),
        request_limits=_summary_request_limits(request_limits),
    )


def _summary_max_output_tokens(model: object) -> int:
    model_maximum = getattr(model, "max_tokens", None)
    if (
        isinstance(model_maximum, int)
        and not isinstance(model_maximum, bool)
        and model_maximum > 0
    ):
        configured_maximum = min(model_maximum, SUMMARY_MAX_OUTPUT_TOKENS)
    else:
        configured_maximum = SUMMARY_MAX_OUTPUT_TOKENS
    context_window = getattr(model, "context_window", None)
    if (
        isinstance(context_window, int)
        and not isinstance(context_window, bool)
        and context_window > 0
    ):
        return min(configured_maximum, max(1, context_window // 4))
    return configured_maximum


def _estimate_summary_tokens(value: str) -> int:
    ascii_characters = sum(ord(character) < 128 for character in value)
    non_ascii_characters = len(value) - ascii_characters
    return (ascii_characters + 2) // 3 + non_ascii_characters


def serialize_agent_conversation(
    messages: Sequence[object],
    *,
    image_policy: SummaryImagePolicy = "placeholder",
) -> str:
    """Render stable, concise Agent messages for a summary prompt."""

    parts: list[str] = []
    for message in messages:
        role = getattr(message, "role", None)
        if role == "user":
            text = _content_text(
                getattr(message, "content", ""),
                image_policy=image_policy,
            )
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
                elif block_type == "image":
                    text_parts.append(
                        _summary_image_placeholder(block, image_policy=image_policy)
                    )
            if thinking_parts:
                parts.append("[Assistant thinking]: " + "\n".join(thinking_parts))
            if text_parts:
                parts.append("[Assistant]: " + "\n".join(text_parts))
            if tool_calls:
                parts.append(f"[Assistant tool calls]: {'; '.join(tool_calls)}")
        elif role == "toolResult":
            text = _content_text(
                getattr(message, "content", ""),
                image_policy=image_policy,
            )
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


def _content_text(
    content: object,
    *,
    image_policy: SummaryImagePolicy,
) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if getattr(block, "type", None) == "text":
                parts.append(str(block.text))
            elif getattr(block, "type", None) == "image":
                parts.append(
                    _summary_image_placeholder(block, image_policy=image_policy)
                )
        return "\n".join(parts)
    return ""


def _summary_image_placeholder(
    block: object,
    *,
    image_policy: SummaryImagePolicy,
) -> str:
    if image_policy == "refuse":
        raise SummaryImagePolicyError(
            "summary input contains an image and image policy is 'refuse'"
        )
    if image_policy != "placeholder":
        raise ValueError(f"unsupported summary image policy: {image_policy!r}")
    mime_type = getattr(block, "mime_type", "application/octet-stream")
    if not isinstance(mime_type, str) or not mime_type:
        mime_type = "application/octet-stream"
    data = getattr(block, "data", "")
    encoded_characters = len(data) if isinstance(data, str) else 0
    return (
        "[Image omitted from summary input: "
        f"mime_type={mime_type}; base64_characters={encoded_characters}]"
    )


def _with_image_omission_diagnostic(
    details: JSONValue,
    messages: Sequence[AgentMessage],
    *,
    image_policy: SummaryImagePolicy,
) -> JSONValue:
    image_count = _count_image_parts(messages)
    if image_count == 0:
        return details
    if image_policy == "refuse":
        raise SummaryImagePolicyError(
            "summary input contains an image and image policy is 'refuse'"
        )
    diagnostic: dict[str, JSONValue] = {
        "code": "image_omitted",
        "count": image_count,
    }
    if isinstance(details, Mapping):
        projected = dict(details)
        existing = projected.get("degradations")
        degradations = list(existing) if isinstance(existing, list) else []
        degradations.append(diagnostic)
        projected["degradations"] = degradations
        return require_json_value(projected, name="summary degradation details")
    projected_details: dict[str, JSONValue] = {"degradations": [diagnostic]}
    if details is not None:
        projected_details["sourceDetails"] = details
    return projected_details


def _count_image_parts(messages: Sequence[AgentMessage]) -> int:
    count = 0
    for message in messages:
        content = getattr(message, "content", ())
        if isinstance(content, str):
            continue
        count += sum(
            1 for block in content if getattr(block, "type", None) == "image"
        )
    return count


def _summary_request_limits(
    request_limits: PreparedRequestLimits | None,
) -> PreparedRequestLimits:
    if request_limits is None:
        return PreparedRequestLimits(
            max_canonical_bytes=SUMMARY_MAX_CANONICAL_BYTES
        )
    maximum = request_limits.max_canonical_bytes
    return replace(
        request_limits,
        max_canonical_bytes=(
            SUMMARY_MAX_CANONICAL_BYTES
            if maximum is None
            else min(maximum, SUMMARY_MAX_CANONICAL_BYTES)
        ),
    )


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
    "SUMMARY_MAX_CANONICAL_BYTES",
    "SUMMARY_MAX_BATCHES",
    "SUMMARY_MAX_CALLS",
    "SUMMARY_MAX_MERGE_DEPTH",
    "BranchSummaryPreparation",
    "BranchSummaryDelta",
    "SummaryDecoration",
    "SummaryDecorator",
    "SummaryCompleter",
    "SummaryCapacityPlanError",
    "SummaryImagePolicy",
    "SummaryImagePolicyError",
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
