from __future__ import annotations

import asyncio

import pytest

from loushang.harness.runtime import (
    AGENT_TRANSCRIPT_PROFILE_SLOT,
    COMMAND_PACKS_SLOT,
    CONTEXT_COMPACTION_SLOT,
    CONTINUITY_PROVIDER_PACKS_SLOT,
    CONVERSATION_STORE_SLOT,
    PROMPT_SECTIONS_SLOT,
    RESOURCE_RUNTIME_SLOT,
    SIDE_QUESTION_PROVIDER_SLOT,
    SKILL_ACTIVATION_SLOT,
    TOOL_PACKS_SLOT,
    ProductRuntimePlan,
    RuntimeCapabilityBindingError,
    RuntimeCapabilityImplementation,
    RuntimeCapabilityRegistry,
    RuntimeCapabilitySelection,
    RuntimeCapabilitySlot,
    RuntimeProfileAdmissionPolicy,
    RuntimeProfileBinder,
    RuntimeProfileLayer,
    RuntimeProfileLayerGrant,
    RuntimeProfileResolutionError,
    RuntimeProfileResolver,
    RuntimeProfileSnapshot,
    SealedRuntimeCapabilityError,
    standard_capability_composition_slots,
    standard_runtime_capability_slots,
)


def _agent_plan(
    *,
    store_implementation: str = "memory",
    compaction_config: dict[str, object] | None = None,
) -> ProductRuntimePlan:
    return ProductRuntimePlan(
        product_id="research",
        slots=(
            CONVERSATION_STORE_SLOT,
            AGENT_TRANSCRIPT_PROFILE_SLOT,
            CONTEXT_COMPACTION_SLOT,
        ),
        defaults=(
            RuntimeCapabilitySelection(
                slot="conversation.store",
                implementation=store_implementation,
                implementation_version=1,
                config={"namespace": "research"},
            ),
            RuntimeCapabilitySelection(
                slot="agent.transcript_profile",
                implementation="agent-v3",
                implementation_version=1,
            ),
            RuntimeCapabilitySelection(
                slot="context.compaction",
                implementation="adaptive",
                implementation_version=1,
                config=compaction_config or {"reserve": 1024},
            ),
        ),
    )


def test_resolver_applies_source_precedence_and_preserves_snapshot_provenance() -> None:
    profile = RuntimeProfileResolver().resolve(
        _agent_plan(),
        layers=(
            RuntimeProfileLayer(
                source="extension",
                layer_id="extension:citations",
                selections=(
                    RuntimeCapabilitySelection(
                        slot="context.compaction",
                        implementation="adaptive",
                        implementation_version=1,
                        config={"reserve": 2048, "preserveCitations": True},
                    ),
                ),
            ),
            RuntimeProfileLayer(
                source="oem",
                layer_id="oem:durable-store",
                selections=(
                    RuntimeCapabilitySelection(
                        slot="conversation.store",
                        implementation="file",
                        implementation_version=1,
                        config={"root": "/sessions"},
                    ),
                ),
            ),
        ),
    )

    store = profile.capability("conversation.store").selections
    compaction = profile.capability("context.compaction").selections

    assert store[0].selection.implementation == "file"
    assert store[0].source == "oem"
    assert compaction[0].selection.config == {
        "reserve": 2048,
        "preserveCitations": True,
    }
    assert compaction[0].source == "extension"

    snapshot = RuntimeProfileSnapshot.from_json(profile.snapshot().to_json())
    assert snapshot.to_json() == profile.snapshot().to_json()
    assert snapshot.capabilities[0].selections[0].source == "oem"


def test_resolver_rejects_undeclared_and_unauthorized_layers_with_diagnostics() -> None:
    with pytest.raises(RuntimeProfileResolutionError) as exc_info:
        RuntimeProfileResolver().resolve(
            _agent_plan(),
            layers=(
                RuntimeProfileLayer(
                    source="session",
                    layer_id="session:unsafe-store",
                    selections=(
                        RuntimeCapabilitySelection(
                            slot="conversation.store",
                            implementation="redis",
                            implementation_version=1,
                        ),
                    ),
                ),
                RuntimeProfileLayer(
                    source="extension",
                    layer_id="extension:unknown",
                    selections=(
                        RuntimeCapabilitySelection(
                            slot="unknown.capability",
                            implementation="unknown",
                            implementation_version=1,
                        ),
                    ),
                ),
            ),
        )

    assert {diagnostic.code for diagnostic in exc_info.value.diagnostics} == {
        "source_not_allowed",
        "unknown_slot",
    }


def test_exclusive_replacement_uses_runtime_profile_precedence() -> None:
    profile = RuntimeProfileResolver().resolve(
        _agent_plan(),
        layers=(
            RuntimeProfileLayer(
                source="session",
                layer_id="session:compact",
                selections=(
                    RuntimeCapabilitySelection(
                        slot="context.compaction",
                        implementation="session-compact",
                        implementation_version=1,
                    ),
                ),
            ),
            RuntimeProfileLayer(
                source="extension",
                layer_id="extension:compact",
                selections=(
                    RuntimeCapabilitySelection(
                        slot="context.compaction",
                        implementation="extension-compact",
                        implementation_version=1,
                    ),
                ),
            ),
        ),
    )

    selected = profile.capability("context.compaction").selections
    assert len(selected) == 1
    assert selected[0].selection.implementation == "session-compact"
    assert selected[0].source == "session"


