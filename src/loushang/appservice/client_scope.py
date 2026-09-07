"""Opt-in semantic client lifetimes; no transport, Product or process ownership.

Only the owning application composes this edge. It must not expose its legacy
unscoped client alongside these scoped clients to untrusted callers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TypeVar

from loushang.appserver.protocol import (
    AckV1,
    AppErrorCodeV1,
    AppServiceError,
    AttachmentEventV1,
    InteractionRespondV1,
    MuxAttachmentV1,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxListResultV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSelectorV1,
    MuxSpaceV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TurnInterruptV1,
    TurnTextV1,
)

from ._operations import _observe, _OwnedAppOperations
from ._scope_interactions import _ScopeInteractions
from .runtime import AppServiceV1, _SessionOwner

_Result = TypeVar("_Result")


@dataclass(eq=False, slots=True)
class _Controller:
    scope: AppClientScopeV1
    mux_id: str
    attachment: MuxAttachmentV1 | None = None
    operation: asyncio.Task[object] | None = None
    cleanup: asyncio.Task[None] | None = None
    fenced: bool = False


class ScopedAppServiceV1:
    """One application's bounded client-scope and accepted-work owner."""

    def __init__(self, service: AppServiceV1, *, close_timeout: float = 10.0) -> None:
        if type(service) is not AppServiceV1:
            raise TypeError("service must be AppServiceV1")
        if service._client_scopes is not None or service._attachments or service._closed:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        if (
            len(service._sessions) + len(service._cleanup_debt) > 64
            or len(service._mux_by_id) > 32
        ):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        self._operations = _OwnedAppOperations(close_timeout=close_timeout)
        self._service = service
        self._timeout = float(close_timeout)
        self._scopes: set[AppClientScopeV1] = set()
        self._controllers: dict[str, _Controller] = {}
        self._opening = 0
        self._creating = 0
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._interactions = _ScopeInteractions(self._operations, self._authority)
        service._client_scopes = self
        for session in service._sessions.values():
            session.event_handler = self._interactions.on_event

    @property
    def pending_counts(self) -> tuple[int, int]:
        return self._operations.pending_counts

    def open_client_scope(self) -> AppClientScopeV1:
        if self._closed or self._service._closed:
            raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)
        if len(self._scopes) >= 8:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        scope = AppClientScopeV1(self, _token=self)
        self._scopes.add(scope)
        return scope

    async def close(self) -> None:
        self._closed = True
        task = self._close_task
        if task is None or (task.done() and (task.cancelled() or task.exception())):
            operation = self._close_once()
            try:
                task = asyncio.create_task(operation)
            except BaseException:
                operation.close()
                raise
            task.add_done_callback(_observe)
            self._close_task = task
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        results = await asyncio.gather(
            *(scope.close() for scope in tuple(self._scopes)), return_exceptions=True
        )
        try:
            await asyncio.wait_for(
                self._interactions.revoke(None), timeout=self._timeout
            )
        except (AppServiceError, TimeoutError):
            results.append(AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE))
        if any(isinstance(result, BaseException) for result in results):
            # Keep internal settlement admission available on an unclean stop.
            # AppService still closes Product ports, then retries this debt.
            self._operations.cancel_ordinary()
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
        await self._operations.close()

    def _authority(self, session_id: str) -> str | None:
        for controller in self._controllers.values():
            attachment = controller.attachment
            if controller.fenced or controller.scope._closed or attachment is None:
                continue
            if any(
                item.member.session.session_id == session_id
                for item in attachment.sessions
            ):
                return attachment.attachment_id
        return None

    async def _reset_attachment(self, controller: _Controller) -> None:
        attachment = controller.attachment
        if attachment is None:
            return
        await self._interactions.revoke(attachment.attachment_id)
        try:
            await self._service.detach_mux(MuxDetachV1(
                attachment.attachment_id, attachment.controller_generation
            ))
        except AppServiceError as error:
            retired = (
                self._service._closed
                and attachment.attachment_id not in self._service._attachments
            )
            if error.code is not AppErrorCodeV1.STALE_ATTACHMENT and not retired:
                raise
        controller.attachment = None

    async def _release_controller(self, controller: _Controller) -> None:
        operation = controller.operation
        if (
            operation is not None and not operation.done()
            and operation is not asyncio.current_task()
        ):
            await asyncio.wait({operation}, timeout=self._timeout)
            if not operation.done():
                raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
        await self._reset_attachment(controller)
        if self._controllers.get(controller.mux_id) is controller:
            self._controllers.pop(controller.mux_id)
            controller.scope._controllers.pop(controller.mux_id, None)


