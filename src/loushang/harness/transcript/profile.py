from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast

from loushang.agent.types import AgentMessage
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    Message,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from loushang.harness.context.conversation import (
    ConversationPreviousSummary,
    ConversationRecordPorts,
)
from loushang.harness.conversation.jsonl_codec import (
    ConversationPayloadCodec,
    ConversationPayloadCodecRegistry,
)
from loushang.harness.conversation.replay import (
    ConversationCheckpoint,
    ConversationReplayFolder,
    ConversationReplayPorts,
)
from loushang.harness.conversation.types import (
    CommandExecutionRecord,
    ConversationRecord,
    OpaquePayload,
)
from loushang.harness.transcript.codecs import (
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    COMMAND_EXECUTION_KIND,
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    EXTENSION_DATA_KIND,
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_PREPARED_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    STANDARD_AGENT_TRANSCRIPT_KINDS,
    THINKING_SELECTION_KIND,
)
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
)
from loushang.harness.transcript.types import (
    AgentTranscriptContext,
    AgentTranscriptRecord,
    AgentTranscriptState,
    ApplicationMessage,
    BranchContextSummary,
    ContextCompactionCheckpoint,
    ConversationMetadataPatch,
    ExtensionData,
    ModelCallOutcome,
    ModelInputComponent,
    ModelInputNodeBundle,
    ModelInputSnapshot,
    ModelInputSnapshotV2,
    ModelSelectionSnapshot,
    RecordAnnotationPatch,
    ThinkingSelectionSnapshot,
    application_message_content_blocks,
)

ContextProjector = Callable[[AgentTranscriptRecord], AgentMessage | None]
StateReducer = Callable[
    [AgentTranscriptState, AgentTranscriptRecord], AgentTranscriptState
]
RecordRole = Callable[[AgentTranscriptRecord], str | None]
TokenEstimator = Callable[[AgentTranscriptRecord], int]
CutGroupBoundary = Callable[[AgentTranscriptRecord], bool]
CheckpointResolver = Callable[
    [AgentTranscriptRecord], ConversationCheckpoint[AgentMessage] | None
]
PreviousSummaryResolver = Callable[
    [AgentTranscriptRecord], ConversationPreviousSummary[str] | None
]
ContextTokenEstimator = Callable[[tuple[AgentMessage, ...]], int]

COMPACTION_SUMMARY_PREFIX = (
    "The conversation history before this point was compacted into the following "
    "summary:\n\n<summary>\n"
)
COMPACTION_SUMMARY_SUFFIX = "\n</summary>"
BRANCH_SUMMARY_PREFIX = (
    "The following is a summary of a branch that this conversation came back "
    "from:\n\n<summary>\n"
)
BRANCH_SUMMARY_SUFFIX = "</summary>"


@dataclass(frozen=True)
class RecordSemantics:
    """Stable runtime meaning for a record kind, independent of wire versions."""

    payload_types: tuple[type[object], ...]
    project_context: ContextProjector | None = None
    reduce_state: StateReducer | None = None
    role: RecordRole | None = None
    estimate_tokens: TokenEstimator | None = None
    separates_cut_group: CutGroupBoundary | None = None
    resolve_checkpoint: CheckpointResolver | None = None
    previous_summary: PreviousSummaryResolver | None = None

    def __post_init__(self) -> None:
        if not self.payload_types:
            raise ValueError("record semantics must declare at least one payload type")
        if any(
            not isinstance(payload_type, type) for payload_type in self.payload_types
        ):
            raise TypeError("record semantic payload types must be classes")


