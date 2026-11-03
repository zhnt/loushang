from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Literal

from loushang.ai.types import ImagePart, UserMessage
from loushang.foundation.json import dump_json_value, require_json_mapping
from loushang.harness.conversation import CommitReceipt, StoreCommitOutcomeUnknown
from loushang.harness.transcript.codecs import (
    STANDARD_PAYLOAD_VERSION,
    create_agent_transcript_payload_registry,
)
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    EXTENSION_DATA_KIND,
)
from loushang.harness.transcript.types import (
    AgentTranscriptRecord,
    ApplicationMessage,
    ExtensionData,
)
from loushang.harness.transcript.unit_of_work import AgentTranscriptUnitOfWork


class ApplicationMessageIdentityConflictError(ValueError):
    pass


class PrebuiltUserMessageIdentityConflictError(ValueError):
    """A fixed record ID names different facts or a different selected branch."""


class PrebuiltExtensionDataIdentityConflictError(ValueError):
    """A fixed extension record ID names different facts or another branch."""


@dataclass(frozen=True)
class CommitResult:
    record_id: str
    disposition: Literal["staged", "committed", "already_committed"]
    receipt: CommitReceipt | None


@dataclass(frozen=True)
class PrebuiltUserMessageLookupResult:
    """Durable input observation; it grants no retry or execution authority."""

    record_id: str
    status: Literal["committed", "not_committed_verified", "unknown", "conflict"]


@dataclass(frozen=True)
class _CommittedApplicationMessage:
    record_id: str
    fingerprint: str


class TranscriptCommitter:
    """Own process-local idempotent commits of app and fixed-ID records."""

    def __init__(self, store: AgentTranscriptUnitOfWork) -> None:
        self._store = store
        self._committed: dict[str, _CommittedApplicationMessage] = {}
        self._uncertain_prebuilt_ids: set[str] = set()
        self._payload_codecs = create_agent_transcript_payload_registry()
        self._commit_lock = asyncio.Lock()
        self._index_committed_messages()

    async def lookup_prebuilt_user_message(
        self, record: AgentTranscriptRecord,
    ) -> PrebuiltUserMessageLookupResult:
        """Read the original authority store without appending or changing leaf.

        The expected record includes its frozen payload and complete metadata.
        Absence requires a complete authority load and unchanged local target.
        A returned observation still needs ordinary owner admission before use.
        """

        if record.kind != AGENT_MESSAGE_KIND or not isinstance(record.payload, UserMessage):
            raise TypeError("prebuilt user lookup requires an agent UserMessage")
        payload = self._payload_codecs.decode(
            AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION,
            self._payload_codecs.encode(
                AGENT_MESSAGE_KIND, STANDARD_PAYLOAD_VERSION, record.payload,
            ),
        )
        if not isinstance(payload, UserMessage):
            raise TypeError("prebuilt user lookup codec did not preserve UserMessage")
        record = replace(
            record, payload=payload,
            metadata=require_json_mapping(dict(record.metadata), name="prebuilt user lookup metadata"),
        )
        async with self._commit_lock:
            def result(
                status: Literal["committed", "not_committed_verified", "unknown", "conflict"],
            ) -> PrebuiltUserMessageLookupResult:
                return PrebuiltUserMessageLookupResult(record.record_id, status)
            if not self._store.is_materialized:
                return result("unknown")
            revision, leaf_id = self._store.revision, self._store.leaf_id
            try:
                observed = await AgentTranscriptUnitOfWork.load(
                    self._store.backend, self._store.key,
                )
            except Exception:
                # Missing, unreadable, or unavailable authority is never absence.
                return result("unknown")
            if (
                observed.header != self._store.header
                or observed.diagnostics or self._store.diagnostics
                or (revision, leaf_id) != (self._store.revision, self._store.leaf_id)
            ):
                return result("unknown")
            existing = observed.get(record.record_id)
            if existing is not None:
                local = self._store.get(record.record_id)
                if (
                    existing != record or existing not in observed.active_path()
                    or (local is not None and local not in self._store.active_path())
                    or (local is None and record.parent_id != leaf_id)
                ):
                    return result("conflict")
                return result("committed")
            if (
                record.record_id in self._uncertain_prebuilt_ids
                or observed.revision != revision
                or observed.records != self._store.records
            ):
                return result("unknown")
            if record.parent_id != leaf_id:
                return result("conflict")
            return result("not_committed_verified")

    async def commit_prebuilt_user_message(
        self, record: AgentTranscriptRecord,
    ) -> CommitResult:
        """Commit one durable fixed-ID UserMessage through the existing owner.

        Product callers must supply final metadata and durable image references.
        An unknown result is not automatically re-appended in this process.
        A fresh authority load can reconcile the exact record before retry.
        """

        if record.kind != AGENT_MESSAGE_KIND or not isinstance(
            record.payload, UserMessage,
        ):
            raise TypeError("prebuilt user commit requires an agent UserMessage")
        content = record.payload.content
        if isinstance(content, list) and any(
            isinstance(part, ImagePart) for part in content
        ):
            raise ValueError("prebuilt user images must be externalized first")
        return await self._commit_prebuilt_record(
            record, kind_label="user",
            conflict_error=PrebuiltUserMessageIdentityConflictError,
        )

    async def commit_prebuilt_extension_data(
        self, record: AgentTranscriptRecord,
    ) -> CommitResult:
        """Commit or reconcile one fixed-ID extension fact through Transcript."""

        if record.kind != EXTENSION_DATA_KIND or not isinstance(
            record.payload, ExtensionData,
        ):
            raise TypeError("prebuilt extension commit requires extension data")
        return await self._commit_prebuilt_record(
            record, kind_label="extension",
            conflict_error=PrebuiltExtensionDataIdentityConflictError,
        )

    async def _commit_prebuilt_record(
        self,
        record: AgentTranscriptRecord,
        *,
        kind_label: str,
        conflict_error: type[ValueError],
    ) -> CommitResult:
        async with self._commit_lock:
            if not self._store.is_materialized:
                raise ValueError(
                    f"prebuilt {kind_label} commit requires a materialized transcript"
                )
            existing = self._store.get(record.record_id)
            if existing is not None:
                if existing != record or existing not in self._store.active_path():
                    raise conflict_error(
                        f"fixed {kind_label} record ID conflicts with stored input "
                        "or selected branch"
                    )
                self._uncertain_prebuilt_ids.discard(record.record_id)
                return CommitResult(record.record_id, "already_committed", None)
            if record.record_id in self._uncertain_prebuilt_ids:
                raise StoreCommitOutcomeUnknown(
                    f"fixed {kind_label} record outcome requires authoritative reload"
                )
            if self._store.diagnostics:
                raise StoreCommitOutcomeUnknown(
                    "incomplete transcript evidence cannot prove fixed "
                    f"{kind_label} record absent"
                )
            try:
                commit = await self._store.commit(record)
            except StoreCommitOutcomeUnknown:
                self._uncertain_prebuilt_ids.add(record.record_id)
                raise
            if commit.receipt is None:
                self._uncertain_prebuilt_ids.add(record.record_id)
                raise StoreCommitOutcomeUnknown(
                    f"prebuilt {kind_label} commit did not return a durable receipt"
                )
            return CommitResult(record.record_id, "committed", commit.receipt)

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
    "PrebuiltExtensionDataIdentityConflictError",
    "PrebuiltUserMessageIdentityConflictError",
    "TranscriptCommitter",
]
