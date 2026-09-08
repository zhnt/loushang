"""Generation-bound interaction settlement for the optional semantic scope."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    SessionEventKindV1,
    SessionEventV1,
)

from ._operations import _OwnedAppOperations
from .runtime import _SessionOwner


@dataclass(slots=True)
class _Question:
    session: _SessionOwner
    interaction_id: str
    authority: str | None
    task: asyncio.Task[None] | None = None
    dismissed: bool = False


class _ScopeInteractions:
    def __init__(
        self,
        operations: _OwnedAppOperations,
        authority: Callable[[str], str | None],
    ) -> None:
        self._operations = operations
        self._authority = authority
        self._questions: dict[tuple[str, str], _Question] = {}

    async def on_event(self, session: _SessionOwner, event: SessionEventV1) -> None:
        if event.interaction_id is None:
            return
        key = (session.identity.session_id, event.interaction_id)
        if event.kind is SessionEventKindV1.INTERACTION_DISMISSED:
            question = self._questions.get(key)
            if question is not None:
                question.dismissed = True
                if question.task is None:
                    self._questions.pop(key, None)
            return
        if event.kind is not SessionEventKindV1.INTERACTION_REQUESTED:
            return
        if key in self._questions or sum(
            item.session is session for item in self._questions.values()
        ) >= 16:
            # Product event observers may isolate listener errors; explicitly
            # stop the turn instead of relying on exception propagation.
            session.interrupt_turn()
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        question = _Question(
            session, event.interaction_id, self._authority(session.identity.session_id)
        )
        self._questions[key] = question
        if question.authority is None:
            try:
                # Never wait for a decision from inside the event listener.
                # A Product's ordered dismissal can depend on this event ending.
                self._decide(question, InteractionOutcomeV1.DENY)
            except AppServiceError:
                session.interrupt_turn()
                raise

    def respond(
        self,
        session: _SessionOwner,
        interaction_id: str,
        authority: str,
        outcome: InteractionOutcomeV1,
    ) -> asyncio.Task[None]:
        question = self._questions.get((session.identity.session_id, interaction_id))
        if (
            question is None or question.authority != authority
            or question.dismissed or question.task is not None
        ):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return self._decide(question, outcome)

    async def revoke(self, authority: str | None) -> None:
        for question in tuple(self._questions.values()):
            if question.authority != authority:
                continue
            task = question.task
            if task is None:
                task = self._decide(question, InteractionOutcomeV1.DENY)
            await asyncio.shield(task)

    async def settle_unowned(self, session_ids: frozenset[str]) -> None:
        while True:
            questions = tuple(
                question for question in self._questions.values()
                if question.authority is None
                and question.session.identity.session_id in session_ids
            )
            if not questions:
                return
            for question in questions:
                task = question.task
                if task is None:
                    task = self._decide(question, InteractionOutcomeV1.DENY)
                await asyncio.shield(task)

    def _decide(
        self, question: _Question, outcome: InteractionOutcomeV1
    ) -> asyncio.Task[None]:
        key = (question.session.identity.session_id, question.interaction_id)

        async def decide() -> None:
            try:
                if not question.dismissed and not question.session._settled:
                    await question.session.respond_interaction(
                        question.interaction_id, outcome
                    )
            except BaseException:
                if question.dismissed:
                    self._questions.pop(key, None)
                elif question.authority is None and question.session._accepting:
                    question.session.interrupt_turn()
                raise
            else:
                self._questions.pop(key, None)
            finally:
                question.task = None

        task = self._operations.admit(decide, control=True)
        question.task = task

        def finished(result: asyncio.Task[None]) -> None:
            if question.task is result:
                question.task = None

        task.add_done_callback(finished)
        return task
