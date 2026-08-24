"""Source-neutral request boundary shared by Resource source components."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from loushang.harness.resources._catalog_records import (
    ResourceSourceGenerationRef,
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


__all__ = ["ResourceDiscoveryRequest"]
