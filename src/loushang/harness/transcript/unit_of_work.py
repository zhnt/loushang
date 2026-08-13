from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from loushang.ai.types import Message, UserMessage
from loushang.foundation.json import JSONValue
from loushang.harness.conversation import (
    CommitReceipt,
    ConversationDiagnostic,
    ConversationKey,
    ConversationSourceDiagnostic,
    ConversationStore,
    StoreCommitOutcomeUnknown,
)
from loushang.harness.conversation.repository import ConversationRepository
from loushang.harness.conversation.types import (
    BranchDelta,
    CommandExecutionRecord,
    ConversationHeader,
    ConversationTreeNode,
)
from loushang.harness.transcript.codecs import STANDARD_PAYLOAD_VERSION
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    COMMAND_EXECUTION_KIND,
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    EXTENSION_DATA_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    THINKING_SELECTION_KIND,
)
from loushang.harness.transcript.profile import AgentTranscriptProfile
from loushang.harness.transcript.types import (
    AgentTranscriptContext,
    AgentTranscriptPayload,
    AgentTranscriptRecord,
    ApplicationMessage,
    BranchContextSummary,
    ContextCompactionCheckpoint,
    ConversationMetadataPatch,
    ExtensionData,
    ModelSelectionSnapshot,
    RecordAnnotationPatch,
    ThinkingSelectionSnapshot,
)
from loushang.harness.transcript.writer import (
    AgentTranscriptRecordFactory,
    Clock,
    IdFactory,
)


@dataclass(frozen=True)
class AgentTranscriptCommit:
    """One accepted record and its receipt once it has reached authority."""

    record: AgentTranscriptRecord
    receipt: CommitReceipt | None
    diagnostics: tuple[ConversationSourceDiagnostic, ...] = ()

    @property
    def durable(self) -> bool:
        return self.receipt is not None


AgentTranscriptOpenDiagnostic = ConversationSourceDiagnostic | ConversationDiagnostic
MaterializationPolicy = Callable[[AgentTranscriptRecord], bool]