def test_ordered_replaces_same_identity_while_append_only_keeps_every_contribution() -> (
    None
):
    ordered_slot = RuntimeCapabilitySlot(
        key="prompt.sections",
        shape="ordered",
        scope="session",
        refresh_boundary="sealed",
        allowed_sources=frozenset({"product", "extension"}),
        variation_semantic="aggregate_contribution",
    )
    append_slot = RuntimeCapabilitySlot(
        key="audit.observers",
        shape="append_only",
        scope="session",
        refresh_boundary="sealed",
        allowed_sources=frozenset({"product", "extension"}),
        variation_semantic="aggregate_contribution",
    )
    interceptor_slot = RuntimeCapabilitySlot(
        key="policy.interceptors",
        shape="ordered",
        scope="session",
        refresh_boundary="sealed",
        allowed_sources=frozenset({"product", "extension"}),
        variation_semantic="ordered_interception",
    )
    plan = ProductRuntimePlan(
        product_id="research",
        slots=(ordered_slot, append_slot, interceptor_slot),
        defaults=(
            RuntimeCapabilitySelection(
                slot="prompt.sections",
                implementation="sources",
                implementation_version=1,
                config={"title": "Sources"},
            ),
            RuntimeCapabilitySelection(
                slot="audit.observers",
                implementation="history",
                implementation_version=1,
            ),
            RuntimeCapabilitySelection(
                slot="policy.interceptors",
                implementation="authorization",
                implementation_version=1,
            ),
        ),
    )

    profile = RuntimeProfileResolver().resolve(
        plan,
        layers=(
            RuntimeProfileLayer(
                source="extension",
                layer_id="extension:citations",
                selections=(
                    RuntimeCapabilitySelection(
                        slot="prompt.sections",
                        implementation="sources",
                        implementation_version=1,
                        config={"title": "Cited sources"},
                    ),
                    RuntimeCapabilitySelection(
                        slot="audit.observers",
                        implementation="history",
                        implementation_version=1,
                    ),
                    RuntimeCapabilitySelection(
                        slot="policy.interceptors",
                        implementation="tracing",
                        implementation_version=1,
                    ),
                ),
            ),
        ),
    )

    assert profile.capability("prompt.sections").selections[0].selection.config == {
        "title": "Cited sources"
    }
    assert len(profile.capability("audit.observers").selections) == 2
    assert [
        selection.selection.implementation
        for selection in profile.capability("policy.interceptors").selections
    ] == ["authorization", "tracing"]


def test_failed_external_replacement_does_not_implicitly_bind_product_baseline() -> (
    None
):
    created: list[str] = []

    def create_product(
        selection: RuntimeCapabilitySelection,
        context: object | None,
    ) -> str:
        del context
        created.append(selection.implementation)
        return selection.implementation

    plan = ProductRuntimePlan(
        product_id="research",
        slots=(CONVERSATION_STORE_SLOT,),
        defaults=(
            RuntimeCapabilitySelection(
                slot="conversation.store",
                implementation="product-store",
                implementation_version=1,
            ),
        ),
    )
    profile = RuntimeProfileResolver().resolve(
        plan,
        layers=(
            RuntimeProfileLayer(
                source="oem",
                layer_id="oem:store",
                selections=(
                    RuntimeCapabilitySelection(
                        slot="conversation.store",
                        implementation="oem-store",
                        implementation_version=1,
                    ),
                ),
            ),
        ),
    )
    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            (
                RuntimeCapabilityImplementation(
                    slot="conversation.store",
                    implementation="product-store",
                    implementation_version=1,
                    create=create_product,
                ),
            )
        )
    )

    with pytest.raises(RuntimeCapabilityBindingError, match="oem-store"):
        binder.bind_sync(profile)
    assert created == []


def test_runtime_capability_registry_duplicate_compatibility_baseline() -> None:
    def create(
        selection: RuntimeCapabilitySelection,
        context: object | None,
    ) -> object:
        del selection, context
        return object()

    first = RuntimeCapabilityImplementation(
        slot="conversation.store",
        implementation="memory",
        implementation_version=1,
        create=create,
    )
    duplicate_key = RuntimeCapabilityImplementation(
        slot="conversation.store",
        implementation="memory",
        implementation_version=1,
        create=lambda selection, context: (selection, context),
    )
    registry = RuntimeCapabilityRegistry()

    assert registry.register(first) is None
    with pytest.raises(
        ValueError,
        match="runtime capability implementation already registered",
    ):
        registry.register(duplicate_key)


def test_binder_refreshes_turn_safe_slots_and_invalidates_prior_leases() -> None:
    calls: list[tuple[str, object]] = []

    async def create(selection: RuntimeCapabilitySelection, context: object) -> str:
        calls.append(("create", (selection.slot, selection.config, context)))
        return f"{selection.slot}:{selection.config}"

    async def dispose(value: object, context: object) -> None:
        calls.append(("dispose", (value, context)))

    registry = RuntimeCapabilityRegistry(
        (
            RuntimeCapabilityImplementation(
                slot="conversation.store",
                implementation="memory",
                implementation_version=1,
                create=create,
                dispose=dispose,
            ),
            RuntimeCapabilityImplementation(
                slot="agent.transcript_profile",
                implementation="agent-v3",
                implementation_version=1,
                create=create,
                dispose=dispose,
            ),
            RuntimeCapabilityImplementation(
                slot="context.compaction",
                implementation="adaptive",
                implementation_version=1,
                create=create,
                dispose=dispose,
            ),
        )
    )
    resolver = RuntimeProfileResolver()
    original = resolver.resolve(_agent_plan())
    refreshed = resolver.resolve(_agent_plan(compaction_config={"reserve": 2048}))
    binder = RuntimeProfileBinder(registry)

    async def scenario() -> None:
        binding = await binder.bind(original, context="session-1")
        lease = binding.capture()
        await binder.rebind(binding, refreshed)

        assert binding.value("context.compaction") == (
            "context.compaction:{'reserve': 2048}"
        )
        assert lease.is_current is False
        with pytest.raises(RuntimeError, match="refreshed"):
            lease.require()

        await binder.dispose(binding)
        assert binding.is_closed is True

    asyncio.run(scenario())

    assert calls == [
        ("create", ("conversation.store", {"namespace": "research"}, "session-1")),
        ("create", ("agent.transcript_profile", {}, "session-1")),
        ("create", ("context.compaction", {"reserve": 1024}, "session-1")),
        ("create", ("context.compaction", {"reserve": 2048}, "session-1")),
        (
            "dispose",
            ("context.compaction:{'reserve': 1024}", "session-1"),
        ),
        (
            "dispose",
            ("context.compaction:{'reserve': 2048}", "session-1"),
        ),
        ("dispose", ("agent.transcript_profile:{}", "session-1")),
        (
            "dispose",
            ("conversation.store:{'namespace': 'research'}", "session-1"),
        ),
    ]


