"""Opt-in live continuation on the original Agent Product Session.

This profile borrows Product intent/receipts and existing owner APIs. It owns
only the fixed local program, never historical admission or a second runtime.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    Protocol,
    Self,
    TypedDict,
    TypeVar,
    cast,
)

from loushang.ai.options import CallOptions, RetryOptions
from loushang.ai.types import ImagePart, UserMessage
from loushang.foundation.file_identity import is_file_status_fingerprint
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    execution_profile_expansion_codes,
)
from loushang.harness.transcript._resume_continuation import (
    _ResumeContinuationTranscript,
    _ResumeIntentRead,
    _ResumeProjector,
)
from loushang.harness.transcript._resume_records import canonical_binding_bytes
from loushang.harness.transcript.types import AgentTranscriptRecord

from .agent_product import AgentProductSession

IntentT = TypeVar("IntentT", bound=_ResumeIntentRead)
IntentCo = TypeVar("IntentCo", bound=_ResumeIntentRead, covariant=True)


class _ActivationOwnerRef(Protocol):
    @property
    def owner_id(self) -> str: ...

    @property
    def fingerprint(self) -> str: ...


_RefT = TypeVar("_RefT", bound=_ActivationOwnerRef)
_PLAN_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_PLAN_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class _ActivationPlanSource(Protocol):
    @property
    def selected_leaf_id(self) -> str | None: ...
    @property
    def source_fingerprint(self) -> str: ...
    @property
    def source_content_digest(self) -> str: ...
    @property
    def selected_ancestry_digest(self) -> str | None: ...


def require_activation_plan_workspace_root(workspace_root: Path) -> None:
    if not isinstance(workspace_root, Path) or not workspace_root.is_absolute():
        raise ValueError("activation Plan requires a canonical absolute workspace root")
    if str(workspace_root) != os.path.normpath(str(workspace_root)):
        raise ValueError("activation Plan requires a canonical absolute workspace root")
    if len(str(workspace_root).encode("utf-8")) > 4096:
        raise ValueError("activation Plan workspace root exceeds its budget")


def require_activation_plan_source(
    history: _ActivationPlanSource, *, session_id: str
) -> None:
    """Check the typed file identity and ancestry facts before fingerprinting a Plan."""
    if type(session_id) is not str or _PLAN_IDENTIFIER.fullmatch(session_id) is None:
        raise ValueError("activation Plan Session id is invalid")
    if history.selected_leaf_id is not None and (
        type(history.selected_leaf_id) is not str
        or _PLAN_IDENTIFIER.fullmatch(history.selected_leaf_id) is None
    ):
        raise ValueError("activation Plan selected leaf id is invalid")
    if not is_file_status_fingerprint(history.source_fingerprint):
        raise ValueError("activation Plan source fingerprint is invalid")
    if (
        type(history.source_content_digest) is not str
        or _PLAN_DIGEST.fullmatch(history.source_content_digest) is None
    ):
        raise ValueError("activation Plan source content digest is invalid")
    if history.selected_ancestry_digest is not None and (
        type(history.selected_ancestry_digest) is not str
        or _PLAN_DIGEST.fullmatch(history.selected_ancestry_digest) is None
    ):
        raise ValueError("activation Plan ancestry digest is invalid")


def checked_activation_plan_owner_refs(
    refs: Sequence[_RefT],
    ref_type: type[_RefT],
    *,
    type_error: str,
    order_error: str,
    budget: tuple[int, str] | None = None,
) -> tuple[_RefT, ...]:
    items = tuple(refs)
    if budget is not None and len(items) > budget[0]:
        raise ValueError(budget[1])
    if any(not isinstance(item, ref_type) for item in items):
        raise TypeError(type_error)
    if items != tuple(sorted(items, key=lambda item: item.owner_id)) or len(
        {item.owner_id for item in items}
    ) != len(items):
        raise ValueError(order_error)
    return items


def activation_plan_fingerprint(
    identity: object, *, digest_domain: bytes, name: str, max_bytes: int
) -> str:
    encoded = canonical_binding_bytes(identity, name=name)
    if len(encoded) > max_bytes:
        raise ValueError("activation Plan exceeds its byte budget")
    return sha256(digest_domain + encoded).hexdigest()


class _ActivationSelectionRef(_ActivationOwnerRef, Protocol):
    @property
    def generation(self) -> str: ...


class _ActivationPlanHistory(_ActivationPlanSource, Protocol):
    @property
    def selected_records(self) -> tuple[AgentTranscriptRecord, ...]: ...

    @property
    def binding_status(self) -> str: ...

    @property
    def binding(self) -> object: ...

    @property
    def activation_status(self) -> str: ...

    @property
    def pending_activation_attempt(self) -> object: ...

    @property
    def pending_activation_record_id(self) -> str | None: ...


class _ActivationPlanIdentity(TypedDict):
    plan_id: str
    session_id: str
    selected_leaf_id: str | None
    source_fingerprint: str
    source_content_digest: str
    ancestry_digest: str | None
    workspace_root: str
    status: Literal["needs_final_validation", "unavailable"]


def project_activation_plan_identity(
    history: _ActivationPlanHistory,
    *,
    session_id: str,
    workspace_root: Path,
    comparison: dict[str, object],
    inputs: Sequence[_ActivationOwnerRef],
    selections: Sequence[_ActivationSelectionRef],
    project_path: _ResumeProjector[_ResumeIntentRead],
    digest_domain: bytes,
    label: str,
    max_bytes: int,
) -> _ActivationPlanIdentity:
    """Authenticate the selected path and fingerprint the bounded Plan envelope."""
    require_activation_plan_source(history, session_id=session_id)
    unavailable = comparison["status"] == "unavailable"
    status: Literal["needs_final_validation", "unavailable"] = (
        "unavailable" if unavailable else "needs_final_validation"
    )
    if not unavailable:
        selected = history.selected_records
        projection = project_path(selected, current_session_id=session_id)
        if (
            projection.ancestry_digest != history.selected_ancestry_digest
            or projection.binding_status != history.binding_status
            or projection.binding != history.binding
            or projection.status != history.activation_status
            or projection.attempt != history.pending_activation_attempt
            or projection.record_id != history.pending_activation_record_id
            or (selected[-1].record_id if selected else None)
            != history.selected_leaf_id
        ):
            raise ValueError("activation Plan selected history facts differ")

    document = {
        "schemaVersion": 1,
        "sessionId": session_id,
        "selectedLeafId": history.selected_leaf_id,
        "sourceFingerprint": history.source_fingerprint,
        "sourceContentDigest": history.source_content_digest,
        "ancestryDigest": history.selected_ancestry_digest,
        "workspaceRoot": str(workspace_root),
        "composition": comparison,
        "ownerSelections": [
            {
                "ownerId": item.owner_id,
                "fingerprint": item.fingerprint,
                "generation": item.generation,
            }
            for item in selections
        ],
        "ownerInputs": [
            {"ownerId": item.owner_id, "fingerprint": item.fingerprint}
            for item in inputs
        ],
        "status": status,
    }
    return _ActivationPlanIdentity(
        plan_id=activation_plan_fingerprint(
            document, digest_domain=digest_domain, name=label, max_bytes=max_bytes
        ),
        session_id=session_id,
        selected_leaf_id=history.selected_leaf_id,
        source_fingerprint=history.source_fingerprint,
        source_content_digest=history.source_content_digest,
        ancestry_digest=history.selected_ancestry_digest,
        workspace_root=str(workspace_root),
        status=status,
    )


def resume_execution_scope(
    profile: EffectiveExecutionProfile, *, name: str, max_bytes: int, digest_domain: bytes
) -> tuple[dict[str, object], str]:
    execution_profile_expansion_codes(profile, None)  # Native type/root budget.
    document: dict[str, object] = {
        "readableRoots": sorted(str(root) for root in profile.readable_roots),
        "writableRoots": sorted(str(root) for root in profile.writable_roots),
        "deniedRoots": sorted(str(root) for root in profile.denied_roots),
        "network": profile.network,
        "policyCode": profile.policy_code,
        "approvalActionId": profile.approval_action_id,
    }
    encoded = canonical_binding_bytes(document, name=name)
    if len(encoded) > max_bytes:
        raise ValueError(f"{name} exceeds its byte budget")
    return document, sha256(digest_domain + encoded).hexdigest()


class _ResumeRuntimeCandidate(Protocol[IntentCo]):
    @property
    def attempt(self) -> IntentCo: ...
    @property
    def consumer(self) -> object: ...
    @property
    def graph_generation(self) -> int: ...
    @property
    def receipt_fingerprint(self) -> str: ...


class _ResumeRuntimePublication(Protocol[IntentT]):
    @property
    def candidate(self) -> _ResumeRuntimeCandidate[IntentT]: ...
    @property
    def input_record_id(self) -> str: ...
    @property
    def current_admission(self) -> Callable[[IntentT], None]: ...
    @property
    def current_epoch_settlement(
        self,
    ) -> Callable[[IntentT, Mapping[str, object]], None]: ...


class _ResumeTranscriptLifecycle(Protocol):
    def sync_operation_scope(self) -> AbstractContextManager[None]: ...


class _ResumeTranscript(Protocol[IntentCo]):
    @property
    def _lifecycle_session(self) -> _ResumeTranscriptLifecycle: ...
    def _require_resume_runtime_preparation(self, attempt_id: str) -> IntentCo: ...
    def _require_resume_staged_input(
        self, attempt_id: str, message: UserMessage
    ) -> None: ...
    def _require_committed_resume_input(
        self, attempt_id: str, record_id: str
    ) -> tuple[IntentCo, object]: ...
    async def _verify_resume_publication_input(
        self, attempt_id: str, record_id: str
    ) -> IntentCo: ...
    def _publish_resume_runtime(self, attempt_id: str, record_id: str) -> None: ...


class _ResumeContinuationSession(AgentProductSession, Generic[IntentT]):
    """Same Session, locks and owners; explicitly selected by a Product binding.

    Product policy hooks are synchronous at their original effect/decision
    points. Graph and committed-input execution remain the existing owners.
    """

    _resume_label: ClassVar[str]
    _resume_recovery_error: ClassVar[type[RuntimeError]]

    def _init_resume_runtime_state(self) -> None:
        # Called at the Product's original construction point, before graph IO.
        self._resume_runtime_preparation_lock = asyncio.Lock()
        self._resume_graph_attempt_id: str | None = None
        self._resume_candidate: _ResumeRuntimeCandidate[IntentT] | None = None
        self._resume_publication: _ResumeRuntimePublication[IntentT] | None = None
        self._resume_dispatch_claimed = False
        self._resume_input_commit_claimed = False
        self._resume_input_preflight_claimed = False
        self._resume_preflight_input_digest: str | None = None

    @property
    def _resume_transcript(self) -> _ResumeTranscript[IntentT]:
        raise NotImplementedError

    @staticmethod
    def _resume_user_input_digest(message: UserMessage) -> str:
        raise NotImplementedError

    def _require_current_resume_selection(self) -> None:
        raise NotImplementedError

    def _claim_resume_runtime_owners(self) -> None:
        raise NotImplementedError

    def _resume_graph_prepared(self) -> None:
        raise NotImplementedError

    def _create_resume_runtime_candidate(
        self,
        attempt: IntentT,
        receipt: Mapping[str, object],
    ) -> _ResumeRuntimeCandidate[IntentT]:
        raise NotImplementedError

    def _require_resume_candidate_policy(
        self,
        candidate: _ResumeRuntimeCandidate[IntentT],
    ) -> dict[str, object]:
        raise NotImplementedError

    def _require_resume_worker_effect_settlement(self, attempt: IntentT) -> None:
        raise NotImplementedError

    def _create_resume_runtime_publication(
        self,
        candidate: _ResumeRuntimeCandidate[IntentT],
        input_record_id: str,
        current_admission: Callable[[IntentT], None],
        current_epoch_settlement: Callable[[IntentT, Mapping[str, object]], None],
    ) -> _ResumeRuntimePublication[IntentT]:
        raise NotImplementedError

    def _activate_resume_runtime_tools(self) -> None:
        raise NotImplementedError

    def _resume_runtime_published(self) -> None:
        raise NotImplementedError

    def _build_resume_composition_receipt(self) -> dict[str, object]:
        raise NotImplementedError

    async def _prepare_resume_runtime_graph(
        self,
        *,
        attempt_id: str,
        require_current_admission: Callable[[IntentT], None],
    ) -> dict[str, object]:
        """Prepare current owners for one committed intent, keeping execution fenced.

        The activation coordinator supplies live subject/policy admission. This
        path returns current observations; it does not commit input, activate
        the Worker turn Tool or publish Product execution readiness.
        """

        manager = self._resume_transcript

        def require_current() -> None:
            # Graph rollback can retire this same Transcript Writer. Never hold
            # its operation scope across graph awaits or retirement would wait
            # for the operation that is itself waiting for retirement.
            with manager._lifecycle_session.sync_operation_scope():
                attempt = manager._require_resume_runtime_preparation(attempt_id)
                self._require_candidate_preparation_admission(
                    lambda: require_current_admission(attempt)
                )
                self._require_current_resume_selection()

        async with self._resume_runtime_preparation_lock:
            self._require_candidate_preparation_admission(require_current)
            self._resume_graph_attempt_id = attempt_id
            try:
                self._claim_resume_runtime_owners()
                await self._prepare_candidate_session_graph(
                    require_current_admission=require_current
                )
                self._resume_graph_prepared()
                require_current()
                receipt = self._build_resume_composition_receipt()
                self._resume_candidate = self._create_resume_runtime_candidate(
                    manager._require_resume_runtime_preparation(attempt_id),
                    receipt,
                )
                return receipt
            except BaseException:
                self._execution_preparation_failed = True
                raise
            finally:
                self._resume_graph_attempt_id = None

    async def _prepare_resume_first_user_input(
        self,
        text: str,
        *,
        attempt_id: str,
        require_current_admission: Callable[[IntentT], None],
        images: list[ImagePart] | None = None,
    ) -> UserMessage:
        """Prepare one current input through original prompt/Resource owners.

        Formal preparation requires the locally committed intent and prepared
        graph. It does not stage or commit a UserMessage, execute commands,
        publish a runtime or run a model. The coordinator still owns those steps.
        """

        from loushang.harness.runtime.turn import TurnInput

        if not isinstance(text, str) or (not text.strip() and not images):
            raise ValueError(f"{self._resume_label} requires nonempty user input")
        manager = self._resume_transcript
        async with self._resume_runtime_preparation_lock:
            candidate = self._resume_candidate
            if candidate is None or candidate.attempt.attempt_id != attempt_id:
                raise self._resume_recovery_error("runtime.candidate_unverified")
            if (
                self._resume_input_preflight_claimed
                or self._resume_input_commit_claimed
            ):
                raise self._resume_recovery_error("input.preflight_already_claimed")

            def require_current() -> None:
                with manager._lifecycle_session.sync_operation_scope():
                    manager._require_resume_runtime_preparation(attempt_id)
                    self._require_candidate_preparation_admission(
                        lambda: require_current_admission(candidate.attempt),
                    )
                    self._require_resume_candidate(candidate)
                    self._require_candidate_preparation_admission(
                        lambda: require_current_admission(candidate.attempt),
                    )

            require_current()
            commands = self._composition.command_controller
            if (
                commands.extract_extension_command_invocation(text) is not None
                or commands.extract_builtin_command_invocation(text) is not None
            ):
                raise self._resume_recovery_error(
                    "input.command_requires_separate_admission"
                )
            self._resume_input_preflight_claimed = True
            evidence_owner = object()
            try:
                message = await self._composition.session_runtime.prompt_controller.prepare_user_message(
                    TurnInput(
                        text=text,
                        attachments=None if images is None else list(images),
                        source="resume",
                    ),
                    evidence_owner=evidence_owner,
                )
                require_current()
                self._resume_preflight_input_digest = self._resume_user_input_digest(
                    message
                )
                return message
            except BaseException:
                self._request_evidence_runtime.discard_owner(evidence_owner)
                self._execution_preparation_failed = True
                raise

    async def _commit_resume_first_user_input(
        self,
        message: UserMessage,
        *,
        attempt_id: str,
        require_current_admission: Callable[[IntentT], None],
    ) -> str:
        """Commit the staged fixed input through native Request Evidence owners.

        This initial route is claimed once, including unknown outcomes. The
        coordinator must use durable lookup for recovery and still settle the
        current epoch before publication or model dispatch.
        """

        if not isinstance(message, UserMessage):
            raise TypeError(f"{self._resume_label} input requires a UserMessage")
        manager = self._resume_transcript
        async with self._resume_runtime_preparation_lock:
            candidate = self._resume_candidate
            if candidate is None or candidate.attempt.attempt_id != attempt_id:
                raise self._resume_recovery_error("runtime.candidate_unverified")
            if self._resume_input_commit_claimed:
                raise self._resume_recovery_error("input.commit_already_claimed")
            if (
                self._resume_preflight_input_digest is not None
                and self._resume_user_input_digest(message)
                != self._resume_preflight_input_digest
            ):
                raise self._resume_recovery_error("input.preflight_payload_changed")
            with manager._lifecycle_session.sync_operation_scope():
                manager._require_resume_runtime_preparation(attempt_id)
                manager._require_resume_staged_input(attempt_id, message)
                self._require_candidate_preparation_admission(
                    lambda: require_current_admission(candidate.attempt),
                )
                self._require_resume_candidate(candidate)
                self._require_candidate_preparation_admission(
                    lambda: require_current_admission(candidate.attempt),
                )
            self._resume_input_commit_claimed = True
            try:
                record_id = await self._composition.session_runtime.agent_event_router.commit_prepared_user_message(
                    message
                )
                with manager._lifecycle_session.sync_operation_scope():
                    manager._require_committed_resume_input(attempt_id, record_id)
                    self._require_candidate_preparation_admission(
                        lambda: require_current_admission(candidate.attempt),
                    )
                    self._require_resume_candidate(candidate)
                    self._require_candidate_preparation_admission(
                        lambda: require_current_admission(candidate.attempt),
                    )
                return record_id
            except BaseException:
                self._execution_preparation_failed = True
                raise

    def _require_resume_candidate(
        self,
        candidate: _ResumeRuntimeCandidate[IntentT],
    ) -> dict[str, object]:
        if (
            not super().execution_available
            or self._resume_candidate is not candidate
            or candidate.consumer is None
            or self._model_call_consumer is not candidate.consumer
            or self._capability_graph_runtime.is_closed
            or self._capability_graph_runtime.generation != candidate.graph_generation
        ):
            raise self._resume_recovery_error("runtime.candidate_changed")
        return self._require_resume_candidate_policy(candidate)

    def _require_current_resume_publication(
        self,
        publication: _ResumeRuntimePublication[IntentT],
    ) -> None:
        candidate = publication.candidate
        with self._resume_transcript._lifecycle_session.sync_operation_scope():
            attempt, _ = self._resume_transcript._require_committed_resume_input(
                candidate.attempt.attempt_id,
                publication.input_record_id,
            )
            self._require_candidate_preparation_admission(
                lambda: publication.current_admission(attempt)
            )
            receipt = self._require_resume_candidate(candidate)
            self._require_candidate_preparation_admission(
                lambda: publication.current_admission(attempt)
            )
            self._require_resume_worker_effect_settlement(attempt)
            self._require_candidate_preparation_admission(
                lambda: publication.current_admission(attempt)
            )
            self._require_candidate_preparation_admission(
                lambda: publication.current_epoch_settlement(attempt, receipt),
            )
            self._require_candidate_preparation_admission(
                lambda: publication.current_admission(attempt)
            )
            self._require_resume_candidate(candidate)
            self._require_candidate_preparation_admission(
                lambda: publication.current_admission(attempt)
            )

    async def _publish_resume_runtime(
        self,
        *,
        attempt_id: str,
        input_record_id: str,
        require_current_admission: Callable[[IntentT], None],
        require_current_epoch_settlement: Callable[
            [IntentT, Mapping[str, object]], None
        ],
    ) -> None:
        """Publish a prepared graph after exact durable input and live owner checks.

        The activation coordinator owns current grants and native effect
        settlement. Historical Binding and these local observations grant none.
        Publication is in memory; recovery must acquire fresh owner authority.
        """

        manager = self._resume_transcript
        async with self._resume_runtime_preparation_lock:
            candidate = self._resume_candidate
            if candidate is None or candidate.attempt.attempt_id != attempt_id:
                raise self._resume_recovery_error("runtime.candidate_unverified")
            if self._resume_publication is not None:
                raise self._resume_recovery_error("runtime.already_published")
            with manager._lifecycle_session.sync_operation_scope():
                manager._require_committed_resume_input(attempt_id, input_record_id)
                self._require_candidate_preparation_admission(
                    lambda: require_current_admission(candidate.attempt),
                )
                self._require_resume_candidate(candidate)
                self._require_candidate_preparation_admission(
                    lambda: require_current_admission(candidate.attempt)
                )
            await manager._verify_resume_publication_input(attempt_id, input_record_id)
            publication = self._create_resume_runtime_publication(
                candidate,
                input_record_id,
                require_current_admission,
                require_current_epoch_settlement,
            )
            self._require_current_resume_publication(publication)
            with manager._lifecycle_session.sync_operation_scope():
                try:
                    self._activate_resume_runtime_tools()
                    self._require_current_resume_publication(publication)
                    manager._publish_resume_runtime(attempt_id, input_record_id)
                    self._resume_publication = publication
                    self._resume_runtime_published()
                except BaseException:
                    self._execution_preparation_failed = True
                    raise

    async def _run_published_resume_input(
        self, *, attempt_id: str, input_record_id: str
    ) -> None:
        """Consume the published input once through the original Host/Agent loop.

        No prompt submission or user append occurs here. The original Model
        Input transport barrier remains installed. A claimed run is never
        automatically replayed after an error, cancellation or unknown outcome.
        """

        publication = self._resume_publication
        if (
            publication is None
            or publication.candidate.attempt.attempt_id != attempt_id
            or publication.input_record_id != input_record_id
        ):
            raise self._resume_recovery_error("model.publication_unverified")
        if self._resume_dispatch_claimed:
            raise self._resume_recovery_error("model.dispatch_already_claimed")
        await self.prepare_model_call_runtime()
        original_options: CallOptions | None = None
        claimed_here = False

        def prepare_current_input() -> None:
            nonlocal original_options, claimed_here
            self._require_current_resume_publication(publication)
            if (
                self._resume_dispatch_claimed
                or self.session_manager.leaf_id != input_record_id
                or self.agent.has_queued_messages()
                or self._composition.retry_runtime.is_retrying
            ):
                raise self._resume_recovery_error("model.input_not_current")
            self._refresh_agent_messages()
            if (
                not self.agent.state.messages
                or getattr(self.agent.state.messages[-1], "role", None) != "user"
            ):
                raise self._resume_recovery_error("model.input_not_current")
            original_options = self.agent.call_options
            self.agent.call_options = replace(
                original_options, retry=RetryOptions(max_attempts=1)
            )
            self._resume_dispatch_claimed = claimed_here = True

        try:
            await self._composition.session_runtime.run_committed_input(
                prepare_current_input=prepare_current_input
            )
            last_assistant = next(
                (
                    message
                    for message in reversed(self.agent.state.messages)
                    if getattr(message, "role", None) == "assistant"
                ),
                None,
            )
            if claimed_here and (
                last_assistant is None
                or getattr(last_assistant, "stop_reason", None) in {"error", "aborted"}
            ):
                self._execution_preparation_failed = True
        except BaseException:
            if claimed_here:
                self._execution_preparation_failed = True
            raise
        finally:
            if original_options is not None:
                self.agent.call_options = original_options


def require_resume_owner_check(
    check: Callable[[], None], *, invalid_return: str
) -> None:
    result = cast(Callable[[], object], check)()
    if result is not None:
        if inspect.iscoroutine(result):
            result.close()
        raise TypeError(invalid_return)


_WriterT = TypeVar("_WriterT", bound=_ResumeContinuationTranscript[Any, Any, Any, Any, Any])
_SessionT = TypeVar("_SessionT", bound=_ResumeContinuationSession[Any])
_QueryT = TypeVar("_QueryT")
_ContinuationT = TypeVar("_ContinuationT")
_BindingT = TypeVar("_BindingT")
_ResumeCleanupSession = _ResumeContinuationSession[Any]
_ResumeCleanupWriter = _ResumeContinuationTranscript[Any, Any, Any, Any, Any]
_ResumeCleanupOwner = _ResumeCleanupSession | _ResumeCleanupWriter


class ResumeContinuationCleanupFailure(RuntimeError):
    """Retain the original undelivered Session or Writer for cleanup retry."""

    _cleanup_label: ClassVar[str]

    def __init__(
        self,
        *,
        original_owner: _ResumeCleanupOwner,
        original_error: BaseException,
        cleanup_error: BaseException,
    ) -> None:
        super().__init__(f"{self._cleanup_label} continuation cleanup remains pending")
        self.original_owner = original_owner
        self.original_error = original_error
        self.cleanup_error = cleanup_error

    async def retry_cleanup(self) -> None:
        owner = self.original_owner
        if isinstance(owner, _ResumeContinuationSession):
            await owner.dispose()
        else:
            await owner.dispose_runtime_profile()

    @classmethod
    def retain_resume_cleanup_failure(
        cls,
        *,
        original_owner: _ResumeCleanupOwner,
        original_error: BaseException,
        cleanup_error: BaseException,
    ) -> Self:
        """Fence the admitting factory before retaining its exact owner."""
        writer = (
            cast(_ResumeCleanupWriter, original_owner._resume_transcript)
            if isinstance(original_owner, _ResumeContinuationSession)
            else original_owner
        )
        try:
            type(writer)._factory_for_persistence(True).fence()
        except BaseException as fence_error:
            original_error.add_note(
                f"Original {cls._cleanup_label} factory fencing also failed: {fence_error!r}"
            )
        return cls(
            original_owner=original_owner,
            original_error=original_error,
            cleanup_error=cleanup_error,
        )

    @classmethod
    async def discard_candidate(
        cls,
        session: _ResumeCleanupSession | None,
        original_error: BaseException,
        *,
        manager: _ResumeCleanupWriter | None = None,
        cleanup_note: str | None = None,
    ) -> None:
        """Dispose the original candidate and retain its owner on failure."""
        try:
            if session is not None:
                await session.dispose()
            elif manager is not None:
                await manager.dispose_runtime_profile()
        except BaseException as cleanup_error:
            if cleanup_note is not None:
                original_error.add_note(f"{cleanup_note}{cleanup_error!r}")
            owner = session if session is not None else manager
            assert owner is not None
            raise cls.retain_resume_cleanup_failure(
                original_owner=owner,
                original_error=original_error,
                cleanup_error=cleanup_error,
            ) from original_error


async def prepare_resume_continuation(
    *,
    product_label: str,
    attempt: IntentT,
    input_record_id: str,
    text: str,
    images: list[ImagePart] | None,
    created_at: datetime,
    require_current_admission: Callable[[IntentT], None],
    require_current_epoch_settlement: Callable[[IntentT, Mapping[str, object]], None],
    open_writer: Callable[[], Awaitable[_WriterT]],
    build_session: Callable[[_WriterT], Awaitable[_SessionT]],
    enroll_native_owners: Callable[[_WriterT], Callable[[], None]] | None,
    prepare_binding: Callable[[UserMessage], _BindingT],
    input_query: Callable[[str, str], _QueryT],
    observe_input_identity: Callable[[_QueryT], None] | None,
    retained_cleanup_error: type[ResumeContinuationCleanupFailure],
    deliver: Callable[[_SessionT, str, str, _QueryT], _ContinuationT],
) -> _ContinuationT:
    """Commit initial input on the original Writer and publish its prepared Session."""

    invalid_check_return = f"{product_label} owner check must return None"

    def checked(check: Callable[[], None]) -> None:
        require_resume_owner_check(check, invalid_return=invalid_check_return)

    def current() -> None:
        checked(lambda: require_current_admission(attempt))

    manager: _WriterT | None = None
    session: _SessionT | None = None
    observed_input = False
    phase = "writer_preparation"
    current()
    try:
        writer = manager = await open_writer()
        with writer._lifecycle_session.sync_operation_scope():
            current()
            writer._require_fresh_resume_input(attempt, input_record_id)
        phase = "intent_commit"
        await writer._commit_resume_activation_intent(
            writer._resume_records.prepare_attempt(attempt, created_at=created_at)
        )
        seal = None
        if enroll_native_owners is not None:
            phase = "native_owner_enrollment"
            current()
            seal = enroll_native_owners(writer)
            current()

        phase = "runtime_preparation"
        prepared = session = await build_session(writer)
        receipt = await prepared._prepare_resume_runtime_graph(
            attempt_id=attempt.attempt_id,
            require_current_admission=require_current_admission,
        )
        if seal is not None:
            phase = "native_owner_seal"
            current()
            seal()
            current()

        def settled() -> None:
            with writer._lifecycle_session.sync_operation_scope():
                current()
                candidate = prepared._resume_candidate
                if candidate is None:
                    raise RuntimeError(f"{product_label} candidate was not delivered")
                prepared._require_resume_candidate(candidate)
                current()
                prepared._require_resume_worker_effect_settlement(attempt)
                current()
                checked(lambda: require_current_epoch_settlement(attempt, receipt))
                current()
                prepared._require_resume_candidate(candidate)
                current()

        settled()
        phase = "input_preparation"
        message = await prepared._prepare_resume_first_user_input(
            text,
            images=images,
            attempt_id=attempt.attempt_id,
            require_current_admission=require_current_admission,
        )
        settled()
        writer._stage_resume_first_user_input(
            message,
            prepare_binding=prepare_binding,
            created_at=created_at,
            original_leaf_id=attempt.original_leaf_id,
            ancestry_digest=attempt.ancestry_digest,
            attempt_id=attempt.attempt_id,
        )
        phase = "input_commit"
        record_id = await prepared._commit_resume_first_user_input(
            message,
            attempt_id=attempt.attempt_id,
            require_current_admission=require_current_admission,
        )
        _, committed = writer._require_committed_resume_input(attempt.attempt_id, record_id)
        query = input_query(attempt.request_id, writer._resume_messages.record_digest(committed))
        observed_input = True
        if observe_input_identity is not None:
            checked(lambda: observe_input_identity(query))
        phase = "runtime_publication"
        await prepared._publish_resume_runtime(
            attempt_id=attempt.attempt_id,
            input_record_id=record_id,
            require_current_admission=require_current_admission,
            require_current_epoch_settlement=require_current_epoch_settlement,
        )
        return deliver(prepared, attempt.attempt_id, record_id, query)
    except BaseException as error:
        error.add_note(
            f"{product_label} continuation failed during {phase}; "
            "no model was dispatched by this entry."
        )
        if isinstance(error, retained_cleanup_error):
            # The failed bootstrap already retains the complete candidate and Writer.
            raise
        if phase in {"input_commit", "runtime_publication"}:
            error.add_note(
                "Input may already be committed; use original input lookup before any explicit recovery."
            )
            if manager is not None and not observed_input and observe_input_identity is not None:
                proof = manager._resume_committed_input
                pending = manager._resume_first_input
                record = proof[1] if proof is not None else (
                    pending.prepared_record if pending is not None else None
                )
                if record is not None:
                    try:
                        recovery_query = input_query(
                            attempt.request_id, manager._resume_messages.record_digest(record)
                        )
                        checked(lambda: observe_input_identity(recovery_query))
                    except BaseException as observation_error:
                        error.add_note(
                            f"Resume input identity delivery also failed: {observation_error!r}"
                        )
        await retained_cleanup_error.discard_candidate(
            session,
            error,
            manager=manager,
            cleanup_note=f"Original {product_label} owner cleanup also failed: ",
        )
        raise
