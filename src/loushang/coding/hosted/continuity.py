"""Coding-owned current-generation composition for G13 hosted continuity."""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import cast

from loushang.apphost import (
    AppHostCatalogInputV1,
    AppHostRuntimeV1,
    SessionIdentityCatalogPortV1,
)
from loushang.apphost.application import HostedApplicationRequestV1
from loushang.apphost.continuity import (
    HostedApplicationContinuityActivationV1,
)
from loushang.apphost.integrations._continuity_preparation import (
    _ProductContinuityAttempt,
)
from loushang.appservice import (
    ApplicationContinuityStoreV1,
)
from loushang.coding.hosted.application import (
    CodingForegroundHostedApplicationRequestV1,
    CodingForegroundProductFactoryV1,
    _coding_hosted_catalog_input,
    _coding_hosted_request_for_runtime,
    _load_coding_hosted_sessions,
)

_STABLE_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,511})\Z")


@dataclass(frozen=True, slots=True)
class CodingHostedContinuityRequestV1:
    """Exact G13 opt-in layered over the unchanged G12 Coding request."""

    activation: HostedApplicationContinuityActivationV1
    foreground: CodingForegroundHostedApplicationRequestV1
    application_id: str
    owner_epoch: str
    store: ApplicationContinuityStoreV1 = field(repr=False)
    phase_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if type(self.activation) is not HostedApplicationContinuityActivationV1:
            raise TypeError("Coding hosted continuity requires explicit activation")
        if type(self.foreground) is not CodingForegroundHostedApplicationRequestV1:
            raise TypeError("invalid Coding foreground application request")
        if _STABLE_ID.fullmatch(self.application_id) is None:
            raise ValueError("invalid Coding hosted continuity application identity")
        if (
            self.foreground.managed_mux is not None
            and self.foreground.managed_mux.application_id != self.application_id
        ):
            raise ValueError("managed Mux application identity mismatch")
        if _OPAQUE_TOKEN.fullmatch(self.owner_epoch) is None:
            raise ValueError("invalid Coding hosted continuity owner epoch")
        for name in ("acquire", "list_applications"):
            if not inspect.iscoroutinefunction(
                inspect.getattr_static(type(self.store), name, None)
            ):
                raise TypeError("invalid Coding hosted continuity store")
        if (
            isinstance(self.phase_timeout_seconds, bool)
            or not isinstance(self.phase_timeout_seconds, (int, float))
            or not 0 < self.phase_timeout_seconds <= 60
        ):
            raise ValueError("invalid Coding hosted continuity timeout")


class CodingHostedContinuityAttemptV1(
    _ProductContinuityAttempt[CodingForegroundHostedApplicationRequestV1]
):
    """Published owner before Coding catalog admission or continuity acquisition."""

    __slots__ = (
        "_catalog",
        "_close_lock",
        "_close_task",
        "_closed",
        "_continuity",
        "_continuity_runtime",
        "_lease",
        "_open_lock",
        "_open_task",
        "_product_factory",
        "_request",
        "_runtime",
        "_settled",
        "_transferred",
    )
    _attempt_closed_error = "coding_hosted_continuity_attempt_closed"
    _prefix_cleanup_error = "coding_hosted_continuity_cleanup_incomplete"
    _construction_cleanup_error = "coding_foreground_cleanup_incomplete"

    def __init__(self, request: CodingHostedContinuityRequestV1) -> None:
        if type(request) is not CodingHostedContinuityRequestV1:
            raise TypeError("invalid Coding hosted continuity request")
        self._request: CodingHostedContinuityRequestV1 = request
        self._product_factory: CodingForegroundProductFactoryV1 = (
            CodingForegroundProductFactoryV1(
                request.foreground.session_factory,
                session_owner=request.foreground.session_owner,
            )
        )
        self._initialize_product_continuity_state()

    async def _load_foreground_request(
        self,
    ) -> CodingForegroundHostedApplicationRequestV1:
        request = self._request.foreground
        await _load_coding_hosted_sessions(request)
        return request

    def _foreground_sessions(
        self, request: CodingForegroundHostedApplicationRequestV1
    ) -> SessionIdentityCatalogPortV1:
        return request.sessions

    def _catalog_input(
        self, request: CodingForegroundHostedApplicationRequestV1
    ) -> AppHostCatalogInputV1:
        return _coding_hosted_catalog_input(request, self._product_factory)

    def _application_request(
        self, request: CodingForegroundHostedApplicationRequestV1
    ) -> HostedApplicationRequestV1:
        return _coding_hosted_request_for_runtime(
            request,
            product_factory=self._product_factory,
            runtime=cast(AppHostRuntimeV1, self._runtime),
        )


def create_coding_hosted_continuity_attempt(
    request: CodingHostedContinuityRequestV1,
) -> CodingHostedContinuityAttemptV1:
    """Publish the Coding G13 owner before the first admission effect."""

    return CodingHostedContinuityAttemptV1(request)


__all__ = [
    "CodingHostedContinuityAttemptV1",
    "CodingHostedContinuityRequestV1",
    "create_coding_hosted_continuity_attempt",
]