def test_binder_rejects_sealed_store_replacement_before_creating_a_new_value() -> None:
    registry = RuntimeCapabilityRegistry()
    binder = RuntimeProfileBinder(registry)

    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(_agent_plan())
        with pytest.raises(RuntimeCapabilityBindingError, match="conversation.store"):
            await binder.bind(profile)

    asyncio.run(scenario())

    # Resolution-level sealing is enforced before a replacement factory is
    # consulted.  Use factories only for the initial binding below.
    created: list[str] = []

    def create(selection: RuntimeCapabilitySelection, context: object) -> str:
        del context
        created.append(selection.implementation)
        return selection.implementation

    for selection in _agent_plan().defaults:
        registry.register(
            RuntimeCapabilityImplementation(
                slot=selection.slot,
                implementation=selection.implementation,
                implementation_version=selection.implementation_version,
                create=create,
            )
        )

    async def sealed_scenario() -> None:
        binding = await binder.bind(RuntimeProfileResolver().resolve(_agent_plan()))
        replacement = RuntimeProfileResolver().resolve(
            _agent_plan(store_implementation="file")
        )
        with pytest.raises(SealedRuntimeCapabilityError, match="conversation.store"):
            await binder.rebind(binding, replacement)
        assert binding.value("conversation.store") == "memory"

    asyncio.run(sealed_scenario())
    assert created == ["memory", "agent-v3", "adaptive"]


def test_turn_rebind_factory_failure_keeps_the_previous_binding_and_lease() -> None:
    def create(selection: RuntimeCapabilitySelection, context: object | None) -> str:
        del context
        if (
            selection.slot == "context.compaction"
            and selection.config["reserve"] == 2048
        ):
            raise RuntimeError("replacement backend is unavailable")
        return (
            f"{selection.slot}:{selection.config['reserve']}"
            if selection.slot == "context.compaction"
            else selection.slot
        )

    registry = RuntimeCapabilityRegistry(
        tuple(
            RuntimeCapabilityImplementation(
                slot=selection.slot,
                implementation=selection.implementation,
                implementation_version=selection.implementation_version,
                create=create,
            )
            for selection in _agent_plan().defaults
        )
    )
    resolver = RuntimeProfileResolver()
    binder = RuntimeProfileBinder(registry)

    async def scenario() -> None:
        binding = await binder.bind(resolver.resolve(_agent_plan()))
        lease = binding.capture()
        with pytest.raises(RuntimeCapabilityBindingError, match="context.compaction"):
            await binder.rebind(
                binding,
                resolver.resolve(_agent_plan(compaction_config={"reserve": 2048})),
            )
        assert binding.value("context.compaction") == "context.compaction:1024"
        assert lease.is_current is True
        assert lease.require().profile is binding.profile

    asyncio.run(scenario())


def test_binder_rolls_back_previously_created_values_when_later_factory_fails() -> None:
    first_slot = RuntimeCapabilitySlot(
        key="first",
        shape="single",
        scope="session",
        refresh_boundary="sealed",
        allowed_sources=frozenset({"product"}),
    )
    second_slot = RuntimeCapabilitySlot(
        key="second",
        shape="single",
        scope="session",
        refresh_boundary="sealed",
        allowed_sources=frozenset({"product"}),
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=(first_slot, second_slot),
            defaults=(
                RuntimeCapabilitySelection(
                    slot="first", implementation="works", implementation_version=1
                ),
                RuntimeCapabilitySelection(
                    slot="second", implementation="fails", implementation_version=1
                ),
            ),
        )
    )
    calls: list[str] = []

    def create_first(selection: RuntimeCapabilitySelection, context: object) -> str:
        del selection, context
        calls.append("create:first")
        return "first"

    def dispose_first(value: object, context: object) -> None:
        del value, context
        calls.append("dispose:first")

    def create_second(selection: RuntimeCapabilitySelection, context: object) -> object:
        del selection, context
        calls.append("create:second")
        raise RuntimeError("no backend")

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            (
                RuntimeCapabilityImplementation(
                    slot="first",
                    implementation="works",
                    implementation_version=1,
                    create=create_first,
                    dispose=dispose_first,
                ),
                RuntimeCapabilityImplementation(
                    slot="second",
                    implementation="fails",
                    implementation_version=1,
                    create=create_second,
                ),
            )
        )
    )

    async def scenario() -> None:
        with pytest.raises(RuntimeCapabilityBindingError, match="second"):
            await binder.bind(profile)

    asyncio.run(scenario())
    assert calls == ["create:first", "create:second", "dispose:first"]


