from __future__ import annotations

import asyncio
import json
import threading
from contextlib import AbstractContextManager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

import loushang.coding._product_worker_canary as canary_module
from loushang.coding._product_worker_canary import (
    CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
    CodingProductWorkerCanaryError,
    bind_coding_product_worker_canary,
    coding_product_worker_session_fingerprint,
)
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.transcript.discovery import (
    SessionDiscoveryMetadata,
    SessionLocator,
)
from loushang.harness.worker import (
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    ManagedWorkerLaunchRequestV1,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
    WorkerFrameCodec,
    WorkerLaunchIdentityV1,
    WorkerProtocolMessage,
    WorkerRuntimeBindingV1,
    WorkerSupervisor,
)
from loushang.harness.worker._native_profile_bridge import (
    _WindowsLpacProductWorkerProfilePlan,
)
from loushang.harness.worker.journal import WorkerSupervisorJournal
from loushang.harness.workspace.process import ProcessStderrTail
from loushang.hosting import ProcessExit

PLC9C5_C54_CASES = (
    "C54-PRODUCT-SELECTED",
    "C54-PRODUCT-MISSING",
    "C54-PRODUCT-WRONG",
    "C54-PRODUCT-DISABLED",
    "C54-SESSION-CANONICAL",
    "C54-SESSION-CWD",
    "C54-SESSION-HOME",
    "C54-SESSION-TAMPERED",
    "C54-SESSION-ALIAS",
    "C54-SESSION-CONFLICT",
    "C54-SESSION-CHANGED",
    "C54-REQUIRED-SUCCESS",
    "C54-REQUIRED-FAILURE",
    "C54-OPTIONAL-SUCCESS",
    "C54-OPTIONAL-DEGRADED",
    "C54-CLOSURE-FRESHNESS",
    "C54-HANDSHAKE-HEALTH-PUBLICATION",
    "C54-UNSUPPORTED-WINDOWS",
    "C54-UNSUPPORTED-WSL",
    "C54-UNSUPPORTED-NON-X86",
    "C54-UNSUPPORTED-MACOS",
    "C54-ORDERED-ROLLBACK",
    "C54-RECOVERY-MATRIX",
    "C54-SHARED-ENTRYPOINT-RECEIPT",
    "C54-SENTINEL-REDACTION",
)

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_ATTEMPT = "d" * 32
_SESSION_NONCE = "e" * 64
_WORKER_BYTES = b"#!/bin/sh\nexit 0\n"
_LAUNCHER_BYTES = b'#!/bin/sh\nexec "$@"\n'
_WORKER_DIGEST = sha256(_WORKER_BYTES).hexdigest()
_LAUNCHER_DIGEST = sha256(_LAUNCHER_BYTES).hexdigest()
_CONTAINMENT_PROFILE_DIGEST = sha256(b"coding-worker-containment-v1").hexdigest()
_EVIDENCE_AUTHORITY_ID = "coding-cleanup-evidence-v1"
_EVIDENCE_AUTHORITY_FINGERPRINT = "f" * 64


class _Authority:
    def __init__(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        events: list[str],
    ) -> None:
        self._lock = threading.RLock()
        self._witness = receipt.authority_witness
        self._events = events
        self._in_gate = False

    def serialized_admission(self) -> AbstractContextManager[None]:
        authority = self

        class _Gate(AbstractContextManager[None]):
            def __enter__(self) -> None:
                authority._lock.acquire()
                assert not authority._in_gate
                authority._in_gate = True

            def __exit__(self, *error: object) -> None:
                authority._in_gate = False
                authority._lock.release()

        return _Gate()

    def current_witness(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> tuple[str, str, str, int, int]:
        del receipt
        assert self._in_gate
        return self._witness

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        assert self._in_gate
        current_generation = self._witness[-1]
        if current_generation == expected_generation:
            self._witness = (*self._witness[:-1], expected_generation + 1)
        elif current_generation != expected_generation + 1:
            raise AssertionError("unexpected kill-switch generation")
        self._events.append("R1-LATCH-FUTURE")
        return expected_generation + 1


class _EvidenceAuthority:
    authority_id = _EVIDENCE_AUTHORITY_ID
    authority_fingerprint = _EVIDENCE_AUTHORITY_FINGERPRINT

    def verify_tree_settlement(self, **facts: object) -> bool:
        del facts
        return True

    def verify_native_containment_settlement(self, **facts: object) -> bool:
        del facts
        return True

    def verify_changed_boot_absence(self, **facts: object) -> bool:
        del facts
        return True

    def verify_registered_lease_expired(self, **facts: object) -> bool:
        del facts
        return True


class _ActivationStateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._document: dict[str, object] | None = None

    def load(self) -> object:
        with self._lock:
            return _json_clone(self._document)

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: object,
    ) -> bool:
        assert isinstance(document, dict)
        with self._lock:
            current_revision = (
                0 if self._document is None else self._document["stateRevision"]
            )
            if current_revision != expected_revision:
                return False
            self._document = _json_clone(document)
            return True


