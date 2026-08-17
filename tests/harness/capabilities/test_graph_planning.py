from __future__ import annotations

import pytest

from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityGraphPlanningError,
    CapabilityGraphPlanRequest,
    CapabilityRequirement,
    RuntimeCapabilityGraphPlanner,
)


def _definition(
    capability_id: str,
    *,
    facets: tuple[str, ...],
    scope: str,
    refresh_boundary: str = "sealed",
    phase: str = "final",
    contract_version: int = 1,
    authority_ceiling: frozenset[str] = frozenset(),
) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id=capability_id,
        owner_id=capability_id.split(".", maxsplit=1)[0],
        contract_version=contract_version,
        facets=facets,
        scope=scope,
        refresh_boundary=refresh_boundary,
        phase=phase,
        authority_ceiling=authority_ceiling,
    )


def _provider(
    capability_id: str,
    *,
    facets: tuple[str, ...],
    requirements: tuple[CapabilityRequirement, ...] = (),
    compatible_contract: CapabilityContractRange | None = None,
    required_authorities: frozenset[str] = frozenset(),
) -> CapabilityBundleProvider:
    return CapabilityBundleProvider(
        capability_id=capability_id,
        provider_id=f"standard.{capability_id}",
        implementation_version=1,
        compatible_contract=compatible_contract or CapabilityContractRange.exact(1),
        facets=facets,
        requirements=requirements,
        required_authorities=required_authorities,
    )


def _valid_request() -> CapabilityGraphPlanRequest:
    workspace = _definition(
        "harness.workspace",
        facets=("read", "process.launch"),
        scope="workspace",
        phase="bootstrap",
        authority_ceiling=frozenset({"filesystem", "process"}),
    )
    resources = _definition(
        "harness.resources",
        facets=("prompt.sections", "tool.packs"),
        scope="session",
        refresh_boundary="turn",
    )
    session = _definition(
        "harness.session",
        facets=("context", "transcript"),
        scope="session",
    )
    return CapabilityGraphPlanRequest(
        product_id="research",
        roots=("harness.session",),
        definitions=(session, workspace, resources),
        providers=(
            _provider(
                "harness.session",
                facets=("context", "transcript"),
                requirements=(
                    CapabilityRequirement(
                        capability="harness.resources",
                        facets=("prompt.sections",),
                        compatible_contract=CapabilityContractRange.exact(1),
                        binding="stable_reference",
                    ),
                    CapabilityRequirement(
                        capability="harness.workspace",
                        facets=("read",),
                        compatible_contract=CapabilityContractRange.exact(1),
                    ),
                ),
            ),
            _provider(
                "harness.resources",
                facets=("prompt.sections", "tool.packs"),
                requirements=(
                    CapabilityRequirement(
                        capability="harness.workspace",
                        facets=("read",),
                        compatible_contract=CapabilityContractRange.exact(1),
                    ),
                ),
            ),
            _provider(
                "harness.workspace",
                facets=("read", "process.launch"),
                required_authorities=frozenset({"filesystem", "process"}),
            ),
        ),
    )


def test_graph_planner_builds_deterministic_dependency_closure() -> None:
    request = _valid_request()

    plan = RuntimeCapabilityGraphPlanner().plan(request)
    reordered = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id=request.product_id,
            roots=request.roots,
            definitions=tuple(reversed(request.definitions)),
            providers=tuple(reversed(request.providers)),
        )
    )

    assert plan.binding_order == (
        "harness.workspace",
        "harness.resources",
        "harness.session",
    )
    assert reordered.binding_order == plan.binding_order
    assert plan.dependency_closure("harness.session") == (
        "harness.workspace",
        "harness.resources",
    )
    assert plan.node("harness.session").dependency_ids == (
        "harness.resources",
        "harness.workspace",
    )


def test_graph_planner_rejects_unknown_and_missing_dependency_contracts() -> None:
    root = _definition("research.root", facets=("query",), scope="session")
    dependency = _definition(
        "harness.workspace",
        facets=("read",),
        scope="workspace",
        contract_version=2,
    )
    provider = _provider(
        "research.root",
        facets=("query",),
        requirements=(
            CapabilityRequirement(
                capability="harness.workspace",
                facets=("read", "process.launch"),
                compatible_contract=CapabilityContractRange.exact(1),
            ),
            CapabilityRequirement(
                capability="research.missing",
                facets=("query",),
                compatible_contract=CapabilityContractRange.exact(1),
            ),
        ),
    )

    with pytest.raises(CapabilityGraphPlanningError) as exc_info:
        RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id="research",
                roots=("research.root",),
                definitions=(root, dependency),
                providers=(
                    provider,
                    _provider(
                        "harness.workspace",
                        facets=("read",),
                        compatible_contract=CapabilityContractRange.exact(2),
                    ),
                ),
            )
        )

    assert tuple(diagnostic.code for diagnostic in exc_info.value.diagnostics) == (
        "missing_provider_facet",
        "requirement_contract_incompatible",
        "unknown_capability",
        "unknown_facet",
    )


