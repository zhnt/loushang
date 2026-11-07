"""Coding-owned hosted Session adapter for the G11 AppService boundary."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from loushang.ai.model import model_selection_ref, normalize_model_selection
from loushang.apphost import SessionDiscoveryScope, SessionIdentityEnvelopeV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    SessionEventKindV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionModelChoiceV1,
    SessionModelsV1,
    SessionOpenSpecV1,
    SessionSnapshotV1,
    SessionSubmissionModeV1,
    TranscriptRecordV1,
)
from loushang.appservice import HostedSessionEventListenerV1, HostedSessionPortV1
from loushang.appservice.resume_ports import (
    ResumeInputLookupQueryV1,
    ResumeInputLookupResultV1,
)
from loushang.harness.events import RuntimeEvent
from loushang.harness.session import (
    SessionControlPort,
    SessionOperationRuntime,
    SessionPromptRequest,
)
from loushang.harness.session.model_selection import (
    apply_session_model_selection,
    get_session_model_selection,
    iter_available_model_details,
    model_choice_data_from_details,
)

from .product_plan import CODING_PRODUCT_ID


@dataclass(frozen=True, slots=True)
class CodingHostedSnapshotProjectionV1:
    """Client-safe Product projection captured without exposing Product state."""

    title: str
    revision: int
    running: bool
    records: tuple[TranscriptRecordV1, ...] = ()
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Coding hosted snapshot title is invalid")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("Coding hosted snapshot revision is invalid")
        if type(self.running) is not bool:
            raise TypeError("Coding hosted snapshot running state is invalid")
        if type(self.truncated) is not bool:
            raise TypeError("Coding hosted snapshot omission flag is invalid")
        if any(type(item) is not TranscriptRecordV1 for item in self.records):
            raise TypeError("Coding hosted snapshot records are invalid")


@dataclass(frozen=True, slots=True)
class CodingHostedEventProjectionV1:
    """One bounded Product projection of a public Harness runtime event."""

    kind: SessionEventKindV1
    text: str | None = None
    interaction_id: str | None = None
    truncated: bool = False

    def __post_init__(self) -> None:
        if type(self.kind) is not SessionEventKindV1:
            raise TypeError("Coding hosted event kind is invalid")
        if type(self.truncated) is not bool:
            raise TypeError("Coding hosted event omission flag is invalid")
        SessionEventV1(
            session_id="projection",
            cursor=1,
            kind=self.kind,
            text=self.text,
            interaction_id=self.interaction_id,
        )


class CodingHostedSessionBindingV1(Protocol):
    """Owned Product binding returned by canonical create/resume composition."""

    @property
    def identity(self) -> SessionIdentityV1: ...

    @property
    def control(self) -> SessionControlPort | None: ...

    def project_snapshot(self) -> CodingHostedSnapshotProjectionV1: ...

    def project_event(
        self,
        event: RuntimeEvent[object],
    ) -> CodingHostedEventProjectionV1 | None: ...

    async def respond_interaction(
        self,
        interaction_id: str,
        outcome: str,
    ) -> bool: ...

    async def close(self) -> None: ...


CodingHostedOpen = Callable[
    [SessionOpenSpecV1], Awaitable[CodingHostedSessionBindingV1]
]


class CodingHostedSessionV1:
    """Adapt one already admitted Coding Session to Product-neutral AppService."""

    __slots__ = (
        "_binding",
        "_close_lock",
        "_close_task",
        "_cursor",
        "_listeners",
        "_operations",
        "_settled",
        "_submission_mode",
        "_unsubscribe",
        "_unsubscribed",
        "identity",
    )

    async def lookup_resume_input(
        self, query: ResumeInputLookupQueryV1,
    ) -> ResumeInputLookupResultV1:
        """Adapt the optional Product observation; scoped service owns reads."""

        from .hosted_session import _lookup_coding_resume_input

        if self._close_task is not None:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        return await _lookup_coding_resume_input(self._binding, query)

    def __init__(self, binding: CodingHostedSessionBindingV1, *,
        execution_submission: bool = False,
    ) -> None:
        self._require_binding(binding)
        if type(execution_submission) is not bool:
            raise TypeError("Coding hosted submission mode is invalid")
        identity = binding.identity
        if type(identity) is not SessionIdentityV1 or identity.product_id != (
            CODING_PRODUCT_ID
        ):
            raise TypeError("Coding hosted Session identity is invalid")
        self.identity = identity
        self._binding = binding
        self._submission_mode = (SessionSubmissionModeV1.EXECUTION if execution_submission
                                 else SessionSubmissionModeV1.LEGACY)
        control = binding.control
        self._operations = (
            None if control is None else SessionOperationRuntime(control)
        )
        self._listeners: set[HostedSessionEventListenerV1] = set()
        self._cursor = 0
        self._settled = False
        self._unsubscribed = False
        self._close_task: asyncio.Task[None] | None = None
        self._close_lock = asyncio.Lock()
        if control is None:
            self._unsubscribe = lambda: None
            return
        try:
            unsubscribe = control.subscribe_runtime_events(
                self._on_runtime_event
            )
        except BaseException:
            raise TypeError("Coding hosted event subscription is unavailable") from None
        if not callable(unsubscribe):
            raise TypeError("Coding hosted event subscription is unavailable")
        self._unsubscribe = unsubscribe

    async def snapshot(self) -> SessionSnapshotV1:
        self._require_open()
        try:
            projection = self._binding.project_snapshot()
        except BaseException:
            raise RuntimeError("coding_hosted_snapshot_unavailable") from None
        if type(projection) is not CodingHostedSnapshotProjectionV1:
            raise RuntimeError("coding_hosted_snapshot_unavailable")
        return SessionSnapshotV1(
            identity=self.identity,
            title=projection.title,
            cursor=self._cursor,
            revision=projection.revision,
            running=projection.running,
            records=projection.records,
            submission_mode=self._submission_mode,
        )

    def subscribe(
        self,
        listener: HostedSessionEventListenerV1,
    ) -> Callable[[], None]:
        self._require_open()
        if not callable(listener):
            raise TypeError("Coding hosted listener must be callable")
        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    async def start_turn(self, text: str) -> None:
        self._require_open()
        await self._require_operations().prompt(
            request=self._prompt_request(text),
        )

    def steer_turn(self, text: str) -> None:
        self._require_open()
        self._require_operations().steer(text)

    def follow_up_turn(self, text: str) -> None:
        self._require_open()
        self._require_operations().follow_up(text)

    def interrupt_turn(self) -> bool:
        self._require_open()
        return False if self._operations is None else self._operations.abort_turn()

    async def respond_interaction(
        self,
        interaction_id: str,
        outcome: InteractionOutcomeV1,
    ) -> bool:
        self._require_open()
        if self._operations is None:
            return False
        mapped = {
            InteractionOutcomeV1.APPROVE: "allow_once",
            InteractionOutcomeV1.DENY: "deny",
            InteractionOutcomeV1.CANCEL: "abort",
        }[outcome]
        try:
            result = await self._binding.respond_interaction(interaction_id, mapped)
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise RuntimeError("coding_hosted_interaction_unavailable") from None
        return result is True

    async def list_models(self) -> SessionModelsV1:
        self._require_open()
        control = self._binding.control
        active_model = getattr(getattr(control, "agent", None), "model", None)
        selection = normalize_model_selection(active_model)
        if selection is None:
            selection = await get_session_model_selection(control)
            active_model = selection
        current = model_selection_ref(selection) if selection is not None else None
        details = await iter_available_model_details(control)
        if active_model is not None:
            details.append(active_model)
        models: list[SessionModelChoiceV1] = []
        for choice in model_choice_data_from_details(details):
            reference = normalize_model_selection(choice.selection)
            if reference is None:
                continue
            models.append(SessionModelChoiceV1(
                id=choice.value,
                provider=reference.provider,
                endpoint_id=reference.endpoint_id,
                model_id=reference.model_id,
                label=choice.label,
                supports_thinking=bool(
                    getattr(choice.selection, "supports_thinking", False)
                    or getattr(choice.selection, "reasoning", False)
                ),
            ))
        visible = models[:256]
        active_choice = next((model for model in models[256:] if model.id == current), None)
        if active_choice is not None:
            visible[-1] = active_choice
        return SessionModelsV1(current, tuple(visible))

    async def select_model(self, model_id: str) -> SessionModelsV1:
        self._require_open()
        control = self._binding.control
        if getattr(control, "is_streaming", False):
            raise RuntimeError("coding_model_change_while_running")
        choices = model_choice_data_from_details(
            await iter_available_model_details(control)
        )
        selected = next(
            (choice.selection for choice in choices if choice.value == model_id), None
        )
        if selected is None:
            raise ValueError("coding_model_unavailable")
        await apply_session_model_selection(control, selected)
        return await self.list_models()

    async def close(self) -> None:
        async with self._close_lock:
            if self._settled:
                return
            if not self._unsubscribed:
                self._unsubscribed = True
                with suppress(BaseException):
                    self._unsubscribe()
                self._listeners.clear()
            if self._close_task is None:
                self._close_task = asyncio.create_task(self._binding.close())
            task = self._close_task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except BaseException:
            async with self._close_lock:
                if self._close_task is task:
                    self._close_task = None
            raise
        async with self._close_lock:
            if self._close_task is task:
                self._settled = True
                self._close_task = None

    @property
    def closed(self) -> bool:
        return self._unsubscribed

    async def _on_runtime_event(self, event: RuntimeEvent[object]) -> None:
        if self._unsubscribed:
            return
        try:
            projection = self._binding.project_event(event)
        except BaseException:
            projection = CodingHostedEventProjectionV1(
                SessionEventKindV1.ERROR,
                "event_projection_unavailable",
            )
        if projection is None:
            return
        if type(projection) is not CodingHostedEventProjectionV1:
            projection = CodingHostedEventProjectionV1(
                SessionEventKindV1.ERROR,
                "event_projection_unavailable",
            )
        self._cursor += 1
        hosted_event = SessionEventV1(
            session_id=self.identity.session_id,
            cursor=self._cursor,
            kind=projection.kind,
            text=projection.text,
            interaction_id=projection.interaction_id,
        )
        self._observe_projection(projection, hosted_event)
        for listener in tuple(self._listeners):
            try:
                result = listener(hosted_event)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    def _observe_projection(
        self, projection: CodingHostedEventProjectionV1, event: SessionEventV1
    ) -> None:
        """Synchronous Product observation before optional delivery listeners."""

    @staticmethod
    def _prompt_request(text: str) -> SessionPromptRequest:
        return SessionPromptRequest(text=text, source="appservice")

    def _require_open(self) -> None:
        if self._unsubscribed:
            raise RuntimeError("coding_hosted_session_closed")

    def _require_operations(self) -> SessionOperationRuntime:
        if self._operations is None:
            from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        return self._operations

    @staticmethod
    def _require_binding(binding: object) -> None:
        from .hosted_session import _require_coding_hosted_binding

        _require_coding_hosted_binding(binding)


def coding_hosted_identity_from_envelope(
    envelope: SessionIdentityEnvelopeV1,
    *,
    discovery_scope: SessionDiscoveryScope,
    scope_fingerprint: str,
) -> SessionIdentityV1:
    """Project a canonical path-free AppHost envelope into the App Contract."""

    from .hosted_catalog import _coding_hosted_identity_from_envelope

    return _coding_hosted_identity_from_envelope(
        envelope, discovery_scope=discovery_scope, scope_fingerprint=scope_fingerprint,
    )


class CodingHostedSessionResolverV1:
    """Route explicit canonical create/resume requests to owned Coding bindings."""

    __slots__ = ("_create", "_resume")

    def __init__(self, *, create: CodingHostedOpen, resume: CodingHostedOpen) -> None:
        if not callable(create) or not callable(resume):
            raise TypeError("Coding hosted resolver callbacks must be callable")
        self._create = create
        self._resume = resume

    async def open_session(self, request: SessionOpenSpecV1) -> HostedSessionPortV1:
        if type(request) is not SessionOpenSpecV1 or request.product_id != (
            CODING_PRODUCT_ID
        ):
            raise ValueError("Coding hosted open request is invalid")
        callback = self._create if request.session_id is None else self._resume
        binding = await callback(request)
        try:
            session = CodingHostedSessionV1(binding)
        except BaseException:
            await self._close_rejected(binding)
            raise
        if not self._matches(request, session.identity):
            await session.close()
            raise ValueError("Coding hosted binding identity mismatch")
        return session

    @staticmethod
    async def _close_rejected(binding: object) -> None:
        close = getattr(binding, "close", None)
        if not inspect.iscoroutinefunction(close):
            return
        task = asyncio.create_task(close())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            with suppress(BaseException):
                await asyncio.shield(task)
            raise

    @staticmethod
    def _matches(request: SessionOpenSpecV1, identity: SessionIdentityV1) -> bool:
        return (
            identity.product_id == request.product_id
            and identity.continuity_id == request.continuity_id
            and identity.scope is request.scope
            and identity.scope_fingerprint == request.scope_fingerprint
            and (request.session_id is None or identity.session_id == request.session_id)
        )


__all__ = [
    "CodingHostedEventProjectionV1",
    "CodingHostedSessionBindingV1",
    "CodingHostedSessionResolverV1",
    "CodingHostedSessionV1",
    "CodingHostedSnapshotProjectionV1",
    "coding_hosted_identity_from_envelope",
]
