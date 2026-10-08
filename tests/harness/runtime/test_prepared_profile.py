from __future__ import annotations

import asyncio

import pytest

from loushang.harness.runtime import (
    ProductRuntimePlan,
    RuntimeCapabilityBindingError,
    RuntimeCapabilityImplementation,
    RuntimeCapabilityRegistry,
    RuntimeCapabilitySelection,
    RuntimeCapabilitySlot,
    RuntimeProfileBinder,
    RuntimeProfileResolver,
)


def setup(create, dispose):
    selections = tuple(
        RuntimeCapabilitySelection(slot=slot, implementation=name, implementation_version=1)
        for slot, name in (("first", "one"), ("first", "two"), ("last", "three"))
    )
    profile = RuntimeProfileResolver().resolve(ProductRuntimePlan(
        product_id="test",
        slots=tuple(RuntimeCapabilitySlot(
            key=key, shape="ordered", scope="session", refresh_boundary="turn",
            allowed_sources=frozenset({"product"}),
            variation_semantic="aggregate_contribution",
        ) for key in ("first", "last")),
        defaults=selections,
    ))
    binder = RuntimeProfileBinder(RuntimeCapabilityRegistry(
        RuntimeCapabilityImplementation(
            slot=s.slot, implementation=s.implementation, implementation_version=1,
            create=create, dispose=dispose,
        ) for s in selections
    ))
    return binder, profile


def test_disposal_publication_failure_keeps_entries_for_retry(monkeypatch):
    async def scenario():
        disposed = []
        binder, profile = setup(lambda s, _: s.implementation, lambda value, _: disposed.append(value))
        binding = await binder.bind(profile)
        loop = asyncio.get_running_loop()

        def reject_task(_loop, _coro, **kwargs):
            raise RuntimeError("test task publication")

        loop.set_task_factory(reject_task)
        try:
            with pytest.raises(RuntimeError, match="test task publication"):
                await binder.dispose(binding)
        finally:
            loop.set_task_factory(None)
        assert disposed == []
        await binder.dispose(binding)
        assert disposed == ["three", "two", "one"]
    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_partial_same_slot_failure_retains_earlier_value(cancel):
    async def scenario():
        created, disposed = [], []

        async def create(selection, _):
            name = selection.implementation
            created.append(name)
            if name == "two":
                if cancel:
                    raise asyncio.CancelledError()
                raise ValueError("second factory")
            return name

        binder, profile = setup(create, lambda value, _: disposed.append(value))
        binding = binder.prepare_binding(profile)
        with pytest.raises(RuntimeError, match="not ready"):
            binding.values()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await binder.bind_prepared(binding)
        else:
            with pytest.raises(RuntimeCapabilityBindingError) as raised:
                await binder.bind_prepared(binding)
            assert raised.value.slot == "first"
            assert raised.value.implementation == "two"
            assert raised.value.implementation_version == 1
            assert isinstance(raised.value.__cause__, ValueError)
        assert created == ["one", "two"] and disposed == []
        with pytest.raises(RuntimeError, match="not ready"):
            binding.capture()
        with pytest.raises(RuntimeError):
            await binder.rebind(binding, profile)
        with pytest.raises(RuntimeError):
            await binder.bind_prepared(binding)
        await binder.dispose(binding)
        assert disposed == ["one"]
    asyncio.run(scenario())


def test_partial_disposal_retries_only_failed_entries_in_reverse_order():
    async def scenario():
        disposed = []

        def dispose(value, _):
            disposed.append(value)
            if value == "two" and disposed.count(value) == 1:
                raise RuntimeError("cleanup once")

        binder, profile = setup(lambda s, _: s.implementation, dispose)
        binding = binder.prepare_binding(profile)
        assert await binder.bind_prepared(binding) is binding
        assert binding.value("first") == ("one", "two")
        with pytest.raises(RuntimeCapabilityBindingError):
            await binder.dispose(binding)
        assert disposed == ["three", "two", "one"]
        await binder.dispose(binding)
        assert disposed == ["three", "two", "one", "two"]
    asyncio.run(scenario())


def test_prepared_close_has_no_factory_effects_and_disallows_sync_dispose():
    async def scenario():
        created = []
        binder, profile = setup(lambda s, _: created.append(s.implementation), lambda *_: None)
        binding = binder.prepare_binding(profile)
        with pytest.raises(RuntimeError, match="asynchronous"):
            binder.dispose_sync(binding)
        assert not binding.is_closed
        await binder.dispose(binding)
        with pytest.raises(RuntimeError):
            await binder.bind_prepared(binding)
        assert created == []
    asyncio.run(scenario())


def test_building_rejects_dispose_reentry_and_wrong_binder():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def create(selection, _):
            entered.set()
            await release.wait()
            return selection.implementation

        binder, profile = setup(create, lambda *_: None)
        other, _ = setup(create, lambda *_: None)
        binding = binder.prepare_binding(profile)
        with pytest.raises(RuntimeError):
            await other.bind_prepared(binding)
        task = asyncio.create_task(binder.bind_prepared(binding))
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(RuntimeError, match="building"):
            await binder.dispose(binding)
        assert not binding.is_closed
        with pytest.raises(RuntimeError):
            await binder.bind_prepared(binding)
        with pytest.raises(RuntimeError, match="not ready"):
            binding.values()
        release.set()
        assert await task is binding
        with pytest.raises(RuntimeError, match="asynchronous"):
            binder.dispose_sync(binding)
        assert not binding.is_closed
        await binder.dispose(binding)
    asyncio.run(scenario())
