"""Transcript lifecycle integration for durable Session blob references."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

from loushang.ai.types import AssistantMessage, ToolResultMessage, UserMessage
from loushang.harness.artifacts import (
    SessionBlobHealth,
    SessionBlobPublication,
    SessionBlobRef,
    SessionBlobStore,
    resolve_session_blob_data_root,
    session_blob_authority_id,
)
from loushang.harness.conversation import CommandExecutionRecord
from loushang.harness.transcript.types import (
    AgentTranscriptRecord,
    ApplicationMessage,
    DecodedAgentTranscriptPayload,
    SessionImagePart,
)


class SessionBlobOwnershipError(ValueError):
    """A transcript tried to exercise another Session's blob authority."""


def collect_agent_transcript_session_blobs(
    records: Sequence[AgentTranscriptRecord],
    *,
    expected_session_id: str | None = None,
) -> tuple[SessionBlobRef, ...]:
    """Collect unique durable blob references in stable transcript order."""

    selected: list[SessionBlobRef] = []
    seen: set[SessionBlobRef] = set()
    for record in records:
        for reference in _payload_session_blobs(record.payload):
            if (
                expected_session_id is not None
                and reference.session_id
                != session_blob_authority_id(expected_session_id)
            ):
                raise SessionBlobOwnershipError(
                    "transcript blob reference belongs to another Session authority"
                )
            if reference not in seen:
                selected.append(reference)
                seen.add(reference)
    return tuple(selected)


def inspect_agent_transcript_session_blobs(
    *,
    session_dir: str | Path,
    session_id: str,
    records: Sequence[AgentTranscriptRecord],
    verify_content: bool = True,
    max_references: int | None = None,
) -> tuple[SessionBlobHealth, ...]:
    """Return availability diagnostics while leaving transcript resume usable."""

    authority_id = session_blob_authority_id(session_id)
    references = collect_agent_transcript_session_blobs(
        records,
        expected_session_id=authority_id,
    )
    if max_references is not None and len(references) > max_references:
        raise ValueError("session blob preview reference limit exceeded")
    if not references:
        return ()
    data_root = resolve_session_blob_data_root(session_dir)
    try:
        store = SessionBlobStore(data_root, authority_id)
        return (
            store.inspect(references)
            if verify_content
            else store.inspect_metadata(references)
        )
    except (OSError, ValueError) as error:
        return tuple(
            SessionBlobHealth(blob, "corrupt", str(error)) for blob in references
        )


def clone_agent_transcript_session_blobs(
    records: Sequence[AgentTranscriptRecord],
    *,
    source_session_dir: str | Path,
    source_session_id: str,
    target_session_dir: str | Path,
    target_session_id: str,
) -> tuple[tuple[AgentTranscriptRecord, ...], SessionBlobPublication | None]:
    """Clone selected durable bytes and rewrite refs to target ownership.

    The returned publication is a compare-and-delete rollback handle. It never
    removes an authority changed by another writer.
    """

    source_authority_id = session_blob_authority_id(source_session_id)
    references = collect_agent_transcript_session_blobs(
        records,
        expected_session_id=source_authority_id,
    )
    if not references:
        return tuple(records), None
    source_data_root = resolve_session_blob_data_root(source_session_dir)
    target_data_root = resolve_session_blob_data_root(target_session_dir)
    target = SessionBlobStore(target_data_root, target_session_id)
    replacements: dict[SessionBlobRef, SessionBlobRef] = {}
    prepared: list[tuple[SessionBlobRef, bytes]] = []
    ordered_sources: list[SessionBlobRef] = []
    source = SessionBlobStore(source_data_root, source_authority_id)
    for source_ref in references:
        ordered_sources.append(source_ref)
        prepared.append((source_ref, source.read_bytes(source_ref)))
    publication = target.import_blobs(
        prepared,
        require_new_authority=True,
    )
    replacements.update(
        zip(ordered_sources, publication.references, strict=True)
    )
    return replace_agent_transcript_session_blobs(records, replacements), publication


def delete_agent_transcript_session_blobs(
    *,
    session_dir: str | Path,
    session_id: str,
) -> bool:
    """Remove the complete durable blob authority owned by one session."""

    return SessionBlobStore(
        resolve_session_blob_data_root(session_dir),
        session_id,
    ).delete()


def replace_agent_transcript_session_blobs(
    records: Sequence[AgentTranscriptRecord],
    replacements: dict[SessionBlobRef, SessionBlobRef],
) -> tuple[AgentTranscriptRecord, ...]:
    result: list[AgentTranscriptRecord] = []
    for record in records:
        payload = _replace_payload_session_blobs(record.payload, replacements)
        if payload is record.payload:
            result.append(record)
            continue
        result.append(
            replace(record, payload=cast(DecodedAgentTranscriptPayload, payload))
        )
    return tuple(result)


def _payload_session_blobs(payload: object) -> tuple[SessionBlobRef, ...]:
    references: list[SessionBlobRef] = []
    if isinstance(payload, CommandExecutionRecord):
        references.extend(payload.output_blobs)
    if isinstance(
        payload,
        UserMessage | AssistantMessage | ToolResultMessage | ApplicationMessage,
    ):
        content = payload.content
        if isinstance(content, list):
            references.extend(
                part.blob for part in content if isinstance(part, SessionImagePart)
            )
    if isinstance(payload, ToolResultMessage) and isinstance(payload.details, Mapping):
        for key in ("stdout_blob", "stderr_blob"):
            reference = _manifest_session_blob(payload.details.get(key))
            if reference is not None:
                references.append(reference)
    return tuple(references)


def _replace_payload_session_blobs(
    payload: object,
    replacements: Mapping[SessionBlobRef, SessionBlobRef],
) -> object:
    if isinstance(payload, CommandExecutionRecord):
        updates = {
            name: replacements.get(reference, reference)
            for name in ("full_output_blob", "stdout_blob", "stderr_blob")
            if (reference := getattr(payload, name)) is not None
        }
        if any(getattr(payload, name) != value for name, value in updates.items()):
            payload = replace(payload, **updates)
    if not isinstance(
        payload,
        UserMessage | AssistantMessage | ToolResultMessage | ApplicationMessage,
    ):
        return payload
    content = payload.content
    if isinstance(content, list):
        replaced_content = [
            SessionImagePart(
                type="image",
                blob=replacements.get(part.blob, part.blob),
            )
            if isinstance(part, SessionImagePart)
            else part
            for part in content
        ]
        if replaced_content != content:
            payload = replace(payload, content=replaced_content)  # type: ignore[arg-type]
    if isinstance(payload, ToolResultMessage) and isinstance(payload.details, Mapping):
        details = dict(payload.details)
        changed = False
        for key in ("stdout_blob", "stderr_blob"):
            reference = _manifest_session_blob(details.get(key))
            if reference is None or reference not in replacements:
                continue
            details[key] = replacements[reference].manifest_entry()
            changed = True
        if changed:
            payload = replace(payload, details=details)
    return payload


def _manifest_session_blob(value: object) -> SessionBlobRef | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return SessionBlobRef.from_manifest_entry(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "clone_agent_transcript_session_blobs",
    "collect_agent_transcript_session_blobs",
    "delete_agent_transcript_session_blobs",
    "inspect_agent_transcript_session_blobs",
    "replace_agent_transcript_session_blobs",
    "SessionBlobOwnershipError",
]
