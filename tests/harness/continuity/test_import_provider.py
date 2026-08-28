"""Executable contract for portable Continuity imports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

import loushang.harness.continuity.import_provider as import_provider_module
from loushang.harness.continuity import (
    CONTINUITY_JSONL_MEDIA_TYPE,
    ContinuityActivationPayload,
    ContinuityImportProviderPack,
    ContinuityPreview,
    ContinuityProviderDescriptor,
    ContinuityTarget,
    ProviderPage,
    ProviderQuery,
)


class _LyingBytes(bytes):
    def __len__(self) -> int:
        return 1


def test_portable_activation_payload_rejects_bytes_subclasses() -> None:
    data = _LyingBytes(b"not-one-byte")

    with pytest.raises(ValueError, match="built-in bytes"):
        ContinuityActivationPayload(
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
            data=data,
            digest=hashlib.sha256(data).hexdigest(),
        )
    with pytest.raises(TypeError, match="built-in bytes"):
        ContinuityActivationPayload.from_bytes(
            data,
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
        )


def test_portable_activation_payload_validates_digest_and_cwd() -> None:
    with pytest.raises(ValueError, match="does not match"):
        ContinuityActivationPayload(
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
            data=b"{}\n",
            digest="0" * 64,
        )


def test_portable_activation_payload_enforces_exact_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(import_provider_module, "MAX_CONTINUITY_ACTIVATION_BYTES", 4)

    assert (
        ContinuityActivationPayload.from_bytes(
            b"1234",
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
            cwd_override="x" * 4096,
        ).byte_size
        == 4
    )
    with pytest.raises(ValueError, match="hard limit"):
        ContinuityActivationPayload.from_bytes(
            b"12345",
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
        )
    with pytest.raises(ValueError, match="non-empty"):
        ContinuityActivationPayload.from_bytes(
            b"",
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
        )
    with pytest.raises(ValueError, match="cwd override"):
        ContinuityActivationPayload.from_bytes(
            b"1",
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
            cwd_override="x" * 4097,
        )
    with pytest.raises(ValueError, match="media type"):
        ContinuityActivationPayload.from_bytes(
            b"1",
            media_type="application/octet-stream",
        )
    with pytest.raises(ValueError, match="version"):
        ContinuityActivationPayload(
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
            data=b"1",
            digest=hashlib.sha256(b"1").hexdigest(),
            schema_version=2,
        )
    with pytest.raises(ValueError, match="cwd override"):
        ContinuityActivationPayload.from_bytes(
            b"{}\n",
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
            cwd_override="bad\x00cwd",
        )


@dataclass
class _ImportProvider:
    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return ContinuityProviderDescriptor(
            provider_id="example.sessions",
            experience_id="coding",
            domain_ids=("coding",),
            label="Example sessions",
            supported_actions=("activate",),
        )

    async def query(self, _request: ProviderQuery) -> ProviderPage:
        raise NotImplementedError

    async def preview(self, _target: ContinuityTarget) -> ContinuityPreview:
        raise NotImplementedError

    async def prepare_import(self, _target: ContinuityTarget) -> object:
        raise NotImplementedError


def test_portable_import_pack_is_bounded_and_protocol_checked() -> None:
    provider = _ImportProvider()

    assert ContinuityImportProviderPack((provider,)).providers == (provider,)
    with pytest.raises(ValueError, match="must not be empty"):
        ContinuityImportProviderPack(())
    with pytest.raises(TypeError, match="invalid Provider"):
        ContinuityImportProviderPack((object(),))  # type: ignore[arg-type]
    assert len(ContinuityImportProviderPack((provider,) * 32).providers) == 32
    with pytest.raises(ValueError, match="exceeds"):
        ContinuityImportProviderPack((provider,) * 33)
