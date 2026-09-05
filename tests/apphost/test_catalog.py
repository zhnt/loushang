from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from loushang.apphost import (
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostCatalogInputV1,
    AppHostCatalogV1,
    CleanupIncompleteError,
    GenerationConflictError,
    GenerationRetiredError,
    ProductDescriptorV1,
    ProductIdentityRequiredError,
    ProductRegistrationV1,
    ProductUnavailableError,
    ProfileDescriptorV1,
    ProfileRegistrationV1,
)


class _Pin:
    def __init__(self, identity: AdmissionIdentityV1, events: list[str]) -> None:
        self._identity = identity
        self._events = events
        self.closed = 0
        self.identity_reads = 0

    @property
    def identity(self) -> AdmissionIdentityV1:
        self.identity_reads += 1
        return self._identity

    async def close(self) -> None:
        self.closed += 1
        self._events.append(f"close:{self._identity.subject_id}")


class _Source:
    def __init__(self, identity: AdmissionIdentityV1, events: list[str]) -> None:
        self.identity = identity
        self.events = events
        self.pins: list[_Pin] = []
        self.entered: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def acquire_pin(self) -> _Pin:
        self.events.append(f"acquire:{self.identity.subject_id}")
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        pin = _Pin(self.identity, self.events)
        self.pins.append(pin)
        return pin


class _CancelAfterReturnSource(_Source):
    async def acquire_pin(self) -> _Pin:
        pin = await super().acquire_pin()
        task = asyncio.current_task()
        assert task is not None
        asyncio.get_running_loop().call_soon(task.cancel)
        return pin


class _DynamicClosePin(_Pin):
    def __init__(self, identity: AdmissionIdentityV1, events: list[str]) -> None:
        super().__init__(identity, events)
        self.dynamic_reads = 0

    def __getattribute__(self, name: str) -> object:
        if name == "close":
            object.__setattr__(
                self,
                "dynamic_reads",
                int(object.__getattribute__(self, "dynamic_reads")) + 1,
            )

            async def forged_close() -> None:
                raise AssertionError("dynamic close must not be invoked")

            return forged_close
        return object.__getattribute__(self, name)


class _DynamicCloseSource(_Source):
    async def acquire_pin(self) -> _DynamicClosePin:
        pin = _DynamicClosePin(self.identity, self.events)
        self.pins.append(pin)
        return pin


class _FailingClosePin(_Pin):
    async def close(self) -> None:
        self.closed += 1
        self.events.append(f"close-failed:{self._identity.subject_id}")
        raise RuntimeError("injected close failure")


class _FailingCloseSource(_Source):
    async def acquire_pin(self) -> _FailingClosePin:
        pin = _FailingClosePin(self.identity, self.events)
        self.pins.append(pin)
        return pin


class _FailOnceClosePin(_Pin):
    async def close(self) -> None:
        self.closed += 1
        self._events.append(f"close-attempt:{self._identity.subject_id}")
        if self.closed == 1:
            raise RuntimeError("secret /tmp/fail-once")


class _FailOnceCloseSource(_Source):
    async def acquire_pin(self) -> _FailOnceClosePin:
        pin = _FailOnceClosePin(self.identity, self.events)
        self.pins.append(pin)
        return pin


class _BlockingClosePin(_Pin):
    def __init__(self, identity: AdmissionIdentityV1, events: list[str]) -> None:
        super().__init__(identity, events)
        self.close_entered = asyncio.Event()
        self.close_release = asyncio.Event()

    async def close(self) -> None:
        self.closed += 1
        self.close_entered.set()
        await self.close_release.wait()
        self._events.append(f"close:{self._identity.subject_id}")


class _BlockingCloseSource(_Source):
    async def acquire_pin(self) -> _BlockingClosePin:
        pin = _BlockingClosePin(self.identity, self.events)
        self.pins.append(pin)
        return pin


class _Factory:
    async def create_runtime(self, candidate: object) -> Any:
        raise AssertionError("A0.2 catalog cannot invoke Product factory")


