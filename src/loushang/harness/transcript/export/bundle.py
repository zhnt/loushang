"""Portable one-file transcript bundle with verified Session blobs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from uuid import uuid4

from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.artifacts import (
    SessionBlobPolicy,
    SessionBlobPublication,
    SessionBlobRef,
    SessionBlobStore,
    require_portable_artifact_id,
    resolve_session_blob_data_root,
    session_blob_authority_id,
)
from loushang.harness.artifacts.store import (
    ArtifactSourceRejected,
    ArtifactStoreQuotaExceeded,
    _is_reparse_point,
    _publish_file_exclusive,
    _sync_directory,
    _unlink_owned_file,
    _write_new_private_file,
)
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationJsonlHeaderCodec,
    ConversationJsonlRecordCodec,
    ConversationKey,
    ConversationSnapshot,
    ConversationStore,
)
from loushang.harness.transcript.codecs import (
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.export.jsonl import (
    linearize_agent_transcript_branch,
)
from loushang.harness.transcript.session_artifacts import (
    SessionBlobOwnershipError,
    collect_agent_transcript_session_blobs,
    replace_agent_transcript_session_blobs,
)
from loushang.harness.transcript.types import AgentTranscriptRecord

_BUNDLE_SCHEMA_VERSION = 1
_BUNDLE_MANIFEST = "bundle.json"
_TRANSCRIPT_MEMBER = "session.jsonl"
_OBJECT_PREFIX = "objects/"
_PORTABLE_UTC_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z"
)

SessionBlobRedactor = Callable[[SessionBlobRef, bytes], bytes]
DEFAULT_TRANSCRIPT_BUNDLE_POLICY = SessionBlobPolicy(
    max_blobs=256,
    max_blob_bytes=16 * 1024 * 1024,
    max_total_bytes=64 * 1024 * 1024,
)


class AgentTranscriptBundleError(ValueError):
    """A portable transcript bundle is unsafe, corrupt, or inconsistent."""


@dataclass(frozen=True, slots=True)
class AgentTranscriptBundle:
    header: ConversationHeader
    records: tuple[AgentTranscriptRecord, ...]
    blobs: tuple[tuple[SessionBlobRef, bytes], ...]


@dataclass(frozen=True, slots=True)
class AgentTranscriptBundleImportResult:
    bundle: AgentTranscriptBundle
    key: ConversationKey
    snapshot: ConversationSnapshot[ConversationHeader, AgentTranscriptRecord]


@dataclass(frozen=True, slots=True)
class _DecodedBundleManifest:
    conversation_id: str
    references: tuple[SessionBlobRef, ...]


def export_agent_transcript_bundle(
    header: ConversationHeader,
    branch_entries: Sequence[AgentTranscriptRecord],
    *,
    session_dir: str | Path,
    output_path: str | Path,
    allow_private: bool = False,
    redactor: SessionBlobRedactor | None = None,
    policy: SessionBlobPolicy = DEFAULT_TRANSCRIPT_BUNDLE_POLICY,
) -> str:
    """Atomically export one branch and its referenced bytes without overwrite."""

    records = tuple(linearize_agent_transcript_branch(branch_entries))
    authority_id = session_blob_authority_id(header.conversation_id)
    try:
        references = collect_agent_transcript_session_blobs(
            records,
            expected_session_id=authority_id,
        )
    except SessionBlobOwnershipError as error:
        raise AgentTranscriptBundleError(
            "bundle transcript contains a foreign Session blob"
        ) from error
    if len(references) > policy.max_blobs:
        raise ArtifactStoreQuotaExceeded(
            f"bundle blob count limit is {policy.max_blobs}"
        )
    data_root = resolve_session_blob_data_root(session_dir)
    replacements: dict[SessionBlobRef, SessionBlobRef] = {}
    objects: dict[str, bytes] = {}
    exported_refs: list[SessionBlobRef] = []

    for reference in references:
        source = SessionBlobStore(data_root, authority_id, policy=policy)
        content = source.read_bytes(reference)
        if len(content) > policy.max_blob_bytes:
            raise ArtifactStoreQuotaExceeded(
                f"bundle blob exceeds per-blob limit of {policy.max_blob_bytes} bytes"
            )
        if reference.disclosure == "private" and not allow_private:
            raise AgentTranscriptBundleError(
                "bundle contains private blobs; allow_private=True is required"
            )
        if reference.disclosure == "redact":
            if redactor is None:
                raise AgentTranscriptBundleError(
                    "bundle contains redact blobs; a redactor is required"
                )
            content = bytes(redactor(reference, content))
            digest = hashlib.sha256(content).hexdigest()
            exported = replace(
                reference,
                session_id=authority_id,
                blob_id=digest,
                disclosure="shareable",
                size_bytes=len(content),
                sha256=digest,
                source=f"redacted:{reference.blob_id}"[:128],
            )
        else:
            exported = replace(reference, session_id=authority_id)
        if len(content) > policy.max_blob_bytes:
            raise ArtifactStoreQuotaExceeded(
                f"bundle blob exceeds per-blob limit of {policy.max_blob_bytes} bytes"
            )
        prior = objects.setdefault(exported.blob_id, content)
        if prior != content:
            raise AgentTranscriptBundleError("blob id maps to conflicting content")
        replacements[reference] = exported
        exported_refs.append(exported)
        if sum(len(payload) for payload in objects.values()) > policy.max_total_bytes:
            raise ArtifactStoreQuotaExceeded(
                f"bundle byte limit is {policy.max_total_bytes} bytes"
            )

    portable_records = replace_agent_transcript_session_blobs(records, replacements)
    transcript = _encode_transcript(header, portable_records)
    manifest = _encode_bundle_manifest(header, exported_refs)
    destination = Path(output_path).expanduser().resolve(strict=False)
    _write_bundle(destination, transcript=transcript, manifest=manifest, objects=objects)
    return str(destination)


def read_agent_transcript_bundle(
    path: str | Path,
    *,
    policy: SessionBlobPolicy = DEFAULT_TRANSCRIPT_BUNDLE_POLICY,
) -> AgentTranscriptBundle:
    """Read a bounded bundle and verify every declared object before import."""

    target = Path(path).expanduser().resolve(strict=True)
    metadata = target.lstat()
    if not stat.S_ISREG(metadata.st_mode) or _is_reparse_point(metadata):
        raise AgentTranscriptBundleError("bundle source is not a safe regular file")
    max_archive_bytes = (
        policy.max_total_bytes + 16 * 1024 * 1024 + policy.max_blobs * 1024
    )
    if metadata.st_size > max_archive_bytes:
        raise ArtifactStoreQuotaExceeded("bundle archive exceeds its size limit")
    try:
        with zipfile.ZipFile(target, "r") as archive:
            members = archive.infolist()
            if len(members) > policy.max_blobs + 2:
                raise ArtifactStoreQuotaExceeded("bundle member count exceeds its limit")
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                raise AgentTranscriptBundleError("bundle contains duplicate members")
            if _BUNDLE_MANIFEST not in names or _TRANSCRIPT_MEMBER not in names:
                raise AgentTranscriptBundleError("bundle is missing required members")
            manifest_bytes = _bounded_zip_read(
                archive,
                _BUNDLE_MANIFEST,
                max_bytes=8 * 1024 * 1024,
            )
            manifest = _decode_bundle_manifest(manifest_bytes)
            references = manifest.references
            if len(references) > policy.max_blobs:
                raise ArtifactStoreQuotaExceeded(
                    f"session blob count limit is {policy.max_blobs}"
                )
            unique_sizes: dict[str, int] = {}
            unique_digests: dict[str, str] = {}
            for reference in references:
                if reference.size_bytes > policy.max_blob_bytes:
                    raise ArtifactStoreQuotaExceeded(
                        f"blob exceeds per-blob limit of {policy.max_blob_bytes} bytes"
                    )
                prior_size = unique_sizes.setdefault(
                    reference.blob_id,
                    reference.size_bytes,
                )
                prior_digest = unique_digests.setdefault(
                    reference.blob_id,
                    reference.sha256,
                )
                if (
                    prior_size != reference.size_bytes
                    or prior_digest != reference.sha256
                ):
                    raise AgentTranscriptBundleError(
                        "blob id maps to conflicting integrity metadata"
                    )
            if sum(unique_sizes.values()) > policy.max_total_bytes:
                raise ArtifactStoreQuotaExceeded(
                    f"session blob byte limit is {policy.max_total_bytes} bytes"
                )
            expected = {
                _BUNDLE_MANIFEST,
                _TRANSCRIPT_MEMBER,
                *(_OBJECT_PREFIX + reference.blob_id for reference in references),
            }
            if set(names) != expected:
                raise AgentTranscriptBundleError("bundle member set is inconsistent")
            blobs: list[tuple[SessionBlobRef, bytes]] = []
            content_by_id: dict[str, bytes] = {}
            for reference in references:
                content = content_by_id.get(reference.blob_id)
                if content is None:
                    content = _bounded_zip_read(
                        archive,
                        _OBJECT_PREFIX + reference.blob_id,
                        max_bytes=reference.size_bytes,
                    )
                    if len(content) != reference.size_bytes or hashlib.sha256(
                        content
                    ).hexdigest() != reference.sha256:
                        raise ArtifactSourceRejected(
                            "bundle blob does not match its reference"
                        )
                    content_by_id[reference.blob_id] = content
                if len(content) != reference.size_bytes or hashlib.sha256(
                    content
                ).hexdigest() != reference.sha256:
                    raise ArtifactSourceRejected(
                        "bundle blob does not match each declared reference"
                    )
                blobs.append((reference, content))
            transcript_bytes = _bounded_zip_read(
                archive,
                _TRANSCRIPT_MEMBER,
                max_bytes=64 * 1024 * 1024,
            )
    except (zipfile.BadZipFile, OSError) as error:
        raise AgentTranscriptBundleError("bundle is unreadable") from error

    header, records = _decode_transcript(transcript_bytes)
    _validate_bundle_header(header)
    if header.conversation_id != manifest.conversation_id:
        raise AgentTranscriptBundleError("bundle transcript identity is inconsistent")
    authority_id = session_blob_authority_id(header.conversation_id)
    try:
        transcript_refs = collect_agent_transcript_session_blobs(
            records,
            expected_session_id=authority_id,
        )
    except SessionBlobOwnershipError as error:
        raise AgentTranscriptBundleError(
            "bundle transcript contains a foreign Session blob"
        ) from error
    if set(transcript_refs) != set(references):
        raise AgentTranscriptBundleError("bundle references do not match transcript")
    if any(ref.session_id != authority_id for ref in references):
        raise AgentTranscriptBundleError("bundle blobs are not owned by its session")
    return AgentTranscriptBundle(header=header, records=records, blobs=tuple(blobs))


async def import_agent_transcript_bundle(
    path: str | Path,
    *,
    store: ConversationStore[ConversationHeader, AgentTranscriptRecord],
    key: ConversationKey,
    session_dir: str | Path,
    operation_id: str,
    policy: SessionBlobPolicy = DEFAULT_TRANSCRIPT_BUNDLE_POLICY,
) -> AgentTranscriptBundleImportResult:
    """Create blobs then transcript, rolling blobs back if transcript commit fails."""

    bundle = read_agent_transcript_bundle(path, policy=policy)
    if bundle.header.conversation_id != key.conversation_id:
        raise AgentTranscriptBundleError(
            "import key and bundle conversation id do not match"
        )
    publication: SessionBlobPublication | None = None
    if bundle.blobs:
        blob_store = SessionBlobStore(
            resolve_session_blob_data_root(session_dir),
            key.conversation_id,
            policy=policy,
        )
        publication = blob_store.import_blobs(
            bundle.blobs,
            require_new_authority=True,
        )
    try:
        snapshot = await store.create(
            key,
            bundle.header,
            bundle.records,
            operation_id=operation_id,
        )
    except BaseException as error:
        if publication is not None:
            try:
                publication.rollback()
            except BaseException as cleanup_error:
                error.add_note(
                    "session blob rollback also failed: "
                    f"{cleanup_error.__class__.__name__}: {cleanup_error}"
                )
        raise
    return AgentTranscriptBundleImportResult(
        bundle=bundle,
        key=key,
        snapshot=snapshot,
    )


def _encode_bundle_manifest(
    header: ConversationHeader,
    references: Sequence[SessionBlobRef],
) -> bytes:
    value = {
        "schemaVersion": _BUNDLE_SCHEMA_VERSION,
        "conversationId": header.conversation_id,
        "blobs": [reference.manifest_entry() for reference in references],
    }
    return _json_line(value)


def _validate_bundle_header(header: ConversationHeader) -> None:
    try:
        require_portable_artifact_id(
            header.conversation_id,
            name="bundle conversation id",
        )
    except (TypeError, ValueError) as error:
        raise AgentTranscriptBundleError("bundle conversation id is not portable") from error
    if _PORTABLE_UTC_TIMESTAMP.fullmatch(header.created_at) is None:
        raise AgentTranscriptBundleError("bundle creation timestamp is not portable UTC")


def _decode_bundle_manifest(content: bytes) -> _DecodedBundleManifest:
    value = _decode_json(content, name="bundle manifest")
    if set(value) != {"schemaVersion", "conversationId", "blobs"}:
        raise AgentTranscriptBundleError("bundle manifest shape is invalid")
    if value["schemaVersion"] != _BUNDLE_SCHEMA_VERSION:
        raise AgentTranscriptBundleError("bundle schema version is unsupported")
    conversation_id = value["conversationId"]
    raw_blobs = value["blobs"]
    if not isinstance(conversation_id, str) or not isinstance(raw_blobs, list):
        raise AgentTranscriptBundleError("bundle manifest fields are invalid")
    try:
        references = tuple(
            SessionBlobRef.from_manifest_entry(
                require_json_mapping(item, name="bundle blob reference")
            )
            for item in raw_blobs
        )
    except (TypeError, ValueError) as error:
        raise AgentTranscriptBundleError("bundle blob reference is invalid") from error
    if len(set(references)) != len(references):
        raise AgentTranscriptBundleError("bundle contains duplicate blob references")
    return _DecodedBundleManifest(
        conversation_id=conversation_id,
        references=references,
    )


def _encode_transcript(
    header: ConversationHeader,
    records: Sequence[AgentTranscriptRecord],
) -> bytes:
    header_codec = ConversationJsonlHeaderCodec()
    record_codec = ConversationJsonlRecordCodec(
        create_agent_transcript_payload_registry()
    )
    lines = [_json_line(header_codec.encode_header(header))]
    lines.extend(_json_line(record_codec.encode_record(record)) for record in records)
    return b"".join(lines)


def _decode_transcript(
    content: bytes,
) -> tuple[ConversationHeader, tuple[AgentTranscriptRecord, ...]]:
    try:
        lines = [line for line in content.decode("utf-8").splitlines() if line.strip()]
    except UnicodeError as error:
        raise AgentTranscriptBundleError("bundle transcript is not UTF-8") from error
    if not lines:
        raise AgentTranscriptBundleError("bundle transcript is empty")
    values = [_decode_json(line.encode(), name="bundle transcript line") for line in lines]
    header_codec = ConversationJsonlHeaderCodec()
    record_codec = ConversationJsonlRecordCodec(
        create_agent_transcript_payload_registry()
    )
    try:
        header = header_codec.decode_header(values[0])
        records = tuple(
            cast(AgentTranscriptRecord, record_codec.decode_record(value))
            for value in values[1:]
        )
    except Exception as error:
        raise AgentTranscriptBundleError("bundle transcript is invalid") from error
    return header, records


def _json_line(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _decode_json(content: bytes, *, name: str) -> dict[str, JSONValue]:
    try:
        value = json.loads(
            content,
            parse_constant=lambda constant: (_raise_invalid_constant(constant)),
        )
        return require_json_mapping(value, name=name)
    except AgentTranscriptBundleError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise AgentTranscriptBundleError(f"{name} is invalid") from error


def _raise_invalid_constant(constant: str) -> None:
    raise ValueError(f"invalid JSON constant: {constant}")


def _bounded_zip_read(
    archive: zipfile.ZipFile,
    name: str,
    *,
    max_bytes: int,
) -> bytes:
    info = archive.getinfo(name)
    if info.is_dir() or info.file_size > max_bytes:
        raise ArtifactStoreQuotaExceeded(f"bundle member {name!r} exceeds its limit")
    with archive.open(info, "r") as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes or len(content) != info.file_size:
        raise ArtifactStoreQuotaExceeded(f"bundle member {name!r} exceeds its limit")
    return content


def _write_bundle(
    destination: Path,
    *,
    transcript: bytes,
    manifest: bytes,
    objects: Mapping[str, bytes],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    identity = _write_new_private_file(temporary, b"")
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(_BUNDLE_MANIFEST, manifest)
            archive.writestr(_TRANSCRIPT_MEMBER, transcript)
            for blob_id, content in sorted(objects.items()):
                archive.writestr(_OBJECT_PREFIX + blob_id, content)
        descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _publish_file_exclusive(temporary, destination)
        _sync_directory(destination.parent)
    finally:
        with suppress(FileNotFoundError):
            _unlink_owned_file(temporary, identity)


__all__ = [
    "AgentTranscriptBundle",
    "AgentTranscriptBundleError",
    "AgentTranscriptBundleImportResult",
    "DEFAULT_TRANSCRIPT_BUNDLE_POLICY",
    "SessionBlobRedactor",
    "export_agent_transcript_bundle",
    "import_agent_transcript_bundle",
    "read_agent_transcript_bundle",
]