class AgentTranscriptProfile:
    """Compose versioned codecs with stable Agent transcript semantics."""

    def __init__(
        self,
        *,
        payload_codecs: ConversationPayloadCodecRegistry | None = None,
        context_token_estimator: ContextTokenEstimator | None = None,
    ) -> None:
        self._payload_codecs = (
            create_agent_transcript_payload_registry()
            if payload_codecs is None
            else payload_codecs
        )
        self._context_token_estimator = (
            context_token_estimator or _default_context_token_estimator
        )
        _require_standard_payload_codecs(self._payload_codecs)
        self._semantics: dict[str, RecordSemantics] = {}
        self._register_default_semantics()

    @classmethod
    def default(cls) -> AgentTranscriptProfile:
        return cls()

    @property
    def payload_codecs(self) -> ConversationPayloadCodecRegistry:
        return self._payload_codecs

    @property
    def semantic_kinds(self) -> tuple[str, ...]:
        return tuple(self._semantics)

    def register_payload_codec(
        self,
        kind: str,
        payload_version: int,
        codec: ConversationPayloadCodec[object],
    ) -> None:
        self._payload_codecs.register(kind, payload_version, codec)

    def register_record_profile(
        self,
        kind: str,
        semantics: RecordSemantics,
        *,
        replace: bool = False,
    ) -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("record semantic kind must be a non-empty string")
        if not isinstance(semantics, RecordSemantics):
            raise TypeError("record semantics must be a RecordSemantics instance")
        if kind in self._semantics and not replace:
            raise ValueError(f"record semantics are already registered for {kind!r}")
        self._semantics[kind] = semantics

    def replay_ports(
        self,
    ) -> ConversationReplayPorts[
        AgentTranscriptRecord,
        AgentMessage,
        AgentTranscriptState,
    ]:
        return ConversationReplayPorts(
            record_id=lambda record: record.record_id,
            project_visible_item=self.record_to_context_item,
            initialize_state=AgentTranscriptState,
            reduce_state=self.reduce_state,
            resolve_checkpoint=self.resolve_checkpoint,
        )

    def record_ports(
        self,
    ) -> ConversationRecordPorts[AgentTranscriptRecord, str]:
        return ConversationRecordPorts(
            record_id=lambda record: record.record_id,
            is_visible=self.record_is_visible,
            role=self.record_role,
            estimate_tokens=self.estimate_record_tokens,
            estimate_context_tokens=self.estimate_context_tokens,
            separates_cut_group=self.separates_cut_group,
            previous_summary=self.previous_summary,
        )

    def replay(
        self,
        records: Sequence[AgentTranscriptRecord],
    ) -> AgentTranscriptContext:
        projection = ConversationReplayFolder(self.replay_ports()).replay(records)
        return AgentTranscriptContext(
            messages=projection.items,
            state=projection.state,
        )

    def record_to_context_item(
        self,
        record: AgentTranscriptRecord,
    ) -> AgentMessage | None:
        semantics = self._semantics_for(record)
        if semantics is None or semantics.project_context is None:
            return None
        return semantics.project_context(record)

    def reduce_state(
        self,
        state: AgentTranscriptState,
        record: AgentTranscriptRecord,
    ) -> AgentTranscriptState:
        semantics = self._semantics_for(record)
        if semantics is None or semantics.reduce_state is None:
            return state
        return semantics.reduce_state(state, record)

    def record_is_visible(self, record: AgentTranscriptRecord) -> bool:
        return self.record_to_context_item(record) is not None

    def record_role(self, record: AgentTranscriptRecord) -> str | None:
        semantics = self._semantics_for(record)
        if semantics is None or semantics.role is None:
            return None
        return semantics.role(record)

    def estimate_record_tokens(self, record: AgentTranscriptRecord) -> int:
        semantics = self._semantics_for(record)
        if semantics is None or semantics.estimate_tokens is None:
            return 0
        estimate = semantics.estimate_tokens(record)
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise ValueError("record token estimate must be a non-negative integer")
        return estimate

    def estimate_context_tokens(
        self,
        records: tuple[AgentTranscriptRecord, ...],
    ) -> int:
        messages = tuple(
            message
            for record in records
            if (message := self.record_to_context_item(record)) is not None
        )
        estimate = self._context_token_estimator(messages)
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise ValueError("context token estimate must be a non-negative integer")
        return estimate

    def separates_cut_group(self, record: AgentTranscriptRecord) -> bool:
        semantics = self._semantics_for(record)
        if semantics is None or semantics.separates_cut_group is None:
            return False
        return semantics.separates_cut_group(record)

    def resolve_checkpoint(
        self,
        record: AgentTranscriptRecord,
    ) -> ConversationCheckpoint[AgentMessage] | None:
        semantics = self._semantics_for(record)
        if semantics is None or semantics.resolve_checkpoint is None:
            return None
        return semantics.resolve_checkpoint(record)

    def previous_summary(
        self,
        record: AgentTranscriptRecord,
    ) -> ConversationPreviousSummary[str] | None:
        semantics = self._semantics_for(record)
        if semantics is None or semantics.previous_summary is None:
            return None
        return semantics.previous_summary(record)

    def _semantics_for(
        self,
        record: AgentTranscriptRecord,
    ) -> RecordSemantics | None:
        if isinstance(record.payload, OpaquePayload):
            return None
        semantics = self._semantics.get(record.kind)
        if semantics is None:
            return None
        if not isinstance(record.payload, semantics.payload_types):
            raise TypeError(
                f"record {record.kind!r} has unexpected decoded payload "
                f"{type(record.payload).__name__}"
            )
        return semantics

    def _register_default_semantics(self) -> None:
        self.register_record_profile(
            AGENT_MESSAGE_KIND,
            RecordSemantics(
                payload_types=(UserMessage, AssistantMessage, ToolResultMessage),
                project_context=_payload_as_agent_message,
                reduce_state=_reduce_agent_message,
                role=_agent_message_role,
                estimate_tokens=_payload_tokens,
                separates_cut_group=lambda record: True,
            ),
        )
        self.register_record_profile(
            THINKING_SELECTION_KIND,
            RecordSemantics(
                payload_types=(ThinkingSelectionSnapshot,),
                reduce_state=_reduce_thinking_selection,
            ),
        )
        self.register_record_profile(
            MODEL_SELECTION_KIND,
            RecordSemantics(
                payload_types=(ModelSelectionSnapshot,),
                reduce_state=_reduce_model_selection,
            ),
        )
        self.register_record_profile(
            COMMAND_EXECUTION_KIND,
            RecordSemantics(
                payload_types=(CommandExecutionRecord,),
                project_context=_project_command,
                role=lambda record: "user",
                estimate_tokens=_payload_tokens,
            ),
        )
        self.register_record_profile(
            CONTEXT_COMPACTION_CHECKPOINT_KIND,
            RecordSemantics(
                payload_types=(ContextCompactionCheckpoint,),
                separates_cut_group=lambda record: True,
                resolve_checkpoint=_resolve_compaction_checkpoint,
                previous_summary=_resolve_previous_summary,
            ),
        )
        self.register_record_profile(
            CONTEXT_BRANCH_SUMMARY_KIND,
            RecordSemantics(
                payload_types=(BranchContextSummary,),
                project_context=_project_branch_summary,
                role=lambda record: "user",
                estimate_tokens=_payload_tokens,
            ),
        )
        self.register_record_profile(
            APPLICATION_MESSAGE_KIND,
            RecordSemantics(
                payload_types=(ApplicationMessage,),
                project_context=_payload_as_agent_message,
                role=lambda record: "user",
                estimate_tokens=_payload_tokens,
            ),
        )
        self.register_record_profile(
            EXTENSION_DATA_KIND,
            RecordSemantics(payload_types=(ExtensionData,)),
        )
        self.register_record_profile(
            RECORD_ANNOTATION_PATCH_KIND,
            RecordSemantics(
                payload_types=(RecordAnnotationPatch,),
                reduce_state=_reduce_annotation_patch,
            ),
        )
        self.register_record_profile(
            CONVERSATION_METADATA_PATCH_KIND,
            RecordSemantics(
                payload_types=(ConversationMetadataPatch,),
                reduce_state=_reduce_metadata_patch,
            ),
        )
        self.register_record_profile(
            MODEL_INPUT_COMPONENT_KIND,
            RecordSemantics(
                payload_types=(ModelInputComponent, ModelInputNodeBundle),
            ),
        )
        self.register_record_profile(
            MODEL_INPUT_PREPARED_KIND,
            RecordSemantics(
                payload_types=(ModelInputSnapshot, ModelInputSnapshotV2),
            ),
        )
        self.register_record_profile(
            MODEL_CALL_OUTCOME_KIND,
            RecordSemantics(payload_types=(ModelCallOutcome,)),
        )


