from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace

import pytest

from loushang.harness.capabilities.component_admission import (
    CapabilityComponentAdmission,
    CapabilityComponentAdmissionError,
    CapabilityComponentCandidate,
    CapabilityComponentOwnerAuthority,
    CapabilityComponentOwnerPolicy,
)
from loushang.harness.capabilities.component_binding import (
    CapabilityOwnerComponentBinding,
    CapabilityOwnerComponentValue,
    owner_component_binding_fingerprint,
)
from loushang.harness.capabilities.component_contracts import (
    CapabilityComponentBindingSpec,
    CapabilityComponentDefinition,
)
from loushang.harness.capabilities.component_runtime import (
    CapabilityOwnerComponentBinder,
    CapabilityOwnerComponentBindingError,
    CapabilityOwnerComponentRuntime,
)
from loushang.harness.capabilities.component_selection import (
    CapabilityComponentSelectionChoice,
    CapabilityComponentSelectionError,
    CapabilityComponentSelectionPlan,
    ProductCapabilityComponentResolver,
    ResolvedCapabilityComponentSet,
)
from loushang.harness.capabilities.contracts import CapabilityContractRange


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _definition(
    *,
    kind: str = "resource.source",
    aggregate: bool = True,
) -> CapabilityComponentDefinition:
    return CapabilityComponentDefinition(
        capability_id="resource.catalog",
        owner_id="resource",
        component_kind=kind,
        payload_schema_id=f"loushang.{kind}/v1",
        payload_schema_version=1,
        compatible_bundle_contract=CapabilityContractRange.exact(2),
        multiplicity="aggregate" if aggregate else "exclusive",
        selection_policy="ordered_unique" if aggregate else "exactly_one",
        minimum_count=1,
        maximum_count=None if aggregate else 1,
        requested_facets=("resource.catalog",),
        disposer_contract="required",
    )


def _authority(
    definition: CapabilityComponentDefinition,
    *,
    component_ids: tuple[str, ...] = ("native", "alternate"),
) -> CapabilityComponentOwnerAuthority:
    return CapabilityComponentOwnerAuthority(
        definition,
        CapabilityComponentOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id=definition.owner_id,
            component_kind=definition.component_kind,
            policy_revision="resource-owner-policy-v1",
            revocation_epoch=0,
            allowed_component_ids=component_ids,
            allowed_source_trust_classes=("host_builtin",),
        ),
    )


def _candidate(
    definition: CapabilityComponentDefinition,
    component_id: str,
    *,
    revision: str = "builtin-r1",
) -> CapabilityComponentCandidate:
    return CapabilityComponentCandidate(
        definition=definition,
        component_id=component_id,
        binding_spec=CapabilityComponentBindingSpec(
            source_kind="first_party",
            source_id="loushang",
            contribution_id=f"resource:{component_id}",
            source_revision_ref=revision,
            content_digest=_digest(f"{component_id}:{revision}"),
        ),
        product_id="coding",
        scope_id="workspace:test",
        product_policy_revision="coding-policy-v1",
        source_trust_class="host_builtin",
        source_trust_policy_revision="host-builtins-v1",
        source_trusted=True,
    )


def _resolved(
    component_ids: tuple[str, ...],
    *,
    revision: str = "builtin-r1",
) -> tuple[ResolvedCapabilityComponentSet, CapabilityComponentOwnerAuthority]:
    definition = _definition()
    authority = _authority(definition, component_ids=component_ids)
    admissions = tuple(
        authority.admit(
            _candidate(definition, component_id, revision=revision),
            issued_at=10,
            expires_at=100,
        )
        for component_id in component_ids
    )
    plan = CapabilityComponentSelectionPlan(
        product_id="coding",
        scope_id="workspace:test",
        capability_id="resource.catalog",
        owner_id="resource",
        product_policy_revision="coding-policy-v1",
        choices=(
            CapabilityComponentSelectionChoice(
                component_kind="resource.source",
                admission_fingerprints=tuple(item.fingerprint for item in admissions),
            ),
        ),
    )
    resolved = ProductCapabilityComponentResolver().resolve(
        plan,
        definitions=(definition,),
        admissions=admissions,
        owner_snapshots=(authority.snapshot(),),
        now=20,
    )
    return resolved, authority


def _bindings(
    resolved: ResolvedCapabilityComponentSet,
    events: list[str],
    *,
    payload_suffix: str,
    fail_component: str | None = None,
) -> tuple[CapabilityOwnerComponentBinding, ...]:
    bindings = []
    for component in resolved.components:
        component_id = component.component_id

        def create(_context, component_id=component_id):  # type: ignore[no-untyped-def]
            events.append(f"create:{component_id}:{payload_suffix}")
            if component_id == fail_component:
                raise RuntimeError("construction failed")
            return f"{component_id}:{payload_suffix}"

        def dispose(_value, component_id=component_id):  # type: ignore[no-untyped-def]
            events.append(f"dispose:{component_id}:{payload_suffix}")

        bindings.append(
            CapabilityOwnerComponentBinding(
                resolved=component,
                binding_fingerprint=owner_component_binding_fingerprint(component),
                create=create,
                validate_payload=lambda payload: (
                    None
                    if isinstance(payload, str)
                    else (_ for _ in ()).throw(TypeError("payload must be text"))
                ),
                dispose=dispose,
            )
        )
    return tuple(bindings)


