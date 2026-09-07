"""Product-neutral in-process AppService and named MuxSpace coordination."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from secrets import token_hex
from typing import cast

from loushang.appserver.protocol import (
    MAX_MEMBERS,
    MAX_MUX_SPACES,
    AckV1,
    AppErrorCodeV1,
    AppServiceError,
    AttachedSessionV1,
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
    MuxSpaceMemberV1,
    MuxSpaceV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TurnInterruptV1,
    TurnTextV1,
)

from .ports import HostedSessionPortV1, HostedSessionResolverV1


def _error(code: AppErrorCodeV1) -> AppServiceError:
    return AppServiceError(code)


class _Attachment:
    __slots__ = (
        "attachment_id",
        "controller_generation",
        "lagged",
        "member_cursors",
        "member_ids",
        "mux_space_id",
        "queue",
        "settled",
    )

    def __init__(
        self,
        *,
        attachment_id: str,
        mux_space_id: str,
        controller_generation: int,
        mailbox_capacity: int,
    ) -> None:
        self.attachment_id = attachment_id
        self.mux_space_id = mux_space_id
        self.controller_generation = controller_generation
        self.queue: asyncio.Queue[AttachmentEventV1] = asyncio.Queue(
            maxsize=mailbox_capacity
        )
        self.member_ids: dict[str, str] = {}
        self.member_cursors: dict[str, int] | None = None
        self.lagged = False
        self.settled = False

    @property
    def active(self) -> bool:
        return not self.settled and not self.lagged

    def bind_member(self, identity: SessionIdentityV1, member_id: str) -> None:
        self.member_ids[identity.session_id] = member_id

    def activate(self, snapshots: tuple[SessionSnapshotV1, ...]) -> None:
        if self.settled or self.lagged:
            raise _error(AppErrorCodeV1.SNAPSHOT_REQUIRED)
        self.member_cursors = {
            snapshot.identity.session_id: snapshot.cursor for snapshot in snapshots
        }
        retained = tuple(self._drain_raw())
        for event in retained:
            threshold = self.member_cursors.get(event.event.session_id)
            if threshold is None or event.event.cursor <= threshold:
                continue
            self._put(event)
        if self.lagged:
            raise _error(AppErrorCodeV1.SNAPSHOT_REQUIRED)

    def push(self, event: SessionEventV1) -> None:
        if self.settled or self.lagged:
            return
        member_id = self.member_ids.get(event.session_id)
        if member_id is None:
            return
        if self.member_cursors is not None:
            threshold = self.member_cursors.get(event.session_id)
            if threshold is None or event.cursor <= threshold:
                return
        self._put(AttachmentEventV1(self.attachment_id, member_id, event))

    def _put(self, event: AttachmentEventV1) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.lagged = True
            self._drain_raw()

    def read(self, *, limit: int) -> tuple[AttachmentEventV1, ...]:
        if self.settled:
            raise _error(AppErrorCodeV1.STALE_ATTACHMENT)
        if self.lagged:
            raise _error(AppErrorCodeV1.ATTACHMENT_LAGGED)
        values: list[AttachmentEventV1] = []
        while len(values) < limit:
            try:
                values.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return tuple(values)

    def invalidate(self) -> None:
        self.lagged = True
        self._drain_raw()

    def settle(self) -> None:
        self.settled = True
        self._drain_raw()
        self.member_ids.clear()
        self.member_cursors = None

    def _drain_raw(self) -> list[AttachmentEventV1]:
        values: list[AttachmentEventV1] = []
        while True:
            try:
                values.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                return values


class _SessionOwner:
    __slots__ = (
        "_accepting",
        "_attachments",
        "_close_lock",
        "_close_task",
        "_latest_cursor",
        "_port",
        "_settled",
        "_unsubscribe",
        "_unsubscribed",
        "identity",
    )

    def __init__(self, port: HostedSessionPortV1) -> None:
        close = getattr(port, "close", None)
        subscribe = getattr(port, "subscribe", None)
        if not inspect.iscoroutinefunction(close) or not callable(subscribe):
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE)
        try:
            identity = port.identity
        except BaseException:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE) from None
        if type(identity) is not SessionIdentityV1:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE)
        self.identity = identity
        self._port = port
        self._attachments: dict[str, _Attachment] = {}
        self._latest_cursor = 0
        self._accepting = True
        self._settled = False
        self._unsubscribed = False
        self._close_task: asyncio.Task[None] | None = None
        self._close_lock = asyncio.Lock()
        try:
            self._unsubscribe = subscribe(self._on_event)
        except BaseException:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE) from None
        if not callable(self._unsubscribe):
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE)

    def add_attachment(self, attachment: _Attachment, member_id: str) -> None:
        if not self._accepting:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE)
        self._attachments[attachment.attachment_id] = attachment
        attachment.bind_member(self.identity, member_id)

    def remove_attachment(self, attachment: _Attachment) -> None:
        self._attachments.pop(attachment.attachment_id, None)

    async def snapshot(self) -> SessionSnapshotV1:
        if not self._accepting:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE)
        try:
            value = await self._port.snapshot()
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE) from None
        if type(value) is not SessionSnapshotV1 or value.identity != self.identity:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE)
        self._latest_cursor = max(self._latest_cursor, value.cursor)
        return value

    async def start_turn(self, text: str) -> None:
        await self._invoke_async(self._port.start_turn, text)

    def steer_turn(self, text: str) -> None:
        self._invoke_sync(self._port.steer_turn, text)

    def follow_up_turn(self, text: str) -> None:
        self._invoke_sync(self._port.follow_up_turn, text)

    def interrupt_turn(self) -> None:
        result = self._invoke_sync(self._port.interrupt_turn)
        if type(result) is not bool:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    async def respond_interaction(
        self,
        interaction_id: str,
        outcome: object,
    ) -> None:
        result = await self._invoke_async(
            self._port.respond_interaction,
            interaction_id,
            outcome,
        )
        if result is not True:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    async def _invoke_async(self, callback: Callable[..., object], *args: object) -> object:
        if not self._accepting:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE)
        try:
            value = callback(*args)
            if not inspect.isawaitable(value):
                raise TypeError
            return await value
        except asyncio.CancelledError:
            raise
        except AppServiceError:
            raise
        except BaseException:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None

    def _invoke_sync(self, callback: Callable[..., object], *args: object) -> object:
        if not self._accepting:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE)
        try:
            value = callback(*args)
            if inspect.isawaitable(value):
                raise TypeError
            return value
        except AppServiceError:
            raise
        except BaseException:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None

    async def _on_event(self, event: SessionEventV1) -> None:
        if not self._accepting:
            return
        if type(event) is not SessionEventV1 or event.session_id != self.identity.session_id:
            self._invalidate_attachments()
            return
        if event.cursor <= self._latest_cursor:
            return
        if self._latest_cursor and event.cursor != self._latest_cursor + 1:
            self._invalidate_attachments()
        self._latest_cursor = event.cursor
        for attachment in tuple(self._attachments.values()):
            attachment.push(event)

    def _invalidate_attachments(self) -> None:
        for attachment in tuple(self._attachments.values()):
            attachment.invalidate()

    async def close(self) -> None:
        async with self._close_lock:
            if self._settled:
                return
            self._accepting = False
            if not self._unsubscribed:
                self._unsubscribed = True
                with suppress(BaseException):
                    self._unsubscribe()
                self._invalidate_attachments()
                self._attachments.clear()
            if self._close_task is None:
                self._close_task = asyncio.create_task(self._port.close())
            task = self._close_task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except BaseException:
            async with self._close_lock:
                if self._close_task is task:
                    self._close_task = None
            raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE) from None
        async with self._close_lock:
            if self._close_task is task:
                self._settled = True
                self._close_task = None


@dataclass(frozen=True, slots=True)
class _Member:
    member_id: str
    title: str
    session: _SessionOwner


class _MuxOwner:
    __slots__ = (
        "attachments",
        "closed",
        "lock",
        "members",
        "mux_space_id",
        "name",
        "next_generation",
        "revision",
    )

    def __init__(self, mux_space_id: str, name: str) -> None:
        self.mux_space_id = mux_space_id
        self.name = name
        self.revision = 1
        self.members: list[_Member] = []
        self.attachments: dict[str, _Attachment] = {}
        self.next_generation = 0
        self.closed = False
        self.lock = asyncio.Lock()

    def projection(self) -> MuxSpaceV1:
        return MuxSpaceV1(
            mux_space_id=self.mux_space_id,
            name=self.name,
            revision=self.revision,
            members=tuple(
                MuxSpaceMemberV1(
                    member_id=member.member_id,
                    session=member.session.identity,
                    title=member.title,
                    position=index,
                )
                for index, member in enumerate(self.members, 1)
            ),
        )

    def take_attachments(self) -> tuple[_Attachment, ...]:
        attachments = tuple(self.attachments.values())
        self.attachments.clear()
        return attachments


class AppServiceV1:
    """In-process hosted application boundary with no transport authority."""

    __slots__ = (
        "_attachments",
        "_cleanup_debt",
        "_close_timeout_seconds",
        "_closed",
        "_id_factory",
        "_mux_by_id",
        "_mux_by_name",
        "_resolver",
        "_sessions",
        "_state_lock",
        "product_id",
    )

    def __init__(
        self,
        *,
        product_id: str,
        resolver: HostedSessionResolverV1,
        id_factory: Callable[[], str] | None = None,
        close_timeout_seconds: float = 10.0,
    ) -> None:
        if not product_id:
            raise ValueError("product_id must be non-empty")
        open_session = getattr(resolver, "open_session", None)
        if not inspect.iscoroutinefunction(open_session):
            raise TypeError("resolver must provide async open_session")
        if (
            isinstance(close_timeout_seconds, bool)
            or not isinstance(close_timeout_seconds, (int, float))
            or not 0 < close_timeout_seconds <= 60
        ):
            raise ValueError("close_timeout_seconds must be in (0, 60]")
        self.product_id = product_id
        self._resolver = resolver
        self._id_factory = id_factory or (lambda: token_hex(16))
        self._state_lock = asyncio.Lock()
        self._mux_by_id: dict[str, _MuxOwner] = {}
        self._mux_by_name: dict[str, _MuxOwner] = {}
        self._sessions: dict[str, _SessionOwner] = {}
        self._attachments: dict[str, tuple[_MuxOwner, _Attachment]] = {}
        self._cleanup_debt: set[_SessionOwner] = set()
        self._close_timeout_seconds = float(close_timeout_seconds)
        self._closed = False

    async def create_mux(self, request: MuxCreateV1) -> MuxSpaceV1:
        if type(request) is not MuxCreateV1:
            raise _error(AppErrorCodeV1.INVALID_REQUEST)
        async with self._state_lock:
            self._require_open()
            if request.name in self._mux_by_name:
                raise _error(AppErrorCodeV1.ALREADY_EXISTS)
            if len(self._mux_by_id) >= MAX_MUX_SPACES:
                raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            mux_space_id = self._new_id()
            if mux_space_id in self._mux_by_id:
                raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            mux = _MuxOwner(mux_space_id, request.name)
            self._mux_by_id[mux_space_id] = mux
            self._mux_by_name[request.name] = mux
            return mux.projection()

    async def list_muxes(self) -> MuxListResultV1:
        async with self._state_lock:
            self._require_open()
            muxes = tuple(sorted(self._mux_by_id.values(), key=lambda item: item.name))
        projections: list[MuxSpaceV1] = []
        for mux in muxes:
            async with mux.lock:
                if not mux.closed:
                    projections.append(mux.projection())
        return MuxListResultV1(tuple(projections))

    async def read_mux(self, request: MuxReadV1) -> MuxSpaceV1:
        self._require_request(request, MuxReadV1)
        mux = await self._resolve_mux(request.selector)
        async with mux.lock:
            self._require_mux_open(mux)
            return mux.projection()

    async def attach_mux(self, request: MuxAttachV1) -> MuxAttachmentV1:
        self._require_request(request, MuxAttachV1)
        mux = await self._resolve_mux(request.selector)
        attachment = _Attachment(
            attachment_id=self._new_id(),
            mux_space_id=mux.mux_space_id,
            controller_generation=1,
            mailbox_capacity=request.mailbox_capacity,
        )
        members: tuple[_Member, ...] = ()
        registered = False
        try:
            async with self._state_lock:
                self._require_open()
                async with mux.lock:
                    self._require_mux_open(mux)
                    if attachment.attachment_id in self._attachments:
                        raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
                    mux.next_generation += 1
                    attachment.controller_generation = mux.next_generation
                    revision = mux.revision
                    members = tuple(mux.members)
                    mux.attachments[attachment.attachment_id] = attachment
                    self._attachments[attachment.attachment_id] = (mux, attachment)
                    registered = True
                    for member in members:
                        member.session.add_attachment(attachment, member.member_id)
            snapshots = tuple(
                await asyncio.gather(*(member.session.snapshot() for member in members))
            )
            async with mux.lock:
                if (
                    mux.closed
                    or mux.revision != revision
                    or mux.attachments.get(attachment.attachment_id) is not attachment
                ):
                    raise _error(AppErrorCodeV1.REVISION_CONFLICT)
                projection = mux.projection()
                attachment.activate(snapshots)
            return MuxAttachmentV1(
                attachment_id=attachment.attachment_id,
                mux_space=projection,
                controller_generation=attachment.controller_generation,
                sessions=tuple(
                    AttachedSessionV1(member, snapshot)
                    for member, snapshot in zip(projection.members, snapshots, strict=True)
                ),
            )
        except BaseException:
            if registered:
                await self._complete_cleanup(
                    self._discard_attachment(mux, attachment, members)
                )
            raise

    async def detach_mux(self, request: MuxDetachV1) -> AckV1:
        self._require_request(request, MuxDetachV1)
        async with self._state_lock:
            self._require_open()
            pair = self._attachments.get(request.attachment_id)
            if pair is None:
                raise _error(AppErrorCodeV1.STALE_ATTACHMENT)
            mux, attachment = pair
            if attachment.controller_generation != request.controller_generation:
                raise _error(AppErrorCodeV1.STALE_ATTACHMENT)
            async with mux.lock:
                mux.attachments.pop(attachment.attachment_id, None)
                self._attachments.pop(attachment.attachment_id, None)
                self._settle_attachments((attachment,), tuple(mux.members))
        return AckV1()

    async def close_mux(self, request: MuxCloseV1) -> AckV1:
        self._require_request(request, MuxCloseV1)
        mux = await self._resolve_mux(request.selector)
        async with self._state_lock:
            self._require_open()
            async with mux.lock:
                if mux.closed:
                    return AckV1()
                mux.closed = True
                attachments = mux.take_attachments()
                members = tuple(mux.members)
                mux.members.clear()
                mux.revision += 1
                self._mux_by_id.pop(mux.mux_space_id, None)
                self._mux_by_name.pop(mux.name, None)
                for attachment in attachments:
                    self._attachments.pop(attachment.attachment_id, None)
                self._settle_attachments(attachments, members)
        await self._close_sessions(tuple(member.session for member in members))
        return AckV1()

    async def open_member(self, request: MuxMemberOpenV1) -> MuxSpaceV1:
        self._require_request(request, MuxMemberOpenV1)
        if request.session.product_id != self.product_id:
            raise _error(AppErrorCodeV1.PRODUCT_MISMATCH)
        mux = await self._resolve_mux(request.selector)
        try:
            port = await self._resolver.open_session(request.session)
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE) from None
        try:
            session = _SessionOwner(port)
        except BaseException:
            close = getattr(port, "close", None)
            if inspect.iscoroutinefunction(close):
                try:
                    await asyncio.wait_for(
                        close(),
                        timeout=self._close_timeout_seconds,
                    )
                except BaseException:
                    raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE) from None
            raise
        if not self._identity_matches(request, session.identity):
            await self._complete_cleanup(self._close_sessions((session,)))
            raise _error(AppErrorCodeV1.PRODUCT_MISMATCH)
        try:
            member = _Member(self._new_id(), request.session.title, session)
            async with self._state_lock:
                self._require_open()
                if session.identity.session_id in self._sessions:
                    raise _error(AppErrorCodeV1.ALREADY_EXISTS)
                async with mux.lock:
                    self._require_mux_open(mux)
                    if len(mux.members) >= MAX_MEMBERS:
                        raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
                    if any(
                        item.member_id == member.member_id for item in mux.members
                    ):
                        raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
                    mux.members.append(member)
                    mux.revision += 1
                    attachments = mux.take_attachments()
                    self._sessions[session.identity.session_id] = session
                    for attachment in attachments:
                        self._attachments.pop(attachment.attachment_id, None)
                    self._settle_attachments(attachments, tuple(mux.members))
                    projection = mux.projection()
            return projection
        except BaseException:
            await self._complete_cleanup(self._close_sessions((session,)))
            raise

    async def close_member(self, request: MuxMemberCloseV1) -> MuxSpaceV1:
        self._require_request(request, MuxMemberCloseV1)
        mux = await self._resolve_mux(request.selector)
        async with self._state_lock:
            self._require_open()
            async with mux.lock:
                self._require_mux_open(mux)
                selected = next(
                    (item for item in mux.members if item.member_id == request.member_id),
                    None,
                )
                if selected is None:
                    raise _error(AppErrorCodeV1.NOT_FOUND)
                prior_members = tuple(mux.members)
                mux.members.remove(selected)
                mux.revision += 1
                attachments = mux.take_attachments()
                for attachment in attachments:
                    self._attachments.pop(attachment.attachment_id, None)
                self._settle_attachments(attachments, prior_members)
                projection = mux.projection()
        if request.close_session:
            await self._close_sessions((selected.session,))
        return projection

    async def snapshot_session(
        self,
        request: SessionSnapshotRequestV1,
    ) -> SessionSnapshotV1:
        self._require_request(request, SessionSnapshotRequestV1)
        session = await self._resolve_member_session(
            request.attachment_id,
            request.controller_generation,
            request.member_id,
        )
        return await session.snapshot()

    async def start_turn(self, request: TurnTextV1) -> AckV1:
        self._require_request(request, TurnTextV1)
        session = await self._resolve_text_session(request)
        await session.start_turn(request.text)
        return AckV1()

    async def steer_turn(self, request: TurnTextV1) -> AckV1:
        self._require_request(request, TurnTextV1)
        session = await self._resolve_text_session(request)
        session.steer_turn(request.text)
        return AckV1()

    async def follow_up_turn(self, request: TurnTextV1) -> AckV1:
        self._require_request(request, TurnTextV1)
        session = await self._resolve_text_session(request)
        session.follow_up_turn(request.text)
        return AckV1()

    async def interrupt_turn(self, request: TurnInterruptV1) -> AckV1:
        self._require_request(request, TurnInterruptV1)
        session = await self._resolve_member_session(
            request.attachment_id,
            request.controller_generation,
            request.member_id,
        )
        session.interrupt_turn()
        return AckV1()

    async def respond_interaction(self, request: InteractionRespondV1) -> AckV1:
        self._require_request(request, InteractionRespondV1)
        session = await self._resolve_member_session(
            request.attachment_id,
            request.controller_generation,
            request.member_id,
        )
        await session.respond_interaction(request.interaction_id, request.outcome)
        return AckV1()

    async def read_events(
        self,
        *,
        attachment_id: str,
        controller_generation: int,
        limit: int = 64,
    ) -> tuple[AttachmentEventV1, ...]:
        if type(limit) is not int or not 1 <= limit <= 1024:
            raise _error(AppErrorCodeV1.INVALID_REQUEST)
        try:
            MuxDetachV1(attachment_id, controller_generation)
        except (TypeError, ValueError):
            raise _error(AppErrorCodeV1.INVALID_REQUEST) from None
        _mux, attachment = await self._resolve_attachment(
            attachment_id,
            controller_generation,
        )
        return attachment.read(limit=limit)

    async def close(self) -> None:
        async with self._state_lock:
            if self._closed:
                muxes: tuple[_MuxOwner, ...] = ()
                attachments: tuple[_Attachment, ...] = ()
                sessions = tuple(self._cleanup_debt)
            else:
                self._closed = True
                muxes = tuple(self._mux_by_id.values())
                sessions = tuple(self._sessions.values())
                self._cleanup_debt.update(sessions)
                attachments = tuple(
                    item[1] for item in self._attachments.values()
                )
                self._mux_by_id.clear()
                self._mux_by_name.clear()
                self._sessions.clear()
                self._attachments.clear()
        for attachment in attachments:
            attachment.settle()
        for mux in muxes:
            async with mux.lock:
                mux.closed = True
                mux.attachments.clear()
                mux.members.clear()
                mux.revision += 1
        await self._close_sessions(sessions)

    async def _resolve_mux(self, selector: MuxSelectorV1) -> _MuxOwner:
        async with self._state_lock:
            self._require_open()
            mux = (
                self._mux_by_id.get(selector.mux_space_id)
                if selector.mux_space_id is not None
                else self._mux_by_name.get(cast(str, selector.name))
            )
        if mux is None:
            raise _error(AppErrorCodeV1.NOT_FOUND)
        return mux

    async def _resolve_attachment(
        self,
        attachment_id: str,
        controller_generation: int,
    ) -> tuple[_MuxOwner, _Attachment]:
        async with self._state_lock:
            self._require_open()
            pair = self._attachments.get(attachment_id)
        if pair is None:
            raise _error(AppErrorCodeV1.STALE_ATTACHMENT)
        mux, attachment = pair
        if (
            attachment.controller_generation != controller_generation
            or not attachment.active
        ):
            code = (
                AppErrorCodeV1.ATTACHMENT_LAGGED
                if attachment.lagged and not attachment.settled
                else AppErrorCodeV1.STALE_ATTACHMENT
            )
            raise _error(code)
        return mux, attachment

    async def _resolve_member_session(
        self,
        attachment_id: str,
        controller_generation: int,
        member_id: str,
    ) -> _SessionOwner:
        async with self._state_lock:
            self._require_open()
            pair = self._attachments.get(attachment_id)
            if pair is None:
                raise _error(AppErrorCodeV1.STALE_ATTACHMENT)
            mux, attachment = pair
            if (
                attachment.controller_generation != controller_generation
                or not attachment.active
            ):
                raise _error(AppErrorCodeV1.STALE_ATTACHMENT)
            async with mux.lock:
                if (
                    not attachment.active
                    or attachment.controller_generation != mux.next_generation
                ):
                    raise _error(AppErrorCodeV1.STALE_ATTACHMENT)
                selected = next(
                    (member for member in mux.members if member.member_id == member_id),
                    None,
                )
        if selected is None:
            raise _error(AppErrorCodeV1.NOT_FOUND)
        return selected.session

    async def _resolve_text_session(self, request: TurnTextV1) -> _SessionOwner:
        return await self._resolve_member_session(
            request.attachment_id,
            request.controller_generation,
            request.member_id,
        )

    async def _discard_attachment(
        self,
        mux: _MuxOwner,
        attachment: _Attachment,
        members: tuple[_Member, ...],
    ) -> None:
        async with self._state_lock:
            async with mux.lock:
                mux.attachments.pop(attachment.attachment_id, None)
                self._attachments.pop(attachment.attachment_id, None)
                self._settle_attachments((attachment,), members)

    @staticmethod
    def _settle_attachments(
        attachments: tuple[_Attachment, ...],
        members: tuple[_Member, ...],
    ) -> None:
        for attachment in attachments:
            for member in members:
                member.session.remove_attachment(attachment)
            attachment.settle()

    @staticmethod
    async def _complete_cleanup(operation: Awaitable[None]) -> None:
        task: asyncio.Future[None] = asyncio.ensure_future(operation)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done():
                with suppress(BaseException):
                    await asyncio.shield(task)
            raise

    async def _close_sessions(self, sessions: tuple[_SessionOwner, ...]) -> None:
        if not sessions:
            return
        async with self._state_lock:
            for session in sessions:
                self._sessions.pop(session.identity.session_id, None)
                self._cleanup_debt.add(session)
        results = await asyncio.gather(
            *(
                asyncio.wait_for(
                    session.close(),
                    timeout=self._close_timeout_seconds,
                )
                for session in sessions
            ),
            return_exceptions=True,
        )
        completed = tuple(
            session
            for session, result in zip(sessions, results, strict=True)
            if not isinstance(result, BaseException)
        )
        if completed:
            async with self._state_lock:
                self._cleanup_debt.difference_update(completed)
        if any(isinstance(result, BaseException) for result in results):
            raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE)

    def _identity_matches(
        self,
        request: MuxMemberOpenV1,
        identity: SessionIdentityV1,
    ) -> bool:
        spec = request.session
        return (
            identity.product_id == spec.product_id == self.product_id
            and identity.continuity_id == spec.continuity_id
            and identity.scope is spec.scope
            and identity.scope_fingerprint == spec.scope_fingerprint
            and (spec.session_id is None or identity.session_id == spec.session_id)
        )

    def _new_id(self) -> str:
        try:
            value = self._id_factory()
        except BaseException:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
        if not isinstance(value, str) or not value:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return value

    def _require_open(self) -> None:
        if self._closed:
            raise _error(AppErrorCodeV1.SERVICE_CLOSED)

    @staticmethod
    def _require_request(request: object, expected: type[object]) -> None:
        if type(request) is not expected:
            raise _error(AppErrorCodeV1.INVALID_REQUEST)

    @staticmethod
    def _require_mux_open(mux: _MuxOwner) -> None:
        if mux.closed:
            raise _error(AppErrorCodeV1.NOT_FOUND)


__all__ = ["AppServiceV1"]
