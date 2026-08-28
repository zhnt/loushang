"""Executable contract for portable Continuity imports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

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
