"""Opt-in live continuation on the original Agent Product Session.

This profile borrows Product intent/receipts and existing owner APIs. It owns
only the fixed local program, never historical admission or a second runtime.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import replace
from typing import ClassVar, Generic, Protocol, TypeVar

from loushang.ai.options import CallOptions, RetryOptions
from loushang.ai.types import ImagePart, UserMessage
from loushang.harness.transcript._resume_continuation import _ResumeIntentRead

from .agent_product import AgentProductSession

IntentT = TypeVar("IntentT", bound=_ResumeIntentRead)
IntentCo = TypeVar("IntentCo", bound=_ResumeIntentRead, covariant=True)


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
