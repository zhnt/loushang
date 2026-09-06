from __future__ import annotations

import ast
import asyncio
import json
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from loushang.apphost import (
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostError,
    AppHostShutdownBudgetV1,
    ProfileDescriptorV1,
    ProfileRegistrationV1,
    SessionBindingKeyV1,
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.coding._product_worker_canary import (
    CodingProductWorkerCanaryStatusV1,
)
from loushang.coding.apphost_composition import (
    CodingAppHostCompositionActivationV1,
    CodingAppHostCompositionError,
    CodingAppHostCompositionRequestV1,
    CodingAppHostRollbackLatchV1,
    create_coding_apphost_composition,
)
from loushang.coding.apphost_product import (
    CodingAppHostProductBindingV1,
    CodingAppHostWorkerAttemptV1,
)
from loushang.harness.worker import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
    WorkerHostingActivationV1,
    WorkerSessionOwnerRouter,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    _MemoryActivationStateStore,
)

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_GENERATION = "generation-g9"
_PROFILE_IDS = ("embedded-tui", "hosted-app")
_INVENTORY = Path(
    "docs/internals/architecture/apphost/hosted-product-g9-entrypoint-inventory.json"
)
_COMPOSITION = Path("src/loushang/coding/apphost_composition.py")
_CURRENT_ROOTS = {
    "coding.bootstrap": Path("src/loushang/coding/bootstrap.py"),
    "coding.cli": Path("src/loushang/coding/cli/__main__.py"),
    "coding.tui": Path("src/loushang/coding/ui/cli.py"),
}


def _policy(session_id: str) -> ProductWorkerActivationPolicyV1:
    return ProductWorkerActivationPolicyV1(
        product_id="coding",
        product_runtime_id=f"runtime-{session_id}",
        product_scope_id=f"session.{session_id}",
        session_id=session_id,
        session_route="selected",
        selected_locator_fingerprint=_DIGEST_A,
        selected_locator_revision="locator-1",
        plugin_id="review-pack",
        plugin_revision_digest=_DIGEST_A,
        contribution_id="review-provider",
        reservation_fingerprint=_DIGEST_B,
        declaration_fingerprint=_DIGEST_C,
        worker_configuration_fingerprint=_DIGEST_A,
        declared_required=True,
        effective_required=True,
        enabled=True,
        allowed_product_ids=("coding",),
        allowed_contribution_ids=("review-provider",),
        requested_owner="hosting",
        owner_selection_generation=3,
        no_fallback=True,
        native_profile_id="posix-static-contained-elf-v1",
        native_profile_catalog_revision="native-catalog-1",
        allowed_native_profile_ids=("posix-static-contained-elf-v1",),
        expected_native_policy_closure_fingerprint=_DIGEST_B,
        product_policy_revision="product-policy-1",
        kill_switch_generation=2,
    )


def _receipt(session_id: str) -> ProductWorkerActivationReceiptV1:
    return ProductWorkerActivationReceiptV1(
        policy=_policy(session_id),
        issue_sequence=1,
        issue_nonce=f"receipt-{session_id}",
    )


def _status(
    receipt: ProductWorkerActivationReceiptV1,
    *,
    attempt_index: int,
) -> CodingProductWorkerCanaryStatusV1:
    return CodingProductWorkerCanaryStatusV1(
        code="coding_worker_ready",
        readiness="ready",
        required=True,
        requested_owner="hosting",
        effective_owner="hosting",
        receipt_fingerprint=receipt.fingerprint,
        attempt_id=f"{attempt_index + 1:032x}",
        owner_generation=receipt.policy.owner_selection_generation,
    )


