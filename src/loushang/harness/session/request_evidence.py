"""Request-local Resource evidence bound to durable Model Input messages."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast

from loushang.agent import ModelCallPreparation
from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.capabilities.prompt_preflight import PromptPreflightResult
from loushang.harness.resources._skill_catalog_consumer import LoadedSkillBody
from loushang.harness.transcript.model_input import RebuiltModelInput
from loushang.harness.transcript.model_input_types import ModelInputSnapshot
from loushang.harness.transcript.model_input_v2_types import ModelInputSnapshotV2
from loushang.harness.transcript.types import AgentTranscriptRecord

RESOURCE_EVIDENCE_COMPONENT = "resource_evidence"
RESOURCE_EVIDENCE_SCHEMA_ID = "loushang.model-input.resource-evidence"
RESOURCE_EVIDENCE_SCHEMA_VERSION = 1
_MESSAGE_TEXT_DIGEST_DOMAIN = b"loushang.model-input.message-text/v1\0"


class RequestEvidenceIntegrityError(RuntimeError):
    """Request evidence cannot be associated without guessing."""


@dataclass(frozen=True, slots=True)
class PreparedResourceEvidence:
    """Immutable loaded-Resource evidence before a message has a record id."""

    model_visible_text: str
    skills: tuple[dict[str, JSONValue], ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.model_visible_text, str) or not self.model_visible_text:
            raise ValueError("Resource evidence model-visible text must be non-empty")
        if not self.skills:
            raise ValueError("Resource evidence must contain a loaded Skill")
        frozen_skills = tuple(
            require_json_mapping(skill, name=f"resource evidence skill[{index}]")
            for index, skill in enumerate(self.skills)
        )
        object.__setattr__(self, "skills", frozen_skills)

    @property
    def message_text_digest(self) -> str:
        return _message_text_digest(self.model_visible_text)

    def to_message_payload(
        self,
        *,
        message_record_id: str,
        message_index: int,
    ) -> dict[str, JSONValue]:
        if not isinstance(message_record_id, str) or not message_record_id:
            raise ValueError("Resource evidence message record id must be non-empty")
        if isinstance(message_index, bool) or message_index < 0:
            raise ValueError("Resource evidence message index must be non-negative")
        return {
            "messageIndex": message_index,
            "messageRecordId": message_record_id,
            "messageTextDigest": self.message_text_digest,
            "modelVisibleText": self.model_visible_text,
            "skills": [dict(skill) for skill in self.skills],
        }


class RequestEvidenceRuntimePort(Protocol):
    """Narrow input/event lifecycle used by the common Session runtime."""

    def prepare(self, result: object) -> object | None: ...

    def bind(self, message: object, evidence: object, *, owner: object) -> None: ...

    def commit_message(self, message: object, record_id: str) -> bool: ...

    def discard_owner(self, owner: object) -> None: ...

    def close(self) -> None: ...


ContextMessageBindings = Callable[[], tuple[tuple[str, object], ...]]
ActiveRecordsProvider = Callable[[], Sequence[AgentTranscriptRecord]]
ModelInputRebuilder = Callable[[str], RebuiltModelInput]


@dataclass(slots=True)
class _PendingEvidence:
    message: object
    role: str
    text: str
    evidence: PreparedResourceEvidence
    owner: object


class SessionRequestEvidenceRuntime:
    """Associate lazy Resource loads with exact Session messages and requests."""

    def __init__(
        self,
        *,
        get_context_message_bindings: ContextMessageBindings,
        get_active_records: ActiveRecordsProvider,
        rebuild_model_input: ModelInputRebuilder,
    ) -> None:
        for callback, name in (
            (get_context_message_bindings, "context message bindings"),
            (get_active_records, "active transcript records"),
            (rebuild_model_input, "Model Input reconstruction"),
        ):
            if not callable(callback):
                raise TypeError(f"request evidence requires {name}")
        self._get_context_message_bindings = get_context_message_bindings
        self._get_active_records = get_active_records
        self._rebuild_model_input = rebuild_model_input
        self._pending: list[_PendingEvidence] = []
        self._committed: dict[str, PreparedResourceEvidence] = {}
        self._recovered: dict[str, PreparedResourceEvidence] = {}
        self._scanned_snapshot_ids: set[str] = set()
        self._closed = False

    def prepare(self, result: object) -> PreparedResourceEvidence | None:
        self._require_open()
        if not isinstance(result, PromptPreflightResult):
            raise TypeError("request evidence requires a PromptPreflightResult")
        if not result.loaded_skills:
            return None
        skills = tuple(
            _loaded_skill_payload(loaded) for loaded in result.loaded_skills
        )
        return PreparedResourceEvidence(
            model_visible_text=result.text,
            skills=skills,
        )

    def bind(self, message: object, evidence: object, *, owner: object) -> None:
        self._require_open()
        if not isinstance(evidence, PreparedResourceEvidence):
            raise TypeError("request evidence binding received an invalid value")
        role, text = _message_signature(message)
        if role != "user" or text != evidence.model_visible_text:
            raise RequestEvidenceIntegrityError(
                "prepared Resource evidence does not match its delivered user message"
            )
        self._pending.append(
            _PendingEvidence(
                message=message,
                role=role,
                text=text,
                evidence=evidence,
                owner=owner,
            )
        )

    def commit_message(self, message: object, record_id: str) -> bool:
        self._require_open()
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("request evidence requires a transcript record id")
        role, text = _message_signature(message)
        pending_index = self._pending_index(message, role=role, text=text)
        if pending_index is None:
            return False
        pending = self._pending.pop(pending_index)
        existing = self._committed.get(record_id)
        if existing is not None and existing != pending.evidence:
            raise RequestEvidenceIntegrityError(
                "one transcript message has conflicting Resource evidence"
            )
        self._committed[record_id] = pending.evidence
        return True

    def discard_owner(self, owner: object) -> None:
        if self._closed:
            return
        self._pending = [item for item in self._pending if item.owner is not owner]

    def close(self) -> None:
        self._closed = True
        self._pending.clear()
        self._committed.clear()
        self._recovered.clear()
        self._scanned_snapshot_ids.clear()

    def project_model_input(
        self,
        preparation: ModelCallPreparation,
    ) -> dict[str, JSONValue] | None:
        """Build the exact JSON-safe evidence component for one logical request."""

        self._require_open()
        if not isinstance(preparation, ModelCallPreparation):
            raise TypeError("request evidence requires ModelCallPreparation")
        active_records = tuple(self._get_active_records())
        active_by_id = {record.record_id: record for record in active_records}
        self._recover_from_snapshots(active_records, active_by_id=active_by_id)

        bindings = tuple(self._get_context_message_bindings())
        binding_record_ids = tuple(record_id for record_id, _message in bindings)
        if len(set(binding_record_ids)) != len(binding_record_ids):
            raise RequestEvidenceIntegrityError(
                "transcript context contains duplicate message record ids"
            )
        selected: list[tuple[int, str, PreparedResourceEvidence]] = []
        for index, (record_id, message) in enumerate(bindings):
            recovered = self._recovered.get(record_id)
            committed = self._committed.get(record_id)
            if recovered is not None and committed is not None and recovered != committed:
                raise RequestEvidenceIntegrityError(
                    "committed Resource evidence conflicts with durable reconstruction"
                )
            evidence = committed or recovered
            if evidence is None:
                continue
            if record_id not in active_by_id:
                raise RequestEvidenceIntegrityError(
                    "Resource evidence message is not on the selected transcript path"
                )
            role, text = _message_signature(message)
            if role != "user" or text != evidence.model_visible_text:
                raise RequestEvidenceIntegrityError(
                    "Resource evidence no longer matches its transcript message"
                )
            selected.append((index, record_id, evidence))

        if not selected:
            return None
        transcript_shape = tuple(
            _message_signature(message) for _record_id, message in bindings
        )
        logical_shape = tuple(
            _message_signature(message) for message in preparation.context.messages
        )
        transcript_positions = _signature_positions(transcript_shape)
        logical_positions = _signature_positions(logical_shape)
        projected: list[tuple[int, str, PreparedResourceEvidence]] = []
        for source_index, record_id, evidence in selected:
            signature = transcript_shape[source_index]
            source_matches = transcript_positions[signature]
            target_matches = logical_positions.get(signature, ())
            if not target_matches:
                continue
            if len(source_matches) != len(target_matches):
                raise RequestEvidenceIntegrityError(
                    "final logical messages retain an ambiguous subset of duplicate "
                    "Resource evidence messages"
                )
            occurrence = source_matches.index(source_index)
            projected.append((target_matches[occurrence], record_id, evidence))
        if not projected:
            return None
        projected.sort(key=lambda item: item[0])
        return {
            "contextComplete": transcript_shape == logical_shape,
            "schemaId": RESOURCE_EVIDENCE_SCHEMA_ID,
            "schemaVersion": RESOURCE_EVIDENCE_SCHEMA_VERSION,
            "messages": [
                evidence.to_message_payload(
                    message_record_id=record_id,
                    message_index=index,
                )
                for index, record_id, evidence in projected
            ],
        }

    def _pending_index(
        self,
        message: object,
        *,
        role: str,
        text: str,
    ) -> int | None:
        for index, pending in enumerate(self._pending):
            if pending.message is message:
                return index
        matches = [
            index
            for index, pending in enumerate(self._pending)
            if pending.role == role and pending.text == text
        ]
        if len(matches) > 1:
            raise RequestEvidenceIntegrityError(
                "multiple uncommitted messages match the same Resource evidence text"
            )
        return matches[0] if matches else None

    def _recover_from_snapshots(
        self,
        active_records: tuple[AgentTranscriptRecord, ...],
        *,
        active_by_id: Mapping[str, AgentTranscriptRecord],
    ) -> None:
        for record in reversed(active_records):
            snapshot = record.payload
            if not isinstance(snapshot, ModelInputSnapshot | ModelInputSnapshotV2):
                continue
            snapshot_id = snapshot.snapshot_id
            if snapshot_id in self._scanned_snapshot_ids:
                break
            rebuilt = self._rebuild_model_input(snapshot_id)
            component = rebuilt.logical_input.get(RESOURCE_EVIDENCE_COMPONENT)
            context_complete = False
            if component is not None:
                context_complete = self._recover_component(
                    component,
                    active_by_id=active_by_id,
                )
            self._scanned_snapshot_ids.add(snapshot_id)
            if context_complete:
                break

    def _recover_component(
        self,
        component: object,
        *,
        active_by_id: Mapping[str, AgentTranscriptRecord],
    ) -> bool:
        payload = require_json_mapping(component, name="Model Input resource evidence")
        if payload.get("schemaId") != RESOURCE_EVIDENCE_SCHEMA_ID:
            raise RequestEvidenceIntegrityError(
                "Model Input Resource evidence has an unsupported schema id"
            )
        if payload.get("schemaVersion") != RESOURCE_EVIDENCE_SCHEMA_VERSION:
            raise RequestEvidenceIntegrityError(
                "Model Input Resource evidence has an unsupported schema version"
            )
        context_complete = payload.get("contextComplete")
        if not isinstance(context_complete, bool):
            raise RequestEvidenceIntegrityError(
                "Model Input Resource evidence context completeness is invalid"
            )
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise RequestEvidenceIntegrityError(
                "Model Input Resource evidence messages must be an array"
            )
        for index, value in enumerate(messages):
            message = require_json_mapping(
                value,
                name=f"Model Input resource evidence message[{index}]",
            )
            record_id = message.get("messageRecordId")
            model_visible_text = message.get("modelVisibleText")
            text_digest = message.get("messageTextDigest")
            skills = message.get("skills")
            if not isinstance(record_id, str) or not record_id:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence has no message record id"
                )
            if not isinstance(model_visible_text, str) or not model_visible_text:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence has no model-visible text"
                )
            if text_digest != _message_text_digest(model_visible_text):
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence message digest is invalid"
                )
            if not isinstance(skills, list) or not skills:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence has no loaded Skills"
                )
            if record_id not in active_by_id:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence names a foreign transcript message"
                )
            evidence = PreparedResourceEvidence(
                model_visible_text=model_visible_text,
                skills=tuple(
                    _validated_skill_payload(skill, index=skill_index)
                    for skill_index, skill in enumerate(skills)
                ),
            )
            existing = self._recovered.get(record_id)
            if existing is not None and existing != evidence:
                raise RequestEvidenceIntegrityError(
                    "durable Model Inputs disagree about one message's Resource evidence"
                )
            self._recovered[record_id] = evidence
        return context_complete

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("Session request evidence runtime is closed")


def _loaded_skill_payload(loaded: object) -> dict[str, JSONValue]:
    if not isinstance(loaded, LoadedSkillBody):
        raise TypeError("request evidence requires an exact loaded Skill body")
    summary = loaded.summary
    receipt = loaded.receipt
    if (
        summary.expected_content_digest != receipt.content_digest
        or summary.expected_content_length != receipt.content_length
    ):
        raise RequestEvidenceIntegrityError(
            "loaded Skill expected and observed content identity diverged"
        )
    return require_json_mapping(
        {
            "activationPolicyFingerprint": summary.activation_policy_fingerprint,
            "candidateFingerprint": summary.candidate_fingerprint,
            "catalogGeneration": summary.catalog_generation,
            "catalogSnapshotFingerprint": summary.catalog_snapshot_fingerprint,
            "expectedContentDigest": summary.expected_content_digest,
            "expectedContentLength": summary.expected_content_length,
            "mediaType": summary.media_type,
            "observedContentDigest": receipt.content_digest,
            "observedContentLength": receipt.content_length,
            "resourceIdentity": summary.identity.to_payload(),
            "schemaId": receipt.schema_id,
            "schemaVersion": receipt.schema_version,
            "sourceGeneration": receipt.source_generation_ref.to_payload(),
        },
        name="loaded Skill Model Input evidence",
    )


def _validated_skill_payload(value: object, *, index: int) -> dict[str, JSONValue]:
    payload = require_json_mapping(
        value,
        name=f"Model Input resource evidence skill[{index}]",
    )
    required_strings = (
        "activationPolicyFingerprint",
        "candidateFingerprint",
        "catalogSnapshotFingerprint",
        "expectedContentDigest",
        "mediaType",
        "observedContentDigest",
        "schemaId",
    )
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required_strings):
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence Skill string facts are invalid"
        )
    required_positive = ("catalogGeneration", "schemaVersion")
    if any(
        isinstance(payload.get(key), bool)
        or not isinstance(payload.get(key), int)
        or cast(int, payload[key]) < 1
        for key in required_positive
    ):
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence Skill generation facts are invalid"
        )
    required_lengths = ("expectedContentLength", "observedContentLength")
    if any(
        isinstance(payload.get(key), bool)
        or not isinstance(payload.get(key), int)
        or cast(int, payload[key]) < 0
        for key in required_lengths
    ):
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence Skill length facts are invalid"
        )
    if (
        payload["expectedContentDigest"] != payload["observedContentDigest"]
        or payload["expectedContentLength"] != payload["observedContentLength"]
    ):
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence Skill content facts diverge"
        )
    for key in ("resourceIdentity", "sourceGeneration"):
        if not isinstance(payload.get(key), dict):
            raise RequestEvidenceIntegrityError(
                f"Model Input Resource evidence Skill {key} is invalid"
            )
    return payload


def _message_signature(message: object) -> tuple[str, str]:
    role = getattr(message, "role", None)
    if role == "application":
        role = "user"
    if not isinstance(role, str):
        role = ""
    return role, _message_text(message)


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        part_type = (
            part.get("type") if isinstance(part, Mapping) else getattr(part, "type", None)
        )
        if part_type != "text":
            continue
        text = (
            part.get("text") if isinstance(part, Mapping) else getattr(part, "text", None)
        )
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _message_text_digest(text: str) -> str:
    return hashlib.sha256(_MESSAGE_TEXT_DIGEST_DOMAIN + text.encode("utf-8")).hexdigest()


def _signature_positions(
    signatures: tuple[tuple[str, str], ...],
) -> dict[tuple[str, str], tuple[int, ...]]:
    positions: dict[tuple[str, str], list[int]] = {}
    for index, signature in enumerate(signatures):
        positions.setdefault(signature, []).append(index)
    return {signature: tuple(values) for signature, values in positions.items()}


__all__ = [
    "PreparedResourceEvidence",
    "RequestEvidenceIntegrityError",
    "RequestEvidenceRuntimePort",
    "RESOURCE_EVIDENCE_COMPONENT",
    "RESOURCE_EVIDENCE_SCHEMA_ID",
    "RESOURCE_EVIDENCE_SCHEMA_VERSION",
    "SessionRequestEvidenceRuntime",
]
