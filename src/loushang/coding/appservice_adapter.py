"""Coding-owned hosted Session adapter for the G11 AppService boundary."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from loushang.apphost import SessionDiscoveryScope, SessionIdentityEnvelopeV1
from loushang.apphost.integrations.session_control import _SessionServiceAdapter
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionEventKindV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    TranscriptRecordV1,
)
from loushang.appservice import HostedSessionPortV1
from loushang.appservice.resume_ports import (
    ResumeInputLookupQueryV1,
    ResumeInputLookupResultV1,
)
from loushang.harness.events import RuntimeEvent
from loushang.harness.session import (
    SessionControlPort,
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


class CodingHostedSessionV1(
    _SessionServiceAdapter[CodingHostedSnapshotProjectionV1, CodingHostedEventProjectionV1]
):
    """Product identity/projections over the existing Session control bridge."""

    __slots__ = ()
    _product_id = CODING_PRODUCT_ID
    _product_label = "Coding"
    _snapshot_type = CodingHostedSnapshotProjectionV1
    _event_type = CodingHostedEventProjectionV1

    def __init__(self, binding: CodingHostedSessionBindingV1, *,
        execution_submission: bool = False,
    ) -> None:
        super().__init__(binding, execution_submission=execution_submission)

    async def lookup_resume_input(
        self, query: ResumeInputLookupQueryV1,
    ) -> ResumeInputLookupResultV1:
        """Adapt the optional Product observation; scoped service owns reads."""

        from .hosted_session import _lookup_coding_resume_input

        if self._close_task is not None:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        return await _lookup_coding_resume_input(self._binding, query)


    def _observe_projection(
        self, projection: CodingHostedEventProjectionV1, event: SessionEventV1
    ) -> None:
        """Synchronous Product observation before optional delivery listeners."""




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
