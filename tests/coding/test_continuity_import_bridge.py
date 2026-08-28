"""Coding adapter tests for portable Continuity imports."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.coding.continuity import CodingContinuityActivationBridge
from loushang.harness.continuity import (
    CONTINUITY_BUNDLE_MEDIA_TYPE,
    CONTINUITY_JSONL_MEDIA_TYPE,
    CallbackPreparedActivationLease,
    ContinuityActivationPayload,
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
)


@dataclass
class _Runtime:
    observed_path: Path | None = None
    observed_bytes: bytes | None = None
    observed_mode: int | None = None
    fallback_cwd: str | None = None
    missing_cwd: str | None = None

    async def prepare_restore_session_operation(
        self,
        session_id: str | Path,
        *,
        fallback_cwd: str | Path | None = None,
        missing_cwd: str = "error",
    ) -> CallbackPreparedActivationLease:
        path = Path(session_id)
        self.observed_path = path
        self.observed_bytes = path.read_bytes()
        self.observed_mode = stat.S_IMODE(path.stat().st_mode)
        self.fallback_cwd = None if fallback_cwd is None else str(fallback_cwd)
        self.missing_cwd = missing_cwd
        target = ContinuityTarget(
            provider_id="cloud.sessions",
            opaque_id="remote-1",
        )
        return CallbackPreparedActivationLease(
            target=target,
            disposition="in_place",
            consume=lambda: "canonical-session",
        )


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
    assert asyncio.run(prepared.consume()) == "canonical-session"


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
        ) -> CallbackPreparedActivationLease:
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
