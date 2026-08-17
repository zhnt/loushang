"""Pure dependency closure, validation, and ordering for Capability plans."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.capabilities.contracts import (
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider


@dataclass(frozen=True)
class CapabilityGraphPlanRequest:
    """One Product's selected, data-only Capability planning inputs."""

    product_id: str
    roots: tuple[str, ...]
    definitions: tuple[CapabilityDefinition, ...]
    providers: tuple[CapabilityBundleProvider, ...]

    def __post_init__(self) -> None:
        product_id = _require_nonempty(self.product_id, name="graph Product id")
        roots = _normalized_names(self.roots, name="graph roots")
        if not roots:
            raise ValueError("graph roots must not be empty")
        definitions = tuple(self.definitions)
        providers = tuple(self.providers)
        if any(not isinstance(item, CapabilityDefinition) for item in definitions):
            raise TypeError(
                "graph definitions must contain CapabilityDefinition values"
            )
        if any(not isinstance(item, CapabilityBundleProvider) for item in providers):
            raise TypeError(
                "graph providers must contain CapabilityBundleProvider values"
            )
        object.__setattr__(self, "product_id", product_id)
        object.__setattr__(self, "roots", roots)
        object.__setattr__(self, "definitions", definitions)
        object.__setattr__(self, "providers", providers)


@dataclass(frozen=True)
class CapabilityGraphDiagnostic:
    """Deterministic, redacted explanation of one rejected graph fact."""

    code: str
    message: str
    capability_id: str | None = None
    dependency_id: str | None = None
    path: tuple[str, ...] = ()


class CapabilityGraphPlanningError(RuntimeError):
    """Raised only after all deterministic planning diagnostics are collected."""

    def __init__(self, diagnostics: tuple[CapabilityGraphDiagnostic, ...]) -> None:
        self.diagnostics = tuple(sorted(diagnostics, key=_diagnostic_key))
        codes = ", ".join(item.code for item in self.diagnostics)
        super().__init__(f"Capability graph planning failed: {codes}")


@dataclass(frozen=True)
class PlannedCapability:
    """One validated node in dependency-first binding order."""

    definition: CapabilityDefinition
    provider: CapabilityBundleProvider
    requirements: tuple[CapabilityRequirement, ...]
    dependency_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.definition, CapabilityDefinition):
            raise TypeError("planned definition must be a CapabilityDefinition")
        if not isinstance(self.provider, CapabilityBundleProvider):
            raise TypeError("planned provider must be a CapabilityBundleProvider")
        if self.definition.capability_id != self.provider.capability_id:
            raise ValueError(
                "planned definition and provider must target the same Capability"
            )
        requirements = tuple(self.requirements)
        if any(
            not isinstance(requirement, CapabilityRequirement)
            for requirement in requirements
        ):
            raise TypeError(
                "planned requirements must contain CapabilityRequirement values"
            )
        if any(
            requirement not in self.provider.requirements
            for requirement in requirements
        ):
            raise ValueError(
                "planned requirements must come from the selected Provider"
            )
        dependency_ids = _normalized_names(
            self.dependency_ids,
            name="planned dependency ids",
        )
        if {item.capability for item in requirements} != set(dependency_ids):
            raise ValueError(
                "planned requirements must match the resolved dependency identities"
            )
        object.__setattr__(
            self,
            "requirements",
            tuple(sorted(requirements, key=lambda item: item.capability)),
        )
        object.__setattr__(self, "dependency_ids", tuple(sorted(dependency_ids)))

    @property
    def capability_id(self) -> str:
        return self.definition.capability_id


