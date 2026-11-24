"""Construct fixed Resume records and check shared historical identity."""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Generic, Literal, NamedTuple, Protocol, TypeVar, cast

from loushang.ai.types import ImagePart, UserMessage
from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.harness.conversation.jsonl_codec import ConversationJsonlRecordCodec
from loushang.harness.transcript.codecs import (
    STANDARD_PAYLOAD_VERSION,
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from loushang.harness.transcript.types import (
    AgentTranscriptPayload,
    AgentTranscriptRecord,
    ExtensionData,
)
from loushang.harness.transcript.writer import AgentTranscriptRecordFactory

if TYPE_CHECKING:
    from loushang.harness.transcript._resume_continuation import _ResumeIntentRead


def make_resume_record(
    kind: str,
    payload: AgentTranscriptPayload,
    *,
    record_id: str,
    parent_id: str | None,
    created_at: datetime,
    metadata: Mapping[str, JSONValue] | None = None,
) -> AgentTranscriptRecord:
    """Build a fixed-ID record through the existing Transcript factory."""
    factory = AgentTranscriptRecordFactory(
        clock=lambda: created_at, id_factory=lambda: record_id
    )
    return factory.create(kind, payload, parent_id=parent_id, metadata=metadata)


class _ResumeMessageBinding(Protocol):
    @property
    def record_id(self) -> str: ...
    @property
    def payload_digest(self) -> str: ...

    def to_message_metadata(self) -> dict[str, JSONValue]: ...


def make_resume_user_record(
    message: UserMessage,
    binding: _ResumeMessageBinding,
    *,
    parent_id: str | None,
    created_at: datetime,
    resource_metadata: Mapping[str, JSONValue] | None,
    evidence_name: str,
    metadata_conflict: str,
    digest: Callable[[UserMessage], str],
    payload_error: str,
    validate: Callable[[AgentTranscriptRecord], object],
    reserved_prefix: str | None = None,
) -> AgentTranscriptRecord:
    """Build and verify one ordinary UserMessage with detached resource evidence."""
    if digest(message) != binding.payload_digest:
        raise ValueError(payload_error)
    evidence = require_json_mapping(
        {} if resource_metadata is None else dict(resource_metadata), name=evidence_name
    )
    if reserved_prefix is not None and any(
        key.startswith(reserved_prefix) for key in evidence
    ):
        raise ValueError(metadata_conflict)
    binding_metadata = binding.to_message_metadata()
    if reserved_prefix is None and evidence.keys() & binding_metadata.keys():
        raise ValueError(metadata_conflict)
    record = make_resume_record(
        AGENT_MESSAGE_KIND,
        message,
        record_id=binding.record_id,
        parent_id=parent_id,
        created_at=created_at,
        metadata={**evidence, **binding_metadata},
    )
    validate(record)
    return record


def freeze_user_message(message: UserMessage) -> UserMessage:
    """Detach mutable input through the Transcript payload codec."""
    if not isinstance(message, UserMessage):
        raise TypeError("Resume input requires a UserMessage")
    registry = create_agent_transcript_payload_registry()
    payload = registry.encode(AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, message)
    frozen = registry.decode(AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, payload)
    if not isinstance(frozen, UserMessage):
        raise TypeError("Resume input codec did not preserve UserMessage")
    return frozen


def user_message_digest(
    message: UserMessage, *, digest_domain: bytes, require_externalized_images: bool
) -> str:
    """Hash the exact Transcript payload with the caller's historical domain."""
    if not isinstance(message, UserMessage):
        label = (
            "RuntimeBinding payload" if require_externalized_images else "Resume input"
        )
        raise TypeError(f"{label} requires a UserMessage")
    if require_externalized_images:
        content = message.content
        if isinstance(content, list) and any(
            isinstance(part, ImagePart) for part in content
        ):
            raise ValueError("RuntimeBinding image payload must be externalized first")
    payload = create_agent_transcript_payload_registry().encode(
        AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, message
    )
    return sha256(digest_domain + canonical_binding_bytes(payload)).hexdigest()


def input_record_digest(record: AgentTranscriptRecord, *, digest_domain: bytes) -> str:
    """Hash the complete original binding record through the Transcript codec."""
    payload = ConversationJsonlRecordCodec(
        create_agent_transcript_payload_registry()
    ).encode_record(record)
    return sha256(
        digest_domain + canonical_binding_bytes(payload, name="Resume input lookup record")
    ).hexdigest()


def canonical_binding_bytes(value: object, *, name: str = "RuntimeBinding metadata") -> bytes:
    return dump_json_value(value, name=name, ensure_ascii=True, sort_keys=True).encode("utf-8")


class SelectedAncestry:
    def __init__(self, domain: bytes) -> None:
        self._digest = sha256(domain)
        self._parent_id: str | None = None
        self._seen: set[str] = set()

    def require_next(self, record: AgentTranscriptRecord, *, error: str) -> None:
        if record.parent_id != self._parent_id or record.record_id in self._seen:
            raise ValueError(error)
        self._seen.add(record.record_id)

    def advance(
        self, record: AgentTranscriptRecord, encode: Callable[[object], bytes]
    ) -> None:
        identity = encode({"recordId": record.record_id, "parentId": record.parent_id})
        self._digest.update(len(identity).to_bytes(4, "big"))
        self._digest.update(identity)
        self._parent_id = record.record_id

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


class _HistoricalBinding(Protocol):
    @property
    def session_id(self) -> str: ...
    @property
    def input_id(self) -> str: ...


class _RuntimeBinding(_HistoricalBinding, _ResumeMessageBinding, Protocol):
    pass


_IntentT = TypeVar("_IntentT", bound="_ResumeIntentRead")
_BindingT = TypeVar("_BindingT", bound=_HistoricalBinding)
_LegacyBindingT = TypeVar("_LegacyBindingT", bound=_RuntimeBinding)
_LegacyBindingCo = TypeVar("_LegacyBindingCo", bound=_RuntimeBinding, covariant=True)
_ResultT = TypeVar("_ResultT")


class _LegacyBindingObservation(Protocol[_LegacyBindingCo]):
    @property
    def status(self) -> Literal["absent", "known", "unknown_version"]: ...
    @property
    def binding(self) -> _LegacyBindingCo | None: ...


def _binding_text(document: Mapping[str, object], key: str) -> str:
    value = document[key]
    if type(value) is not str:
        raise ValueError(f"RuntimeBinding {key} is invalid")
    return value


def decode_resume_binding_document(
    raw: Mapping[str, object],
    *,
    construct: Callable[..., _LegacyBindingT],
    construct_origin: Callable[[str, str], object],
) -> _LegacyBindingT:
    """Read the shared fields after the Product selects its historical wire schema."""
    document = require_json_mapping(dict(raw), name="RuntimeBinding metadata")
    origin = document["originEvidence"]
    if not isinstance(origin, dict):
        raise ValueError("RuntimeBinding origin evidence is invalid")
    if origin == {"kind": "legacy_unknown"}:
        provenance = None
    elif set(origin) == {"kind", "setId", "planFingerprint"} and origin.get("kind") == "composition":
        provenance = construct_origin(
            _binding_text(origin, "setId"), _binding_text(origin, "planFingerprint")
        )
    else:
        raise ValueError("RuntimeBinding origin evidence is invalid")
    differences = document["differenceCodes"]
    if not isinstance(differences, list) or any(
        type(value) is not str for value in differences
    ):
        raise ValueError("RuntimeBinding difference codes are invalid")
    return construct(
        attempt_id=_binding_text(document, "attemptId"),
        input_id=_binding_text(document, "inputId"),
        record_id=_binding_text(document, "recordId"),
        session_id=_binding_text(document, "sessionId"),
        original_leaf_id=(
            None if document["originalLeafId"] is None else _binding_text(document, "originalLeafId")
        ),
        ancestry_digest=_binding_text(document, "ancestryDigest"),
        subject_digest=_binding_text(document, "subjectDigest"),
        origin_composition=provenance,
        planned_fingerprint=_binding_text(document, "plannedFingerprint"),
        actual_fingerprint=_binding_text(document, "actualFingerprint"),
        payload_digest=_binding_text(document, "payloadDigest"),
        difference_codes=tuple(differences),
    )


def require_legacy_resume_user_payload(
    record: AgentTranscriptRecord, *, error: str = "RuntimeBinding requires an agent UserMessage record"
) -> UserMessage:
    payload = record.payload
    if record.kind != AGENT_MESSAGE_KIND or not isinstance(payload, UserMessage):
        raise ValueError(error)
    return payload


def require_legacy_resume_binding(
    record: AgentTranscriptRecord,
    binding: _RuntimeBinding,
    *,
    payload: UserMessage,
    expected_session_id: str,
    digest: Callable[[UserMessage], str],
) -> None:
    if binding.record_id != record.record_id or binding.session_id != expected_session_id:
        raise ValueError("RuntimeBinding record or Session identity differs")
    if binding.payload_digest != digest(payload):
        raise ValueError("RuntimeBinding payload digest differs from the message")


def read_legacy_runtime_binding(
    record: AgentTranscriptRecord,
    *,
    inspect_binding: Callable[[Mapping[str, object]], _LegacyBindingObservation[_LegacyBindingT]],
    digest: Callable[[UserMessage], str],
    payload_error: str = "RuntimeBinding requires an agent UserMessage record",
    missing_error: str = "RuntimeBinding known schema has no binding",
) -> _LegacyBindingT | Literal["unknown_version"] | None:
    observation = inspect_binding(record.metadata)
    if observation.status == "absent":
        return None
    payload = require_legacy_resume_user_payload(record, error=payload_error)
    if observation.status == "unknown_version":
        return "unknown_version"
    binding = observation.binding
    if binding is None:
        raise ValueError(missing_error)
    require_legacy_resume_binding(
        record, binding, payload=payload, expected_session_id=binding.session_id, digest=digest,
    )
    return binding


def project_legacy_runtime_binding(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
    ancestry: SelectedAncestry,
    inspect_binding: Callable[
        [Mapping[str, object]], _LegacyBindingObservation[_LegacyBindingT]
    ],
    digest: Callable[[UserMessage], str],
    construct: Callable[..., _ResultT],
) -> _ResultT:
    """Verify all legacy bindings and retain only the current Session's epoch."""
    status: Literal["none", "bound", "unknown_version"] = "none"
    selected_binding: _LegacyBindingT | None = None
    selected_record_id: str | None = None
    for record in records:
        ancestry.require_next(
            record, error="RuntimeBinding projection requires a complete parent-linked path"
        )
        ancestry.advance(record, canonical_binding_bytes)
        binding = read_legacy_runtime_binding(record, inspect_binding=inspect_binding, digest=digest)
        if binding is None:
            continue
        if isinstance(binding, str):
            status, selected_binding, selected_record_id = "unknown_version", None, record.record_id
            continue
        if binding.session_id == current_session_id and status != "unknown_version":
            status, selected_binding, selected_record_id = "bound", binding, record.record_id
    return construct(
        status, ancestry.hexdigest(), binding=selected_binding, record_id=selected_record_id
    )


def decode_attempt_record_fields(
    record: AgentTranscriptRecord,
    document: Mapping[str, object],
    *,
    effect_classes: tuple[object, ...],
    construct: Callable[..., _IntentT],
    identity_error: str,
) -> _IntentT:
    """Decode the shared intent fields after the Product checks its wire version."""
    attempt = construct(
        attempt_id=cast(str, document["attemptId"]),
        request_id=cast(str, document["requestId"]),
        session_id=cast(str, document["sessionId"]),
        original_leaf_id=cast(str | None, document["originalLeafId"]),
        ancestry_digest=cast(str, document["ancestryDigest"]),
        plan_fingerprint=cast(str, document["planFingerprint"]),
        epoch_fingerprint=cast(str, document["epochFingerprint"]),
        subject_digest=cast(str, document["subjectDigest"]),
        effect_classes=cast(tuple[str, ...], effect_classes),
    )
    if (
        record.record_id != attempt.attempt_id
        or record.parent_id != attempt.original_leaf_id
    ):
        raise ValueError(identity_error)
    return attempt


class _ActivationHistory(NamedTuple, Generic[_IntentT, _BindingT]):
    status: Literal["none", "pending", "unknown_version"]
    attempt: _IntentT | None
    ancestry_digest: str
    binding: _BindingT | None
    binding_record_id: str | None


def scan_activation_history(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
    ancestry: SelectedAncestry,
    encode: Callable[[object], bytes],
    attempt_prefix: str,
    attempt_readers: Mapping[str, Callable[[AgentTranscriptRecord], _IntentT]],
    read_binding: Callable[
        [AgentTranscriptRecord, Mapping[str, _IntentT]],
        _BindingT | Literal["unknown_version"] | None,
    ],
    path_error: str,
    ancestry_error: str,
    duplicate_error: str,
    track_other_sessions: bool = True,
    input_id: str | None = None,
) -> Generator[AgentTranscriptRecord | None, None, _ActivationHistory[_IntentT, _BindingT]]:
    """Observe the complete selected path through the Product's historical codecs."""
    pending: dict[str, _IntentT] = {}
    unknown = False
    selected_binding: _BindingT | None = None
    selected_record_id: str | None = None
    for record in records:
        ancestry.require_next(record, error=path_error)
        payload = record.payload
        if isinstance(payload, ExtensionData) and payload.extension_type.startswith(attempt_prefix):
            reader = attempt_readers.get(payload.extension_type)
            if reader is None:
                unknown = True
            else:
                attempt = reader(record)
                if attempt.ancestry_digest != ancestry.hexdigest():
                    raise ValueError(ancestry_error)
                if track_other_sessions or attempt.session_id == current_session_id:
                    if attempt.session_id in pending:
                        raise ValueError(duplicate_error)
                    pending[attempt.session_id] = attempt
        binding = read_binding(record, pending)
        match = None
        if isinstance(binding, str):
            unknown = True
        elif binding is not None:
            pending.pop(binding.session_id, None)
            if binding.session_id == current_session_id and not unknown:
                selected_binding = binding
                selected_record_id = record.record_id
                if binding.input_id == input_id:
                    match = record
        ancestry.advance(record, encode)
        yield match
    current = pending.get(current_session_id)
    if unknown:
        return _ActivationHistory(
            "unknown_version", None, ancestry.hexdigest(), None, selected_record_id
        )
    return _ActivationHistory(
        "pending" if current is not None else "none",
        current, ancestry.hexdigest(), selected_binding, selected_record_id,
    )


def finish_history_scan(
    steps: Generator[AgentTranscriptRecord | None, None, _ResultT],
    matches: list[AgentTranscriptRecord] | None = None,
) -> _ResultT:
    while True:
        try:
            match = next(steps)
        except StopIteration as complete:
            return complete.value
        if matches is not None and match is not None:
            matches.append(match)


def select_input_record(
    candidates: Sequence[AgentTranscriptRecord],
    *,
    expected_digest: str,
    digest: Callable[[AgentTranscriptRecord], str],
    duplicate: Literal["unknown", "conflict"] = "conflict",
) -> AgentTranscriptRecord | Literal["unknown", "conflict"]:
    """Require one candidate and the exact bytes fixed for that input."""
    if not candidates:
        return "unknown"
    if len(candidates) != 1:
        return duplicate
    record = candidates[0]
    return record if digest(record) == expected_digest else "conflict"
