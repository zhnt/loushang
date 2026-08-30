"""Request-local Resource evidence bound to durable Model Input messages."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Protocol, cast

from loushang.agent import ModelCallPreparation
from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.capabilities.prompt_preflight import PromptPreflightResult
from loushang.harness.resources._skill_catalog_consumer import LoadedSkillBody
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from loushang.harness.transcript.model_input import RebuiltModelInput
from loushang.harness.transcript.model_input_types import ModelInputSnapshot
from loushang.harness.transcript.model_input_v2_types import ModelInputSnapshotV2
from loushang.harness.transcript.types import AgentTranscriptRecord

RESOURCE_EVIDENCE_COMPONENT = "resource_evidence"
RESOURCE_EVIDENCE_SCHEMA_ID = "loushang.model-input.resource-evidence"
RESOURCE_EVIDENCE_SCHEMA_VERSION = 1
RESOURCE_EVIDENCE_METADATA_KEY = "loushang.request.resource_evidence"
_MESSAGE_TEXT_DIGEST_DOMAIN = b"loushang.model-input.message-text/v1\0"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class RequestEvidenceIntegrityError(RuntimeError):
    """Request evidence cannot be associated without guessing."""


class _FrozenJSONMapping(Mapping[str, JSONValue]):
    """Own a deep JSON copy and never expose a mutable nested value."""

    __slots__ = ("_data",)

    def __init__(self, value: Mapping[str, object], *, name: str) -> None:
        self._data = require_json_mapping(dict(value), name=name)

    def __getitem__(self, key: str) -> JSONValue:
        return cast(JSONValue, deepcopy(self._data[key]))

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def to_payload(self) -> dict[str, JSONValue]:
        return cast(dict[str, JSONValue], deepcopy(self._data))

    def __repr__(self) -> str:
        return repr(self._data)


@dataclass(frozen=True, slots=True)
class PreparedResourceEvidence:
    """Immutable loaded-Resource evidence before a message has a record id."""

    model_visible_text: str
    skills: tuple[Mapping[str, JSONValue], ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.model_visible_text, str) or not self.model_visible_text:
            raise ValueError("Resource evidence model-visible text must be non-empty")
        if not self.skills:
            raise ValueError("Resource evidence must contain a loaded Skill")
        frozen_skills = tuple(
            _FrozenJSONMapping(
                _validated_skill_payload(skill, index=index),
                name=f"resource evidence skill[{index}]",
            )
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
        if (
            isinstance(message_index, bool)
            or not isinstance(message_index, int)
            or message_index < 0
        ):
            raise ValueError("Resource evidence message index must be non-negative")
        return {
            "messageIndex": message_index,
            "messageRecordId": message_record_id,
            "messageTextDigest": self.message_text_digest,
            "modelVisibleText": self.model_visible_text,
            "skills": [_copy_frozen_mapping(skill) for skill in self.skills],
        }

    def to_message_metadata(self) -> dict[str, JSONValue]:
        """Return the durable evidence anchor committed with the user message."""

        return {
            "schemaId": RESOURCE_EVIDENCE_SCHEMA_ID,
            "schemaVersion": RESOURCE_EVIDENCE_SCHEMA_VERSION,
            "messageTextDigest": self.message_text_digest,
            "modelVisibleText": self.model_visible_text,
            "skills": [_copy_frozen_mapping(skill) for skill in self.skills],
        }


class RequestEvidenceRuntimePort(Protocol):
    """Narrow input/event lifecycle used by the common Session runtime."""

    def prepare(self, result: object) -> object | None: ...

    def bind(
        self,
        message: object,
        evidence: object,
        *,
        owner: object,
        allow_signature_fallback: bool = False,
    ) -> None: ...

    def prepare_message_commit(
        self,
        message: object,
    ) -> Mapping[str, JSONValue] | None: ...

    def commit_message(self, message: object, record_id: str) -> bool: ...

    def discard_owner(self, owner: object) -> None: ...

    def close(self) -> None: ...


ContextMessageBindings = Callable[..., tuple[tuple[str, object], ...]]
ActiveRecordsProvider = Callable[[], Sequence[AgentTranscriptRecord]]
ModelInputRebuilder = Callable[[str], RebuiltModelInput]


@dataclass(slots=True)
class _PendingEvidence:
    message: object
    role: str
    text: str
    evidence: PreparedResourceEvidence
    owner: object
    allow_signature_fallback: bool


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
        self._scanned_anchor_record_ids: set[str] = set()
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

    def bind(
        self,
        message: object,
        evidence: object,
        *,
        owner: object,
        allow_signature_fallback: bool = False,
    ) -> None:
        self._require_open()
        if not isinstance(evidence, PreparedResourceEvidence):
            raise TypeError("request evidence binding received an invalid value")
        if not isinstance(allow_signature_fallback, bool):
            raise TypeError("request evidence fallback policy must be a boolean")
        role, text = _message_signature(message, application_as_user=False)
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
                allow_signature_fallback=allow_signature_fallback,
            )
        )

    def prepare_message_commit(
        self,
        message: object,
    ) -> Mapping[str, JSONValue] | None:
        """Pin one pending binding and return metadata for its atomic commit."""

        self._require_open()
        role, text = _message_signature(message, application_as_user=False)
        pending_index = self._pending_index(message, role=role, text=text)
        if pending_index is None:
            return None
        pending = self._pending[pending_index]
        pending.message = message
        pending.role = role
        pending.text = text
        pending.allow_signature_fallback = False
        return {
            RESOURCE_EVIDENCE_METADATA_KEY: pending.evidence.to_message_metadata()
        }

    def commit_message(self, message: object, record_id: str) -> bool:
        self._require_open()
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("request evidence requires a transcript record id")
        role, text = _message_signature(message, application_as_user=False)
        existing = self._committed.get(record_id)
        if existing is not None:
            if role != "user" or text != existing.model_visible_text:
                raise RequestEvidenceIntegrityError(
                    "a retried transcript record conflicts with its Resource evidence"
                )
            return True
        pending_index = self._pending_index(message, role=role, text=text)
        if pending_index is None:
            return False
        pending = self._pending[pending_index]
        self._pending.pop(pending_index)
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
        self._scanned_anchor_record_ids.clear()
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
        if len(active_by_id) != len(active_records):
            raise RequestEvidenceIntegrityError(
                "selected transcript path contains duplicate record ids"
            )
        self._recover_from_message_anchors(active_records)
        self._recover_from_snapshots(active_records)

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
            if pending.allow_signature_fallback
            and pending.role == role
            and pending.text == text
        ]
        if len(matches) > 1:
            raise RequestEvidenceIntegrityError(
                "multiple uncommitted messages match the same Resource evidence text"
            )
        return matches[0] if matches else None

    def _recover_from_message_anchors(
        self,
        active_records: tuple[AgentTranscriptRecord, ...],
    ) -> None:
        for record in active_records:
            if record.record_id in self._scanned_anchor_record_ids:
                continue
            component = record.metadata.get(RESOURCE_EVIDENCE_METADATA_KEY)
            if component is None:
                self._scanned_anchor_record_ids.add(record.record_id)
                continue
            if record.kind != AGENT_MESSAGE_KIND:
                raise RequestEvidenceIntegrityError(
                    "Resource evidence metadata is attached to a non-message record"
                )
            role, text = _message_signature(
                record.payload,
                application_as_user=False,
            )
            if role != "user":
                raise RequestEvidenceIntegrityError(
                    "Resource evidence metadata is attached to a non-user message"
                )
            evidence = _validated_message_metadata(component)
            if evidence.model_visible_text != text:
                raise RequestEvidenceIntegrityError(
                    "Resource evidence metadata does not match its transcript message"
                )
            self._merge_recovered({record.record_id: evidence})
            self._scanned_anchor_record_ids.add(record.record_id)

    def _recover_from_snapshots(
        self,
        active_records: tuple[AgentTranscriptRecord, ...],
    ) -> None:
        for record_index in range(len(active_records) - 1, -1, -1):
            record = active_records[record_index]
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
                context_complete, recovered = self._recover_component(
                    component,
                    snapshot_records=active_records[:record_index],
                    logical_messages=rebuilt.logical_input.get("messages"),
                )
                self._merge_recovered(recovered)
            self._scanned_snapshot_ids.add(snapshot_id)
            if context_complete:
                break

    def _recover_component(
        self,
        component: object,
        *,
        snapshot_records: tuple[AgentTranscriptRecord, ...],
        logical_messages: object,
    ) -> tuple[bool, dict[str, PreparedResourceEvidence]]:
        payload = require_json_mapping(component, name="Model Input resource evidence")
        _require_exact_keys(
            payload,
            {
                "contextComplete",
                "messages",
                "schemaId",
                "schemaVersion",
            },
            name="Model Input Resource evidence",
        )
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
        if not isinstance(messages, list) or not messages:
            raise RequestEvidenceIntegrityError(
                "Model Input Resource evidence messages must be a non-empty array"
            )
        if not isinstance(logical_messages, list):
            raise RequestEvidenceIntegrityError(
                "Model Input Resource evidence has no logical message array"
            )
        snapshot_bindings = tuple(
            self._get_context_message_bindings(snapshot_records)
        )
        transcript_shape = tuple(
            _message_signature(message) for _record_id, message in snapshot_bindings
        )
        logical_shape = tuple(_message_signature(message) for message in logical_messages)
        if context_complete and transcript_shape != logical_shape:
            raise RequestEvidenceIntegrityError(
                "Model Input Resource evidence falsely claims complete context"
            )
        binding_positions = {
            record_id: index
            for index, (record_id, _message) in enumerate(snapshot_bindings)
        }
        if len(binding_positions) != len(snapshot_bindings):
            raise RequestEvidenceIntegrityError(
                "snapshot context contains duplicate message record ids"
            )
        transcript_positions = _signature_positions(transcript_shape)
        logical_positions = _signature_positions(logical_shape)
        snapshot_by_id = {record.record_id: record for record in snapshot_records}
        recovered: dict[str, PreparedResourceEvidence] = {}
        message_indices: set[int] = set()
        for index, value in enumerate(messages):
            message = require_json_mapping(
                value,
                name=f"Model Input resource evidence message[{index}]",
            )
            _require_exact_keys(
                message,
                {
                    "messageIndex",
                    "messageRecordId",
                    "messageTextDigest",
                    "modelVisibleText",
                    "skills",
                },
                name=f"Model Input Resource evidence message[{index}]",
            )
            message_index = message.get("messageIndex")
            record_id = message.get("messageRecordId")
            model_visible_text = message.get("modelVisibleText")
            text_digest = message.get("messageTextDigest")
            skills = message.get("skills")
            if not isinstance(record_id, str) or not record_id:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence has no message record id"
                )
            if (
                isinstance(message_index, bool)
                or not isinstance(message_index, int)
                or message_index < 0
                or message_index >= len(logical_messages)
            ):
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence message index is invalid"
                )
            if message_index in message_indices:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence repeats a message index"
                )
            message_indices.add(message_index)
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
            if record_id in recovered:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence repeats a transcript message"
                )
            record = snapshot_by_id.get(record_id)
            if record is None:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence names a non-ancestral transcript message"
                )
            if record.kind != AGENT_MESSAGE_KIND:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence names a non-message record"
                )
            record_role, record_text = _message_signature(
                record.payload,
                application_as_user=False,
            )
            if record_role != "user" or record_text != model_visible_text:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence does not match its transcript record"
                )
            source_index = binding_positions.get(record_id)
            if source_index is None:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence message is outside snapshot context"
                )
            signature = transcript_shape[source_index]
            source_matches = transcript_positions[signature]
            target_matches = logical_positions.get(signature, ())
            if len(source_matches) != len(target_matches):
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence snapshot has ambiguous duplicates"
                )
            occurrence = source_matches.index(source_index)
            if target_matches[occurrence] != message_index:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence message index changed"
                )
            logical_role, logical_text = logical_shape[message_index]
            if logical_role != "user" or logical_text != model_visible_text:
                raise RequestEvidenceIntegrityError(
                    "Model Input Resource evidence does not match its logical message"
                )
            evidence = PreparedResourceEvidence(
                model_visible_text=model_visible_text,
                skills=tuple(
                    _validated_skill_payload(skill, index=skill_index)
                    for skill_index, skill in enumerate(skills)
                ),
            )
            recovered[record_id] = evidence
        return context_complete, recovered

    def _merge_recovered(
        self,
        recovered: Mapping[str, PreparedResourceEvidence],
    ) -> None:
        for record_id, evidence in recovered.items():
            existing = self._recovered.get(record_id)
            if existing is not None and existing != evidence:
                raise RequestEvidenceIntegrityError(
                    "durable evidence disagrees about one transcript message"
                )
        self._recovered.update(recovered)

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
    _require_exact_keys(
        payload,
        {
            "activationPolicyFingerprint",
            "candidateFingerprint",
            "catalogGeneration",
            "catalogSnapshotFingerprint",
            "expectedContentDigest",
            "expectedContentLength",
            "mediaType",
            "observedContentDigest",
            "observedContentLength",
            "resourceIdentity",
            "schemaId",
            "schemaVersion",
            "sourceGeneration",
        },
        name=f"Model Input Resource evidence Skill[{index}]",
    )
    required_digests = (
        "activationPolicyFingerprint",
        "candidateFingerprint",
        "catalogSnapshotFingerprint",
        "expectedContentDigest",
        "observedContentDigest",
    )
    if any(not _is_sha256(payload.get(key)) for key in required_digests):
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence Skill digest facts are invalid"
        )
    for key in ("mediaType", "schemaId"):
        _require_non_empty_string(
            payload.get(key),
            name=f"Model Input Resource evidence Skill {key}",
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
    identity = _validated_resource_identity(payload.get("resourceIdentity"))
    if (
        identity["schemaId"] != payload["schemaId"]
        or identity["schemaVersion"] != payload["schemaVersion"]
    ):
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence Skill schema facts diverge"
        )
    payload["resourceIdentity"] = identity
    payload["sourceGeneration"] = _validated_source_generation(
        payload.get("sourceGeneration")
    )
    return payload


def _validated_message_metadata(value: object) -> PreparedResourceEvidence:
    payload = require_json_mapping(value, name="transcript Resource evidence metadata")
    _require_exact_keys(
        payload,
        {
            "messageTextDigest",
            "modelVisibleText",
            "schemaId",
            "schemaVersion",
            "skills",
        },
        name="transcript Resource evidence metadata",
    )
    if payload.get("schemaId") != RESOURCE_EVIDENCE_SCHEMA_ID:
        raise RequestEvidenceIntegrityError(
            "transcript Resource evidence metadata has an unsupported schema id"
        )
    if payload.get("schemaVersion") != RESOURCE_EVIDENCE_SCHEMA_VERSION:
        raise RequestEvidenceIntegrityError(
            "transcript Resource evidence metadata has an unsupported schema version"
        )
    text = payload.get("modelVisibleText")
    if not isinstance(text, str) or not text:
        raise RequestEvidenceIntegrityError(
            "transcript Resource evidence metadata has no model-visible text"
        )
    if payload.get("messageTextDigest") != _message_text_digest(text):
        raise RequestEvidenceIntegrityError(
            "transcript Resource evidence metadata message digest is invalid"
        )
    skills = payload.get("skills")
    if not isinstance(skills, list) or not skills:
        raise RequestEvidenceIntegrityError(
            "transcript Resource evidence metadata has no loaded Skills"
        )
    return PreparedResourceEvidence(
        model_visible_text=text,
        skills=tuple(
            _validated_skill_payload(skill, index=index)
            for index, skill in enumerate(skills)
        ),
    )


def _validated_resource_identity(value: object) -> dict[str, JSONValue]:
    payload = require_json_mapping(
        value,
        name="Model Input Resource evidence identity",
    )
    _require_exact_keys(
        payload,
        {"publicId", "resourceKind", "schemaId", "schemaVersion"},
        name="Model Input Resource evidence identity",
    )
    for key in ("publicId", "schemaId"):
        _require_non_empty_string(
            payload.get(key),
            name=f"Model Input Resource evidence identity {key}",
        )
    if payload.get("resourceKind") != "skill":
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence identity does not name a Skill"
        )
    schema_version = payload.get("schemaVersion")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version < 1
    ):
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence identity schema version is invalid"
        )
    return payload


def _validated_source_generation(value: object) -> dict[str, JSONValue]:
    payload = require_json_mapping(
        value,
        name="Model Input Resource evidence source generation",
    )
    _require_exact_keys(
        payload,
        {
            "generation",
            "producer",
            "productId",
            "sourceId",
            "sourcePolicyFingerprint",
        },
        name="Model Input Resource evidence source generation",
    )
    for key in ("generation", "productId", "sourceId"):
        _require_non_empty_string(
            payload.get(key),
            name=f"Model Input Resource evidence source generation {key}",
        )
    if not _is_sha256(payload.get("sourcePolicyFingerprint")):
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence source policy fingerprint is invalid"
        )
    producer = require_json_mapping(
        payload.get("producer"),
        name="Model Input Resource evidence source producer",
    )
    producer_type = producer.get("type")
    if producer_type == "resource_component":
        _require_exact_keys(
            producer,
            {
                "bindingFingerprint",
                "componentAdmissionFingerprint",
                "componentCandidateFingerprint",
                "componentContributionId",
                "packageContentDigest",
                "pluginInstanceRevisionRef",
                "type",
            },
            name="Model Input Resource evidence component producer",
        )
        for key in (
            "bindingFingerprint",
            "componentAdmissionFingerprint",
            "componentCandidateFingerprint",
            "packageContentDigest",
        ):
            if not _is_sha256(producer.get(key)):
                raise RequestEvidenceIntegrityError(
                    f"Model Input Resource evidence producer {key} is invalid"
                )
        for key in ("componentContributionId", "pluginInstanceRevisionRef"):
            _require_non_empty_string(
                producer.get(key),
                name=f"Model Input Resource evidence producer {key}",
            )
    elif producer_type == "extension_owner":
        _require_exact_keys(
            producer,
            {
                "extensionGeneration",
                "extensionOwnerFingerprint",
                "extensionSetFingerprint",
                "runtimeId",
                "type",
            },
            name="Model Input Resource evidence Extension producer",
        )
        if producer.get("extensionGeneration") != payload["generation"]:
            raise RequestEvidenceIntegrityError(
                "Model Input Resource evidence Extension generation diverges"
            )
        _require_non_empty_string(
            producer.get("runtimeId"),
            name="Model Input Resource evidence Extension runtime id",
        )
        for key in ("extensionOwnerFingerprint", "extensionSetFingerprint"):
            if not _is_sha256(producer.get(key)):
                raise RequestEvidenceIntegrityError(
                    f"Model Input Resource evidence producer {key} is invalid"
                )
    else:
        raise RequestEvidenceIntegrityError(
            "Model Input Resource evidence source producer type is invalid"
        )
    payload["producer"] = producer
    return payload


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    name: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        raise RequestEvidenceIntegrityError(
            f"{name} fields are invalid: expected {sorted(expected)}, got {sorted(actual)}"
        )


def _require_non_empty_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RequestEvidenceIntegrityError(f"{name} must be non-empty text")
    return value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _copy_frozen_mapping(value: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    if isinstance(value, _FrozenJSONMapping):
        return value.to_payload()
    return require_json_mapping(dict(value), name="Resource evidence Skill")


def _message_signature(
    message: object,
    *,
    application_as_user: bool = True,
) -> tuple[str, str]:
    role = (
        message.get("role")
        if isinstance(message, Mapping)
        else getattr(message, "role", None)
    )
    if application_as_user and role == "application":
        role = "user"
    if not isinstance(role, str):
        role = ""
    return role, _message_text(message)


def _message_text(message: object) -> str:
    content = (
        message.get("content", "")
        if isinstance(message, Mapping)
        else getattr(message, "content", "")
    )
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
    "RESOURCE_EVIDENCE_METADATA_KEY",
    "RESOURCE_EVIDENCE_SCHEMA_ID",
    "RESOURCE_EVIDENCE_SCHEMA_VERSION",
    "SessionRequestEvidenceRuntime",
]
