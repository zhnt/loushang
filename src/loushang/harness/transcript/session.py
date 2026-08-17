"""Session-facing operations for one optional Agent transcript profile.

``AgentTranscriptUnitOfWork`` owns durable records and revisions. This class
owns the shared session-facing operations built on that store: standard record
append helpers, application-message commit observation, labels, and selected
branch context. Product code remains responsible for storage selection,
session directories, summaries, and lifecycle policy.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from loushang.ai.types import AssistantMessage, ToolResultMessage, UserMessage
from loushang.foundation.json import require_json_value
from loushang.harness.conversation import (
    BranchDelta,
    CommandExecutionRecord,
    ConversationHeader,
)
from loushang.harness.transcript.committer import (
    CommitResult,
    TranscriptCommitter,
)
from loushang.harness.transcript.kinds import RECORD_ANNOTATION_PATCH_KIND
from loushang.harness.transcript.model_call import (
    ModelCallInvocationProjection,
    project_model_call_invocations,
)
from loushang.harness.transcript.model_input import (
    ModelInputCommitContext as _ModelInputCommitContext,
)
from loushang.harness.transcript.model_input import (
    ModelInputRuntimeReferences,
    ModelInputTranscriptCommitter,
    RebuiltModelInput,
    rebuild_model_input,
)
from loushang.harness.transcript.types import (
    AgentTranscriptContext,
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
from loushang.harness.transcript.unit_of_work import (
    AgentTranscriptCommit,
    AgentTranscriptUnitOfWork,
)

CommitObserver = Callable[[CommitResult], None]
ApplicationMessageIdFactory = Callable[[], str]
Clock = Callable[[], datetime]
_LEAF_UNSET = object()


class AgentTranscriptSession:
    """Shared session operations over one durable Agent transcript store."""

    def __init__(
        self,
        *,
        transcript: AgentTranscriptUnitOfWork,
        labels_by_target_id: dict[str, str] | None = None,
        label_timestamps_by_target_id: dict[str, str] | None = None,
        application_message_id_factory: ApplicationMessageIdFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._transcript = transcript
        self.labels_by_target_id = dict(labels_by_target_id or {})
        self.label_timestamps_by_target_id = dict(label_timestamps_by_target_id or {})
        self._application_message_id_factory = (
            application_message_id_factory or _default_id
        )
        self._clock = clock or _utc_now
        self._committer = TranscriptCommitter(transcript)
        self._commit_observer: CommitObserver | None = None

    def set_commit_observer(self, observer: CommitObserver | None) -> None:
        """Observe durable commits without participating in commit success."""

        self._commit_observer = observer

    @property
    def is_materialized(self) -> bool:
        return self._transcript.is_materialized

    @property
    def header(self) -> ConversationHeader:
        return self._transcript.header

    @property
    def entries(self) -> list[AgentTranscriptRecord]:
        return list(self._transcript.records)

    @property
    def by_id(self) -> dict[str, AgentTranscriptRecord]:
        return {entry.record_id: entry for entry in self._transcript.records}

    @property
    def leaf_id(self) -> str | None:
        return self._transcript.leaf_id

    @leaf_id.setter
    def leaf_id(self, value: str | None) -> None:
        if value is None:
            self._transcript.reset_branch()
        else:
            self._transcript.branch(value)

    def get_entry(self, entry_id: str) -> AgentTranscriptRecord | None:
        return self._transcript.get(entry_id)

    def get_header(self) -> ConversationHeader:
        return self.header

    def get_leaf_id(self) -> str | None:
        return self.leaf_id

    def get_leaf_entry(self) -> AgentTranscriptRecord | None:
        return self._transcript.leaf()

    def get_entries(self) -> list[AgentTranscriptRecord]:
        return list(self.entries)

    def get_children(self, parent_id: str) -> list[AgentTranscriptRecord]:
        return list(self._transcript.children(parent_id))

    def get_tree(self) -> Sequence[object]:
        """Return the current record tree for product-neutral inspection."""

        return list(self._transcript.tree())

    def get_label(self, entry_id: str) -> str | None:
        return self.labels_by_target_id.get(entry_id)

    def get_branch(
        self, leaf_id: str | None | object = _LEAF_UNSET
    ) -> list[AgentTranscriptRecord]:
        if leaf_id is _LEAF_UNSET:
            return list(self._transcript.active_path())
        if not isinstance(leaf_id, str):
            return []
        if self._transcript.get(leaf_id) is None:
            raise ValueError(f"Entry {leaf_id} not found")
        return list(self._transcript.records_to(leaf_id))

    def get_branch_delta(
        self,
        from_id: str,
        target_id: str,
    ) -> BranchDelta[AgentTranscriptRecord]:
        return self._transcript.branch_delta(from_id, target_id)

    def branch(self, branch_from_id: str) -> None:
        if self._transcript.get(branch_from_id) is None:
            raise ValueError(f"Entry {branch_from_id} not found")
        self._transcript.branch(branch_from_id)

    def reset_leaf(self) -> None:
        self._transcript.reset_branch()

    async def branch_with_summary(
        self,
        branch_from_id: str | None,
        summary: str,
        details: object | None = None,
        from_hook: bool | None = None,
        model_input_snapshot_ids: tuple[str, ...] = (),
    ) -> str:
        if branch_from_id is not None and self._transcript.get(branch_from_id) is None:
            raise ValueError(f"Entry {branch_from_id} not found")
        previous_leaf_id = self.leaf_id
        self.leaf_id = branch_from_id
        try:
            return self._complete_commit(
                await self._transcript.append_branch_summary(
                    BranchContextSummary(
                        from_record_id=branch_from_id or "root",
                        summary=summary,
                        details=require_json_value(
                            details,
                            name="branch_summary.details",
                        ),
                        from_hook=from_hook,
                        model_input_snapshot_ids=model_input_snapshot_ids,
                    )
                )
            )
        except Exception:
            self.leaf_id = previous_leaf_id
            raise

    async def append_entry(self, entry: AgentTranscriptRecord) -> str:
        commit = await self._transcript.commit(entry)
        if entry.kind == RECORD_ANNOTATION_PATCH_KIND:
            self._record_label_entry(entry)
        return self._complete_commit(commit)

    async def append_message(self, message: object) -> str:
        if isinstance(message, ApplicationMessage):
            return (await self.commit_application_message(message)).record_id
        if isinstance(message, CommandExecutionRecord):
            return self._complete_commit(
                await self._transcript.append_command_execution(message)
            )
        if isinstance(message, UserMessage | AssistantMessage | ToolResultMessage):
            return self._complete_commit(
                await self._transcript.append_agent_message(message)
            )
        raise TypeError(f"Unsupported transcript message: {type(message)!r}")

    async def commit_application_message(
        self,
        message: ApplicationMessage,
    ) -> CommitResult:
        result = await self._committer.commit_application_message(message)
        if result.disposition == "committed":
            self._notify_commit(result)
        return result

    async def append_thinking_level_change(self, thinking_level: str) -> str:
        return self._complete_commit(
            await self._transcript.append_thinking_selection(
                ThinkingSelectionSnapshot(level=thinking_level)
            )
        )

    async def append_model_change(
        self,
        provider: str,
        model_id: str,
        *,
        endpoint_id: str,
    ) -> str:
        return self._complete_commit(
            await self._transcript.append_model_selection(
                ModelSelectionSnapshot(
                    provider=provider,
                    endpoint_id=endpoint_id,
                    model_id=model_id,
                )
            )
        )

    async def append_compaction(
        self,
        summary: str,
        first_kept_entry_id: str,
        tokens_before: int,
        details: object | None = None,
        from_hook: bool | None = None,
        model_input_snapshot_ids: tuple[str, ...] = (),
    ) -> str:
        return self._complete_commit(
            await self._transcript.append_compaction_checkpoint(
                ContextCompactionCheckpoint(
                    summary=summary,
                    first_kept_record_id=first_kept_entry_id,
                    tokens_before=tokens_before,
                    details=require_json_value(details, name="compaction.details"),
                    from_hook=from_hook,
                    model_input_snapshot_ids=model_input_snapshot_ids,
                )
            )
        )

    async def append_extension_data(
        self,
        extension_type: str,
        data: object | None = None,
    ) -> str:
        return self._complete_commit(
            await self._transcript.append_extension_data(
                ExtensionData(
                    extension_type=extension_type,
                    data=require_json_value(data, name="extension_data.data"),
                )
            )
        )

    async def append_custom_message_entry(
        self,
        custom_type: str,
        content: str | list[object],
        display: bool,
        details: object | None = None,
    ) -> str:
        message = ApplicationMessage(
            application_message_id=self._application_message_id_factory(),
            custom_type=custom_type,
            content=content,  # type: ignore[arg-type]
            details=require_json_value(details, name="custom_message.details"),
            display=display,
            timestamp=self._clock().timestamp(),
        )
        return self._complete_application_commit(
            await self._committer.commit_application_message(message)
        )

    async def append_label(self, target_id: str, label: str | None) -> str:
        if self._transcript.get(target_id) is None:
            raise ValueError(f"Entry {target_id} not found")
        normalized = _normalize_nonblank(label)
        commit = await self._transcript.append_annotation_patch(
            RecordAnnotationPatch(
                target_record_id=target_id,
                namespace="display.label",
                operation="set" if normalized is not None else "remove",
                value=normalized,
            )
        )
        self._record_label_entry(commit.record)
        return self._complete_commit(commit)

    async def append_conversation_name(self, name: str | None) -> str:
        normalized = _normalize_nonblank(name)
        patch = (
            ConversationMetadataPatch(values={"name": normalized})
            if normalized is not None
            else ConversationMetadataPatch(removed_keys=("name",))
        )
        return self._complete_commit(
            await self._transcript.append_metadata_patch(patch)
        )

    def build_context(self) -> AgentTranscriptContext:
        return self._transcript.replay_context()

    def create_model_input_committer(
        self,
        *,
        purpose: str,
        logical_input: dict[str, object],
        runtime_references: ModelInputRuntimeReferences,
    ) -> ModelInputTranscriptCommitter:
        """Capture one fresh Model Input boundary without exposing the Store."""

        source_leaf_id = self._transcript.leaf_id
        if source_leaf_id is None:
            raise RuntimeError(
                "Model Input requires committed logical facts in the transcript"
            )
        return ModelInputTranscriptCommitter(
            transcript=self._transcript,
            context=_ModelInputCommitContext(
                purpose=purpose,
                source_leaf_id=source_leaf_id,
                source_revision=self._transcript.revision,
                logical_input=logical_input,
            ),
            runtime_references=runtime_references,
        )

    def rebuild_model_input(self, snapshot_id: str) -> RebuiltModelInput:
        """Reconstruct one committed request through the Session boundary."""

        return rebuild_model_input(self._transcript, snapshot_id)

    def get_model_call_invocations(
        self,
    ) -> tuple[ModelCallInvocationProjection, ...]:
        """Project prepared attempts and known outcomes on the selected path."""

        return project_model_call_invocations(self._transcript.active_path())

    def _complete_commit(self, commit: AgentTranscriptCommit) -> str:
        result = CommitResult(
            record_id=commit.record.record_id,
            disposition="committed" if commit.receipt is not None else "staged",
            receipt=commit.receipt,
        )
        if result.disposition == "committed":
            self._notify_commit(result)
        return result.record_id

    def _complete_application_commit(self, result: CommitResult) -> str:
        if result.disposition == "committed":
            self._notify_commit(result)
        return result.record_id

    def _notify_commit(self, result: CommitResult) -> None:
        observer = self._commit_observer
        if observer is not None:
            observer(result)

    def _record_label_entry(self, entry: AgentTranscriptRecord) -> None:
        patch = entry.payload
        if not isinstance(patch, RecordAnnotationPatch):
            return
        if patch.namespace != "display.label":
            return
        if patch.operation == "set" and isinstance(patch.value, str):
            self.labels_by_target_id[patch.target_record_id] = patch.value
            self.label_timestamps_by_target_id[patch.target_record_id] = (
                entry.created_at
            )
            return
        self.labels_by_target_id.pop(patch.target_record_id, None)
        self.label_timestamps_by_target_id.pop(patch.target_record_id, None)


def _normalize_nonblank(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _default_id() -> str:
    return uuid4().hex


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "AgentTranscriptSession",
    "ApplicationMessageIdFactory",
    "Clock",
    "CommitObserver",
]
