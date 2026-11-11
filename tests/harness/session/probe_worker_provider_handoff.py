"""Shared Session handoff with real Supervisor/query/facet/admission objects.

Reuse the existing in-memory transport. Native acquisition and Product policy
are controlled ports: this does not prove physical native or Coding admission.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.harness.worker._ordinary_prepare as native_programs
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerPolicy,
    CapabilityWorkerProviderBindingSpec,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstanceRevisionRef
from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.session._worker_provider import (
    _abort_worker_provider,
    _commit_worker_provider,
    _prepare_native_worker_component,
    _WorkerAttemptRelease,
)
from loushang.harness.worker._ordinary_prepare import _NativeWorkerAttempt
from loushang.harness.worker.capability_query import (
    CapabilityWorkerFacetGrantV1,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.facet_proxy import CapabilityWorkerReadOnlyFacetProxy
from loushang.harness.worker.protocol import WorkerProtocolMessage
from tests.harness.capabilities.test_provider_selection import (
    _candidate,
    _definition,
    _provider,
)
from tests.harness.worker.test_capability_query import (
    _authority,
    _domain_binding,
    _healthy_supervisor,
    _identity,
    _runtime,
)
from tests.harness.worker.test_product_activation import _policy, _receipt


@dataclass(frozen=True)
class _Prepared:
    binding: CapabilityBundleProviderBinding
    facet: CapabilityWorkerReadOnlyFacetProxy
    receipt_fingerprint: str
    worker_admission_fingerprint: str
    _release: _WorkerAttemptRelease
    _commit: Callable[[], None] | None


async def _scenario(tmp_path: Path, case: str) -> None:
    supervisor, transport, _process = await _healthy_supervisor(tmp_path)
    domain_binding = replace(
        _domain_binding(), allowed_capability_ids=("coding.lsp.hover",)
    )
    current = _authority()
    definition = replace(
        _definition("coding.lsp.hover"),
        owner_id=domain_binding.owner_id,
        facets=("hover",),
    )
    provider = replace(_provider(definition), facets=("hover",))
    runtime = WorkerRuntimeBindingV1.capture(
        package_root=tmp_path,
        configuration=PluginLocalWorkerConfiguration(
            entrypoint="worker", protocol="capability.query", protocol_version=1
        ),
    )
    request = ManagedWorkerLaunchRequestV1(
        identity=supervisor.identity, runtime=runtime, validate_current=lambda: None
    )
    spec = CapabilityWorkerProviderBindingSpec(
        plugin_id=domain_binding.plugin_id,
        contribution_id=domain_binding.contribution_id,
        capability_id=definition.capability_id,
        owner_id=domain_binding.owner_id,
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        manifest_digest="c" * 64,
        reservation_fingerprint="d" * 64,
        declaration_fingerprint=current.declaration_fingerprint,
        worker_configuration_fingerprint=runtime.worker_configuration_fingerprint,
        executable_digest=runtime.executable_digest,
        executable_size=runtime.executable_size,
        declared_required=False,
        native_platform="linux-x86_64",
    )
    candidate = replace(
        _candidate(definition, provider, marker="a"),
        provider=replace(provider, source_id=f"plugin:{spec.plugin_id}"),
        binding_spec=spec,
        product_id="coding",
        scope_id=domain_binding.scope_id,
        product_policy_revision=current.product_policy_revision,
        declaration_fingerprint=current.declaration_fingerprint,
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="review-pack@test", plugin_id=spec.plugin_id, revision=1
        ),
        source_trust_class="local-worker-candidate",
    )
    provider = candidate.provider
    owner = CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id=definition.owner_id,
            policy_revision=current.owner_policy_revision,
            revocation_epoch=current.revocation_epoch,
            allowed_provider_ids=(provider.provider_id,),
            allowed_source_trust_classes=(candidate.source_trust_class,),
            allowed_execution_models=("local_worker",),
            authority_ceiling=(),
        )
    )
    eligibility = owner.grant_eligibility(candidate, issued_at=100, expires_at=220)
    admission = owner.admit(
        candidate, eligibility=eligibility, issued_at=120, expires_at=200
    )
    resolved = ProductCapabilityProviderResolver().resolve(
        ProductCapabilityProviderSelectionPlanV1(
            product_id="coding",
            roots=(definition.capability_id,),
            choices=(
                ProductCapabilityProviderChoice(
                    capability_id=definition.capability_id,
                    provider_id=provider.provider_id,
                    candidate_fingerprint=admission.candidate_fingerprint,
                ),
            ),
            policy_revision="test-product-choice",
        ),
        definitions=(definition,),
        admissions=(admission,),
        owner_snapshots=(owner.snapshot(),),
        evaluated_at=150,
    )
    receipt = _receipt(
        replace(
            _policy(required=False),
            product_scope_id=domain_binding.scope_id,
            plugin_id=spec.plugin_id,
            contribution_id=spec.contribution_id,
            allowed_contribution_ids=(spec.contribution_id,),
            owner_selection_generation=current.owner_generation,
            declaration_fingerprint=current.declaration_fingerprint,
            worker_configuration_fingerprint=runtime.worker_configuration_fingerprint,
        )
    )
    events: list[str] = []
    native_tasks = []

    def issue_grant(*, capability_id, facet_id):
        return CapabilityWorkerFacetGrantV1(
            capability_id=capability_id,
            facet_id=facet_id,
            binding_fingerprint=domain_binding.fingerprint,
            authority_fingerprint=current.fingerprint,
            owner_policy_revision=current.owner_policy_revision,
        ), lambda value: value

    authority = SimpleNamespace(
        binding=domain_binding,
        current_authority=lambda: current,
        issue_read_only_facet=issue_grant,
    )
    expected = bind_capability_query_worker_adapter(
        supervisor=supervisor,
        binding=domain_binding,
        authority_reader=lambda: current,
        enabled=True,
    ).admit()

    async def release():
        events.append("release")
        if case == "clock_error":
            raise RuntimeError("controlled cleanup failure")
        await supervisor.fence(code="test-handoff-release")

    async def native():
        native_tasks.append(asyncio.current_task())
        return _NativeWorkerAttempt(
            request=request,
            supervisor=supervisor,
            release=release,
            commit_activation=lambda: events.append("commit"),
        )

    def bind_authority(value):
        assert value is request
        return authority

    def capture(**values):
        assert values["resolved"] is resolved.entries[0]
        assert values["capability_authority"] is authority
        assert values["release_attempt"] is release
        return candidate, domain_binding

    policy = SimpleNamespace(
        capability_id=definition.capability_id,
        facet_id="hover",
        bind_authority=bind_authority,
        capture=capture,
        read_candidate=lambda value: candidate,
    )

    def clock():
        if case == "clock_error":
            raise StopIteration("controlled clock exhaustion")
        return 150

    task = asyncio.create_task(
        _prepare_native_worker_component(
            prepare_native=native,
            policy=policy,
            receipt=receipt,
            resolved_providers=resolved,
            expected_admission=expected,
            graph_generation=1,
            clock=clock,
            base_policy_binding=None,
            renewing_provider_owner=owner,
            release_type=_WorkerAttemptRelease,
            prepared_factory=_Prepared,
            pending_failure=RuntimeError,
            provider_error_type=RuntimeError,
            provider_error_prefix="handoff",
            fingerprint_namespace=b"handoff-test/v1\0",
            cleanup_note="cleanup failed: ",
        )
    )
    try:
        await transport.wait_for_writes(2)
        assert native_tasks == [task]
        if case == "cancel_describe":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert events == ["release"]
            return
        query = transport.message(1)
        transport.feed(
            WorkerProtocolMessage.create(
                "result",
                correlationId=query.fields["correlationId"],
                payload={
                    "capabilities": [
                        {
                            "capabilityId": definition.capability_id,
                            "descriptorVersion": 1,
                            "facetIds": ["hover"],
                        }
                    ],
                    "responseVersion": 1,
                },
            )
        )
        if case == "clock_error":
            with pytest.raises(RuntimeError) as observed:
                await task
            assert isinstance(observed.value.__cause__, StopIteration)
            assert observed.value.__cause__.__notes__ == [
                "cleanup failed: RuntimeError"
            ]
            assert not getattr(observed.value, "__notes__", [])
            assert events == ["release"]
            return
        prepared = await task
        assert prepared.facet.state == "staged" and events == []
        with pytest.raises(RuntimeError, match="publication_missing"):
            _commit_worker_provider(
                prepared.facet, prepared._commit, RuntimeError, "handoff"
            )
        prepared.facet.publish(
            admission=expected, owner_generation=current.owner_generation
        )
        _commit_worker_provider(
            prepared.facet, prepared._commit, RuntimeError, "handoff"
        )
        assert events == ["commit"]
        assert await _abort_worker_provider(prepared.facet, prepared._release)
        assert not await _abort_worker_provider(prepared.facet, prepared._release)
        assert prepared.facet.state == "retired" and events == ["commit", "release"]
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await supervisor.fence(code="test-handoff-cleanup")


@pytest.mark.parametrize("case", ("publish_abort", "clock_error", "cancel_describe"))
def test_worker_provider_retains_custody_until_graph_or_failure(
    tmp_path: Path, case: str
):
    asyncio.run(_scenario(tmp_path, case))


@pytest.mark.parametrize("platform", ("posix", "windows"))
def test_native_failure_before_handoff_closes_original_stack_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
):
    """Both real programs fail before native/OS effects; Session must not retry cleanup."""
    closed = []
    primary = ValueError("controlled materialization failure")

    class Stack(AsyncExitStack):
        async def aclose(self):
            closed.append(self)
            await super().aclose()

    monkeypatch.setattr(native_programs, "AsyncExitStack", Stack)
    runtime = _runtime(tmp_path)
    identity = _identity(runtime)

    def materialize(attempt_id):
        assert attempt_id == identity.attempt_id
        raise primary

    program = (
        native_programs._prepare_posix_native_worker
        if platform == "posix"
        else native_programs._prepare_windows_native_worker
    )

    async def scenario():
        with pytest.raises(ValueError) as observed:
            await _prepare_native_worker_component(
                prepare_native=partial(
                    program,
                    launch_source=SimpleNamespace(materialize=materialize),
                    activation=SimpleNamespace(),
                    pending_launch=SimpleNamespace(identity=identity),
                    receipt=_receipt(),
                    resume_parent_context=None,
                    resume_settlement=None,
                    failure=RuntimeError,
                    parent_failure=RuntimeError,
                    failure_code_prefix="test",
                    task_name_prefix="test-before-handoff-",
                    cleanup_note="cleanup failed: ",
                    correlation_id="test-before-handoff",
                ),
                policy=SimpleNamespace(),
                receipt=_receipt(),
                resolved_providers=SimpleNamespace(entries=()),
                expected_admission=None,
                graph_generation=1,
                clock=lambda: 150,
                base_policy_binding=None,
                renewing_provider_owner=None,
                release_type=_WorkerAttemptRelease,
                prepared_factory=_Prepared,
                pending_failure=RuntimeError,
                provider_error_type=RuntimeError,
                provider_error_prefix="test",
                fingerprint_namespace=b"test/v1\0",
                cleanup_note="cleanup failed: ",
            )
        assert observed.value is primary
        assert not getattr(primary, "__notes__", [])
        assert len(closed) == 1

    asyncio.run(scenario())
