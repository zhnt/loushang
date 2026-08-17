from __future__ import annotations

import asyncio
from pathlib import Path
from typing import get_type_hints

import pytest

from loushang.harness.extensions.api import ExtensionContributionAPI
from loushang.harness.extensions.contributions import surfaces_from_loaded_extension
from loushang.harness.extensions.dispatch import ExtensionDispatcher
from loushang.harness.extensions.manifest import ExtensionManifest
from loushang.harness.extensions.resources import ExtensionResourceRuntime
from loushang.harness.extensions.routing import (
    ExtensionRouteError,
    ExtensionRoutePlan,
    ExtensionRouter,
    RegisteredExtensionHandler,
    RouteStep,
)
from loushang.harness.extensions.types import ExtensionPolicyDecision, LoadedExtension
from loushang.harness.resources.types import ResourceBundle


def _registration(
    route_id: str,
    handler,
    *,
    event: str = "context",
    priority: int = 0,
    after: tuple[str, ...] = (),
    before: tuple[str, ...] = (),
    on_error: str = "skip",
) -> RegisteredExtensionHandler:
    return RegisteredExtensionHandler(
        local_route_id=route_id,
        event_name=event,
        handler=handler,
        priority=priority,
        after=after,
        before=before,
        on_error=on_error,  # type: ignore[arg-type]
    )


def _extension(
    name: str,
    *registrations: RegisteredExtensionHandler,
) -> LoadedExtension:
    return LoadedExtension(
        name=name,
        source_path=Path(f"/tmp/{name}.py"),
        handler_registrations=list(registrations),
    )


def _noop(event, context) -> None:
    del event, context


def test_contribution_api_records_ordering_metadata_and_preserves_hooks() -> None:
    handler = _noop
    api = ExtensionContributionAPI(name="shared", source_path=Path("/tmp/shared.py"))

    api.on(
        "context",
        handler,
        route_id="redact",
        priority=20,
        after=("extension:base",),
        before=("route:shared/context/final",),
        on_error="fail_chain",
    )

    extension = api.build_loaded_extension()
    registration = extension.handler_registrations[0]
    assert extension.hooks == {"context": [handler]}
    assert registration.local_route_id == "redact"
    assert registration.priority == 20
    assert registration.after == ("extension:base",)
    assert registration.before == ("route:shared/context/final",)
    assert registration.on_error == "fail_chain"


def test_loaded_extension_route_registration_type_is_runtime_reflectable() -> None:
    hints = get_type_hints(LoadedExtension)

    assert hints["handler_registrations"] == list[RegisteredExtensionHandler]


def test_contribution_api_rejects_string_ordering_references() -> None:
    api = ExtensionContributionAPI(name="shared", source_path=Path("/tmp/shared.py"))

    with pytest.raises(TypeError, match="sequence of strings"):
        api.on("context", _noop, after="extension:base")
    with pytest.raises(TypeError, match="sequence of strings"):
        api.on("context", _noop, before="extension:tail")


def test_contribution_api_rejects_explicit_empty_route_id() -> None:
    api = ExtensionContributionAPI(name="shared", source_path=Path("/tmp/shared.py"))

    with pytest.raises(ValueError, match="route id must not be empty"):
        api.on("context", _noop, route_id="")


def test_registration_only_extension_projects_hooks_and_surface_metadata() -> None:
    registration = _registration(
        "redact",
        _noop,
        priority=20,
        after=("extension:base",),
        on_error="fail_chain",
    )
    extension = _extension("shared", registration)

    surfaces = surfaces_from_loaded_extension(extension)

    assert extension.hooks == {"context": [_noop]}
    assert len(surfaces) == 1
    surface = surfaces[0]
    assert (surface.type, surface.name) == ("hook", "context")
    assert surface.priority == 20
    assert surface.after == ("extension:base",)
    assert surface.on_error == "fail_chain"
    assert surface.metadata["route_id"] == "redact"