@dataclass(frozen=True)
class RuntimeCapabilityGraphPlan:
    """Pure validated graph plan; it contains no mounted values or factories."""

    product_id: str
    roots: tuple[str, ...]
    nodes: tuple[PlannedCapability, ...]

    def __post_init__(self) -> None:
        product_id = _require_nonempty(self.product_id, name="graph Product id")
        roots = _normalized_names(self.roots, name="graph roots")
        if not roots:
            raise ValueError("graph roots must not be empty")
        nodes = tuple(self.nodes)
        if any(not isinstance(node, PlannedCapability) for node in nodes):
            raise TypeError("graph nodes must contain PlannedCapability values")
        node_ids = tuple(node.capability_id for node in nodes)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("graph nodes must not repeat a Capability identity")
        missing_roots = set(roots) - set(node_ids)
        if missing_roots:
            raise ValueError("every graph root must be present in the planned nodes")
        positions = {
            capability_id: index for index, capability_id in enumerate(node_ids)
        }
        for index, node in enumerate(nodes):
            if any(
                dependency_id not in positions or positions[dependency_id] >= index
                for dependency_id in node.dependency_ids
            ):
                raise ValueError(
                    "graph nodes must place every dependency before its consumer"
                )
        object.__setattr__(self, "product_id", product_id)
        object.__setattr__(self, "roots", tuple(sorted(roots)))
        object.__setattr__(self, "nodes", nodes)

    @property
    def binding_order(self) -> tuple[str, ...]:
        return tuple(node.capability_id for node in self.nodes)

    def node(self, capability_id: str) -> PlannedCapability:
        for node in self.nodes:
            if node.capability_id == capability_id:
                return node
        raise KeyError(f"Capability is not present in the graph plan: {capability_id}")

    def dependency_closure(self, capability_id: str) -> tuple[str, ...]:
        self.node(capability_id)
        dependencies: set[str] = set()

        def collect(current_id: str) -> None:
            for dependency_id in self.node(current_id).dependency_ids:
                if dependency_id in dependencies:
                    continue
                dependencies.add(dependency_id)
                collect(dependency_id)

        collect(capability_id)
        return tuple(
            node_id for node_id in self.binding_order if node_id in dependencies
        )