def record_to_context_item(
    record: AgentTranscriptRecord,
) -> AgentMessage | None:
    return _DEFAULT_PROFILE.record_to_context_item(record)


def record_is_visible(record: AgentTranscriptRecord) -> bool:
    return _DEFAULT_PROFILE.record_is_visible(record)


def record_role(record: AgentTranscriptRecord) -> str | None:
    return _DEFAULT_PROFILE.record_role(record)


def estimate_record_tokens(record: AgentTranscriptRecord) -> int:
    return _DEFAULT_PROFILE.estimate_record_tokens(record)


def command_execution_to_text(command: CommandExecutionRecord) -> str:
    text = f"Ran `{command.command}`\n"
    if command.output:
        text += f"```\n{command.output}\n```"
    else:
        text += "(no output)"
    if command.cancelled:
        text += "\n\n(command cancelled)"
    elif command.exit_code not in (None, 0):
        text += f"\n\nCommand exited with code {command.exit_code}"
    if command.truncated and command.full_output_path:
        text += f"\n\n[Output truncated. Full output: {command.full_output_path}]"
    return text


def application_message_to_user_message(
    message: ApplicationMessage,
) -> UserMessage:
    return UserMessage(
        role="user",
        content=application_message_content_blocks(message),
        timestamp=message.timestamp,
    )