def _json_clone(value: object):
    if value is None:
        return None
    return json.loads(json.dumps(value, sort_keys=True))


class _Endpoint:
    def __init__(self, ready: WorkerProtocolMessage) -> None:
        self.incoming = bytearray(WorkerFrameCodec.encode(ready))
        self.changed = asyncio.Event()
        self.writes: list[bytes] = []
        self.closed = False

    async def read(self, max_bytes: int) -> bytes:
        while not self.incoming:
            if self.closed:
                return b""
            self.changed.clear()
            await self.changed.wait()
        chunk = bytes(self.incoming[:max_bytes])
        del self.incoming[:max_bytes]
        return chunk

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def close(self) -> None:
        self.closed = True
        self.changed.set()


class _Process:
    lease_id = "worker-process-one"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.exit: asyncio.Future[ProcessExit] | None = None

    def _exit(self) -> asyncio.Future[ProcessExit]:
        if self.exit is None:
            self.exit = asyncio.get_running_loop().create_future()
        return self.exit

    async def read_stdout(self, max_bytes: int) -> bytes:
        del max_bytes
        return b""

    async def read_stderr(self, max_bytes: int) -> bytes:
        del max_bytes
        return b""

    async def write_stdin(self, data: bytes) -> None:
        del data

    async def close_stdin(self) -> None:
        return None

    async def wait(self) -> ProcessExit:
        return await asyncio.shield(self._exit())

    async def terminate(self) -> ProcessExit:
        self.events.append("R4-TERMINATE-TREE")
        future = self._exit()
        if not future.done():
            future.set_result(ProcessExit(-15))
        return await future

    async def close(self) -> None:
        await self.terminate()

    def stderr_tail(self) -> ProcessStderrTail:
        return ProcessStderrTail()


class _Lease:
    session_id = "hosting-session-one"

    def __init__(self, endpoint: _Endpoint, process: _Process) -> None:
        self.endpoint = endpoint
        self.process = process

    async def close(self) -> None:
        await self.endpoint.close()
        await self.process.terminate()


class _Hosting:
    def __init__(self, identity: WorkerLaunchIdentityV1, events: list[str]) -> None:
        self.events = events
        self.fail = False
        self.endpoint = _Endpoint(
            WorkerProtocolMessage.create(
                "ready",
                attemptId=identity.attempt_id,
                identityFingerprint=identity.fingerprint,
                protocol="capability.query",
                protocolVersion=1,
                sessionNonce=identity.session_nonce,
                supervisorEpoch=identity.supervisor_epoch,
            )
        )
        self.process = _Process(events)

    async def start(self, request, preparation):
        del request, preparation
        self.events.append("hosting-start")
        if self.fail:
            raise RuntimeError("/secret/hosting-sentinel")
        return _Lease(self.endpoint, self.process)

    async def close(self) -> None:
        return None


class _CurrentOwner:
    def __init__(self) -> None:
        self.calls = 0

    async def start(self, request, *, correlation_id, signal=None):
        del request, correlation_id, signal
        self.calls += 1
        raise AssertionError("same-attempt fallback is forbidden")


