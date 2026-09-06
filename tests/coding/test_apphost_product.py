from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from loushang.apphost import (
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostCatalogInputV1,
    AppHostCatalogV1,
    AppHostError,
    AppHostFailureCategory,
    AppHostRuntimeV1,
    ProductDescriptorV1,
    ProductRegistrationV1,
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
    CodingProductWorkerCanary,
    CodingProductWorkerCanaryStatusV1,
)
from loushang.coding.apphost_product import (
    CodingAppHostProductBindingV1,
    CodingAppHostProductError,
    CodingAppHostProductFactoryV1,
    CodingAppHostWorkerAttemptV1,
    coding_apphost_product_registration,
)
from loushang.harness.worker import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64


def _policy(
    session_id: str,
    *,
    product_id: str = "coding",
    required: bool = True,
) -> ProductWorkerActivationPolicyV1:
    return ProductWorkerActivationPolicyV1(
        product_id=product_id,
        product_runtime_id=f"runtime-{session_id}",
        product_scope_id=f"session.{session_id}",
        session_id=session_id,
        session_route="new",
        selected_locator_fingerprint=None,
        selected_locator_revision="new-session",
        plugin_id="review-pack",
        plugin_revision_digest=_DIGEST_A,
        contribution_id="review-provider",
        reservation_fingerprint=_DIGEST_B,
        declaration_fingerprint=_DIGEST_C,
        worker_configuration_fingerprint=_DIGEST_A,
        declared_required=required,
        effective_required=required,
        enabled=True,
        allowed_product_ids=(product_id,),
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


def _receipt(
    session_id: str,
    *,
    product_id: str = "coding",
    required: bool = True,
) -> ProductWorkerActivationReceiptV1:
    return ProductWorkerActivationReceiptV1(
        policy=_policy(session_id, product_id=product_id, required=required),
        issue_sequence=1,
        issue_nonce=f"receipt-{session_id}",
    )


def _status(
    receipt: ProductWorkerActivationReceiptV1,
    *,
    readiness: str = "ready",
) -> CodingProductWorkerCanaryStatusV1:
    return CodingProductWorkerCanaryStatusV1(
        code=(
            "coding_worker_ready"
            if readiness == "ready"
            else "coding_worker_optional_degraded"
        ),
        readiness=readiness,  # type: ignore[arg-type]
        required=receipt.policy.effective_required,
        requested_owner="hosting",
        effective_owner="hosting",
        receipt_fingerprint=receipt.fingerprint,
        attempt_id="d" * 32,
        owner_generation=receipt.policy.owner_selection_generation,
    )


class _Attempt:
    def __init__(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        *,
        readiness: str = "ready",
        recover_error: bool = False,
        start_error: bool = False,
        close_failures: int = 0,
        close_entered: asyncio.Event | None = None,
        close_release: asyncio.Event | None = None,
        start_entered: asyncio.Event | None = None,
        start_release: asyncio.Event | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.activation_receipt = receipt
        self._status = _status(receipt, readiness=readiness)
        self.recover_error = recover_error
        self.start_error = start_error
        self.close_failures = close_failures
        self.close_entered = close_entered
        self.close_release = close_release
        self.start_entered = start_entered
        self.start_release = start_release
        self.events = [] if events is None else events
        self.close_calls = 0
        self.entrypoints: list[str] = []

    @property
    def status(self) -> CodingProductWorkerCanaryStatusV1:
        return self._status

    def receipt_for_entrypoint(
        self,
        entrypoint: str,
    ) -> ProductWorkerActivationReceiptV1:
        self.entrypoints.append(entrypoint)
        self.events.append(f"receipt:{entrypoint}")
        return self.activation_receipt

    async def recover(self) -> tuple[str, ...]:
        self.events.append("recover")
        if self.recover_error:
            raise RuntimeError("/secret/recovery")
        return ("recovered",)

    async def start(
        self,
        *,
        correlation_id: str,
    ) -> CodingProductWorkerCanaryStatusV1:
        assert correlation_id == "g8-correlation"
        self.events.append("start")
        if self.start_entered is not None:
            self.start_entered.set()
        if self.start_release is not None:
            await self.start_release.wait()
        if self.start_error:
            raise RuntimeError("/secret/start")
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
            raise RuntimeError("/secret/close")


AttemptBuilder = Callable[[SessionBindingKeyV1, int], _Attempt]


class _AttemptFactory:
    def __init__(self, builder: AttemptBuilder | None = None) -> None:
        self.builder = builder or (
            lambda key, index: _Attempt(_receipt(key.session_id))
        )
        self.attempts: list[_Attempt] = []
        self.opaque_bindings: list[object] = []

    def create_attempt(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        opaque_session_binding: object,
    ) -> CodingAppHostWorkerAttemptV1:
        self.opaque_bindings.append(opaque_session_binding)
        attempt = self.builder(binding_key, len(self.attempts))
        self.attempts.append(attempt)
        return attempt


class _ReadyCanaryRecovery:
    async def recover(self, **facts: object) -> tuple[str, ...]:
        del facts
        return (
            "V1-PRIOR-ABSENT",
            "V2-EXACT-REAPED",
            "V3-SAMEBOOT-UNKNOWN",
            "V4-CHANGEDBOOT-ABSENT",
            "V5-BUDGET-EXHAUSTED",
            "V6-HOST-RESTART",
        )


class _ReadyCanaryDomain:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def fence_attempt(self, **facts: object) -> None:
        del facts
        self.events.append("domain-fence")

    async def revoke_and_drain(self, **facts: object) -> None:
        del facts
        self.events.append("domain-drain")

    async def settle_readiness(self, **facts: object) -> None:
        del facts
        self.events.append("readiness-settle")


class _ReadyCanaryCoordinator:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def retire_exact(self, **facts: object) -> None:
        del facts
        self.events.append("attempt-retire")

    def record_protocol_terminal(self, **facts: object) -> None:
        del facts
        self.events.append("protocol-terminal")


class _ReadyCanarySupervisor:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def shutdown(self, *, reason: str) -> None:
        assert reason == "coding_product_session_close"
        self.events.append("supervisor-shutdown")

    async def fence(self, *, code: str) -> None:
        raise AssertionError(f"healthy close must not fence: {code}")


class _ReadyCanaryNativeProfile:
    cleanup_contract_version = 1

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def close(self) -> None:
        self.events.append("native-close")


class _ReadyCanaryCleanup:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def settle(self, **facts: object) -> None:
        assert facts["protocol_terminal"] is True
        assert facts["domain_retired"] is True
        self.events.append("cleanup-settle")


class _SingleCanaryFactory:
    def __init__(self, canary: CodingProductWorkerCanary) -> None:
        self.canary = canary
        self.calls = 0

    def create_attempt(self, **facts: object) -> CodingProductWorkerCanary:
        assert facts["binding_key"] == SessionBindingKeyV1(
            "coding",
            "continuity-session-1",
            "session-1",
        )
        self.calls += 1
        return self.canary


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


def _opened(session_id: str = "session-1") -> _Opened:
    return _Opened(
        SessionBindingKeyV1("coding", f"continuity-{session_id}", session_id),
        object(),
    )


class _Pin:
    def __init__(
        self,
        identity: AdmissionIdentityV1,
        events: list[str],
    ) -> None:
        self._identity = identity
        self.events = events
        self.closed = 0

    @property
    def identity(self) -> AdmissionIdentityV1:
        return self._identity

    async def close(self) -> None:
        self.closed += 1
        self.events.append(f"pin-close:{self._identity.subject_id}")


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
                "canonical",
                envelope.session_id,
                "revision-1",
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
        return tuple(item.projection for item in self.candidates.values())[:limit]

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
        raise AssertionError("G8 resume tests do not create Session candidates")


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


class _ProfileLease:
    def __init__(self, profile_id: str, binding: object, events: list[str]) -> None:
        self._profile_id = profile_id
        self._binding = binding
        self.events = events
        self.closed = 0

    @property
    def profile_id(self) -> str:
        return self._profile_id

    @property
    def profile_binding(self) -> object:
        return self._binding

    async def close(self) -> None:
        if not self.closed:
            self.events.append(f"profile-close:{self._profile_id}")
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


class _PlainProfileBinding:
    def __init__(self, key: SessionBindingKeyV1) -> None:
        self._key = key

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._key

    @property
    def opaque_binding(self) -> object:
        return "plain-product"


class _PlainRuntime:
    def __init__(self, key: SessionBindingKeyV1, events: list[str]) -> None:
        self._key = key
        self._profile = _PlainProfileBinding(key)
        self.events = events

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._key

    @property
    def profile_binding(self) -> _PlainProfileBinding:
        return self._profile

    async def close(self) -> None:
        self.events.append("plain-close")


class _PlainFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0

    async def create_runtime(self, candidate: _Opened) -> _PlainRuntime:
        self.calls += 1
        return _PlainRuntime(candidate.binding_key, self.events)


@dataclass
class _Environment:
    runtime: AppHostRuntimeV1
    catalog: AppHostCatalogV1
    attempts: _AttemptFactory
    product_factory: CodingAppHostProductFactoryV1
    candidates: dict[str, _Candidate]
    profiles: dict[str, _ProfileFactory]
    events: list[str]
    plain: _PlainFactory


async def _environment(
    attempts: _AttemptFactory | None = None,
    *,
    sessions: tuple[tuple[str, str], ...] = (("coding", "session-1"),),
) -> _Environment:
    events: list[str] = []
    attempt_factory = attempts or _AttemptFactory()
    generation_id = "generation-g8"
    profile_ids = ("embedded-tui", "hosted-app")
    candidates = {
        session_id: _Candidate(
            SessionIdentityEnvelopeV1(
                product_id=product_id,
                product_compatibility_id="compat-1",
                continuity_id=f"continuity-{session_id}",
                session_id=session_id,
                provider_id="canonical",
                locator_token=f"locator-{session_id}",
            )
        )
        for product_id, session_id in sessions
    }
    coding_identity = AdmissionIdentityV1(
        generation_id,
        AppHostAdmissionSubjectKind.PRODUCT,
        "coding",
    )
    coding_source = _Source(coding_identity, events)
    product_factory = CodingAppHostProductFactoryV1(
        attempt_factory,
        correlation_id_factory=lambda: "g8-correlation",
    )
    coding_registration = coding_apphost_product_registration(
        generation_id=generation_id,
        product_version="1.0",
        compatibility_id="compat-1",
        supported_profile_ids=profile_ids,
        admission_source=coding_source,
        candidate_validator=_Validator(),
        product_factory=product_factory,
    )
    assert coding_registration.factory is product_factory
    products = [coding_registration]
    plain = _PlainFactory(events)
    if any(product_id == "work" for product_id, _ in sessions):
        plain_identity = AdmissionIdentityV1(
            generation_id,
            AppHostAdmissionSubjectKind.PRODUCT,
            "work",
        )
        products.append(
            ProductRegistrationV1(
                descriptor=ProductDescriptorV1(
                    "work",
                    "1.0",
                    "compat-1",
                    profile_ids,
                ),
                factory=plain,
                candidate_validator=_Validator(),
                admission_identity=plain_identity,
                admission_source=_Source(plain_identity, events),
            )
        )
    profiles: dict[str, _ProfileFactory] = {}
    profile_regs = []
    for profile_id in profile_ids:
        identity = AdmissionIdentityV1(
            generation_id,
            AppHostAdmissionSubjectKind.PROFILE,
            profile_id,
        )
        factory = _ProfileFactory(profile_id, events)
        profiles[profile_id] = factory
        profile_regs.append(
            ProfileRegistrationV1(
                descriptor=ProfileDescriptorV1(profile_id, "1.0"),
                factory=factory,
                admission_identity=identity,
                admission_source=_Source(identity, events),
            )
        )
    catalog = await AppHostCatalogV1.admit(
        AppHostCatalogInputV1(
            generation_id=generation_id,
            products=tuple(products),
            profiles=tuple(profile_regs),
        )
    )
    return _Environment(
        runtime=AppHostRuntimeV1(catalog, _Sessions(candidates)),
        catalog=catalog,
        attempts=attempt_factory,
        product_factory=product_factory,
        candidates=candidates,
        profiles=profiles,
        events=events,
        plain=plain,
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "_g8_case",
    (
        "G8-EXACT-RECEIPT",
        "G8-RECOVERY-FIRST",
        "G8-REQUIRED-READY",
        "G8-CROSS-ENTRYPOINT",
    ),
    ids=(
        "G8-EXACT-RECEIPT",
        "G8-RECOVERY-FIRST",
        "G8-REQUIRED-READY",
        "G8-CROSS-ENTRYPOINT",
    ),
)
def test_g8_exact_receipt_recovery_first_required_ready_and_cross_entrypoint(
    _g8_case: str,
) -> None:
    async def scenario() -> None:
        events: list[str] = []
        attempts = _AttemptFactory(
            lambda key, index: _Attempt(_receipt(key.session_id), events=events)
        )
        environment = await _environment(attempts)
        candidate = environment.candidates["session-1"]
        lease = await environment.runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )

        assert events[:3] == ["receipt:product", "recover", "start"]
        assert attempts.attempts[0].entrypoints == ["product"]
        profile_view = lease.profile_binding
        binding = profile_view.opaque_binding
        assert isinstance(binding, CodingAppHostProductBindingV1)
        assert binding.binding_key == lease.binding_key
        assert binding.receipt_fingerprint == attempts.attempts[0].activation_receipt.fingerprint
        assert binding.required is True
        assert binding.readiness == "ready"

        await lease.close()
        assert attempts.attempts[0].close_calls == 0
        await environment.runtime.close_session(lease.binding_key)
        assert attempts.attempts[0].close_calls == 1
        await environment.runtime.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-RECEIPT-MISMATCH",),
    ids=("G8-RECEIPT-MISMATCH",),
)
def test_g8_receipt_mismatch_and_recovery_failure_are_closed_before_effect(
    _g8_case: str,
) -> None:
    async def scenario() -> None:
        mismatch = _AttemptFactory(
            lambda key, index: _Attempt(_receipt("foreign-session"))
        )
        factory = CodingAppHostProductFactoryV1(
            mismatch,
            correlation_id_factory=lambda: "g8-correlation",
        )
        with pytest.raises(CodingAppHostProductError) as rejected:
            await factory.create_runtime(_opened())
        assert rejected.value.code == "coding_apphost_receipt_mismatch"
        assert mismatch.attempts[0].events == ["receipt:product", "worker-close"]

        recovery = _AttemptFactory(
            lambda key, index: _Attempt(
                _receipt(key.session_id),
                recover_error=True,
            )
        )
        factory = CodingAppHostProductFactoryV1(
            recovery,
            correlation_id_factory=lambda: "g8-correlation",
        )
        with pytest.raises(CodingAppHostProductError) as unavailable:
            await factory.create_runtime(_opened())
        assert unavailable.value.code == "coding_apphost_runtime_unavailable"
        assert recovery.attempts[0].events == [
            "receipt:product",
            "recover",
            "worker-close",
        ]

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-OPTIONAL-DEGRADED",),
    ids=("G8-OPTIONAL-DEGRADED",),
)
def test_g8_optional_degraded_is_explicit_and_never_falls_back(
    _g8_case: str,
) -> None:
    async def scenario() -> None:
        attempts = _AttemptFactory(
            lambda key, index: _Attempt(
                _receipt(key.session_id, required=False),
                readiness="degraded",
            )
        )
        factory = CodingAppHostProductFactoryV1(
            attempts,
            correlation_id_factory=lambda: "g8-correlation",
        )
        runtime = await factory.create_runtime(_opened())
        binding = runtime.profile_binding.opaque_binding
        assert isinstance(binding, CodingAppHostProductBindingV1)
        assert binding.required is False
        assert binding.readiness == "degraded"
        assert binding.requested_owner == binding.effective_owner == "hosting"
        await runtime.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-UNRELATED-WORKER-FREE",),
    ids=("G8-UNRELATED-WORKER-FREE",),
)
def test_g8_unrelated_product_is_worker_free(_g8_case: str) -> None:
    async def scenario() -> None:
        environment = await _environment(
            sessions=(("work", "work-session"),)
        )
        candidate = environment.candidates["work-session"]
        lease = await environment.runtime.attach_resume(
            product_id="work",
            reference=candidate.projection.reference,
            profile_id="hosted-app",
        )
        assert environment.plain.calls == 1
        assert environment.attempts.attempts == []
        await lease.close()
        await environment.runtime.close_session(lease.binding_key)
        await environment.runtime.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-MULTIPROFILE-SINGLE-FLIGHT", "G8-DETACH-NONOWNING"),
    ids=("G8-MULTIPROFILE-SINGLE-FLIGHT", "G8-DETACH-NONOWNING"),
)
def test_g8_multiprofile_single_flight_and_detach_is_nonowning(
    _g8_case: str,
) -> None:
    async def scenario() -> None:
        environment = await _environment()
        candidate = environment.candidates["session-1"]
        first, second = await asyncio.gather(
            environment.runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            ),
            environment.runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="hosted-app",
            ),
        )
        assert first.binding_key == second.binding_key
        assert len(environment.attempts.attempts) == 1
        await asyncio.gather(first.close(), second.close())
        assert environment.attempts.attempts[0].close_calls == 0
        await environment.runtime.close_session(first.binding_key)
        assert environment.attempts.attempts[0].close_calls == 1
        await environment.runtime.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-MULTISESSION-ISOLATION",),
    ids=("G8-MULTISESSION-ISOLATION",),
)
def test_g8_concurrent_multisession_attempts_are_isolated(_g8_case: str) -> None:
    async def scenario() -> None:
        entered = {"session-1": asyncio.Event(), "session-2": asyncio.Event()}
        release = asyncio.Event()
        attempts = _AttemptFactory(
            lambda key, index: _Attempt(
                _receipt(key.session_id),
                start_entered=entered[key.session_id],
                start_release=release,
            )
        )
        environment = await _environment(
            attempts,
            sessions=(("coding", "session-1"), ("coding", "session-2")),
        )
        tasks = [
            asyncio.create_task(
                environment.runtime.attach_resume(
                    product_id="coding",
                    reference=environment.candidates[session_id].projection.reference,
                    profile_id="embedded-tui",
                )
            )
            for session_id in ("session-1", "session-2")
        ]
        await asyncio.gather(*(event.wait() for event in entered.values()))
        assert all(attempt.close_calls == 0 for attempt in attempts.attempts)
        release.set()
        leases = await asyncio.gather(*tasks)
        assert len(attempts.attempts) == 2

        await asyncio.gather(*(lease.close() for lease in leases))
        await environment.runtime.close_session(leases[0].binding_key)
        assert [attempt.close_calls for attempt in attempts.attempts] == [1, 0]
        await environment.runtime.close_session(leases[1].binding_key)
        assert [attempt.close_calls for attempt in attempts.attempts] == [1, 1]
        await environment.runtime.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-STALE-DETACH",),
    ids=("G8-STALE-DETACH",),
)
def test_g8_stale_detach_cannot_close_successor_attempt(_g8_case: str) -> None:
    async def scenario() -> None:
        environment = await _environment()
        candidate = environment.candidates["session-1"]
        stale = await environment.runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        await stale.close()
        await environment.runtime.close_session(stale.binding_key)
        successor = await environment.runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        assert len(environment.attempts.attempts) == 2
        await stale.close()
        assert environment.attempts.attempts[1].close_calls == 0
        await successor.close()
        await environment.runtime.close_session(successor.binding_key)
        assert environment.attempts.attempts[1].close_calls == 1
        await environment.runtime.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-CANCEL-COMPENSATION",),
    ids=("G8-CANCEL-COMPENSATION",),
)
def test_g8_cancellation_compensates_unpublished_attempt(_g8_case: str) -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        close_entered = asyncio.Event()
        close_release = asyncio.Event()
        attempts = _AttemptFactory(
            lambda key, index: _Attempt(
                _receipt(key.session_id),
                start_entered=entered,
                start_release=release,
                close_entered=close_entered,
                close_release=close_release,
            )
        )
        factory = CodingAppHostProductFactoryV1(
            attempts,
            correlation_id_factory=lambda: "g8-correlation",
        )
        task = asyncio.create_task(factory.create_runtime(_opened()))
        await entered.wait()
        task.cancel()
        await close_entered.wait()
        task.cancel()
        assert not task.done()
        close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert attempts.attempts[0].close_calls == 1
        assert factory.pending_cleanup_count == 0

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-START-FAIL-NO-FALLBACK",),
    ids=("G8-START-FAIL-NO-FALLBACK",),
)
def test_g8_failed_start_is_not_cached_and_fresh_retry_succeeds(
    _g8_case: str,
) -> None:
    async def scenario() -> None:
        attempts = _AttemptFactory(
            lambda key, index: _Attempt(
                _receipt(key.session_id),
                start_error=index == 0,
            )
        )
        environment = await _environment(attempts)
        candidate = environment.candidates["session-1"]
        with pytest.raises(AppHostError) as unavailable:
            await environment.runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            )
        assert unavailable.value.category is AppHostFailureCategory.RUNTIME_UNAVAILABLE
        assert "/secret/start" not in str(unavailable.value)
        lease = await environment.runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        assert len(attempts.attempts) == 2
        assert attempts.attempts[0].close_calls == 1
        assert attempts.attempts[1].events == [
            "receipt:product",
            "recover",
            "start",
        ]
        await lease.close()
        await environment.runtime.close_session(lease.binding_key)
        await environment.runtime.close()

    _run(scenario())