def test_plan_synthesizes_legacy_handlers_in_stable_two_dimensional_order() -> None:
    calls: list[str] = []

    def handler(name: str):
        def run(event, context):
            del event, context
            calls.append(name)
            return name

        return run

    first = LoadedExtension(
        name="first",
        source_path=Path("/tmp/first.py"),
        hooks={"context": [handler("first-1"), handler("first-2")]},
    )
    second = LoadedExtension(
        name="second",
        source_path=Path("/tmp/second.py"),
        hooks={"context": [handler("second-1")]},
    )
    diagnostics = []
    plan = ExtensionRoutePlan.from_extensions([first, second], diagnostics=diagnostics)
    router = ExtensionRouter(plan, diagnostics=diagnostics)
    context_calls: list[str] = []

    results = asyncio.run(
        router.observe(
            "context",
            object(),
            context_factory=lambda extension: (
                context_calls.append(extension.name) or object()
            ),
        )
    )

    assert results == ("first-1", "first-2", "second-1")
    assert calls == ["first-1", "first-2", "second-1"]
    assert context_calls == ["first", "second"]
    assert [route.route_id for route in plan.routes_for("context")] == [
        "first/context/legacy-0001",
        "first/context/legacy-0002",
        "second/context/legacy-0001",
    ]
    assert diagnostics == []


def test_plan_orders_constraints_before_priority_and_uses_priority_for_ready_routes() -> (
    None
):
    base = _extension("base", _registration("base", _noop))
    high = _extension("high", _registration("high", _noop, priority=20))
    tail = _extension(
        "tail",
        _registration(
            "tail",
            _noop,
            priority=100,
            after=("extension:base",),
        ),
    )

    plan = ExtensionRoutePlan.from_extensions([base, tail, high])

    assert [route.extension.name for route in plan.routes_for("context")] == [
        "high",
        "base",
        "tail",
    ]


def test_explicit_registration_plan_does_not_synthesize_legacy_hooks() -> None:
    legacy = LoadedExtension(
        name="legacy",
        source_path=Path("/tmp/legacy.py"),
        hooks={"context": [_noop]},
    )
    high = _registration("high", _noop, event="policy", priority=10)
    low = _registration("low", _noop, event="policy")

    plan = ExtensionRoutePlan.from_extension_registrations(
        [
            (
                legacy,
                (
                    low,
                    high,
                ),
            )
        ]
    )

    assert plan.routes_for("context") == ()
    assert [
        route.registration.local_route_id for route in plan.routes_for("policy")
    ] == [
        "high",
        "low",
    ]


def test_plan_preserves_external_edges_while_falling_back_inside_cycle() -> None:
    before = _extension(
        "before",
        _registration(
            "before",
            _noop,
            before=("route:a/context/a",),
        ),
    )
    a = _extension(
        "a",
        _registration(
            "a",
            _noop,
            priority=1,
            after=("route:b/context/b",),
        ),
    )
    b = _extension(
        "b",
        _registration(
            "b",
            _noop,
            priority=9,
            after=("route:a/context/a",),
        ),
    )
    after = _extension(
        "after",
        _registration(
            "after",
            _noop,
            after=("route:b/context/b",),
        ),
    )
    diagnostics = []

    plan = ExtensionRoutePlan.from_extensions(
        [a, after, before, b],
        diagnostics=diagnostics,
    )

    assert [route.extension.name for route in plan.routes_for("context")] == [
        "before",
        "b",
        "a",
        "after",
    ]
    cycle = [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.code == "extension_route_order_cycle"
    ]
    assert len(cycle) == 1
    assert cycle[0].details["metadata"]["route_ids"] == (
        "b/context/b",
        "a/context/a",
    )