def test_binder_rollback_continues_after_an_individual_disposer_failure() -> None:
    slots = tuple(
        RuntimeCapabilitySlot(
            key=key,
            shape="single",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product"}),
        )
        for key in ("first", "second", "third")
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=slots,
            defaults=tuple(
                RuntimeCapabilitySelection(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                )
                for slot in slots
            ),
        )
    )
    calls: list[str] = []

    def create(selection: RuntimeCapabilitySelection, _context: object) -> str:
        calls.append(f"create:{selection.slot}")
        if selection.slot == "third":
            raise RuntimeError("third factory failed")
        return selection.slot

    def dispose(value: object, _context: object) -> None:
        calls.append(f"dispose:{value}")
        if value == "second":
            raise RuntimeError("second disposer failed")

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            tuple(
                RuntimeCapabilityImplementation(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                    create=create,
                    dispose=dispose,
                )
                for slot in slots
            )
        )
    )

    async def scenario() -> None:
        with pytest.raises(RuntimeCapabilityBindingError, match="third"):
            await binder.bind(profile)

    asyncio.run(scenario())

    assert calls == [
        "create:first",
        "create:second",
        "create:third",
        "dispose:second",
        "dispose:first",
    ]


def test_binder_cancellation_finishes_rollback_before_propagating() -> None:
    slots = tuple(
        RuntimeCapabilitySlot(
            key=key,
            shape="single",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product"}),
        )
        for key in ("first", "second", "blocked")
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=slots,
            defaults=tuple(
                RuntimeCapabilitySelection(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                )
                for slot in slots
            ),
        )
    )
    calls: list[str] = []

    async def scenario() -> None:
        factory_started = asyncio.Event()
        dispose_started = asyncio.Event()
        release_dispose = asyncio.Event()

        async def create(
            selection: RuntimeCapabilitySelection,
            _context: object,
        ) -> str:
            calls.append(f"create:{selection.slot}")
            if selection.slot == "blocked":
                factory_started.set()
                await asyncio.Event().wait()
            return selection.slot

        async def dispose(value: object, _context: object) -> None:
            calls.append(f"dispose:{value}:start")
            if value == "second":
                dispose_started.set()
                await release_dispose.wait()
            calls.append(f"dispose:{value}:end")

        binder = RuntimeProfileBinder(
            RuntimeCapabilityRegistry(
                tuple(
                    RuntimeCapabilityImplementation(
                        slot=slot.key,
                        implementation=slot.key,
                        implementation_version=1,
                        create=create,
                        dispose=dispose,
                    )
                    for slot in slots
                )
            )
        )
        binding_task = asyncio.create_task(binder.bind(profile))
        await factory_started.wait()
        binding_task.cancel()
        await dispose_started.wait()
        binding_task.cancel()
        release_dispose.set()

        with pytest.raises(asyncio.CancelledError):
            await binding_task

    asyncio.run(scenario())

    assert calls == [
        "create:first",
        "create:second",
        "create:blocked",
        "dispose:second:start",
        "dispose:second:end",
        "dispose:first:start",
        "dispose:first:end",
    ]


def test_turn_rebind_candidate_cancellation_keeps_old_generation_callable() -> None:
    slots = tuple(
        RuntimeCapabilitySlot(
            key=key,
            shape="single",
            scope="session",
            refresh_boundary="turn",
            allowed_sources=frozenset({"product"}),
        )
        for key in ("first", "second")
    )

    def profile(generation: int):
        return RuntimeProfileResolver().resolve(
            ProductRuntimePlan(
                product_id="research",
                slots=slots,
                defaults=tuple(
                    RuntimeCapabilitySelection(
                        slot=slot.key,
                        implementation=slot.key,
                        implementation_version=1,
                        config={"generation": generation},
                    )
                    for slot in slots
                ),
            )
        )

    calls: list[str] = []

    async def scenario() -> None:
        blocked = asyncio.Event()

        async def create(
            selection: RuntimeCapabilitySelection,
            _context: object,
        ) -> str:
            generation = selection.config["generation"]
            calls.append(f"create:{selection.slot}:{generation}")
            if selection.slot == "second" and generation == 2:
                blocked.set()
                await asyncio.Event().wait()
            return f"{selection.slot}:{generation}"

        async def dispose(value: object, _context: object) -> None:
            calls.append(f"dispose:{value}")

        binder = RuntimeProfileBinder(
            RuntimeCapabilityRegistry(
                tuple(
                    RuntimeCapabilityImplementation(
                        slot=slot.key,
                        implementation=slot.key,
                        implementation_version=1,
                        create=create,
                        dispose=dispose,
                    )
                    for slot in slots
                )
            )
        )
        binding = await binder.bind(profile(1))
        old_lease = binding.capture()
        rebind_task = asyncio.create_task(binder.rebind(binding, profile(2)))
        await blocked.wait()
        rebind_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await rebind_task

        assert binding.value("first") == "first:1"
        assert binding.value("second") == "second:1"
        assert old_lease.is_current is True

    asyncio.run(scenario())

    assert calls == [
        "create:first:1",
        "create:second:1",
        "create:first:2",
        "create:second:2",
        "dispose:first:2",
    ]


def test_turn_rebind_retirement_failure_keeps_the_replacement_callable() -> None:
    slot = RuntimeCapabilitySlot(
        key="turn.value",
        shape="single",
        scope="session",
        refresh_boundary="turn",
        allowed_sources=frozenset({"product"}),
    )

    def profile(generation: int):
        return RuntimeProfileResolver().resolve(
            ProductRuntimePlan(
                product_id="research",
                slots=(slot,),
                defaults=(
                    RuntimeCapabilitySelection(
                        slot=slot.key,
                        implementation="value",
                        implementation_version=1,
                        config={"generation": generation},
                    ),
                ),
            )
        )

    def create(
        selection: RuntimeCapabilitySelection,
        _context: object,
    ) -> dict[str, object]:
        return {"generation": selection.config["generation"], "closed": False}

    def dispose(value: object, _context: object) -> None:
        assert isinstance(value, dict)
        value["closed"] = True
        if value["generation"] == 1:
            raise RuntimeError("old generation retirement failed")

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            (
                RuntimeCapabilityImplementation(
                    slot=slot.key,
                    implementation="value",
                    implementation_version=1,
                    create=create,
                    dispose=dispose,
                ),
            )
        )
    )

    async def scenario() -> None:
        binding = await binder.bind(profile(1))
        old_lease = binding.capture()

        with pytest.raises(RuntimeCapabilityBindingError, match="disposer failed"):
            await binder.rebind(binding, profile(2))

        assert binding.value(slot.key) == {"generation": 2, "closed": False}
        assert binding.profile == profile(2)
        assert old_lease.is_current is False

    asyncio.run(scenario())