class _Validator:
    async def open_product_candidate(self, candidate: object, envelope: object) -> Any:
        raise AssertionError("A0.2 catalog cannot invoke Product validator")


class _Importer:
    async def import_candidate(self, candidate: object) -> Any:
        raise AssertionError("A0.2 catalog cannot invoke Product importer")


class _ProfileFactory:
    async def bind_profile(self, runtime: object) -> Any:
        raise AssertionError("A0.2 catalog cannot invoke profile factory")


def _identity(
    generation: str,
    kind: AppHostAdmissionSubjectKind,
    subject: str,
) -> AdmissionIdentityV1:
    return AdmissionIdentityV1(generation, kind, subject)


def _input(
    generation: str,
    events: list[str],
    *,
    product_ids: tuple[str, ...] = ("coding", "slides"),
) -> tuple[AppHostCatalogInputV1, dict[str, _Source]]:
    sources: dict[str, _Source] = {}
    profile_id = "embedded-tui"
    profile_identity = _identity(
        generation, AppHostAdmissionSubjectKind.PROFILE, profile_id
    )
    profile_source = _Source(profile_identity, events)
    sources[profile_id] = profile_source
    products = []
    for product_id in product_ids:
        identity = _identity(
            generation, AppHostAdmissionSubjectKind.PRODUCT, product_id
        )
        source = _Source(identity, events)
        sources[product_id] = source
        products.append(
            ProductRegistrationV1(
                descriptor=ProductDescriptorV1(
                    product_id=product_id,
                    product_version=f"{generation}.0",
                    compatibility_id=f"{product_id}-session-v1",
                    supported_profile_ids=(profile_id,),
                ),
                factory=_Factory(),
                candidate_validator=_Validator(),
                importer=_Importer(),
                admission_identity=identity,
                admission_source=source,
            )
        )
    return (
        AppHostCatalogInputV1(
            generation_id=generation,
            products=tuple(products),
            profiles=(
                ProfileRegistrationV1(
                    descriptor=ProfileDescriptorV1(profile_id, "1"),
                    factory=_ProfileFactory(),
                    admission_identity=profile_identity,
                    admission_source=profile_source,
                ),
            ),
        ),
        sources,
    )


def test_catalog_admits_all_subjects_and_routes_only_explicit_products() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, sources = _input("generation-1", events)
        catalog = await AppHostCatalogV1.admit(value)

        assert catalog.generation_id == "generation-1"
        assert not hasattr(catalog, "acquire_product")
        assert all(source.pins[0].identity_reads == 1 for source in sources.values())
        with pytest.raises(ProductIdentityRequiredError):
            await catalog._acquire_product("")
        with pytest.raises(ProductUnavailableError):
            await catalog._acquire_product("unknown")

        route = await catalog._acquire_product("slides")
        assert route.generation_id == "generation-1"
        assert route.descriptor.product_id == "slides"
        with pytest.raises(AttributeError):
            route.descriptor = value.products[0].descriptor  # type: ignore[misc]
        assert len(sources["slides"].pins) == 2
        await route.close()
        await route.close()
        assert sources["slides"].pins[-1].closed == 1
        await catalog.close()
        assert all(source.pins[0].closed == 1 for source in sources.values())

    asyncio.run(exercise())


def test_catalog_rejects_mismatched_pin_and_rolls_back_in_reverse_order() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, sources = _input("generation-1", events)
        sources["slides"].identity = _identity(
            "generation-2", AppHostAdmissionSubjectKind.PRODUCT, "slides"
        )
        with pytest.raises(GenerationConflictError):
            await AppHostCatalogV1.admit(value)

        assert sources["coding"].pins[0].closed == 1
        assert sources["slides"].pins[0].closed == 1
        assert events[-2:] == ["close:embedded-tui", "close:coding"]
        assert sources["embedded-tui"].pins[0].closed == 1

    asyncio.run(exercise())


