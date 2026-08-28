"""Coding adapter tests for portable Continuity imports."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from loushang.coding import continuity as continuity_module
from loushang.coding.continuity import CodingContinuityActivationBridge
from loushang.harness.continuity import (
    CONTINUITY_BUNDLE_MEDIA_TYPE,
    CONTINUITY_JSONL_MEDIA_TYPE,
    ContinuityActivationPayload,
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
    PreparedActivationLease,
)

requires_secure_staging = pytest.mark.skipif(
    not continuity_module._supports_continuity_directory_handles(),
    reason="secure directory-relative staging is unavailable",
)


@dataclass
class _PreparedOperation:
    result: object = "canonical-session"
    consumed: bool = False
    abort_count: int = 0
    consume_error: BaseException | None = None

    async def consume(self) -> object:
        self.consumed = True
        if self.consume_error is not None:
            raise self.consume_error
        return self.result

    async def abort(self) -> None:
        self.abort_count += 1

    async def close(self) -> None:
        await self.abort()

    @property
    def aborted(self) -> bool:
        return self.abort_count > 0


@dataclass
class _Runtime:
    observed_path: Path | None = None
    observed_bytes: bytes | None = None
    observed_mode: int | None = None
    fallback_cwd: str | None = None
    missing_cwd: str | None = None
    prepared: _PreparedOperation = field(default_factory=_PreparedOperation)

    async def prepare_restore_session_operation(
        self,
        session_id: str | Path,
        *,
        fallback_cwd: str | Path | None = None,
        missing_cwd: str = "error",
    ) -> _PreparedOperation:
        path = Path(session_id)
        self.observed_path = path
        self.observed_bytes = path.read_bytes()
        self.observed_mode = stat.S_IMODE(path.stat().st_mode)
        self.fallback_cwd = None if fallback_cwd is None else str(fallback_cwd)
        self.missing_cwd = missing_cwd
        return self.prepared


def _source() -> ContinuityProviderSourceDescriptor:
    return ContinuityProviderSourceDescriptor(
        provider_id="cloud.sessions",
        source="oem",
        source_id="oem:cloud",
        implementation="cloud.continuity.sessions",
        implementation_version=1,
    )


@pytest.mark.parametrize(
    ("media_type", "suffix"),
    (
        (CONTINUITY_JSONL_MEDIA_TYPE, ".jsonl"),
        (CONTINUITY_BUNDLE_MEDIA_TYPE, ".loushang.zip"),
    ),
)
@requires_secure_staging
def test_coding_portable_activation_bridge_uses_private_bounded_temporary_copy(
    tmp_path: Path,
    media_type: str,
    suffix: str,
) -> None:
    runtime = _Runtime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
        fallback_cwd="/workspace",
    )
    payload_bytes = b'{"type":"conversation"}\n'
    payload = ContinuityActivationPayload(
        media_type=media_type,
        data=payload_bytes,
        digest=hashlib.sha256(payload_bytes).hexdigest(),
        cwd_override="/source-suggested-workspace",
    )
    target = ContinuityTarget(
        provider_id="cloud.sessions",
        opaque_id="remote-1",
    )

    prepared = asyncio.run(bridge.prepare(target, payload, _source()))

    assert runtime.observed_path is not None
    assert runtime.observed_path.name.endswith(suffix)
    assert runtime.observed_bytes == payload_bytes
    if os.name == "posix":
        assert runtime.observed_mode == 0o600
        assert stat.S_IMODE((tmp_path / "continuity").stat().st_mode) == 0o700
    assert runtime.fallback_cwd == "/workspace"
    assert runtime.missing_cwd == "fallback"
    assert not runtime.observed_path.exists()
    assert isinstance(prepared, PreparedActivationLease)
    assert prepared.target == target
    assert prepared.disposition == "in_place"
    assert not prepared.consumed
    assert asyncio.run(prepared.consume()) == "canonical-session"
    assert prepared.consumed


@requires_secure_staging
def test_coding_portable_activation_bridge_aborts_failed_consume_exactly_once(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(
        prepared=_PreparedOperation(consume_error=RuntimeError("consume failed"))
    )
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )
    prepared = asyncio.run(
        bridge.prepare(
            ContinuityTarget(
                provider_id="cloud.sessions",
                opaque_id="remote-1",
            ),
            payload,
            _source(),
        )
    )

    with pytest.raises(RuntimeError, match="consume failed"):
        asyncio.run(prepared.consume())
    asyncio.run(prepared.abort())

    assert runtime.prepared.abort_count == 1


@requires_secure_staging
def test_coding_portable_activation_bridge_aborts_cancelled_consume_exactly_once(
    tmp_path: Path,
) -> None:
    class _BlockingPreparedOperation(_PreparedOperation):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def consume(self) -> object:
            self.consumed = True
            self.started.set()
            await self.release.wait()
            return self.result

    candidate = _BlockingPreparedOperation()
    runtime = _Runtime(prepared=candidate)
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )

    async def scenario() -> None:
        prepared = await bridge.prepare(
            ContinuityTarget(
                provider_id="cloud.sessions",
                opaque_id="remote-1",
            ),
            payload,
            _source(),
        )
        task = asyncio.create_task(prepared.consume())
        await asyncio.wait_for(candidate.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await prepared.abort()

    asyncio.run(scenario())

    assert candidate.abort_count == 1


def test_coding_portable_activation_bridge_rejects_product_budget_before_write(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
        max_bytes=4,
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"12345",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )
    target = ContinuityTarget(
        provider_id="cloud.sessions",
        opaque_id="remote-1",
    )

    with pytest.raises(ValueError, match="Product limit"):
        asyncio.run(bridge.prepare(target, payload, _source()))

    assert runtime.observed_path is None
    assert not (tmp_path / "continuity").exists()


@pytest.mark.skipif(
    continuity_module._supports_continuity_directory_handles(),
    reason="secure directory-relative staging is available",
)
def test_coding_portable_activation_bridge_fails_closed_without_secure_staging(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )

    with pytest.raises(OSError, match="unavailable"):
        asyncio.run(
            bridge.prepare(
                ContinuityTarget(
                    provider_id="cloud.sessions",
                    opaque_id="remote-1",
                ),
                payload,
                _source(),
            )
        )

    assert runtime.observed_path is None


@requires_secure_staging
def test_coding_portable_activation_bridge_does_not_trust_source_cwd(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
        cwd_override="/source-controlled",
    )

    prepared = asyncio.run(
        bridge.prepare(
            ContinuityTarget(
                provider_id="cloud.sessions",
                opaque_id="remote-1",
            ),
            payload,
            _source(),
        )
    )

    assert runtime.fallback_cwd is None
    assert runtime.missing_cwd == "error"
    asyncio.run(prepared.abort())
    assert runtime.prepared.aborted


def test_coding_portable_activation_bridge_rejects_linked_temporary_root(
    tmp_path: Path,
) -> None:
    target_root = tmp_path / "target"
    target_root.mkdir()
    linked_root = tmp_path / "linked"
    try:
        linked_root.symlink_to(target_root, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    runtime = _Runtime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=linked_root,
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )
    target = ContinuityTarget(
        provider_id="cloud.sessions",
        opaque_id="remote-1",
    )

    with pytest.raises(OSError, match="unsafe"):
        asyncio.run(bridge.prepare(target, payload, _source()))

    assert os.listdir(target_root) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_coding_portable_activation_bridge_rejects_writable_path_ancestor(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    runtime = _Runtime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=shared / "continuity",
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )

    with pytest.raises(PermissionError, match="writable ancestor"):
        asyncio.run(
            bridge.prepare(
                ContinuityTarget(
                    provider_id="cloud.sessions",
                    opaque_id="remote-1",
                ),
                payload,
                _source(),
            )
        )

    assert runtime.observed_path is None


@requires_secure_staging
def test_coding_portable_activation_bridge_cleans_up_when_product_prepare_fails(
    tmp_path: Path,
) -> None:
    class _FailingRuntime(_Runtime):
        async def prepare_restore_session_operation(
            self,
            session_id: str | Path,
            *,
            fallback_cwd: str | Path | None = None,
            missing_cwd: str = "error",
        ) -> _PreparedOperation:
            self.observed_path = Path(session_id)
            self.observed_bytes = self.observed_path.read_bytes()
            raise RuntimeError("canonical prepare failed")

    runtime = _FailingRuntime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )
    target = ContinuityTarget(
        provider_id="cloud.sessions",
        opaque_id="remote-1",
    )

    with pytest.raises(RuntimeError, match="canonical prepare failed"):
        asyncio.run(bridge.prepare(target, payload, _source()))

    assert runtime.observed_path is not None
    assert not runtime.observed_path.exists()


@requires_secure_staging
def test_coding_portable_activation_bridge_cleans_up_when_write_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    staged_path: list[Path] = []
    original = continuity_module._write_private_continuity_payload

    def delayed_write(
        root: Path,
        payload: ContinuityActivationPayload,
    ) -> object:
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release continuity write")
        staged = original(root, payload)
        staged_path.append(staged.path)
        return staged

    monkeypatch.setattr(
        continuity_module,
        "_write_private_continuity_payload",
        delayed_write,
    )
    runtime = _Runtime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )

    async def scenario() -> None:
        task = asyncio.create_task(
            bridge.prepare(
                ContinuityTarget(
                    provider_id="cloud.sessions",
                    opaque_id="remote-1",
                ),
                payload,
                _source(),
            )
        )
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert staged_path
    assert not staged_path[0].exists()
    assert list((tmp_path / "continuity").iterdir()) == []
    assert runtime.observed_path is None


@requires_secure_staging
def test_coding_portable_activation_bridge_cleans_up_when_prepare_is_cancelled(
    tmp_path: Path,
) -> None:
    class _BlockingRuntime(_Runtime):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def prepare_restore_session_operation(
            self,
            session_id: str | Path,
            *,
            fallback_cwd: str | Path | None = None,
            missing_cwd: str = "error",
        ) -> _PreparedOperation:
            path = Path(session_id)
            self.observed_path = path
            self.observed_bytes = path.read_bytes()
            self.started.set()
            await self.release.wait()
            return self.prepared

    runtime = _BlockingRuntime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )

    async def scenario() -> None:
        task = asyncio.create_task(
            bridge.prepare(
                ContinuityTarget(
                    provider_id="cloud.sessions",
                    opaque_id="remote-1",
                ),
                payload,
                _source(),
            )
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert runtime.observed_path is not None
    assert not runtime.observed_path.exists()


@requires_secure_staging
def test_coding_portable_activation_bridge_rejects_replaced_temporary_file(
    tmp_path: Path,
) -> None:
    replacement = b"replacement"

    class _ReplacingRuntime(_Runtime):
        async def prepare_restore_session_operation(
            self,
            session_id: str | Path,
            *,
            fallback_cwd: str | Path | None = None,
            missing_cwd: str = "error",
        ) -> _PreparedOperation:
            prepared = await super().prepare_restore_session_operation(
                session_id,
                fallback_cwd=fallback_cwd,
                missing_cwd=missing_cwd,
            )
            path = Path(session_id)
            path.unlink()
            path.write_bytes(replacement)
            return prepared

    runtime = _ReplacingRuntime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
    )
    payload = ContinuityActivationPayload.from_bytes(
        b"{}\n",
        media_type=CONTINUITY_JSONL_MEDIA_TYPE,
    )

    with pytest.raises(OSError, match="identity changed"):
        asyncio.run(
            bridge.prepare(
                ContinuityTarget(
                    provider_id="cloud.sessions",
                    opaque_id="remote-1",
                ),
                payload,
                _source(),
            )
        )

    assert runtime.prepared.aborted
    assert runtime.observed_path is not None
    assert runtime.observed_path.read_bytes() == replacement
