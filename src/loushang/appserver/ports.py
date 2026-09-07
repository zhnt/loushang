"""AppServer-owned structural Product port bundle for optional composition."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Generic, TypeVar

APPSERVER_PORT_CONTRACT_VERSION = "loushang.appserver.product-ports/v1"

_STABLE_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,511})\Z")

SessionPortT = TypeVar("SessionPortT")
WorkPortT = TypeVar("WorkPortT")
ProjectionPortT = TypeVar("ProjectionPortT")
InteractionPortT = TypeVar("InteractionPortT")


@dataclass(frozen=True, slots=True)
class AppServerSessionIdentityV1:
    """AppServer's authority-free copy of one hosted Session identity."""

    product_id: str
    continuity_id: str
    session_id: str
    contract_version: str = APPSERVER_PORT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.contract_version) is not str
            or self.contract_version != APPSERVER_PORT_CONTRACT_VERSION
        ):
            raise ValueError("invalid appserver product ports contract")
        if type(self.product_id) is not str or _STABLE_ID.fullmatch(
            self.product_id
        ) is None:
            raise ValueError("invalid appserver product ports contract")
        for value in (self.continuity_id, self.session_id):
            if type(value) is not str or _OPAQUE_TOKEN.fullmatch(value) is None:
                raise ValueError("invalid appserver product ports contract")


@dataclass(frozen=True, slots=True)
class AppServerProductPortsV1(
    Generic[SessionPortT, WorkPortT, ProjectionPortT, InteractionPortT]
):
    """Typed immutable wiring bundle; AppHost never invokes these ports.

    Product/AppHost composition supplies exact types for the four parameters.
    This container deliberately defines no generic command or payload escape
    hatch and owns no lifecycle close operation. G11 AppService owns its exact
    runtime Session input port separately.
    """

    identity: AppServerSessionIdentityV1
    session: SessionPortT = field(repr=False)
    projection: ProjectionPortT = field(repr=False)
    work: WorkPortT | None = field(default=None, repr=False)
    interaction: InteractionPortT | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.identity) is not AppServerSessionIdentityV1:
            raise ValueError("invalid appserver product ports contract")
        if self.session is None or self.projection is None:
            raise ValueError("invalid appserver product ports contract")


__all__ = [
    "APPSERVER_PORT_CONTRACT_VERSION",
    "AppServerProductPortsV1",
    "AppServerSessionIdentityV1",
]