def test_catalog_cancellation_rolls_back_already_acquired_generation_pins() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, sources = _input("generation-1", events)
        sources["slides"].entered = asyncio.Event()
        sources["slides"].release = asyncio.Event()
        task = asyncio.create_task(AppHostCatalogV1.admit(value))
        await sources["slides"].entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sources["coding"].pins[0].closed == 1
        assert sources["embedded-tui"].pins[0].closed == 1

    asyncio.run(exercise())


def test_catalog_cancel_scheduled_after_pin_return_closes_returned_pin() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, sources = _input("generation-1", events)
        replacement = _CancelAfterReturnSource(sources["coding"].identity, events)
        value = replace(
            value,
            products=(
                replace(value.products[0], admission_source=replacement),
                *value.products[1:],
            ),
        )
        with pytest.raises(asyncio.CancelledError):
            await AppHostCatalogV1.admit(value)
        assert replacement.pins[0].closed == 1
        assert sources["slides"].pins[0].closed == 1

    asyncio.run(exercise())


def test_catalog_rejects_dynamic_close_without_invoking_dynamic_dispatch() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, sources = _input("generation-1", events)
        replacement = _DynamicCloseSource(sources["coding"].identity, events)
        value = replace(
            value,
            products=(
                replace(value.products[0], admission_source=replacement),
                *value.products[1:],
            ),
        )
        with pytest.raises(GenerationConflictError):
            await AppHostCatalogV1.admit(value)
        pin = replacement.pins[0]
        assert isinstance(pin, _DynamicClosePin)
        assert pin.dynamic_reads == 0
        assert pin.closed == 1

    asyncio.run(exercise())


def test_catalog_retains_cleanup_failure_and_still_rolls_back_prior_pins() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, sources = _input("generation-1", events)
        wrong = _identity(
            "generation-2", AppHostAdmissionSubjectKind.PRODUCT, "slides"
        )
        replacement = _FailingCloseSource(wrong, events)
        value = replace(
            value,
            products=(
                value.products[0],
                replace(value.products[1], admission_source=replacement),
            ),
        )
        with pytest.raises(CleanupIncompleteError) as error:
            await AppHostCatalogV1.admit(value)
        assert error.value.__cause__ is None
        assert replacement.pins[0].closed == 1
        assert sources["coding"].pins[0].closed == 1

    asyncio.run(exercise())


def test_catalog_replace_is_cas_and_does_not_retarget_existing_route() -> None:
    async def exercise() -> None:
        events: list[str] = []
        first, first_sources = _input("generation-1", events)
        second, second_sources = _input("generation-2", events)
        catalog = await AppHostCatalogV1.admit(first)
        retained = await catalog._acquire_product("coding")

        await catalog.replace(second, expected_generation_id="generation-1")
        current = await catalog._acquire_product("coding")
        assert retained.generation_id == "generation-1"
        assert retained.descriptor.product_version == "generation-1.0"
        assert first_sources["coding"].pins[-1].closed == 0
        assert current.generation_id == "generation-2"
        assert all(source.pins[0].closed == 1 for source in first_sources.values())

        third, third_sources = _input("generation-3", events)
        with pytest.raises(GenerationConflictError):
            await catalog.replace(third, expected_generation_id="generation-1")
        assert all(source.pins[0].closed == 1 for source in third_sources.values())

        same_id, same_sources = _input("generation-2", events)
        with pytest.raises(GenerationConflictError):
            await catalog.replace(same_id, expected_generation_id="generation-2")
        assert all(source.pins[0].closed == 1 for source in same_sources.values())

        await retained.close()
        await current.close()
        await catalog.close()
        assert all(source.pins[0].closed == 1 for source in second_sources.values())

    asyncio.run(exercise())


