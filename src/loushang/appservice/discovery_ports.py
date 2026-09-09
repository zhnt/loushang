"""Optional Product discovery observations, not routing or filesystem authority."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from loushang.appserver.protocol import (
    MAX_DISCOVERY_CANDIDATES,
    MAX_DISCOVERY_PAGE,
    SessionDiscoveryCandidateV1,
    SessionListResultV1,
    SessionListV1,
    SessionScopeV1,
)


@dataclass(frozen=True, slots=True)
class HostedSessionDiscoveryScopeV1:
    product_id: str
    scope: SessionScopeV1
    scope_fingerprint: str

    def __post_init__(self) -> None:
        SessionListV1(self.product_id, self.scope, self.scope_fingerprint)


@dataclass(frozen=True, slots=True)
class HostedSessionDiscoverySnapshotV1:
    scope: HostedSessionDiscoveryScopeV1
    candidates: tuple[SessionDiscoveryCandidateV1, ...]
    complete: bool
    omitted_count: int = 0
    omitted_count_exact: bool = True

    def __post_init__(self) -> None:
        if type(self.scope) is not HostedSessionDiscoveryScopeV1:
            raise TypeError("invalid discovery scope")
        if type(self.candidates) is not tuple or len(self.candidates) > MAX_DISCOVERY_CANDIDATES:
            raise ValueError("invalid discovery snapshot bound")
        # Share the wire algebra's exact scope/availability/completeness checks.
        for offset in range(0, max(1, len(self.candidates)), MAX_DISCOVERY_PAGE):
            SessionListResultV1(
                self.scope.product_id, self.scope.scope, self.scope.scope_fingerprint,
                "validation", self.candidates[offset:offset + MAX_DISCOVERY_PAGE],
                self.complete, omitted_count=self.omitted_count,
                omitted_count_exact=self.omitted_count_exact,
            )
        if len({item.identity for item in self.candidates}) != len(self.candidates):
            raise ValueError("ambiguous discovery identities")


class HostedSessionDiscoveryPortV1(Protocol):
    async def discover_sessions(
        self, scope: HostedSessionDiscoveryScopeV1, *, stop: Callable[[], bool]
    ) -> HostedSessionDiscoverySnapshotV1:
        """Complete only after actual read work ends; cooperate with stop/deadline."""
        ...


def require_admitted_scopes(
    scopes: tuple[HostedSessionDiscoveryScopeV1, ...] | None, product_id: str,
) -> None:
    if scopes is not None and (
        type(scopes) is not tuple or not 1 <= len(scopes) <= 2
        or any(type(scope) is not HostedSessionDiscoveryScopeV1 for scope in scopes)
        or len({scope.scope for scope in scopes}) != len(scopes)
        or any(scope.product_id != product_id for scope in scopes)
    ):
        raise ValueError("invalid admitted Session scopes")


@dataclass(frozen=True, slots=True)
class HostedSessionDiscoveryBindingV1:
    generation_id: str
    scopes: tuple[HostedSessionDiscoveryScopeV1, ...]
    port: HostedSessionDiscoveryPortV1 = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.scopes) is not tuple or not 1 <= len(self.scopes) <= 2
            or any(type(scope) is not HostedSessionDiscoveryScopeV1 for scope in self.scopes)
            or len({scope.scope for scope in self.scopes}) != len(self.scopes)
            or len({scope.product_id for scope in self.scopes}) != 1
        ):
            raise ValueError("invalid admitted discovery scopes")
        scope = self.scopes[0]
        SessionListResultV1(scope.product_id, scope.scope, scope.scope_fingerprint,
                            self.generation_id, (), True)
        if not inspect.iscoroutinefunction(getattr(self.port, "discover_sessions", None)):
            raise TypeError("invalid Product discovery port")


def require_discovery_context(
    binding: HostedSessionDiscoveryBindingV1 | None, product_id: str,
    generation_id: str | None = None,
) -> None:
    if binding is not None and (
        type(binding) is not HostedSessionDiscoveryBindingV1
        or any(scope.product_id != product_id for scope in binding.scopes)
        or (generation_id is not None and binding.generation_id != generation_id)
    ):
        raise ValueError("invalid Product discovery binding")