def test_definition_and_owner_admission_are_exact_and_independently_fingerprinted() -> None:
    definition = _definition(aggregate=False, kind="resource.catalog_engine")
    authority = _authority(definition, component_ids=("standard",))
    candidate = _candidate(definition, "standard")

    admission = authority.admit(candidate, issued_at=10, expires_at=100)

    assert definition.fingerprint != candidate.fingerprint
    assert candidate.fingerprint != admission.fingerprint
    assert admission.owner_snapshot_fingerprint == authority.snapshot().fingerprint
    with pytest.raises(TypeError, match="owner-constructed"):
        CapabilityComponentAdmission()
    with pytest.raises(TypeError, match="Binding-constructed"):
        CapabilityOwnerComponentValue()
    with pytest.raises(CapabilityComponentAdmissionError) as rejected:
        authority.admit(
            replace(candidate, component_id="unlisted"),
            issued_at=10,
            expires_at=100,
        )
    assert rejected.value.code == "component_not_allowed"


def test_plugin_component_binding_identity_includes_verified_symbol_and_lock() -> None:
    base = CapabilityComponentBindingSpec(
        source_kind="plugin",
        source_id="example.plugin",
        contribution_id="resource:source",
        source_revision_ref="example.plugin@4",
        content_digest=_digest("package-r4"),
        plugin_id="example.plugin",
        dependency_lock_digest=_digest("lock-r4"),
        factory_path="components/source.py",
        factory_symbol="create_source",
        disposer_path="components/source.py",
        disposer_symbol="dispose_source",
    )
    changed_symbol = replace(base, factory_symbol="create_other_source")

    assert base.fingerprint != changed_symbol.fingerprint
    with pytest.raises(TypeError, match="dependency lock digest"):
        replace(base, dependency_lock_digest=None)
    with pytest.raises(ValueError, match="must not carry Plugin locators"):
        replace(base, source_kind="first_party")


def test_product_selection_preserves_explicit_aggregate_order_and_rejects_stale() -> None:
    resolved, authority = _resolved(("alternate", "native"))

    assert [item.component_id for item in resolved.components] == [
        "alternate",
        "native",
    ]
    assert [item.selection_ordinal for item in resolved.components] == [0, 1]
    with pytest.raises(TypeError, match="resolver-constructed"):
        ResolvedCapabilityComponentSet()

    admission = authority.admit(
        _candidate(authority.definition, "native", revision="expired"),
        issued_at=10,
        expires_at=20,
    )
    plan = CapabilityComponentSelectionPlan(
        product_id="coding",
        scope_id="workspace:test",
        capability_id="resource.catalog",
        owner_id="resource",
        product_policy_revision="coding-policy-v1",
        choices=(
            CapabilityComponentSelectionChoice(
                component_kind="resource.source",
                admission_fingerprints=(admission.fingerprint,),
            ),
        ),
    )
    with pytest.raises(CapabilityComponentSelectionError) as stale:
        ProductCapabilityComponentResolver().resolve(
            plan,
            definitions=(authority.definition,),
            admissions=(admission,),
            owner_snapshots=(authority.snapshot(),),
            now=20,
        )
    assert stale.value.code == "component_admission_not_current"


def test_generation_publication_pins_old_value_until_exact_lease_drains() -> None:
    asyncio.run(_generation_publication_pins_old_value_until_exact_lease_drains())


async def _generation_publication_pins_old_value_until_exact_lease_drains() -> None:
    runtime = CapabilityOwnerComponentRuntime(
        capability_id="resource.catalog",
        owner_id="resource",
        product_id="coding",
        runtime_id="runtime-test",
    )
    binder = CapabilityOwnerComponentBinder()
    events: list[str] = []
    first, _ = _resolved(("native",), revision="builtin-r1")
    first_result = await binder.bind(
        runtime,
        first,
        _bindings(first, events, payload_suffix="v1"),
    )
    old_lease = runtime.capture_one("resource.source")
    second, _ = _resolved(("native",), revision="builtin-r2")

    second_result = await binder.bind(
        runtime,
        second,
        _bindings(second, events, payload_suffix="v2"),
    )

    assert first_result.snapshot.generation == 1
    assert second_result.snapshot.generation == 2
    assert old_lease.require() == "native:v1"
    assert runtime.has_pending_retirements
    assert "dispose:native:v1" not in events
    assert await old_lease.aclose() == ()
    assert "dispose:native:v1" in events
    assert not runtime.has_pending_retirements

    current = runtime.capture_one("resource.source")
    assert current.require() == "native:v2"
    assert await binder.dispose(runtime) == ()
    assert "dispose:native:v2" not in events
    assert await current.aclose() == ()
    assert events[-1] == "dispose:native:v2"


