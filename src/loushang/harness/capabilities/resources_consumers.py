"""Focused Consumers for the private facets of ``harness.resources``."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, TypeVar, cast

from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.packs import (
    CapabilityPack,
    CapabilityPackComposition,
)
from loushang.harness.capabilities.prompt import PreparedPrompt, PromptSection
from loushang.harness.capabilities.resources_contracts import (
    COMMAND_PACKS_FACET,
    PROMPT_SECTIONS_FACET,
    RESOURCE_CATALOG_FACET,
    RESOURCE_LOAD_FACET,
    RESOURCE_RUNTIME_FACET,
    RESOURCES_ACTIVATION_REQUIREMENT,
    RESOURCES_CATALOG_LOAD_REQUIREMENT,
    RESOURCES_COMMAND_PACK_REQUIREMENT,
    RESOURCES_PROMPT_REQUIREMENT,
    RESOURCES_TOOL_PACK_REQUIREMENT,
    SKILL_ACTIVATION_FACET,
    TOOL_PACKS_FACET,
)
from loushang.harness.resources._catalog_records import (
    LoadedResource,
    ResourceCatalogSnapshot,
    ResourceIdentity,
    ResourceLoadHandle,
)
from loushang.harness.resources.activation import ResourceActivation
from loushang.harness.resources.types import ResourceBundle

T = TypeVar("T")


class _ResourceRuntimeFacet(Protocol):
    def activate(self, bundle: ResourceBundle | None) -> ResourceActivation: ...


class _SkillActivationFacet(Protocol):
    def apply(
        self,
        bundle: ResourceBundle,
        disabled_skills: tuple[str, ...] | list[str],
    ) -> ResourceBundle: ...


class _PackFacet(Protocol):
    def compose(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]: ...


class _PromptFacet(Protocol):
    def compose(self, sections: Iterable[PromptSection]) -> PreparedPrompt: ...


class _ResourceCatalogFacet(Protocol):
    @property
    def snapshot(self) -> ResourceCatalogSnapshot: ...


class _ResourceLoadFacet(Protocol):
    def load_handle(self, identity: ResourceIdentity) -> ResourceLoadHandle: ...

    async def load(self, handle: ResourceLoadHandle) -> LoadedResource: ...


@dataclass(frozen=True)
class ResourceActivationCapabilityConsumer:
    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != RESOURCES_ACTIVATION_REQUIREMENT:
            raise ValueError(
                "resource activation Consumer received the wrong facet view"
            )

    def apply_skill_activation(
        self,
        bundle: ResourceBundle,
        disabled_skills: tuple[str, ...] | list[str],
    ) -> ResourceBundle:
        return cast(
            _SkillActivationFacet,
            self.facets.require(SKILL_ACTIVATION_FACET),
        ).apply(bundle, disabled_skills)

    def activate(self, bundle: ResourceBundle | None) -> ResourceActivation:
        return cast(
            _ResourceRuntimeFacet,
            self.facets.require(RESOURCE_RUNTIME_FACET),
        ).activate(bundle)


@dataclass(frozen=True)
class ResourcePromptCapabilityConsumer:
    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != RESOURCES_PROMPT_REQUIREMENT:
            raise ValueError("resource prompt Consumer received the wrong facet view")

    def compose(self, sections: Iterable[PromptSection]) -> PreparedPrompt:
        return cast(
            _PromptFacet,
            self.facets.require(PROMPT_SECTIONS_FACET),
        ).compose(sections)


@dataclass(frozen=True)
class ResourceToolPackCapabilityConsumer:
    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != RESOURCES_TOOL_PACK_REQUIREMENT:
            raise ValueError(
                "resource Tool-pack Consumer received the wrong facet view"
            )

    def compose(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]:
        return cast(_PackFacet, self.facets.require(TOOL_PACKS_FACET)).compose(packs)


@dataclass(frozen=True)
class ResourceCommandPackCapabilityConsumer:
    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != RESOURCES_COMMAND_PACK_REQUIREMENT:
            raise ValueError(
                "resource Command-pack Consumer received the wrong facet view"
            )

    def compose(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]:
        return cast(_PackFacet, self.facets.require(COMMAND_PACKS_FACET)).compose(packs)


@dataclass(frozen=True)
class ResourceCatalogCapabilityConsumer:
    """Exact-generation Catalog/load view for internal Resource consumers."""

    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != RESOURCES_CATALOG_LOAD_REQUIREMENT:
            raise ValueError("Resource Catalog Consumer received the wrong facet view")

    @property
    def snapshot(self) -> ResourceCatalogSnapshot:
        return cast(
            _ResourceCatalogFacet,
            self.facets.require(RESOURCE_CATALOG_FACET),
        ).snapshot

    def load_handle(self, identity: ResourceIdentity) -> ResourceLoadHandle:
        return cast(
            _ResourceLoadFacet,
            self.facets.require(RESOURCE_LOAD_FACET),
        ).load_handle(identity)

    async def load(self, handle: ResourceLoadHandle) -> LoadedResource:
        return await cast(
            _ResourceLoadFacet,
            self.facets.require(RESOURCE_LOAD_FACET),
        ).load(handle)


__all__ = [
    "ResourceActivationCapabilityConsumer",
    "ResourceCatalogCapabilityConsumer",
    "ResourceCommandPackCapabilityConsumer",
    "ResourcePromptCapabilityConsumer",
    "ResourceToolPackCapabilityConsumer",
]