class _Attempt:
    def __init__(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        *,
        attempt_index: int,
        events: list[str],
        recover_error: bool = False,
        start_error: bool = False,
        close_failures: int = 0,
        close_entered: asyncio.Event | None = None,
        close_release: asyncio.Event | None = None,
        start_entered: asyncio.Event | None = None,
        start_release: asyncio.Event | None = None,
    ) -> None:
        self.activation_receipt = receipt
        self._status = _status(receipt, attempt_index=attempt_index)
        self.events = events
        self.recover_error = recover_error
        self.start_error = start_error
        self.close_failures = close_failures
        self.close_entered = close_entered
        self.close_release = close_release
        self.start_entered = start_entered
        self.start_release = start_release
        self.close_calls = 0

    @property
    def status(self) -> CodingProductWorkerCanaryStatusV1:
        return self._status

    def receipt_for_entrypoint(
        self,
        entrypoint: str,
    ) -> ProductWorkerActivationReceiptV1:
        self.events.append(f"receipt:{entrypoint}")
        return self.activation_receipt

    async def recover(self) -> tuple[str, ...]:
        self.events.append("recover")
        if self.recover_error:
            raise RuntimeError("recovery failed")
        return ("recovered",)

    async def start(
        self,
        *,
        correlation_id: str,
    ) -> CodingProductWorkerCanaryStatusV1:
        assert correlation_id
        self.events.append("start")
        if self.start_entered is not None:
            self.start_entered.set()
        if self.start_release is not None:
            await self.start_release.wait()
        if self.start_error:
            raise RuntimeError("start failed")
        return self._status

    async def close(self) -> None:
        self.close_calls += 1
        self.events.append("worker-close")
        if self.close_entered is not None:
            self.close_entered.set()
        if self.close_release is not None:
            await self.close_release.wait()
        if self.close_failures:
            self.close_failures -= 1
            raise RuntimeError("close failed")


AttemptBuilder = Callable[[SessionBindingKeyV1, int, list[str]], _Attempt]


class _AttemptFactory:
    def __init__(self, builder: AttemptBuilder | None = None) -> None:
        self.builder = builder or (
            lambda key, index, events: _Attempt(
                _receipt(key.session_id),
                attempt_index=index,
                events=events,
            )
        )
        self.events: list[str] = []
        self.attempts: list[_Attempt] = []

    def create_attempt(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        opaque_session_binding: object,
    ) -> CodingAppHostWorkerAttemptV1:
        del opaque_session_binding
        attempt = self.builder(binding_key, len(self.attempts), self.events)
        self.attempts.append(attempt)
        return attempt


class _Pin:
    def __init__(self, identity: AdmissionIdentityV1, events: list[str]) -> None:
        self._identity = identity
        self._events = events
        self.closed = 0

    @property
    def identity(self) -> AdmissionIdentityV1:
        return self._identity

    async def close(self) -> None:
        self.closed += 1
        self._events.append(f"pin-close:{self._identity.subject_id}")


class _Source:
    def __init__(self, identity: AdmissionIdentityV1, events: list[str]) -> None:
        self.identity = identity
        self.events = events
        self.pins: list[_Pin] = []

    async def acquire_pin(self) -> _Pin:
        pin = _Pin(self.identity, self.events)
        self.pins.append(pin)
        return pin


class _Claimed:
    def __init__(self, reference: SessionCandidateRefV1, opaque: object) -> None:
        self._reference = reference
        self._opaque = opaque

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference

    @property
    def opaque_binding(self) -> object:
        return self._opaque

    async def close(self) -> None:
        return None


class _Candidate:
    def __init__(self, envelope: SessionIdentityEnvelopeV1) -> None:
        self.envelope = envelope
        self._projection = SessionIdentityProjectionV1(
            reference=SessionCandidateRefV1(
                "canonical", envelope.session_id, "revision-1"
            ),
            scope=SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
            mode=SessionCandidateMode.CANONICAL,
            envelope=envelope,
        )

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._projection

    async def verify_current(self) -> None:
        return None

    async def claim(self) -> _Claimed:
        return _Claimed(self._projection.reference, self)

    async def close(self) -> None:
        return None


class _Sessions:
    def __init__(self, candidates: dict[str, _Candidate]) -> None:
        self.candidates = candidates

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        del scopes
        return tuple(candidate.projection for candidate in self.candidates.values())[
            :limit
        ]

    async def open_candidate(self, reference: SessionCandidateRefV1) -> _Candidate:
        return self.candidates[reference.candidate_id]

    async def find_created_candidate(
        self,
        request: SessionCreateRequestV1,
    ) -> _Candidate | None:
        del request
        return None

    async def create_candidate(self, intent: SessionCreateIntentV1) -> _Candidate:
        del intent
        raise AssertionError("G9 drill does not create Session candidates")