class RuntimeCapabilityGraphPlanner:
    """Build the accepted coarse Capability DAG without constructing Providers."""

    def plan(
        self,
        request: CapabilityGraphPlanRequest,
    ) -> RuntimeCapabilityGraphPlan:
        if not isinstance(request, CapabilityGraphPlanRequest):
            raise TypeError(
                "graph planner request must be a CapabilityGraphPlanRequest"
            )

        diagnostics: list[CapabilityGraphDiagnostic] = []
        definitions, duplicate_definitions = _index_definitions(
            request.definitions,
            diagnostics,
        )
        providers, duplicate_providers = _index_providers(
            request.providers,
            diagnostics,
        )
        self._validate_providers(
            definitions,
            providers,
            duplicate_definitions=duplicate_definitions,
            diagnostics=diagnostics,
        )

        visit_state: dict[str, str] = {}
        visit_path: list[str] = []
        binding_order: list[str] = []
        edges: dict[str, set[str]] = {}

        def visit(
            capability_id: str,
            *,
            root: bool = False,
            requested_by: str | None = None,
        ) -> None:
            if (
                capability_id in duplicate_definitions
                or capability_id in duplicate_providers
            ):
                return
            if visit_state.get(capability_id) == "done":
                return
            if visit_state.get(capability_id) == "visiting":
                cycle_start = visit_path.index(capability_id)
                cycle = tuple((*visit_path[cycle_start:], capability_id))
                diagnostic = CapabilityGraphDiagnostic(
                    code="dependency_cycle",
                    message="Capability dependency graph contains a cycle",
                    capability_id=capability_id,
                    path=cycle,
                )
                if diagnostic not in diagnostics:
                    diagnostics.append(diagnostic)
                return

            definition = definitions.get(capability_id)
            if definition is None:
                diagnostics.append(
                    CapabilityGraphDiagnostic(
                        code="unknown_root" if root else "unknown_capability",
                        message="Capability is not declared in this Product graph",
                        capability_id=capability_id,
                    )
                )
                return
            if definition.owner_id not in {"harness", request.product_id}:
                diagnostics.append(
                    CapabilityGraphDiagnostic(
                        code=(
                            "cross_product_root" if root else "cross_product_dependency"
                        ),
                        message=(
                            "Product graph cannot mount a Capability owned by "
                            "another Product"
                        ),
                        capability_id=(capability_id if root else requested_by),
                        dependency_id=(None if root else capability_id),
                    )
                )
                return
            provider = providers.get(capability_id)
            if provider is None:
                diagnostics.append(
                    CapabilityGraphDiagnostic(
                        code="missing_provider",
                        message="Capability has no selected Bundle Provider",
                        capability_id=capability_id,
                    )
                )
                return

            visit_state[capability_id] = "visiting"
            visit_path.append(capability_id)
            dependencies = edges.setdefault(capability_id, set())
            for requirement in sorted(
                provider.requirements,
                key=lambda item: item.capability,
            ):
                if (
                    requirement.capability in duplicate_definitions
                    or requirement.capability in duplicate_providers
                ):
                    continue
                dependency = definitions.get(requirement.capability)
                dependency_provider = providers.get(requirement.capability)
                if dependency is None or dependency_provider is None:
                    if requirement.optional:
                        continue
                    if dependency is None:
                        diagnostics.append(
                            CapabilityGraphDiagnostic(
                                code="unknown_capability",
                                message="Required Capability is not declared",
                                capability_id=capability_id,
                                dependency_id=requirement.capability,
                            )
                        )
                    else:
                        diagnostics.append(
                            CapabilityGraphDiagnostic(
                                code="missing_provider",
                                message="Required Capability has no selected Provider",
                                capability_id=capability_id,
                                dependency_id=requirement.capability,
                            )
                        )
                    continue
                dependencies.add(requirement.capability)
                self._validate_requirement(
                    consumer=definition,
                    requirement=requirement,
                    dependency=dependency,
                    dependency_provider=dependency_provider,
                    diagnostics=diagnostics,
                )
                visit(requirement.capability, requested_by=capability_id)
            visit_path.pop()
            visit_state[capability_id] = "done"
            binding_order.append(capability_id)

        for root in sorted(request.roots):
            visit(root, root=True)

        if diagnostics:
            raise CapabilityGraphPlanningError(tuple(_deduplicate(diagnostics)))

        nodes = tuple(
            PlannedCapability(
                definition=definitions[capability_id],
                provider=providers[capability_id],
                requirements=tuple(
                    requirement
                    for requirement in sorted(
                        providers[capability_id].requirements,
                        key=lambda item: item.capability,
                    )
                    if requirement.capability in edges.get(capability_id, set())
                ),
                dependency_ids=tuple(sorted(edges.get(capability_id, set()))),
            )
            for capability_id in binding_order
        )
        return RuntimeCapabilityGraphPlan(
            product_id=request.product_id,
            roots=tuple(sorted(request.roots)),
            nodes=nodes,
        )

    @staticmethod
    def _validate_providers(
        definitions: dict[str, CapabilityDefinition],
        providers: dict[str, CapabilityBundleProvider],
        duplicate_definitions: frozenset[str],
        diagnostics: list[CapabilityGraphDiagnostic],
    ) -> None:
        for capability_id, provider in sorted(providers.items()):
            if capability_id in duplicate_definitions:
                continue
            definition = definitions.get(capability_id)
            if definition is None:
                diagnostics.append(
                    CapabilityGraphDiagnostic(
                        code="unknown_provider_capability",
                        message="Provider targets an undeclared Capability",
                        capability_id=capability_id,
                    )
                )
                continue
            if not provider.compatible_contract.accepts(definition.contract_version):
                diagnostics.append(
                    CapabilityGraphDiagnostic(
                        code="provider_contract_incompatible",
                        message="Provider is incompatible with the Capability contract",
                        capability_id=capability_id,
                    )
                )
            undeclared_facets = set(provider.facets) - set(definition.facets)
            if undeclared_facets:
                diagnostics.append(
                    CapabilityGraphDiagnostic(
                        code="facet_ceiling_exceeded",
                        message="Provider exports facets outside the Definition ceiling",
                        capability_id=capability_id,
                    )
                )
            excess_authority = (
                provider.required_authorities - definition.authority_ceiling
            )
            if excess_authority:
                diagnostics.append(
                    CapabilityGraphDiagnostic(
                        code="authority_ceiling_exceeded",
                        message="Provider requires authority outside the Definition ceiling",
                        capability_id=capability_id,
                    )
                )

    @staticmethod
    def _validate_requirement(
        *,
        consumer: CapabilityDefinition,
        requirement: CapabilityRequirement,
        dependency: CapabilityDefinition,
        dependency_provider: CapabilityBundleProvider,
        diagnostics: list[CapabilityGraphDiagnostic],
    ) -> None:
        if not requirement.compatible_contract.accepts(dependency.contract_version):
            diagnostics.append(
                CapabilityGraphDiagnostic(
                    code="requirement_contract_incompatible",
                    message="Consumer requirement is incompatible with the contract",
                    capability_id=consumer.capability_id,
                    dependency_id=dependency.capability_id,
                )
            )
        if set(requirement.facets) - set(dependency.facets):
            diagnostics.append(
                CapabilityGraphDiagnostic(
                    code="unknown_facet",
                    message="Consumer requests a facet absent from the Definition",
                    capability_id=consumer.capability_id,
                    dependency_id=dependency.capability_id,
                )
            )
        if set(requirement.facets) - set(dependency_provider.facets):
            diagnostics.append(
                CapabilityGraphDiagnostic(
                    code="missing_provider_facet",
                    message="Selected Provider does not supply every requested facet",
                    capability_id=consumer.capability_id,
                    dependency_id=dependency.capability_id,
                )
            )
        if consumer.phase == "bootstrap" and dependency.phase == "final":
            diagnostics.append(
                CapabilityGraphDiagnostic(
                    code="phase_inversion",
                    message="Bootstrap Capability depends on a final-only Capability",
                    capability_id=consumer.capability_id,
                    dependency_id=dependency.capability_id,
                )
            )
        if requirement.binding == "stable_reference":
            return
        if dependency.scope not in _DIRECT_DEPENDENCY_SCOPES[consumer.scope]:
            diagnostics.append(
                CapabilityGraphDiagnostic(
                    code="scope_inversion",
                    message="Dependency does not outlive the consuming Capability",
                    capability_id=consumer.capability_id,
                    dependency_id=dependency.capability_id,
                )
            )
        if (
            consumer.refresh_boundary == "sealed"
            and dependency.refresh_boundary == "turn"
        ):
            diagnostics.append(
                CapabilityGraphDiagnostic(
                    code="refresh_inversion",
                    message="Sealed Capability captures a turn-refreshable dependency",
                    capability_id=consumer.capability_id,
                    dependency_id=dependency.capability_id,
                )
            )


