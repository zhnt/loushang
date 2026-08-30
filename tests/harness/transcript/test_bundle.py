from __future__ import annotations

import asyncio
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

import loushang.harness.transcript.export.bundle as bundle_module
from loushang.ai.types import TextPart, ToolResultMessage, UserMessage
from loushang.harness.artifacts import (
    ArtifactStoreQuotaExceeded,
    SessionBlobError,
    SessionBlobPolicy,
    SessionBlobStore,
)
from loushang.harness.conversation import (
    CommandExecutionRecord,
    ConversationHeader,
    ConversationKey,
    ConversationRecord,
    MemoryConversationStore,
)
from loushang.harness.transcript import SessionImagePart
from loushang.harness.transcript.export import (
    DEFAULT_TRANSCRIPT_BUNDLE_POLICY,
    AgentTranscriptBundleError,
    export_agent_transcript_bundle,
    import_agent_transcript_bundle,
    read_agent_transcript_bundle,
)
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND, COMMAND_EXECUTION_KIND
from loushang.harness.transcript.session_artifacts import (
    SessionBlobOwnershipError,
    clone_agent_transcript_session_blobs,
)


def _session(tmp_path: Path, *, disclosure: str = "private"):
    session_dir = tmp_path / "data" / "sessions"
    blob_store = SessionBlobStore(tmp_path / "data", "session-1", now=lambda: 1.0)
    blob = blob_store.put_bytes(
        b"complete output",
        logical_name="commands/stdout.txt",
        kind="command-output",
        media_type="text/plain",
        disclosure=disclosure,  # type: ignore[arg-type]
    )
    header = ConversationHeader(
        conversation_id="session-1",
        version=1,
        created_at="2026-08-27T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )
    record = ConversationRecord(
        record_id="record-1",
        parent_id=None,
        kind=COMMAND_EXECUTION_KIND,
        payload_version=1,
        created_at="2026-08-27T00:00:01Z",
        payload=CommandExecutionRecord(
            command="build",
            output="complete...",
            exit_code=0,
            truncated=True,
            full_output_blob=blob,
        ),
    )
    return session_dir, header, record, blob


def test_bundle_round_trip_contains_transcript_and_verified_blobs(
    tmp_path: Path,
) -> None:
    session_dir, header, record, blob = _session(tmp_path)
    output = tmp_path / "exports" / "backup.loushang.zip"

    result = export_agent_transcript_bundle(
        header,
        [record],
        session_dir=session_dir,
        output_path=output,
        allow_private=True,
    )
    bundle = read_agent_transcript_bundle(result)

    assert Path(result) == output.resolve()
    assert bundle.header == header
    assert len(bundle.records) == 1
    restored = bundle.records[0].payload
    assert isinstance(restored, CommandExecutionRecord)
    assert restored.full_output_blob == blob
    assert bundle.blobs == ((blob, b"complete output"),)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "bundle.json",
            "session.jsonl",
            f"objects/{blob.blob_id}",
        }
        assert b"fullOutputPath" not in archive.read("session.jsonl")
        assert b"/tmp" not in archive.read("bundle.json")


