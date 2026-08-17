from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from loushang.ai.auth.credentials import OAuthCredential

AuthorizationCallback = Callable[[str], Awaitable[str]]


@runtime_checkable
class OAuthProvider(Protocol):
    id: str

    async def login(
        self,
        *,
        authorize: AuthorizationCallback | None = None,
    ) -> OAuthCredential: ...

    async def refresh(self, credential: OAuthCredential) -> OAuthCredential: ...

    async def revoke(self, credential: OAuthCredential) -> None: ...


__all__ = ["AuthorizationCallback", "OAuthProvider"]
