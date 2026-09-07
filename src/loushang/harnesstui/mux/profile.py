"""Explicit factory for the process-local G11 Hosted Mux Profile."""

from __future__ import annotations

from loushang.appserver.client import AppClientV1
from loushang.appserver.protocol import MuxSelectorV1

from .controller import HostedMuxControllerV1


async def open_hosted_mux_profile(
    client: AppClientV1,
    *,
    selector: MuxSelectorV1,
    mailbox_capacity: int = 256,
) -> HostedMuxControllerV1:
    """Explicitly construct and attach the hosted profile; never auto-discovered."""

    controller = HostedMuxControllerV1(
        client,
        selector=selector,
        mailbox_capacity=mailbox_capacity,
    )
    await controller.start()
    return controller


__all__ = ["open_hosted_mux_profile"]
