"""Optional A0.4 binder from AppHost attachments to AppServer-owned ports."""

from __future__ import annotations

import asyncio
from typing import Generic, Protocol, TypeVar, cast, runtime_checkable

from loushang.appserver.ports import (
    AppServerProductPortsV1,
    AppServerSessionIdentityV1,
)

from .contracts import (
    AppHostSessionLeaseV1,
    ProductDescriptorV1,
    SessionBindingKeyV1,
    SessionCandidateRefV1,
    SessionCreateRequestV1,
)
from .errors import AppHostError, AppHostFailureCategory, CleanupIncompleteError
from .runtime import AppHostRuntimeV1

SessionPortT = TypeVar("SessionPortT")
WorkPortT = TypeVar("WorkPortT")
ProjectionPortT = TypeVar("ProjectionPortT")
InteractionPortT = TypeVar("InteractionPortT")


@runtime_checkable
class HostedProductSessionV1(
    Protocol,
    Generic[SessionPortT, WorkPortT, ProjectionPortT, InteractionPortT],
):
    """One owned hosted attachment; its structural ports are non-owning."""

    @property
    def descriptor(self) -> ProductDescriptorV1: ...

    @property
    def generation_id(self) -> str: ...

    @property
    def binding_key(self) -> SessionBindingKeyV1: ...

    @property
    def ports(
        self,
    ) -> AppServerProductPortsV1[
        SessionPortT,
        WorkPortT,
        ProjectionPortT,
        InteractionPortT,
    ]: ...

    async def close(self) -> None: ...


class _HostedProductSession(
    Generic[SessionPortT, WorkPortT, ProjectionPortT, InteractionPortT]
):
    __slots__ = ("_attachment", "_ports")

    def __init__(
        self,
        attachment: AppHostSessionLeaseV1,
        ports: AppServerProductPortsV1[
            SessionPortT,
            WorkPortT,
            ProjectionPortT,
            InteractionPortT,
        ],
    ) -> None:
        self._attachment = attachment
        self._ports = ports

    @property
    def descriptor(self) -> ProductDescriptorV1:
        return self._attachment.descriptor

    @property
    def generation_id(self) -> str:
        return self._attachment.generation_id

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._attachment.binding_key

    @property
    def ports(
        self,
    ) -> AppServerProductPortsV1[
        SessionPortT,
        WorkPortT,
        ProjectionPortT,
        InteractionPortT,
    ]:
        return self._ports

    async def close(self) -> None:
        await self._attachment.close()


class AppHostHostedBinderV1(
    Generic[SessionPortT, WorkPortT, ProjectionPortT, InteractionPortT]
):
    """Borrow an AppHost runtime and elect one explicit hosted profile.

    The binder validates only wiring identity.  It never invokes Product ports,
    parses an App protocol, constructs AppService, or owns transport state.
    """

    __slots__ = ("_profile_id", "_runtime")

    def __init__(self, runtime: AppHostRuntimeV1, *, profile_id: str) -> None:
        if not isinstance(runtime, AppHostRuntimeV1):
            raise TypeError("runtime must be AppHostRuntimeV1")
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("profile_id must be non-empty")
        self._runtime = runtime
        self._profile_id = profile_id

    async def attach_resume(
        self,
        *,
        product_id: str,
        reference: SessionCandidateRefV1,
    ) -> HostedProductSessionV1[
        SessionPortT,
        WorkPortT,
        ProjectionPortT,
        InteractionPortT,
    ]:
        operation = asyncio.create_task(
            self._runtime.attach_resume(
                product_id=product_id,
                reference=reference,
                profile_id=self._profile_id,
            )
        )
        return await self._join(operation)

    async def attach_create(
        self,
        request: SessionCreateRequestV1,
    ) -> HostedProductSessionV1[
        SessionPortT,
        WorkPortT,
        ProjectionPortT,
        InteractionPortT,
    ]:
        operation = asyncio.create_task(
            self._runtime.attach_create(request, profile_id=self._profile_id)
        )
        return await self._join(operation)

    async def _join(
        self,
        operation: asyncio.Task[AppHostSessionLeaseV1],
    ) -> HostedProductSessionV1[
        SessionPortT,
        WorkPortT,
        ProjectionPortT,
        InteractionPortT,
    ]:
        try:
            attachment = await asyncio.shield(operation)
        except asyncio.CancelledError:
            try:
                attachment = await asyncio.shield(operation)
            except CleanupIncompleteError:
                raise
            except BaseException:
                raise asyncio.CancelledError from None
            try:
                await attachment.close()
            except CleanupIncompleteError:
                raise
            except BaseException:
                raise CleanupIncompleteError() from None
            raise
        binding = attachment.profile_binding
        if type(binding) is not AppServerProductPortsV1:
            await _reject_attachment(attachment)
        ports = cast(
            AppServerProductPortsV1[
                SessionPortT,
                WorkPortT,
                ProjectionPortT,
                InteractionPortT,
            ],
            binding,
        )
        expected = AppServerSessionIdentityV1(
            product_id=attachment.binding_key.product_id,
            continuity_id=attachment.binding_key.continuity_id,
            session_id=attachment.binding_key.session_id,
        )
        if ports.identity != expected:
            await _reject_attachment(attachment)
        return _HostedProductSession(attachment, ports)


async def _reject_attachment(attachment: AppHostSessionLeaseV1) -> None:
    try:
        await attachment.close()
    except BaseException:
        raise CleanupIncompleteError() from None
    raise AppHostError(AppHostFailureCategory.PROFILE_UNAVAILABLE)


__all__ = ["AppHostHostedBinderV1", "HostedProductSessionV1"]