class _Domain:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.fail_publish = False
        self.ready_states: list[tuple[bool, bool, str]] = []

    async def publish(self, *, adapter, admission, **identity) -> None:
        del admission, identity
        assert adapter._supervisor.status.state == "healthy"
        self.events.append("domain-publish")
        if self.fail_publish:
            raise RuntimeError("/secret/domain-sentinel")

    async def fence_attempt(self, **identity) -> None:
        del identity
        self.events.append("R2-FENCE-ATTEMPTS")

    async def revoke_and_drain(self, **identity) -> None:
        del identity
        self.events.append("R3-REVOKE-DRAIN")

    async def settle_readiness(self, *, required, ready, code) -> None:
        self.ready_states.append((required, ready, code))
        if code == "coding_worker_rollback_latched":
            self.events.append("R6-SETTLE-READINESS")

    async def issue_current(self, *, prior_receipt_fingerprint) -> object:
        assert len(prior_receipt_fingerprint) == 64
        self.events.append("R7-ISSUE-CURRENT")
        return object()


class _Cleanup:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.settlements: list[dict[str, object]] = []

    async def settle(self, **facts) -> None:
        assert facts["protocol_terminal"] is True
        assert facts["domain_retired"] is True
        self.settlements.append(dict(facts))
        self.events.append("R5-SETTLE-OR-DEBT")


class _Recovery:
    def __init__(self) -> None:
        self.steps = (
            "V1-PRIOR-ABSENT",
            "V2-EXACT-REAPED",
            "V3-SAMEBOOT-UNKNOWN",
            "V4-CHANGEDBOOT-ABSENT",
            "V5-BUDGET-EXHAUSTED",
            "V6-HOST-RESTART",
        )

    async def recover(self, **identity) -> tuple[str, ...]:
        del identity
        return self.steps


class _Context:
    def __init__(self, tmp_path: Path, *, required: bool = True) -> None:
        self.events: list[str] = []
        self.discovery = _discovery(tmp_path)
        self.policy = _policy(self.discovery, required=required)
        self.receipt = ProductWorkerActivationReceiptV1(
            policy=self.policy,
            issue_sequence=1,
            issue_nonce="coding-worker-receipt-one",
        )
        configuration = PluginLocalWorkerConfiguration(
            entrypoint="worker",
            protocol="capability.query",
            protocol_version=1,
        )
        executable = tmp_path / "worker"
        executable.write_bytes(_WORKER_BYTES)
        executable.chmod(0o500)
        self.launcher = tmp_path / "containment-launcher"
        self.launcher.write_bytes(_LAUNCHER_BYTES)
        self.launcher.chmod(0o500)
        runtime = WorkerRuntimeBindingV1.capture(
            package_root=tmp_path,
            configuration=configuration,
        )
        assert runtime.executable_digest == _WORKER_DIGEST
        assert runtime.worker_configuration_fingerprint == (
            self.policy.worker_configuration_fingerprint
        )
        identity = WorkerLaunchIdentityV1(
            plugin_id=self.policy.plugin_id,
            plugin_revision_digest=self.policy.plugin_revision_digest,
            contribution_id=self.policy.contribution_id,
            owner_id="coding.capability",
            product_id="coding",
            scope_id=self.policy.product_scope_id,
            owner_generation=self.policy.owner_selection_generation,
            declaration_fingerprint=self.policy.declaration_fingerprint,
            worker_configuration_fingerprint=(
                self.policy.worker_configuration_fingerprint
            ),
            attempt_id=_ATTEMPT,
            supervisor_epoch=1,
            session_nonce=_SESSION_NONCE,
        )
        self.request = ManagedWorkerLaunchRequestV1(
            identity=identity,
            runtime=runtime,
            validate_current=lambda: None,
        )
        self.supervisor = WorkerSupervisor(
            identity=identity,
            journal=WorkerSupervisorJournal(tmp_path / "worker-journal.jsonl"),
            protocol="capability.query",
            protocol_version=1,
        )
        self.current = _CurrentOwner()
        self.hosting = _Hosting(identity, self.events)
        self.authority = CapabilityWorkerAuthorityV1(
            plugin_revision_digest=self.policy.plugin_revision_digest,
            declaration_fingerprint=self.policy.declaration_fingerprint,
            owner_generation=self.policy.owner_selection_generation,
            product_policy_revision=self.policy.product_policy_revision,
            owner_policy_revision="owner-policy-1",
            revocation_epoch=0,
        )
        self.binding = CapabilityWorkerBindingV1(
            plugin_id=self.policy.plugin_id,
            contribution_id=self.policy.contribution_id,
            product_id="coding",
            scope_id=self.policy.product_scope_id,
            owner_id=identity.owner_id,
            allowed_capability_ids=("coding.hover",),
            authority=self.authority,
        )
        self.domain = _Domain(self.events)
        self.cleanup = _Cleanup(self.events)
        self.recovery = _Recovery()
        self.evidence = _EvidenceAuthority()

    def bind(self, **overrides):
        selected_receipt = overrides.get("receipt", self.receipt)
        selected_authority = (
            _Authority(selected_receipt, self.events)
            if isinstance(selected_receipt, ProductWorkerActivationReceiptV1)
            else _Authority(self.receipt, self.events)
        )
        values = {
            "policy": self.policy,
            "receipt": self.receipt,
            "session_discovery": self.discovery,
            "validate_product_session": lambda: None,
            "authority": selected_authority,
            "evidence_authority": self.evidence,
            "trusted_evidence_authority_id": self.evidence.authority_id,
            "trusted_evidence_authority_fingerprint": (
                self.evidence.authority_fingerprint
            ),
            "activation_state_store": _ActivationStateStore(),
            "restart_budget": 3,
            "supervisor": self.supervisor,
            "worker_request": self.request,
            "current_owner": self.current,
            "hosting": self.hosting,
            "containment_launcher_path": str(self.launcher),
            "containment_launcher_sha256": _LAUNCHER_DIGEST,
            "containment_profile_sha256": _CONTAINMENT_PROFILE_DIGEST,
            "capability_binding": self.binding,
            "capability_authority_reader": lambda: self.authority,
            "domain": self.domain,
            "cleanup": self.cleanup,
            "recovery": self.recovery,
            "host_identity": "host-one",
            "boot_identity": "boot-one",
        }
        values.update(overrides)
        return bind_coding_product_worker_canary(**values)