def test_bundle_carries_session_backed_images_without_inline_bytes(
    tmp_path: Path,
) -> None:
    session_dir = tmp_path / "data" / "sessions"
    store = SessionBlobStore(tmp_path / "data", "image-session", now=lambda: 1.0)
    image = store.put_bytes(
        b"image bytes",
        logical_name="images/generated.png",
        kind="image",
        media_type="image/png",
    )
    header = ConversationHeader(
        conversation_id="image-session",
        version=1,
        created_at="2026-08-27T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )
    record = ConversationRecord(
        record_id="record-image",
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-08-27T00:00:01Z",
        payload=UserMessage(
            role="user",
            content=[SessionImagePart(type="image", blob=image)],
            timestamp=1.0,
        ),
    )

    output = export_agent_transcript_bundle(
        header,
        [record],
        session_dir=session_dir,
        output_path=tmp_path / "image-backup.zip",
        allow_private=True,
    )
    bundle = read_agent_transcript_bundle(output)

    assert bundle.blobs == ((image, b"image bytes"),)
    restored = bundle.records[0].payload
    assert isinstance(restored, UserMessage)
    assert isinstance(restored.content[0], SessionImagePart)
    with zipfile.ZipFile(output) as archive:
        transcript = archive.read("session.jsonl")
    assert b"sessionBlob" in transcript
    assert b"image bytes" not in transcript


def test_bundle_collects_stream_blobs_from_tool_result_details(tmp_path: Path) -> None:
    session_dir = tmp_path / "data" / "sessions"
    store = SessionBlobStore(tmp_path / "data", "tool-session", now=lambda: 1.0)
    stdout = store.put_bytes(
        b"complete stdout",
        logical_name="command-output/stdout.log",
        kind="command-stdout",
        media_type="text/plain",
    )
    stderr = store.put_bytes(
        b"complete stderr",
        logical_name="command-output/stderr.log",
        kind="command-stderr",
        media_type="text/plain",
    )
    header = ConversationHeader(
        conversation_id="tool-session",
        version=1,
        created_at="2026-08-27T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )
    record = ConversationRecord(
        record_id="record-tool",
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-08-27T00:00:01Z",
        payload=ToolResultMessage(
            role="toolResult",
            tool_call_id="call-1",
            tool_name="bash",
            content=[TextPart(type="text", text="preview")],
            is_error=False,
            timestamp=1.0,
            details={
                "stdout_blob": stdout.manifest_entry(),
                "stderr_blob": stderr.manifest_entry(),
            },
        ),
    )

    output = export_agent_transcript_bundle(
        header,
        [record],
        session_dir=session_dir,
        output_path=tmp_path / "tool-backup.zip",
        allow_private=True,
    )
    bundle = read_agent_transcript_bundle(output)

    assert bundle.blobs == (
        (stdout, b"complete stdout"),
        (stderr, b"complete stderr"),
    )


def test_bundle_private_bytes_require_explicit_backup_consent(tmp_path: Path) -> None:
    session_dir, header, record, _blob = _session(tmp_path)

    with pytest.raises(AgentTranscriptBundleError, match="allow_private"):
        export_agent_transcript_bundle(
            header,
            [record],
            session_dir=session_dir,
            output_path=tmp_path / "backup.zip",
        )


def test_bundle_and_clone_reject_foreign_session_blob_authority(tmp_path: Path) -> None:
    session_dir, header, record, _blob = _session(tmp_path)
    foreign = SessionBlobStore(tmp_path / "data", "foreign").put_bytes(
        b"private foreign output",
        logical_name="commands/foreign.txt",
        kind="command-output",
        media_type="text/plain",
    )
    payload = record.payload
    assert isinstance(payload, CommandExecutionRecord)
    forged = replace(record, payload=replace(payload, full_output_blob=foreign))

    with pytest.raises(AgentTranscriptBundleError, match="foreign Session blob"):
        export_agent_transcript_bundle(
            header,
            [forged],
            session_dir=session_dir,
            output_path=tmp_path / "foreign.zip",
            allow_private=True,
        )
    with pytest.raises(SessionBlobOwnershipError, match="another Session"):
        clone_agent_transcript_session_blobs(
            [forged],
            source_session_dir=session_dir,
            source_session_id=header.conversation_id,
            target_session_dir=tmp_path / "target" / "data" / "sessions",
            target_session_id="target",
        )
    assert not (tmp_path / "target" / "data" / "session-assets").exists()


def test_bundle_has_an_independent_bounded_in_memory_policy() -> None:
    assert DEFAULT_TRANSCRIPT_BUNDLE_POLICY.max_blob_bytes == 16 * 1024 * 1024
    assert DEFAULT_TRANSCRIPT_BUNDLE_POLICY.max_total_bytes == 64 * 1024 * 1024


def test_bundle_redaction_rewrites_blob_integrity_and_disclosure(
    tmp_path: Path,
) -> None:
    session_dir, header, record, original = _session(
        tmp_path,
        disclosure="redact",
    )

    output = export_agent_transcript_bundle(
        header,
        [record],
        session_dir=session_dir,
        output_path=tmp_path / "redacted.zip",
        redactor=lambda _ref, content: content.replace(b"output", b"[redacted]"),
    )
    bundle = read_agent_transcript_bundle(output)

    exported_ref, content = bundle.blobs[0]
    assert content == b"complete [redacted]"
    assert exported_ref.disclosure == "shareable"
    assert exported_ref.sha256 != original.sha256
    restored = bundle.records[0].payload
    assert isinstance(restored, CommandExecutionRecord)
    assert restored.full_output_blob == exported_ref


def test_bundle_import_commits_blobs_and_transcript_to_target_authorities(
    tmp_path: Path,
) -> None:
    session_dir, header, record, blob = _session(tmp_path / "source")
    output = export_agent_transcript_bundle(
        header,
        [record],
        session_dir=session_dir,
        output_path=tmp_path / "backup.zip",
        allow_private=True,
    )
    target_session_dir = tmp_path / "target" / "data" / "sessions"
    store = MemoryConversationStore(record_id=lambda item: item.record_id)
    key = ConversationKey("target", "session-1")

    result = asyncio.run(
        import_agent_transcript_bundle(
            output,
            store=store,
            key=key,
            session_dir=target_session_dir,
            operation_id="import-1",
        )
    )

    assert result.snapshot.header == header
    target_blobs = SessionBlobStore(
        tmp_path / "target" / "data",
        "session-1",
    )
    assert target_blobs.read_bytes(blob) == b"complete output"


def test_bundle_import_rolls_back_blobs_when_transcript_create_fails(
    tmp_path: Path,
) -> None:
    session_dir, header, record, _blob = _session(tmp_path / "source")
    output = export_agent_transcript_bundle(
        header,
        [record],
        session_dir=session_dir,
        output_path=tmp_path / "backup.zip",
        allow_private=True,
    )
    target_session_dir = tmp_path / "target" / "data" / "sessions"

    class FailingStore:
        async def create(self, *args, **kwargs):
            del args, kwargs
            raise RuntimeError("transcript failed")

    with pytest.raises(RuntimeError, match="transcript failed"):
        asyncio.run(
            import_agent_transcript_bundle(
                output,
                store=FailingStore(),  # type: ignore[arg-type]
                key=ConversationKey("target", "session-1"),
                session_dir=target_session_dir,
                operation_id="import-1",
            )
        )

    assert not (tmp_path / "target" / "data" / "session-assets" / "session-1").exists()


def test_bundle_reader_rejects_extra_and_duplicate_members(tmp_path: Path) -> None:
    session_dir, header, record, _blob = _session(tmp_path)
    output = Path(
        export_agent_transcript_bundle(
            header,
            [record],
            session_dir=session_dir,
            output_path=tmp_path / "backup.zip",
            allow_private=True,
        )
    )
    with zipfile.ZipFile(output, "a") as archive:
        archive.writestr("../escape", b"bad")

    with pytest.raises(AgentTranscriptBundleError, match="member set"):
        read_agent_transcript_bundle(output)


def test_bundle_manifest_cannot_reference_undeclared_transcript_blob(
    tmp_path: Path,
) -> None:
    session_dir, header, record, _blob = _session(tmp_path)
    output = Path(
        export_agent_transcript_bundle(
            header,
            [record],
            session_dir=session_dir,
            output_path=tmp_path / "backup.zip",
            allow_private=True,
        )
    )
    rewritten = tmp_path / "rewritten.zip"
    with zipfile.ZipFile(output) as source, zipfile.ZipFile(rewritten, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "bundle.json":
                manifest = json.loads(content)
                manifest["blobs"] = []
                content = json.dumps(manifest).encode()
            target.writestr(name, content)

    with pytest.raises(AgentTranscriptBundleError):
        read_agent_transcript_bundle(rewritten)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("createdAt", "../../outside", "timestamp"),
        ("conversationId", "../outside", "conversation id"),
        ("conversationId", "C:\\outside", "conversation id"),
    ],
)
def test_bundle_reader_rejects_header_values_that_could_escape_session_root(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    header = ConversationHeader(
        conversation_id="safe-session",
        version=1,
        created_at="2026-08-27T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )
    source = Path(
        export_agent_transcript_bundle(
            header,
            [],
            session_dir=tmp_path / "data" / "sessions",
            output_path=tmp_path / "safe.zip",
        )
    )
    rewritten = tmp_path / f"unsafe-{field}.zip"
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(rewritten, "w") as output:
        for name in archive.namelist():
            content = archive.read(name)
            if name == "session.jsonl":
                envelope = json.loads(content)
                envelope[field] = value
                content = (json.dumps(envelope) + "\n").encode()
            elif name == "bundle.json" and field == "conversationId":
                manifest = json.loads(content)
                manifest["conversationId"] = value
                content = json.dumps(manifest).encode()
            output.writestr(name, content)

    with pytest.raises(AgentTranscriptBundleError, match=message):
        read_agent_transcript_bundle(rewritten)


def test_bundle_total_quota_is_rejected_before_any_object_is_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_dir = tmp_path / "data" / "sessions"
    store = SessionBlobStore(tmp_path / "data", "session-1")
    refs = [
        store.put_bytes(
            content,
            logical_name=f"{index}.txt",
            kind="output",
            media_type="text/plain",
            disclosure="shareable",
        )
        for index, content in enumerate((b"aaa", b"bbb"), start=1)
    ]
    header = ConversationHeader(
        conversation_id="session-1",
        version=1,
        created_at="2026-08-27T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )
    records = [
        ConversationRecord(
            record_id=f"record-{index}",
            parent_id=f"record-{index - 1}" if index > 1 else None,
            kind=COMMAND_EXECUTION_KIND,
            payload_version=1,
            created_at=f"2026-08-27T00:00:0{index}Z",
            payload=CommandExecutionRecord(
                command=f"command-{index}",
                output="...",
                exit_code=0,
                truncated=True,
                full_output_blob=reference,
            ),
        )
        for index, reference in enumerate(refs, start=1)
    ]
    output = export_agent_transcript_bundle(
        header,
        records,
        session_dir=session_dir,
        output_path=tmp_path / "quota.zip",
    )
    opened: list[str] = []
    original = bundle_module._bounded_zip_read

    def recording_read(archive, name: str, *, max_bytes: int) -> bytes:
        opened.append(name)
        return original(archive, name, max_bytes=max_bytes)

    monkeypatch.setattr(bundle_module, "_bounded_zip_read", recording_read)

    with pytest.raises(ArtifactStoreQuotaExceeded, match="byte limit"):
        read_agent_transcript_bundle(
            output,
            policy=SessionBlobPolicy(
                max_blobs=2,
                max_blob_bytes=4,
                max_total_bytes=4,
            ),
        )
    assert opened == ["bundle.json"]


def test_bundle_import_does_not_reuse_or_delete_existing_empty_authority(
    tmp_path: Path,
) -> None:
    session_dir, header, record, _blob = _session(tmp_path / "source")
    output = export_agent_transcript_bundle(
        header,
        [record],
        session_dir=session_dir,
        output_path=tmp_path / "backup.zip",
        allow_private=True,
    )
    target_data = tmp_path / "target" / "data"
    existing = target_data / "session-assets" / "session-1"
    (existing / "objects").mkdir(parents=True)
    (existing / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sessionId": "session-1",
                "blobs": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SessionBlobError, match="already exists"):
        asyncio.run(
            import_agent_transcript_bundle(
                output,
                store=MemoryConversationStore(
                    record_id=lambda item: item.record_id
                ),
                key=ConversationKey("target", "session-1"),
                session_dir=target_data / "sessions",
                operation_id="import-existing",
            )
        )

    assert existing.exists()
    assert json.loads((existing / "manifest.json").read_text())["blobs"] == []