class _Validator:
    async def open_product_candidate(
        self,
        candidate: object,
        envelope: SessionIdentityEnvelopeV1,
    ) -> _Opened:
        return _Opened(
            SessionBindingKeyV1(
                envelope.product_id,
                envelope.continuity_id,
                envelope.session_id,
            ),
            candidate,
        )


class _Opened:
    def __init__(self, key: SessionBindingKeyV1, opaque: object) -> None:
        self._key = key
        self._opaque = opaque

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._key

    @property
    def opaque_binding(self) -> object:
        return self._opaque

    async def close(self) -> None:
        return None


class _ProfileLease:
    def __init__(self, profile_id: str, binding: object, events: list[str]) -> None:
        self._profile_id = profile_id
        self._binding = binding
        self._events = events
        self.closed = 0

    @property
    def profile_id(self) -> str:
        return self._profile_id

    @property
    def profile_binding(self) -> object:
        return self._binding

    async def close(self) -> None:
        if self.closed == 0:
            self._events.append(f"profile-close:{self._profile_id}")
        self.closed += 1


class _ProfileFactory:
    def __init__(self, profile_id: str, events: list[str]) -> None:
        self.profile_id = profile_id
        self.events = events
        self.leases: list[_ProfileLease] = []

    async def bind_profile(self, binding: object) -> _ProfileLease:
        lease = _ProfileLease(self.profile_id, binding, self.events)
        self.leases.append(lease)
        return lease


class _RollbackControl:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.entered = asyncio.Event()
        self.calls = 0
        self.failures = 0
        self.release: asyncio.Event | None = None

    async def latch_future_attempts(self) -> CodingAppHostRollbackLatchV1:
        self.calls += 1
        self.events.append("rollback-latch")
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failures:
            self.failures -= 1
            raise RuntimeError("latch failed")
        return CodingAppHostRollbackLatchV1(
            selection_generation=4,
            active_attempt_fingerprints=(_DIGEST_A,),
        )


@dataclass(slots=True)
class _Environment:
    composition: Any
    attempts: _AttemptFactory
    candidates: dict[str, _Candidate]
    profiles: dict[str, _ProfileFactory]
    rollback: _RollbackControl
    events: list[str]


async def _environment(
    attempts: _AttemptFactory | None = None,
    *,
    session_ids: tuple[str, ...] = ("session-1",),
) -> _Environment:
    events = attempts.events if attempts is not None else []
    attempt_factory = attempts or _AttemptFactory()
    if not events:
        attempt_factory.events = events
    candidates = {
        session_id: _Candidate(
            SessionIdentityEnvelopeV1(
                product_id="coding",
                product_compatibility_id="compat-1",
                continuity_id=f"continuity-{session_id}",
                session_id=session_id,
                provider_id="canonical",
                locator_token=f"locator-{session_id}",
            )
        )
        for session_id in session_ids
    }
    product_identity = AdmissionIdentityV1(
        _GENERATION,
        AppHostAdmissionSubjectKind.PRODUCT,
        "coding",
    )
    profiles: dict[str, _ProfileFactory] = {}
    registrations: list[ProfileRegistrationV1] = []
    for profile_id in _PROFILE_IDS:
        identity = AdmissionIdentityV1(
            _GENERATION,
            AppHostAdmissionSubjectKind.PROFILE,
            profile_id,
        )
        profile = _ProfileFactory(profile_id, events)
        profiles[profile_id] = profile
        registrations.append(
            ProfileRegistrationV1(
                descriptor=ProfileDescriptorV1(profile_id, "1.0"),
                factory=profile,
                admission_identity=identity,
                admission_source=_Source(identity, events),
            )
        )
    rollback = _RollbackControl(events)
    composition = await create_coding_apphost_composition(
        CodingAppHostCompositionRequestV1(
            activation=CodingAppHostCompositionActivationV1(),
            generation_id=_GENERATION,
            product_version="1.0",
            compatibility_id="compat-1",
            product_admission_source=_Source(product_identity, events),
            candidate_validator=_Validator(),
            attempt_factory=attempt_factory,
            profiles=tuple(registrations),
            sessions=_Sessions(candidates),
            rollback_control=rollback,
            shutdown_budget=AppHostShutdownBudgetV1(2.0, 1.0),
        )
    )
    return _Environment(
        composition=composition,
        attempts=attempt_factory,
        candidates=candidates,
        profiles=profiles,
        rollback=rollback,
        events=events,
    )