_DIRECT_DEPENDENCY_SCOPES = {
    "process": frozenset({"process"}),
    "tenant": frozenset({"process", "tenant"}),
    "workspace": frozenset({"process", "tenant", "workspace"}),
    "session": frozenset({"process", "tenant", "workspace", "session"}),
    "turn": frozenset({"process", "tenant", "workspace", "session", "turn"}),
    "channel": frozenset({"process", "tenant", "channel"}),
}


def _index_definitions(
    values: tuple[CapabilityDefinition, ...],
    diagnostics: list[CapabilityGraphDiagnostic],
) -> tuple[dict[str, CapabilityDefinition], frozenset[str]]:
    indexed: dict[str, CapabilityDefinition] = {}
    duplicates: set[str] = set()
    for definition in values:
        if definition.capability_id in duplicates:
            continue
        if definition.capability_id in indexed:
            diagnostics.append(
                CapabilityGraphDiagnostic(
                    code="duplicate_definition",
                    message="Capability Definition identity is duplicated",
                    capability_id=definition.capability_id,
                )
            )
            del indexed[definition.capability_id]
            duplicates.add(definition.capability_id)
            continue
        indexed[definition.capability_id] = definition
    return indexed, frozenset(duplicates)


def _index_providers(
    values: tuple[CapabilityBundleProvider, ...],
    diagnostics: list[CapabilityGraphDiagnostic],
) -> tuple[dict[str, CapabilityBundleProvider], frozenset[str]]:
    indexed: dict[str, CapabilityBundleProvider] = {}
    duplicates: set[str] = set()
    for provider in values:
        if provider.capability_id in duplicates:
            continue
        if provider.capability_id in indexed:
            diagnostics.append(
                CapabilityGraphDiagnostic(
                    code="ambiguous_provider",
                    message="Capability has more than one selected Bundle Provider",
                    capability_id=provider.capability_id,
                )
            )
            del indexed[provider.capability_id]
            duplicates.add(provider.capability_id)
            continue
        indexed[provider.capability_id] = provider
    return indexed, frozenset(duplicates)


def _diagnostic_key(
    diagnostic: CapabilityGraphDiagnostic,
) -> tuple[object, ...]:
    return (
        diagnostic.code,
        diagnostic.capability_id or "",
        diagnostic.dependency_id or "",
        diagnostic.path,
        diagnostic.message,
    )


def _deduplicate(
    diagnostics: list[CapabilityGraphDiagnostic],
) -> tuple[CapabilityGraphDiagnostic, ...]:
    unique: list[CapabilityGraphDiagnostic] = []
    for diagnostic in diagnostics:
        if diagnostic not in unique:
            unique.append(diagnostic)
    return tuple(unique)


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _normalized_names(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    normalized = tuple(_require_nonempty(value, name=name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


__all__ = [
    "CapabilityGraphDiagnostic",
    "CapabilityGraphPlanRequest",
    "CapabilityGraphPlanningError",
    "PlannedCapability",
    "RuntimeCapabilityGraphPlan",
    "RuntimeCapabilityGraphPlanner",
]
