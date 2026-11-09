"""Opt-in continuation of an owned Product transcript, not a wire schema.

Borrowed logical views identify history and fixed commits. They grant no live
execution authority; Product codecs retain namespace/version and owner policy.
The original Transcript owner still performs all writes, blobs and lookups.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import ClassVar, Generic, Protocol, TypeVar, cast

from loushang.ai.types import UserMessage
from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.conversation import ConversationRecord, StoreCommitOutcomeUnknown

from .committer import CommitResult, PrebuiltUserMessageLookupResult
from .product_session import BindingInputT, ProductBindingT, ProductTranscriptSession
from .types import AgentTranscriptRecord, ExtensionData


class _ResumeIntentRead(Protocol):
    @property
    def attempt_id(self) -> str: ...

    @property
    def request_id(self) -> str: ...

    @property
    def session_id(self) -> str: ...

    @property
    def original_leaf_id(self) -> str | None: ...

    @property
    def ancestry_digest(self) -> str: ...

    @property
    def plan_fingerprint(self) -> str: ...


class _ResumePlanRead(Protocol):
    @property
    def plan_id(self) -> str: ...

    @property
    def session_id(self) -> str: ...

    @property
    def selected_leaf_id(self) -> str | None: ...

    @property
    def ancestry_digest(self) -> str | None: ...


IntentT = TypeVar("IntentT", bound=_ResumeIntentRead)
IntentCo = TypeVar("IntentCo", bound=_ResumeIntentRead, covariant=True)
BindingT = TypeVar("BindingT")
BindingCo = TypeVar("BindingCo", covariant=True)
BindingContra = TypeVar("BindingContra", contravariant=True)
PlanT = TypeVar("PlanT", bound=_ResumePlanRead)


class _ResumeProjection(Protocol[IntentCo]):
    """Product-classified historical facts; never present admission."""

    @property
    def status(self) -> str: ...
    @property
    def attempt(self) -> IntentCo | None: ...
    @property
    def record_id(self) -> str | None: ...
    @property
    def ancestry_digest(self) -> str: ...
    @property
    def binding_status(self) -> str: ...
    @property
    def binding_record_id(self) -> str | None: ...


class _ResumePendingInput(Protocol[IntentCo, BindingCo]):
    """Borrow original data; only metadata/record/outcome fields are writable."""

    @property
    def expected_message(self) -> UserMessage: ...
    @property
    def expected_message_digest(self) -> str: ...
    @property
    def prepare_binding(self) -> Callable[[UserMessage], BindingCo]: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def original_leaf_id(self) -> str | None: ...
    @property
    def commit_parent_id(self) -> str: ...
    @property
    def attempt_id(self) -> str: ...
    @property
    def attempt(self) -> IntentCo: ...
    @property
    def revision(self) -> int: ...
    @property
    def ancestry_digest(self) -> str: ...
    @property
    def lock(self) -> asyncio.Lock: ...

    expected_metadata: dict[str, JSONValue] | None
    prepared_record: AgentTranscriptRecord | None
    outcome_unknown: bool


class _ResumeMessageCodec(Protocol):
    def freeze_input(self, message: UserMessage) -> UserMessage: ...
    def input_digest(self, message: UserMessage) -> str: ...
    def record_digest(self, record: AgentTranscriptRecord) -> str: ...


class _ResumeRecordCodec(Protocol[IntentT, BindingContra]):
    def validate_attempt(self, record: AgentTranscriptRecord) -> IntentT: ...
    def prepare_attempt(
        self, attempt: IntentT, *, created_at: datetime
    ) -> AgentTranscriptRecord: ...
    def prepare_first_input_record(
        self,
        pending: _ResumePendingInput[IntentT, BindingContra],
        persisted: UserMessage,
        *,
        read_session_id: Callable[[], str],
        resource_metadata: dict[str, JSONValue],
    ) -> AgentTranscriptRecord: ...


class _ResumeProjector(Protocol[IntentCo]):
    def __call__(
        self, records: Iterable[AgentTranscriptRecord], *, current_session_id: str
    ) -> _ResumeProjection[IntentCo]: ...


class _AsyncResumeProjector(Protocol[IntentCo]):
    def __call__(
        self, records: Iterable[AgentTranscriptRecord], *, current_session_id: str
    ) -> Awaitable[_ResumeProjection[IntentCo]]: ...


class _ResumeHistory(Protocol[IntentCo]):
    @property
    def project(self) -> _ResumeProjector[IntentCo]: ...
    @property
    def project_async(self) -> _AsyncResumeProjector[IntentCo]: ...


class _ResumeContinuationTranscript(
    ProductTranscriptSession[BindingInputT, ProductBindingT],
    Generic[BindingInputT, ProductBindingT, IntentT, BindingT, PlanT],
):
    """Fixed local continuation program on the original Product Session object.

    Only an explicit Product binding selects this internal profile. The base
    ProductTranscriptSession and its default Writer contracts stay unchanged.
    """

    _resume_messages: ClassVar[_ResumeMessageCodec]
    _resume_records: _ResumeRecordCodec[IntentT, BindingT]
    _resume_history: _ResumeHistory[IntentT]
    _resume_pending_type: type[_ResumePendingInput[IntentT, BindingT]]
    _resume_recovery_error: ClassVar[type[RuntimeError]]
    _resume_label: ClassVar[str]

    _resume_first_input: _ResumePendingInput[IntentT, BindingT] | None = None
    _resume_runtime_publication_pending: bool = False
    _resume_writer_plan: PlanT | None = None
    _resume_committed_attempt: tuple[IntentT, str] | None = None
    _resume_committed_plan: PlanT | None = None
    _resume_committed_input: tuple[IntentT, AgentTranscriptRecord, str] | None = None
    _activation_guard_snapshot: tuple[int, str | None] | None = None
    _activation_guard_path: tuple[AgentTranscriptRecord, ...] | None = None
    _activation_guard_fingerprints: (
        tuple[tuple[AgentTranscriptRecord, str], ...] | None
    ) = None
    _activation_guard_binding_record_id: str | None = None

    def _require_ordinary_input_policy(self, message: object) -> None:
        """Product policy at the ordinary-only boundary; staged input bypasses it."""

    @staticmethod
    def _activation_neutral_record(record: AgentTranscriptRecord) -> bool:
        raise NotImplementedError("The Product must classify neutral records")

    @property
    def resume_runtime_publication_pending(self) -> bool:
        """Local readiness only; historical Binding cannot prove publication."""

        return self._resume_runtime_publication_pending

    async def _commit_resume_activation_intent(
        self,
        record: AgentTranscriptRecord,
    ) -> CommitResult:
        """Fence execution before the admitted owner's first durable intent.

        The caller still owns live subject/policy validation and effect
        settlement. This is the initial intent route, not a retry or recovery
        admission. Transcript retains the original Writer and fixed-ID commit.
        """

        if not self.persist or not self._transcript.is_materialized:
            raise ValueError(
                f"{self._resume_label} intent requires a materialized Writer"
            )
        attempt = self._resume_records.validate_attempt(record)
        writer_plan = self._resume_writer_plan
        if writer_plan is None:
            self.require_no_unsettled_resume_activation()
        else:
            existing = self._resume_history.project(
                self._transcript.active_path(),
                current_session_id=self.get_header().conversation_id,
            )
            if (
                existing.status != "none"
                or existing.binding_status == "unknown_version"
            ):
                raise self._resume_recovery_error("activation.recovery_required")
            if (
                attempt.plan_fingerprint != writer_plan.plan_id
                or attempt.session_id != writer_plan.session_id
                or attempt.original_leaf_id != writer_plan.selected_leaf_id
                or attempt.ancestry_digest != writer_plan.ancestry_digest
            ):
                raise ValueError(
                    f"{self._resume_label} intent differs from its prepared Writer Plan"
                )
        frozen = self._resume_records.prepare_attempt(
            attempt,
            created_at=datetime.fromisoformat(record.created_at.replace("Z", "+00:00")),
        )
        if frozen != record:
            raise ValueError(
                f"{self._resume_label} intent differs from its canonical record"
            )
        projection = self._resume_history.project(
            self._transcript.active_path(),
            current_session_id=self.get_header().conversation_id,
        )
        if (
            attempt.session_id != self.get_header().conversation_id
            or attempt.original_leaf_id != self._transcript.leaf_id
            or projection.status != "none"
            or projection.binding_status == "unknown_version"
            or attempt.ancestry_digest != projection.ancestry_digest
        ):
            raise ValueError(
                f"{self._resume_label} intent differs from selected history"
            )
        # This assignment precedes even operation-scope acquisition. A failed
        # or cancelled await cannot prove intent/effects absent or reopen live
        # execution; the activation recovery owner must settle that decision.
        self._resume_runtime_publication_pending = True
        self._resume_writer_plan = None
        self._resume_committed_attempt = None
        self._resume_committed_plan = None
        self._resume_committed_input = None
        result = await self.commit_prebuilt_extension_data(frozen)
        if (
            type(result) is not CommitResult
            or result.record_id != frozen.record_id
            or result.disposition not in {"committed", "already_committed"}
        ):
            raise StoreCommitOutcomeUnknown(
                f"{self._resume_label} intent commit was not verified"
            )
        self._resume_committed_attempt = (attempt, frozen.created_at)
        self._resume_committed_plan = writer_plan
        return result

    def _require_resume_runtime_preparation(self, attempt_id: str) -> IntentT:
        """Verify a local definite intent, without admitting policy or effects."""

        proof = self._resume_committed_attempt
        if (
            not self.persist
            or not self._resume_runtime_publication_pending
            or proof is None
            or self._lifecycle_session._writer_owner is None
        ):
            raise self._resume_recovery_error("runtime.intent_unverified")
        attempt, created_at = proof
        if type(attempt_id) is not str or attempt_id != attempt.attempt_id:
            raise ValueError(
                f"{self._resume_label} preparation differs from its committed attempt"
            )
        selected = self._transcript.active_path()
        try:
            projection = self._resume_history.project(
                selected,
                current_session_id=self.get_header().conversation_id,
            )
            expected = self._resume_records.prepare_attempt(
                attempt,
                created_at=datetime.fromisoformat(created_at.replace("Z", "+00:00")),
            )
            if (
                projection.status != "pending"
                or projection.attempt != attempt
                or projection.record_id != attempt_id
                or not selected
                or selected[-1] != expected
            ):
                raise ValueError(
                    f"{self._resume_label} preparation selected history changed"
                )
        except ValueError as error:
            raise self._resume_recovery_error("runtime.intent_changed") from error
        return attempt

    async def append_message(
        self,
        message: object,
        *,
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> str:
        pending = self._resume_first_input
        if isinstance(pending, self._resume_pending_type):
            if not isinstance(message, UserMessage):
                raise ValueError(f"{self._resume_label} first user input is pending")
            return await self._append_resume_first_user_message(
                pending,
                message,
                metadata=metadata,
            )
        if self.persist:
            self.require_no_unsettled_resume_activation()
        self._require_ordinary_input_policy(message)
        guarded_revision = self._transcript.revision
        guarded_path = self._transcript.active_path() if self.persist else ()
        record_id = await super().append_message(message, metadata=metadata)
        selected = self._transcript.active_path() if self.persist else ()
        if (
            self.persist
            and self._transcript.revision == guarded_revision + 1
            and self._transcript.leaf_id == record_id
            and len(selected) == len(guarded_path) + 1
            and all(old is new for old, new in zip(guarded_path, selected))
            and selected[-1].parent_id
            == (guarded_path[-1].record_id if guarded_path else None)
            and self._activation_neutral_record(selected[-1])
        ):
            # A commit without Binding cannot change activation classification.
            # Retain the guard so subsequent messages avoid a full replay.
            self._activation_guard_snapshot = (
                self._transcript.revision,
                self._transcript.leaf_id,
            )
            if self._activation_guard_path is guarded_path:
                self._activation_guard_path = selected
        return record_id

    def _stage_resume_first_user_input(
        self,
        message: UserMessage,
        *,
        prepare_binding: Callable[[UserMessage], BindingT],
        created_at: datetime,
        original_leaf_id: str | None,
        ancestry_digest: str,
        attempt_id: str,
    ) -> None:
        """Register one admitted continuation input after the Writer is owned.

        The activation owner supplies current policy and effect settlement.
        This method only fences the selected transcript branch and commits the
        eventual UserMessage through the Product Transcript owner.
        """

        if not self.persist or not self._transcript.is_materialized:
            raise ValueError(
                f"{self._resume_label} first input requires a materialized Writer"
            )
        if not isinstance(message, UserMessage) or not callable(prepare_binding):
            raise TypeError(
                f"{self._resume_label} first input requires a message and binding owner"
            )
        if not isinstance(created_at, datetime) or created_at.tzinfo is None:
            raise ValueError(
                f"{self._resume_label} first input timestamp must be timezone-aware"
            )
        if self._resume_first_input is not None:
            raise ValueError(f"{self._resume_label} first input is already staged")
        active = tuple(self._transcript.active_path())
        original_length = 0
        if original_leaf_id is not None:
            for index, record in enumerate(active):
                if record.record_id == original_leaf_id:
                    original_length = index + 1
                    break
            else:
                raise ValueError(
                    f"{self._resume_label} original leaf is not on the selected path"
                )
        original_path = active[:original_length]
        projection = self._resume_history.project(
            original_path,
            current_session_id=self.get_header().conversation_id,
        )
        if (
            projection.status != "none"
            or projection.binding_status == "unknown_version"
            or projection.ancestry_digest != ancestry_digest
        ):
            raise ValueError(
                f"{self._resume_label} original history has an unresolved attempt"
            )
        tail = active[original_length:]
        if len(tail) != 1:
            raise ValueError(
                f"{self._resume_label} requires one selected activation attempt"
            )
        intent = tail[0]
        attempt = self._resume_records.validate_attempt(intent)
        if (
            attempt.attempt_id != attempt_id
            or attempt.session_id != self.get_header().conversation_id
            or attempt.original_leaf_id != original_leaf_id
            or attempt.ancestry_digest != ancestry_digest
        ):
            raise ValueError(
                f"{self._resume_label} activation attempt differs from selected history"
            )
        frozen_message = self._resume_messages.freeze_input(message)
        self._resume_first_input = cast(
            Callable[..., _ResumePendingInput[IntentT, BindingT]],
            self._resume_pending_type,
        )(
            expected_message=frozen_message,
            expected_message_digest=self._resume_messages.input_digest(frozen_message),
            prepare_binding=prepare_binding,
            created_at=created_at,
            original_leaf_id=original_leaf_id,
            commit_parent_id=intent.record_id,
            attempt_id=attempt_id,
            attempt=attempt,
            revision=self._transcript.revision,
            ancestry_digest=projection.ancestry_digest,
            lock=asyncio.Lock(),
        )
        # Binding/input durability does not prove that current Runtime owners
        # have published. The forthcoming activation owner must settle this
        # separate phase; historical projection cannot open this local gate.
        self._resume_runtime_publication_pending = True

    def _require_resume_staged_input(
        self, attempt_id: str, message: UserMessage
    ) -> None:
        """Check exact staged identity before invoking commit metadata owners."""

        pending = self._resume_first_input
        if pending is None or pending.attempt_id != attempt_id:
            raise self._resume_recovery_error("input.staged_input_missing")
        if pending.outcome_unknown:
            raise StoreCommitOutcomeUnknown(
                f"{self._resume_label} first input requires authoritative reload"
            )
        if (
            self._resume_messages.input_digest(message)
            != pending.expected_message_digest
        ):
            raise ValueError(
                f"{self._resume_label} first input differs from the staged input"
            )

    async def _append_resume_first_user_message(
        self,
        pending: _ResumePendingInput[IntentT, BindingT],
        message: UserMessage,
        *,
        metadata: Mapping[str, JSONValue] | None,
    ) -> str:
        metadata_snapshot = require_json_mapping(
            {} if metadata is None else dict(metadata),
            name=f"{self._resume_label} first input metadata",
        )
        async with pending.lock:
            if self._resume_first_input is not pending:
                raise ValueError(f"{self._resume_label} first input was replaced")
            if pending.outcome_unknown:
                raise StoreCommitOutcomeUnknown(
                    f"{self._resume_label} first input requires authoritative reload"
                )
            if (
                self._resume_messages.input_digest(message)
                != pending.expected_message_digest
            ):
                raise ValueError(
                    f"{self._resume_label} first input differs from the staged input"
                )
            if pending.expected_metadata is None:
                pending.expected_metadata = metadata_snapshot
            elif metadata_snapshot != pending.expected_metadata:
                raise ValueError(
                    f"{self._resume_label} first input metadata changed after admission"
                )
            if (
                self.get_leaf_id() != pending.commit_parent_id
                or self._transcript.revision != pending.revision
            ):
                raise ValueError(
                    f"{self._resume_label} selected transcript branch changed"
                )

            def prepare_record(persisted: UserMessage):
                record = self._resume_records.prepare_first_input_record(
                    pending,
                    persisted,
                    read_session_id=lambda: self.get_header().conversation_id,
                    resource_metadata=metadata_snapshot,
                )
                pending.prepared_record = replace(
                    record,
                    payload=self._resume_messages.freeze_input(persisted),
                    metadata=require_json_mapping(
                        dict(record.metadata),
                        name=f"{self._resume_label} prepared input metadata",
                    ),
                )
                return record

            try:
                result = await self.commit_prebuilt_user_message_from_message(
                    pending.expected_message,
                    prepare_record=prepare_record,
                )
                prepared = pending.prepared_record
                if (
                    type(result) is not CommitResult
                    or prepared is None
                    or result.record_id != prepared.record_id
                    or result.disposition not in {"committed", "already_committed"}
                ):
                    raise StoreCommitOutcomeUnknown(
                        f"{self._resume_label} input commit was not verified"
                    )
                self._resume_committed_input = (
                    pending.attempt,
                    prepared,
                    self._resume_messages.record_digest(prepared),
                )
            except BaseException:
                if pending.prepared_record is not None:
                    pending.outcome_unknown = True
                raise
            self._resume_first_input = None
            return result.record_id

    def _require_committed_resume_input(
        self,
        attempt_id: str,
        record_id: str,
    ) -> tuple[IntentT, AgentTranscriptRecord]:
        """Verify local commit and selected-path identity without granting execution."""

        snapshot = (self._transcript.revision, self._transcript.leaf_id)
        selected = self._transcript.active_path()
        result = self._require_committed_resume_input_identity(
            attempt_id, record_id, selected
        )
        try:
            if (
                not self._activation_guard_covers_path(selected)
                and self._resume_history.project(
                    selected, current_session_id=self.get_header().conversation_id
                ).status
                != "none"
            ):
                raise ValueError(
                    f"{self._resume_label} committed input identity changed"
                )
        except ValueError as error:
            raise self._resume_recovery_error("runtime.input_changed") from error
        if snapshot != (
            self._transcript.revision,
            self._transcript.leaf_id,
        ) or not self._same_activation_path(selected, self._transcript.active_path()):
            raise self._resume_recovery_error("runtime.input_changed")
        return result

    def _require_committed_resume_input_identity(
        self,
        attempt_id: str,
        record_id: str,
        selected: tuple[AgentTranscriptRecord, ...],
    ) -> tuple[IntentT, AgentTranscriptRecord]:
        """Check live owner and exact input/intent identity, never classify history."""

        proof = self._resume_committed_input
        intent_proof = self._resume_committed_attempt
        if (
            proof is None
            or intent_proof is None
            or self._resume_first_input is not None
            or self._lifecycle_session._writer_owner is None
        ):
            raise self._resume_recovery_error("runtime.input_unverified")
        attempt, expected, digest = proof
        if attempt_id != attempt.attempt_id or record_id != expected.record_id:
            raise ValueError(
                f"{self._resume_label} publication differs from its committed input"
            )
        try:
            index = next(
                i for i, entry in enumerate(selected) if entry.record_id == record_id
            )
            if (
                attempt != intent_proof[0]
                or index == 0
                or self._resume_messages.record_digest(expected) != digest
                or self._resume_messages.record_digest(selected[index]) != digest
                or selected[index - 1]
                != self._resume_records.prepare_attempt(
                    attempt,
                    created_at=datetime.fromisoformat(
                        intent_proof[1].replace("Z", "+00:00")
                    ),
                )
            ):
                raise ValueError(
                    f"{self._resume_label} committed input identity changed"
                )
        except (ValueError, StopIteration) as error:
            raise self._resume_recovery_error("runtime.input_changed") from error
        return attempt, expected

    async def _verify_resume_publication_input(
        self,
        attempt_id: str,
        record_id: str,
    ) -> IntentT:
        attempt, expected = self._require_committed_resume_input(attempt_id, record_id)
        observation = await self.lookup_prebuilt_user_message(expected)
        if observation.status != "committed" or observation.record_id != record_id:
            raise self._resume_recovery_error("runtime.input_unverified")
        self._require_committed_resume_input(attempt_id, record_id)
        return attempt

    async def _lookup_resume_first_user_input(
        self,
        *,
        request_id: str,
    ) -> PrebuiltUserMessageLookupResult:
        """Observe a staged input after losing its commit receipt, without replay.

        The original Transcript owner compares the exact persisted payload and
        metadata retained before dispatch. Observation neither clears the
        activation fence nor admits retry or model execution; those decisions
        require fresh owner admission and effect settlement.
        """

        pending = self._resume_first_input
        if not isinstance(pending, self._resume_pending_type):
            raise ValueError(f"{self._resume_label} has no staged input to observe")
        async with pending.lock:
            if self._resume_first_input is not pending:
                raise ValueError(f"{self._resume_label} first input was replaced")
            if request_id != pending.attempt.request_id:
                raise ValueError(f"{self._resume_label} input request identity differs")
            if pending.prepared_record is None:
                raise ValueError(
                    f"{self._resume_label} input has no prepared record to observe"
                )
            return await self.lookup_prebuilt_user_message(pending.prepared_record)

    async def prepare_resume_activation_guard(self) -> None:
        """Check a captured history cooperatively before ordinary admission.

        A branch/commit during a yield requires a fresh check. No partial
        projection is published, and the existing synchronous fence remains
        authoritative for every later execution boundary.
        """

        while self.persist:
            if self._resume_runtime_publication_pending:
                raise self._resume_recovery_error("runtime.publication_pending")
            snapshot = (self._transcript.revision, self._transcript.leaf_id)
            if self._activation_guard_snapshot == snapshot and (
                self._activation_guard_fingerprints is None
                or self._activation_fingerprints_unchanged()
            ):
                return
            records = self._transcript.active_path()
            if self._extend_neutral_activation_guard(snapshot, records):
                return
            fingerprints = self._activation_fingerprints(records)
            try:
                projection = await self._resume_history.project_async(
                    records, current_session_id=self.get_header().conversation_id
                )
            except ValueError as error:
                raise self._resume_recovery_error(
                    "history.activation_invalid"
                ) from error
            if self._resume_runtime_publication_pending:
                raise self._resume_recovery_error("runtime.publication_pending")
            if snapshot != (self._transcript.revision, self._transcript.leaf_id):
                continue
            self._accept_activation_guard_projection(
                snapshot, projection, records, fingerprints
            )
            return

    def require_no_unsettled_resume_activation(self) -> None:
        """Fence ordinary bootstrap before Product runtime selection.

        A successful historical check grants no current execution authority.
        """

        if not self.persist:
            return
        if self._resume_runtime_publication_pending:
            raise self._resume_recovery_error("runtime.publication_pending")
        snapshot = (self._transcript.revision, self._transcript.leaf_id)
        if self._activation_guard_snapshot == snapshot and (
            self._activation_guard_fingerprints is None
            or self._activation_fingerprints_unchanged()
        ):
            return
        records = self._transcript.active_path()
        if self._extend_neutral_activation_guard(snapshot, records):
            return
        fingerprints = self._activation_fingerprints(records)
        try:
            projection = self._resume_history.project(
                records,
                current_session_id=self.get_header().conversation_id,
            )
        except ValueError as error:
            raise self._resume_recovery_error("history.activation_invalid") from error
        self._accept_activation_guard_projection(
            snapshot, projection, records, fingerprints
        )

    @classmethod
    def _activation_fingerprints(
        cls, records: tuple[AgentTranscriptRecord, ...]
    ) -> tuple[tuple[AgentTranscriptRecord, str], ...] | None:
        fingerprints = []
        for record in records:
            if type(record) is not ConversationRecord:
                return None
            if cls._activation_neutral_record(record):
                continue
            if type(record.payload) not in {ExtensionData, UserMessage}:
                return None
            try:
                fingerprint = cls._resume_messages.record_digest(record)
            except (ValueError, TypeError):
                return None
            fingerprints.append((record, fingerprint))
        return tuple(fingerprints)

    def _activation_fingerprints_unchanged(self) -> bool:
        fingerprints = self._activation_guard_fingerprints
        if fingerprints is None:
            return False
        try:
            return all(
                self._resume_messages.record_digest(record) == expected
                for record, expected in fingerprints
            )
        except (ValueError, TypeError):
            return False

    def _activation_guard_covers_path(
        self, records: tuple[AgentTranscriptRecord, ...]
    ) -> bool:
        return (
            self._activation_guard_snapshot
            == (self._transcript.revision, self._transcript.leaf_id)
            and self._activation_guard_path is not None
            and self._same_activation_path(self._activation_guard_path, records)
            and self._activation_fingerprints_unchanged()
        )

    @staticmethod
    def _same_activation_path(
        left: tuple[AgentTranscriptRecord, ...],
        right: tuple[AgentTranscriptRecord, ...],
    ) -> bool:
        return left is right or (
            len(left) == len(right) and all(old is new for old, new in zip(left, right))
        )

    def _require_activation_guard_input_proof(
        self, binding_record_id: str | None, records: tuple[AgentTranscriptRecord, ...]
    ) -> None:
        proof = self._resume_committed_input
        if binding_record_id is not None and proof is not None:
            if binding_record_id != proof[1].record_id:
                raise self._resume_recovery_error("runtime.current_admission_required")
            self._require_committed_resume_input_identity(
                proof[0].attempt_id, proof[1].record_id, records
            )

    def _extend_neutral_activation_guard(
        self,
        snapshot: tuple[int, str | None],
        records: tuple[AgentTranscriptRecord, ...],
    ) -> bool:
        previous = self._activation_guard_path
        if (
            self._activation_guard_snapshot is None
            or self._activation_guard_fingerprints is None
            or previous is None
            or len(records) < len(previous)
            or (records[-1].record_id if records else None) != snapshot[1]
            or not all(old is new for old, new in zip(previous, records))
        ):
            return False
        seen = {record.record_id for record in previous}
        parent_id = previous[-1].record_id if previous else None
        for record in records[len(previous) :]:
            if (
                record.parent_id != parent_id
                or record.record_id in seen
                or not self._activation_neutral_record(record)
            ):
                return False
            seen.add(record.record_id)
            parent_id = record.record_id
        if snapshot != (self._transcript.revision, self._transcript.leaf_id):
            return False
        self._require_activation_guard_input_proof(
            self._activation_guard_binding_record_id, records
        )
        if not self._activation_fingerprints_unchanged():
            return False
        if snapshot != (
            self._transcript.revision,
            self._transcript.leaf_id,
        ) or not self._same_activation_path(records, self._transcript.active_path()):
            return False
        # Only the suffix is neutral. Sensitive facts in the accepted prefix
        # retain exact byte identity, and local input/owner proof is rechecked.
        # A new intent/binding always gets fresh complete ancestry validation.
        self._activation_guard_path = records
        self._activation_guard_snapshot = snapshot
        return True

    def _accept_activation_guard_projection(
        self,
        snapshot: tuple[int, str | None],
        projection: _ResumeProjection[IntentT],
        records: tuple[AgentTranscriptRecord, ...],
        fingerprints: tuple[tuple[AgentTranscriptRecord, str], ...] | None,
    ) -> None:
        if projection.status != "none":
            raise self._resume_recovery_error(f"history.activation_{projection.status}")
        if projection.binding_status == "unknown_version":
            raise self._resume_recovery_error("history.activation_unknown_version")
        if projection.binding_status == "bound":
            # A valid persisted Binding settles the historical input across a
            # process restart. It grants no current Tool or model authority;
            # those come from the runtime being built now. When this process
            # owns a local commit proof, retain the stronger identity check.
            self._require_activation_guard_input_proof(
                projection.binding_record_id, records
            )
        if (
            fingerprints is not None
            and self._activation_fingerprints(records) != fingerprints
        ):
            raise self._resume_recovery_error("history.activation_invalid")
        if snapshot != (
            self._transcript.revision,
            self._transcript.leaf_id,
        ) or not self._same_activation_path(records, self._transcript.active_path()):
            raise self._resume_recovery_error("history.activation_invalid")
        self._activation_guard_snapshot = snapshot
        self._activation_guard_path = records
        self._activation_guard_binding_record_id = (
            projection.binding_record_id
            if projection.binding_status == "bound"
            else None
        )
        self._activation_guard_fingerprints = (
            fingerprints
            if (records[-1].record_id if records else None) == snapshot[1]
            else None
        )