async def _attach(
    environment: _Environment,
    session_id: str = "session-1",
    profile_id: str = "embedded-tui",
) -> Any:
    candidate = environment.candidates[session_id]
    return await environment.composition.attach_resume(
        reference=candidate.projection.reference,
        profile_id=profile_id,
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.mark.parametrize("_case", ("G9-COMPOSE-EXPLICIT",), ids=("G9-COMPOSE-EXPLICIT",))
def test_g9_compose_requires_explicit_hosting_activation(_case: str) -> None:
    async def scenario() -> None:
        environment = await _environment()
        assert environment.composition.activation.owner == "hosting"
        assert environment.attempts.attempts == []
        lease = await _attach(environment)
        binding = lease.profile_binding.opaque_binding
        assert isinstance(binding, CodingAppHostProductBindingV1)
        assert binding.effective_owner == "hosting"
        await lease.close()
        await environment.composition.close()

        with pytest.raises(TypeError):
            await create_coding_apphost_composition(cast(Any, object()))

    _run(scenario())


class _OwnerPort:
    def __init__(self, *, failure: bool = False) -> None:
        self.calls = 0
        self.failure = failure

    async def start(self, *args: object, **kwargs: object) -> Any:
        del args, kwargs
        self.calls += 1
        if self.failure:
            raise RuntimeError("selected owner failed")
        return cast(Any, object())


@pytest.mark.parametrize("_case", ("G9-OMISSION-CURRENT",), ids=("G9-OMISSION-CURRENT",))
def test_g9_omitted_owner_remains_current(_case: str) -> None:
    async def scenario() -> None:
        current = _OwnerPort()
        hosting = _OwnerPort()
        router = WorkerSessionOwnerRouter(current=current, hosting=hosting)
        await router.start(cast(Any, object()), correlation_id="g9-omission")
        assert router.selection.effective_owner == "current"
        assert current.calls == 1
        assert hosting.calls == 0

    _run(scenario())
    for path in _CURRENT_ROOTS.values():
        assert "apphost_composition" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "_case",
    ("G9-ROLLBACK-BEFORE-EFFECT",),
    ids=("G9-ROLLBACK-BEFORE-EFFECT",),
)
def test_g9_rollback_before_effect_is_default_dark_and_complete(_case: str) -> None:
    async def scenario() -> None:
        environment = await _environment()
        report = await environment.composition.rollback()
        assert report.completed
        assert report.rollback_latch is not None
        assert environment.attempts.attempts == []
        assert environment.rollback.calls == 1
        with pytest.raises(CodingAppHostCompositionError) as fenced:
            await _attach(environment)
        assert fenced.value.code == "coding_apphost_composition_fenced"

    _run(scenario())