def test_plan_reports_malformed_missing_self_and_duplicate_route_ids() -> None:
    extension = _extension(
        "shared",
        _registration(
            "same",
            _noop,
            after=(
                "bad-reference",
                "route:missing/context/route",
                "route:shared/context/same",
            ),
        ),
        _registration("same", _noop),
    )
    diagnostics = []

    plan = ExtensionRoutePlan.from_extensions([extension], diagnostics=diagnostics)

    assert len(plan.routes_for("context")) == 2
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "duplicate_extension_route_id",
        "malformed_extension_route_reference",
        "missing_extension_route_reference",
        "extension_route_self_reference",
    ]


def test_plan_preserves_routes_when_active_extensions_share_an_id() -> None:
    calls: list[str] = []

    def handler(name: str):
        def run(event, context) -> None:
            del event, context
            calls.append(name)

        return run

    first = _extension("duplicate", _registration("shared", handler("first")))
    second = _extension("duplicate", _registration("shared", handler("second")))
    diagnostics = []
    plan = ExtensionRoutePlan.from_extensions(
        [first, second],
        diagnostics=diagnostics,
    )
    router = ExtensionRouter(plan, diagnostics=diagnostics)

    asyncio.run(
        router.observe(
            "context",
            object(),
            context_factory=lambda extension: extension.name,
        )
    )

    assert calls == ["first", "second"]
    assert [route.route_id for route in plan.routes_for("context")] == [
        "duplicate/context/shared",
        "duplicate/context/shared#duplicate-2",
    ]
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "duplicate_extension_route_id"
    ]


def test_route_ids_encode_components_and_reserve_duplicate_suffixes() -> None:
    first = LoadedExtension(
        name="first",
        source_path=Path("/tmp/first.py"),
        manifest=ExtensionManifest(id="a", name="First"),
        handler_registrations=[
            _registration("same", _noop),
            _registration("same", _noop),
            _registration(
                "dependent",
                _noop,
                after=("route:a/context/same%23duplicate-2",),
            ),
            _registration("same#duplicate-2", _noop),
            _registration("x/context/百分比%y", _noop),
        ],
    )
    second = LoadedExtension(
        name="second",
        source_path=Path("/tmp/second.py"),
        manifest=ExtensionManifest(id="a/context/x", name="Second"),
        handler_registrations=[_registration("y", _noop)],
    )
    diagnostics = []

    plan = ExtensionRoutePlan.from_extensions(
        [first, second],
        diagnostics=diagnostics,
    )

    assert [route.route_id for route in plan.routes_for("context")] == [
        "a/context/same",
        "a/context/same#duplicate-2",
        "a/context/same%23duplicate-2",
        "a/context/dependent",
        "a/context/x%2Fcontext%2F%E7%99%BE%E5%88%86%E6%AF%94%25y",
        "a%2Fcontext%2Fx/context/y",
    ]
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "duplicate_extension_route_id"
    ]


def test_route_planning_handles_dependency_chains_beyond_recursion_limit() -> None:
    route_count = 1200
    registrations = [
        _registration(
            f"route-{index}",
            _noop,
            before=(f"route:large/context/route-{index + 1}",)
            if index + 1 < route_count
            else (),
        )
        for index in range(route_count)
    ]

    plan = ExtensionRoutePlan.from_extensions([_extension("large", *registrations)])

    routes = plan.routes_for("context")
    assert len(routes) == route_count
    assert routes[0].route_id == "large/context/route-0"
    assert routes[-1].route_id == f"large/context/route-{route_count - 1}"


def test_route_planning_handles_wide_independent_route_sets() -> None:
    route_count = 3000
    registrations = [
        _registration(f"route-{index}", _noop) for index in range(route_count)
    ]

    plan = ExtensionRoutePlan.from_extensions([_extension("wide", *registrations)])

    routes = plan.routes_for("context")
    assert len(routes) == route_count
    assert routes[0].route_id == "wide/context/route-0"
    assert routes[-1].route_id == f"wide/context/route-{route_count - 1}"


