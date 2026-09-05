from __future__ import annotations

import asyncio
import json
import os
import platform
from dataclasses import replace
from pathlib import Path

import pytest

import loushang.coding._product_worker_canary as canary_module
from loushang.coding._product_worker_canary import (
    CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
    CodingProductWorkerCanaryError,
    bind_coding_product_worker_canary,
)
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.transcript.discovery import SessionLocator
from loushang.harness.worker import (
    ManagedWorkerLaunchRequestV1,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
    WorkerBindingError,
    WorkerRuntimeBindingV1,
    WorkerSupervisor,
)
from loushang.harness.worker._native_profile_bridge import (
    _plan_windows_lpac_product_worker_profile,
    _WindowsLpacProductWorkerProfilePlan,
)
from loushang.harness.worker.journal import WorkerSupervisorJournal
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    WorkerCleanupSettlementV2,
)
from tests.harness.worker import test_coding_product_worker_canary as linux_product
from tests.hosting.test_windows_lpac_preparation_native import (
    _NATIVE_PLATFORM_IMPORTS,
    _compile_fixture,
)

pytestmark = [
    pytest.mark.skipif(
        os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"},
        reason="PLC9C5 C5.5c requires Windows AMD64 Product composition",
    ),
    pytest.mark.skipif(
        os.environ.get("LOUSHANG_PLC9C5_C55C_REPORT") != "1",
        reason="PLC9C5 C5.5c report runs only in its explicit Product gate",
    ),
]

PLC9C5_C55C_CASES = (
    "C55C-PRODUCT-SELECTED",
    "C55C-PRODUCT-MISSING",
    "C55C-PRODUCT-WRONG",
    "C55C-PRODUCT-DISABLED",
    "C55C-SESSION-CANONICAL",
    "C55C-SESSION-CWD",
    "C55C-SESSION-HOME",
    "C55C-SESSION-TAMPERED",
    "C55C-SESSION-ALIAS",
    "C55C-SESSION-CONFLICT",
    "C55C-SESSION-CHANGED",
    "C55C-REQUIRED-SUCCESS",
    "C55C-REQUIRED-FAILURE",
    "C55C-OPTIONAL-SUCCESS",
    "C55C-OPTIONAL-DEGRADED",
    "C55C-POLICY-CLOSURE-FRESHNESS",
    "C55C-PROVISIONING-FRESHNESS",
    "C55C-HANDSHAKE-HEALTH-PUBLICATION",
    "C55C-WINDOWS-AMD64-ACCEPT",
    "C55C-UNSUPPORTED-WINDOWS-NON-AMD64",
    "C55C-UNSUPPORTED-WSL",
    "C55C-UNSUPPORTED-MACOS",
    "C55C-ORDERED-ROLLBACK",
    "C55C-RECOVERY-MATRIX",
    "C55C-NATIVE-CONTAINMENT-SETTLEMENT",
    "C55C-SHARED-ENTRYPOINT-RECEIPT",
    "C55C-NO-FALLBACK",
    "C55C-SENTINEL-REDACTION",
)


class _WindowsProductNativeProfile:
    """Pathless Product-report double for the already-required C5.5b oracle."""

    def __init__(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        events: list[str],
    ) -> None:
        self.receipt_fingerprint = receipt.fingerprint
        self.worker_request_fingerprint = request.fingerprint
        self.native_profile_id = CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID
        self.native_profile_catalog_revision = (
            receipt.policy.native_profile_catalog_revision
        )
        self.realized_native_policy_closure_fingerprint = (
            receipt.policy.expected_native_policy_closure_fingerprint
        )
        self.execution_closure_fingerprint = linux_product._DIGEST_A
        self.cleanup_contract_version = 2
        self.settlement_witness = object()
        self._events = events

    async def capture_native(self, request, *, capture):
        return await capture(request)

    async def verify_current(self) -> None:
        return None

    def native_containment_settlement_witness(self) -> object:
        self._events.append("native-containment-witness")
        return self.settlement_witness

    async def close(self) -> None:
        return None


