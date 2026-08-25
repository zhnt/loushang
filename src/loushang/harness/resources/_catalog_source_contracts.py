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
class BorrowedResourceSourceGenerationLease(Protocol):
    """Owner-retained snapshot/body-reader lease held by a Resource generation.

    Extension hook output uses this seam because it is owned by the exact
    Extension generation rather than mounted as a Resource source component.
    The borrower releases this lease but never disposes the owner generation.
    """

    @property
    def source_generation_ref(self) -> ResourceSourceGenerationRef: ...

    @property
    def source_snapshot(self) -> ResourceSourceSnapshot: ...

    def load(
        self,
        handle: ResourceLoadHandle,
    ) -> ResourceBodyRead | Awaitable[ResourceBodyRead]: ...

    @property
    def is_released(self) -> bool: ...

    @property
    def ownership_state(self) -> str: ...

    def claim(self) -> None: ...

    def release(self) -> None: ...


__all__ = ["BorrowedResourceSourceGenerationLease", "ResourceDiscoveryRequest"]
