from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from loushang.ai.types import Message, UserMessage
from loushang.foundation.json import JSONValue
from loushang.harness.conversation import (
    CommitReceipt,
    ConversationBatchStore,
    ConversationDiagnostic,
    ConversationKey,
    ConversationSourceDiagnostic,
    ConversationStore,
    StoreCommitOutcomeUnknown,
)
from loushang.harness.conversation.jsonl_codec import ConversationJsonlRecordCodec
from loushang.harness.conversation.repository import ConversationRepository
from loushang.harness.conversation.types import (
    BranchDelta,
    CommandExecutionRecord,
    ConversationHeader,
    ConversationTreeNode,
)
from loushang.harness.journal import DEFAULT_JSONL_FORMAT
from loushang.harness.transcript.codecs import STANDARD_PAYLOAD_VERSION
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    COMMAND_EXECUTION_KIND,
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    EXTENSION_DATA_KIND,
    MODEL_CALL_OUTCOME_KIND,
    MODEL_INPUT_COMPONENT_KIND,
    MODEL_INPUT_PREPARED_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    THINKING_SELECTION_KIND,
)
from loushang.harness.transcript.model_call_types import ModelCallOutcome
from loushang.harness.transcript.model_input_types import (
    MODEL_INPUT_MAX_ENCODED_RECORD_BYTES,
    ModelInputComponent,
    ModelInputIntegrityError,
    ModelInputRecordSizeError,
    ModelInputSnapshot,
)
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
    ModelInputNodeBundle,
    ModelInputSnapshotV2,
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
        resolved_profile = profile or AgentTranscriptProfile.default()
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
                profile=resolved_profile,
                materialized=False,
                materialization_policy=materialization_policy,
                clock=resolved_clock,
            )
        for record in initial_records:
            _require_model_input_record_size(record, resolved_profile)
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
            profile=resolved_profile,
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

    async def commit_batch(
        self,
        records: Sequence[AgentTranscriptRecord],
    ) -> tuple[AgentTranscriptCommit, ...]:
        """Durably append one parent-linked batch, then advance runtime state."""

        async with self._commit_lock:
            return await self._finish_batch_commit_atomically(records)

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

    def _require_record_model_input_lineage(
        self,
        record: AgentTranscriptRecord,
    ) -> None:
        if record.kind == CONTEXT_COMPACTION_CHECKPOINT_KIND and isinstance(
            record.payload,
            ContextCompactionCheckpoint,
        ):
            self._require_model_input_lineage(
                record.payload.model_input_snapshot_ids,
                purposes={
                    "compaction_history",
                    "compaction_merge",
                    "compaction_turn_prefix",
                },
                owner="compaction checkpoint",
            )
        elif record.kind == CONTEXT_BRANCH_SUMMARY_KIND and isinstance(
            record.payload,
            BranchContextSummary,
        ):
            self._require_model_input_lineage(
                record.payload.model_input_snapshot_ids,
                purposes={"branch_summary"},
                owner="branch summary",
            )
        elif record.kind == MODEL_CALL_OUTCOME_KIND and isinstance(
            record.payload,
            ModelCallOutcome,
        ):
            self._require_model_call_outcome(record.payload)

    def _require_model_call_outcome(self, outcome: ModelCallOutcome) -> None:
        if any(
            isinstance(record.payload, ModelCallOutcome)
            and record.payload.invocation_id == outcome.invocation_id
            for record in self.records
        ):
            raise ModelInputIntegrityError(
                "model call invocation already has a terminal outcome"
            )
        active_path = self.active_path()
        invocation_snapshots = tuple(
            record.payload
            for record in active_path
            if isinstance(record.payload, ModelInputSnapshot | ModelInputSnapshotV2)
            and record.payload.invocation_id == outcome.invocation_id
        )
        expected_snapshot_ids = tuple(
            snapshot.snapshot_id for snapshot in invocation_snapshots
        )
        if outcome.model_input_snapshot_ids != expected_snapshot_ids:
            raise ModelInputIntegrityError(
                "model call outcome does not reference the complete ordered "
                "Model Input attempt sequence"
            )

    def _require_model_input_lineage(
        self,
        snapshot_ids: tuple[str, ...],
        *,
        purposes: set[str],
        owner: str,
    ) -> None:
        if not snapshot_ids:
            return
        # Local import avoids reversing model_input's UnitOfWork dependency.
        from loushang.harness.transcript.model_input import rebuild_model_input

        for snapshot_id in snapshot_ids:
            rebuilt = rebuild_model_input(self, snapshot_id)
            if rebuilt.snapshot.purpose not in purposes:
                allowed = ", ".join(sorted(purposes))
                raise ModelInputIntegrityError(
                    f"{owner} Model Input lineage {snapshot_id!r} has purpose "
                    f"{rebuilt.snapshot.purpose!r}; expected one of: {allowed}"
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

    async def append_model_input_component(
        self,
        component: ModelInputComponent,
        *,
        max_encoded_record_bytes: int,
        expected_revision: int,
        expected_leaf_id: str,
    ) -> AgentTranscriptCommit:
        return await self._append_model_input_fact(
            MODEL_INPUT_COMPONENT_KIND,
            component,
            max_encoded_record_bytes=max_encoded_record_bytes,
            expected_revision=expected_revision,
            expected_leaf_id=expected_leaf_id,
        )

    async def append_model_input_components(
        self,
        components: Sequence[ModelInputComponent],
        *,
        max_encoded_record_bytes: int,
        expected_revision: int,
        expected_leaf_id: str,
    ) -> tuple[AgentTranscriptCommit, ...]:
        async with self._commit_lock:
            if not components:
                return ()
            if self.revision != expected_revision or self.leaf_id != expected_leaf_id:
                raise ModelInputIntegrityError(
                    "transcript changed outside the Model Input commit sequence"
                )
            parent_id = expected_leaf_id
            records: list[AgentTranscriptRecord] = []
            for component in components:
                record = self._record_factory.create(
                    MODEL_INPUT_COMPONENT_KIND,
                    component,
                    parent_id=parent_id,
                    payload_version=STANDARD_PAYLOAD_VERSION,
                )
                self._require_record_size(record, max_encoded_record_bytes)
                records.append(record)
                parent_id = record.record_id
            return await self._finish_batch_commit_atomically(
                records,
                propagate_cancellation=True,
            )

    async def append_model_input_node_bundles(
        self,
        bundles: Sequence[ModelInputNodeBundle],
        *,
        max_encoded_record_bytes: int,
        expected_revision: int,
        expected_leaf_id: str,
    ) -> tuple[AgentTranscriptCommit, ...]:
        async with self._commit_lock:
            if not bundles:
                return ()
            if self.revision != expected_revision or self.leaf_id != expected_leaf_id:
                raise ModelInputIntegrityError(
                    "transcript changed outside the Model Input commit sequence"
                )
            parent_id = expected_leaf_id
            records: list[AgentTranscriptRecord] = []
            for bundle in bundles:
                record = self._record_factory.create(
                    MODEL_INPUT_COMPONENT_KIND,
                    bundle,
                    parent_id=parent_id,
                    payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
                )
                self._require_record_size(record, max_encoded_record_bytes)
                records.append(record)
                parent_id = record.record_id
            return await self._finish_batch_commit_atomically(
                records,
                propagate_cancellation=True,
            )

    async def append_model_input_snapshot(
        self,
        snapshot: ModelInputSnapshot | ModelInputSnapshotV2,
        *,
        max_encoded_record_bytes: int,
        expected_revision: int,
        expected_leaf_id: str,
    ) -> AgentTranscriptCommit:
        return await self._append_model_input_fact(
            MODEL_INPUT_PREPARED_KIND,
            snapshot,
            payload_version=(
                MODEL_INPUT_V2_PAYLOAD_VERSION
                if isinstance(snapshot, ModelInputSnapshotV2)
                else STANDARD_PAYLOAD_VERSION
            ),
            max_encoded_record_bytes=max_encoded_record_bytes,
            expected_revision=expected_revision,
            expected_leaf_id=expected_leaf_id,
        )

    async def append_model_call_outcome(
        self,
        outcome: ModelCallOutcome,
        *,
        expected_revision: int,
        expected_leaf_id: str,
    ) -> AgentTranscriptCommit:
        async with self._commit_lock:
            if self.revision != expected_revision or self.leaf_id != expected_leaf_id:
                raise ModelInputIntegrityError(
                    "transcript changed outside the Model Input commit sequence"
                )
            record = self._record_factory.create(
                MODEL_CALL_OUTCOME_KIND,
                outcome,
                parent_id=expected_leaf_id,
                payload_version=STANDARD_PAYLOAD_VERSION,
            )
            return await self._finish_commit_atomically(
                record,
                propagate_cancellation=True,
            )

    async def _append_model_input_fact(
        self,
        kind: str,
        payload: ModelInputComponent | ModelInputSnapshot | ModelInputSnapshotV2,
        *,
        payload_version: int = STANDARD_PAYLOAD_VERSION,
        max_encoded_record_bytes: int,
        expected_revision: int,
        expected_leaf_id: str,
    ) -> AgentTranscriptCommit:
        async with self._commit_lock:
            if self.revision != expected_revision or self.leaf_id != expected_leaf_id:
                raise ModelInputIntegrityError(
                    "transcript changed outside the Model Input commit sequence"
                )
            record = self._record_factory.create(
                kind,
                payload,
                parent_id=expected_leaf_id,
                payload_version=payload_version,
            )
            self._require_record_size(record, max_encoded_record_bytes)
            return await self._finish_commit_atomically(
                record,
                propagate_cancellation=True,
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
            records = (
                self.records_for_fork(selected_id) if selected_id is not None else ()
            )
            return await type(self).create(
                self._backend,
                target_key,
                header,
                records=records,
                leaf_id=selected_id,
                record_factory=self._record_factory,
                profile=self._profile,
            )

    def records_for_fork(
        self,
        leaf_id: str,
    ) -> tuple[AgentTranscriptRecord, ...]:
        """Return one selected path plus explicitly referenced derivation facts."""

        selected = self.records_to(leaf_id)
        included_ids = {record.record_id for record in selected}
        pending_snapshot_ids = list(_summary_lineage_ids(selected))
        resolved_snapshot_ids: set[str] = set()
        while pending_snapshot_ids:
            snapshot_id = pending_snapshot_ids.pop()
            if snapshot_id in resolved_snapshot_ids:
                continue
            matches = [
                record
                for record in self.records
                if record.kind == MODEL_INPUT_PREPARED_KIND
                and isinstance(
                    record.payload, ModelInputSnapshot | ModelInputSnapshotV2
                )
                and record.payload.snapshot_id == snapshot_id
            ]
            if len(matches) != 1:
                raise ModelInputIntegrityError(
                    f"fork Model Input lineage {snapshot_id!r} is not uniquely available"
                )
            dependency_path = self.records_to(matches[0].record_id)
            included_ids.update(record.record_id for record in dependency_path)
            outcome_matches = [
                record
                for record in self.records
                if isinstance(record.payload, ModelCallOutcome)
                and snapshot_id in record.payload.model_input_snapshot_ids
            ]
            if len(outcome_matches) > 1:
                raise ModelInputIntegrityError(
                    f"fork Model Input outcome for {snapshot_id!r} is ambiguous"
                )
            resolved_snapshot_ids.add(snapshot_id)
            if outcome_matches:
                outcome_path = self.records_to(outcome_matches[0].record_id)
                included_ids.update(record.record_id for record in outcome_path)
                pending_snapshot_ids.extend(
                    lineage_id
                    for lineage_id in _summary_lineage_ids(outcome_path)
                    if lineage_id not in resolved_snapshot_ids
                )
            pending_snapshot_ids.extend(
                lineage_id
                for lineage_id in _summary_lineage_ids(dependency_path)
                if lineage_id not in resolved_snapshot_ids
            )
        return tuple(
            record for record in self.records if record.record_id in included_ids
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

    async def _commit_batch_locked(
        self,
        records: tuple[AgentTranscriptRecord, ...],
    ) -> tuple[AgentTranscriptCommit, ...]:
        if not records:
            return ()
        parent_id = self.leaf_id
        for record in records:
            if record.parent_id != parent_id:
                raise ValueError(
                    "transcript batch records must form one selected parent chain"
                )
            parent_id = record.record_id
        if not self._materialized or not isinstance(
            self._backend,
            ConversationBatchStore,
        ):
            commits: list[AgentTranscriptCommit] = []
            for record in records:
                commits.append(await self._commit_locked(record))
            return tuple(commits)

        candidate = _create_repository(
            header=self.header,
            records=(*self.records, *records),
            leaf_id=records[-1].record_id,
        )
        expected_revision = self._revision
        operation_ids = tuple(record.record_id for record in records)
        try:
            result = await self._backend.append_batch(
                self._key,
                records,
                expected_revision=expected_revision,
                operation_ids=operation_ids,
            )
        except StoreCommitOutcomeUnknown:
            result = await self._backend.append_batch(
                self._key,
                records,
                expected_revision=expected_revision,
                operation_ids=operation_ids,
            )
        if len(result.receipts) != len(records):
            raise RuntimeError("conversation backend returned an invalid batch size")
        batch_commits: list[AgentTranscriptCommit] = []
        for index, (record, receipt) in enumerate(
            zip(records, result.receipts, strict=True),
            start=1,
        ):
            expected_receipt_revision = expected_revision + index
            if receipt.revision != expected_receipt_revision:
                raise RuntimeError(
                    "conversation backend returned an invalid batch revision"
                )
            if receipt.record_id not in {None, record.record_id}:
                raise RuntimeError(
                    "conversation backend returned a different batch record id"
                )
            batch_commits.append(
                AgentTranscriptCommit(
                    record=record,
                    receipt=receipt,
                    diagnostics=(result.diagnostics if index == len(records) else ()),
                )
            )
        self._repository = candidate
        self._revision = result.receipts[-1].revision
        self._diagnostics = (*self._diagnostics, *result.diagnostics)
        return tuple(batch_commits)

    async def _finish_commit_atomically(
        self,
        record: AgentTranscriptRecord,
        *,
        propagate_cancellation: bool = False,
    ) -> AgentTranscriptCommit:
        """Finish an accepted commit before releasing the lock.

        Once the caller owns ``_commit_lock``, a successful durable write wins
        over cancellation.  The owned child keeps the backend result and the
        in-memory repository/revision update in one cancellation-atomic region.
        Explicitly suppressed cancellation requests are removed so callers do
        not continue with a stale ``Task.cancelling()`` count.
        """

        self._require_record_model_input_lineage(record)
        _require_model_input_record_size(record, self._profile)
        operation = asyncio.create_task(self._commit_locked(record))
        caller = asyncio.current_task()
        cancellation_requested = False
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                if caller is not None and caller.cancelling():
                    cancellation_requested = True
                    while caller.cancelling():
                        caller.uncancel()
                    continue
                if operation.done():
                    break
                raise
        result = operation.result()
        if cancellation_requested and propagate_cancellation:
            raise asyncio.CancelledError
        return result

    async def _finish_batch_commit_atomically(
        self,
        records: Sequence[AgentTranscriptRecord],
        *,
        propagate_cancellation: bool = False,
    ) -> tuple[AgentTranscriptCommit, ...]:
        durable_records = tuple(records)
        if not durable_records:
            return ()
        for record in durable_records:
            self._require_record_model_input_lineage(record)
            _require_model_input_record_size(record, self._profile)
        operation = asyncio.create_task(self._commit_batch_locked(durable_records))
        caller = asyncio.current_task()
        cancellation_requested = False
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                if caller is not None and caller.cancelling():
                    cancellation_requested = True
                    while caller.cancelling():
                        caller.uncancel()
                    continue
                if operation.done():
                    break
                raise
        result = operation.result()
        if cancellation_requested and propagate_cancellation:
            raise asyncio.CancelledError
        return result

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

    def _require_record_size(
        self,
        record: AgentTranscriptRecord,
        maximum: int,
    ) -> None:
        _require_encoded_record_size(record, maximum, self._profile)


def _require_model_input_record_size(
    record: AgentTranscriptRecord,
    profile: AgentTranscriptProfile,
) -> None:
    if record.kind in {
        MODEL_CALL_OUTCOME_KIND,
        MODEL_INPUT_COMPONENT_KIND,
        MODEL_INPUT_PREPARED_KIND,
    }:
        _require_encoded_record_size(
            record,
            MODEL_INPUT_MAX_ENCODED_RECORD_BYTES,
            profile,
        )


def _summary_lineage_ids(
    records: Sequence[AgentTranscriptRecord],
) -> tuple[str, ...]:
    return tuple(
        snapshot_id
        for record in records
        if isinstance(
            record.payload,
            ContextCompactionCheckpoint | BranchContextSummary,
        )
        for snapshot_id in record.payload.model_input_snapshot_ids
    )


def _require_encoded_record_size(
    record: AgentTranscriptRecord,
    maximum: int,
    profile: AgentTranscriptProfile,
) -> None:
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise ValueError("maximum encoded record bytes must be positive")
    codec = ConversationJsonlRecordCodec(profile.payload_codecs)
    envelope = codec.encode_record(record)
    jsonl_format = DEFAULT_JSONL_FORMAT
    line = (
        json.dumps(
            envelope,
            ensure_ascii=jsonl_format.ensure_ascii,
            sort_keys=jsonl_format.sort_keys,
            separators=jsonl_format.separators,
            allow_nan=False,
        )
        + jsonl_format.newline
    )
    encoded_size = len(line.encode(jsonl_format.encoding))
    if encoded_size > maximum:
        raise ModelInputRecordSizeError(
            f"{record.kind} encoded record is {encoded_size} bytes; limit is {maximum}"
        )


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
