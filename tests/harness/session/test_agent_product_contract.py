from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from loushang.agent import Agent, ModelCallPreparation
from loushang.ai import Context
from loushang.ai.model import Capabilities, Model
from loushang.ai.options import CallOptions
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.harness.approval.plugin_activation import (
    PluginActivationDecisionJournal,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
)
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
    CapabilityBundleProvider,
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
    StagedResourceCompositionCandidate,
    stage_resource_composition_candidate,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.component_host import CapabilityComponentHost
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionError,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionPolicy,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionRecord,
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerPolicy,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
)
from loushang.harness.capabilities.workspace_provider import (
    workspace_capability_provider_binding,
)
from loushang.harness.config.agent import (
    CompactionSettings,
    ControlConfig,
    RetrySettings,
    SettingsManager,
)
from loushang.harness.conversation import ConversationKey, MemoryConversationStore
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.plugin_authoring.capability_provider import (
    PLUGIN_PROVIDER_SELECTION_RULE,
    CapabilityProviderDeclarationPayload,
    PluginSymbolReference,
)
from loushang.harness.plugin_authoring.consumer_pack import (
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.resource_catalog.product_inputs import (
    InitialResourceCatalogProductAdapter,
    InitialResourceCatalogProductSelection,
    ProductEmbeddedResourceCollectionSpec,
    ProductNativeResourceRootSpec,
)
from loushang.harness.resource_catalog.session_bootstrap import (
    InitialSessionResourceCatalogBootstrap,
    InitialSessionResourceCatalogInputs,
)
from loushang.harness.resources._catalog_embedded_source import (
    EmbeddedResourceCollectionHandle,
    mint_embedded_resource_collection_handle,
)
from loushang.harness.resources._catalog_native_source import (
    mint_native_resource_root_handle,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
    PluginDeclarationSource,
)
from loushang.harness.resources.plugins.import_realm import PluginImportRealm
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime import (
    CancellationSignal,
    RegistrationIdentity,
    RegistrationOwner,
    RuntimeProfileResolver,
)
from loushang.harness.runtime.session_operations import (
    SessionOperationCandidate,
    SessionOperationCoordinator,
)
from loushang.harness.runtime.transition import SessionTransitionHost
from loushang.harness.session import AgentProductSession
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
)
from loushang.harness.session.product_composition_assembly import (
    ProductCapabilityProviderOwnerBinding,
    ProductCompositionAssemblyError,
    ProductCompositionAssemblyRequest,
    ProductContributionOwnerBinding,
    ProductPluginCompositionAssemblyRequest,
    assemble_product_plugin_composition,
)
from loushang.harness.transcript import (
    AgentTranscriptLifecycle,
    AgentTranscriptProfile,
    AgentTranscriptRuntimeBinding,
    AgentTranscriptSessionFactory,
    BranchSummaryOutput,
    CompactionHookDecision,
    CompactionHookRequest,
    CompactionPreparation,
    CompactionResult,
    ContextCompactionCheckpoint,
    ProductTranscriptSession,
    create_agent_transcript_compaction_capability,
)
from loushang.harness.workspace.operations import LocalToolOperations
from loushang.harness.workspace.process import ProcessLaunchRequest


class _ContractTranscriptSession(ProductTranscriptSession[str, str]):
    _factory: ClassVar[AgentTranscriptSessionFactory[str, str]]

    @classmethod
    def _session_factory(cls) -> AgentTranscriptSessionFactory[str, str]:
        return cls._factory

    def _fork_binding_input(self) -> str:
        return self._lifecycle_session.product_binding


@dataclass
class _Footer:
    available_provider_count: int | None = None
    disposed: bool = False

    def set_extension_status(self, name: str, status: str | None) -> None:
        del name, status

    def set_available_provider_count(self, count: int) -> None:
        self.available_provider_count = count

    def dispose(self) -> None:
        self.disposed = True


class _ContractProductSession(AgentProductSession):
    def __init__(
        self,
        *,
        product_id: str,
        transcript: _ContractTranscriptSession,
        capability_runtime: StagedResourceCompositionCandidate,
        reserve_tokens: int,
        compact_percent: float,
        workspace_capability_binding: CapabilityBundleProviderBinding | None = None,
        capability_composition_inputs: SessionCapabilityCompositionInputs | None = None,
        capability_component_host: CapabilityComponentHost | None = None,
        capability_owner_generation_bindings: tuple[
            SessionCapabilityOwnerGenerationBinding, ...
        ] = (),
        resource_bundle: ResourceBundle | None = None,
        extension_runner: ExtensionRunner | None = None,
        initial_resource_catalog_bootstrap: (
            InitialSessionResourceCatalogBootstrap | None
        ) = None,
    ) -> None:
        self.product_id = product_id
        self.executor_calls: list[tuple[str, str | None]] = []
        self.hook_calls: list[tuple[str, str, object]] = []
        self.footer = _Footer()

        async def execute_compaction(
            *,
            preparation: CompactionPreparation,
            model: object,
            headers: Mapping[str, str] | None,
            signal: object | None,
            custom_instructions: str | None = None,
            prepare_model_call: object | None = None,
        ) -> CompactionResult:
            assert getattr(model, "id", None) == f"{product_id}-model"
            assert headers is None
            assert signal is self.agent.signal
            assert callable(prepare_model_call)
            self.executor_calls.append((product_id, custom_instructions))
            return CompactionResult(
                summary=f"{product_id} summary",
                first_kept_entry_id=preparation.first_kept_entry_id,
                tokens_before=preparation.tokens_before,
                details={"product": product_id},
            )

        async def execute_branch_summary(
            entries: object,
            signal: CancellationSignal,
            **options: object,
        ) -> BranchSummaryOutput:
            del entries, signal, options
            raise AssertionError("branch summary is outside this contract")

        async def retry_sleep(delay_ms: int, signal: CancellationSignal) -> None:
            del delay_ms, signal

        super().__init__(
            agent=Agent(
                initial_state={
                    "system_prompt": f"{product_id} prompt",
                    "model": _model(product_id),
                    "thinking_level": "off",
                }
            ),
            session_manager=transcript,
            capability_runtime=capability_runtime,
            execute_compaction=execute_compaction,
            execute_branch_summary=execute_branch_summary,
            get_changelog=lambda cwd, args: (cwd, args),
            copy_to_clipboard=lambda text: text,
            retry_sleep=retry_sleep,
            footer_data_provider=self.footer,
            settings_manager=SettingsManager(
                ControlConfig(
                    compaction=CompactionSettings(
                        enabled=True,
                        reserve_tokens=reserve_tokens,
                        compact_percent=compact_percent,
                        keep_recent_tokens=1,
                    ),
                    retry=RetrySettings(
                        enabled=False,
                        max_retries=0,
                        base_delay_ms=0,
                    ),
                )
            ),
            workspace_capability_binding=workspace_capability_binding,
            capability_composition_inputs=capability_composition_inputs,
            capability_component_host=capability_component_host,
            capability_owner_generation_bindings=(capability_owner_generation_bindings),
            resource_bundle=resource_bundle,
            extension_runner=extension_runner,
            initial_resource_catalog_bootstrap=(initial_resource_catalog_bootstrap),
        )

    async def _before_product_compaction(
        self,
        request: CompactionHookRequest,
    ) -> CompactionHookDecision | None:
        self.hook_calls.append(("before", request.reason, request.custom_instructions))
        return None

    async def _after_product_compaction(
        self,
        result: CompactionResult,
        record_id: str,
        from_hook: bool,
    ) -> None:
        self.hook_calls.append(("after", result.summary, (record_id, from_hook)))


def test_session_registration_inventory_keeps_retirement_retry_facts() -> None:
    owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="review",
        runtime_id="session:review",
        generation=1,
    )
    identity = RegistrationIdentity(
        surface="tool",
        public_key="review_lookup",
        registration_id="review-tool-v1",
    )
    session = object.__new__(AgentProductSession)
    session._tool_registry = SimpleNamespace(  # type: ignore[attr-defined]
        registration_inventory=((owner, identity, "active"),)
    )
    session._extension_runner = SimpleNamespace(  # type: ignore[attr-defined]
        registration_inventory=(),
        retired_registration_inventory=((owner, identity, "failed_retryable"),),
    )

    entries = session._effective_registration_entries()

    assert len(entries) == 1
    assert entries[0].registration_id == identity.registration_id
    assert entries[0].attachment == "pending_retirement"
    assert entries[0].state == "failed_retryable"