class AgentTranscriptUnitOfWork:
    """One Agent transcript stream with optional deferred materialization."""

    def __init__(
        self,
        *,
        backend: ConversationStore[ConversationHeader, AgentTranscriptRecord],
        key: ConversationKey,
        repository: ConversationRepository[
            ConversationHeader,
            AgentTranscriptRecord,
        ],
        revision: int,
        record_factory: AgentTranscriptRecordFactory | None = None,
        profile: AgentTranscriptProfile | None = None,
        diagnostics: Sequence[AgentTranscriptOpenDiagnostic] = (),
        materialized: bool = True,
        materialization_policy: MaterializationPolicy | None = None,
        clock: Clock | None = None,
    ) -> None:
        if revision != len(repository.records):
            raise ValueError("transcript store revision must equal its record count")
        if repository.header.conversation_id != key.conversation_id:
            raise ValueError("conversation key and header id must match")
        self._backend = backend
        self._key = key
        self._repository = repository
        self._revision = revision
        self._record_factory = record_factory or AgentTranscriptRecordFactory()
        self._profile = profile or AgentTranscriptProfile.default()
        self._diagnostics = tuple(diagnostics)
        self._materialized = materialized
        self._materialization_policy = (
            materialization_policy or _default_materialization_policy
        )
        self._clock = clock or _utc_now
        self._commit_lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        backend: ConversationStore[ConversationHeader, AgentTranscriptRecord],
        key: ConversationKey,
        header: ConversationHeader,
        *,
        records: Sequence[AgentTranscriptRecord] = (),
        leaf_id: str | None = None,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
        record_factory: AgentTranscriptRecordFactory | None = None,
        profile: AgentTranscriptProfile | None = None,
        defer_materialization: bool = False,
        materialization_policy: MaterializationPolicy | None = None,
    ) -> AgentTranscriptUnitOfWork:
        _require_matching_identity(key, header)
        initial_records = tuple(records)
        repository = _create_repository(
            header=header,
            records=initial_records,
            leaf_id=leaf_id,
        )
        resolved_clock = clock or _utc_now
        if defer_materialization:
            if initial_records:
                raise ValueError(
                    "deferred transcript materialization requires no initial records"
                )
            return cls(
                backend=backend,
                key=key,
                repository=repository,
                revision=0,
                record_factory=record_factory
                or AgentTranscriptRecordFactory(
                    clock=resolved_clock,
                    id_factory=id_factory,
                ),
                profile=profile,
                materialized=False,
                materialization_policy=materialization_policy,
                clock=resolved_clock,
            )
        snapshot = await backend.create(
            key,
            header,
            initial_records,
            operation_id=_create_operation_id(key),
        )
        repository = ConversationRepository.from_snapshot(
            snapshot,
            record_id=lambda record: record.record_id,
            parent_id=lambda record: record.parent_id,
            leaf_id=leaf_id,
        )
        return cls(
            backend=backend,
            key=key,
            repository=repository,
            revision=snapshot.revision,
            record_factory=record_factory
            or AgentTranscriptRecordFactory(
                clock=resolved_clock,
                id_factory=id_factory,
            ),
            profile=profile,
            diagnostics=repository.diagnostics,
            materialization_policy=materialization_policy,
            clock=resolved_clock,
        )

    @classmethod
    async def load(
        cls,
        backend: ConversationStore[ConversationHeader, AgentTranscriptRecord],
        key: ConversationKey,
        *,
        leaf_id: str | None = None,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
        record_factory: AgentTranscriptRecordFactory | None = None,
        profile: AgentTranscriptProfile | None = None,
    ) -> AgentTranscriptUnitOfWork:
        resolved_clock = clock or _utc_now
        load_result = await backend.load(key)
        _require_matching_identity(key, load_result.snapshot.header)
        open_result = ConversationRepository.open(
            load_result,
            record_id=lambda record: record.record_id,
            parent_id=lambda record: record.parent_id,
            leaf_id=leaf_id,
        )
        repository = open_result.repository
        return cls(
            backend=backend,
            key=key,
            repository=repository,
            revision=load_result.snapshot.revision,
            record_factory=record_factory
            or AgentTranscriptRecordFactory(
                clock=resolved_clock,
                id_factory=id_factory,
            ),
            profile=profile,
            diagnostics=open_result.diagnostics,
            clock=resolved_clock,
        )

    @property
    def backend(
        self,
    ) -> ConversationStore[ConversationHeader, AgentTranscriptRecord]:
        return self._backend

    @property
    def key(self) -> ConversationKey:
        return self._key

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def is_materialized(self) -> bool:
        return self._materialized

    @property
    def header(self) -> ConversationHeader:
        return self._repository.header

    @property
    def records(self) -> tuple[AgentTranscriptRecord, ...]:
        return self._repository.records

    @property
    def diagnostics(self) -> tuple[AgentTranscriptOpenDiagnostic, ...]:
        return self._diagnostics

    @property
    def leaf_id(self) -> str | None:
        return self._repository.leaf_id

    def get(self, record_id: str) -> AgentTranscriptRecord | None:
        return self._repository.get(record_id)

    def leaf(self) -> AgentTranscriptRecord | None:
        return self._repository.leaf()

    def children(self, record_id: str) -> tuple[AgentTranscriptRecord, ...]:
        return self._repository.children(record_id)

    def branch(self, record_id: str) -> None:
        self._require_idle_commit("select a transcript branch")
        self._repository.branch(record_id)

    def reset_branch(self) -> None:
        self._require_idle_commit("reset the transcript branch")
        self._repository.reset_branch()

    def tree(self) -> tuple[ConversationTreeNode[AgentTranscriptRecord], ...]:
        return self._repository.tree()

    def active_path(self) -> tuple[AgentTranscriptRecord, ...]:
        return self._repository.active_records()

    def records_to(self, record_id: str) -> tuple[AgentTranscriptRecord, ...]:
        return self._repository.records_to(record_id)

    def branch_delta(
        self,
        from_id: str,
        target_id: str,
    ) -> BranchDelta[AgentTranscriptRecord]:
        return self._repository.branch_delta(from_id, target_id)

    def replay_context(self) -> AgentTranscriptContext:
        return self._profile.replay(self.active_path())

    async def commit(self, record: AgentTranscriptRecord) -> AgentTranscriptCommit:
        """Durably append one prebuilt record, then advance runtime state."""

        async with self._commit_lock:
            return await self._finish_commit_atomically(record)

    async def append(
        self,
        kind: str,
        payload: AgentTranscriptPayload,
        *,
        payload_version: int = STANDARD_PAYLOAD_VERSION,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        async with self._commit_lock:
            record = self._record_factory.create(
                kind,
                payload,
                parent_id=self.leaf_id,
                payload_version=payload_version,
                metadata=metadata,
            )
            return await self._finish_commit_atomically(record)

    async def append_agent_message(
        self,
        message: Message,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(AGENT_MESSAGE_KIND, message, metadata=metadata)

    async def append_thinking_selection(
        self,
        selection: ThinkingSelectionSnapshot,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(THINKING_SELECTION_KIND, selection, metadata=metadata)

    async def append_model_selection(
        self,
        selection: ModelSelectionSnapshot,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(MODEL_SELECTION_KIND, selection, metadata=metadata)

    async def append_command_execution(
        self,
        command: CommandExecutionRecord,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(COMMAND_EXECUTION_KIND, command, metadata=metadata)

    async def append_compaction_checkpoint(
        self,
        checkpoint: ContextCompactionCheckpoint,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(
            CONTEXT_COMPACTION_CHECKPOINT_KIND,
            checkpoint,
            metadata=metadata,
        )

    async def append_branch_summary(
        self,
        summary: BranchContextSummary,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(
            CONTEXT_BRANCH_SUMMARY_KIND, summary, metadata=metadata
        )

    async def append_application_message(
        self,
        message: ApplicationMessage,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(APPLICATION_MESSAGE_KIND, message, metadata=metadata)

    async def append_extension_data(
        self,
        data: ExtensionData,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(EXTENSION_DATA_KIND, data, metadata=metadata)

    async def append_annotation_patch(
        self,
        patch: RecordAnnotationPatch,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(RECORD_ANNOTATION_PATCH_KIND, patch, metadata=metadata)

    async def append_metadata_patch(
        self,
        patch: ConversationMetadataPatch,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> AgentTranscriptCommit:
        return await self.append(
            CONVERSATION_METADATA_PATCH_KIND,
            patch,
            metadata=metadata,
        )

    async def fork(
        self,
        target_key: ConversationKey,
        header: ConversationHeader,
        *,
        leaf_id: str | None = None,
    ) -> AgentTranscriptUnitOfWork:
        async with self._commit_lock:
            selected_id = self.leaf_id if leaf_id is None else leaf_id
            records = self.records_to(selected_id) if selected_id is not None else ()
            return await type(self).create(
                self._backend,
                target_key,
                header,
                records=records,
                leaf_id=records[-1].record_id if records else None,
                record_factory=self._record_factory,
                profile=self._profile,
            )

    async def _commit_locked(
        self,
        record: AgentTranscriptRecord,
    ) -> AgentTranscriptCommit:
        if record.parent_id != self.leaf_id:
            raise ValueError(
                "transcript record parent must match the selected leaf: "
                f"expected {self.leaf_id!r}, got {record.parent_id!r}"
            )
        candidate = _create_repository(
            header=self.header,
            records=(*self.records, record),
            leaf_id=record.record_id,
        )
        if not self._materialized:
            if not self._materialization_policy(record):
                self._repository = candidate
                self._revision += 1
                return AgentTranscriptCommit(record=record, receipt=None)
            return await self._materialize_locked(record, candidate)
        expected_revision = self._revision
        try:
            commit_result = await self._backend.append(
                self._key,
                record,
                expected_revision=expected_revision,
                operation_id=record.record_id,
            )
        except StoreCommitOutcomeUnknown:
            commit_result = await self._backend.append(
                self._key,
                record,
                expected_revision=expected_revision,
                operation_id=record.record_id,
            )
        receipt = commit_result.receipt
        next_revision = expected_revision + 1
        if receipt.revision != next_revision:
            raise RuntimeError(
                "conversation backend returned an invalid append revision: "
                f"expected {next_revision}, got {receipt.revision}"
            )
        if receipt.record_id not in {None, record.record_id}:
            raise RuntimeError(
                "conversation backend returned a different committed record id"
            )
        self._repository = candidate
        self._revision = receipt.revision
        self._diagnostics = (*self._diagnostics, *commit_result.diagnostics)
        return AgentTranscriptCommit(
            record=record,
            receipt=receipt,
            diagnostics=commit_result.diagnostics,
        )

    async def _finish_commit_atomically(
        self,
        record: AgentTranscriptRecord,
    ) -> AgentTranscriptCommit:
        """Finish an accepted commit before releasing the lock.

        Once the caller owns ``_commit_lock``, a successful durable write wins
        over cancellation.  The owned child keeps the backend result and the
        in-memory repository/revision update in one cancellation-atomic region.
        Explicitly suppressed cancellation requests are removed so callers do
        not continue with a stale ``Task.cancelling()`` count.
        """

        operation = asyncio.create_task(self._commit_locked(record))
        caller = asyncio.current_task()
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                if caller is not None and caller.cancelling():
                    while caller.cancelling():
                        caller.uncancel()
                    continue
                if operation.done():
                    break
                raise
        return operation.result()

    async def _materialize_locked(
        self,
        record: AgentTranscriptRecord,
        candidate: ConversationRepository[
            ConversationHeader,
            AgentTranscriptRecord,
        ],
    ) -> AgentTranscriptCommit:
        diagnostics: tuple[ConversationSourceDiagnostic, ...] = ()
        try:
            snapshot = await self._backend.create(
                self._key,
                self.header,
                candidate.records,
                operation_id=_create_operation_id(self._key),
            )
        except StoreCommitOutcomeUnknown as error:
            try:
                loaded = await self._backend.load(self._key)
            except Exception:
                raise error
            snapshot = loaded.snapshot
            diagnostics = loaded.diagnostics
            if snapshot.header != self.header or snapshot.records != candidate.records:
                raise error
        if (
            snapshot.header != self.header
            or snapshot.records != candidate.records
            or snapshot.revision != len(candidate.records)
        ):
            raise RuntimeError(
                "conversation backend returned an invalid materialized snapshot"
            )
        receipt = CommitReceipt(
            revision=snapshot.revision,
            committed_at=self._clock(),
            record_id=record.record_id,
        )
        self._repository = candidate
        self._revision = snapshot.revision
        self._materialized = True
        self._diagnostics = (*self._diagnostics, *diagnostics)
        return AgentTranscriptCommit(
            record=record,
            receipt=receipt,
            diagnostics=diagnostics,
        )

    def _require_idle_commit(self, operation: str) -> None:
        if self._commit_lock.locked():
            raise RuntimeError(f"cannot {operation} while a commit is in progress")


def _create_repository(
    *,
    header: ConversationHeader,
    records: Sequence[AgentTranscriptRecord],
    leaf_id: str | None,
) -> ConversationRepository[ConversationHeader, AgentTranscriptRecord]:
    return ConversationRepository.create(
        header=header,
        records=records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        leaf_id=leaf_id,
    )


def _require_matching_identity(
    key: ConversationKey,
    header: ConversationHeader,
) -> None:
    if header.conversation_id != key.conversation_id:
        raise ValueError("conversation key and header id must match")


def _create_operation_id(key: ConversationKey) -> str:
    return f"create:{key.namespace}:{key.conversation_id}"


def _default_materialization_policy(record: AgentTranscriptRecord) -> bool:
    if record.kind == APPLICATION_MESSAGE_KIND:
        return True
    return record.kind == AGENT_MESSAGE_KIND and isinstance(record.payload, UserMessage)


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "AgentTranscriptCommit",
    "AgentTranscriptOpenDiagnostic",
    "AgentTranscriptUnitOfWork",
    "MaterializationPolicy",
]