@pytest.mark.parametrize(
    "_case",
    ("G9-ROLLBACK-INFLIGHT-STICKY",),
    ids=("G9-ROLLBACK-INFLIGHT-STICKY",),
)
def test_g9_rollback_drains_exact_inflight_hosting_attempt(_case: str) -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        attempts = _AttemptFactory(
            lambda key, index, events: _Attempt(
                _receipt(key.session_id),
                attempt_index=index,
                events=events,
                start_entered=entered,
                start_release=release,
            )
        )
        environment = await _environment(attempts)
        attach_task = asyncio.create_task(_attach(environment))
        await entered.wait()
        rollback_task = asyncio.create_task(environment.composition.rollback())
        await environment.rollback.entered.wait()
        assert environment.rollback.calls == 1
        assert not rollback_task.done()
        release.set()
        lease = await attach_task
        report = await rollback_task
        assert report.completed
        assert len(attempts.attempts) == 1
        assert attempts.attempts[0].close_calls == 1
        await lease.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_case",
    ("G9-ROLLBACK-NO-FALLBACK",),
    ids=("G9-ROLLBACK-NO-FALLBACK",),
)
def test_g9_failed_hosting_attempt_never_replays_current(_case: str) -> None:
    async def scenario() -> None:
        current = _OwnerPort()
        hosting = _OwnerPort(failure=True)
        router = WorkerSessionOwnerRouter(
            current=current,
            hosting=hosting,
            activation=WorkerHostingActivationV1(owner="hosting"),
        )
        with pytest.raises(RuntimeError):
            await router.start(cast(Any, object()), correlation_id="g9-no-fallback")
        assert hosting.calls == 1
        assert current.calls == 0

        attempts = _AttemptFactory(
            lambda key, index, events: _Attempt(
                _receipt(key.session_id),
                attempt_index=index,
                events=events,
                start_error=True,
            )
        )
        environment = await _environment(attempts)
        with pytest.raises(AppHostError):
            await _attach(environment)
        assert len(attempts.attempts) == 1
        assert attempts.attempts[0].close_calls == 1
        await environment.composition.rollback()

    _run(scenario())


@pytest.mark.parametrize(
    "_case",
    ("G9-ROLLBACK-DRAIN-ORDER",),
    ids=("G9-ROLLBACK-DRAIN-ORDER",),
)
def test_g9_rollback_orders_latch_drain_and_pin_retirement(_case: str) -> None:
    async def scenario() -> None:
        environment = await _environment()
        lease = await _attach(environment)
        report = await environment.composition.rollback()
        assert report.completed
        events = environment.events
        latch = events.index("rollback-latch")
        profile = events.index("profile-close:embedded-tui")
        worker = events.index("worker-close")
        product_pin = events.index("pin-close:coding")
        assert latch < profile < worker < product_pin
        await lease.close()

    _run(scenario())


@pytest.mark.parametrize("_case", ("G9-CRASH-RECOVERY",), ids=("G9-CRASH-RECOVERY",))
def test_g9_crash_recovery_closes_failed_attempt_before_successor(_case: str) -> None:
    async def scenario() -> None:
        attempts = _AttemptFactory(
            lambda key, index, events: _Attempt(
                _receipt(key.session_id),
                attempt_index=index,
                events=events,
                recover_error=index == 0,
            )
        )
        environment = await _environment(attempts)
        with pytest.raises(AppHostError):
            await _attach(environment)
        lease = await _attach(environment)
        assert len(attempts.attempts) == 2
        worker_events = [
            event
            for event in attempts.events
            if event in {"receipt:product", "recover", "worker-close", "start"}
        ]
        assert worker_events == [
            "receipt:product",
            "recover",
            "worker-close",
            "receipt:product",
            "recover",
            "start",
        ]
        assert attempts.attempts[0].close_calls == 1
        assert attempts.attempts[1].close_calls == 0
        await lease.close()
        await environment.composition.rollback()

    _run(scenario())


@pytest.mark.parametrize(
    "_case",
    ("G9-CLEANUP-DEBT-RETRY",),
    ids=("G9-CLEANUP-DEBT-RETRY",),
)
def test_g9_cleanup_debt_retries_exact_owner_without_relatching(_case: str) -> None:
    async def scenario() -> None:
        attempts = _AttemptFactory(
            lambda key, index, events: _Attempt(
                _receipt(key.session_id),
                attempt_index=index,
                events=events,
                close_failures=1,
            )
        )
        environment = await _environment(attempts)
        lease = await _attach(environment)
        first = await environment.composition.rollback()
        assert not first.completed
        assert first.failed_phases == ("apphost_shutdown",)
        second = await environment.composition.rollback()
        assert second.completed
        assert environment.rollback.calls == 1
        assert attempts.attempts[0].close_calls == 2
        await lease.close()

    _run(scenario())