def test_g8_unpublished_cleanup_debt_blocks_new_effect_until_retry() -> None:
    async def scenario() -> None:
        attempts = _AttemptFactory(
            lambda key, index: _Attempt(
                _receipt("foreign-session") if index == 0 else _receipt(key.session_id),
                close_failures=1 if index == 0 else 0,
            )
        )
        factory = CodingAppHostProductFactoryV1(
            attempts,
            correlation_id_factory=lambda: "g8-correlation",
        )
        with pytest.raises(CodingAppHostProductError) as rejected:
            await factory.create_runtime(_opened())
        assert rejected.value.code == "coding_apphost_cleanup_incomplete"
        assert factory.pending_cleanup_count == 1

        runtime = await factory.create_runtime(_opened())
        assert attempts.attempts[0].close_calls == 2
        assert factory.pending_cleanup_count == 0
        await runtime.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-CLOSE-DEBT-RETRY",),
    ids=("G8-CLOSE-DEBT-RETRY",),
)
def test_g8_apphost_close_debt_is_retryable_and_retains_exact_slot(
    _g8_case: str,
) -> None:
    async def scenario() -> None:
        attempts = _AttemptFactory(
            lambda key, index: _Attempt(
                _receipt(key.session_id),
                close_failures=1,
            )
        )
        environment = await _environment(attempts)
        candidate = environment.candidates["session-1"]
        lease = await environment.runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        await lease.close()
        with pytest.raises(AppHostError) as incomplete:
            await environment.runtime.close_session(lease.binding_key)
        assert incomplete.value.category is AppHostFailureCategory.CLEANUP_INCOMPLETE
        assert "/secret/close" not in str(incomplete.value)
        assert attempts.attempts[0].close_calls == 1
        await environment.runtime.close_session(lease.binding_key)
        assert attempts.attempts[0].close_calls == 2
        await environment.runtime.close()

    _run(scenario())