def test_plan_normalizes_and_rejects_empty_extension_route_identities() -> None:
    normalized = _extension(
        " normalized ",
        _registration("route", _noop),
    )
    dependent = _extension(
        "dependent",
        _registration(
            "route",
            _noop,
            after=("extension:normalized",),
        ),
    )
    empty = _extension("   ", _registration("route", _noop))
    diagnostics = []

    plan = ExtensionRoutePlan.from_extensions(
        [dependent, empty, normalized],
        diagnostics=diagnostics,
    )

    assert [route.route_id for route in plan.routes_for("context")] == [
        "normalized/context/route",
        "dependent/context/route",
    ]
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "invalid_extension_route_identity"
    ]


def test_cycle_diagnostics_follow_stable_route_order() -> None:
    root = _extension(
        "root",
        _registration(
            "root",
            _noop,
            before=(
                "route:a/context/one",
                "route:b/context/one",
            ),
        ),
    )
    a = _extension(
        "a",
        _registration("one", _noop, after=("route:a/context/two",)),
        _registration("two", _noop, after=("route:a/context/one",)),
    )
    b = _extension(
        "b",
        _registration("one", _noop, after=("route:b/context/two",)),
        _registration("two", _noop, after=("route:b/context/one",)),
    )
    diagnostics = []

    ExtensionRoutePlan.from_extensions(
        [root, a, b],
        diagnostics=diagnostics,
    )

    assert [
        diagnostic.details["metadata"]["route_ids"]
        for diagnostic in diagnostics
        if diagnostic.code == "extension_route_order_cycle"
    ] == [
        ("a/context/one", "a/context/two"),
        ("b/context/one", "b/context/two"),
    ]


def test_plan_skips_inactive_extensions_and_their_ordering_references() -> None:
    calls: list[str] = []

    def inactive_handler(event, context) -> None:
        del event, context
        calls.append("inactive")

    inactive = LoadedExtension(
        name="optional",
        source_path=Path("/tmp/optional.py"),
        handler_registrations=[_registration("inactive", inactive_handler)],
        policy=ExtensionPolicyDecision(enabled=False),
    )
    active = _extension(
        "active",
        _registration(
            "active",
            _noop,
            after=(
                "extension:optional",
                "route:optional/context/inactive",
            ),
        ),
    )
    diagnostics = []
    plan = ExtensionRoutePlan.from_extensions(
        [inactive, active],
        diagnostics=diagnostics,
    )
    router = ExtensionRouter(plan, diagnostics=diagnostics)

    asyncio.run(
        router.observe(
            "context",
            object(),
            context_factory=lambda extension: extension.name,
        )
    )

    assert [route.extension.name for route in plan.routes_for("context")] == ["active"]
    assert calls == []
    assert diagnostics == []


def test_router_reduce_passes_latest_state_and_can_stop_chain() -> None:
    seen: list[tuple[str, int]] = []

    def add_one(event, context):
        del context
        seen.append(("one", event))
        return 1

    async def add_two(event, context):
        del context
        seen.append(("two", event))
        return 2

    def never(event, context):
        del event, context
        raise AssertionError("stopped route must not run")

    extension = _extension(
        "math",
        _registration("one", add_one),
        _registration("two", add_two),
        _registration("never", never),
    )
    diagnostics = []
    router = ExtensionRouter.from_extensions(
        [extension],
        diagnostics=diagnostics,
    )

    async def reducer(state, result, route):
        next_state = state + result
        return RouteStep(next_state, stop=route.registration.local_route_id == "two")

    outcome = asyncio.run(
        router.intercept(
            "context",
            0,
            event_factory=lambda state, route: state,
            reducer=reducer,
            context_factory=lambda extension: extension.name,
        )
    )

    assert outcome == RouteStep(3, stop=True)
    assert seen == [("one", 0), ("two", 1)]
    assert diagnostics == []