class AppClientScopeV1:
    """Owned AppClient capability; close fences delivery authority, not turns."""

    def __init__(self, owner: ScopedAppServiceV1, *, _token: object) -> None:
        if _token is not owner:
            raise TypeError("client scopes require the application factory")
        self._owner = owner
        self._service = owner._service
        self._controllers: dict[str, _Controller] = {}
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    def _require_open(self) -> None:
        if self._closed or self._owner._closed or self._service._closed:
            raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)

    async def create_mux(self, request: MuxCreateV1) -> MuxSpaceV1:
        self._require_open()
        self._service._require_request(request, MuxCreateV1)
        owner = self._owner
        if len(self._service._mux_by_id) + owner._creating >= 32:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        released = False

        def release(_task: object = None) -> None:
            nonlocal released
            if not released:
                released = True
                owner._creating -= 1

        async def create() -> MuxSpaceV1:
            try:
                return await self._service.create_mux(request)
            finally:
                release()

        task = owner._operations.admit(create)
        owner._creating += 1
        task.add_done_callback(release)
        return await asyncio.shield(task)

    async def list_muxes(self) -> MuxListResultV1:
        self._require_open()
        return await self._service.list_muxes()

    async def read_mux(self, request: MuxReadV1) -> MuxSpaceV1:
        self._require_open()
        return await self._service.read_mux(request)

    async def _canonical(self, selector: MuxSelectorV1) -> MuxSpaceV1:
        self._require_open()
        mux = await self._service.read_mux(MuxReadV1(selector))
        self._require_open()
        return mux

    def _controller(self, mux_id: str) -> _Controller:
        self._require_open()
        controller = self._controllers.get(mux_id)
        if controller is None or controller.cleanup is not None:
            raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)
        if controller.operation is not None and not controller.operation.done():
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return controller

    async def attach_mux(self, request: MuxAttachV1) -> MuxAttachmentV1:
        self._service._require_request(request, MuxAttachV1)
        mux = await self._canonical(request.selector)
        controller = self._owner._controllers.get(mux.mux_space_id)
        fresh = controller is None
        if controller is not None and controller.scope is not self:
            raise AppServiceError(AppErrorCodeV1.ALREADY_ATTACHED)
        if controller is None:
            controller = _Controller(self, mux.mux_space_id)
        else:
            controller = self._controller(mux.mux_space_id)
        selected = controller

        async def attach() -> MuxAttachmentV1:
            await self._owner._reset_attachment(selected)
            await self._owner._interactions.settle_unowned(frozenset(
                member.session.session_id for member in mux.members
            ))
            value = await self._service.attach_mux(replace(
                request, selector=MuxSelectorV1(mux_space_id=selected.mux_id)
            ))
            selected.attachment = value
            await self._owner._interactions.settle_unowned(frozenset(
                member.session.session_id for member in value.mux_space.members
            ))
            if self._closed:
                await self._owner._reset_attachment(selected)
                raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)
            selected.fenced = False
            return value

        task = self._owner._operations.admit(attach)
        selected.fenced = True
        selected.operation = task
        if fresh:
            self._owner._controllers[selected.mux_id] = selected
            self._controllers[selected.mux_id] = selected
        return await asyncio.shield(task)

    def _attachment(self, attachment_id: str, generation: int) -> _Controller:
        self._require_open()
        for controller in self._controllers.values():
            value = controller.attachment
            if (
                not controller.fenced and value is not None
                and value.attachment_id == attachment_id
                and value.controller_generation == generation
            ):
                return controller
        raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)

    async def detach_mux(self, request: MuxDetachV1) -> AckV1:
        self._service._require_request(request, MuxDetachV1)
        controller = self._attachment(
            request.attachment_id, request.controller_generation
        )
        task = self._owner._operations.admit(
            lambda: self._owner._release_controller(controller), control=True
        )
        controller.fenced = True
        controller.cleanup = task
        await asyncio.shield(task)
        return AckV1()

    async def _change(
        self, selector: MuxSelectorV1,
        operation: Callable[[MuxSelectorV1], Awaitable[_Result]],
        *, opening: bool = False, closing: bool = False,
        stopping_member: str | None = None,
    ) -> _Result:
        mux = await self._canonical(selector)
        controller = self._controller(mux.mux_space_id)
        owner = self._owner
        stopped_sessions = frozenset(
            member.session.session_id for member in mux.members
            if closing or member.member_id == stopping_member
        )
        if opening and (
            len(self._service._sessions) + len(self._service._cleanup_debt)
            + owner._opening >= 64
        ):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

        opening_released = False

        def release_opening(_task: object = None) -> None:
            nonlocal opening_released
            if opening and not opening_released:
                opening_released = True
                owner._opening -= 1

        async def change() -> _Result:
            try:
                await owner._reset_attachment(controller)
                owner._operations.cancel_sessions(stopped_sessions)
                result = await operation(MuxSelectorV1(mux_space_id=controller.mux_id))
                await owner._operations.join_sessions(stopped_sessions)
                if closing:
                    await owner._release_controller(controller)
                return result
            finally:
                release_opening()

        task = owner._operations.admit(change)
        controller.fenced = True
        controller.operation = task
        if opening:
            owner._opening += 1
            task.add_done_callback(release_opening)
        return await asyncio.shield(task)

    async def open_member(self, request: MuxMemberOpenV1) -> MuxSpaceV1:
        self._service._require_request(request, MuxMemberOpenV1)
        return await self._change(
            request.selector,
            lambda selector: self._service.open_member(replace(request, selector=selector)),
            opening=True,
        )

    async def close_member(self, request: MuxMemberCloseV1) -> MuxSpaceV1:
        self._service._require_request(request, MuxMemberCloseV1)
        return await self._change(
            request.selector,
            lambda selector: self._service.close_member(replace(request, selector=selector)),
            stopping_member=request.member_id if request.close_session else None,
        )

    async def close_mux(self, request: MuxCloseV1) -> AckV1:
        self._service._require_request(request, MuxCloseV1)
        return await self._change(
            request.selector, lambda selector: self._service.close_mux(MuxCloseV1(selector)),
            closing=True,
        )

    async def _session(
        self, attachment_id: str, generation: int, member_id: str
    ) -> _SessionOwner:
        controller = self._attachment(attachment_id, generation)
        session = await self._service._resolve_member_session(
            attachment_id, generation, member_id
        )
        if self._attachment(attachment_id, generation) is not controller:
            raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)
        return session

    async def snapshot_session(
        self, request: SessionSnapshotRequestV1
    ) -> SessionSnapshotV1:
        self._service._require_request(request, SessionSnapshotRequestV1)
        session = await self._session(
            request.attachment_id, request.controller_generation, request.member_id
        )
        value = await session.snapshot()
        self._attachment(request.attachment_id, request.controller_generation)
        return value

    async def start_turn(self, request: TurnTextV1) -> AckV1:
        self._service._require_request(request, TurnTextV1)
        session = await self._session(
            request.attachment_id, request.controller_generation, request.member_id
        )
        await self._owner._operations.execute(
            lambda: session.start_turn(request.text), key=session.identity.session_id
        )
        return AckV1()

    async def steer_turn(self, request: TurnTextV1) -> AckV1:
        self._service._require_request(request, TurnTextV1)
        session = await self._session(
            request.attachment_id, request.controller_generation, request.member_id
        )
        session.steer_turn(request.text)
        return AckV1()

    async def follow_up_turn(self, request: TurnTextV1) -> AckV1:
        self._service._require_request(request, TurnTextV1)
        session = await self._session(
            request.attachment_id, request.controller_generation, request.member_id
        )
        session.follow_up_turn(request.text)
        return AckV1()

    async def interrupt_turn(self, request: TurnInterruptV1) -> AckV1:
        self._service._require_request(request, TurnInterruptV1)
        session = await self._session(
            request.attachment_id, request.controller_generation, request.member_id
        )
        session.interrupt_turn()
        return AckV1()

    async def respond_interaction(self, request: InteractionRespondV1) -> AckV1:
        self._service._require_request(request, InteractionRespondV1)
        session = await self._session(
            request.attachment_id, request.controller_generation, request.member_id
        )
        task = self._owner._interactions.respond(
            session, request.interaction_id, request.attachment_id, request.outcome
        )
        await asyncio.shield(task)
        return AckV1()

    async def read_events(
        self, *, attachment_id: str, controller_generation: int, limit: int = 64
    ) -> tuple[AttachmentEventV1, ...]:
        self._attachment(attachment_id, controller_generation)
        result = await self._service.read_events(
            attachment_id=attachment_id,
            controller_generation=controller_generation, limit=limit,
        )
        self._attachment(attachment_id, controller_generation)
        return result

    async def close(self) -> None:
        self._closed = True
        for controller in self._controllers.values():
            controller.fenced = True
        task = self._close_task
        if task is None or (task.done() and (task.cancelled() or task.exception())):
            # One retained waiter per bounded scope, not a Product operation.
            # It must not occupy the control slot needed by its own denial.
            operation = self._settle()
            try:
                task = asyncio.create_task(operation)
            except BaseException:
                operation.close()
                raise
            task.add_done_callback(_observe)
            self._close_task = task
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self._owner._timeout)
        except (TimeoutError, AppServiceError):
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE) from None

    async def _settle(self) -> None:
        for controller in tuple(self._controllers.values()):
            cleanup = controller.cleanup
            if cleanup is not None and not cleanup.done():
                await asyncio.shield(cleanup)
            if self._controllers.get(controller.mux_id) is controller:
                await self._owner._release_controller(controller)
        self._owner._scopes.discard(self)


__all__ = ["AppClientScopeV1", "ScopedAppServiceV1"]
