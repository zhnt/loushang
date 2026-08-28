from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from loushang.harness.continuity import (
    CONTINUITY_JSONL_MEDIA_TYPE,
    CallbackPreparedActivationLease,
    ContinuityActivationPayload,
    ContinuityHub,
    ContinuityPluginAdmissionError,
    ContinuityPluginProviderContext,
    ContinuityPluginProviderContribution,
    ContinuityPluginProviderPack,
    ContinuityPreview,
    ContinuityPreviewSection,
    ContinuityProviderDescriptor,
    ContinuityProviderSourceDescriptor,
    ContinuityQuery,
    ContinuitySummary,
    ContinuityTarget,
    ExperienceDescriptor,
    ProviderPage,
    ProviderPageItem,
    ProviderQuery,
    compose_experience_continuity,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginInstanceRevisionRef,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.runtime import (
    CONTINUITY_PROVIDER_PACKS_SLOT,
    ProductRuntimePlan,
    RuntimeCapabilityRegistry,
    RuntimeProfileAdmissionPolicy,
    RuntimeProfileBinder,
    RuntimeProfileResolver,
)

_NOW = datetime(2026, 8, 28, tzinfo=UTC).isoformat()


@dataclass
class _PreparedImport:
    target: ContinuityTarget
    payload: ContinuityActivationPayload
    aborted: int = 0
    closed: int = 0

    async def abort(self) -> None:
        self.aborted += 1

    async def close(self) -> None:
        self.closed += 1


@dataclass
class _PluginProvider:
    provider_id: str = "cloud.sessions"
    imports: list[_PreparedImport] = field(default_factory=list)
    queries: int = 0

    @property
    def descriptor(self) -> ContinuityProviderDescriptor:
        return ContinuityProviderDescriptor(
            provider_id=self.provider_id,
            experience_id="coding",
            domain_ids=("coding",),
            primary_domain_id="coding",
            label="Cloud sessions",
            supported_sorts=("updated", "created"),
            implementation_version=1,
        )

    async def query(self, _request: ProviderQuery) -> ProviderPage:
        self.queries += 1
        target = ContinuityTarget(
            provider_id=self.provider_id,
            opaque_id="remote-1",
            revision="revision-1",
        )
        return ProviderPage(
            items=(
                ProviderPageItem(
                    summary=ContinuitySummary(
                        target=target,
                        domain_ids=("coding",),
                        primary_domain_id="coding",
                        title="Remote session",
                        updated_at=_NOW,
                        actions=("activate", "delete"),
                    ),
                    after_cursor="remote-1",
                ),
            ),
            has_more=False,
            index_state="fresh",
            index_generation="generation-1",
            query_snapshot="snapshot-1",
        )

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        return ContinuityPreview(
            target=target,
            revision=target.revision,
            heading="Remote session",
            sections=(ContinuityPreviewSection(kind="text", text="remote"),),
        )

    async def prepare_import(self, target: ContinuityTarget) -> _PreparedImport:
        prepared = _PreparedImport(
            target=target,
            payload=ContinuityActivationPayload.from_bytes(
                b'{"type":"conversation"}\n',
                media_type=CONTINUITY_JSONL_MEDIA_TYPE,
                cwd_override="/workspace",
            ),
        )
        self.imports.append(prepared)
        return prepared


@dataclass
class _Bridge:
    prepared: list[
        tuple[
            ContinuityTarget,
            ContinuityActivationPayload,
            ContinuityProviderSourceDescriptor,
        ]
    ] = field(default_factory=list)
    consumed: int = 0
    aborted: int = 0

    async def prepare(
        self,
        target: ContinuityTarget,
        payload: ContinuityActivationPayload,
        source: ContinuityProviderSourceDescriptor,
    ) -> CallbackPreparedActivationLease:
        self.prepared.append((target, payload, source))

        def consume() -> str:
            self.consumed += 1
            return "canonical-session"

        def abort() -> None:
            self.aborted += 1

        return CallbackPreparedActivationLease(
            target=target,
            disposition="in_place",
            consume=consume,
            abort=abort,
        )


@dataclass
class _Authorities:
    instance: PluginInstanceRevisionRef
    trust: PluginSourceTrustSnapshotV1

    def read_instance(self, _plugin_id: str) -> PluginInstanceRevisionRef:
        return self.instance

    def read_trust(
        self,
        _plugin_id: str,
        _source_identity: str,
    ) -> PluginSourceTrustSnapshotV1:
        return self.trust


def _trust(*, trusted: bool = True) -> PluginSourceTrustSnapshotV1:
    return PluginSourceTrustSnapshotV1(
        plugin_id="cloud.history",
        package_source_identity="installed:cloud.history",
        source_trust_class="installed",
        source_trust_policy_revision="trust-policy-1",
        trusted=trusted,
    )


def _contribution(
    provider: _PluginProvider,
    authorities: _Authorities,
    contexts: list[ContinuityPluginProviderContext],
) -> ContinuityPluginProviderContribution:
    return ContinuityPluginProviderContribution(
        product_id="coding",
        experience_id="coding",
        contribution_ref=PluginContributionRef(
            plugin_id="cloud.history",
            contribution_id="sessions",
        ),
        instance_revision_ref=authorities.instance,
        trust_snapshot=authorities.trust,
        implementation_version=1,
        create=lambda context: (
            contexts.append(context)
            or ContinuityPluginProviderPack(providers=(provider,))
        ),
        current_instance_reader=authorities.read_instance,
        current_trust_reader=authorities.read_trust,
        binding_inputs={"account": "primary"},
    )


def _hub(
    contribution: ContinuityPluginProviderContribution,
    bridge: _Bridge,
) -> ContinuityHub:
    runtime = contribution.runtime_contribution(bridge)
    plan = ProductRuntimePlan(
        product_id="coding",
        slots=(CONTINUITY_PROVIDER_PACKS_SLOT,),
    )
    admitted = RuntimeProfileAdmissionPolicy(
        grants=(runtime.grant,),
        slot_permissions={
            CONTINUITY_PROVIDER_PACKS_SLOT.key: frozenset({"continuity.provider"})
        },
    ).admit(plan, (runtime.layer,))
    profile = RuntimeProfileResolver().resolve(
        plan,
        layers=admitted.require_valid(),
    )
    binding = RuntimeProfileBinder(
        RuntimeCapabilityRegistry((runtime.implementation,))
    ).bind_sync(profile, context=object())
    composition = compose_experience_continuity(
        experience=ExperienceDescriptor(
            experience_id="coding",
            label="Coding",
            domain_ids=("coding",),
        ),
        binding=binding,
    )
    return ContinuityHub(composition, cursor_secret=b"test-secret")


def test_plugin_contribution_uses_narrow_context_and_projects_read_only_source() -> None:
    provider = _PluginProvider()
    instance = PluginInstanceRevisionRef(
        instance_id="cloud-history-installed",
        plugin_id="cloud.history",
        revision=3,
    )
    authorities = _Authorities(instance=instance, trust=_trust())
    contexts: list[ContinuityPluginProviderContext] = []
    hub = _hub(_contribution(provider, authorities, contexts), _Bridge())

    async def scenario() -> None:
        page = await hub.query(ContinuityQuery())
        assert len(page.items) == 1
        assert page.items[0].actions == ("activate",)
        delete_page = await hub.query(
            ContinuityQuery(required_actions=("delete",))
        )
        assert delete_page.items == ()
        assert provider.queries == 1

    asyncio.run(scenario())
    assert len(contexts) == 1
    assert contexts[0].binding_inputs == {"account": "primary"}
    assert not hasattr(contexts[0], "runtime")
    source = hub.reference().observation.provider_sources[0]
    assert source.source == "plugin"
    assert source.plugin_id == "cloud.history"
    assert source.instance_revision == 3
    assert source.source_trust_policy_revision == "trust-policy-1"


def test_plugin_activation_is_bridged_and_settles_both_prepared_leases() -> None:
    provider = _PluginProvider()
    instance = PluginInstanceRevisionRef(
        instance_id="cloud-history-installed",
        plugin_id="cloud.history",
        revision=1,
    )
    authorities = _Authorities(instance=instance, trust=_trust())
    bridge = _Bridge()
    hub = _hub(_contribution(provider, authorities, []), bridge)

    async def scenario() -> None:
        page = await hub.query(ContinuityQuery())
        target = page.items[0].target
        lease = await hub.prepare(target)
        assert await lease.consume() == "canonical-session"
        await lease.close()

    asyncio.run(scenario())
    assert bridge.consumed == 1
    assert bridge.aborted == 0
    assert bridge.prepared[0][2].plugin_id == "cloud.history"
    assert provider.imports[0].closed == 1
    assert provider.imports[0].aborted == 0


def test_plugin_authority_is_revalidated_before_each_operation() -> None:
    provider = _PluginProvider()
    instance = PluginInstanceRevisionRef(
        instance_id="cloud-history-installed",
        plugin_id="cloud.history",
        revision=1,
    )
    authorities = _Authorities(instance=instance, trust=_trust())
    hub = _hub(_contribution(provider, authorities, []), _Bridge())
    authorities.instance = replace(instance, revision=2)

    async def scenario() -> None:
        page = await hub.query(ContinuityQuery())
        assert page.partial is True
        assert page.provider_diagnostics[0].code == "continuity_provider_query_failed"
        assert provider.queries == 0

    asyncio.run(scenario())


def test_untrusted_plugin_contribution_is_rejected_before_factory_binding() -> None:
    instance = PluginInstanceRevisionRef(
        instance_id="cloud-history-installed",
        plugin_id="cloud.history",
        revision=1,
    )
    authorities = _Authorities(instance=instance, trust=_trust(trusted=False))

    with pytest.raises(ContinuityPluginAdmissionError) as captured:
        _contribution(_PluginProvider(), authorities, [])

    assert captured.value.code == "continuity_plugin_source_untrusted"