def test_router_skip_isolates_handler_and_runtime_callback_failures() -> None:
    calls: list[str] = []

    def broken(event, context):
        del event, context
        raise RuntimeError("handler failed")

    def succeeding(event, context):
        del event, context
        calls.append("succeeding")
        return "ok"

    extension = _extension(
        "shared",
        _registration("broken", broken),
        _registration("succeeding", succeeding),
    )
    diagnostics = []
    router = ExtensionRouter.from_extensions(
        [extension],
        diagnostics=diagnostics,
        runtime_error_handler=lambda extension, event, error: (_ for _ in ()).throw(
            RuntimeError("callback failed")
        ),
    )

    results = asyncio.run(
        router.observe(
            "context",
            object(),
            context_factory=lambda extension: extension.name,
        )
    )

    assert results == ("ok",)
    assert calls == ["succeeding"]
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "extension_context_failed"
    ]
    assert diagnostics[0].details["metadata"]["route_id"] == "shared/context/broken"


def test_router_fail_chain_raises_typed_route_error() -> None:
    def broken(event, context):
        del event, context
        raise ValueError("stop")

    extension = _extension(
        "shared",
        _registration("broken", broken, on_error="fail_chain"),
    )
    diagnostics = []
    router = ExtensionRouter.from_extensions([extension], diagnostics=diagnostics)

    with pytest.raises(ExtensionRouteError) as raised:
        asyncio.run(
            router.observe(
                "context",
                object(),
                context_factory=lambda extension: extension.name,
            )
        )

    assert raised.value.route.route_id == "shared/context/broken"
    assert isinstance(raised.value.__cause__, ValueError)
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "extension_context_failed"
    ]


def test_router_propagates_cancellation_without_diagnostic() -> None:
    async def cancelled(event, context):
        del event, context
        raise asyncio.CancelledError

    extension = _extension("shared", _registration("cancel", cancelled))
    diagnostics = []
    router = ExtensionRouter.from_extensions([extension], diagnostics=diagnostics)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            router.observe(
                "context",
                object(),
                context_factory=lambda extension: extension.name,
            )
        )

    assert diagnostics == []


def test_dispatcher_can_reuse_plan_without_repeating_validation_diagnostics() -> None:
    extension = _extension(
        "shared",
        _registration("route", _noop, after=("route:missing/context/route",)),
    )
    diagnostics = []
    plan = ExtensionRoutePlan.from_extensions([extension], diagnostics=diagnostics)

    first = ExtensionDispatcher(
        [extension],
        route_plan=plan,
        context_factory=lambda extension: extension.name,
        diagnostics=diagnostics,
    )
    second = ExtensionDispatcher(
        [extension],
        route_plan=plan,
        context_factory=lambda extension: extension.name,
        diagnostics=diagnostics,
    )
    asyncio.run(first.dispatch("context", object()))
    asyncio.run(second.dispatch("context", object()))

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "missing_extension_route_reference"
    ]


def test_resource_runtime_reuses_route_order_and_honors_fail_chain() -> None:
    calls: list[str] = []

    def first(bundle, context):
        del context
        calls.append("first")
        return None

    def broken(bundle, context):
        del bundle, context
        calls.append("broken")
        raise RuntimeError("resource failure")

    first_extension = _extension(
        "first",
        _registration(
            "first",
            first,
            event="resources_discover",
            priority=20,
        ),
    )
    broken_extension = _extension(
        "broken",
        _registration(
            "broken",
            broken,
            event="resources_discover",
            on_error="fail_chain",
        ),
    )
    diagnostics = []
    plan = ExtensionRoutePlan.from_extensions(
        [broken_extension, first_extension],
        diagnostics=diagnostics,
    )
    runtime = ExtensionResourceRuntime(
        [broken_extension, first_extension],
        diagnostics=diagnostics,
        route_plan=plan,
    )

    with pytest.raises(ExtensionRouteError):
        runtime.discover(
            ResourceBundle(cwd=Path("/tmp")),
            context=object(),
        )

    assert calls == ["first", "broken"]
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "extension_resources_discover_failed"
    ]
