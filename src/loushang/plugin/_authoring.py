"""Stable, data-only authoring facade for Plugin declaration IR v2."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import wraps
from typing import Literal, Protocol, TypeAlias

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityRequirement,
    CapabilityRequirementBinding,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.plugin_authoring.builder import PluginDeclarationBuilder
from loushang.harness.plugin_authoring.capability_provider import (
    PLUGIN_PROVIDER_SELECTION_RULE,
    CapabilityProviderDeclarationPayload,
)
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
    ResourceItemLocatorKind,
)
from loushang.harness.resources.plugins.declarations import PluginDeclaration
from loushang.harness.resources.plugins.locators import parse_plugin_entrypoint
from loushang.harness.resources.plugins.symbol_reference import PluginSymbolReference
from loushang.harness.resources.skill_actions import (
    ManagedSkillActionDeclaration,
    SkillActionCwdPolicy,
    SkillActionEffect,
    SkillActionEffectKind,
    SkillActionRuntime,
)

Contract: TypeAlias = int | tuple[int, int]


class _ContributionSpec(Protocol):
    contribution_id: str

    def _apply(self, builder: PluginDeclarationBuilder) -> PluginDeclaration: ...


@dataclass(frozen=True, slots=True)
class CapabilityProviderSpec:
    """Immutable author intent for one complete Capability provider."""

    contribution_id: str
    capability: str
    provider_id: str
    implementation_version: int
    compatible_contract: CapabilityContractRange
    facets: tuple[str, ...]
    requirements: tuple[CapabilityRequirement, ...]
    authorities: frozenset[str]
    factory: str
    disposer: str | None

    def _apply(self, builder: PluginDeclarationBuilder) -> PluginDeclaration:
        return builder.add_capability_provider(
            contribution_id=self.contribution_id,
            payload=CapabilityProviderDeclarationPayload(
                provider=CapabilityBundleProvider(
                    capability_id=self.capability,
                    provider_id=self.provider_id,
                    implementation_version=self.implementation_version,
                    compatible_contract=self.compatible_contract,
                    facets=self.facets,
                    requirements=self.requirements,
                    required_authorities=self.authorities,
                    source_id=f"plugin:{builder.plugin_id}",
                    selection_rule=PLUGIN_PROVIDER_SELECTION_RULE,
                ),
                factory=_symbol_reference(self.factory),
                disposer=(
                    None if self.disposer is None else _symbol_reference(self.disposer)
                ),
                binding_inputs=builder.effective_configuration(
                    contribution_id=self.contribution_id
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class ResourceItemSpec:
    """Immutable author intent for one Resource Catalog item."""

    contribution_id: str
    locator: str
    locator_kind: ResourceItemLocatorKind
    media_type: str
    owner_namespace: str
    resource_kind: Literal["asset", "method", "prompt", "skill", "source", "theme"]
    schema_id: str
    schema_version: int
    actions: tuple[ManagedSkillActionDeclaration, ...] = ()

    def __post_init__(self) -> None:
        actions = tuple(self.actions)
        if any(not isinstance(item, ManagedSkillActionDeclaration) for item in actions):
            raise TypeError(
                "Resource Skill actions must be managed action declarations"
            )
        identities = tuple(item.action_id for item in actions)
        if identities != tuple(sorted(identities)) or len(identities) != len(
            set(identities)
        ):
            raise ValueError("Resource Skill actions must be sorted and unique")
        if actions and self.resource_kind != "skill":
            raise ValueError("Only Skill Resources may declare managed actions")
        object.__setattr__(self, "actions", actions)

    def _apply(self, builder: PluginDeclarationBuilder) -> PluginDeclaration:
        return builder.add_resource_item(
            contribution_id=self.contribution_id,
            payload=ResourceItemDeclarationPayload(
                locator=self.locator,
                locator_kind=self.locator_kind,
                media_type=self.media_type,
                owner_namespace=self.owner_namespace,
                resource_kind=self.resource_kind,
                schema_id=self.schema_id,
                schema_version=self.schema_version,
            ),
        )


class PluginDefinitionBuilder:
    """Narrow declaration builder; it carries no Host or owner authority."""

    __slots__ = ("__builder", "__contribution_ids")

    def __init__(self, builder: PluginDeclarationBuilder) -> None:
        self.__builder = builder
        self.__contribution_ids: set[str] = set()

    def effective_configuration(
        self,
        *,
        contribution_id: str,
    ) -> Mapping[str, object]:
        """Read the Product-frozen, non-secret contribution configuration."""

        return self.__builder.effective_configuration(contribution_id=contribution_id)

    def add(self, contribution: CapabilityProviderSpec | ResourceItemSpec) -> None:
        """Add one immutable contribution intent to its exact reservation."""

        if not isinstance(contribution, CapabilityProviderSpec | ResourceItemSpec):
            raise TypeError("Plugin Definition accepts a documented contribution spec")
        if contribution.contribution_id in self.__contribution_ids:
            raise ValueError(
                "Plugin Definition repeats contribution: "
                f"{contribution.contribution_id}"
            )
        contribution._apply(self.__builder)
        self.__contribution_ids.add(contribution.contribution_id)

    def _build(self) -> tuple[PluginDeclaration, ...]:
        return self.__builder.build()


PluginDefinitionFunction: TypeAlias = Callable[
    [PluginDefinitionBuilder], object | None
]


def plugin_definition(
    definition: PluginDefinitionFunction,
) -> Callable[[PluginDeclarationBuilder], tuple[PluginDeclaration, ...]]:
    """Compile a public declaration function through the sole internal builder."""

    if not callable(definition):
        raise TypeError("Plugin Definition must be callable")

    @wraps(definition)
    def compiled(
        builder: PluginDeclarationBuilder,
    ) -> tuple[PluginDeclaration, ...]:
        if not isinstance(builder, PluginDeclarationBuilder):
            raise TypeError("Plugin Definition requires a Host-issued builder")
        public_builder = PluginDefinitionBuilder(builder)
        result = definition(public_builder)
        if result is not None:
            raise ValueError("Plugin Definition functions must return None")
        return public_builder._build()

    return compiled


def capability_requirement(
    *,
    capability: str,
    facets: Sequence[str],
    contract: Contract,
    optional: bool = False,
    binding: CapabilityRequirementBinding = "direct",
) -> CapabilityRequirement:
    """Construct the canonical Capability requirement data record."""

    return CapabilityRequirement(
        capability=capability,
        facets=_string_tuple(facets, name="Capability requirement facets"),
        compatible_contract=_contract_range(contract),
        optional=optional,
        binding=binding,
    )


def capability_provider(
    *,
    contribution_id: str,
    capability: str,
    provider_id: str,
    implementation_version: int,
    contract: Contract,
    facets: Sequence[str],
    requirements: Sequence[CapabilityRequirement] = (),
    authorities: Sequence[str] = (),
    factory: str,
    disposer: str | None,
) -> CapabilityProviderSpec:
    """Declare one provider without exposing a registry, Graph, or live context."""

    return CapabilityProviderSpec(
        contribution_id=contribution_id,
        capability=capability,
        provider_id=provider_id,
        implementation_version=implementation_version,
        compatible_contract=_contract_range(contract),
        facets=_string_tuple(facets, name="Capability Provider facets"),
        requirements=_requirement_tuple(requirements),
        authorities=frozenset(
            _string_tuple(authorities, name="Capability Provider authorities")
        ),
        factory=_canonical_symbol_locator(factory),
        disposer=(None if disposer is None else _canonical_symbol_locator(disposer)),
    )


class _ResourceAuthoring:
    __slots__ = ()

    @staticmethod
    def skill(
        *,
        contribution_id: str,
        locator: str,
        owner_namespace: str = "resources.skill",
        media_type: str = "text/markdown",
        schema_id: str = "loushang.resource.skill",
        schema_version: int = 1,
        actions: Sequence[ManagedSkillActionDeclaration] = (),
    ) -> ResourceItemSpec:
        """Declare a ``SKILL.md`` directory as one Catalog Resource item."""

        return ResourceItemSpec(
            contribution_id=contribution_id,
            locator=locator,
            locator_kind="directory",
            media_type=media_type,
            owner_namespace=owner_namespace,
            resource_kind="skill",
            schema_id=schema_id,
            schema_version=schema_version,
            actions=tuple(actions),
        )


resource = _ResourceAuthoring()


def skill_action_effect(
    *,
    kind: SkillActionEffectKind,
    target: str,
) -> SkillActionEffect:
    """Declare one policy-visible effect beyond the implicit process launch."""

    return SkillActionEffect(kind=kind, target=target)


def skill_action(
    *,
    id: str,
    script: str,
    script_digest: str,
    runtime: SkillActionRuntime,
    argv: Sequence[str] = (),
    cwd: SkillActionCwdPolicy = "skill",
    environment: Sequence[tuple[str, str]] = (),
    effects: Sequence[SkillActionEffect] = (),
) -> ManagedSkillActionDeclaration:
    """Declare an exact, contained, approval-gated Skill script action."""

    return ManagedSkillActionDeclaration(
        action_id=id,
        script=script,
        script_digest=script_digest,
        runtime=runtime,
        argv=tuple(argv),
        cwd_policy=cwd,
        environment=tuple(environment),
        effects=tuple(effects),
    )


def _contract_range(value: Contract) -> CapabilityContractRange:
    if isinstance(value, bool):
        raise TypeError("Capability contract must be an integer or version pair")
    if isinstance(value, int):
        return CapabilityContractRange.exact(value)
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    ):
        return CapabilityContractRange(minimum=value[0], maximum=value[1])
    raise TypeError("Capability contract must be an integer or version pair")


def _string_tuple(values: Sequence[str], *, name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{name} must be a sequence of strings")
    result = tuple(values)
    if any(not isinstance(item, str) for item in result):
        raise TypeError(f"{name} must contain only strings")
    return result


def _requirement_tuple(
    values: Sequence[CapabilityRequirement],
) -> tuple[CapabilityRequirement, ...]:
    if isinstance(values, CapabilityRequirement):
        raise TypeError("Capability Provider requirements must be a sequence")
    result = tuple(values)
    if any(not isinstance(item, CapabilityRequirement) for item in result):
        raise TypeError(
            "Capability Provider requirements must contain requirement records"
        )
    return result


def _canonical_symbol_locator(value: str) -> str:
    path, symbol = parse_plugin_entrypoint(value)
    return f"{path.as_posix()}:{symbol}"


def _symbol_reference(value: str) -> PluginSymbolReference:
    path, symbol = parse_plugin_entrypoint(value)
    return PluginSymbolReference(
        path=path.as_posix(),
        symbol=symbol,
        execution_model="in_process",
    )


__all__ = [
    "CapabilityProviderSpec",
    "Contract",
    "PluginDefinitionBuilder",
    "PluginDefinitionFunction",
    "ResourceItemSpec",
    "capability_provider",
    "capability_requirement",
    "plugin_definition",
    "resource",
    "skill_action",
    "skill_action_effect",
]