def test_binder_dispose_finishes_all_entries_before_propagating_cancellation() -> None:
    slots = tuple(
        RuntimeCapabilitySlot(
            key=key,
            shape="single",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product"}),
        )
        for key in ("first", "second")
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=slots,
            defaults=tuple(
                RuntimeCapabilitySelection(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                )
                for slot in slots
            ),
        )
    )
    calls: list[str] = []

    async def scenario() -> None:
        dispose_started = asyncio.Event()
        release_dispose = asyncio.Event()

        async def dispose(value: object, _context: object) -> None:
            calls.append(f"dispose:{value}:start")
            if value == "second":
                dispose_started.set()
                await release_dispose.wait()
            calls.append(f"dispose:{value}:end")

        binder = RuntimeProfileBinder(
            RuntimeCapabilityRegistry(
                tuple(
                    RuntimeCapabilityImplementation(
                        slot=slot.key,
                        implementation=slot.key,
                        implementation_version=1,
                        create=lambda selection, _context: selection.slot,
                        dispose=dispose,
                    )
                    for slot in slots
                )
            )
        )
        binding = await binder.bind(profile)
        dispose_task = asyncio.create_task(binder.dispose(binding))
        await dispose_started.wait()
        dispose_task.cancel()
        release_dispose.set()

        with pytest.raises(asyncio.CancelledError):
            await dispose_task

        assert binding.is_closed is True

    asyncio.run(scenario())

    assert calls == [
        "dispose:second:start",
        "dispose:second:end",
        "dispose:first:start",
        "dispose:first:end",
    ]


def test_binder_retires_entries_in_reverse_actual_creation_order_across_rebinds() -> (
    None
):
    slots = tuple(
        RuntimeCapabilitySlot(
            key=key,
            shape="single",
            scope="session",
            refresh_boundary="turn",
            allowed_sources=frozenset({"product"}),
        )
        for key in ("z-last-key", "a-first-key")
    )

    def profile(*, z_generation: int, a_generation: int):
        generations = {
            "z-last-key": z_generation,
            "a-first-key": a_generation,
        }
        return RuntimeProfileResolver().resolve(
            ProductRuntimePlan(
                product_id="research",
                slots=slots,
                defaults=tuple(
                    RuntimeCapabilitySelection(
                        slot=slot.key,
                        implementation=slot.key,
                        implementation_version=1,
                        config={"generation": generations[slot.key]},
                    )
                    for slot in slots
                ),
            )
        )

    calls: list[str] = []

    def create(selection: RuntimeCapabilitySelection, _context: object) -> str:
        value = f"{selection.slot}:{selection.config['generation']}"
        calls.append(f"create:{value}")
        return value

    def dispose(value: object, _context: object) -> None:
        calls.append(f"dispose:{value}")

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            tuple(
                RuntimeCapabilityImplementation(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                    create=create,
                    dispose=dispose,
                )
                for slot in slots
            )
        )
    )

    async def scenario() -> None:
        binding = await binder.bind(profile(z_generation=1, a_generation=1))
        await binder.rebind(binding, profile(z_generation=2, a_generation=2))
        await binder.rebind(binding, profile(z_generation=3, a_generation=2))
        await binder.dispose(binding)

    asyncio.run(scenario())

    assert calls == [
        "create:z-last-key:1",
        "create:a-first-key:1",
        "create:z-last-key:2",
        "create:a-first-key:2",
        "dispose:a-first-key:1",
        "dispose:z-last-key:1",
        "create:z-last-key:3",
        "dispose:z-last-key:2",
        "dispose:z-last-key:3",
        "dispose:a-first-key:2",
    ]


def test_concurrent_binder_dispose_joins_once_and_invalidates_reads_immediately() -> (
    None
):
    slot = RuntimeCapabilitySlot(
        key="entry",
        shape="single",
        scope="session",
        refresh_boundary="sealed",
        allowed_sources=frozenset({"product"}),
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=(slot,),
            defaults=(
                RuntimeCapabilitySelection(
                    slot=slot.key,
                    implementation="entry",
                    implementation_version=1,
                ),
            ),
        )
    )
    calls: list[str] = []

    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def dispose(value: object, _context: object) -> None:
            calls.append(f"start:{value}")
            started.set()
            await release.wait()
            calls.append(f"end:{value}")

        binder = RuntimeProfileBinder(
            RuntimeCapabilityRegistry(
                (
                    RuntimeCapabilityImplementation(
                        slot=slot.key,
                        implementation="entry",
                        implementation_version=1,
                        create=lambda _selection, _context: "value",
                        dispose=dispose,
                    ),
                )
            )
        )
        binding = await binder.bind(profile)
        lease = binding.capture()
        first = asyncio.create_task(binder.dispose(binding))
        await started.wait()

        assert binding.is_closed is True
        assert lease.is_current is False
        with pytest.raises(RuntimeError, match="disposed"):
            lease.require()
        with pytest.raises(RuntimeError, match="closed"):
            binding.value(slot.key)

        second = asyncio.create_task(binder.dispose(binding))
        await asyncio.sleep(0)
        assert calls == ["start:value"]
        release.set()
        await asyncio.gather(first, second)
        await binder.dispose(binding)
        binder.dispose_sync(binding)

    asyncio.run(scenario())

    assert calls == ["start:value", "end:value"]


