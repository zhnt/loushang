"""Provider-side ports for continuity discovery and activation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from loushang.harness.continuity.types import (
    ActivationDisposition,
    ContinuityPreview,
    ContinuityProviderDescriptor,
    ContinuityTarget,
    ProviderPage,
    ProviderQuery,
)


@runtime_checkable
class PreparedActivationLease(Protocol):
    """An unpublished, single-use Product activation candidate."""

    @property
    def target(self) -> ContinuityTarget: ...

    @property
    def disposition(self) -> ActivationDisposition: ...

    @property
    def consumed(self) -> bool: ...

    async def consume(self) -> object: ...

    async def abort(self) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class ContinuityProvider(Protocol):
    """A Product/OEM adapter over one or more Domain continuity units."""

    @property
    def descriptor(self) -> ContinuityProviderDescriptor: ...

    async def query(self, request: ProviderQuery) -> ProviderPage: ...

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview: ...

    async def prepare(self, target: ContinuityTarget) -> PreparedActivationLease: ...


@runtime_checkable
class ContinuityDeletionProvider(Protocol):
    """Optional Product-owned deletion operation for a continuity target."""

    async def delete(self, target: ContinuityTarget) -> bool: ...


__all__ = [
    "ContinuityDeletionProvider",
    "ContinuityProvider",
    "PreparedActivationLease",
]
