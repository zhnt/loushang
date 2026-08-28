"""Portable Continuity import contracts at the Product-owned boundary.

This module deliberately stops at the Continuity owner boundary. It does not
mint Runtime Profile grants, evaluate extension factories, or read extension
lifecycle state. A later Plugin-authoring bridge must arrive here with an
owner-admitted, host-constructed Provider.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from loushang.harness.continuity.provider import PreparedActivationLease
from loushang.harness.continuity.types import (
    ContinuityPreview,
    ContinuityProviderDescriptor,
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
    ProviderPage,
    ProviderQuery,
)

CONTINUITY_JSONL_MEDIA_TYPE = "application/vnd.loushang.conversation+jsonl"
CONTINUITY_BUNDLE_MEDIA_TYPE = "application/vnd.loushang.session-bundle+zip"
MAX_CONTINUITY_ACTIVATION_BYTES = 64 * 1024 * 1024
MAX_CONTINUITY_IMPORT_PROVIDERS = 32
MAX_CONTINUITY_CWD_OVERRIDE_LENGTH = 4096

_ACTIVATION_MEDIA_TYPES = frozenset(
    {CONTINUITY_JSONL_MEDIA_TYPE, CONTINUITY_BUNDLE_MEDIA_TYPE}
)


@dataclass(frozen=True, slots=True)
class ContinuityActivationPayload:
    """Bounded portable bytes prepared outside the canonical Session store."""

    media_type: str
    data: bytes = field(repr=False)
    digest: str
    cwd_override: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported continuity activation payload version")
        if self.media_type not in _ACTIVATION_MEDIA_TYPES:
            raise ValueError("unsupported continuity activation media type")
        if type(self.data) is not bytes or not self.data:
            raise ValueError(
                "continuity activation data must be non-empty built-in bytes"
            )
        if len(self.data) > MAX_CONTINUITY_ACTIVATION_BYTES:
            raise ValueError("continuity activation payload exceeds the hard limit")
        if (
            not isinstance(self.digest, str)
            or len(self.digest) != 64
            or any(character not in "0123456789abcdef" for character in self.digest)
        ):
            raise ValueError("continuity activation digest must be SHA-256 hex")
        actual = hashlib.sha256(self.data).hexdigest()
        if not hmac.compare_digest(actual, self.digest):
            raise ValueError("continuity activation digest does not match its bytes")
        if self.cwd_override is not None and (
            not isinstance(self.cwd_override, str)
            or not self.cwd_override.strip()
            or "\x00" in self.cwd_override
            or len(self.cwd_override) > MAX_CONTINUITY_CWD_OVERRIDE_LENGTH
        ):
            raise ValueError("continuity activation cwd override is invalid")

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        media_type: str,
        cwd_override: str | None = None,
    ) -> ContinuityActivationPayload:
        if type(data) is not bytes:
            raise TypeError("continuity activation data must be built-in bytes")
        return cls(
            media_type=media_type,
            data=data,
            digest=hashlib.sha256(data).hexdigest(),
            cwd_override=cwd_override,
        )

    @property
    def byte_size(self) -> int:
        return len(self.data)

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "mediaType": self.media_type,
            "byteSize": self.byte_size,
            "digest": self.digest,
            "cwdOverride": self.cwd_override,
        }


@runtime_checkable
class PreparedContinuityImport(Protocol):
    """Source-owned, unpublished portable activation candidate."""

    @property
    def target(self) -> ContinuityTarget: ...

    @property
    def payload(self) -> ContinuityActivationPayload: ...

    async def abort(self) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class ContinuityImportProvider(Protocol):
    """Read-only import Provider contract; mutation is deliberately absent."""

    @property
    def descriptor(self) -> ContinuityProviderDescriptor: ...

    async def query(self, request: ProviderQuery) -> ProviderPage: ...

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview: ...

    async def prepare_import(
        self,
        target: ContinuityTarget,
    ) -> PreparedContinuityImport: ...


@dataclass(frozen=True, slots=True)
class ContinuityImportProviderPack:
    """Bounded owner input; construction and authority are owned elsewhere."""

    providers: tuple[ContinuityImportProvider, ...]

    def __post_init__(self) -> None:
        providers = tuple(self.providers)
        if not providers:
            raise ValueError("continuity import Provider pack must not be empty")
        if len(providers) > MAX_CONTINUITY_IMPORT_PROVIDERS:
            raise ValueError("continuity import Provider pack exceeds its limit")
        if any(not isinstance(item, ContinuityImportProvider) for item in providers):
            raise TypeError("continuity import pack contains an invalid Provider")
        object.__setattr__(self, "providers", providers)


@runtime_checkable
class ContinuityActivationBridge(Protocol):
    """Product-owned bridge from portable bytes to canonical Session lifecycle."""

    async def prepare(
        self,
        target: ContinuityTarget,
        payload: ContinuityActivationPayload,
        source: ContinuityProviderSourceDescriptor,
    ) -> PreparedActivationLease: ...


__all__ = [
    "CONTINUITY_BUNDLE_MEDIA_TYPE",
    "CONTINUITY_JSONL_MEDIA_TYPE",
    "ContinuityActivationBridge",
    "ContinuityActivationPayload",
    "ContinuityImportProvider",
    "ContinuityImportProviderPack",
    "PreparedContinuityImport",
]
