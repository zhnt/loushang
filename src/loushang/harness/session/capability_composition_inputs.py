"""Immutable plugin graph inputs and exact-owner Consumer generation staging."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal, TypeAlias

from loushang.harness.capabilities.consumer_requirements import (
    ProductCapabilityConsumerRequirementEntry,
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerSnapshot,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProvider,
    ResolvedCapabilityProviderSet,
)
from loushang.harness.resources.plugins.selection import (
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import PublishedPluginPackage

SessionCompositionChange = Literal["no_change", "restart_required"]


@dataclass(frozen=True, slots=True)
class SessionCapabilityComponentRequest:
    """Data/evidence needed for one Component Host activation consumption."""

    resolved: ResolvedCapabilityProvider
    package: PublishedPluginPackage = field(repr=False, compare=False)
    owner_snapshot: CapabilityProviderOwnerSnapshot
    trust_snapshot: PluginSourceTrustSnapshotV1
    activation_decision_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.resolved, ResolvedCapabilityProvider):
            raise TypeError("Component request requires a resolved Provider")
        if not isinstance(self.package, PublishedPluginPackage):
            raise TypeError("Component request requires a published Plugin package")
        if not isinstance(self.owner_snapshot, CapabilityProviderOwnerSnapshot):
            raise TypeError("Component request requires an owner snapshot")
        if not isinstance(self.trust_snapshot, PluginSourceTrustSnapshotV1):
            raise TypeError("Component request requires a trust snapshot")
        _require_hex(
            self.activation_decision_id,
            length=48,
            name="activation decision id",
        )
        spec = self.resolved.binding_spec
        if (
            self.package.manifest.name != spec.plugin_id
            or self.package.content_digest != spec.package_content_digest
            or self.package.dependency_lock.digest != spec.dependency_lock_digest
        ):
            raise ValueError("Component request package does not exact-match Provider")

    @property
    def capability_id(self) -> str:
        return self.resolved.capability_id


@dataclass(frozen=True, slots=True)
class SessionCapabilityCompositionInputs:
    """Pinned external Provider/Consumer facts merged into one Session graph."""

    product_composition: ProductCompositionCompilation
    resolved_providers: ResolvedCapabilityProviderSet
    component_requests: tuple[SessionCapabilityComponentRequest, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.product_composition, ProductCompositionCompilation):
            raise TypeError("Session composition requires Product compilation")
        if not isinstance(self.resolved_providers, ResolvedCapabilityProviderSet):
            raise TypeError("Session composition requires resolved Providers")
        requirements = self.product_composition.consumer_requirements
        if requirements.product_id != self.resolved_providers.product_id:
            raise ValueError("Session composition Product facts do not match")
        admissions = (
            *self.product_composition.resource_admissions,
            *self.product_composition.catalog_admissions,
        )
        if any(item.product_id != requirements.product_id for item in admissions):
            raise ValueError("Session contribution admission belongs to another Product")
        requests = tuple(self.component_requests)
        if any(
            not isinstance(item, SessionCapabilityComponentRequest)
            for item in requests
        ):
            raise TypeError("Session component requests have invalid type")
        if requests != tuple(sorted(requests, key=lambda item: item.capability_id)):
            raise ValueError("Session component requests must be Capability-sorted")
        request_ids = tuple(item.capability_id for item in requests)
        entry_ids = tuple(item.capability_id for item in self.resolved_providers.entries)
        if request_ids != entry_ids:
            raise ValueError("Session component requests must cover resolved Providers")
        if any(
            request.resolved is not entry
            for request, entry in zip(
                requests,
                self.resolved_providers.entries,
                strict=True,
            )
        ):
            raise ValueError("Session component request does not retain exact resolution")
        object.__setattr__(self, "component_requests", requests)

    @property
    def product_id(self) -> str:
        return self.resolved_providers.product_id

    @property
    def composition_fingerprint(self) -> str:
        document = {
            "catalogAdmissions": [
                item.fingerprint
                for item in self.product_composition.catalog_admissions
            ],
            "consumerRequirements": (
                self.product_composition.consumer_requirements.fingerprint
            ),
            "providerClosure": self.resolved_providers.closure_fingerprint,
            "resourceAdmissions": [
                item.fingerprint
                for item in self.product_composition.resource_admissions
            ],
        }
        payload = json.dumps(
            document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(b"loushang.session-capability-composition/v1\0" + payload).hexdigest()

    def compare(self, other: SessionCapabilityCompositionInputs) -> SessionCompositionChange:
        if not isinstance(other, SessionCapabilityCompositionInputs):
            raise TypeError("Session composition comparison requires exact inputs")
        return (
            "no_change"
            if self.composition_fingerprint == other.composition_fingerprint
            else "restart_required"
        )


@dataclass(frozen=True, slots=True)
class SessionCapabilityConsumerCapture:
    """One exact per-contribution Consumer view captured after graph publication."""

    entry: ProductCapabilityConsumerRequirementEntry
    facets: CapabilityFacetSet = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.entry, ProductCapabilityConsumerRequirementEntry):
            raise TypeError("Session Consumer capture requires a requirement entry")
        if not isinstance(self.facets, CapabilityFacetSet):
            raise TypeError("Session Consumer capture requires a facet set")
        if self.facets.requirement != self.entry.requirement:
            raise ValueError("Session Consumer capture does not match its entry")


OwnerGenerationStage: TypeAlias = Callable[
    [tuple[SessionCapabilityConsumerCapture, ...]],
    object | Awaitable[object],
]
OwnerGenerationDispose: TypeAlias = Callable[[object], None | Awaitable[None]]


@dataclass(frozen=True, slots=True)
class SessionCapabilityOwnerGenerationBinding:
    """Exact Tool/Command owner adapter; it receives only declared Consumers."""

    owner_id: str
    contribution_kind: str
    plugin_id: str
    contribution_id: str
    admission_fingerprint: str
    stage: OwnerGenerationStage = field(repr=False, compare=False)
    dispose: OwnerGenerationDispose = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("Consumer owner id", self.owner_id),
            ("Consumer contribution kind", self.contribution_kind),
            ("Consumer Plugin id", self.plugin_id),
            ("Consumer contribution id", self.contribution_id),
        ):
            _require_nonempty(value, name=name)
        _require_hex(
            self.admission_fingerprint,
            length=64,
            name="Consumer admission fingerprint",
        )
        if not callable(self.stage) or not callable(self.dispose):
            raise TypeError("Owner generation stage/dispose must be callable")

    def matches(self, admission: OwnerContributionAdmissionRecord) -> bool:
        return (
            self.owner_id == admission.owner_id
            and self.contribution_kind == admission.contribution_kind
            and self.plugin_id == admission.plugin_id
            and self.contribution_id == admission.contribution_id
            and self.admission_fingerprint == admission.fingerprint
        )


@dataclass(slots=True)
class StagedSessionCapabilityOwnerGeneration:
    binding: SessionCapabilityOwnerGenerationBinding
    value: object = field(repr=False)
    disposed: bool = False

    async def dispose_once(self) -> None:
        if self.disposed:
            return
        result = self.binding.dispose(self.value)
        if inspect.isawaitable(result):
            await result
        self.disposed = True


class SessionCapabilityOwnerGenerationStagingError(RuntimeError):
    """Owner staging failed while some generations still require disposal."""

    def __init__(
        self,
        message: str,
        *,
        pending_generations: tuple[StagedSessionCapabilityOwnerGeneration, ...],
    ) -> None:
        super().__init__(message)
        self.pending_generations = pending_generations


async def stage_session_capability_owner_generations(
    *,
    admissions: tuple[OwnerContributionAdmissionRecord, ...],
    bindings: tuple[SessionCapabilityOwnerGenerationBinding, ...],
    captures: tuple[SessionCapabilityConsumerCapture, ...],
) -> tuple[StagedSessionCapabilityOwnerGeneration, ...]:
    """Stage exact owners transactionally after Consumer capture."""

    admission_values, binding_values = (
        validate_session_capability_owner_generation_bindings(
            admissions=admissions,
            bindings=bindings,
        )
    )

    captures_by_admission: dict[str, list[SessionCapabilityConsumerCapture]] = {}
    for capture in captures:
        captures_by_admission.setdefault(
            capture.entry.admission_fingerprint,
            [],
        ).append(capture)
    if set(captures_by_admission) - {
        item.fingerprint for item in admission_values
    }:
        raise ValueError("Consumer capture belongs to an unknown owner admission")

    staged: list[StagedSessionCapabilityOwnerGeneration] = []
    try:
        for admission, binding in zip(
            admission_values,
            binding_values,
            strict=True,
        ):
            owner_captures = tuple(
                captures_by_admission.get(admission.fingerprint, ())
            )
            result = binding.stage(owner_captures)
            if inspect.isawaitable(result):
                result = await result
            staged.append(
                StagedSessionCapabilityOwnerGeneration(
                    binding=binding,
                    value=result,
                )
            )
    except BaseException as error:
        pending: list[StagedSessionCapabilityOwnerGeneration] = []
        for generation in reversed(staged):
            try:
                await generation.dispose_once()
            except BaseException as cleanup_error:
                pending.append(generation)
                error.add_note(
                    "Owner generation rollback also failed: "
                    f"{cleanup_error!r}"
                )
        if pending:
            raise SessionCapabilityOwnerGenerationStagingError(
                "Owner generation staging failed with pending rollback cleanup.",
                pending_generations=tuple(reversed(pending)),
            ) from error
        raise
    return tuple(staged)


def validate_session_capability_owner_generation_bindings(
    *,
    admissions: tuple[OwnerContributionAdmissionRecord, ...],
    bindings: tuple[SessionCapabilityOwnerGenerationBinding, ...],
) -> tuple[
    tuple[OwnerContributionAdmissionRecord, ...],
    tuple[SessionCapabilityOwnerGenerationBinding, ...],
]:
    admission_values = tuple(sorted(admissions, key=lambda item: item.fingerprint))
    binding_values = tuple(
        sorted(bindings, key=lambda item: item.admission_fingerprint)
    )
    if any(
        not isinstance(item, OwnerContributionAdmissionRecord)
        for item in admission_values
    ):
        raise TypeError("Catalog admissions have invalid type")
    if any(
        not isinstance(item, SessionCapabilityOwnerGenerationBinding)
        for item in binding_values
    ):
        raise TypeError("Owner generation bindings have invalid type")
    if len({item.fingerprint for item in admission_values}) != len(admission_values):
        raise ValueError("Catalog admissions must be unique")
    if len({item.admission_fingerprint for item in binding_values}) != len(
        binding_values
    ):
        raise ValueError("Owner generation bindings must be unique")
    if len(admission_values) != len(binding_values) or any(
        not binding.matches(admission)
        for admission, binding in zip(
            admission_values,
            binding_values,
            strict=True,
        )
    ):
        raise ValueError("Owner generation bindings do not exact-match admissions")
    return admission_values, binding_values


async def dispose_session_capability_owner_generations(
    generations: tuple[StagedSessionCapabilityOwnerGeneration, ...],
) -> None:
    errors: list[BaseException] = []
    for generation in reversed(generations):
        try:
            await generation.dispose_once()
        except BaseException as exc:
            errors.append(exc)
    if errors:
        primary = errors[0]
        for cleanup_error in errors[1:]:
            primary.add_note(
                "Additional owner generation cleanup failure: "
                f"{cleanup_error!r}"
            )
        raise primary


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _require_hex(value: object, *, length: int, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be {length} lowercase hexadecimal characters")


__all__ = [
    "SessionCapabilityComponentRequest",
    "SessionCapabilityCompositionInputs",
    "SessionCapabilityConsumerCapture",
    "SessionCapabilityOwnerGenerationBinding",
    "SessionCapabilityOwnerGenerationStagingError",
    "SessionCompositionChange",
    "StagedSessionCapabilityOwnerGeneration",
    "dispose_session_capability_owner_generations",
    "stage_session_capability_owner_generations",
    "validate_session_capability_owner_generation_bindings",
]