class _CoordinatorCleanup(linux_product._Cleanup):
    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.coordinator: ProductWorkerActivationCoordinator | None = None

    async def settle(self, **facts: object) -> None:
        await super().settle(**facts)
        assert self.coordinator is not None
        receipt = facts["receipt"]
        request = facts["request"]
        assert isinstance(receipt, ProductWorkerActivationReceiptV1)
        assert isinstance(request, ManagedWorkerLaunchRequestV1)
        self.coordinator.record_cleanup_settlement(
            WorkerCleanupSettlementV2(
                receipt_fingerprint=receipt.fingerprint,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
                host_identity="host-one",
                boot_identity="boot-one",
                protocol_terminal=True,
                domain_retired=True,
                tree_settled=True,
                native_containment_settled=True,
            ),
            witness=object(),
            native_containment_witness=facts["native_containment_witness"],
        )


class _WindowsProductContext:
    def __init__(self, tmp_path: Path, *, required: bool = True) -> None:
        self.base = linux_product._Context(tmp_path, required=required)
        self.policy = linux_product._policy(
            self.base.discovery,
            required=required,
            profile_id=CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
        )
        self.receipt = ProductWorkerActivationReceiptV1(
            policy=self.policy,
            issue_sequence=1,
            issue_nonce="windows-product-receipt",
        )
        self.base.policy = self.policy
        self.base.receipt = self.receipt
        self.plan = _WindowsLpacProductWorkerProfilePlan(
            worker_request_fingerprint=self.base.request.fingerprint,
            native_profile_catalog_revision=(
                self.policy.native_profile_catalog_revision
            ),
            containment_launcher_sha256=linux_product._LAUNCHER_DIGEST,
            containment_profile_sha256=(linux_product._CONTAINMENT_PROFILE_DIGEST),
            expected_native_policy_closure_fingerprint=(
                self.policy.expected_native_policy_closure_fingerprint
            ),
            operation_nonce=linux_product._DIGEST_A,
            lifecycle_fingerprint=linux_product._DIGEST_B,
        )
        self.activation_store = linux_product._ActivationStateStore()
        self.native_store = linux_product._ActivationStateStore()
        self.platform_imports = ("KERNEL32.DLL",)
        self.bound_facts: list[dict[str, object]] = []
        self.last_profile: _WindowsProductNativeProfile | None = None

    def bind(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        native_rejection: str | None = None,
        use_real_bridge: bool = False,
        **overrides: object,
    ):
        def bind_windows(**facts: object) -> _WindowsProductNativeProfile:
            self.bound_facts.append(facts)
            if native_rejection is not None:
                raise WorkerBindingError(
                    "Windows Product report native rejection",
                    code=native_rejection,
                )
            receipt = facts["receipt"]
            request = facts["worker_request"]
            plan = facts["plan"]
            assert isinstance(receipt, ProductWorkerActivationReceiptV1)
            assert isinstance(request, ManagedWorkerLaunchRequestV1)
            assert type(plan) is _WindowsLpacProductWorkerProfilePlan
            if plan.worker_request_fingerprint != request.fingerprint:
                raise WorkerBindingError(
                    "Windows Product provisioning request changed",
                    code="worker_native_provisioning_fingerprint_mismatch",
                )
            if (
                plan.expected_native_policy_closure_fingerprint
                != receipt.policy.expected_native_policy_closure_fingerprint
            ):
                raise WorkerBindingError(
                    "Windows Product policy closure changed",
                    code="worker_native_policy_closure_mismatch",
                )
            profile = _WindowsProductNativeProfile(
                receipt=receipt,
                request=request,
                events=self.base.events,
            )
            self.last_profile = profile
            return profile

        if not use_real_bridge:
            monkeypatch.setattr(
                canary_module,
                "_bind_windows_lpac_contained_product_worker_profile",
                bind_windows,
            )
        values: dict[str, object] = {
            "activation_state_store": self.activation_store,
            "containment_launcher_path": None,
            "containment_launcher_sha256": self.plan.containment_launcher_sha256,
            "containment_profile_sha256": self.plan.containment_profile_sha256,
            "windows_lpac_plan": self.plan,
            "windows_platform_imports": self.platform_imports,
            "native_provisioning_state_store": self.native_store,
        }
        values.update(overrides)
        return self.base.bind(**values)

    def configure_real_bridge(self, tmp_path: Path) -> None:
        build_root = tmp_path / "build"
        runtime_root = tmp_path / "runtime"
        build_root.mkdir()
        runtime_root.mkdir()
        executable = runtime_root / "worker.exe"
        _compile_fixture(build_root, executable)
        configuration = PluginLocalWorkerConfiguration(
            entrypoint="worker.exe",
            protocol="capability.query",
            protocol_version=1,
        )
        runtime = WorkerRuntimeBindingV1.capture(
            package_root=runtime_root,
            configuration=configuration,
        )
        identity = replace(
            self.base.request.identity,
            worker_configuration_fingerprint=configuration.fingerprint,
        )
        request = ManagedWorkerLaunchRequestV1(
            identity=identity,
            runtime=runtime,
            validate_current=lambda: None,
        )
        plan = _plan_windows_lpac_product_worker_profile(
            worker_request=request,
            native_profile_catalog_revision=(
                self.policy.native_profile_catalog_revision
            ),
            containment_launcher_sha256=linux_product._LAUNCHER_DIGEST,
            platform_imports=_NATIVE_PLATFORM_IMPORTS,
        )
        policy = replace(
            self.policy,
            worker_configuration_fingerprint=configuration.fingerprint,
            expected_native_policy_closure_fingerprint=(
                plan.expected_native_policy_closure_fingerprint
            ),
        )
        receipt = _receipt(policy, "windows-real-bridge-receipt")
        self.policy = policy
        self.receipt = receipt
        self.plan = plan
        self.platform_imports = _NATIVE_PLATFORM_IMPORTS
        self.base.policy = policy
        self.base.receipt = receipt
        self.base.request = request
        self.base.supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "windows-worker-journal.jsonl"),
            protocol="capability.query",
            protocol_version=1,
        )
        self.base.hosting = linux_product._Hosting(identity, self.base.events)