@pytest.mark.parametrize(
    "_g8_case",
    ("G8-SHUTDOWN-ORDER",),
    ids=("G8-SHUTDOWN-ORDER",),
)
def test_g8_shutdown_closes_profiles_before_worker_and_generation_pins(
    _g8_case: str,
) -> None:
    async def scenario() -> None:
        events: list[str] = []
        attempts = _AttemptFactory(
            lambda key, index: _Attempt(_receipt(key.session_id), events=events)
        )
        environment = await _environment(attempts)
        # Share one event ledger with AppHost profile/pin fixtures.
        attempts.attempts.clear()
        attempts.builder = lambda key, index: _Attempt(
            _receipt(key.session_id),
            events=environment.events,
        )
        candidate = environment.candidates["session-1"]
        await environment.runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="hosted-app",
        )
        await environment.runtime.close()

        profile_index = environment.events.index("profile-close:hosted-app")
        worker_index = environment.events.index("worker-close")
        pin_indices = [
            index
            for index, event in enumerate(environment.events)
            if event.startswith("pin-close:")
        ]
        assert profile_index < worker_index < min(pin_indices)

    _run(scenario())


def test_g8_real_coding_canary_joins_and_closes_through_product_factory() -> None:
    async def scenario() -> None:
        receipt = _receipt("session-1")
        events: list[str] = []
        request = SimpleNamespace(
            identity=SimpleNamespace(
                attempt_id="d" * 32,
                owner_generation=receipt.policy.owner_selection_generation,
            )
        )
        canary = CodingProductWorkerCanary(
            policy=receipt.policy,
            receipt=receipt,
            coordinator=_ReadyCanaryCoordinator(events),  # type: ignore[arg-type]
            supervisor=_ReadyCanarySupervisor(events),  # type: ignore[arg-type]
            request=request,  # type: ignore[arg-type]
            session_port=object(),  # type: ignore[arg-type]
            native_profile=_ReadyCanaryNativeProfile(events),  # type: ignore[arg-type]
            capability_binding=object(),  # type: ignore[arg-type]
            capability_authority_reader=lambda: object(),  # type: ignore[arg-type]
            domain=_ReadyCanaryDomain(events),  # type: ignore[arg-type]
            cleanup=_ReadyCanaryCleanup(events),  # type: ignore[arg-type]
            recovery=_ReadyCanaryRecovery(),  # type: ignore[arg-type]
            host_identity="host-one",
            boot_identity="boot-one",
            status=_status(receipt),
        )
        attempt_factory = _SingleCanaryFactory(canary)
        factory = CodingAppHostProductFactoryV1(
            attempt_factory,
            correlation_id_factory=lambda: "g8-correlation",
        )

        runtime = await factory.create_runtime(_opened())
        binding = runtime.profile_binding.opaque_binding
        assert type(canary) is CodingProductWorkerCanary
        assert isinstance(binding, CodingAppHostProductBindingV1)
        assert binding.receipt_fingerprint == receipt.fingerprint
        assert binding.readiness == "ready"
        assert attempt_factory.calls == 1

        await runtime.close()
        assert events == [
            "domain-fence",
            "domain-drain",
            "attempt-retire",
            "supervisor-shutdown",
            "protocol-terminal",
            "native-close",
            "cleanup-settle",
            "readiness-settle",
        ]

    _run(scenario())


def test_g8_concrete_canary_satisfies_attempt_port_shape() -> None:
    for name in ("receipt_for_entrypoint", "recover", "start", "close"):
        assert callable(getattr(CodingProductWorkerCanary, name))