def test_binder_cancellation_preserves_concurrent_cleanup_failure_diagnostics() -> None:
    slot = RuntimeCapabilitySlot(
        key="entry",
        shape="single",
        scope="session",
        refresh_boundary="sealed",
        allowed_sources=frozenset({"product"}),
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=(slot,),
            defaults=(
                RuntimeCapabilitySelection(
                    slot=slot.key,
                    implementation="entry",
                    implementation_version=1,
                ),
            ),
        )
    )

    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def dispose(_value: object, _context: object) -> None:
            started.set()
            await release.wait()
            raise RuntimeError("cleanup boom")

        binder = RuntimeProfileBinder(
            RuntimeCapabilityRegistry(
                (
                    RuntimeCapabilityImplementation(
                        slot=slot.key,
                        implementation="entry",
                        implementation_version=1,
                        create=lambda _selection, _context: "value",
                        dispose=dispose,
                    ),
                )
            )
        )
        binding = await binder.bind(profile)
        disposing = asyncio.create_task(binder.dispose(binding))
        await started.wait()
        disposing.cancel("shutdown cancelled")
        await asyncio.sleep(0)
        disposing.cancel("shutdown cancelled again")
        release.set()

        with pytest.raises(asyncio.CancelledError) as exc_info:
            await disposing

        assert any(
            "capability disposer failed" in note
            for note in getattr(exc_info.value, "__notes__", ())
        )

    asyncio.run(scenario())


def test_turn_rebind_retirement_cancellation_keeps_published_generation() -> None:
    slot = RuntimeCapabilitySlot(
        key="turn.value",
        shape="single",
        scope="session",
        refresh_boundary="turn",
        allowed_sources=frozenset({"product"}),
    )

    def profile(generation: int):
        return RuntimeProfileResolver().resolve(
            ProductRuntimePlan(
                product_id="research",
                slots=(slot,),
                defaults=(
                    RuntimeCapabilitySelection(
                        slot=slot.key,
                        implementation="value",
                        implementation_version=1,
                        config={"generation": generation},
                    ),
                ),
            )
        )

    async def scenario() -> None:
        retirement_started = asyncio.Event()
        release_retirement = asyncio.Event()

        async def dispose(value: object, _context: object) -> None:
            if value == 1:
                retirement_started.set()
                await release_retirement.wait()

        binder = RuntimeProfileBinder(
            RuntimeCapabilityRegistry(
                (
                    RuntimeCapabilityImplementation(
                        slot=slot.key,
                        implementation="value",
                        implementation_version=1,
                        create=lambda selection, _context: selection.config[
                            "generation"
                        ],
                        dispose=dispose,
                    ),
                )
            )
        )
        binding = await binder.bind(profile(1))
        old_lease = binding.capture()
        rebind = asyncio.create_task(binder.rebind(binding, profile(2)))
        await retirement_started.wait()

        assert binding.value(slot.key) == 2
        assert old_lease.is_current is False
        rebind.cancel("retirement cancelled")
        release_retirement.set()
        with pytest.raises(asyncio.CancelledError):
            await rebind
        assert binding.value(slot.key) == 2

    asyncio.run(scenario())


def test_sync_binder_cleanup_continues_after_disposer_failure() -> None:
    slots = tuple(
        RuntimeCapabilitySlot(
            key=key,
            shape="single",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product"}),
        )
        for key in ("first", "second")
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=slots,
            defaults=tuple(
                RuntimeCapabilitySelection(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                )
                for slot in slots
            ),
        )
    )
    calls: list[str] = []

    def dispose(value: object, _context: object) -> None:
        calls.append(f"dispose:{value}")
        if value == "second":
            raise RuntimeError("second cleanup failed")

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            tuple(
                RuntimeCapabilityImplementation(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                    create=lambda selection, _context: selection.slot,
                    dispose=dispose,
                )
                for slot in slots
            )
        )
    )
    binding = binder.bind_sync(profile)

    with pytest.raises(RuntimeCapabilityBindingError, match="second"):
        binder.dispose_sync(binding)

    assert calls == ["dispose:second", "dispose:first"]
    assert binding.is_closed is True


def test_async_binder_cleanup_continues_after_disposer_failure() -> None:
    slots = tuple(
        RuntimeCapabilitySlot(
            key=key,
            shape="single",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product"}),
        )
        for key in ("first", "second")
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=slots,
            defaults=tuple(
                RuntimeCapabilitySelection(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                )
                for slot in slots
            ),
        )
    )
    calls: list[str] = []

    async def dispose(value: object, _context: object) -> None:
        calls.append(f"dispose:{value}")
        if value == "second":
            raise RuntimeError("second cleanup failed")

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            tuple(
                RuntimeCapabilityImplementation(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                    create=lambda selection, _context: selection.slot,
                    dispose=dispose,
                )
                for slot in slots
            )
        )
    )

    async def scenario() -> None:
        binding = await binder.bind(profile)
        with pytest.raises(RuntimeCapabilityBindingError, match="second"):
            await binder.dispose(binding)
        assert binding.is_closed is True

    asyncio.run(scenario())

    assert calls == ["dispose:second", "dispose:first"]