def _discovery(
    root: Path,
    *,
    mode: str = "canonical",
    origin: str = "global",
    health: str = "available",
    aliases: tuple[SessionLocator, ...] = (),
    conflicts: tuple[SessionLocator, ...] = (),
) -> SessionDiscoveryMetadata:
    return SessionDiscoveryMetadata(
        locator=SessionLocator(
            source_id=f"sessions.{origin}",
            conversation_id="session-one",
            session_file=root / "session-one.jsonl",
            revision="locator-1",
        ),
        mode=mode,  # type: ignore[arg-type]
        origin=origin,  # type: ignore[arg-type]
        health=health,  # type: ignore[arg-type]
        aliases=aliases,
        conflicts=conflicts,
    )


def _policy(
    discovery: SessionDiscoveryMetadata,
    *,
    required: bool = True,
    product_id: str = "coding",
    enabled: bool = True,
    owner: str = "hosting",
    profile_id: str = "posix-static-contained-elf-v1",
) -> ProductWorkerActivationPolicyV1:
    configuration = PluginLocalWorkerConfiguration(
        entrypoint="worker",
        protocol="capability.query",
        protocol_version=1,
    )
    expected_native_policy_closure_fingerprint = (
        ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
            native_profile_catalog_revision="native-catalog-1",
            native_profile_id=profile_id,
            payload_sha256=_WORKER_DIGEST,
            containment_launcher_sha256=_LAUNCHER_DIGEST,
            containment_profile_sha256=_CONTAINMENT_PROFILE_DIGEST,
        )
    )
    return ProductWorkerActivationPolicyV1(
        product_id=product_id,
        product_runtime_id="coding-runtime-1",
        product_scope_id="session.session-one",
        session_id="session-one",
        session_route="selected",
        selected_locator_fingerprint=(
            coding_product_worker_session_fingerprint(discovery)
        ),
        selected_locator_revision="locator-1",
        plugin_id="review-pack",
        plugin_revision_digest=_DIGEST_A,
        contribution_id="review-provider",
        reservation_fingerprint=_DIGEST_B,
        declaration_fingerprint=_DIGEST_C,
        worker_configuration_fingerprint=configuration.fingerprint,
        declared_required=required,
        effective_required=required,
        enabled=enabled,
        allowed_product_ids=(product_id,),
        allowed_contribution_ids=("review-provider",),
        requested_owner=owner,  # type: ignore[arg-type]
        owner_selection_generation=3,
        no_fallback=True,
        native_profile_id=profile_id,
        native_profile_catalog_revision="native-catalog-1",
        allowed_native_profile_ids=(profile_id,),
        expected_native_policy_closure_fingerprint=(
            expected_native_policy_closure_fingerprint
        ),
        product_policy_revision="product-policy-1",
        kill_switch_generation=2,
    )