@pytest.mark.parametrize(
    ("definitions", "providers", "expected_code"),
    (
        ((), (), "unknown_root"),
        (
            (
                _definition(
                    "research.root",
                    facets=("value",),
                    scope="session",
                ),
            ),
            (),
            "missing_provider",
        ),
    ),
)
def test_graph_planner_rejects_unknown_roots_and_missing_root_providers(
    definitions: tuple[CapabilityDefinition, ...],
    providers: tuple[CapabilityBundleProvider, ...],
    expected_code: str,
) -> None:
    with pytest.raises(CapabilityGraphPlanningError) as exc_info:
        RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id="research",
                roots=("research.root",),
                definitions=definitions,
                providers=providers,
            )
        )

    assert [item.code for item in exc_info.value.diagnostics] == [expected_code]


def test_graph_planner_reports_complete_cycle_path() -> None:
    definitions = tuple(
        _definition(capability_id, facets=("value",), scope="session")
        for capability_id in ("research.a", "research.b", "research.c")
    )
    providers = (
        _provider(
            "research.a",
            facets=("value",),
            requirements=(
                CapabilityRequirement(
                    capability="research.b",
                    facets=("value",),
                    compatible_contract=CapabilityContractRange.exact(1),
                ),
            ),
        ),
        _provider(
            "research.b",
            facets=("value",),
            requirements=(
                CapabilityRequirement(
                    capability="research.c",
                    facets=("value",),
                    compatible_contract=CapabilityContractRange.exact(1),
                ),
            ),
        ),
        _provider(
            "research.c",
            facets=("value",),
            requirements=(
                CapabilityRequirement(
                    capability="research.a",
                    facets=("value",),
                    compatible_contract=CapabilityContractRange.exact(1),
                ),
            ),
        ),
    )

    with pytest.raises(CapabilityGraphPlanningError) as exc_info:
        RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id="research",
                roots=("research.a",),
                definitions=definitions,
                providers=providers,
            )
        )

    assert len(exc_info.value.diagnostics) == 1
    diagnostic = exc_info.value.diagnostics[0]
    assert diagnostic.code == "dependency_cycle"
    assert diagnostic.path == (
        "research.a",
        "research.b",
        "research.c",
        "research.a",
    )


@pytest.mark.parametrize(
    ("consumer", "dependency", "binding", "expected_code"),
    (
        (
            _definition("research.process", facets=("value",), scope="process"),
            _definition("research.session", facets=("value",), scope="session"),
            "direct",
            "scope_inversion",
        ),
        (
            _definition("research.sealed", facets=("value",), scope="session"),
            _definition(
                "research.turn",
                facets=("value",),
                scope="session",
                refresh_boundary="turn",
            ),
            "direct",
            "refresh_inversion",
        ),
        (
            _definition(
                "research.bootstrap",
                facets=("value",),
                scope="session",
                phase="bootstrap",
            ),
            _definition("research.final", facets=("value",), scope="session"),
            "stable_reference",
            "phase_inversion",
        ),
    ),
)
def test_graph_planner_rejects_lifecycle_inversions(
    consumer: CapabilityDefinition,
    dependency: CapabilityDefinition,
    binding: str,
    expected_code: str,
) -> None:
    requirement = CapabilityRequirement(
        capability=dependency.capability_id,
        facets=("value",),
        compatible_contract=CapabilityContractRange.exact(1),
        binding=binding,
    )

    with pytest.raises(CapabilityGraphPlanningError) as exc_info:
        RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id="research",
                roots=(consumer.capability_id,),
                definitions=(consumer, dependency),
                providers=(
                    _provider(
                        consumer.capability_id,
                        facets=("value",),
                        requirements=(requirement,),
                    ),
                    _provider(dependency.capability_id, facets=("value",)),
                ),
            )
        )

    assert [item.code for item in exc_info.value.diagnostics] == [expected_code]