def test_sync_binder_rollback_continues_after_disposer_failure() -> None:
    slots = tuple(
        RuntimeCapabilitySlot(
            key=key,
            shape="single",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product"}),
        )
        for key in ("first", "second", "third")
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=slots,
            defaults=tuple(
                RuntimeCapabilitySelection(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                )
                for slot in slots
            ),
        )
    )
    calls: list[str] = []

    def create(selection: RuntimeCapabilitySelection, _context: object) -> str:
        calls.append(f"create:{selection.slot}")
        if selection.slot == "third":
            raise RuntimeError("third factory failed")
        return selection.slot

    def dispose(value: object, _context: object) -> None:
        calls.append(f"dispose:{value}")
        if value == "second":
            raise RuntimeError("second cleanup failed")

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            tuple(
                RuntimeCapabilityImplementation(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                    create=create,
                    dispose=dispose,
                )
                for slot in slots
            )
        )
    )

    with pytest.raises(RuntimeCapabilityBindingError, match="third"):
        binder.bind_sync(profile)

    assert calls == [
        "create:first",
        "create:second",
        "create:third",
        "dispose:second",
        "dispose:first",
    ]


def test_binder_attributes_synchronous_disposer_self_cancellation_to_its_entry() -> (
    None
):
    slots = tuple(
        RuntimeCapabilitySlot(
            key=key,
            shape="single",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product"}),
        )
        for key in ("async-first", "cancel-second")
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=slots,
            defaults=tuple(
                RuntimeCapabilitySelection(
                    slot=slot.key,
                    implementation=slot.key,
                    implementation_version=1,
                )
                for slot in slots
            ),
        )
    )
    calls: list[str] = []

    async def dispose_async(_value: object, _context: object) -> None:
        calls.append("async:start")
        await asyncio.sleep(0)
        calls.append("async:end")

    def dispose_cancelling(_value: object, _context: object) -> None:
        calls.append("cancel")
        task = asyncio.current_task()
        assert task is not None
        task.cancel("disposer self-cancelled")

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            (
                RuntimeCapabilityImplementation(
                    slot="async-first",
                    implementation="async-first",
                    implementation_version=1,
                    create=lambda selection, _context: selection.slot,
                    dispose=dispose_async,
                ),
                RuntimeCapabilityImplementation(
                    slot="cancel-second",
                    implementation="cancel-second",
                    implementation_version=1,
                    create=lambda selection, _context: selection.slot,
                    dispose=dispose_cancelling,
                ),
            )
        )
    )

    async def scenario() -> None:
        binding = await binder.bind(profile)
        with pytest.raises(RuntimeCapabilityBindingError) as exc_info:
            await binder.dispose(binding)
        assert exc_info.value.slot == "cancel-second"

    asyncio.run(scenario())

    assert calls == ["cancel", "async:start", "async:end"]


def test_snapshot_rejects_boolean_versions_instead_of_treating_them_as_integers() -> (
    None
):
    with pytest.raises(TypeError, match="schemaVersion"):
        RuntimeProfileSnapshot.from_json(
            {"schemaVersion": True, "productId": "research", "capabilities": []}
        )


def test_snapshot_records_variation_semantics_and_reads_legacy_capabilities() -> None:
    profile_snapshot = RuntimeProfileResolver().resolve(_agent_plan()).snapshot()
    payload = profile_snapshot.to_json()

    capabilities = payload["capabilities"]
    assert isinstance(capabilities, list)
    assert isinstance(capabilities[0], dict)
    assert capabilities[0]["variationSemantic"] == "exclusive_replacement"
    assert RuntimeProfileSnapshot.from_json(payload) == profile_snapshot

    legacy_payload = profile_snapshot.to_json()
    legacy_capabilities = legacy_payload["capabilities"]
    assert isinstance(legacy_capabilities, list)
    for capability in legacy_capabilities:
        assert isinstance(capability, dict)
        capability.pop("variationSemantic")
    legacy_snapshot = RuntimeProfileSnapshot.from_json(legacy_payload)
    assert all(
        capability.variation_semantic is None
        for capability in legacy_snapshot.capabilities
    )


def test_variable_slots_require_shape_compatible_variation_semantics() -> None:
    with pytest.raises(ValueError, match="must declare a variation semantic"):
        RuntimeCapabilitySlot(
            key="replaceable",
            shape="single",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product", "oem"}),
        )

    with pytest.raises(ValueError, match="single or exclusive"):
        RuntimeCapabilitySlot(
            key="invalid-replacement",
            shape="ordered",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product"}),
            variation_semantic="exclusive_replacement",
        )

    with pytest.raises(ValueError, match="ordered or append_only"):
        RuntimeCapabilitySlot(
            key="invalid-aggregate",
            shape="single",
            scope="session",
            refresh_boundary="sealed",
            allowed_sources=frozenset({"product"}),
            variation_semantic="aggregate_contribution",
        )


def test_sync_binder_rejects_async_factories_without_creating_an_event_loop() -> None:
    slot = RuntimeCapabilitySlot(
        key="pure",
        shape="single",
        scope="session",
        refresh_boundary="sealed",
        allowed_sources=frozenset({"product"}),
    )
    profile = RuntimeProfileResolver().resolve(
        ProductRuntimePlan(
            product_id="research",
            slots=(slot,),
            defaults=(
                RuntimeCapabilitySelection(
                    slot="pure",
                    implementation="async-only",
                    implementation_version=1,
                ),
            ),
        )
    )

    async def create_async(
        selection: RuntimeCapabilitySelection,
        context: object | None,
    ) -> object:
        del selection, context
        return object()

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            (
                RuntimeCapabilityImplementation(
                    slot="pure",
                    implementation="async-only",
                    implementation_version=1,
                    create=create_async,
                ),
            )
        )
    )

    with pytest.raises(RuntimeCapabilityBindingError, match="cannot await"):
        binder.bind_sync(profile)