@pytest.mark.parametrize("case_id", PLC9C5_C54_CASES, ids=PLC9C5_C54_CASES)
def test_plc9c5_c54_linux_product_case(case_id: str, tmp_path: Path) -> None:
    context = _Context(tmp_path, required="OPTIONAL" not in case_id)

    if case_id == "C54-PRODUCT-SELECTED":
        canary = context.bind()
        assert canary.status.code == "coding_worker_selected"
        assert canary.status.effective_owner == "hosting"

    elif case_id == "C54-PRODUCT-MISSING":
        canary = bind_coding_product_worker_canary()
        assert canary.status.to_dict()["effectiveOwner"] == "current"
        assert context.events == []

    elif case_id == "C54-PRODUCT-WRONG":
        wrong = replace(
            context.policy,
            product_id="work",
            allowed_product_ids=("work",),
        )
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(policy=wrong, receipt=None)
        assert caught.value.code == "coding_worker_product_mismatch"

    elif case_id == "C54-PRODUCT-DISABLED":
        disabled = _policy(
            context.discovery,
            enabled=False,
            owner="current",
        )
        canary = context.bind(policy=disabled, receipt=None)
        assert canary.status.code == "coding_worker_disabled_by_policy"
        assert context.events == []

    elif case_id in {"C54-SESSION-CANONICAL", "C54-SESSION-CWD", "C54-SESSION-HOME"}:
        origin = {
            "C54-SESSION-CANONICAL": "global",
            "C54-SESSION-CWD": "cwd",
            "C54-SESSION-HOME": "home",
        }[case_id]
        mode = "canonical" if origin == "global" else "compatibility"
        discovery = _discovery(tmp_path, mode=mode, origin=origin)
        policy = _policy(discovery)
        receipt = ProductWorkerActivationReceiptV1(
            policy=policy,
            issue_sequence=1,
            issue_nonce="session-route-receipt",
        )
        canary = context.bind(
            policy=policy,
            receipt=receipt,
            session_discovery=discovery,
        )
        # The request is deliberately still bound to the same Product/Plugin;
        # only locator provenance varies here.
        assert canary.status.receipt_fingerprint == receipt.fingerprint

    elif case_id == "C54-SESSION-TAMPERED":

        def reject() -> None:
            raise ValueError("/secret/tampered-session")

        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(validate_product_session=reject)
        assert caught.value.code == "coding_worker_session_product_mismatch"
        assert "/secret" not in str(caught.value)

    elif case_id == "C54-SESSION-ALIAS":
        alias = SessionLocator(
            source_id="sessions.cwd",
            conversation_id="session-one",
            session_file=tmp_path / "alias.jsonl",
            revision="alias-1",
        )
        discovery = _discovery(tmp_path, aliases=(alias,))
        policy = _policy(discovery)
        receipt = ProductWorkerActivationReceiptV1(
            policy=policy,
            issue_sequence=1,
            issue_nonce="alias-receipt",
        )
        assert (
            context.bind(
                policy=policy,
                receipt=receipt,
                session_discovery=discovery,
            ).status.code
            == "coding_worker_selected"
        )

    elif case_id == "C54-SESSION-CONFLICT":
        conflict = SessionLocator(
            source_id="sessions.cwd",
            conversation_id="session-one",
            session_file=tmp_path / "conflict.jsonl",
            revision="conflict-1",
        )
        discovery = _discovery(
            tmp_path,
            health="conflict",
            conflicts=(conflict,),
        )
        policy = _policy(discovery)
        receipt = ProductWorkerActivationReceiptV1(
            policy=policy,
            issue_sequence=1,
            issue_nonce="conflict-receipt",
        )
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(
                policy=policy,
                receipt=receipt,
                session_discovery=discovery,
            )
        assert caught.value.code == "coding_worker_session_locator_conflict"

    elif case_id == "C54-SESSION-CHANGED":
        changed = replace(
            context.discovery,
            locator=replace(context.discovery.locator, revision="locator-2"),
        )
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(session_discovery=changed)
        assert caught.value.code == "coding_worker_session_locator_changed"

    elif case_id in {"C54-REQUIRED-SUCCESS", "C54-OPTIONAL-SUCCESS"}:
        canary = context.bind()
        status = asyncio.run(canary.start(correlation_id="launch-one"))
        assert status.readiness == "ready"
        assert context.events.index("hosting-start") < context.events.index(
            "domain-publish"
        )
        asyncio.run(context.supervisor.fence(code="test-complete"))

    elif case_id in {"C54-REQUIRED-FAILURE", "C54-OPTIONAL-DEGRADED"}:
        context.hosting.fail = True
        canary = context.bind()
        if context.policy.effective_required:
            with pytest.raises(CodingProductWorkerCanaryError) as caught:
                asyncio.run(canary.start(correlation_id="launch-one"))
            assert caught.value.code == "coding_worker_required_unavailable"
        else:
            status = asyncio.run(canary.start(correlation_id="launch-one"))
            assert status.readiness == "degraded"
        assert context.current.calls == 0

    elif case_id == "C54-CLOSURE-FRESHNESS":
        stale_policy = replace(
            context.policy,
            expected_native_policy_closure_fingerprint=_DIGEST_A,
        )
        stale_receipt = ProductWorkerActivationReceiptV1(
            policy=stale_policy,
            issue_sequence=1,
            issue_nonce="stale-closure-receipt",
        )
        state_store = _ActivationStateStore()
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(
                policy=stale_policy,
                receipt=stale_receipt,
                activation_state_store=state_store,
            )
        assert caught.value.code == "worker_native_policy_closure_mismatch"
        assert state_store.load() is None

    elif case_id == "C54-HANDSHAKE-HEALTH-PUBLICATION":
        canary = context.bind()
        asyncio.run(canary.start(correlation_id="launch-one"))
        assert context.events.index("hosting-start") < context.events.index(
            "domain-publish"
        )
        asyncio.run(context.supervisor.fence(code="test-complete"))

    elif case_id in {
        "C54-UNSUPPORTED-WINDOWS",
        "C54-UNSUPPORTED-WSL",
        "C54-UNSUPPORTED-NON-X86",
        "C54-UNSUPPORTED-MACOS",
    }:
        profile_id = {
            "C54-UNSUPPORTED-WINDOWS": "windows-restricted-direct-import-pe-v1",
            "C54-UNSUPPORTED-WSL": "wsl-static-contained-elf-v1",
            "C54-UNSUPPORTED-NON-X86": "posix-arm64-contained-elf-v1",
            "C54-UNSUPPORTED-MACOS": "macos-static-contained-mach-o-v1",
        }[case_id]
        policy = _policy(context.discovery, profile_id=profile_id)
        receipt = ProductWorkerActivationReceiptV1(
            policy=policy,
            issue_sequence=1,
            issue_nonce="unsupported-receipt",
        )
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            context.bind(policy=policy, receipt=receipt)
        assert caught.value.code == "coding_worker_native_profile_unsupported"
        assert context.events == []

    elif case_id == "C54-ORDERED-ROLLBACK":
        canary = context.bind()
        asyncio.run(canary.start(correlation_id="launch-one"))
        context.events.clear()
        status = asyncio.run(canary.rollback())
        observed = tuple(item for item in context.events if item.startswith("R"))
        assert observed == canary.rollback_steps
        assert status.effective_owner == "current"
        assert context.current.calls == 0

    elif case_id == "C54-RECOVERY-MATRIX":
        canary = context.bind()
        assert asyncio.run(canary.recover()) == canary.recovery_steps
        context.recovery.steps = context.recovery.steps[:-1]
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            asyncio.run(canary.recover())
        assert caught.value.code == "coding_worker_recovery_incomplete"

    elif case_id == "C54-SHARED-ENTRYPOINT-RECEIPT":
        canary = context.bind()
        receipts = tuple(
            canary.receipt_for_entrypoint(entrypoint)
            for entrypoint in ("cli", "tui", "product")
        )
        assert all(item is context.receipt for item in receipts)
        with pytest.raises(CodingProductWorkerCanaryError):
            canary.receipt_for_entrypoint("lsp")

    elif case_id == "C54-SENTINEL-REDACTION":
        context.hosting.fail = True
        canary = context.bind()
        with pytest.raises(CodingProductWorkerCanaryError) as caught:
            asyncio.run(canary.start(correlation_id="launch-one"))
        serialized = json.dumps(canary.status.to_dict(), sort_keys=True)
        assert caught.value.code == "coding_worker_required_unavailable"
        assert "/secret" not in serialized
        assert "sentinel" not in serialized

    else:
        raise AssertionError(f"Unhandled PLC9C5 C5.4 case {case_id}")


