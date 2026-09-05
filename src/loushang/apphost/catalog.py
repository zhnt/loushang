"""Admitted immutable Product catalog generations for AppHost A0.2."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from ._ownership import (
    AsyncClose,
    CloseGroup,
    RetryableCloser,
    bind_native_async,
    read_static_property,
)
from .contracts import (
    AdmissionIdentityV1,
    AppHostCatalogInputV1,
    ClaimedSessionCandidateV1,
    OpenedProductCandidateV1,
    ProductDescriptorV1,
    ProductProfileBindingV1,
    ProductRegistrationV1,
    ProfileDescriptorV1,
    ProfileLeaseV1,
    ProfileRegistrationV1,
    ScopedProductRuntimeV1,
    SessionCandidateRefV1,
    SessionIdentityEnvelopeV1,
)
from .errors import (
    AppHostError,
    AppHostFailureCategory,
    CleanupIncompleteError,
    GenerationConflictError,
    GenerationRetiredError,
    ProductIdentityRequiredError,
    ProductIncompatibleError,
    ProductUnavailableError,
    redacted_apphost_error,
)

AcquirePin = Callable[[], Awaitable[object]]
ValidateCandidate = Callable[
    [ClaimedSessionCandidateV1, SessionIdentityEnvelopeV1],
    Awaitable[OpenedProductCandidateV1],
]
ImportCandidate = Callable[
    [ClaimedSessionCandidateV1], Awaitable[SessionCandidateRefV1]
]
CreateRuntime = Callable[[OpenedProductCandidateV1], Awaitable[ScopedProductRuntimeV1]]
BindProfile = Callable[[ProductProfileBindingV1], Awaitable[ProfileLeaseV1]]


@dataclass(frozen=True, slots=True)
class _ProductEntry:
    descriptor: ProductDescriptorV1
    identity: AdmissionIdentityV1
    acquire_pin: AcquirePin
    create_runtime: CreateRuntime
    validate_candidate: ValidateCandidate
    import_candidate: ImportCandidate | None

    @classmethod
    def bind(cls, registration: ProductRegistrationV1) -> _ProductEntry:
        importer = (
            None
            if registration.importer is None
            else cast(
                ImportCandidate,
                bind_native_async(registration.importer, "import_candidate"),
            )
        )
        return cls(
            descriptor=registration.descriptor,
            identity=registration.admission_identity,
            acquire_pin=cast(
                AcquirePin,
                bind_native_async(registration.admission_source, "acquire_pin"),
            ),
            create_runtime=cast(
                CreateRuntime,
                bind_native_async(registration.factory, "create_runtime"),
            ),
            validate_candidate=cast(
                ValidateCandidate,
                bind_native_async(
                    registration.candidate_validator,
                    "open_product_candidate",
                ),
            ),
            import_candidate=importer,
        )


@dataclass(frozen=True, slots=True)
class _ProfileEntry:
    descriptor: ProfileDescriptorV1
    identity: AdmissionIdentityV1
    acquire_pin: AcquirePin
    bind_profile: BindProfile

    @classmethod
    def bind(cls, registration: ProfileRegistrationV1) -> _ProfileEntry:
        return cls(
            descriptor=registration.descriptor,
            identity=registration.admission_identity,
            acquire_pin=cast(
                AcquirePin,
                bind_native_async(registration.admission_source, "acquire_pin"),
            ),
            bind_profile=cast(
                BindProfile,
                bind_native_async(registration.factory, "bind_profile"),
            ),
        )


class _OwnedAdmissionPin:
    __slots__ = ("_closer", "identity")

    def __init__(
        self,
        identity: AdmissionIdentityV1,
        closer: RetryableCloser,
    ) -> None:
        self.identity = identity
        self._closer = closer

    @property
    def closer(self) -> RetryableCloser:
        return self._closer

    async def close(self) -> None:
        if not await self._closer.settle():
            raise CleanupIncompleteError() from None


class _ProductCatalogLease:
    """Private exact-generation route capability without a Product factory."""

    __slots__ = ("_entry", "_pin")

    def __init__(self, entry: _ProductEntry, pin: _OwnedAdmissionPin) -> None:
        self._entry = entry
        self._pin = pin

    @property
    def descriptor(self) -> ProductDescriptorV1:
        return self._entry.descriptor

    @property
    def generation_id(self) -> str:
        return self._entry.identity.generation_id

    @property
    def closer(self) -> RetryableCloser:
        return self._pin.closer

    async def validate(
        self,
        candidate: ClaimedSessionCandidateV1,
        envelope: SessionIdentityEnvelopeV1,
    ) -> OpenedProductCandidateV1:
        try:
            return await self._entry.validate_candidate(candidate, envelope)
        except asyncio.CancelledError:
            raise
        except AppHostError:
            raise redacted_apphost_error(
                AppHostFailureCategory.PRODUCT_INCOMPATIBLE
            ) from None
        except BaseException:
            raise ProductIncompatibleError() from None

    async def import_legacy(
        self,
        candidate: ClaimedSessionCandidateV1,
    ) -> SessionCandidateRefV1:
        importer = self._entry.import_candidate
        if importer is None:
            raise AppHostError(AppHostFailureCategory.PRODUCT_INCOMPATIBLE)
        try:
            return await importer(candidate)
        except asyncio.CancelledError:
            raise
        except AppHostError:
            raise redacted_apphost_error(
                AppHostFailureCategory.PRODUCT_INCOMPATIBLE
            ) from None
        except BaseException:
            raise ProductIncompatibleError() from None

    async def close(self) -> None:
        await self._pin.close()


class _RuntimeCatalogLease:
    """Private full-generation capability retained by one live binding."""

    __slots__ = ("_group", "_product", "_profiles")

    def __init__(
        self,
        product: _ProductEntry,
        profiles: tuple[_ProfileEntry, ...],
        group: CloseGroup,
    ) -> None:
        self._product = product
        self._profiles = profiles
        self._group = group

    @property
    def descriptor(self) -> ProductDescriptorV1:
        return self._product.descriptor

    @property
    def generation_id(self) -> str:
        return self._product.identity.generation_id

    async def validate(
        self,
        candidate: ClaimedSessionCandidateV1,
        envelope: SessionIdentityEnvelopeV1,
    ) -> OpenedProductCandidateV1:
        try:
            return await self._product.validate_candidate(candidate, envelope)
        except asyncio.CancelledError:
            raise
        except AppHostError:
            raise ProductIncompatibleError() from None
        except BaseException:
            raise ProductIncompatibleError() from None

    async def create(
        self,
        candidate: OpenedProductCandidateV1,
    ) -> ScopedProductRuntimeV1:
        try:
            return await self._product.create_runtime(candidate)
        except asyncio.CancelledError:
            raise
        except AppHostError:
            raise redacted_apphost_error(
                AppHostFailureCategory.RUNTIME_UNAVAILABLE
            ) from None
        except BaseException:
            raise redacted_apphost_error(
                AppHostFailureCategory.RUNTIME_UNAVAILABLE
            ) from None

    async def bind_profile(
        self,
        profile_id: str,
        runtime: ProductProfileBindingV1,
    ) -> ProfileLeaseV1:
        if profile_id not in self._product.descriptor.supported_profile_ids:
            raise redacted_apphost_error(
                AppHostFailureCategory.PROFILE_UNAVAILABLE
            )
        profile = next(
            (item for item in self._profiles if item.descriptor.profile_id == profile_id),
            None,
        )
        if profile is None:
            raise redacted_apphost_error(
                AppHostFailureCategory.PROFILE_UNAVAILABLE
            )
        try:
            return await profile.bind_profile(runtime)
        except asyncio.CancelledError:
            raise
        except AppHostError:
            raise redacted_apphost_error(
                AppHostFailureCategory.PROFILE_UNAVAILABLE
            ) from None
        except BaseException:
            raise redacted_apphost_error(
                AppHostFailureCategory.PROFILE_UNAVAILABLE
            ) from None

    async def close(self) -> None:
        await self._group.close()


@dataclass(frozen=True, slots=True)
class _ProductReservation:
    generation: _CatalogGeneration
    entry: _ProductEntry

    async def acquire(self) -> _ProductCatalogLease:
        try:
            pin = await _acquire_exact_pin(
                self.entry.acquire_pin,
                self.entry.identity,
            )
        except BaseException:
            finish = asyncio.create_task(self.generation.finish_reservation())
            await asyncio.shield(finish)
            raise
        finish = asyncio.create_task(self.generation.finish_reservation())
        try:
            accepting = await asyncio.shield(finish)
        except asyncio.CancelledError:
            await asyncio.shield(finish)
            if not await pin.closer.settle():
                raise CleanupIncompleteError() from None
            raise
        if not accepting:
            if not await pin.closer.settle():
                raise CleanupIncompleteError() from None
            raise GenerationRetiredError()
        return _ProductCatalogLease(self.entry, pin)

    async def acquire_runtime(self) -> _RuntimeCatalogLease:
        profiles = tuple(
            profile
            for profile_id in self.entry.descriptor.supported_profile_ids
            for profile in self.generation.profiles
            if profile.descriptor.profile_id == profile_id
        )
        requests = (
            (self.entry.acquire_pin, self.entry.identity),
            *((profile.acquire_pin, profile.identity) for profile in profiles),
        )
        acquired: list[_OwnedAdmissionPin] = []

        async def acquire_one(
            callback: AcquirePin,
            identity: AdmissionIdentityV1,
        ) -> _OwnedAdmissionPin:
            pin = await _acquire_exact_pin(callback, identity)
            acquired.append(pin)
            return pin

        tasks = tuple(
            asyncio.create_task(acquire_one(callback, identity))
            for callback, identity in requests
        )
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            finish = asyncio.create_task(self.generation.finish_reservation())
            await asyncio.shield(finish)
            if not await CloseGroup(pin.closer for pin in acquired).settle():
                raise CleanupIncompleteError() from None
            raise
        finish = asyncio.create_task(self.generation.finish_reservation())
        try:
            accepting = await asyncio.shield(finish)
        except asyncio.CancelledError:
            await asyncio.shield(finish)
            if not await CloseGroup(pin.closer for pin in acquired).settle():
                raise CleanupIncompleteError() from None
            raise
        failures = tuple(
            result for result in results if not isinstance(result, _OwnedAdmissionPin)
        )
        if failures or not accepting:
            if not await CloseGroup(pin.closer for pin in acquired).settle():
                raise CleanupIncompleteError() from None
            if any(isinstance(error, asyncio.CancelledError) for error in failures):
                raise asyncio.CancelledError
            if not accepting:
                raise GenerationRetiredError()
            first = failures[0]
            if isinstance(first, AppHostError):
                raise first from None
            raise GenerationConflictError() from None
        return _RuntimeCatalogLease(
            self.entry,
            profiles,
            CloseGroup(pin.closer for pin in acquired),
        )


class _CatalogGeneration:
    __slots__ = (
        "_accepting",
        "_base_pins",
        "_drained",
        "_lock",
        "_reservations",
        "generation_id",
        "products",
        "profiles",
    )

    def __init__(
        self,
        generation_id: str,
        products: tuple[_ProductEntry, ...],
        profiles: tuple[_ProfileEntry, ...],
        base_pins: CloseGroup,
    ) -> None:
        self.generation_id = generation_id
        self.products = products
        self.profiles = profiles
        self._base_pins = base_pins
        self._accepting = True
        self._reservations = 0
        self._drained = asyncio.Event()
        self._drained.set()
        self._lock = asyncio.Lock()

    @classmethod
    async def admit(cls, value: AppHostCatalogInputV1) -> _CatalogGeneration:
        if not isinstance(value, AppHostCatalogInputV1):
            raise TypeError("catalog input must be AppHostCatalogInputV1")
        try:
            products = tuple(_ProductEntry.bind(item) for item in value.products)
            profiles = tuple(_ProfileEntry.bind(item) for item in value.profiles)
        except BaseException:
            raise GenerationConflictError() from None
        requests = (
            *((item.acquire_pin, item.identity) for item in products),
            *((item.acquire_pin, item.identity) for item in profiles),
        )
        acquired_order: list[_OwnedAdmissionPin] = []

        async def acquire_and_record(
            acquire: AcquirePin,
            identity: AdmissionIdentityV1,
        ) -> _OwnedAdmissionPin:
            pin = await _acquire_exact_pin(acquire, identity)
            acquired_order.append(pin)
            return pin

        tasks = tuple(
            asyncio.create_task(acquire_and_record(acquire, identity))
            for acquire, identity in requests
        )
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if not await CloseGroup(
                pin.closer for pin in acquired_order
            ).settle():
                raise CleanupIncompleteError() from None
            raise
        failures = tuple(
            result for result in results if not isinstance(result, _OwnedAdmissionPin)
        )
        if failures:
            if not await CloseGroup(
                pin.closer for pin in acquired_order
            ).settle():
                raise CleanupIncompleteError() from None
            if any(isinstance(error, asyncio.CancelledError) for error in failures):
                raise asyncio.CancelledError
            first = failures[0]
            if isinstance(first, AppHostError):
                raise first from None
            raise GenerationRetiredError() from None
        return cls(
            value.generation_id,
            products,
            profiles,
            CloseGroup(pin.closer for pin in acquired_order),
        )

    async def reserve_product(self, product_id: str) -> _ProductReservation:
        async with self._lock:
            if not self._accepting:
                raise GenerationRetiredError()
            entry = next(
                (item for item in self.products if item.descriptor.product_id == product_id),
                None,
            )
            if entry is None:
                raise ProductUnavailableError()
            if self._reservations == 0:
                self._drained.clear()
            self._reservations += 1
            return _ProductReservation(self, entry)

    async def finish_reservation(self) -> bool:
        async with self._lock:
            self._reservations -= 1
            if self._reservations == 0:
                self._drained.set()
            return self._accepting

    async def fence(self) -> None:
        async with self._lock:
            self._accepting = False
            if self._reservations == 0:
                self._drained.set()

    async def settle_retirement(self) -> bool:
        await self.fence()
        await self._drained.wait()
        return await self._base_pins.settle()


class AppHostCatalogV1:
    """Atomic owner of one active immutable admitted generation.

    Owner locks protect only pointer/reservation state. Admission source and
    cleanup callbacks always run outside these locks. Replaced generations
    remain in ``_retiring`` until their retryable settlement succeeds.
    """

    __slots__ = ("_active", "_closed", "_lock", "_retiring", "_tasks")

    def __init__(self, generation: _CatalogGeneration) -> None:
        self._active = generation
        self._closed = False
        self._lock = asyncio.Lock()
        self._retiring: set[_CatalogGeneration] = set()
        self._tasks: dict[_CatalogGeneration, asyncio.Task[bool]] = {}

    @classmethod
    async def admit(cls, value: AppHostCatalogInputV1) -> AppHostCatalogV1:
        return cls(await _CatalogGeneration.admit(value))

    @property
    def generation_id(self) -> str:
        return self._active.generation_id

    async def _acquire_product(self, product_id: str) -> _ProductCatalogLease:
        """Friend seam for AppHostRouterV1; not a public routing bypass."""
        if not isinstance(product_id, str) or not product_id:
            raise ProductIdentityRequiredError()
        async with self._lock:
            if self._closed:
                raise GenerationRetiredError()
            reservation = await self._active.reserve_product(product_id)
        return await reservation.acquire()

    async def _acquire_runtime_product(
        self, product_id: str
    ) -> _RuntimeCatalogLease:
        """Friend seam for the A0.3 live registry; retains Product and profiles."""
        if not isinstance(product_id, str) or not product_id:
            raise ProductIdentityRequiredError()
        async with self._lock:
            if self._closed:
                raise GenerationRetiredError()
            reservation = await self._active.reserve_product(product_id)
        return await reservation.acquire_runtime()

    async def replace(
        self,
        value: AppHostCatalogInputV1,
        *,
        expected_generation_id: str,
    ) -> None:
        replacement = await _CatalogGeneration.admit(value)
        operation = asyncio.create_task(
            self._replace_admitted(
                replacement,
                expected_generation_id=expected_generation_id,
            )
        )
        operation.add_done_callback(_observe_background_result)
        await asyncio.shield(operation)

    async def _replace_admitted(
        self,
        replacement: _CatalogGeneration,
        *,
        expected_generation_id: str,
    ) -> None:
        accepted = False
        previous: _CatalogGeneration | None = None
        async with self._lock:
            if (
                not self._closed
                and self._active.generation_id == expected_generation_id
                and replacement.generation_id != expected_generation_id
            ):
                previous = self._active
                await previous.fence()
                self._active = replacement
                self._retiring.add(previous)
                accepted = True
            else:
                await replacement.fence()
                self._retiring.add(replacement)
        target = previous if accepted else replacement
        assert target is not None
        # The settlement owner must exist before the caller can be cancelled
        # after the CAS.  Shielding only a coroutine leaves a cancellation
        # window before that coroutine has installed its persistent task.
        complete = await self._settle_one(target)
        if not complete:
            raise CleanupIncompleteError() from None
        if not accepted:
            if self._closed:
                raise GenerationRetiredError()
            raise GenerationConflictError()

    async def settle_retiring(self) -> None:
        operation = asyncio.create_task(self._settle_retiring_once())
        operation.add_done_callback(_observe_background_result)
        await asyncio.shield(operation)

    async def _settle_retiring_once(self) -> None:
        async with self._lock:
            generations = tuple(self._retiring)
        tasks = tuple(
            asyncio.create_task(self._settle_one(generation))
            for generation in generations
        )
        results = await asyncio.gather(*(asyncio.shield(task) for task in tasks))
        if not all(results):
            raise CleanupIncompleteError() from None

    async def close(self) -> None:
        operation = asyncio.create_task(self._close_once())
        operation.add_done_callback(_observe_background_result)
        await asyncio.shield(operation)

    async def _close_once(self) -> None:
        async with self._lock:
            if not self._closed:
                self._closed = True
                await self._active.fence()
                self._retiring.add(self._active)
            generations = tuple(self._retiring)
        tasks = tuple(
            asyncio.create_task(self._settle_one(generation))
            for generation in generations
        )
        results = await asyncio.gather(*(asyncio.shield(task) for task in tasks))
        if not all(results):
            raise CleanupIncompleteError() from None

    async def _settle_one(self, generation: _CatalogGeneration) -> bool:
        async with self._lock:
            task = self._tasks.get(generation)
            if task is None or (task.done() and not task.result()):
                task = asyncio.create_task(generation.settle_retirement())
                self._tasks[generation] = task
        result = await asyncio.shield(task)
        if result:
            async with self._lock:
                self._retiring.discard(generation)
                self._tasks.pop(generation, None)
        return result


async def _acquire_exact_pin(
    acquire: AcquirePin,
    expected: AdmissionIdentityV1,
) -> _OwnedAdmissionPin:
    raw: object | None = None
    owner: _OwnedAdmissionPin | None = None
    try:
        raw = await acquire()
        closer = RetryableCloser.bind(raw)
        identity = read_static_property(raw, "identity")
        if type(identity) is not AdmissionIdentityV1 or identity != expected:
            owner = _OwnedAdmissionPin(expected, closer)
            if not await closer.settle():
                raise CleanupIncompleteError() from None
            raise GenerationConflictError()
        owner = _OwnedAdmissionPin(identity, closer)
        await asyncio.sleep(0)
        return owner
    except asyncio.CancelledError:
        if owner is not None and not await owner.closer.settle():
            raise CleanupIncompleteError() from None
        raise
    except CleanupIncompleteError:
        raise
    except AppHostError as error:
        if (
            owner is not None
            and not owner.closer.complete
            and not await owner.closer.settle()
        ):
            raise CleanupIncompleteError() from None
        raise redacted_apphost_error(error.category) from None
    except BaseException:
        if owner is not None and not await owner.closer.settle():
            raise CleanupIncompleteError() from None
        if raw is not None and owner is None:
            rescued = _bind_rescue_close(raw)
            if rescued is None or not await RetryableCloser(rescued).settle():
                raise CleanupIncompleteError() from None
        raise GenerationConflictError() from None


def _bind_rescue_close(value: object) -> AsyncClose | None:
    """Bind only the static class descriptor for cleanup after rejection."""

    try:
        descriptor = inspect.getattr_static(type(value), "close", None)
        inspected = (
            descriptor.__func__
            if isinstance(descriptor, (classmethod, staticmethod))
            else descriptor
        )
        if not inspect.iscoroutinefunction(inspected):
            return None
        return cast(AsyncClose, descriptor.__get__(value, type(value)))
    except BaseException:
        return None


def _observe_background_result(task: asyncio.Task[None]) -> None:
    """Consume a detached caller result; catalog debt remains independently owned."""

    if not task.cancelled():
        task.exception()


__all__ = ["AppHostCatalogV1"]