def test_agent_product_sessions_keep_compaction_strategy_and_state_isolated(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        research_transcript = await _new_transcript(
            tmp_path,
            product_id="research",
        )
        design_transcript = await _new_transcript(
            tmp_path,
            product_id="design",
        )
        research_capabilities = _capability_runtime("research")
        design_capabilities = _capability_runtime("design")
        research = _ContractProductSession(
            product_id="research",
            transcript=research_transcript,
            capability_runtime=research_capabilities,
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        design = _ContractProductSession(
            product_id="design",
            transcript=design_transcript,
            capability_runtime=design_capabilities,
            reserve_tokens=2_222,
            compact_percent=72.0,
        )
        research_events: list[dict[str, object]] = []
        design_events: list[dict[str, object]] = []
        research.subscribe(research_events.append)
        design.subscribe(design_events.append)
        graph_bind_calls = 0
        graph_bind_started = asyncio.Event()
        release_graph_bind = asyncio.Event()
        original_graph_bind = research._capability_graph_binder.bind

        async def counted_graph_bind(runtime, plan, bindings):
            nonlocal graph_bind_calls
            graph_bind_calls += 1
            graph_bind_started.set()
            await release_graph_bind.wait()
            return await original_graph_bind(runtime, plan, bindings)

        research._capability_graph_binder.bind = counted_graph_bind  # type: ignore[method-assign]
        direct_prepare = asyncio.create_task(
            research._model_call_runtime.prepare(
                ModelCallPreparation(
                    purpose="main",
                    sequence=1,
                    model=research.agent.model,
                    context=Context(system_prompt="research prompt", messages=[]),
                    options=CallOptions(),
                )
            )
        )
        await asyncio.wait_for(graph_bind_started.wait(), timeout=1)
        lifecycle_prepare = asyncio.create_task(research.prepare_model_call_runtime())
        try:
            await asyncio.sleep(0)
            assert lifecycle_prepare.done() is False
            release_graph_bind.set()
            prepared_options, _ = await asyncio.wait_for(
                asyncio.gather(direct_prepare, lifecycle_prepare),
                timeout=2,
            )
        finally:
            release_graph_bind.set()
            for task in (direct_prepare, lifecycle_prepare):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                direct_prepare,
                lifecycle_prepare,
                return_exceptions=True,
            )
        await research.prepare_model_call_runtime()
        effective_runtime = research.get_effective_runtime_view()

        assert graph_bind_calls == 1
        assert prepared_options.prepared_request_committer is not None
        assert research._capability_graph_runtime.runtime_id == (
            effective_runtime.runtime_id
        )
        assert not hasattr(research._model_call_runtime, "graph_runtime")
        assert not hasattr(research._model_call_runtime, "bind")
        assert not hasattr(research._model_call_runtime, "dispose")
        assert research.session_control is research
        assert design.session_control is design
        assert research.session_id == "research-session"
        assert design.session_id == "design-session"
        assert research.get_active_tool_names() == []
        assert design.get_active_tool_names() == []
        assert effective_runtime.product_id == "research"
        graph_snapshot = research._capability_graph_runtime.snapshot
        assert graph_snapshot is not None
        assert graph_snapshot.roots == ("harness.model_input",)
        nodes = {node.capability_id: node for node in graph_snapshot.nodes}
        assert tuple(
            requirement.capability_id
            for requirement in nodes["harness.model_input"].requirements
        ) == ("harness.session",)
        assert nodes["harness.resources"].requirements == ()
        assert tuple(
            requirement.capability_id
            for requirement in nodes["harness.session"].requirements
        ) == ("harness.resources",)
        assert nodes["harness.resources"].required_by == ("harness.session",)
        assert nodes["harness.session"].required_by == ("harness.model_input",)
        assert "harness.workspace" not in nodes
        with pytest.raises(RuntimeError, match="not available"):
            await research.get_workspace_process_launcher().start(
                ProcessLaunchRequest(
                    command=("never-start",),
                    cwd=str(tmp_path),
                    effective_environment=(),
                ),
                correlation_id="generic-no-workspace",
            )
        assert tuple(node.capability_id for node in effective_runtime.capabilities) == (
            "harness.resources",
            "harness.session",
            "harness.model_input",
        )
        assert effective_runtime.source_publication is not None
        assert effective_runtime.source_publication.owner_capability_id == (
            "harness.resources"
        )
        assert effective_runtime.source_publication.resource_revision == 0
        assert effective_runtime.clocks.model_surface is None
        assert effective_runtime.skew == ()
        assert (
            research.explain_runtime_capability("harness.model_input").clocks.mount
            == effective_runtime.clocks.mount
        )
        assert (
            research.effective_runtime_to_json(effective_runtime)["runtime_id"]
            == effective_runtime.runtime_id
        )
        research._composition.resource_refresh_runtime._commit_resource_bundle(
            ResourceBundle(cwd=tmp_path)
        )
        refreshed_runtime = research.get_effective_runtime_view()
        source_diff = research.diff_effective_runtime(
            effective_runtime,
            refreshed_runtime,
        )
        assert refreshed_runtime.clocks.mount == effective_runtime.clocks.mount
        assert refreshed_runtime.source_publication is not None
        assert refreshed_runtime.source_publication.resource_revision == 1
        assert source_diff.source_publication_changed is True
        assert source_diff.mount_generation_changed is False
        assert source_diff.registration_revision_changed is False
        _assert_no_composed_runtime_mirrors(research)
        _assert_no_composed_runtime_mirrors(design)

        research_result = await research.compact("research-only")

        assert isinstance(research_result, CompactionResult)
        assert research_result.summary == "research summary"
        assert research.executor_calls == [("research", "research-only")]
        assert research.hook_calls[0] == (
            "before",
            "manual",
            "research-only",
        )
        assert research.hook_calls[1][0:2] == (
            "after",
            "research summary",
        )
        assert _checkpoint_summaries(research_transcript) == ["research summary"]
        assert _checkpoint_summaries(design_transcript) == []
        assert design.executor_calls == []
        assert design.hook_calls == []
        assert design_events == []
        _assert_compaction_events(
            research_events,
            product_id="research",
            session_id="research-session",
            reserve_tokens=1_111,
            compact_percent=61.0,
        )

        await research.dispose()

        assert research.footer.disposed is True
        assert research._capability_graph_runtime.is_closed is True
        assert research_capabilities.binding.is_closed is True
        assert design_capabilities.binding.is_closed is False
        assert disposed_transcripts == ["research-session"]
        with pytest.raises(RuntimeError, match="disposed"):
            research.get_effective_runtime_view()
        with pytest.raises(RuntimeError, match="not mounted"):
            research._resource_capability_ports.activation.activate(None)
        assert (
            research.effective_runtime_to_json(effective_runtime)["runtime_id"]
            == effective_runtime.runtime_id
        )
        detached_diff = research.diff_effective_runtime(
            effective_runtime,
            effective_runtime,
        )
        assert detached_diff.profile_changed is False
        assert detached_diff.registration_revision_changed is False

        design_result = await design.compact("design-only")

        assert isinstance(design_result, CompactionResult)
        assert design_result.summary == "design summary"
        assert design.executor_calls == [("design", "design-only")]
        assert design.hook_calls[0] == ("before", "manual", "design-only")
        assert design.hook_calls[1][0:2] == ("after", "design summary")
        assert _checkpoint_summaries(design_transcript) == ["design summary"]
        assert _checkpoint_summaries(research_transcript) == ["research summary"]
        _assert_compaction_events(
            design_events,
            product_id="design",
            session_id="design-session",
            reserve_tokens=2_222,
            compact_percent=72.0,
        )

        await design.dispose()

        assert design.footer.disposed is True
        assert design_capabilities.binding.is_closed is True
        assert disposed_transcripts == ["research-session", "design-session"]

    asyncio.run(scenario())


def test_graph_owned_compaction_views_follow_the_current_profile_selection(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="turn-profile")
        session = _ContractProductSession(
            product_id="turn-profile",
            transcript=transcript,
            capability_runtime=_capability_runtime("turn-profile"),
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        await session.prepare_model_call_runtime()
        mounted_generation = session._capability_graph_runtime.generation
        replacement = create_agent_transcript_compaction_capability(
            implementation="agent_transcript.turn_aware_summary",
            implementation_version=1,
            config={
                "enabled": False,
                "compactPercent": 33.0,
                "reserveTokens": 999,
                "keepRecentTokens": 7,
            },
        )
        object.__setattr__(
            session._staged_transcript_candidate,
            "_get_compaction_capability",
            lambda: replacement,
        )
        settings_manager = session._settings_controller.get_settings_manager()
        assert settings_manager is not None
        settings_manager.update_settings(
            scope="session",
            compaction=CompactionSettings(),
        )

        assert session._composition.compaction_capability is replacement
        assert session._composition.compaction_runtime._get_policy() == (
            replacement.policy
        )
        assert session.auto_compaction_enabled is False
        usage = session._composition.session_inspector.get_context_usage()
        assert usage.reserve_tokens == 999
        assert usage.compact_percent == 33.0
        assert usage.keep_recent_tokens == 7
        assert session._capability_graph_runtime.generation == mounted_generation

        await session.dispose()
        assert disposed_transcripts == ["turn-profile-session"]

    asyncio.run(scenario())


def test_initial_catalog_bootstrap_publishes_one_graph_owned_session_view(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        product_id = "catalog-bootstrap"
        transcript = await _new_transcript(tmp_path, product_id=product_id)
        capability_runtime = _capability_runtime(product_id)
        bootstrap, base_bundle = _initial_catalog_bootstrap(
            tmp_path,
            product_id=product_id,
        )
        extension_runner = ExtensionRunner([])
        session = _ContractProductSession(
            product_id=product_id,
            transcript=transcript,
            capability_runtime=capability_runtime,
            reserve_tokens=1_111,
            compact_percent=61.0,
            resource_bundle=base_bundle,
            extension_runner=extension_runner,
            initial_resource_catalog_bootstrap=bootstrap,
        )

        await session.prepare_model_call_runtime()
        await session.prepare_model_call_runtime()

        assert bootstrap.state == "published"
        assert extension_runner.generation == 2
        assert capability_runtime.ownership_state == "graph_owned"
        assert session._staged_resource_candidate is None
        assert session._resource_catalog_snapshot is not None
        assert session._resource_catalog_projection is not None
        statuses = session.list_skill_statuses()
        assert [(status.name, status.status) for status in statuses] == [
            ("review", "effective")
        ]
        assert session.resource_bundle is not base_bundle
        assert session.resource_bundle is not None
        assert [skill.name for skill in session.resource_bundle.skills] == ["review"]
        source_reference = session._source_publication_reference()
        assert source_reference.extension_generation == 2
        assert source_reference.resource_revision == getattr(
            session._resource_catalog_snapshot,
            "catalog_generation",
        )

        await session.dispose()

        assert capability_runtime.ownership_state == "disposed"
        assert disposed_transcripts == [f"{product_id}-session"]

    asyncio.run(scenario())


def test_product_input_adapter_carries_native_and_embedded_skills_through_session(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        product_id = "catalog-product-inputs"
        session_id = f"{product_id}-session"
        workspace = tmp_path / product_id
        skill_root = workspace / "skills" / "native"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            "---\nname: native\ndescription: Native skill\n---\nUse native.\n",
            encoding="utf-8",
        )
        transcript = await _new_transcript(tmp_path, product_id=product_id)
        capability_runtime = _capability_runtime(product_id)
        base_bundle = ResourceBundle(cwd=workspace)
        extension_runner = ExtensionRunner([])
        adapter = InitialResourceCatalogProductAdapter(
            InitialResourceCatalogProductSelection(
                product_policy_revision="resource-policy-v1",
                native_roots=(
                    ProductNativeResourceRootSpec(
                        handle_id="project-resources",
                        root=workspace,
                        source_class="project_local",
                        root_kind="standard",
                    ),
                ),
                embedded_collections=(
                    ProductEmbeddedResourceCollectionSpec(
                        collection_id="coding-builtin-resources",
                        embedded_revision="v1",
                        files={
                            "skills/embedded/SKILL.md": (
                                b"---\nname: embedded\ndescription: Embedded skill\n"
                                b"---\nUse embedded.\n"
                            )
                        },
                    ),
                ),
            ),
            clock=lambda: 10,
        )

        session = adapter.construct_session(
            product_id=product_id,
            session_id=session_id,
            base_resource_bundle=base_bundle,
            construct=lambda bootstrap: _ContractProductSession(
                product_id=product_id,
                transcript=transcript,
                capability_runtime=capability_runtime,
                reserve_tokens=1_111,
                compact_percent=61.0,
                resource_bundle=base_bundle,
                extension_runner=extension_runner,
                initial_resource_catalog_bootstrap=bootstrap,
            ),
        )

        await session.prepare_model_call_runtime()

        assert session.resource_bundle is not None
        assert {skill.name for skill in session.resource_bundle.skills} == {
            "embedded",
            "native",
        }
        assert capability_runtime.ownership_state == "graph_owned"

        await session.dispose()
        assert capability_runtime.ownership_state == "disposed"
        assert disposed_transcripts == [session_id]

    asyncio.run(scenario())


def test_failed_graph_bind_rolls_back_initial_catalog_and_extension_candidates(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        product_id = "catalog-bind-failure"
        transcript = await _new_transcript(tmp_path, product_id=product_id)
        capability_runtime = _capability_runtime(product_id)
        bootstrap, base_bundle = _initial_catalog_bootstrap(
            tmp_path,
            product_id=product_id,
        )
        extension_runner = ExtensionRunner([])
        session = _ContractProductSession(
            product_id=product_id,
            transcript=transcript,
            capability_runtime=capability_runtime,
            reserve_tokens=1_111,
            compact_percent=61.0,
            resource_bundle=base_bundle,
            extension_runner=extension_runner,
            initial_resource_catalog_bootstrap=bootstrap,
        )

        async def fail_bind(*_args: object) -> None:
            raise RuntimeError("catalog graph preparation failed")

        session._capability_graph_binder.bind = fail_bind  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="catalog graph preparation failed"):
            await session.prepare_model_call_runtime()

        assert bootstrap.state == "disposed"
        assert extension_runner.generation == 1
        assert capability_runtime.ownership_state == "disposed"
        assert session._capability_graph_runtime.snapshot is None
        assert session.resource_bundle is base_bundle

        await session.dispose()
        assert disposed_transcripts == [f"{product_id}-session"]

    asyncio.run(scenario())


def test_failed_initial_catalog_publication_restores_session_view_and_rolls_back(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        product_id = "catalog-publish-failure"
        transcript = await _new_transcript(tmp_path, product_id=product_id)
        capability_runtime = _capability_runtime(product_id)
        bootstrap, base_bundle = _initial_catalog_bootstrap(
            tmp_path,
            product_id=product_id,
        )
        extension_runner = ExtensionRunner([])
        session = _ContractProductSession(
            product_id=product_id,
            transcript=transcript,
            capability_runtime=capability_runtime,
            reserve_tokens=1_111,
            compact_percent=61.0,
            resource_bundle=base_bundle,
            extension_runner=extension_runner,
            initial_resource_catalog_bootstrap=bootstrap,
        )
        original_commit = session._commit_initial_resource_publication

        def fail_after_commit(
            catalog: object,
            projection: object,
            bundle: ResourceBundle,
        ) -> None:
            original_commit(catalog, projection, bundle)
            raise RuntimeError("catalog publication failed")

        session._commit_initial_resource_publication = fail_after_commit  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="catalog publication failed"):
            await session.prepare_model_call_runtime()

        assert bootstrap.state == "disposed"
        assert extension_runner.generation == 1
        assert capability_runtime.ownership_state == "disposed"
        assert session.resource_bundle is base_bundle
        assert session._resource_catalog_snapshot is None
        assert session._resource_catalog_projection is None

        await session.dispose()
        assert disposed_transcripts == [f"{product_id}-session"]

    asyncio.run(scenario())


def test_cancelled_initial_catalog_bootstrap_finishes_graph_and_joint_rollback(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        product_id = "catalog-cancelled"
        transcript = await _new_transcript(tmp_path, product_id=product_id)
        capability_runtime = _capability_runtime(product_id)
        bootstrap, base_bundle = _initial_catalog_bootstrap(
            tmp_path,
            product_id=product_id,
        )
        extension_runner = ExtensionRunner([])
        session = _ContractProductSession(
            product_id=product_id,
            transcript=transcript,
            capability_runtime=capability_runtime,
            reserve_tokens=1_111,
            compact_percent=61.0,
            resource_bundle=base_bundle,
            extension_runner=extension_runner,
            initial_resource_catalog_bootstrap=bootstrap,
        )
        graph_bound = asyncio.Event()
        never_release = asyncio.Event()
        original_bind = session._capability_graph_binder.bind

        async def pause_after_bind(runtime, plan, bindings):  # type: ignore[no-untyped-def]
            result = await original_bind(runtime, plan, bindings)
            graph_bound.set()
            await never_release.wait()
            return result

        session._capability_graph_binder.bind = pause_after_bind  # type: ignore[method-assign]
        preparation = asyncio.create_task(session.prepare_model_call_runtime())
        await asyncio.wait_for(graph_bound.wait(), timeout=1)
        preparation.cancel()

        with pytest.raises(asyncio.CancelledError):
            await preparation

        assert bootstrap.state == "disposed"
        assert extension_runner.generation == 1
        assert capability_runtime.ownership_state == "disposed"
        assert session._capability_graph_runtime.is_closed is True

        await session.dispose()
        assert disposed_transcripts == [f"{product_id}-session"]

    asyncio.run(scenario())


def test_unprepared_catalog_bootstrap_releases_owned_source_inputs_on_shutdown(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        product_id = "catalog-unprepared"
        transcript = await _new_transcript(tmp_path, product_id=product_id)
        embedded = mint_embedded_resource_collection_handle(
            collection_id="catalog-unprepared-oem",
            embedded_revision="v1",
            files={},
        )
        bootstrap, base_bundle = _initial_catalog_bootstrap(
            tmp_path,
            product_id=product_id,
            embedded_collections=(embedded,),
        )
        session = _ContractProductSession(
            product_id=product_id,
            transcript=transcript,
            capability_runtime=_capability_runtime(product_id),
            reserve_tokens=1_111,
            compact_percent=61.0,
            resource_bundle=base_bundle,
            extension_runner=ExtensionRunner([]),
            initial_resource_catalog_bootstrap=bootstrap,
        )

        await session.dispose()

        assert bootstrap.state == "disposed"
        assert embedded.closed is True
        assert disposed_transcripts == [f"{product_id}-session"]

    asyncio.run(scenario())


def test_failed_graph_preparation_is_disposed_without_leaving_agent_boundary(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="bind-failure")
        capability_runtime = _capability_runtime("bind-failure")
        session = _ContractProductSession(
            product_id="bind-failure",
            transcript=transcript,
            capability_runtime=capability_runtime,
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        side_candidate = session._staged_side_question_candidate
        assert side_candidate is not None
        side_disposal_calls = 0
        original_side_dispose = side_candidate.dispose

        def count_side_dispose() -> None:
            nonlocal side_disposal_calls
            side_disposal_calls += 1
            original_side_dispose()

        side_candidate.dispose = count_side_dispose  # type: ignore[method-assign]

        async def fail_bind(*_args: object) -> None:
            raise RuntimeError("graph preparation failed")

        session._capability_graph_binder.bind = fail_bind  # type: ignore[method-assign]

        previous = object()
        host = SessionTransitionHost(
            previous,
            dispose=lambda _session: None,
        )
        coordinator = SessionOperationCoordinator(host)

        with pytest.raises(RuntimeError, match="graph preparation failed"):
            await coordinator.run(
                lambda _current: SessionOperationCandidate(
                    session,
                    None,
                    rollback=session.dispose,
                ),
                prepare_session=lambda candidate, _previous: (
                    candidate.session.prepare_model_call_runtime()
                ),
            )

        assert host.current is previous
        assert session._capability_graph_runtime.snapshot is None
        assert session.agent.prepare_model_call is None
        assert session._capability_graph_runtime.is_closed is True
        assert side_disposal_calls == 1
        assert side_candidate.ownership_state == "disposed"
        assert session._staged_side_question_candidate is None
        assert disposed_transcripts == ["bind-failure-session"]

    asyncio.run(scenario())


def test_failed_graph_preparation_retains_root_candidate_for_shutdown_retry(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="bind-cleanup-retry")
        capability_runtime = _capability_runtime("bind-cleanup-retry")
        session = _ContractProductSession(
            product_id="bind-cleanup-retry",
            transcript=transcript,
            capability_runtime=capability_runtime,
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        original_dispose = capability_runtime.dispose
        disposal_attempts = 0

        def fail_first_disposal() -> None:
            nonlocal disposal_attempts
            disposal_attempts += 1
            if disposal_attempts == 1:
                raise RuntimeError("transient candidate cleanup failure")
            original_dispose()

        capability_runtime.dispose = fail_first_disposal  # type: ignore[method-assign]

        async def fail_bind(*_args: object) -> None:
            raise RuntimeError("graph preparation failed")

        session._capability_graph_binder.bind = fail_bind  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="graph preparation failed") as caught:
            await session.prepare_model_call_runtime()

        assert "transient candidate cleanup failure" in "\n".join(
            caught.value.__notes__
        )
        assert session._staged_resource_candidate is capability_runtime
        assert capability_runtime.ownership_state == "root_owned"

        await session.dispose()

        assert disposal_attempts == 2
        assert capability_runtime.ownership_state == "disposed"
        assert disposed_transcripts == ["bind-cleanup-retry-session"]

    asyncio.run(scenario())


def test_unprepared_shutdown_retains_root_candidate_for_cleanup_retry(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="shutdown-retry")
        capability_runtime = _capability_runtime("shutdown-retry")
        session = _ContractProductSession(
            product_id="shutdown-retry",
            transcript=transcript,
            capability_runtime=capability_runtime,
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        original_dispose = capability_runtime.dispose
        disposal_attempts = 0

        def fail_first_disposal() -> None:
            nonlocal disposal_attempts
            disposal_attempts += 1
            if disposal_attempts == 1:
                raise RuntimeError("transient root cleanup failure")
            original_dispose()

        capability_runtime.dispose = fail_first_disposal  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="transient root cleanup failure"):
            await session.dispose()

        assert disposal_attempts == 1
        assert session._staged_resource_candidate is capability_runtime
        assert capability_runtime.ownership_state == "root_owned"

        await session.dispose()

        assert disposal_attempts == 2
        assert session._staged_resource_candidate is None
        assert capability_runtime.ownership_state == "disposed"
        assert disposed_transcripts == ["shutdown-retry-session"]

    asyncio.run(scenario())


def test_unprepared_shutdown_retries_the_side_question_candidate(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="side-shutdown-retry")
        session = _ContractProductSession(
            product_id="side-shutdown-retry",
            transcript=transcript,
            capability_runtime=_capability_runtime("side-shutdown-retry"),
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        candidate = session._staged_side_question_candidate
        assert candidate is not None
        original_dispose = candidate.dispose
        disposal_attempts = 0

        def fail_first_disposal() -> None:
            nonlocal disposal_attempts
            disposal_attempts += 1
            if disposal_attempts == 1:
                raise RuntimeError("transient side-question cleanup failure")
            original_dispose()

        candidate.dispose = fail_first_disposal  # type: ignore[method-assign]

        with pytest.raises(
            RuntimeError,
            match="transient side-question cleanup failure",
        ):
            await session.dispose()

        assert disposal_attempts == 1
        assert session._staged_side_question_candidate is candidate
        assert candidate.ownership_state == "root_owned"

        await session.dispose()

        assert disposal_attempts == 2
        assert session._staged_side_question_candidate is None
        assert candidate.ownership_state == "disposed"
        assert disposed_transcripts == ["side-shutdown-retry-session"]

    asyncio.run(scenario())


def test_graph_owned_transcript_release_retries_after_index_publication(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        events: list[str] = []
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(
            disposed_transcripts,
            release_events=events,
            fail_release_once=True,
        )
        transcript = await _new_transcript(tmp_path, product_id="transcript-retry")
        original_publish_index = transcript.publish_index_summary

        async def publish_index() -> None:
            events.append("index")
            await original_publish_index()

        transcript.publish_index_summary = publish_index  # type: ignore[method-assign]
        session = _ContractProductSession(
            product_id="transcript-retry",
            transcript=transcript,
            capability_runtime=_capability_runtime("transcript-retry"),
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        await session.prepare_model_call_runtime()

        with pytest.raises(RuntimeError, match="cleanup remains pending"):
            await session.dispose()

        assert events == ["index", "release"]
        assert transcript._lifecycle_session.ownership_state == "graph_owned"
        assert session._capability_graph_runtime.has_pending_retirements is True
        assert disposed_transcripts == []

        await session.dispose()

        assert events == ["index", "release", "index", "release"]
        assert transcript._lifecycle_session.ownership_state == "disposed"
        assert session._capability_graph_runtime.has_pending_retirements is False
        assert disposed_transcripts == ["transcript-retry-session"]

    asyncio.run(scenario())


def test_prepare_fails_closed_without_touching_graph_when_owner_cleanup_is_pending(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="cleanup-debt")
        session = _ContractProductSession(
            product_id="cleanup-debt",
            transcript=transcript,
            capability_runtime=_capability_runtime("cleanup-debt"),
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        await session.prepare_model_call_runtime()
        consumer = session._model_call_consumer
        assert consumer is not None
        session._model_call_consumer = None
        session._capability_owner_generations = (object(),)  # type: ignore[assignment]

        async def unexpected_bind(*_args: object) -> None:
            raise AssertionError("pending cleanup must not start another bind")

        session._capability_graph_binder.bind = unexpected_bind  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="cleanup is pending"):
            await session.prepare_model_call_runtime()

        assert session._capability_graph_runtime.is_closed is False
        assert session._capability_graph_runtime.snapshot is not None
        session._capability_owner_generations = ()
        session._model_call_consumer = consumer
        await session.dispose()
        assert disposed_transcripts == ["cleanup-debt-session"]

    asyncio.run(scenario())


def test_owner_cleanup_failure_invalidates_public_capability_ports(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="owner-port-close")
        session = _ContractProductSession(
            product_id="owner-port-close",
            transcript=transcript,
            capability_runtime=_capability_runtime("owner-port-close"),
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        await session.prepare_model_call_runtime()

        class _RetryableGeneration:
            disposed = False
            attempts = 0

            async def dispose_once(self) -> None:
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("synthetic owner cleanup failure")
                self.disposed = True

        generation = _RetryableGeneration()
        session._capability_owner_generations = (generation,)  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="synthetic owner cleanup failure"):
            await session.dispose()

        with pytest.raises(RuntimeError, match="ports are disposed"):
            await session.get_workspace_process_launcher().start(
                ProcessLaunchRequest(
                    command=("synthetic",),
                    cwd=str(tmp_path),
                    effective_environment=(),
                ),
                correlation_id="owner-port-close",
            )

        await session.dispose()
        assert generation.disposed is True
        assert disposed_transcripts == ["owner-port-close-session"]

    asyncio.run(scenario())


def test_source_publication_does_not_mix_partial_extension_provenance(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="source-domain")
        session = _ContractProductSession(
            product_id="source-domain",
            transcript=transcript,
            capability_runtime=_capability_runtime("source-domain"),
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        session._extension_runner = SimpleNamespace(generation=7)

        reference = session._source_publication_reference()

        assert reference.source_runtime_id == (
            session._capability_graph_runtime.runtime_id
        )
        assert reference.extension_generation is None
        assert reference.declaration_revision is None

        await session.dispose()
        assert disposed_transcripts == ["source-domain-session"]

    asyncio.run(scenario())


def test_product_model_input_reads_profile_after_turn_boundary_refresh(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="profile-refresh")
        capability_runtime = _capability_runtime("profile-refresh")
        session = _ContractProductSession(
            product_id="profile-refresh",
            transcript=transcript,
            capability_runtime=capability_runtime,
            reserve_tokens=1_111,
            compact_percent=61.0,
        )
        await session.prepare_model_call_runtime()
        mount_profile_fingerprint = (
            session._capability_graph_runtime.profile_fingerprint
        )

        profile = capability_runtime.binding.profile
        capabilities = list(profile.capabilities)
        prompt_index = next(
            index
            for index, capability in enumerate(capabilities)
            if capability.slot.key == "prompt.sections"
        )
        prompt = capabilities[prompt_index]
        selected = prompt.selections[0]
        changed_selection = replace(
            selected.selection,
            config={**selected.selection.config, "separator": "\n---\n"},
        )
        capabilities[prompt_index] = replace(
            prompt,
            selections=(replace(selected, selection=changed_selection),),
        )
        await capability_runtime._binder.rebind(
            capability_runtime.binding,
            replace(profile, capabilities=tuple(capabilities)),
        )
        current_profile_fingerprint = session._current_profile_fingerprint()
        assert current_profile_fingerprint != mount_profile_fingerprint

        options = await session._model_call_runtime.prepare(
            ModelCallPreparation(
                purpose="main",
                sequence=1,
                model=session.agent.model,
                context=Context(system_prompt="profile refresh", messages=[]),
                options=CallOptions(),
            )
        )
        committer = options.prepared_request_committer
        assert committer is not None
        await committer.commit_prepared_request(
            PreparedModelRequest(
                invocation_id="profile-refresh-invocation",
                attempt=1,
                provider_id="test",
                endpoint_id="test-endpoint",
                api="test",
                model_id="profile-refresh-model",
                mode="stream",
                payload={"messages": []},
            )
        )
        snapshot = next(
            entry.payload
            for entry in transcript.get_entries()
            if entry.kind == "model.input.prepared"
        )

        assert snapshot.profile_fingerprint == current_profile_fingerprint
        assert snapshot.profile_fingerprint != mount_profile_fingerprint
        assert transcript.rebuild_model_input(snapshot.snapshot_id).snapshot == snapshot

        await session.dispose()
        assert disposed_transcripts == ["profile-refresh-session"]

    asyncio.run(scenario())


def test_agent_product_finalizes_shutdown_when_capability_disposal_fails(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        transcript = await _new_transcript(tmp_path, product_id="failure")
        capability_runtime = _capability_runtime("failure")
        session = _ContractProductSession(
            product_id="failure",
            transcript=transcript,
            capability_runtime=capability_runtime,
            reserve_tokens=1_111,
            compact_percent=61.0,
        )

        def fail_capability_disposal() -> None:
            raise RuntimeError("capability disposal failed")

        capability_runtime.dispose = fail_capability_disposal  # type: ignore[method-assign]

        try:
            await session.dispose()
        except RuntimeError as error:
            assert str(error) == "capability disposal failed"
        else:  # pragma: no cover - the injected failure must propagate
            raise AssertionError("capability disposal failure did not propagate")

        assert session.footer.disposed is True
        assert disposed_transcripts == ["failure-session"]

    asyncio.run(scenario())


def test_workspace_provider_cleanup_remains_owned_until_retry_succeeds(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        release_events: list[str] = []
        _bind_transcript_factory(
            disposed_transcripts,
            release_events=release_events,
        )
        transcript = await _new_transcript(tmp_path, product_id="workspace-cleanup")
        original_publish_index = transcript.publish_index_summary

        async def publish_index() -> None:
            release_events.append("index")
            await original_publish_index()

        transcript.publish_index_summary = publish_index  # type: ignore[method-assign]
        cleanup_attempts = 0

        async def cleanup() -> None:
            nonlocal cleanup_attempts
            cleanup_attempts += 1
            release_events.append("workspace")
            if cleanup_attempts == 1:
                raise RuntimeError("transient workspace cleanup failure")

        workspace_binding = workspace_capability_provider_binding(
            operations=LocalToolOperations(),
            process_launcher=_UnusedWorkspaceLauncher(),
            scope_instance_id=f"workspace:{tmp_path}",
            binding_input_fingerprint=hashlib.sha256(b"workspace-cleanup").hexdigest(),
            cleanup=cleanup,
            source_id="contract-test",
        )
        session = _ContractProductSession(
            product_id="workspace-cleanup",
            transcript=transcript,
            capability_runtime=_capability_runtime("workspace-cleanup"),
            reserve_tokens=1_111,
            compact_percent=61.0,
            workspace_capability_binding=workspace_binding,
        )
        await session.prepare_model_call_runtime()
        cached_launcher = session.get_workspace_process_launcher()

        with pytest.raises(RuntimeError, match="cleanup remains pending"):
            await session.dispose()

        assert cleanup_attempts == 1
        assert release_events == ["index", "release", "workspace"]
        assert session._capability_graph_runtime.has_pending_retirements is True
        with pytest.raises(RuntimeError, match="disposed"):
            await cached_launcher.start(
                ProcessLaunchRequest(
                    command=("never-start",),
                    cwd=str(tmp_path),
                    effective_environment=(),
                ),
                correlation_id="disposed-workspace",
            )

        await session.dispose()

        assert cleanup_attempts == 2
        assert release_events == ["index", "release", "workspace", "workspace"]
        assert session._capability_graph_runtime.has_pending_retirements is False
        assert disposed_transcripts == ["workspace-cleanup-session"]

    asyncio.run(scenario())


def test_workspace_signature_flows_through_session_into_model_input(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)

        async def mounted_signatures(marker: str) -> dict[str, str]:
            transcript = await _new_transcript(
                tmp_path,
                product_id="workspace-signature",
            )
            workspace_binding = workspace_capability_provider_binding(
                operations=LocalToolOperations(),
                process_launcher=_UnusedWorkspaceLauncher(),
                scope_instance_id=f"workspace:{tmp_path}",
                binding_input_fingerprint=hashlib.sha256(marker.encode()).hexdigest(),
            )
            session = _ContractProductSession(
                product_id="workspace-signature",
                transcript=transcript,
                capability_runtime=_capability_runtime("workspace-signature"),
                reserve_tokens=1_111,
                compact_percent=61.0,
                workspace_capability_binding=workspace_binding,
            )
            await session.prepare_model_call_runtime()
            snapshot = session._capability_graph_runtime.snapshot
            assert snapshot is not None
            signatures = {
                node.capability_id: node.binding_signature for node in snapshot.nodes
            }
            await session.dispose()
            return signatures

        first = await mounted_signatures("workspace-one")
        second = await mounted_signatures("workspace-two")

        assert first["harness.resources"] == second["harness.resources"]
        assert first["harness.workspace"] != second["harness.workspace"]
        assert first["harness.session"] != second["harness.session"]
        assert first["harness.model_input"] != second["harness.model_input"]

    asyncio.run(scenario())


def test_foundation_plugin_reaches_one_session_graph_and_reverse_owner_unload(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed_transcripts: list[str] = []
        _bind_transcript_factory(disposed_transcripts)
        events = tmp_path / "foundation-events.log"
        fixture = _publish_foundation_plugin(tmp_path, events=events)
        try:
            selection = _foundation_selection(fixture)
            assert events.exists() is False
            definition = CapabilityDefinition(
                capability_id="coding.foundation",
                owner_id="coding",
                contract_version=1,
                facets=("query",),
                scope="session",
                refresh_boundary="sealed",
                phase="final",
            )
            provider_authority = _foundation_provider_authority(
                definition,
                "org.loushang.coding.foundation/default",
            )
            owner_authority = _foundation_tool_owner_authority()
            [trust_snapshot] = selection.plan.source_trust_snapshots
            workspace_binding = workspace_capability_provider_binding(
                operations=LocalToolOperations(),
                process_launcher=_UnusedWorkspaceLauncher(),
                scope_instance_id="workspace:test",
                binding_input_fingerprint=hashlib.sha256(
                    b"foundation-workspace"
                ).hexdigest(),
                source_id="foundation-contract-test",
            )
            assembly_request = _foundation_assembly_request(
                selection=selection,
                definition=definition,
                provider_authority=provider_authority,
                owner_authority=owner_authority,
                workspace_binding=workspace_binding,
            )
            with pytest.raises(ValueError, match="roots do not match Consumer roots"):
                assemble_product_plugin_composition(
                    replace(
                        assembly_request,
                        host_capability_ids=(
                            WORKSPACE_CAPABILITY_DEFINITION.capability_id,
                        ),
                    ),
                    evaluated_at=150,
                )
            with pytest.raises(ProductCompositionAssemblyError) as missing_definition:
                assemble_product_plugin_composition(
                    replace(
                        assembly_request,
                        contribution_request=replace(
                            assembly_request.contribution_request,
                            definitions=(
                                MODEL_INPUT_CAPABILITY_DEFINITION,
                                WORKSPACE_CAPABILITY_DEFINITION,
                            ),
                        ),
                    ),
                    evaluated_at=150,
                )
            assert (
                missing_definition.value.code == "product_provider_definition_missing"
            )
            assert missing_definition.value.capability_ids == (
                definition.capability_id,
            )
            with pytest.raises(ProductCompositionAssemblyError) as missing_owner:
                assemble_product_plugin_composition(
                    replace(assembly_request, provider_owner_bindings=()),
                    evaluated_at=150,
                )
            assert missing_owner.value.code == "product_provider_owner_missing"
            assert missing_owner.value.capability_ids == (definition.capability_id,)
            unused_provider_authority = CapabilityProviderOwnerAuthority(
                CapabilityProviderOwnerPolicy(
                    capability_id="coding.unused",
                    owner_id="coding",
                    policy_revision="coding-unused-owner-1",
                    revocation_epoch=0,
                    allowed_provider_ids=("org.loushang.coding.unused/default",),
                    allowed_source_trust_classes=("host-equivalent-local",),
                    authority_ceiling=(),
                )
            )
            with pytest.raises(ProductCompositionAssemblyError) as extra_owner:
                assemble_product_plugin_composition(
                    replace(
                        assembly_request,
                        provider_owner_bindings=(
                            *assembly_request.provider_owner_bindings,
                            ProductCapabilityProviderOwnerBinding(
                                authority=unused_provider_authority,
                            ),
                        ),
                    ),
                    evaluated_at=150,
                )
            assert extra_owner.value.code == "product_provider_owner_extra"
            assert extra_owner.value.capability_ids == ("coding.unused",)
            assembly = assemble_product_plugin_composition(
                assembly_request,
                evaluated_at=150,
            )
            [owner_admission] = assembly.product_composition.catalog_admissions
            [resolved_provider] = assembly.resolved_providers.entries
            provider_admission = resolved_provider.admission
            provider_plan = ProductCapabilityProviderSelectionPlanV1(
                product_id="coding",
                roots=assembly.resolved_providers.roots,
                choices=(resolved_provider.choice,),
                policy_revision="coding-plugin-policy-1",
            )
            identities = iter(("1" * 48, "2" * 48))
            activation_journal = PluginActivationDecisionJournal(
                tmp_path / "foundation-activation.jsonl",
                scope_id="workspace:test",
                identity_factory=lambda: next(identities),
                clock=lambda: 150,
            )
            component_host = CapabilityComponentHost(
                decision_journal=activation_journal,
                import_realm=PluginImportRealm(
                    import_realm_id_factory=lambda: "4" * 32
                ),
                host_boot_id="3" * 32,
                clock=lambda: 150,
                owner_snapshot_reader=(
                    lambda _capability_id: provider_authority.snapshot()
                ),
                trust_snapshot_reader=(
                    lambda _plugin_id, _source_identity: trust_snapshot
                ),
                product_policy_revision_reader=(
                    lambda _product_id, _scope_id: "coding-plugin-policy-1"
                ),
            )
            [component_candidate] = assembly.component_candidates
            subject = component_host.activation_subject(
                resolved_provider,
                owner_snapshot=component_candidate.owner_snapshot,
                trust_snapshot=component_candidate.trust_snapshot,
            )
            decision = activation_journal.issue_activation_decision(
                subject,
                disposition="approved",
                authorization=PluginApprovalAuthorizationV1.direct(
                    actor_id="operator:test",
                    source="foundation-session-test",
                ),
                issued_at_unix_ms=140,
                expires_at_unix_ms=300,
                expected_journal_revision=0,
            )
            with pytest.raises(ProductCompositionAssemblyError) as missing_activation:
                assembly.bind_session_inputs({})
            assert (
                missing_activation.value.code == "product_provider_activation_missing"
            )
            assert missing_activation.value.capability_ids == (
                definition.capability_id,
            )
            with pytest.raises(ProductCompositionAssemblyError) as extra_activation:
                assembly.bind_session_inputs(
                    {
                        definition.capability_id: decision.decision_id,
                        "coding.unused": "9" * 48,
                    }
                )
            assert extra_activation.value.code == "product_provider_activation_extra"
            assert extra_activation.value.capability_ids == ("coding.unused",)
            composition_inputs = assembly.bind_session_inputs(
                {definition.capability_id: decision.decision_id}
            )
            [component_request] = composition_inputs.component_requests
            compilation = composition_inputs.product_composition
            reevaluated_providers = ProductCapabilityProviderResolver().resolve(
                provider_plan,
                definitions=(definition, WORKSPACE_CAPABILITY_DEFINITION),
                admissions=(provider_admission,),
                owner_snapshots=(provider_authority.snapshot(),),
                evaluated_at=151,
                prebound_providers=(workspace_binding.provider,),
            )
            reevaluated_inputs = SessionCapabilityCompositionInputs(
                product_composition=replace(
                    compilation,
                    authority_context=replace(
                        compilation.authority_context,
                        evaluated_at=151,
                    ),
                ),
                resolved_providers=reevaluated_providers,
                component_requests=(
                    replace(
                        component_request,
                        resolved=reevaluated_providers.entries[0],
                    ),
                ),
            )
            assert composition_inputs.compare(reevaluated_inputs) == "no_change"

            async def stage_tools(
                captures: tuple[SessionCapabilityConsumerCapture, ...],
            ) -> object:
                [capture] = captures
                assert (
                    capture.entry.admission_fingerprint == owner_admission.fingerprint
                )
                assert capture.facets.require("query") == {
                    "label": "foundation",
                    "runtime_id": "session:coding-session",
                    "workspace_read": True,
                }
                _append_event(events, "tool-stage")
                return {"generation": 1}

            async def dispose_tools(value: object) -> None:
                assert value == {"generation": 1}
                _append_event(events, "tool-dispose")

            owner_binding = SessionCapabilityOwnerGenerationBinding(
                owner_id=owner_admission.owner_id,
                contribution_kind=owner_admission.contribution_kind,
                plugin_id=owner_admission.plugin_id,
                contribution_id=owner_admission.contribution_id,
                admission_fingerprint=owner_admission.fingerprint,
                authority_gate=SessionCapabilityOwnerAuthorityGate(
                    authority_context=compilation.authority_context,
                    owner_snapshot_reader=(
                        lambda _owner, _kind, _product: owner_authority.snapshot()
                    ),
                    trust_snapshot_reader=(lambda _plugin, _source: trust_snapshot),
                    product_policy_revision_reader=(
                        lambda _product, _scope: "coding-plugin-policy-1"
                    ),
                    clock=lambda: 150,
                ),
                stage=stage_tools,
                dispose=dispose_tools,
            )
            transcript = await _new_transcript(tmp_path, product_id="coding")
            session = _ContractProductSession(
                product_id="coding",
                transcript=transcript,
                capability_runtime=_capability_runtime("coding"),
                reserve_tokens=1_111,
                compact_percent=61.0,
                workspace_capability_binding=workspace_binding,
                capability_composition_inputs=composition_inputs,
                capability_component_host=component_host,
                capability_owner_generation_bindings=(owner_binding,),
            )

            assert events.exists() is False
            assert activation_journal.snapshot().activation_uses == ()
            await session.prepare_model_call_runtime()

            snapshot = session._capability_graph_runtime.snapshot
            assert snapshot is not None
            assert "coding.foundation" in {
                item.capability_id for item in snapshot.nodes
            }
            assert activation_journal.snapshot().activation_uses[0].state == (
                "COMMITTED"
            )
            assert events.read_text(encoding="utf-8").splitlines() == [
                "provider-import",
                "provider-create",
                "tool-stage",
            ]
            assert (
                session.evaluate_capability_composition_change(
                    replace(
                        composition_inputs,
                        component_requests=(
                            replace(
                                component_request,
                                activation_decision_id="9" * 48,
                            ),
                        ),
                    )
                )
                == "no_change"
            )
            assert (
                session.evaluate_capability_composition_change(
                    replace(
                        composition_inputs,
                        component_requests=(
                            replace(
                                component_request,
                                trust_snapshot=replace(
                                    trust_snapshot,
                                    trusted=False,
                                ),
                            ),
                        ),
                    )
                )
                == "restart_required"
            )
            assert session.evaluate_capability_composition_change(None) == (
                "restart_required"
            )

            await session.dispose()

            assert events.read_text(encoding="utf-8").splitlines() == [
                "provider-import",
                "provider-create",
                "tool-stage",
                "tool-dispose",
                "provider-dispose",
            ]
            assert disposed_transcripts == ["coding-session"]
        finally:
            fixture.runtime.close()

    asyncio.run(scenario())


def test_product_plugin_assembly_rejects_consumer_provider_facet_mismatch(
    tmp_path: Path,
) -> None:
    events = tmp_path / "mismatch-events.log"
    fixture = _publish_foundation_plugin(
        tmp_path,
        events=events,
        plugin_id="foundation-mismatch",
        provider_id="org.loushang.coding.foundation/mismatch",
        provider_facets=("runtime",),
        consumer_facets=("query",),
    )
    try:
        definition = CapabilityDefinition(
            capability_id="coding.foundation",
            owner_id="coding",
            contract_version=1,
            facets=("query", "runtime"),
            scope="session",
            refresh_boundary="sealed",
            phase="final",
        )
        workspace_binding = workspace_capability_provider_binding(
            operations=LocalToolOperations(),
            process_launcher=_UnusedWorkspaceLauncher(),
            scope_instance_id="workspace:test",
            binding_input_fingerprint=hashlib.sha256(
                b"foundation-mismatch-workspace"
            ).hexdigest(),
            source_id="foundation-mismatch-test",
        )
        request = _foundation_assembly_request(
            selection=_foundation_selection(fixture),
            definition=definition,
            provider_authority=_foundation_provider_authority(
                definition,
                fixture.provider_id,
            ),
            owner_authority=_foundation_tool_owner_authority(),
            workspace_binding=workspace_binding,
        )

        with pytest.raises(ProductCompositionError) as mismatch:
            assemble_product_plugin_composition(request, evaluated_at=150)

        assert mismatch.value.code == "consumer_selected_provider_facet_mismatch"
        assert events.exists() is False
    finally:
        fixture.runtime.close()


def test_product_plugin_assembly_retains_the_selected_alternative_provider_facts(
    tmp_path: Path,
) -> None:
    primary_events = tmp_path / "primary-events.log"
    alternative_events = tmp_path / "alternative-events.log"
    primary = _publish_foundation_plugin(
        tmp_path,
        events=primary_events,
        plugin_id="foundation-primary",
        provider_id="org.loushang.coding.foundation/primary",
        label="primary",
    )
    alternative = _publish_foundation_plugin(
        tmp_path,
        events=alternative_events,
        plugin_id="foundation-alternative",
        provider_id="org.loushang.coding.foundation/alternative",
        include_tool_pack=False,
        label="alternative",
    )
    try:
        definition = CapabilityDefinition(
            capability_id="coding.foundation",
            owner_id="coding",
            contract_version=1,
            facets=("query",),
            scope="session",
            refresh_boundary="sealed",
            phase="final",
        )
        workspace_binding = workspace_capability_provider_binding(
            operations=LocalToolOperations(),
            process_launcher=_UnusedWorkspaceLauncher(),
            scope_instance_id="workspace:test",
            binding_input_fingerprint=hashlib.sha256(
                b"foundation-alternative-workspace"
            ).hexdigest(),
            source_id="foundation-alternative-test",
        )
        request = _foundation_assembly_request(
            selection=_foundation_selection(primary, alternative),
            definition=definition,
            provider_authority=_foundation_provider_authority(
                definition,
                primary.provider_id,
                alternative.provider_id,
            ),
            owner_authority=_foundation_tool_owner_authority(),
            workspace_binding=workspace_binding,
            selected_provider_id=alternative.provider_id,
        )

        assembly = assemble_product_plugin_composition(request, evaluated_at=150)

        [resolved] = assembly.resolved_providers.entries
        [component] = assembly.component_candidates
        assert resolved.provider.provider_id == alternative.provider_id
        assert component.resolved is resolved
        assert component.package is alternative.package
        assert (
            component.owner_snapshot
            == request.provider_owner_bindings[0].authority.snapshot()
        )
        assert component.trust_snapshot.plugin_id == alternative.package.manifest.name
        assert primary_events.exists() is False
        assert alternative_events.exists() is False
    finally:
        alternative.runtime.close()
        primary.runtime.close()


@dataclass(frozen=True, slots=True)
class _FoundationPluginFixture:
    runtime: PluginRuntimeResolution
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contributions: tuple[PluginContributionReservation, ...]
    label: str
    provider_id: str


def _publish_foundation_plugin(
    tmp_path: Path,
    *,
    events: Path,
    plugin_id: str = "foundation-sample",
    provider_id: str = "org.loushang.coding.foundation/default",
    provider_facets: tuple[str, ...] = ("query",),
    consumer_facets: tuple[str, ...] = ("query",),
    include_tool_pack: bool = True,
    label: str = "foundation",
) -> _FoundationPluginFixture:
    source_root = tmp_path / plugin_id
    declarations_root = source_root / "declarations"
    declarations_root.mkdir(parents=True)
    source = PluginDeclarationSource.document("declarations/foundation.json")
    contribution_values = [
        PluginContributionReservation(
            contribution_id="foundation-provider",
            kind="capability_provider",
            owner="coding.foundation",
            declaration_source=source,
            contribution_execution_model="in_process",
            requested_authorities=(),
        ),
    ]
    if include_tool_pack:
        contribution_values.append(
            PluginContributionReservation(
                contribution_id="foundation-tools",
                kind="tool_pack",
                owner="coding.tools",
                declaration_source=source,
                contribution_execution_model="data_only",
                requested_authorities=(),
            )
        )
    contributions = tuple(contribution_values)
    provider_payload = CapabilityProviderDeclarationPayload(
        provider=CapabilityBundleProvider(
            capability_id="coding.foundation",
            provider_id=provider_id,
            implementation_version=1,
            compatible_contract=CapabilityContractRange.exact(1),
            facets=provider_facets,
            requirements=(
                CapabilityRequirement(
                    capability="harness.workspace",
                    facets=("read",),
                    compatible_contract=CapabilityContractRange.exact(1),
                ),
            ),
            source_id=f"plugin:{plugin_id}",
            selection_rule=PLUGIN_PROVIDER_SELECTION_RULE,
        ),
        factory=PluginSymbolReference(
            path="provider.py",
            symbol="create_provider",
            execution_model="in_process",
        ),
        disposer=PluginSymbolReference(
            path="provider.py",
            symbol="dispose_provider",
            execution_model="in_process",
        ),
        binding_inputs={"label": label},
    )
    tool_payload = ToolPackDeclarationPayload(
        catalog_id="coding.tools",
        catalog_revision=1,
        item_ids=("foundation-query",),
        owner_namespace="coding.tools",
        requirements=(
            CapabilityRequirement(
                capability="coding.foundation",
                facets=consumer_facets,
                compatible_contract=CapabilityContractRange.exact(1),
            ),
        ),
    )
    payloads = [provider_payload.to_dict()]
    if include_tool_pack:
        payloads.append(tool_payload.to_dict())
    declarations = tuple(
        PluginDeclaration(
            plugin_id=plugin_id,
            contribution_id=contribution.contribution_id,
            kind=contribution.kind,
            owner=contribution.owner,
            reservation_fingerprint=contribution.fingerprint,
            source_descriptor_fingerprint=(contribution.source_descriptor_fingerprint),
            source_kind=contribution.declaration_source.kind,
            payload=payload,
        )
        for contribution, payload in zip(contributions, payloads, strict=True)
    )
    (declarations_root / "foundation.json").write_bytes(
        PluginDeclarationDocumentCodec.encode_bytes(
            PluginDeclarationDocument(declarations=declarations)
        )
    )
    (source_root / "provider.py").write_text(
        _foundation_provider_source(events),
        encoding="utf-8",
    )
    (source_root / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_id,
                "version": "1",
                "contributionIndex": {
                    "version": 2,
                    "items": [item.to_dict() for item in contributions],
                },
            }
        ),
        encoding="utf-8",
    )
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=source_root))
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=PackageMaterializer(
            install_root=tmp_path / "foundation-installed",
            plugin_revision_root=tmp_path / "foundation-revisions",
        ),
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    return _FoundationPluginFixture(
        runtime=runtime,
        package=package,
        binding=binding,
        contributions=package.contribution_index.items,
        label=label,
        provider_id=provider_id,
    )


def _foundation_selection(
    *fixtures: _FoundationPluginFixture,
) -> PluginSelection:
    ordered = tuple(sorted(fixtures, key=lambda item: item.package.manifest.name))
    plugin_ids = tuple(item.package.manifest.name for item in ordered)
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="coding-plugin-policy-1",
            instance_revision_refs=tuple(
                PluginInstanceRevisionRef(
                    instance_id=f"{plugin_id}@workspace:test",
                    plugin_id=plugin_id,
                    revision=1,
                )
                for plugin_id in plugin_ids
            ),
        ),
        selected_plugin_ids=plugin_ids,
        selected_contributions=tuple(
            sorted(
                PluginContributionRef(
                    fixture.package.manifest.name,
                    item.contribution_id,
                )
                for fixture in ordered
                for item in fixture.contributions
            )
        ),
        source_trust_snapshots=tuple(
            PluginSourceTrustSnapshotV1(
                plugin_id=fixture.package.manifest.name,
                package_source_identity=fixture.binding.source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="trust-1",
                trusted=True,
            )
            for fixture in ordered
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id=fixture.package.manifest.name,
                    contribution_id=item.contribution_id,
                    configuration=(
                        {"label": fixture.label}
                        if item.kind == "capability_provider"
                        else {}
                    ),
                )
                for fixture in ordered
                for item in fixture.contributions
            )
        ),
        allowed_authority_ceiling=(),
    )
    result = PluginDeclarationHost().resolve(
        tuple(item.package for item in ordered),
        bindings=tuple(item.binding for item in ordered),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(result, PluginSelection)
    return result


def _foundation_assembly_request(
    *,
    selection: PluginSelection,
    definition: CapabilityDefinition,
    provider_authority: CapabilityProviderOwnerAuthority,
    owner_authority: OwnerContributionAuthority,
    workspace_binding: CapabilityBundleProviderBinding,
    selected_provider_id: str | None = None,
) -> ProductPluginCompositionAssemblyRequest:
    def select(
        admissions: tuple[CapabilityProviderAdmissionRecord, ...],
    ) -> tuple[ProductCapabilityProviderChoice, ...]:
        return tuple(
            ProductCapabilityProviderChoice(
                capability_id=item.capability_id,
                provider_id=item.provider.provider_id,
                candidate_fingerprint=item.candidate_fingerprint,
            )
            for item in admissions
            if selected_provider_id is None
            or item.provider.provider_id == selected_provider_id
        )

    return ProductPluginCompositionAssemblyRequest(
        contribution_request=ProductCompositionAssemblyRequest(
            selection=selection,
            owner_bindings=(
                ProductContributionOwnerBinding(
                    authority=owner_authority,
                    admission_ttl_seconds=200,
                ),
            ),
            mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
            definitions=(
                MODEL_INPUT_CAPABILITY_DEFINITION,
                WORKSPACE_CAPABILITY_DEFINITION,
                definition,
            ),
        ),
        provider_owner_bindings=(
            ProductCapabilityProviderOwnerBinding(
                authority=provider_authority,
                eligibility_ttl_seconds=250,
                admission_ttl_seconds=200,
            ),
        ),
        provider_roots=(definition.capability_id,),
        host_capability_ids=(
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
            WORKSPACE_CAPABILITY_DEFINITION.capability_id,
        ),
        select_capability_providers=select,
        prebound_providers=(workspace_binding.provider,),
    )


def _foundation_provider_authority(
    definition: CapabilityDefinition,
    *provider_ids: str,
) -> CapabilityProviderOwnerAuthority:
    return CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id=definition.capability_id,
            owner_id=definition.owner_id,
            policy_revision="coding-foundation-owner-1",
            revocation_epoch=3,
            allowed_provider_ids=tuple(sorted(provider_ids)),
            allowed_source_trust_classes=("host-equivalent-local",),
            authority_ceiling=(),
        )
    )


def _foundation_tool_owner_authority() -> OwnerContributionAuthority:
    return OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id="coding.tools",
            contribution_kind="tool_pack",
            product_id="coding",
            policy_revision="coding-tools-owner-1",
            revocation_epoch=2,
            allowed_source_trust_classes=("host-equivalent-local",),
            allowed_collection_ids=("coding.tools",),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    )


def _foundation_provider_source(events: Path) -> str:
    return f"""\
from pathlib import Path

from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleValue,
    CapabilityFacetBinding,
)

EVENTS = Path({str(events)!r})
with EVENTS.open("a", encoding="utf-8") as stream:
    stream.write("provider-import\\n")

def create_provider(context):
    with EVENTS.open("a", encoding="utf-8") as stream:
        stream.write("provider-create\\n")
    return CapabilityBundleValue((CapabilityFacetBinding(
        "query",
        {{
            "label": context.binding_inputs["label"],
            "runtime_id": context.runtime_id,
            "workspace_read": (
                context.dependency("harness.workspace").require("read") is not None
            ),
        }},
    ),))

def dispose_provider(_value):
    with EVENTS.open("a", encoding="utf-8") as stream:
        stream.write("provider-dispose\\n")
"""


def _append_event(path: Path, event: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(event + "\n")


def _bind_transcript_factory(
    disposed: list[str],
    *,
    release_events: list[str] | None = None,
    fail_release_once: bool = False,
) -> None:
    release_attempts = 0

    async def bind_runtime(context, binding: str):
        nonlocal release_attempts
        assert context.persist is False
        conversation_id = context.header.conversation_id

        async def dispose() -> None:
            nonlocal release_attempts
            release_attempts += 1
            if release_events is not None:
                release_events.append("release")
            if fail_release_once and release_attempts == 1:
                raise RuntimeError("transient transcript release failure")
            disposed.append(conversation_id)

        return AgentTranscriptRuntimeBinding(
            store=MemoryConversationStore(record_id=lambda record: record.record_id),
            key=ConversationKey("memory", conversation_id),
            profile=AgentTranscriptProfile.default(),
            product_binding=binding,
            dispose=dispose,
        )

    lifecycle = AgentTranscriptLifecycle(bind_runtime=bind_runtime)
    _ContractTranscriptSession._factory = AgentTranscriptSessionFactory(
        lifecycle=lifecycle,
        resolve_binding_input=lambda persist: "memory" if not persist else "file",
        header_metadata=lambda binding: {"productBinding": binding},
    )


async def _new_transcript(
    tmp_path: Path,
    *,
    product_id: str,
) -> _ContractTranscriptSession:
    transcript = await _ContractTranscriptSession.in_memory(
        cwd=tmp_path / product_id,
        session_id=f"{product_id}-session",
    )
    await transcript.append_message(
        UserMessage(
            role="user",
            content=f"{product_id} context that should be summarized",
            timestamp=1.0,
        )
    )
    await transcript.append_message(
        AssistantMessage(
            endpoint="test-endpoint",
            role="assistant",
            content=[TextPart(type="text", text=f"{product_id} recent reply")],
            api="test",
            provider="test",
            model=f"{product_id}-model",
            response_id=None,
            usage=Usage(
                input=20,
                output=10,
                cache_read=0,
                cache_write=0,
                total_tokens=30,
                cost=None,
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=2.0,
        )
    )
    return transcript


def _capability_runtime(product_id: str) -> StagedResourceCompositionCandidate:
    profile = RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id=product_id)
    )
    return stage_resource_composition_candidate(profile)


def _initial_catalog_bootstrap(
    tmp_path: Path,
    *,
    product_id: str,
    embedded_collections: tuple[EmbeddedResourceCollectionHandle, ...] = (),
) -> tuple[InitialSessionResourceCatalogBootstrap, ResourceBundle]:
    workspace = tmp_path / product_id
    resource_root = workspace / ".loushang"
    skill_root = resource_root / "skills" / "review"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review changes\n---\nReview carefully.\n",
        encoding="utf-8",
    )
    bundle = ResourceBundle(cwd=workspace)
    bootstrap = InitialSessionResourceCatalogBootstrap(
        InitialSessionResourceCatalogInputs(
            product_id=product_id,
            scope_id=f"session:{product_id}-session",
            resource_runtime_id=f"resource-owner:{product_id}-session",
            product_policy_revision="resource-policy-v1",
            root_handles=(
                mint_native_resource_root_handle(
                    handle_id=f"{product_id}-resources",
                    root=resource_root,
                    source_class="project_local",
                    root_kind="standard",
                ),
            ),
            embedded_collections=embedded_collections,
            issued_at=1,
            expires_at=10,
            now=2,
            base_resource_bundle=bundle,
        )
    )
    return bootstrap, bundle


class _UnusedWorkspaceLauncher:
    async def start(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("workspace cleanup does not start a process")


def _model(product_id: str) -> Model:
    return Model(
        id=f"{product_id}-model",
        name=f"{product_id.title()} Model",
        provider="test",
        endpoint="test",
        capabilities=Capabilities(
            input=("text",),
            context_window=128_000,
            max_tokens=4_096,
        ),
    )


def _checkpoint_summaries(
    transcript: _ContractTranscriptSession,
) -> list[str]:
    return [
        entry.payload.summary
        for entry in transcript.get_entries()
        if isinstance(entry.payload, ContextCompactionCheckpoint)
    ]


def _assert_compaction_events(
    events: list[dict[str, object]],
    *,
    product_id: str,
    session_id: str,
    reserve_tokens: int,
    compact_percent: float,
) -> None:
    compaction_events = [
        event
        for event in events
        if event["type"] in {"compaction_start", "compaction_end"}
    ]
    assert [event["type"] for event in compaction_events] == [
        "compaction_start",
        "compaction_end",
    ]
    assert all(event["product_id"] == product_id for event in compaction_events)
    assert all(event["session_id"] == session_id for event in compaction_events)
    usage = compaction_events[0]["usage"]
    assert isinstance(usage, dict)
    assert usage["reserve_tokens"] == reserve_tokens
    assert usage["compact_percent"] == compact_percent


def _assert_no_composed_runtime_mirrors(session: AgentProductSession) -> None:
    mirrored_runtime_names = {
        "_bash_runtime",
        "_command_controller",
        "_compaction_capability",
        "_compaction_runtime",
        "_diagnostics_bridge",
        "_extension_binding",
        "_extension_event_sink",
        "_extension_input_runtime",
        "_extension_message_controller",
        "_identity_binding",
        "_maintenance_binding",
        "_model_binding",
        "_navigation_runtime",
        "_resource_refresh_runtime",
        "_resource_watch_controller",
        "_retry_runtime",
        "_selection_runtime",
        "_session_inspector",
        "_session_runtime",
        "_tool_controller",
    }
    assert mirrored_runtime_names.isdisjoint(vars(session))