class _FakeWindowsNativeProfile:
    def __init__(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
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
        self.cleanup_contract_version = 2
        self.settlement_witness = object()
        self.closed = False
        self.captured = False

    @property
    def execution_closure_fingerprint(self) -> str:
        if not self.captured:
            raise AssertionError("execution closure was read before native capture")
        return _DIGEST_A

    async def capture_native(self, request, *, capture):
        result = await capture(request)
        self.captured = True
        return result

    async def verify_current(self) -> None:
        return None

    def native_containment_settlement_witness(self) -> object:
        return self.settlement_witness

    async def close(self) -> None:
        self.closed = True


def test_product_closes_bound_native_profile_when_start_decision_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context(tmp_path)
    profile = _FakeWindowsNativeProfile(
        receipt=context.receipt,
        request=context.request,
    )
    monkeypatch.setattr(
        canary_module,
        "_bind_posix_static_contained_product_worker_profile",
        lambda **facts: profile,
    )
    canary = context.bind()
    monkeypatch.setattr(
        canary._coordinator,
        "evaluate",
        lambda policy, receipt: {"reason": "stale-receipt"},
    )

    with pytest.raises(CodingProductWorkerCanaryError) as rejected:
        asyncio.run(canary.start(correlation_id="stale-decision"))

    assert rejected.value.code == "coding_worker_required_unavailable"
    assert profile.closed
    assert context.domain.ready_states == [
        (True, False, "coding_worker_stale-receipt"),
    ]


def test_windows_product_dispatch_admits_cleanup_v2_without_linux_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context(tmp_path)
    policy = _policy(
        context.discovery,
        profile_id=CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
    )
    receipt = ProductWorkerActivationReceiptV1(
        policy=policy,
        issue_sequence=1,
        issue_nonce="windows-product-receipt",
    )
    plan = _WindowsLpacProductWorkerProfilePlan(
        worker_request_fingerprint=context.request.fingerprint,
        native_profile_catalog_revision=policy.native_profile_catalog_revision,
        containment_launcher_sha256=_LAUNCHER_DIGEST,
        containment_profile_sha256=_CONTAINMENT_PROFILE_DIGEST,
        expected_native_policy_closure_fingerprint=(
            policy.expected_native_policy_closure_fingerprint
        ),
        operation_nonce=_DIGEST_A,
        lifecycle_fingerprint=_DIGEST_B,
    )
    profile = _FakeWindowsNativeProfile(receipt=receipt, request=context.request)
    observed: list[dict[str, object]] = []

    def bind_windows(**facts: object) -> _FakeWindowsNativeProfile:
        observed.append(facts)
        return profile

    monkeypatch.setattr(
        canary_module,
        "_bind_windows_lpac_contained_product_worker_profile",
        bind_windows,
    )
    activation_store = _ActivationStateStore()
    native_store = _ActivationStateStore()
    canary = context.bind(
        policy=policy,
        receipt=receipt,
        activation_state_store=activation_store,
        containment_launcher_path=None,
        windows_lpac_plan=plan,
        windows_platform_imports=("KERNEL32.DLL",),
        native_provisioning_state_store=native_store,
    )

    asyncio.run(canary.start(correlation_id="windows-product-start"))
    assert (
        activation_store.load()["attempts"][  # type: ignore[index]
            f"{receipt.fingerprint}:{_ATTEMPT}:3"
        ]["cleanupContractVersion"]
        == 2
    )
    asyncio.run(canary.rollback())

    assert len(observed) == 1
    assert observed[0]["plan"] is plan
    assert context.cleanup.settlements[-1]["native_containment_witness"] is (
        profile.settlement_witness
    )
    assert context.current.calls == 0