def context_item_to_model_message(message: AgentMessage) -> Message | None:
    if isinstance(message, UserMessage | AssistantMessage | ToolResultMessage):
        return message
    if isinstance(message, ApplicationMessage):
        return application_message_to_user_message(message)
    return None


def context_items_to_model_messages(
    messages: Sequence[AgentMessage],
    *,
    image_placeholder: str | None = None,
) -> list[Message]:
    """Project transcript context and optionally replace image parts."""

    projected = [
        model_message
        for message in messages
        if (model_message := context_item_to_model_message(message)) is not None
    ]
    if image_placeholder is None:
        return projected
    placeholder = TextPart(type="text", text=image_placeholder)
    return [
        _replace_message_images(message, placeholder=placeholder)
        for message in projected
    ]


def _replace_message_images(message: Message, *, placeholder: TextPart) -> Message:
    if not isinstance(message, UserMessage | ToolResultMessage):
        return message
    content = message.content
    if not isinstance(content, list):
        return message

    filtered: list[TextPart | ImagePart] = []
    for block in content:
        if isinstance(block, ImagePart):
            if not (
                filtered
                and isinstance(filtered[-1], TextPart)
                and filtered[-1].text == placeholder.text
            ):
                filtered.append(placeholder)
            continue
        filtered.append(block)
    if filtered == content:
        return message
    return replace(message, content=filtered)


def _payload_as_agent_message(record: AgentTranscriptRecord) -> AgentMessage:
    return cast(AgentMessage, record.payload)


def _reduce_agent_message(
    state: AgentTranscriptState,
    record: AgentTranscriptRecord,
) -> AgentTranscriptState:
    message = record.payload
    if not isinstance(message, AssistantMessage):
        return state
    return _new_state(
        state,
        model_selection=ModelSelectionSnapshot(
            provider=message.provider,
            endpoint_id=message.endpoint,
            model_id=message.model,
        ),
    )


def _reduce_thinking_selection(
    state: AgentTranscriptState,
    record: AgentTranscriptRecord,
) -> AgentTranscriptState:
    return _new_state(
        state,
        thinking_selection=cast(ThinkingSelectionSnapshot, record.payload),
    )


