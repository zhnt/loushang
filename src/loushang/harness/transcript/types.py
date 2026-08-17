from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Literal, TypeAlias, cast

from loushang.agent.types import AgentMessage, CustomAgentMessage
from loushang.ai.types import ImagePart, Message, TextPart
from loushang.foundation.json import JSONValue, require_json_mapping, require_json_value
from loushang.harness.conversation.types import (
    CommandExecutionRecord,
    ConversationRecord,
    OpaquePayload,
)
from loushang.harness.transcript.model_call_types import ModelCallOutcome
from loushang.harness.transcript.model_input_types import (
    ModelInputComponent,
    ModelInputSnapshot,
)
from loushang.harness.transcript.model_input_v2_types import (
    ModelInputNodeBundle,
    ModelInputSnapshotV2,
)

ContentBlock: TypeAlias = TextPart | ImagePart
ApplicationDeliveryMode: TypeAlias = Literal[
    "direct",
    "trigger_turn",
    "steering",
    "follow_up",
    "next_turn",
]
AnnotationOperation: TypeAlias = Literal["set", "remove"]


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_optional_text(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name=name)


def _model_input_lineage(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError("Model Input snapshot lineage must be a tuple")
    normalized = tuple(
        _require_text(item, name="Model Input snapshot lineage id") for item in value
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError("Model Input snapshot lineage ids must be unique")
    return normalized


def _require_non_negative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_timestamp(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("application message timestamp must be a number")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError("application message timestamp must be finite")
    return normalized


def _freeze_json_mapping(
    value: Mapping[str, object], *, name: str
) -> Mapping[str, JSONValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return MappingProxyType(require_json_mapping(dict(value), name=name))


@dataclass(frozen=True)
class ThinkingSelectionSnapshot:
    level: str

    def __post_init__(self) -> None:
        _require_text(self.level, name="thinking selection level")


@dataclass(frozen=True)
class ModelSelectionSnapshot:
    provider: str
    endpoint_id: str
    model_id: str

    def __post_init__(self) -> None:
        _require_text(self.provider, name="model selection provider")
        _require_text(self.endpoint_id, name="model selection endpoint id")
        _require_text(self.model_id, name="model selection model id")


@dataclass(frozen=True)
class ContextCompactionCheckpoint:
    summary: str
    first_kept_record_id: str
    tokens_before: int
    details: JSONValue = None
    from_hook: bool | None = None
    model_input_snapshot_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.summary, str):
            raise TypeError("compaction summary must be a string")
        _require_text(
            self.first_kept_record_id,
            name="compaction first kept record id",
        )
        _require_non_negative_int(
            self.tokens_before,
            name="compaction tokens before",
        )
        if self.from_hook is not None and type(self.from_hook) is not bool:
            raise TypeError("compaction from_hook must be a boolean or None")
        object.__setattr__(
            self,
            "model_input_snapshot_ids",
            _model_input_lineage(self.model_input_snapshot_ids),
        )
        object.__setattr__(
            self,
            "details",
            require_json_value(self.details, name="compaction details"),
        )

    @property
    def derivation_verifiable(self) -> bool:
        return bool(self.model_input_snapshot_ids)


@dataclass(frozen=True)
class BranchContextSummary:
    from_record_id: str
    summary: str
    details: JSONValue = None
    from_hook: bool | None = None
    model_input_snapshot_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.from_record_id, name="branch summary source record id")
        if not isinstance(self.summary, str):
            raise TypeError("branch summary must be a string")
        if self.from_hook is not None and type(self.from_hook) is not bool:
            raise TypeError("branch summary from_hook must be a boolean or None")
        object.__setattr__(
            self,
            "model_input_snapshot_ids",
            _model_input_lineage(self.model_input_snapshot_ids),
        )
        object.__setattr__(
            self,
            "details",
            require_json_value(self.details, name="branch summary details"),
        )

    @property
    def derivation_verifiable(self) -> bool:
        return bool(self.model_input_snapshot_ids)


@dataclass(frozen=True)
class ApplicationMessage(CustomAgentMessage):
    """Application-provided Agent input whose identity survives queueing."""

    application_message_id: str
    custom_type: str
    content: str | list[ContentBlock]
    timestamp: float
    display: bool = True
    details: JSONValue = None
    origin: str = "application"
    delivery_mode: ApplicationDeliveryMode = "direct"
    role: Literal["application"] = field(default="application", init=False)

    def __post_init__(self) -> None:
        _require_text(
            self.application_message_id,
            name="application message id",
        )
        _require_text(self.custom_type, name="application message custom type")
        if isinstance(self.content, str):
            content: str | list[ContentBlock] = self.content
        elif isinstance(self.content, list) and all(
            isinstance(part, TextPart | ImagePart) for part in self.content
        ):
            content = list(self.content)
        else:
            raise TypeError(
                "application message content must be text or text/image parts"
            )
        if type(self.display) is not bool:
            raise TypeError("application message display must be a boolean")
        _require_text(self.origin, name="application message origin")
        if self.delivery_mode not in {
            "direct",
            "trigger_turn",
            "steering",
            "follow_up",
            "next_turn",
        }:
            raise ValueError(
                "application message delivery mode must be direct, trigger_turn, "
                "steering, follow_up, or next_turn"
            )
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "timestamp", _require_timestamp(self.timestamp))
        object.__setattr__(
            self,
            "details",
            require_json_value(self.details, name="application message details"),
        )


@dataclass(frozen=True)
class ExtensionData:
    extension_type: str
    data: JSONValue = None

    def __post_init__(self) -> None:
        _require_text(self.extension_type, name="extension data type")
        object.__setattr__(
            self,
            "data",
            require_json_value(self.data, name="extension data"),
        )


@dataclass(frozen=True)
class RecordAnnotationPatch:
    target_record_id: str
    namespace: str
    operation: AnnotationOperation
    value: JSONValue = None

    def __post_init__(self) -> None:
        _require_text(self.target_record_id, name="annotation target record id")
        _require_text(self.namespace, name="annotation namespace")
        if self.operation not in {"set", "remove"}:
            raise ValueError("annotation operation must be 'set' or 'remove'")
        if self.operation == "remove" and self.value is not None:
            raise ValueError("removed annotations must not include a value")
        object.__setattr__(
            self,
            "value",
            require_json_value(self.value, name="annotation value"),
        )


@dataclass(frozen=True)
class ConversationMetadataPatch:
    values: Mapping[str, JSONValue] = field(default_factory=dict)
    removed_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = _freeze_json_mapping(self.values, name="conversation metadata values")
        if not isinstance(self.removed_keys, tuple | list):
            raise TypeError("conversation metadata removed keys must be a sequence")
        removed_keys = tuple(self.removed_keys)
        for key in removed_keys:
            _require_text(key, name="conversation metadata removed key")
        if len(set(removed_keys)) != len(removed_keys):
            raise ValueError("conversation metadata removed keys must be unique")
        overlap = set(values).intersection(removed_keys)
        if overlap:
            raise ValueError(
                "conversation metadata keys cannot be set and removed together: "
                + ", ".join(sorted(overlap))
            )
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "removed_keys", removed_keys)