def test_capability_composition_slots_have_deliberate_source_boundaries() -> None:
    slots = {slot.key: slot for slot in standard_capability_composition_slots()}

    assert set(slots) == {
        "resource.runtime",
        "prompt.sections",
        "skill.activation",
        "tool.packs",
        "command.packs",
        "interaction.side_question",
        "continuity.provider_packs",
    }
    assert slots == {
        "resource.runtime": RESOURCE_RUNTIME_SLOT,
        "prompt.sections": PROMPT_SECTIONS_SLOT,
        "skill.activation": SKILL_ACTIVATION_SLOT,
        "tool.packs": TOOL_PACKS_SLOT,
        "command.packs": COMMAND_PACKS_SLOT,
        "interaction.side_question": SIDE_QUESTION_PROVIDER_SLOT,
        "continuity.provider_packs": CONTINUITY_PROVIDER_PACKS_SLOT,
    }
    assert slots["resource.runtime"].allowed_sources == frozenset({"product", "oem"})
    assert slots["tool.packs"].allowed_sources == frozenset(
        {"product", "oem", "extension"}
    )
    assert slots["command.packs"].allowed_sources == frozenset(
        {"product", "oem", "extension"}
    )
    assert slots["interaction.side_question"].allowed_sources == frozenset(
        {"product", "oem", "extension"}
    )
    assert slots["interaction.side_question"].required is False
    assert "session" not in slots["tool.packs"].allowed_sources
    assert slots["continuity.provider_packs"].scope == "process"
    assert slots["continuity.provider_packs"].refresh_boundary == "sealed"
    assert slots["continuity.provider_packs"].allowed_sources == frozenset(
        {"product", "oem"}
    )
    assert slots["prompt.sections"].shape == "single"
    assert slots["tool.packs"].shape == "single"
    assert slots["command.packs"].shape == "single"


def test_standard_slots_have_one_explicit_variation_semantic() -> None:
    slots = {slot.key: slot for slot in standard_runtime_capability_slots()}

    assert {key: slot.variation_semantic for key, slot in slots.items()} == {
        "conversation.store": "exclusive_replacement",
        "agent.transcript_profile": "exclusive_replacement",
        "context.compaction": "exclusive_replacement",
        "resource.runtime": "exclusive_replacement",
        "prompt.sections": "exclusive_replacement",
        "skill.activation": "exclusive_replacement",
        "tool.packs": "exclusive_replacement",
        "command.packs": "exclusive_replacement",
        "interaction.side_question": "exclusive_replacement",
        "continuity.provider_packs": "aggregate_contribution",
    }


def test_admission_requires_an_explicit_grant_and_slot_permission() -> None:
    plan = ProductRuntimePlan(
        product_id="research",
        slots=(PROMPT_SECTIONS_SLOT, TOOL_PACKS_SLOT),
    )
    extension_layer = RuntimeProfileLayer(
        source="extension",
        layer_id="extension:citations",
        selections=(
            RuntimeCapabilitySelection(
                slot="prompt.sections",
                implementation="citations",
                implementation_version=1,
            ),
            RuntimeCapabilitySelection(
                slot="tool.packs",
                implementation="citation-tools",
                implementation_version=1,
            ),
        ),
    )

    untrusted = RuntimeProfileAdmissionPolicy().admit(plan, (extension_layer,))
    assert untrusted.layers == ()
    assert [diagnostic.code for diagnostic in untrusted.diagnostics] == [
        "untrusted_runtime_layer"
    ]

    policy = RuntimeProfileAdmissionPolicy(
        grants=(
            RuntimeProfileLayerGrant(
                source="extension",
                layer_id="extension:citations",
                allowed_slots=frozenset({"prompt.sections", "tool.packs"}),
                granted_permissions=frozenset({"prompt.compose"}),
            ),
        ),
        slot_permissions={"tool.packs": frozenset({"tool.execute"})},
    )
    denied = policy.admit(plan, (extension_layer,))
    assert denied.layers == ()
    assert [diagnostic.code for diagnostic in denied.diagnostics] == [
        "runtime_slot_permission_denied"
    ]

    admitted = RuntimeProfileAdmissionPolicy(
        grants=(
            RuntimeProfileLayerGrant(
                source="extension",
                layer_id="extension:citations",
                allowed_slots=frozenset({"prompt.sections", "tool.packs"}),
                granted_permissions=frozenset({"prompt.compose", "tool.execute"}),
            ),
        ),
        slot_permissions={"tool.packs": frozenset({"tool.execute"})},
    ).admit(plan, (extension_layer,))
    assert admitted.require_valid() == (extension_layer,)


def test_runtime_profile_public_facades_export_the_same_admission_types() -> None:
    import loushang.harness.runtime as runtime_module
    import loushang.harness.runtime.profile as profile_module

    assert (
        runtime_module.RuntimeProfileAdmission is profile_module.RuntimeProfileAdmission
    )
    assert (
        runtime_module.RuntimeProfileAdmissionPolicy
        is profile_module.RuntimeProfileAdmissionPolicy
    )
    assert (
        runtime_module.RuntimeProfileLayerGrant
        is profile_module.RuntimeProfileLayerGrant
    )


def test_admission_leaves_unknown_slots_for_the_resolver_to_diagnose() -> None:
    plan = ProductRuntimePlan(product_id="research", slots=(TOOL_PACKS_SLOT,))
    layer = RuntimeProfileLayer(
        source="extension",
        layer_id="extension:unknown-slot",
        selections=(
            RuntimeCapabilitySelection(
                slot="unknown.capability",
                implementation="unknown",
                implementation_version=1,
            ),
        ),
    )
    policy = RuntimeProfileAdmissionPolicy(
        grants=(
            RuntimeProfileLayerGrant(
                source="extension",
                layer_id="extension:unknown-slot",
                allowed_slots=frozenset(),
            ),
        )
    )

    admitted = policy.admit(plan, (layer,))

    assert admitted.require_valid() == (layer,)
    with pytest.raises(RuntimeProfileResolutionError) as exc_info:
        RuntimeProfileResolver().resolve(plan, layers=admitted.layers)
    assert [diagnostic.code for diagnostic in exc_info.value.diagnostics] == [
        "unknown_slot"
    ]