def _reduce_model_selection(
    state: AgentTranscriptState,
    record: AgentTranscriptRecord,
) -> AgentTranscriptState:
    return _new_state(
        state,
        model_selection=cast(ModelSelectionSnapshot, record.payload),
    )


def _reduce_metadata_patch(
    state: AgentTranscriptState,
    record: AgentTranscriptRecord,
) -> AgentTranscriptState:
    patch = cast(ConversationMetadataPatch, record.payload)
    metadata = dict(state.conversation_metadata)
    metadata.update(patch.values)
    for key in patch.removed_keys:
        metadata.pop(key, None)
    return _new_state(state, conversation_metadata=metadata)


def _reduce_annotation_patch(
    state: AgentTranscriptState,
    record: AgentTranscriptRecord,
) -> AgentTranscriptState:
    patch = cast(RecordAnnotationPatch, record.payload)
    annotations = {
        target: dict(namespaces) for target, namespaces in state.annotations.items()
    }
    target_annotations = annotations.setdefault(patch.target_record_id, {})
    if patch.operation == "set":
        target_annotations[patch.namespace] = patch.value
    else:
        target_annotations.pop(patch.namespace, None)
        if not target_annotations:
            annotations.pop(patch.target_record_id, None)
    return _new_state(state, annotations=annotations)


def _new_state(
    state: AgentTranscriptState,
    *,
    thinking_selection: ThinkingSelectionSnapshot | None = None,
    model_selection: ModelSelectionSnapshot | None | object = ...,
    conversation_metadata=None,
    annotations=None,
) -> AgentTranscriptState:
    return AgentTranscriptState(
        thinking_selection=thinking_selection or state.thinking_selection,
        model_selection=(
            state.model_selection
            if model_selection is ...
            else cast(ModelSelectionSnapshot | None, model_selection)
        ),
        conversation_metadata=(
            state.conversation_metadata
            if conversation_metadata is None
            else conversation_metadata
        ),
        annotations=state.annotations if annotations is None else annotations,
    )


def _agent_message_role(record: AgentTranscriptRecord) -> str | None:
    role = getattr(record.payload, "role", None)
    return role if isinstance(role, str) else None


def _project_command(record: AgentTranscriptRecord) -> AgentMessage | None:
    command = cast(CommandExecutionRecord, record.payload)
    if command.exclude_from_context:
        return None
    return _user_message(
        command_execution_to_text(command),
        created_at=record.created_at,
    )


def _project_branch_summary(record: AgentTranscriptRecord) -> UserMessage:
    summary = cast(BranchContextSummary, record.payload)
    return _user_message(
        BRANCH_SUMMARY_PREFIX + summary.summary + BRANCH_SUMMARY_SUFFIX,
        created_at=record.created_at,
    )


def _resolve_compaction_checkpoint(
    record: AgentTranscriptRecord,
) -> ConversationCheckpoint[AgentMessage]:
    checkpoint = cast(ContextCompactionCheckpoint, record.payload)
    return ConversationCheckpoint(
        first_kept_record_id=checkpoint.first_kept_record_id,
        summary_item=_user_message(
            COMPACTION_SUMMARY_PREFIX + checkpoint.summary + COMPACTION_SUMMARY_SUFFIX,
            created_at=record.created_at,
        ),
    )


def _resolve_previous_summary(
    record: AgentTranscriptRecord,
) -> ConversationPreviousSummary[str]:
    checkpoint = cast(ContextCompactionCheckpoint, record.payload)
    return ConversationPreviousSummary(
        first_kept_record_id=checkpoint.first_kept_record_id,
        content=checkpoint.summary,
    )


def _user_message(text: str, *, created_at: str) -> UserMessage:
    return UserMessage(
        role="user",
        content=[TextPart(type="text", text=text)],
        timestamp=_timestamp_from_iso(created_at),
    )