AgentTranscriptPayload: TypeAlias = (
    Message
    | ThinkingSelectionSnapshot
    | ModelSelectionSnapshot
    | CommandExecutionRecord
    | ContextCompactionCheckpoint
    | BranchContextSummary
    | ApplicationMessage
    | ExtensionData
    | RecordAnnotationPatch
    | ConversationMetadataPatch
    | ModelInputComponent
    | ModelInputSnapshot
    | ModelInputNodeBundle
    | ModelInputSnapshotV2
    | ModelCallOutcome
)
DecodedAgentTranscriptPayload: TypeAlias = AgentTranscriptPayload | OpaquePayload
AgentTranscriptRecord: TypeAlias = ConversationRecord[DecodedAgentTranscriptPayload]


@dataclass(frozen=True)
class AgentTranscriptState:
    thinking_selection: ThinkingSelectionSnapshot = field(
        default_factory=lambda: ThinkingSelectionSnapshot(level="off")
    )
    model_selection: ModelSelectionSnapshot | None = None
    conversation_metadata: Mapping[str, JSONValue] = field(default_factory=dict)
    annotations: Mapping[str, Mapping[str, JSONValue]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        metadata = _freeze_json_mapping(
            self.conversation_metadata,
            name="conversation metadata state",
        )
        annotation_snapshot: dict[str, Mapping[str, JSONValue]] = {}
        if not isinstance(self.annotations, Mapping):
            raise TypeError("annotation state must be a mapping")
        for target_id, namespaces in self.annotations.items():
            _require_text(target_id, name="annotation state target id")
            annotation_snapshot[target_id] = _freeze_json_mapping(
                namespaces,
                name=f"annotations[{target_id!r}]",
            )
        object.__setattr__(self, "conversation_metadata", metadata)
        object.__setattr__(
            self,
            "annotations",
            MappingProxyType(annotation_snapshot),
        )


@dataclass(frozen=True)
class AgentTranscriptContext:
    messages: tuple[AgentMessage, ...]
    state: AgentTranscriptState

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))

    @property
    def thinking_selection(self) -> ThinkingSelectionSnapshot:
        return self.state.thinking_selection

    @property
    def model_selection(self) -> ModelSelectionSnapshot | None:
        return self.state.model_selection

    @property
    def thinking_level(self) -> str:
        return self.state.thinking_selection.level

    @property
    def model(self) -> dict[str, str] | None:
        selection = self.state.model_selection
        if selection is None:
            return None
        return {
            "provider": selection.provider,
            "endpoint_id": selection.endpoint_id,
            "model_id": selection.model_id,
        }


def application_message_content_blocks(
    message: ApplicationMessage,
) -> list[ContentBlock]:
    if isinstance(message.content, str):
        return [TextPart(type="text", text=message.content)]
    return list(message.content)


def require_agent_transcript_record(
    record: ConversationRecord[object],
) -> AgentTranscriptRecord:
    return cast(AgentTranscriptRecord, record)


__all__ = [
    "AgentTranscriptContext",
    "AgentTranscriptPayload",
    "AgentTranscriptRecord",
    "AgentTranscriptState",
    "AnnotationOperation",
    "ApplicationDeliveryMode",
    "ApplicationMessage",
    "BranchContextSummary",
    "ContentBlock",
    "ContextCompactionCheckpoint",
    "ConversationMetadataPatch",
    "DecodedAgentTranscriptPayload",
    "ExtensionData",
    "ModelSelectionSnapshot",
    "ModelCallOutcome",
    "RecordAnnotationPatch",
    "ThinkingSelectionSnapshot",
    "application_message_content_blocks",
    "require_agent_transcript_record",
]
