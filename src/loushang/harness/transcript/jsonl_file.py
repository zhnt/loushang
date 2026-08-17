"""Agent transcript composition over the Conversation JSONL format.

Product code chooses a root directory and a storage provider; it does not own
JSONL codecs, locking, or file discovery.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, cast

from loushang.harness.conversation import (
    ConversationHeader,
    ConversationJsonlHeaderCodec,
    ConversationJsonlRecordCodec,
    ConversationKey,
    ConversationRepository,
    FileConversationStore,
)
from loushang.harness.journal import (
    DEFAULT_JSONL_FORMAT,
    DURABLE_LOCKED_JOURNAL,
    JournalFileError,
    JournalLoadPolicy,
    JournalRecordCodec,
    JsonlJournal,
    JsonlSnapshot,
    LockMode,
    journal_file_lock,
)
from loushang.harness.transcript.profile import AgentTranscriptProfile
from loushang.harness.transcript.types import AgentTranscriptRecord


class AgentTranscriptFileError(ValueError):
    """An Agent transcript JSONL file could not be read safely."""

    def __init__(self, message: str, *, path: Path, code: str) -> None:
        super().__init__(message)
        self.path = path
        self.code = code


_PROFILE = AgentTranscriptProfile.default()
_HEADER_CODEC = ConversationJsonlHeaderCodec()
_RECORD_CODEC = cast(
    JournalRecordCodec[AgentTranscriptRecord],
    ConversationJsonlRecordCodec(_PROFILE.payload_codecs),
)
_READ_LOAD_POLICY = JournalLoadPolicy(
    header="required",
    invalid_record="raise",
    partial_tail="skip",
)
_WRITABLE_LOAD_POLICY = JournalLoadPolicy(
    header="required",
    invalid_record="raise",
    partial_tail="repair",
)


@contextmanager
def agent_transcript_file_lock(path: Path, mode: LockMode) -> Iterator[None]:
    """Lock one transcript file with the current platform implementation."""

    with journal_file_lock(
        path,
        mode,
        is_windows=_is_windows,
        load_fcntl=_load_fcntl,
        load_msvcrt=_load_msvcrt,
    ):
        yield


def agent_transcript_journal(
    path: Path,
    *,
    repair_partial_tail: bool = False,
) -> JsonlJournal[ConversationHeader, AgentTranscriptRecord]:
    """Open one Conversation JSONL transcript journal."""

    return JsonlJournal(
        path,
        record_codec=_RECORD_CODEC,
        header_codec=_HEADER_CODEC,
        format_profile=DEFAULT_JSONL_FORMAT,
        durability=DURABLE_LOCKED_JOURNAL,
        load_policy=(
            _WRITABLE_LOAD_POLICY if repair_partial_tail else _READ_LOAD_POLICY
        ),
        lock_factory=agent_transcript_file_lock,
    )


def write_agent_transcript_export(
    path: Path,
    header: ConversationHeader,
    records: list[AgentTranscriptRecord],
) -> None:
    """Write a derived Conversation JSONL artifact, never an active Store stream."""

    agent_transcript_journal(path).rewrite(records, header=header)


def create_agent_transcript_repository(
    *,
    header: ConversationHeader,
    records: list[AgentTranscriptRecord],
) -> ConversationRepository[ConversationHeader, AgentTranscriptRecord]:
    return ConversationRepository.create(
        header=header,
        records=records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        mode="compatible",
    )


def load_agent_transcript_repository(
    path: Path,
) -> ConversationRepository[ConversationHeader, AgentTranscriptRecord]:
    """Load a detached Conversation JSONL transcript without mutating its source."""

    try:
        snapshot = agent_transcript_journal(path).load()
        if snapshot.header is None:
            raise AgentTranscriptFileError(
                "Transcript file must start with a conversation header",
                path=path,
                code="missing_conversation_header",
            )
        return _create_detached_repository(
            header=snapshot.header,
            records=snapshot.records,
        )
    except JournalFileError as exc:
        raise _agent_transcript_file_error(exc) from exc


def load_agent_transcript_file(
    path: Path,
) -> tuple[ConversationHeader, list[AgentTranscriptRecord]]:
    try:
        snapshot: JsonlSnapshot[ConversationHeader, AgentTranscriptRecord] = (
            agent_transcript_journal(path).load()
        )
    except JournalFileError as exc:
        raise _agent_transcript_file_error(exc) from exc
    if snapshot.header is None:
        raise AgentTranscriptFileError(
            "Transcript file must start with a conversation header",
            path=path,
            code="missing_conversation_header",
        )
    return snapshot.header, list(snapshot.records)


def load_agent_transcript_header(path: Path) -> ConversationHeader:
    """Read only the Conversation JSONL header without scanning the transcript."""

    target = Path(path)
    try:
        with agent_transcript_file_lock(target, "shared"):
            with target.open("r", encoding=DEFAULT_JSONL_FORMAT.encoding) as handle:
                line = next((line for line in handle if line.strip()), "")
    except OSError as exc:
        raise AgentTranscriptFileError(
            "Transcript file could not be read",
            path=target,
            code="session_file_read_failed",
        ) from exc
    if not line:
        raise AgentTranscriptFileError(
            "Transcript file is empty",
            path=target,
            code="empty_session_file",
        )
    try:
        value = json.loads(
            line,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise AgentTranscriptFileError(
            "Transcript file header is not valid JSON",
            path=target,
            code="invalid_session_header_json",
        ) from exc
    try:
        if not isinstance(value, dict):
            raise TypeError("conversation header must be a JSON object")
        return _HEADER_CODEC.decode_header(value)
    except Exception as exc:
        code = getattr(exc, "code", "invalid_session_header")
        mapped = {
            "invalid_envelope_type": "unsupported_session_format",
            "unsupported_conversation_format_version": "unsupported_session_format",
        }.get(code, code)
        raise AgentTranscriptFileError(
            "Transcript file format is not supported"
            if mapped == "unsupported_session_format"
            else "Transcript file header is invalid",
            path=target,
            code=mapped,
        ) from exc


FilenameForKey = Callable[[ConversationKey], str]


@dataclass
class AgentTranscriptFileLayout:
    """Map transcript identities to Conversation JSONL paths.

    Products own the root they select. OEMs can provide a filename function
    without replacing the codec or storage semantics.
    """

    root: Path
    filename_for_key: FilenameForKey | None = None
    _known_paths: dict[ConversationKey, Path] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = self.root.expanduser().resolve(strict=False)

    @property
    def namespace(self) -> str:
        return str(self.root)

    def key(self, conversation_id: str) -> ConversationKey:
        return ConversationKey(
            namespace=self.namespace,
            conversation_id=conversation_id,
        )

    def bind_path(self, key: ConversationKey, path: str | Path) -> None:
        self._require_namespace(key)
        self._known_paths[key] = Path(path).expanduser().resolve(strict=False)

    def create_path(self, key: ConversationKey) -> Path:
        self._require_namespace(key)
        self.root.mkdir(parents=True, exist_ok=True)
        known = self._known_paths.get(key)
        if known is not None:
            return known
        filename = (
            self.filename_for_key(key)
            if self.filename_for_key is not None
            else _default_filename(key)
        )
        path = self.root / filename
        self._known_paths[key] = path
        return path

    def resolve_path(self, key: ConversationKey) -> Path | None:
        self._require_namespace(key)
        known = self._known_paths.get(key)
        if known is not None and known.is_file():
            return known
        for path in self.scan_paths(key.namespace):
            try:
                candidate = self.key_for_path(key.namespace, path)
            except Exception:
                continue
            if candidate == key:
                return path
        return None

    def scan_paths(self, namespace: str) -> tuple[Path, ...]:
        if namespace != self.namespace or not self.root.is_dir():
            return ()
        return tuple(
            path
            for path in sorted(self.root.glob("*.jsonl"))
            if not path.name.endswith("-export.jsonl")
            and _is_conversation_jsonl_candidate(path)
        )

    def has_transcript_modified_after(self, modified_at_ns: int) -> bool:
        """Check local authority freshness without decoding transcript bodies."""

        return bool(self.transcript_paths_modified_after(modified_at_ns))

    def transcript_paths_modified_after(
        self,
        modified_at_ns: int,
    ) -> tuple[Path, ...]:
        """List changed authority candidates using directory metadata only."""

        if not self.root.is_dir():
            return ()
        changed: list[Path] = []
        for path in self.root.glob("*.jsonl"):
            if path.name.endswith("-export.jsonl"):
                continue
            try:
                if path.is_file() and path.stat().st_mtime_ns > modified_at_ns:
                    changed.append(path)
            except OSError:
                continue
        return tuple(sorted(changed))

    def key_for_path(self, namespace: str, path: Path) -> ConversationKey:
        if namespace != self.namespace:
            raise ValueError("conversation key does not belong to this layout")
        key = self.key(load_agent_transcript_header(path).conversation_id)
        self.bind_path(key, path)
        return key

    def bind_existing_path(self, path: str | Path) -> ConversationKey:
        resolved = Path(path).expanduser().resolve(strict=False)
        return self.key_for_path(self.namespace, resolved)

    def bind_create_path(self, key: ConversationKey, path: str | Path) -> None:
        """Bind a product-selected filename before ``ConversationStore.create``."""

        self.bind_path(key, path)

    def tombstone_path(self, key: ConversationKey) -> Path:
        self._require_namespace(key)
        digest = hashlib.sha256(
            f"{key.namespace}\0{key.conversation_id}".encode()
        ).hexdigest()
        return self.root / ".conversation-identities" / f"{digest}.deleted.json"

    def _require_namespace(self, key: ConversationKey) -> None:
        if key.namespace != self.namespace:
            raise ValueError("conversation key does not belong to this layout")


def create_agent_transcript_file_store(
    layout: AgentTranscriptFileLayout,
) -> FileConversationStore[ConversationHeader, AgentTranscriptRecord]:
    """Build the Conversation JSONL provider for an Agent transcript profile."""

    return FileConversationStore(
        create_path=layout.create_path,
        resolve_path=layout.resolve_path,
        scan_paths=layout.scan_paths,
        key_for_path=layout.key_for_path,
        journal_factory=agent_transcript_journal,
        write_journal_factory=lambda path: agent_transcript_journal(
            path,
            repair_partial_tail=True,
        ),
        record_id=lambda record: record.record_id,
        tombstone_path=layout.tombstone_path,
    )


def _create_detached_repository(
    *,
    header: ConversationHeader,
    records: tuple[AgentTranscriptRecord, ...],
) -> ConversationRepository[ConversationHeader, AgentTranscriptRecord]:
    return ConversationRepository.create(
        header=header,
        records=records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        mode="compatible",
    )


def _agent_transcript_file_error(error: JournalFileError) -> AgentTranscriptFileError:
    code = {
        "empty_journal": "empty_session_file",
        "invalid_header_json": "invalid_session_header_json",
        "invalid_header_shape": "invalid_session_header",
        "invalid_envelope_type": "unsupported_session_format",
        "unsupported_conversation_format_version": "unsupported_session_format",
    }.get(error.code, error.code)
    message = {
        "empty_session_file": "Transcript file is empty",
        "invalid_session_header_json": "Transcript file header is not valid JSON",
        "missing_conversation_header": (
            "Transcript file must start with a conversation header"
        ),
        "invalid_session_header": "Transcript file header is invalid",
        "unsupported_session_format": "Transcript file format is not supported",
    }.get(code, "Transcript file is invalid")
    return AgentTranscriptFileError(message, path=error.path, code=code)


def _is_conversation_jsonl_candidate(path: Path) -> bool:
    """Exclude other JSONL families; malformed Conversation files stay visible."""

    try:
        with path.open("r", encoding=DEFAULT_JSONL_FORMAT.encoding) as handle:
            line = next((line for line in handle if line.strip()), "")
        value = json.loads(line)
    except Exception:
        return True
    return not isinstance(value, dict) or value.get("type") == "conversation"


def _reject_json_constant(token: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant {token!r}")


def _default_filename(key: ConversationKey) -> str:
    timestamp = (
        datetime.now(UTC)
        .isoformat()
        .replace("+00:00", "Z")
        .replace(":", "-")
        .replace(".", "-")
    )
    return f"{timestamp}_{key.conversation_id}.jsonl"


def _is_windows() -> bool:
    return os.name == "nt"


def _load_fcntl() -> Any:
    return importlib.import_module("fcntl")


def _load_msvcrt() -> Any:
    return importlib.import_module("msvcrt")


__all__ = [
    "AgentTranscriptFileError",
    "AgentTranscriptFileLayout",
    "FilenameForKey",
    "LockMode",
    "agent_transcript_file_lock",
    "agent_transcript_journal",
    "create_agent_transcript_file_store",
    "create_agent_transcript_repository",
    "load_agent_transcript_file",
    "load_agent_transcript_repository",
    "load_agent_transcript_header",
    "write_agent_transcript_export",
]
