from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.coding.continuity import (
    CodingContinuityActivationBridge,
    bind_coding_continuity,
)
from loushang.harness.continuity import (
    CONTINUITY_BUNDLE_MEDIA_TYPE,
    CONTINUITY_JSONL_MEDIA_TYPE,
    CallbackPreparedActivationLease,
    ContinuityActivationPayload,
    ContinuityPluginProviderContribution,
    ContinuityPluginProviderPack,
    ContinuityPreview,
    ContinuityProviderDescriptor,
    ContinuityProviderSourceDescriptor,
    ContinuityTarget,
    ProviderPage,
    ProviderQuery,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginInstanceRevisionRef,
    PluginSourceTrustSnapshotV1,
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
        source="plugin",
        source_id="plugin:cloud:r1:sessions",
        implementation="plugin:cloud:continuity:sessions",
        implementation_version=1,
        plugin_id="cloud",
        contribution_id="sessions",
        instance_id="cloud-installed",
        instance_revision=1,
        source_trust_class="installed",
        source_trust_policy_revision="trust-1",
    )


@pytest.mark.parametrize(
    ("media_type", "suffix"),
    (
        (CONTINUITY_JSONL_MEDIA_TYPE, ".jsonl"),
        (CONTINUITY_BUNDLE_MEDIA_TYPE, ".loushang.zip"),
    ),
)
def test_coding_plugin_activation_bridge_uses_private_bounded_temporary_copy(
    tmp_path: Path,
    media_type: str,
    suffix: str,
) -> None:
    runtime = _Runtime()
    bridge = CodingContinuityActivationBridge(
        runtime,  # type: ignore[arg-type]
        temporary_root=tmp_path / "continuity",
    )
    payload_bytes = b'{"type":"conversation"}\n'
    payload = ContinuityActivationPayload(
        media_type=media_type,
        data=payload_bytes,
        digest=hashlib.sha256(payload_bytes).hexdigest(),
        cwd_override="/workspace",
    )
    target = ContinuityTarget(
        provider_id="cloud.sessions",
        opaque_id="remote-1",
    )

    prepared = asyncio.run(bridge.prepare(target, payload, _source()))

    assert runtime.observed_path is not None
    assert runtime.observed_path.name.endswith(suffix)
    assert runtime.observed_bytes == payload_bytes
    assert runtime.observed_mode == 0o600
    assert runtime.fallback_cwd == "/workspace"
    assert runtime.missing_cwd == "fallback"
    assert not runtime.observed_path.exists()
    assert asyncio.run(prepared.consume()) == "canonical-session"


def test_coding_plugin_activation_bridge_rejects_product_budget_before_write(
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


def test_coding_plugin_activation_bridge_rejects_linked_temporary_root(
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


class _RemoteProvider:
    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return ContinuityProviderDescriptor(
            provider_id="cloud.sessions",
            experience_id="coding",
            domain_ids=("coding",),
            label="Cloud sessions",
            implementation_version=1,
        )

    async def query(self, _request: ProviderQuery) -> ProviderPage:
        raise NotImplementedError

    async def preview(self, _target: ContinuityTarget) -> ContinuityPreview:
        raise NotImplementedError

    async def prepare_import(self, _target: ContinuityTarget) -> object:
        raise NotImplementedError


def test_bind_coding_continuity_composes_admitted_plugin_provenance(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    instance = PluginInstanceRevisionRef(
        instance_id="cloud-installed",
        plugin_id="cloud",
        revision=2,
    )
    trust = PluginSourceTrustSnapshotV1(
        plugin_id="cloud",
        package_source_identity="installed:cloud",
        source_trust_class="installed",
        source_trust_policy_revision="trust-2",
        trusted=True,
    )
    contribution = ContinuityPluginProviderContribution(
        product_id="coding",
        experience_id="coding",
        contribution_ref=PluginContributionRef("cloud", "sessions"),
        instance_revision_ref=instance,
        trust_snapshot=trust,
        implementation_version=1,
        create=lambda _context: ContinuityPluginProviderPack(
            providers=(_RemoteProvider(),)
        ),
        current_instance_reader=lambda _plugin_id: instance,
        current_trust_reader=lambda _plugin_id, _source: trust,
    )

    composition = bind_coding_continuity(
        runtime,  # type: ignore[arg-type]
        plugin_contributions=(contribution,),
        temporary_root=tmp_path / "continuity",
    )
    observation = composition.hub.reference().observation

    assert [provider.provider_id for provider in observation.providers] == [
        "coding.sessions",
        "cloud.sessions",
    ]
    assert [source.source for source in observation.provider_sources] == [
        "product",
        "plugin",
    ]
    assert observation.provider_sources[1].plugin_id == "cloud"
    with pytest.raises(RuntimeError, match="already sealed"):
        bind_coding_continuity(
            runtime,  # type: ignore[arg-type]
            plugin_contributions=(contribution,),
        )

    asyncio.run(composition.shutdown())