def test_emergency_rollback_upgrades_an_inflight_normal_close() -> None:
    async def scenario() -> None:
        close_entered = asyncio.Event()
        close_release = asyncio.Event()
        attempts = _AttemptFactory(
            lambda key, index, events: _Attempt(
                _receipt(key.session_id),
                attempt_index=index,
                events=events,
                close_entered=close_entered,
                close_release=close_release,
            )
        )
        environment = await _environment(attempts)
        lease = await _attach(environment)
        close_task = asyncio.create_task(environment.composition.close())
        await close_entered.wait()
        rollback_task = asyncio.create_task(environment.composition.rollback())
        await environment.rollback.entered.wait()
        assert environment.rollback.calls == 1
        assert not close_task.done()
        close_release.set()
        await close_task
        report = await rollback_task
        assert report.completed
        assert attempts.attempts[0].close_calls == 1
        await lease.close()

    _run(scenario())


def test_failed_rollback_latch_is_reported_and_retried() -> None:
    async def scenario() -> None:
        environment = await _environment()
        environment.rollback.failures = 1
        first = await environment.composition.rollback()
        assert not first.completed
        assert first.failed_phases == ("rollback_latch",)
        assert first.apphost_shutdown is not None
        assert first.apphost_shutdown.completed
        second = await environment.composition.rollback()
        assert second.completed
        assert environment.rollback.calls == 2

    _run(scenario())


def test_cancelled_rollback_caller_does_not_cancel_owned_settlement() -> None:
    async def scenario() -> None:
        environment = await _environment()
        release = asyncio.Event()
        environment.rollback.release = release
        caller = asyncio.create_task(environment.composition.rollback())
        await environment.rollback.entered.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        release.set()
        report = await environment.composition.rollback()
        assert report.completed
        assert environment.rollback.calls == 1

    _run(scenario())


@pytest.mark.parametrize(
    "_case",
    ("G9-MULTIPROFILE-SINGLE-FLIGHT",),
    ids=("G9-MULTIPROFILE-SINGLE-FLIGHT",),
)
def test_g9_multiple_profiles_share_one_session_attempt(_case: str) -> None:
    async def scenario() -> None:
        environment = await _environment()
        first, second = await asyncio.gather(
            _attach(environment, profile_id="embedded-tui"),
            _attach(environment, profile_id="hosted-app"),
        )
        assert len(environment.attempts.attempts) == 1
        await first.close()
        await second.close()
        assert environment.attempts.attempts[0].close_calls == 0
        await environment.composition.close_session(first.binding_key)
        assert environment.attempts.attempts[0].close_calls == 1
        await environment.composition.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_case",
    ("G9-MULTISESSION-ISOLATION",),
    ids=("G9-MULTISESSION-ISOLATION",),
)
def test_g9_session_close_cannot_retire_another_session(_case: str) -> None:
    async def scenario() -> None:
        environment = await _environment(session_ids=("session-1", "session-2"))
        first, second = await asyncio.gather(
            _attach(environment, "session-1"),
            _attach(environment, "session-2"),
        )
        assert len(environment.attempts.attempts) == 2
        await first.close()
        await environment.composition.close_session(first.binding_key)
        assert sum(attempt.close_calls for attempt in environment.attempts.attempts) == 1
        assert second.binding_key.session_id == "session-2"
        await second.close()
        await environment.composition.rollback()
        assert all(attempt.close_calls == 1 for attempt in environment.attempts.attempts)

    _run(scenario())


class _CoordinatorAuthority:
    def __init__(self, receipt: ProductWorkerActivationReceiptV1) -> None:
        self._lock = threading.RLock()
        self.witness = receipt.authority_witness
        self.in_gate = False
        self.evidence_authority = _CoordinatorEvidence()

    def serialized_admission(self) -> AbstractContextManager[None]:
        authority = self

        class _Gate(AbstractContextManager[None]):
            def __enter__(self) -> None:
                authority._lock.acquire()
                authority.in_gate = True

            def __exit__(self, *args: object) -> None:
                del args
                authority.in_gate = False
                authority._lock.release()

        return _Gate()

    def current_witness(
        self,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> tuple[str, str, str, int, int]:
        assert self.in_gate
        del receipt
        return self.witness

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        assert self.in_gate
        if self.witness[-1] == expected_generation:
            self.witness = (*self.witness[:-1], expected_generation + 1)
        return expected_generation + 1


class _CoordinatorEvidence:
    authority_id = "g9-cleanup-evidence"
    authority_fingerprint = "e" * 64

    def verify_tree_settlement(self, **facts: object) -> bool:
        del facts
        return True

    def verify_changed_boot_absence(self, **facts: object) -> bool:
        del facts
        return True

    def verify_registered_lease_expired(self, **facts: object) -> bool:
        del facts
        return True


def _coordinator(
    *,
    store: _MemoryActivationStateStore,
    receipt: ProductWorkerActivationReceiptV1,
    authority: _CoordinatorAuthority | None = None,
) -> tuple[ProductWorkerActivationCoordinator, _CoordinatorAuthority]:
    authority = authority or _CoordinatorAuthority(receipt)
    evidence = authority.evidence_authority
    return (
        ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=evidence,
            trusted_evidence_authority_id=evidence.authority_id,
            trusted_evidence_authority_fingerprint=evidence.authority_fingerprint,
            state_store=store,
        ),
        authority,
    )