def test_stable_reference_allows_scope_and_refresh_seams() -> None:
    consumer = _definition("research.process", facets=("value",), scope="process")
    dependency = _definition(
        "research.turn",
        facets=("value",),
        scope="session",
        refresh_boundary="turn",
    )
    requirement = CapabilityRequirement(
        capability=dependency.capability_id,
        facets=("value",),
        compatible_contract=CapabilityContractRange.exact(1),
        binding="stable_reference",
    )

    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="research",
            roots=(consumer.capability_id,),
            definitions=(consumer, dependency),
            providers=(
                _provider(
                    consumer.capability_id,
                    facets=("value",),
                    requirements=(requirement,),
                ),
                _provider(dependency.capability_id, facets=("value",)),
            ),
        )
    )

    assert plan.binding_order == ("research.turn", "research.process")


def test_graph_planner_rejects_provider_contract_facet_and_authority_ceiling() -> None:
    definition = _definition(
        "harness.workspace",
        facets=("read",),
        scope="workspace",
        contract_version=2,
        authority_ceiling=frozenset({"filesystem"}),
    )
    provider = _provider(
        "harness.workspace",
        facets=("read", "raw_backend"),
        compatible_contract=CapabilityContractRange.exact(1),
        required_authorities=frozenset({"filesystem", "network"}),
    )

    with pytest.raises(CapabilityGraphPlanningError) as exc_info:
        RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id="research",
                roots=("harness.workspace",),
                definitions=(definition,),
                providers=(provider,),
            )
        )

    assert tuple(diagnostic.code for diagnostic in exc_info.value.diagnostics) == (
        "authority_ceiling_exceeded",
        "facet_ceiling_exceeded",
        "provider_contract_incompatible",
    )


def test_optional_missing_dependency_does_not_enter_the_plan() -> None:
    root = _definition("research.root", facets=("value",), scope="session")
    provider = _provider(
        "research.root",
        facets=("value",),
        requirements=(
            CapabilityRequirement(
                capability="research.optional",
                facets=("value",),
                compatible_contract=CapabilityContractRange.exact(1),
                optional=True,
            ),
        ),
    )

    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="research",
            roots=("research.root",),
            definitions=(root,),
            providers=(provider,),
        )
    )

    assert plan.binding_order == ("research.root",)
    assert plan.node("research.root").requirements == ()


def test_graph_planner_rejects_cross_product_dependencies() -> None:
    research = _definition("research.root", facets=("value",), scope="session")
    coding = _definition("coding.lsp", facets=("query",), scope="workspace")

    with pytest.raises(CapabilityGraphPlanningError) as exc_info:
        RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id="research",
                roots=(research.capability_id,),
                definitions=(research, coding),
                providers=(
                    _provider(
                        research.capability_id,
                        facets=("value",),
                        requirements=(
                            CapabilityRequirement(
                                capability=coding.capability_id,
                                facets=("query",),
                                compatible_contract=CapabilityContractRange.exact(1),
                            ),
                        ),
                    ),
                    _provider(coding.capability_id, facets=("query",)),
                ),
            )
        )

    assert [item.code for item in exc_info.value.diagnostics] == [
        "cross_product_dependency"
    ]


def test_ambiguous_inputs_have_order_independent_diagnostics() -> None:
    definitions = (
        _definition("research.root", facets=("old",), scope="session"),
        _definition(
            "research.root",
            facets=("new",),
            scope="session",
            contract_version=2,
        ),
    )
    providers = (
        _provider("research.root", facets=("old",)),
        _provider(
            "research.root",
            facets=("new",),
            compatible_contract=CapabilityContractRange.exact(2),
        ),
    )

    diagnostics = []
    for definition_order, provider_order in (
        (definitions, providers),
        (tuple(reversed(definitions)), tuple(reversed(providers))),
    ):
        with pytest.raises(CapabilityGraphPlanningError) as exc_info:
            RuntimeCapabilityGraphPlanner().plan(
                CapabilityGraphPlanRequest(
                    product_id="research",
                    roots=("research.root",),
                    definitions=definition_order,
                    providers=provider_order,
                )
            )
        diagnostics.append(exc_info.value.diagnostics)

    assert diagnostics[0] == diagnostics[1]
    assert [item.code for item in diagnostics[0]] == [
        "ambiguous_provider",
        "duplicate_definition",
    ]
