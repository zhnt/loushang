from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from loushang.foundation.json import dump_json_value
from loushang.harness.conversation import CommitReceipt
from loushang.harness.transcript.codecs import (
    STANDARD_PAYLOAD_VERSION,
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.kinds import APPLICATION_MESSAGE_KIND
from loushang.harness.transcript.types import ApplicationMessage
from loushang.harness.transcript.unit_of_work import AgentTranscriptUnitOfWork


class ApplicationMessageIdentityConflictError(ValueError):
    pass


@dataclass(frozen=True)
class CommitResult:
    record_id: str
    disposition: Literal["staged", "committed", "already_committed"]
    receipt: CommitReceipt | None


@dataclass(frozen=True)
class _CommittedApplicationMessage:
    record_id: str
    fingerprint: str


class TranscriptCommitter:
    """Own the process-local idempotent commit of application messages."""

    def __init__(self, store: AgentTranscriptUnitOfWork) -> None:
        self._store = store
        self._committed: dict[str, _CommittedApplicationMessage] = {}
        self._payload_codecs = create_agent_transcript_payload_registry()
        self._commit_lock = asyncio.Lock()
        self._index_committed_messages()

    async def commit_application_message(
        self,
        message: ApplicationMessage,
    ) -> CommitResult:
        async with self._commit_lock:
            fingerprint = self._fingerprint(message)
            existing = self._committed.get(message.application_message_id)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise ApplicationMessageIdentityConflictError(
                        "application message id was reused with a different payload: "
                        f"{message.application_message_id}"
                    )
                return CommitResult(
                    record_id=existing.record_id,
                    disposition="already_committed",
                    receipt=None,
                )

            commit = await self._store.append_application_message(message)
            if commit.receipt is None:
                raise RuntimeError(
                    "application messages must materialize a provisional transcript"
                )
            record = commit.record
            self._committed[message.application_message_id] = (
                _CommittedApplicationMessage(
                    record_id=record.record_id,
                    fingerprint=fingerprint,
                )
            )
            return CommitResult(
                record_id=record.record_id,
                disposition="committed",
                receipt=commit.receipt,
            )

    def _index_committed_messages(self) -> None:
        for record in self._store.records:
            if record.kind != APPLICATION_MESSAGE_KIND or not isinstance(
                record.payload,
                ApplicationMessage,
            ):
                continue
            message = record.payload
            fingerprint = self._fingerprint(message)
            existing = self._committed.get(message.application_message_id)
            if existing is not None and existing.fingerprint != fingerprint:
                raise ApplicationMessageIdentityConflictError(
                    "stored application message id has conflicting payloads: "
                    f"{message.application_message_id}"
                )
            self._committed[message.application_message_id] = (
                _CommittedApplicationMessage(
                    record_id=record.record_id,
                    fingerprint=fingerprint,
                )
            )

    def _fingerprint(self, message: ApplicationMessage) -> str:
        payload = self._payload_codecs.encode(
            APPLICATION_MESSAGE_KIND,
            STANDARD_PAYLOAD_VERSION,
            message,
        )
        return dump_json_value(
            payload,
            name="application message identity",
            ensure_ascii=False,
            sort_keys=True,
        )


__all__ = [
    "ApplicationMessageIdentityConflictError",
    "CommitResult",
    "TranscriptCommitter",
]