def test_catalog_retirement_fences_new_routes_but_preserves_returned_pin() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, sources = _input("generation-1", events)
        catalog = await AppHostCatalogV1.admit(value)
        retained = await catalog._acquire_product("coding")
        route_pin = sources["coding"].pins[-1]

        await catalog.close()
        with pytest.raises(GenerationRetiredError):
            await catalog._acquire_product("coding")
        assert route_pin.closed == 0
        await retained.close()
        assert route_pin.closed == 1

    asyncio.run(exercise())


def test_catalog_external_acquire_does_not_block_an_unrelated_product() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, sources = _input("generation-1", events)
        catalog = await AppHostCatalogV1.admit(value)
        sources["coding"].entered = asyncio.Event()
        sources["coding"].release = asyncio.Event()

        blocked = asyncio.create_task(catalog._acquire_product("coding"))
        await sources["coding"].entered.wait()
        independent = await asyncio.wait_for(
            catalog._acquire_product("slides"), timeout=0.2
        )
        await independent.close()
        sources["coding"].release.set()
        coding = await blocked
        await coding.close()
        await catalog.close()

    asyncio.run(exercise())


def test_catalog_replace_retains_cleanup_debt_and_retries_only_failed_pin() -> None:
    async def exercise() -> None:
        events: list[str] = []
        first, sources = _input("generation-1", events)
        failing = _FailOnceCloseSource(sources["coding"].identity, events)
        first = replace(
            first,
            products=(
                replace(first.products[0], admission_source=failing),
                *first.products[1:],
            ),
        )
        second, second_sources = _input("generation-2", events)
        catalog = await AppHostCatalogV1.admit(first)

        with pytest.raises(CleanupIncompleteError) as error:
            await catalog.replace(second, expected_generation_id="generation-1")
        assert error.value.__cause__ is None
        assert catalog.generation_id == "generation-2"
        assert failing.pins[0].closed == 1
        assert sources["slides"].pins[0].closed == 1
        assert sources["embedded-tui"].pins[0].closed == 1

        await catalog.settle_retiring()
        assert failing.pins[0].closed == 2
        assert sources["slides"].pins[0].closed == 1
        assert sources["embedded-tui"].pins[0].closed == 1
        await catalog.close()
        assert all(source.pins[0].closed == 1 for source in second_sources.values())

    asyncio.run(exercise())


def test_catalog_cancel_after_replace_cas_keeps_retirement_joinable() -> None:
    async def exercise() -> None:
        events: list[str] = []
        first, sources = _input("generation-1", events)
        blocking = _BlockingCloseSource(sources["embedded-tui"].identity, events)
        first = replace(
            first,
            profiles=(replace(first.profiles[0], admission_source=blocking),),
        )
        second, _ = _input("generation-2", events)
        catalog = await AppHostCatalogV1.admit(first)
        pin = blocking.pins[0]
        assert isinstance(pin, _BlockingClosePin)

        replacement = asyncio.create_task(
            catalog.replace(second, expected_generation_id="generation-1")
        )
        await pin.close_entered.wait()
        assert catalog.generation_id == "generation-2"
        replacement.cancel()
        with pytest.raises(asyncio.CancelledError):
            await replacement
        pin.close_release.set()
        await catalog.close()
        assert pin.closed == 1

    asyncio.run(exercise())


def test_catalog_route_close_is_one_shared_retryable_settlement() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, sources = _input("generation-1", events)
        failing = _FailOnceCloseSource(sources["coding"].identity, events)
        value = replace(
            value,
            products=(
                replace(value.products[0], admission_source=failing),
                *value.products[1:],
            ),
        )
        catalog = await AppHostCatalogV1.admit(value)
        route = await catalog._acquire_product("coding")
        route_pin = failing.pins[-1]
        with pytest.raises(CleanupIncompleteError):
            await asyncio.gather(route.close(), route.close())
        assert route_pin.closed == 1
        await route.close()
        await route.close()
        assert route_pin.closed == 2
        # The base generation pin has independent retirement ownership.
        with pytest.raises(CleanupIncompleteError):
            await catalog.close()
        await catalog.close()

    asyncio.run(exercise())
