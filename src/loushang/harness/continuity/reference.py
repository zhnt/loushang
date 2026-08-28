"""Typed stable observation reference for one process-owned ContinuityHub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loushang.harness.continuity.provider import PreparedActivationLease
from loushang.harness.continuity.types import (
    ContinuityPage,
    ContinuityPreview,
    ContinuityProviderDescriptor,
    ContinuityProviderSourceDescriptor,
    ContinuityQuery,
    ContinuityTarget,
    ExperienceDescriptor,
)

if TYPE_CHECKING:
    from loushang.harness.continuity.hub import ContinuityHub


class StaleContinuityReferenceError(RuntimeError):
    """Raised when a continuity reference outlives its process authority."""


@dataclass(frozen=True)
class ContinuityObservationDescriptor:
    """Issuance-time metadata snapshot; identity only, no liveness."""

    experience: ExperienceDescriptor
    providers: tuple[ContinuityProviderDescriptor, ...]
    provider_sources: tuple[ContinuityProviderSourceDescriptor, ...] = ()

    def __post_init__(self) -> None:
        if self.provider_sources and len(self.provider_sources) != len(self.providers):
            raise ValueError(
                "continuity observation Provider sources must align with Providers"
            )
        if self.provider_sources and any(
            source.provider_id != provider.provider_id
            for provider, source in zip(
                self.providers,
                self.provider_sources,
                strict=True,
            )
        ):
            raise ValueError(
                "continuity observation Provider source identity does not match"
            )


class StableContinuityReference:
    """Typed observation port issued by one process-owned ContinuityHub.

    Every verb revalidates authority liveness before delegating; after the
    authority begins closing, verbs fail with StaleContinuityReferenceError
    and never reach a provider.  The reference owns nothing and cannot
    dispose the hub, binding, or providers.  Release is idempotent
    bookkeeping and is never a precondition for authority shutdown.
    """

    def __init__(self, hub: ContinuityHub) -> None:
        self._hub = hub
        self._released = False
        self._observation = ContinuityObservationDescriptor(
            experience=hub.composition.experience,
            providers=tuple(
                bound.provider.descriptor
                for bound in hub.composition.continuity_providers
            ),
            provider_sources=tuple(
                bound.source for bound in hub.composition.continuity_providers
            ),
        )

    @property
    def observation(self) -> ContinuityObservationDescriptor:
        """Frozen issuance-time metadata; readable after authority close."""

        return self._observation

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        """Idempotently declare this reference done."""

        self._released = True

    def _admit(self) -> None:
        """Synchronously check liveness and register one in-flight verb.

        The check and the registration happen with no intervening ``await``,
        so a verb admitted before close starts is always joined by close and
        a verb arriving after close starts never reaches a provider.
        """

        if self._released or self._hub.closing:
            raise StaleContinuityReferenceError(
                "continuity reference is stale"
            )
        self._hub._admit_reference_operation()

    def _complete(self) -> None:
        self._hub._complete_reference_operation()

    async def query(self, request: ContinuityQuery) -> ContinuityPage:
        self._admit()
        try:
            return await self._hub.query(request)
        finally:
            self._complete()

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        self._admit()
        try:
            return await self._hub.preview(target)
        finally:
            self._complete()

    async def prepare(self, target: ContinuityTarget) -> PreparedActivationLease:
        self._admit()
        try:
            return await self._hub.prepare(target)
        finally:
            self._complete()

    async def delete(self, target: ContinuityTarget) -> bool:
        self._admit()
        try:
            return await self._hub.delete(target)
        finally:
            self._complete()


__all__ = [
    "ContinuityObservationDescriptor",
    "StaleContinuityReferenceError",
    "StableContinuityReference",
]
