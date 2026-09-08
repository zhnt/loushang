"""Product-neutral in-process AppService and named MuxSpace coordination."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from secrets import token_hex
from typing import TYPE_CHECKING, cast

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

from .continuity import (
    ApplicationContinuityError,
    ApplicationContinuityErrorCodeV1,
    ApplicationContinuityLeaseV1,
    ApplicationContinuityRecordV1,
    MuxMemberContinuityV1,
    MuxSpaceContinuityV1,
)
from .discovery_ports import HostedSessionDiscoveryBindingV1
from .ports import (
    HostedSessionPortV1,
    HostedSessionResolutionErrorV1,
    HostedSessionResolutionFailureV1,
    HostedSessionResolverV1,
)
from .session_discovery import SessionDiscoveryOwnerV1, SessionDiscoveryViewV1

if TYPE_CHECKING:
    from .client_scope import ScopedAppServiceV1

_CONTINUITY_TOKEN = object()


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
        "event_handler",
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
        self.event_handler: (
            Callable[[_SessionOwner, SessionEventV1], Awaitable[None]] | None
        ) = None
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

    async def _invoke_async(
        self, callback: Callable[..., object], *args: object
    ) -> object:
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
        if (
            type(event) is not SessionEventV1
            or event.session_id != self.identity.session_id
        ):
            self._invalidate_attachments()
            return
        if event.cursor <= self._latest_cursor:
            return
        if self._latest_cursor and event.cursor != self._latest_cursor + 1:
            self._invalidate_attachments()
        self._latest_cursor = event.cursor
        if self.event_handler is not None:
            await self.event_handler(self, event)
            if event.cursor < self._latest_cursor:
                return
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
        "_client_scopes",
        "_close_timeout_seconds",
        "_closed",
        "_discovery",
        "_continuity_application_id",
        "_continuity_lease",
        "_continuity_owner_epoch",
        "_continuity_revision",
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
        discovery: HostedSessionDiscoveryBindingV1 | None = None,
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
        if discovery is not None and (
            type(discovery) is not HostedSessionDiscoveryBindingV1
            or any(scope.product_id != product_id for scope in discovery.scopes)
        ):
            raise ValueError("invalid Product discovery binding")
        self._discovery = None if discovery is None else SessionDiscoveryOwnerV1(
            discovery, close_timeout=close_timeout_seconds
        )
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
        self._client_scopes: ScopedAppServiceV1 | None = None
        self._continuity_lease: ApplicationContinuityLeaseV1 | None = None
        self._continuity_application_id: str | None = None
        self._continuity_owner_epoch: str | None = None
        self._continuity_revision: int | None = None

    @property
    def continuity_enabled(self) -> bool:
        return self._continuity_lease is not None

    @property
    def discovery_client(self) -> SessionDiscoveryViewV1 | None:
        if self._closed or self._discovery is None:
            return None
        return self._discovery.legacy_client

    @property
    def continuity_revision(self) -> int | None:
        return self._continuity_revision

    def _adopt_continuity_state(
        self,
        *,
        lease: ApplicationContinuityLeaseV1,
        record: ApplicationContinuityRecordV1 | None,
        sessions: dict[str, _SessionOwner],
        _token: object,
    ) -> None:
        if _token is not _CONTINUITY_TOKEN:
            raise TypeError("AppService continuity state requires recovery")
        if (
            self._continuity_lease is not None or self._mux_by_id or self._sessions
            or self._client_scopes is not None
        ):
            raise RuntimeError("AppService continuity state already initialized")
        application_id = lease.application_id
        if record is not None and (
            record.application_id != application_id
            or record.product_id != self.product_id
        ):
            raise ValueError("AppService continuity identity mismatch")
        mux_by_id: dict[str, _MuxOwner] = {}
        mux_by_name: dict[str, _MuxOwner] = {}
        expected_sessions = {
            member.session.session_id
            for mux in (() if record is None else record.mux_spaces)
            for member in mux.members
        }
        if set(sessions) != expected_sessions:
            raise ValueError("AppService recovered Session set mismatch")
        if record is not None:
            for retained in record.mux_spaces:
                mux = _MuxOwner(retained.mux_space_id, retained.name)
                mux.revision = retained.revision
                mux.members.extend(
                    _Member(
                        member.member_id,
                        member.title,
                        sessions[member.session.session_id],
                    )
                    for member in retained.members
                )
                mux_by_id[mux.mux_space_id] = mux
                mux_by_name[mux.name] = mux
        self._continuity_lease = lease
        self._continuity_application_id = application_id
        self._continuity_owner_epoch = lease.owner_epoch
        self._continuity_revision = None if record is None else record.record_revision
        self._mux_by_id = mux_by_id
        self._mux_by_name = mux_by_name
        self._sessions = dict(sessions)

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
            cancellation = await self._commit_continuity(
                self._next_continuity_record(add_mux=mux)
            )
            self._mux_by_id[mux_space_id] = mux
            self._mux_by_name[request.name] = mux
            projection = mux.projection()
        if cancellation is not None:
            raise cancellation
        return projection

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
                    for member, snapshot in zip(
                        projection.members, snapshots, strict=True
                    )
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
                cancellation = await self._commit_continuity(
                    self._next_continuity_record(remove_mux=mux)
                )
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
        if cancellation is not None:
            raise cancellation
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
        except HostedSessionResolutionErrorV1 as error:
            code = (
                AppErrorCodeV1.NOT_FOUND
                if type(error) is HostedSessionResolutionErrorV1
                and error.reason is HostedSessionResolutionFailureV1.MISSING
                else AppErrorCodeV1.SESSION_UNAVAILABLE
            )
            raise _error(code) from None
        except BaseException:
            raise _error(AppErrorCodeV1.SESSION_UNAVAILABLE) from None
        try:
            session = _SessionOwner(port)
            if self._client_scopes is not None:
                session.event_handler = self._client_scopes._interactions.on_event
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
        published = False
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
                    if any(item.member_id == member.member_id for item in mux.members):
                        raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
                    staged_members = (*mux.members, member)
                    cancellation = await self._commit_continuity(
                        self._next_continuity_record(
                            replace_mux=mux,
                            members=staged_members,
                            mux_revision=mux.revision + 1,
                        )
                    )
                    mux.members.append(member)
                    mux.revision += 1
                    attachments = mux.take_attachments()
                    self._sessions[session.identity.session_id] = session
                    for attachment in attachments:
                        self._attachments.pop(attachment.attachment_id, None)
                    self._settle_attachments(attachments, tuple(mux.members))
                    projection = mux.projection()
                    published = True
            if cancellation is not None:
                raise cancellation
            return projection
        except BaseException:
            if not published:
                await self._complete_cleanup(self._close_sessions((session,)))
            raise

    async def close_member(self, request: MuxMemberCloseV1) -> MuxSpaceV1:
        self._require_request(request, MuxMemberCloseV1)
        if self.continuity_enabled and not request.close_session:
            raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        mux = await self._resolve_mux(request.selector)
        async with self._state_lock:
            self._require_open()
            async with mux.lock:
                self._require_mux_open(mux)
                selected = next(
                    (
                        item
                        for item in mux.members
                        if item.member_id == request.member_id
                    ),
                    None,
                )
                if selected is None:
                    raise _error(AppErrorCodeV1.NOT_FOUND)
                prior_members = tuple(mux.members)
                staged_members = tuple(
                    item for item in mux.members if item is not selected
                )
                cancellation = await self._commit_continuity(
                    self._next_continuity_record(
                        replace_mux=mux,
                        members=staged_members,
                        mux_revision=mux.revision + 1,
                    )
                )
                mux.members.remove(selected)
                mux.revision += 1
                attachments = mux.take_attachments()
                for attachment in attachments:
                    self._attachments.pop(attachment.attachment_id, None)
                self._settle_attachments(attachments, prior_members)
                projection = mux.projection()
        if request.close_session:
            await self._close_sessions((selected.session,))
        if cancellation is not None:
            raise cancellation
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
        scope_failure = False
        if self._discovery is not None:
            self._discovery.fence()
        if self._client_scopes is not None:
            try:
                await self._client_scopes.close()
            except AppServiceError:
                scope_failure = True
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
                attachments = tuple(item[1] for item in self._attachments.values())
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
        if self._discovery is not None:
            await self._discovery.close()
        await self._close_sessions(sessions)
        if scope_failure:
            raise _error(AppErrorCodeV1.CLEANUP_INCOMPLETE)

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

    def _next_continuity_record(
        self,
        *,
        add_mux: _MuxOwner | None = None,
        remove_mux: _MuxOwner | None = None,
        replace_mux: _MuxOwner | None = None,
        members: tuple[_Member, ...] | None = None,
        mux_revision: int | None = None,
    ) -> ApplicationContinuityRecordV1 | None:
        if self._continuity_lease is None:
            return None
        retained: list[MuxSpaceContinuityV1] = []
        for mux in self._mux_by_id.values():
            if mux is remove_mux:
                continue
            if mux is replace_mux:
                if members is None or mux_revision is None:
                    raise RuntimeError("incomplete continuity MuxSpace replacement")
                retained.append(
                    self._continuity_mux(
                        mux,
                        members=members,
                        revision=mux_revision,
                    )
                )
            else:
                retained.append(self._continuity_mux(mux))
        if add_mux is not None:
            retained.append(self._continuity_mux(add_mux))
        retained.sort(key=lambda item: (item.name, item.mux_space_id))
        application_id = self._continuity_application_id
        if application_id is None:
            raise RuntimeError("continuity application identity is unavailable")
        revision = (
            1 if self._continuity_revision is None else self._continuity_revision + 1
        )
        return ApplicationContinuityRecordV1(
            application_id=application_id,
            product_id=self.product_id,
            record_revision=revision,
            mux_spaces=tuple(retained),
        )

    @staticmethod
    def _continuity_mux(
        mux: _MuxOwner,
        *,
        members: tuple[_Member, ...] | None = None,
        revision: int | None = None,
    ) -> MuxSpaceContinuityV1:
        retained = tuple(mux.members) if members is None else members
        return MuxSpaceContinuityV1(
            mux_space_id=mux.mux_space_id,
            name=mux.name,
            revision=mux.revision if revision is None else revision,
            members=tuple(
                MuxMemberContinuityV1(
                    member_id=member.member_id,
                    title=member.title,
                    position=position,
                    session=member.session.identity,
                )
                for position, member in enumerate(retained, 1)
            ),
        )

    async def _commit_continuity(
        self,
        record: ApplicationContinuityRecordV1 | None,
    ) -> asyncio.CancelledError | None:
        if record is None:
            return None
        lease = self._continuity_lease
        if lease is None:
            raise RuntimeError("continuity record has no lease")
        task = asyncio.create_task(
            lease.commit(
                expected_revision=self._continuity_revision,
                record=record,
            )
        )
        cancellation = await _join_continuity_commit(task)
        self._continuity_revision = record.record_revision
        return cancellation

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
        owner_epoch = self._continuity_owner_epoch
        if owner_epoch is not None:
            digest = sha256(f"{owner_epoch}\0{value}".encode()).hexdigest()
            return f"g13-{digest}"
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


async def _join_continuity_commit(
    task: asyncio.Task[None],
) -> asyncio.CancelledError | None:
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if caller is None or caller.cancelling() == 0:
                break
            cancellation = error
        except BaseException:
            break
    try:
        task.result()
    except asyncio.CancelledError:
        raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
    except ApplicationContinuityError as error:
        code = (
            AppErrorCodeV1.REVISION_CONFLICT
            if error.code is ApplicationContinuityErrorCodeV1.CONFLICT
            else AppErrorCodeV1.OPERATION_UNAVAILABLE
        )
        raise _error(code) from None
    except BaseException:
        raise _error(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
    return cancellation


__all__ = ["AppServiceV1"]