def test_failed_generation_reverse_rolls_back_without_publication() -> None:
    asyncio.run(_failed_generation_reverse_rolls_back_without_publication())


async def _failed_generation_reverse_rolls_back_without_publication() -> None:
    resolved, _ = _resolved(("native", "alternate", "third"))
    runtime = CapabilityOwnerComponentRuntime(
        capability_id="resource.catalog",
        owner_id="resource",
        product_id="coding",
        runtime_id="runtime-test",
    )
    events: list[str] = []

    with pytest.raises(CapabilityOwnerComponentBindingError) as failed:
        await CapabilityOwnerComponentBinder().bind(
            runtime,
            resolved,
            _bindings(
                resolved,
                events,
                payload_suffix="failed",
                fail_component="third",
            ),
        )

    assert failed.value.diagnostic_codes == ("component_construction_failed",)
    assert runtime.generation == 0
    assert runtime.snapshot is None
    assert events == [
        "create:native:failed",
        "create:alternate:failed",
        "create:third:failed",
        "dispose:alternate:failed",
        "dispose:native:failed",
    ]


def test_payload_validation_failure_disposes_before_rejecting_generation() -> None:
    asyncio.run(_payload_validation_failure_disposes_before_rejecting_generation())


async def _payload_validation_failure_disposes_before_rejecting_generation() -> None:
    resolved, _ = _resolved(("native",))
    component = resolved.components[0]
    runtime = CapabilityOwnerComponentRuntime(
        capability_id="resource.catalog",
        owner_id="resource",
        product_id="coding",
        runtime_id="runtime-test",
    )
    events: list[str] = []
    binding = CapabilityOwnerComponentBinding(
        resolved=component,
        binding_fingerprint=owner_component_binding_fingerprint(component),
        create=lambda _context: object(),
        validate_payload=lambda _payload: (_ for _ in ()).throw(
            TypeError("invalid payload")
        ),
        dispose=lambda value: events.append(
            f"dispose:{value.component_id}:g{value.owner_generation}"
        ),
    )

    with pytest.raises(CapabilityOwnerComponentBindingError):
        await CapabilityOwnerComponentBinder().bind(runtime, resolved, (binding,))

    assert runtime.snapshot is None
    assert events == ["dispose:native:g1"]


def test_failed_retirement_is_retained_for_exact_retry() -> None:
    asyncio.run(_failed_retirement_is_retained_for_exact_retry())


async def _failed_retirement_is_retained_for_exact_retry() -> None:
    runtime = CapabilityOwnerComponentRuntime(
        capability_id="resource.catalog",
        owner_id="resource",
        product_id="coding",
        runtime_id="runtime-test",
    )
    binder = CapabilityOwnerComponentBinder()
    first, _ = _resolved(("native",), revision="builtin-r1")
    component = first.components[0]
    attempts = 0

    def retry_once(_value):  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("retry")

    first_binding = CapabilityOwnerComponentBinding(
        resolved=component,
        binding_fingerprint=owner_component_binding_fingerprint(component),
        create=lambda _context: "native:v1",
        validate_payload=lambda _payload: None,
        dispose=retry_once,
    )
    await binder.bind(runtime, first, (first_binding,))
    second, _ = _resolved(("native",), revision="builtin-r2")

    replaced = await binder.bind(
        runtime,
        second,
        _bindings(second, [], payload_suffix="v2"),
    )

    assert replaced.retirement_diagnostic_codes == (
        "component_retirement_failed",
    )
    assert runtime.has_pending_retirements
    assert await binder.drain(runtime) == ()
    assert attempts == 2
    assert not runtime.has_pending_retirements
    assert await binder.dispose(runtime) == ()


def test_cancelled_generation_rolls_back_constructed_values() -> None:
    asyncio.run(_cancelled_generation_rolls_back_constructed_values())


async def _cancelled_generation_rolls_back_constructed_values() -> None:
    resolved, _ = _resolved(("native", "alternate"))
    runtime = CapabilityOwnerComponentRuntime(
        capability_id="resource.catalog",
        owner_id="resource",
        product_id="coding",
        runtime_id="runtime-test",
    )
    events: list[str] = []
    blocked = asyncio.Event()
    bindings = list(_bindings(resolved, events, payload_suffix="cancelled"))
    alternate = resolved.components[1]

    async def wait_forever(_context):  # type: ignore[no-untyped-def]
        blocked.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    bindings[1] = CapabilityOwnerComponentBinding(
        resolved=alternate,
        binding_fingerprint=owner_component_binding_fingerprint(alternate),
        create=wait_forever,
        validate_payload=lambda _payload: None,
        dispose=lambda _value: events.append("dispose:alternate:cancelled"),
    )
    task = asyncio.create_task(
        CapabilityOwnerComponentBinder().bind(runtime, resolved, tuple(bindings))
    )
    await blocked.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.generation == 0
    assert events == [
        "create:native:cancelled",
        "dispose:native:cancelled",
    ]
