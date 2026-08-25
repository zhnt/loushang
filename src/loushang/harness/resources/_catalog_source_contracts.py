"""Source-neutral request boundary shared by Resource source components."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol, runtime_checkable

from loushang.harness.resources._catalog_records import (
    ResourceBodyRead,
    ResourceLoadHandle,
    ResourceSourceGenerationRef,
    ResourceSourceSnapshot,
)


@runtime_checkable
class ResourceDiscoveryRequest(Protocol):
    """Minimum immutable identity common to every synchronous discovery call."""

    @property
    def product_id(self) -> str: ...

    @property
    def source_generation_ref(self) -> ResourceSourceGenerationRef: ...

    @property
    def request_fingerprint(self) -> str: ...


@runtime_checkable
class BorrowedResourceSourceGeneration(Protocol):
    """Owner-retained snapshot/body reader borrowed by the Resource generation.

    Extension hook output uses this seam because it is owned by the exact
    Extension generation rather than mounted as a Resource source component.
    The borrower must never dispose it independently.
    """

    @property
    def source_generation_ref(self) -> ResourceSourceGenerationRef: ...

    @property
    def source_snapshot(self) -> ResourceSourceSnapshot: ...

    def load(
        self,
        handle: ResourceLoadHandle,
    ) -> ResourceBodyRead | Awaitable[ResourceBodyRead]: ...


__all__ = ["BorrowedResourceSourceGeneration", "ResourceDiscoveryRequest"]