def _receipt(policy: ProductWorkerActivationPolicyV1, nonce: str):
    return ProductWorkerActivationReceiptV1(
        policy=policy,
        issue_sequence=1,
        issue_nonce=nonce,
    )


def _assert_native_rejection(
    context: _WindowsProductContext,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    with pytest.raises(CodingProductWorkerCanaryError) as caught:
        context.bind(monkeypatch, native_rejection=code)
    assert caught.value.code == code
    assert context.base.events == []


@pytest.mark.parametrize("case_id", PLC9C5_C55C_CASES, ids=PLC9C5_C55C_CASES)
def test_plc9c5_c55c_windows_product_case(
    case_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _WindowsProductContext(
        tmp_path,
        required="OPTIONAL" not in case_id,
    )

    if case_id == "C55C-PRODUCT-SELECTED":
        canary = context.bind(monkeypatch)
        assert canary.status.code == "coding_worker_selected"
        assert context.bound_facts[0]["plan"] is context.plan

    elif case_id == "C55C-PRODUCT-MISSING":
        canary = bind_coding_product_worker_canary()
        assert canary.status.effective_owner == "current"
        assert context.bound_facts == []

    elif case_id == "C55C-PRODUCT-WRONG":
        wrong = replace(
            context.policy,
            product_id="work",
            allowed_product_ids=("work",),
        )
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(monkeypatch, policy=wrong, receipt=None)
        assert caught.value.code == "coding_worker_product_mismatch"

    elif case_id == "C55C-PRODUCT-DISABLED":
        disabled = linux_product._policy(
            context.base.discovery,
            enabled=False,
            owner="current",
            profile_id=CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
        )
        canary = context.bind(monkeypatch, policy=disabled, receipt=None)
        assert canary.status.effective_owner == "current"
        assert context.bound_facts == []

    elif case_id in {
        "C55C-SESSION-CANONICAL",
        "C55C-SESSION-CWD",
        "C55C-SESSION-HOME",
    }:
        origin = {
            "C55C-SESSION-CANONICAL": "global",
            "C55C-SESSION-CWD": "cwd",
            "C55C-SESSION-HOME": "home",
        }[case_id]
        discovery = linux_product._discovery(
            tmp_path,
            mode="canonical" if origin == "global" else "compatibility",
            origin=origin,
        )
        policy = linux_product._policy(
            discovery,
            profile_id=CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
        )
        receipt = _receipt(policy, f"windows-session-{origin}")
        canary = context.bind(
            monkeypatch,
            policy=policy,
            receipt=receipt,
            session_discovery=discovery,
        )
        assert canary.status.receipt_fingerprint == receipt.fingerprint

    elif case_id == "C55C-SESSION-TAMPERED":

        def reject() -> None:
            raise ValueError(r"C:\secret\tampered-session")

        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(monkeypatch, validate_product_session=reject)
        assert caught.value.code == "coding_worker_session_product_mismatch"
        assert "secret" not in str(caught.value)

    elif case_id == "C55C-SESSION-ALIAS":
        alias = SessionLocator(
            source_id="sessions.cwd",
            conversation_id="session-one",
            session_file=tmp_path / "alias.jsonl",
            revision="alias-1",
        )
        discovery = linux_product._discovery(tmp_path, aliases=(alias,))
        policy = linux_product._policy(
            discovery,
            profile_id=CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
        )
        receipt = _receipt(policy, "windows-session-alias")
        assert (
            context.bind(
                monkeypatch,
                policy=policy,
                receipt=receipt,
                session_discovery=discovery,
            ).status.code
            == "coding_worker_selected"
        )

    elif case_id == "C55C-SESSION-CONFLICT":
        conflict = SessionLocator(
            source_id="sessions.cwd",
            conversation_id="session-one",
            session_file=tmp_path / "conflict.jsonl",
            revision="conflict-1",
        )
        discovery = linux_product._discovery(
            tmp_path,
            health="conflict",
            conflicts=(conflict,),
        )
        policy = linux_product._policy(
            discovery,
            profile_id=CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
        )
        receipt = _receipt(policy, "windows-session-conflict")
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(
                monkeypatch,
                policy=policy,
                receipt=receipt,
                session_discovery=discovery,
            )
        assert caught.value.code == "coding_worker_session_locator_conflict"

    elif case_id == "C55C-SESSION-CHANGED":
        changed = replace(
            context.base.discovery,
            locator=replace(context.base.discovery.locator, revision="locator-2"),
        )
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(monkeypatch, session_discovery=changed)
        assert caught.value.code == "coding_worker_session_locator_changed"

    elif case_id in {"C55C-REQUIRED-SUCCESS", "C55C-OPTIONAL-SUCCESS"}:
        canary = context.bind(monkeypatch)
        assert asyncio.run(canary.start(correlation_id="windows-start")).readiness == (
            "ready"
        )
        assert context.base.events.index("hosting-start") < context.base.events.index(
            "domain-publish"
        )
        asyncio.run(context.base.supervisor.fence(code="windows-test-complete"))

    elif case_id in {"C55C-REQUIRED-FAILURE", "C55C-OPTIONAL-DEGRADED"}:
        context.base.hosting.fail = True
        canary = context.bind(monkeypatch)
        if context.policy.effective_required:
            with pytest.raises(CodingProductWorkerCanaryError) as caught:
                asyncio.run(canary.start(correlation_id="windows-failure"))
            assert caught.value.code == "coding_worker_required_unavailable"
        else:
            assert (
                asyncio.run(canary.start(correlation_id="windows-failure")).readiness
                == "degraded"
            )
        assert context.base.current.calls == 0

    elif case_id == "C55C-POLICY-CLOSURE-FRESHNESS":
        stale_policy = replace(
            context.policy,
            expected_native_policy_closure_fingerprint=linux_product._DIGEST_C,
        )
        stale_receipt = _receipt(stale_policy, "windows-stale-policy")
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(monkeypatch, policy=stale_policy, receipt=stale_receipt)
        assert caught.value.code == "worker_native_policy_closure_mismatch"

    elif case_id == "C55C-PROVISIONING-FRESHNESS":
        stale_plan = replace(
            context.plan,
            containment_profile_sha256=linux_product._DIGEST_C,
        )
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(monkeypatch, windows_lpac_plan=stale_plan)
        assert caught.value.code == (
            "coding_worker_native_provisioning_fingerprint_mismatch"
        )
        assert context.bound_facts == []

    elif case_id == "C55C-HANDSHAKE-HEALTH-PUBLICATION":
        canary = context.bind(monkeypatch)
        asyncio.run(canary.start(correlation_id="windows-handshake"))
        assert context.base.events[:2] == ["hosting-start", "domain-publish"]
        asyncio.run(context.base.supervisor.fence(code="windows-test-complete"))

    elif case_id == "C55C-WINDOWS-AMD64-ACCEPT":
        assert os.name == "nt"
        assert platform.machine().lower() in {"amd64", "x86_64"}
        context.configure_real_bridge(tmp_path)
        canary = context.bind(monkeypatch, use_real_bridge=True)
        assert canary.status.readiness == "selected"
        asyncio.run(canary._native_profile.close())
        assert context.native_store.load()["phase"] == "settled"  # type: ignore[index]

    elif case_id == "C55C-UNSUPPORTED-WINDOWS-NON-AMD64":
        _assert_native_rejection(
            context,
            monkeypatch,
            "worker_native_architecture_unsupported",
        )

    elif case_id == "C55C-UNSUPPORTED-WSL":
        _assert_native_rejection(
            context,
            monkeypatch,
            "worker_native_platform_wsl_unsupported",
        )

    elif case_id == "C55C-UNSUPPORTED-MACOS":
        _assert_native_rejection(
            context,
            monkeypatch,
            "worker_native_platform_unsupported",
        )

    elif case_id == "C55C-ORDERED-ROLLBACK":
        canary = context.bind(monkeypatch)
        asyncio.run(canary.start(correlation_id="windows-rollback"))
        context.base.events.clear()
        status = asyncio.run(canary.rollback())
        observed = tuple(
            event for event in context.base.events if event.startswith("R")
        )
        assert observed == canary.rollback_steps
        assert status.effective_owner == "current"
        assert context.base.current.calls == 0

    elif case_id == "C55C-RECOVERY-MATRIX":
        canary = context.bind(monkeypatch)
        assert asyncio.run(canary.recover()) == canary.recovery_steps
        context.base.recovery.steps = context.base.recovery.steps[:-1]
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            asyncio.run(canary.recover())
        assert caught.value.code == "coding_worker_recovery_incomplete"

    elif case_id == "C55C-NATIVE-CONTAINMENT-SETTLEMENT":
        cleanup = _CoordinatorCleanup(context.base.events)
        context.base.cleanup = cleanup
        canary = context.bind(monkeypatch, cleanup=cleanup)
        cleanup.coordinator = canary._coordinator
        asyncio.run(canary.start(correlation_id="windows-settlement"))
        asyncio.run(canary.rollback())
        attempts = canary._coordinator.snapshot()["attempts"]
        assert next(iter(attempts.values()))["phase"] == "settled"  # type: ignore[union-attr]
        assert cleanup.settlements[-1]["native_containment_witness"] is (
            context.last_profile.settlement_witness
        )

    elif case_id == "C55C-SHARED-ENTRYPOINT-RECEIPT":
        canary = context.bind(monkeypatch)
        receipts = tuple(
            canary.receipt_for_entrypoint(entrypoint)
            for entrypoint in ("cli", "tui", "product")
        )
        assert all(receipt is context.receipt for receipt in receipts)

    elif case_id == "C55C-NO-FALLBACK":
        context.base.hosting.fail = True
        canary = context.bind(monkeypatch)
        with pytest.raises(CodingProductWorkerCanaryError):
            asyncio.run(canary.start(correlation_id="windows-no-fallback"))
        assert context.base.current.calls == 0

    elif case_id == "C55C-SENTINEL-REDACTION":
        context.base.hosting.fail = True
        canary = context.bind(monkeypatch)
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            asyncio.run(canary.start(correlation_id="windows-sentinel"))
        serialized = json.dumps(canary.status.to_dict(), sort_keys=True)
        assert caught.value.code == "coding_worker_required_unavailable"
        assert "secret" not in serialized.casefold()
        assert "sentinel" not in serialized.casefold()

    else:  # pragma: no cover - exact manifest tuple is exhaustive
        raise AssertionError(f"Unhandled PLC9C5 C5.5c case {case_id}")