def _timestamp_from_iso(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _payload_tokens(record: AgentTranscriptRecord) -> int:
    payload = record.payload
    if isinstance(payload, CommandExecutionRecord):
        return _characters_to_tokens(len(payload.command) + len(payload.output))
    if isinstance(payload, ApplicationMessage):
        return _content_tokens(payload.content)
    if isinstance(payload, BranchContextSummary | ContextCompactionCheckpoint):
        return _characters_to_tokens(len(payload.summary))
    if isinstance(payload, UserMessage):
        return _content_tokens(payload.content)
    if isinstance(payload, AssistantMessage):
        characters = 0
        for part in payload.content:
            if isinstance(part, TextPart):
                characters += len(part.text)
            elif isinstance(part, ThinkingPart):
                characters += len(part.thinking)
            elif isinstance(part, ToolCall):
                characters += len(part.name) + len(str(part.arguments))
            elif isinstance(part, ImagePart):
                characters += 4_800
        return _characters_to_tokens(characters)
    if isinstance(payload, ToolResultMessage):
        return _content_tokens(payload.content)
    return 0


def _content_tokens(content: str | list[TextPart | ImagePart]) -> int:
    if isinstance(content, str):
        return _characters_to_tokens(len(content))
    characters = sum(
        len(part.text) if isinstance(part, TextPart) else 4_800 for part in content
    )
    return _characters_to_tokens(characters)


def _characters_to_tokens(characters: int) -> int:
    return (characters + 3) // 4


def _default_context_token_estimator(messages: tuple[AgentMessage, ...]) -> int:
    # A profile consumer can inject a model-aware estimator. The default remains
    # deterministic and deliberately mirrors the per-record approximation.
    return sum(_agent_message_tokens(message) for message in messages)


def _require_standard_payload_codecs(
    registry: ConversationPayloadCodecRegistry,
) -> None:
    registered = set(registry.registered_keys)
    missing = [
        kind for kind in STANDARD_AGENT_TRANSCRIPT_KINDS if (kind, 1) not in registered
    ]
    if missing:
        raise ValueError(
            "Agent transcript profile is missing standard payload codecs: "
            + ", ".join(missing)
        )
    model_input_kinds = (
        MODEL_INPUT_COMPONENT_KIND,
        MODEL_INPUT_PREPARED_KIND,
    )
    missing_v2 = [
        kind
        for kind in model_input_kinds
        if (kind, MODEL_INPUT_V2_PAYLOAD_VERSION) not in registered
    ]
    if missing_v2:
        raise ValueError(
            "Agent transcript profile is missing Model Input v2 payload codecs: "
            + ", ".join(missing_v2)
        )
    required = set(registry.required_kinds)
    missing_required = [kind for kind in model_input_kinds if kind not in required]
    if missing_required:
        raise ValueError(
            "Agent transcript profile is missing required payload kinds: "
            + ", ".join(missing_required)
        )


def _agent_message_tokens(message: AgentMessage) -> int:
    if isinstance(message, ApplicationMessage):
        return _content_tokens(message.content)
    temporary = ConversationRecord(
        record_id="token-estimate",
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="1970-01-01T00:00:00Z",
        payload=cast(UserMessage | AssistantMessage | ToolResultMessage, message),
    )
    return _payload_tokens(cast(AgentTranscriptRecord, temporary))


_DEFAULT_PROFILE = AgentTranscriptProfile.default()


__all__ = [
    "AgentTranscriptProfile",
    "BRANCH_SUMMARY_PREFIX",
    "BRANCH_SUMMARY_SUFFIX",
    "COMPACTION_SUMMARY_PREFIX",
    "COMPACTION_SUMMARY_SUFFIX",
    "RecordSemantics",
    "application_message_to_user_message",
    "command_execution_to_text",
    "context_item_to_model_message",
    "context_items_to_model_messages",
    "estimate_record_tokens",
    "record_is_visible",
    "record_role",
    "record_to_context_item",
]