@pytest.mark.parametrize(
    "_case",
    ("G9-RESTART-GENERATION",),
    ids=("G9-RESTART-GENERATION",),
)
def test_g9_restart_retains_durable_kill_switch_generation(_case: str) -> None:
    receipt = _receipt("session-1")
    store = _MemoryActivationStateStore()
    coordinator, authority = _coordinator(store=store, receipt=receipt)
    assert coordinator.latch_kill_switch(expected_generation=2) == ()
    restarted, _ = _coordinator(
        store=store,
        receipt=receipt,
        authority=authority,
    )
    snapshot = restarted.snapshot()
    assert snapshot["killSwitchState"] == "completed"
    assert snapshot["killSwitchGeneration"] == 3
    assert restarted.latch_kill_switch(expected_generation=2) == ()


@pytest.mark.parametrize(
    "_case",
    ("G9-ENTRYPOINT-INVENTORY",),
    ids=("G9-ENTRYPOINT-INVENTORY",),
)
def test_g9_entrypoint_inventory_is_exact_and_source_backed(_case: str) -> None:
    inventory = json.loads(_INVENTORY.read_text(encoding="utf-8"))
    assert set(inventory) == {"inventoryVersion", "entries"}
    assert inventory["inventoryVersion"] == 1
    entries = {entry["entrypointId"]: entry for entry in inventory["entries"]}
    assert set(entries) == {"coding.apphost.composition", *_CURRENT_ROOTS}
    for entrypoint_id, row in entries.items():
        path = Path(row["source"])
        assert path.is_file()
        imports_composition = "apphost_composition" in path.read_text(encoding="utf-8")
        if entrypoint_id == "coding.apphost.composition":
            assert row["disposition"] == "explicit-hosting"
            assert row["importsComposition"] is True
            assert path == _COMPOSITION
        else:
            assert row["disposition"] == "current-only"
            assert row["importsComposition"] is False
            assert not imports_composition


def _imports(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    package = path.parent.relative_to("src").parts
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            retained = len(package) - (node.level - 1) if node.level else 0
            parts = (
                (*package[:retained], *(node.module or "").split("."))
                if node.level
                else tuple((node.module or "").split("."))
            )
            if parts:
                imported.add(".".join(part for part in parts if part))
    return imported


@pytest.mark.parametrize(
    "_case",
    ("G9-DEPENDENCY-GRAPH",),
    ids=("G9-DEPENDENCY-GRAPH",),
)
def test_g9_composition_has_the_only_accepted_dependency_edge(_case: str) -> None:
    imports = _imports(_COMPOSITION)
    assert imports & {"loushang.apphost"} == {"loushang.apphost"}
    assert "loushang.coding.apphost_product" in imports
    forbidden = ("loushang.hosting", "loushang.appserver", "loushang.harnessgui")
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imports
        for prefix in forbidden
    )
    for path in Path("src/loushang").rglob("*.py"):
        if path != _COMPOSITION:
            assert "apphost_composition" not in path.read_text(encoding="utf-8")
    for path in Path("src/loushang/apphost").rglob("*.py"):
        assert not any(
            module == "loushang.coding" or module.startswith("loushang.coding.")
            for module in _imports(path)
        )
