from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Literal

import pytest

from loushang.coding.lsp._plugin_opt_in import (
    CodingLspPluginOptInError,
    CodingLspPluginOptInRequest,
    assemble_coding_lsp_plugin_opt_in,
    create_coding_lsp_default_plugin_opt_in_request,
    prepare_coding_lsp_plugin_opt_in,
)
from loushang.coding.lsp._provider_api import (
    CODING_LSP_TOOL_RUNTIME_FACET,
    CodingLspPluginConfigV1,
)
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.approval.plugin_activation import (
    ContributionActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationDecisionRecordV1,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginApprovalDecisionRecordV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.capabilities.component_host import CapabilityComponentHost
from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleValue,
    CapabilityFacetBinding,
)
from loushang.harness.capabilities.workspace_provider import (
    workspace_capability_provider_binding,
)
from loushang.harness.resources.plugins.selection import (
    PluginExecutionApprovalSubject,
)
from loushang.harness.runtime.bindings import RuntimeBindingState
from loushang.harness.runtime.registration import (
    RegistrationDisposalResult,
    RegistrationIdentity,
    RegistrationLease,
    RegistrationOwner,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
    SessionCapabilityConsumerCapture,
    commit_session_capability_owner_generations,
    dispose_session_capability_owner_generations,
    stage_session_capability_owner_generations,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.workspace.operations import LocalToolOperations
from loushang.harness.workspace.process import (
    ProcessHandle,
    ProcessLaunchRequest,
)


@dataclass(slots=True)
class _ApprovalOwner:
    now: int
    definition_disposition: Literal["approved", "denied"] = "approved"
    activation_disposition: Literal["approved", "denied"] = "approved"
    definition_calls: int = 0
    activation_calls: int = 0
    activation_decision: PluginActivationDecisionRecordV1 | None = None

    def approve_definition(
        self,
        *,
        journal: PluginExecutionDecisionJournal,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginApprovalDecisionRecordV1:
        self.definition_calls += 1
        return journal.issue_execution_decision(
            subject,
            disposition=self.definition_disposition,
            authorization=PluginApprovalAuthorizationV1.direct(
                actor_id="operator:test",
                source="coding-lsp-opt-in-test",
            ),
            revocation_epoch=0,
            issued_at_unix_ms=self.now - 10,
            expires_at_unix_ms=self.now + 1_000,
            expected_journal_revision=journal.snapshot().journal_revision,
        )

    def approve_activation(
        self,
        *,
        journal: PluginActivationDecisionJournal,
        subject: ContributionActivationApprovalSubject,
    ) -> PluginActivationDecisionRecordV1:
        self.activation_calls += 1
        decision = journal.issue_activation_decision(
            subject,
            disposition=self.activation_disposition,
            authorization=PluginApprovalAuthorizationV1.direct(
                actor_id="operator:test",
                source="coding-lsp-opt-in-test",
            ),
            issued_at_unix_ms=self.now - 10,
            expires_at_unix_ms=self.now + 1_000,
            expected_journal_revision=journal.snapshot().journal_revision,
        )
        self.activation_decision = decision
        return decision


class _UnusedWorkspaceLauncher:
    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ProcessHandle:
        del request, correlation_id, signal
        raise AssertionError("inert opt-in assembly must not launch a process")


@dataclass(slots=True)
class _ToolRegistrationPort:
    fail_on: str | None = None
    staged: list[str] = field(default_factory=list)
    visible: list[str] = field(default_factory=list)
    enabled: list[tuple[str, bool]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    activation_snapshots: list[tuple[str, ...]] = field(default_factory=list)

    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease:
        del source_info
        assert isinstance(tool, ToolDefinition)
        name = tool.name
        if name == self.fail_on:
            self.events.append(f"fail:{name}")
            raise RuntimeError("injected Tool staging failure")
        self.staged.append(name)
        self.enabled.append((name, enabled))
        self.events.append(f"stage:{name}")
        identity = RegistrationIdentity.create(surface="tool", public_key=name)

        def activate() -> None:
            self.activation_snapshots.append(tuple(self.staged))
            self.visible.append(name)
            self.events.append(f"activate:{name}")

        def deactivate() -> None:
            self.visible.remove(name)
            self.events.append(f"deactivate:{name}")

        def rollback() -> RegistrationDisposalResult:
            self.staged.remove(name)
            self.events.append(f"rollback:{name}")
            return RegistrationDisposalResult(state="removed")

        def dispose() -> RegistrationDisposalResult:
            if name in self.visible:
                self.visible.remove(name)
            if name in self.staged:
                self.staged.remove(name)
            self.events.append(f"dispose:{name}")
            return RegistrationDisposalResult(state="removed")

        return RegistrationLease(
            owner=owner,
            identity=identity,
            dispose=dispose,
            activate=activate,
            deactivate=deactivate,
            rollback=rollback,
        )


def test_product_opt_in_request_rejects_an_object_without_approval_owner_ports() -> (
    None
):
    assert tuple(item.name for item in fields(CodingLspPluginOptInRequest)) == (
        "approval_owner",
    )
    with pytest.raises(TypeError, match="Approval owner"):
        CodingLspPluginOptInRequest(approval_owner=object())  # type: ignore[arg-type]


def test_product_opt_in_composer_reaches_approved_session_inputs_without_start(
    tmp_path: Path,
) -> None:
    now = 2_500
    cleanup_calls: list[str] = []
    approval_owner = _ApprovalOwner(now)
    materializer = CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    workspace_binding = workspace_capability_provider_binding(
        operations=LocalToolOperations(),
        process_launcher=_UnusedWorkspaceLauncher(),
        scope_instance_id="workspace:test",
        binding_input_fingerprint="1" * 64,
        source_id="coding-lsp-opt-in-test",
    )
    config = CodingLspPluginConfigV1.from_runtime_inputs(
        workspace_root=tmp_path,
        definitions=(),
        baseline_environment={"PATH": "/admitted/bin"},
    )

    assembled = assemble_coding_lsp_plugin_opt_in(
        CodingLspPluginOptInRequest(approval_owner=approval_owner),
        session_id="session-test",
        config=config,
        package_materializer=materializer,
        workspace_binding=workspace_binding,
        state_root=tmp_path / "state",
        host_boot_id="3" * 32,
        tool_mode="on_demand",
        clock=lambda: now,
        state_cleanup=lambda: cleanup_calls.append("cleanup"),
    )
    revision_handle = assembled.runtime.packages[0].revision_handle
    assert revision_handle.closed is False
    try:
        assert approval_owner.definition_calls == 1
        assert approval_owner.activation_calls == 1
        assert {item.declaration.kind for item in assembled.selection.candidates} == {
            "capability_provider",
            "tool_pack",
        }
        [catalog_admission] = (
            assembled.plugin_assembly.product_composition.catalog_admissions
        )
        assert catalog_admission.owner_id == "coding.tools"
        contribution = catalog_admission.candidate.contribution
        assert isinstance(contribution, CatalogConsumerContributionSpec)
        assert contribution.item_ids == (
            "document_outline",
            "inspect_symbol",
        )
        [resolved] = assembled.plugin_assembly.resolved_providers.entries
        [component] = assembled.plugin_assembly.component_candidates
        assert resolved.capability_id == "coding.lsp"
        assert resolved.provider.provider_id == "coding.lsp.default"
        assert component.resolved is resolved
        assert component.package is assembled.runtime.packages[0]
        assert isinstance(assembled.component_host, CapabilityComponentHost)
        assert isinstance(assembled.session_inputs, SessionCapabilityCompositionInputs)
        assert (
            assembled.session_inputs.product_composition
            is assembled.plugin_assembly.product_composition
        )
        [component_request] = assembled.session_inputs.component_requests
        assert component_request.resolved is resolved
        assert approval_owner.activation_decision is not None
        assert component_request.activation_decision_id == (
            approval_owner.activation_decision.decision_id
        )
        assert approval_owner.activation_decision.consumption_state == "AVAILABLE"
    finally:
        assembled.close()
    assert revision_handle.closed is True
    assembled.close()
    assert cleanup_calls == ["cleanup"]


def test_product_opt_in_preparation_retries_failed_state_cleanup(
    tmp_path: Path,
) -> None:
    attempts = 0

    def flaky_cleanup() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("injected transient state cleanup failure")

    preparation = prepare_coding_lsp_plugin_opt_in(
        CodingLspPluginOptInRequest(approval_owner=_ApprovalOwner(2_500)),
        session_id="session-test",
        config=CodingLspPluginConfigV1.from_runtime_inputs(
            workspace_root=tmp_path,
            definitions=(),
            baseline_environment={"PATH": "/admitted/bin"},
        ),
        package_materializer=CodingPackageMaterializer(
            install_root=tmp_path / "installed",
            plugin_revision_root=tmp_path / "revisions",
        ),
        state_root=tmp_path / "state",
        clock=lambda: 2_500,
        state_cleanup=flaky_cleanup,
    )
    [revision_handle] = (
        package.revision_handle for package in preparation.runtime.packages
    )

    with pytest.raises(OSError, match="transient state cleanup failure"):
        preparation.close()

    assert revision_handle.closed is True
    assert preparation._runtime_closed is True
    assert preparation._state_cleaned is False
    assert preparation._closed is False

    preparation.close()

    assert attempts == 2
    assert preparation._state_cleaned is True
    assert preparation._closed is True


def test_product_opt_in_assembly_retries_failed_state_cleanup(tmp_path: Path) -> None:
    attempts = 0

    def flaky_cleanup() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("injected transient assembly cleanup failure")

    assembled = assemble_coding_lsp_plugin_opt_in(
        CodingLspPluginOptInRequest(approval_owner=_ApprovalOwner(2_500)),
        session_id="session-test",
        config=CodingLspPluginConfigV1.from_runtime_inputs(
            workspace_root=tmp_path,
            definitions=(),
            baseline_environment={"PATH": "/admitted/bin"},
        ),
        package_materializer=CodingPackageMaterializer(
            install_root=tmp_path / "installed",
            plugin_revision_root=tmp_path / "revisions",
        ),
        workspace_binding=workspace_capability_provider_binding(
            operations=LocalToolOperations(),
            process_launcher=_UnusedWorkspaceLauncher(),
            scope_instance_id="workspace:test",
            binding_input_fingerprint="9" * 64,
            source_id="coding-lsp-opt-in-test",
        ),
        state_root=tmp_path / "state",
        host_boot_id="3" * 32,
        tool_mode="on_demand",
        clock=lambda: 2_500,
        state_cleanup=flaky_cleanup,
    )

    with pytest.raises(OSError, match="transient assembly cleanup failure"):
        assembled.close()

    assert assembled._runtime_closed is True
    assert assembled._state_cleaned is False
    assert assembled._closed is False

    assembled.close()

    assert attempts == 2
    assert assembled._state_cleaned is True
    assert assembled._closed is True


def test_product_opt_in_tool_owner_stages_complete_generation_and_retires_reverse(
    tmp_path: Path,
) -> None:
    now = 2_500
    materializer = CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    workspace_binding = workspace_capability_provider_binding(
        operations=LocalToolOperations(),
        process_launcher=_UnusedWorkspaceLauncher(),
        scope_instance_id="workspace:test",
        binding_input_fingerprint="4" * 64,
        source_id="coding-lsp-opt-in-test",
    )
    assembled = assemble_coding_lsp_plugin_opt_in(
        CodingLspPluginOptInRequest(approval_owner=_ApprovalOwner(now)),
        session_id="session-test",
        config=CodingLspPluginConfigV1.from_runtime_inputs(
            workspace_root=tmp_path,
            definitions=(),
            baseline_environment={"PATH": "/admitted/bin"},
        ),
        package_materializer=materializer,
        workspace_binding=workspace_binding,
        state_root=tmp_path / "state",
        host_boot_id="3" * 32,
        tool_mode="on_demand",
        clock=lambda: now,
    )
    registration = _ToolRegistrationPort()
    runtime_state = RuntimeBindingState(
        CapabilityBundleValue(
            (CapabilityFacetBinding(CODING_LSP_TOOL_RUNTIME_FACET, object()),)
        )
    )
    [entry] = (
        assembled.session_inputs.product_composition.consumer_requirements.satisfied_entries
    )
    capture = SessionCapabilityConsumerCapture(
        entry=entry,
        facets=CapabilityFacetSet(
            requirement=entry.requirement,
            _lease=runtime_state.capture(),
        ),
    )
    binding = assembled.tool_owner.bind(registration)
    with pytest.raises(RuntimeError, match="already bound"):
        assembled.tool_owner.bind(registration)

    async def scenario() -> None:
        generations = await stage_session_capability_owner_generations(
            admissions=(
                assembled.plugin_assembly.product_composition.catalog_admissions
            ),
            bindings=(binding,),
            captures=(capture,),
        )
        assert registration.visible == []
        assert registration.staged == ["document_outline", "inspect_symbol"]
        commit_session_capability_owner_generations(generations)
        assert registration.visible == ["document_outline", "inspect_symbol"]
        assert registration.enabled == [
            ("document_outline", False),
            ("inspect_symbol", False),
        ]
        assert registration.activation_snapshots == [
            ("document_outline", "inspect_symbol"),
            ("document_outline", "inspect_symbol"),
        ]
        await dispose_session_capability_owner_generations(generations)

    try:
        asyncio.run(scenario())
        assert registration.visible == []
        assert registration.staged == []
        assert registration.events == [
            "stage:document_outline",
            "stage:inspect_symbol",
            "activate:document_outline",
            "activate:inspect_symbol",
            "dispose:inspect_symbol",
            "dispose:document_outline",
        ]
    finally:
        assembled.close()


def test_product_opt_in_tool_owner_rolls_back_partial_staging(
    tmp_path: Path,
) -> None:
    now = 2_500
    assembled = assemble_coding_lsp_plugin_opt_in(
        CodingLspPluginOptInRequest(approval_owner=_ApprovalOwner(now)),
        session_id="session-test",
        config=CodingLspPluginConfigV1.from_runtime_inputs(
            workspace_root=tmp_path,
            definitions=(),
            baseline_environment={"PATH": "/admitted/bin"},
        ),
        package_materializer=CodingPackageMaterializer(
            install_root=tmp_path / "installed",
            plugin_revision_root=tmp_path / "revisions",
        ),
        workspace_binding=workspace_capability_provider_binding(
            operations=LocalToolOperations(),
            process_launcher=_UnusedWorkspaceLauncher(),
            scope_instance_id="workspace:test",
            binding_input_fingerprint="5" * 64,
            source_id="coding-lsp-opt-in-test",
        ),
        state_root=tmp_path / "state",
        host_boot_id="3" * 32,
        tool_mode="always",
        clock=lambda: now,
    )
    registration = _ToolRegistrationPort(fail_on="inspect_symbol")
    runtime_state = RuntimeBindingState(
        CapabilityBundleValue(
            (CapabilityFacetBinding(CODING_LSP_TOOL_RUNTIME_FACET, object()),)
        )
    )
    [entry] = (
        assembled.session_inputs.product_composition.consumer_requirements.satisfied_entries
    )
    capture = SessionCapabilityConsumerCapture(
        entry=entry,
        facets=CapabilityFacetSet(
            requirement=entry.requirement,
            _lease=runtime_state.capture(),
        ),
    )
    binding = assembled.tool_owner.bind(registration)

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="injected Tool staging failure"):
            await stage_session_capability_owner_generations(
                admissions=(
                    assembled.plugin_assembly.product_composition.catalog_admissions
                ),
                bindings=(binding,),
                captures=(capture,),
            )

    try:
        asyncio.run(scenario())
        assert registration.visible == []
        assert registration.staged == []
        assert registration.enabled == [("document_outline", True)]
        assert registration.events == [
            "stage:document_outline",
            "fail:inspect_symbol",
            "rollback:document_outline",
        ]
    finally:
        assembled.close()


def test_product_opt_in_definition_denial_is_fail_closed(
    tmp_path: Path,
) -> None:
    now = 2_500
    approval_owner = _ApprovalOwner(now, definition_disposition="denied")
    materializer = CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    workspace_binding = workspace_capability_provider_binding(
        operations=LocalToolOperations(),
        process_launcher=_UnusedWorkspaceLauncher(),
        scope_instance_id="workspace:test",
        binding_input_fingerprint="2" * 64,
        source_id="coding-lsp-opt-in-test",
    )

    with pytest.raises(CodingLspPluginOptInError) as captured:
        assemble_coding_lsp_plugin_opt_in(
            CodingLspPluginOptInRequest(approval_owner=approval_owner),
            session_id="session-test",
            config=CodingLspPluginConfigV1.from_runtime_inputs(
                workspace_root=tmp_path,
                definitions=(),
                baseline_environment={"PATH": "/admitted/bin"},
            ),
            package_materializer=materializer,
            workspace_binding=workspace_binding,
            state_root=tmp_path / "state",
            host_boot_id="3" * 32,
            tool_mode="on_demand",
            clock=lambda: now,
        )

    assert captured.value.code == "coding_lsp_plugin_definition_denied"
    assert approval_owner.definition_calls == 1
    assert approval_owner.activation_calls == 0


def test_product_opt_in_preserves_unknown_neutral_error_without_self_cause(
    tmp_path: Path,
) -> None:
    failure = CodingLspPluginOptInError(
        "injected unknown neutral failure",
        code="coding_capability_injected_unknown",
    )

    class UnknownFailureApprovalOwner:
        def approve_definition(
            self,
            *,
            journal: PluginExecutionDecisionJournal,
            subject: PluginExecutionApprovalSubject,
        ) -> PluginApprovalDecisionRecordV1:
            del journal, subject
            raise failure

        def approve_activation(
            self,
            *,
            journal: PluginActivationDecisionJournal,
            subject: ContributionActivationApprovalSubject,
        ) -> PluginActivationDecisionRecordV1:
            del journal, subject
            raise AssertionError("definition failure must stop activation")

    with pytest.raises(CodingLspPluginOptInError) as captured:
        prepare_coding_lsp_plugin_opt_in(
            CodingLspPluginOptInRequest(
                approval_owner=UnknownFailureApprovalOwner()
            ),
            session_id="session-test",
            config=CodingLspPluginConfigV1.from_runtime_inputs(
                workspace_root=tmp_path,
                definitions=(),
                baseline_environment={"PATH": "/admitted/bin"},
            ),
            package_materializer=CodingPackageMaterializer(
                install_root=tmp_path / "installed",
                plugin_revision_root=tmp_path / "revisions",
            ),
            state_root=tmp_path / "state",
            clock=lambda: 2_500,
        )

    assert captured.value is failure
    assert captured.value.code == "coding_capability_injected_unknown"
    assert captured.value.__cause__ is not captured.value


def test_product_opt_in_activation_denial_is_fail_closed(
    tmp_path: Path,
) -> None:
    now = 2_500
    approval_owner = _ApprovalOwner(now, activation_disposition="denied")
    materializer = CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    workspace_binding = workspace_capability_provider_binding(
        operations=LocalToolOperations(),
        process_launcher=_UnusedWorkspaceLauncher(),
        scope_instance_id="workspace:test",
        binding_input_fingerprint="3" * 64,
        source_id="coding-lsp-opt-in-test",
    )

    with pytest.raises(CodingLspPluginOptInError) as captured:
        assemble_coding_lsp_plugin_opt_in(
            CodingLspPluginOptInRequest(approval_owner=approval_owner),
            session_id="session-test",
            config=CodingLspPluginConfigV1.from_runtime_inputs(
                workspace_root=tmp_path,
                definitions=(),
                baseline_environment={"PATH": "/admitted/bin"},
            ),
            package_materializer=materializer,
            workspace_binding=workspace_binding,
            state_root=tmp_path / "state",
            host_boot_id="3" * 32,
            tool_mode="on_demand",
            clock=lambda: now,
        )

    assert captured.value.code == "coding_lsp_plugin_activation_denied"
    assert approval_owner.definition_calls == 1
    assert approval_owner.activation_calls == 1


def test_product_opt_in_reconstructs_with_fresh_exact_activation_evidence(
    tmp_path: Path,
) -> None:
    now = 2_500
    materializer = CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    workspace_binding = workspace_capability_provider_binding(
        operations=LocalToolOperations(),
        process_launcher=_UnusedWorkspaceLauncher(),
        scope_instance_id="workspace:test",
        binding_input_fingerprint="6" * 64,
        source_id="coding-lsp-opt-in-test",
    )
    config = CodingLspPluginConfigV1.from_runtime_inputs(
        workspace_root=tmp_path,
        definitions=(),
        baseline_environment={"PATH": "/admitted/bin"},
    )
    first_owner = _ApprovalOwner(now)
    first = assemble_coding_lsp_plugin_opt_in(
        CodingLspPluginOptInRequest(approval_owner=first_owner),
        session_id="session-test",
        config=config,
        package_materializer=materializer,
        workspace_binding=workspace_binding,
        state_root=tmp_path / "state",
        host_boot_id="3" * 32,
        tool_mode="on_demand",
        clock=lambda: now,
    )
    [first_request] = first.session_inputs.component_requests
    first.close()

    second_owner = _ApprovalOwner(now)
    second = assemble_coding_lsp_plugin_opt_in(
        CodingLspPluginOptInRequest(approval_owner=second_owner),
        session_id="session-test",
        config=config,
        package_materializer=materializer,
        workspace_binding=workspace_binding,
        state_root=tmp_path / "state",
        host_boot_id="3" * 32,
        tool_mode="on_demand",
        clock=lambda: now,
    )
    try:
        [second_request] = second.session_inputs.component_requests
        assert second_request.activation_decision_id != (
            first_request.activation_decision_id
        )
        assert second_owner.definition_calls == 1
        assert second_owner.activation_calls == 1
    finally:
        second.close()


def test_default_product_approval_owner_accepts_only_exact_lsp_closure(
    tmp_path: Path,
) -> None:
    now = 2_500
    request = create_coding_lsp_default_plugin_opt_in_request(clock=lambda: now)
    assembled = assemble_coding_lsp_plugin_opt_in(
        request,
        session_id="session-test",
        config=CodingLspPluginConfigV1.from_runtime_inputs(
            workspace_root=tmp_path,
            definitions=(),
            baseline_environment={"PATH": "/admitted/bin"},
        ),
        package_materializer=CodingPackageMaterializer(
            install_root=tmp_path / "installed",
            plugin_revision_root=tmp_path / "revisions",
        ),
        workspace_binding=workspace_capability_provider_binding(
            operations=LocalToolOperations(),
            process_launcher=_UnusedWorkspaceLauncher(),
            scope_instance_id="workspace:test",
            binding_input_fingerprint="7" * 64,
            source_id="coding-lsp-opt-in-test",
        ),
        state_root=tmp_path / "state",
        host_boot_id="3" * 32,
        tool_mode="on_demand",
        clock=lambda: now,
    )
    try:
        [component_request] = assembled.session_inputs.component_requests
        journal = PluginActivationDecisionJournal(
            tmp_path / "state" / "activation-decisions.jsonl",
            scope_id="session:session-test",
            clock=lambda: now,
        )
        [decision] = journal.snapshot().decisions
        assert decision.decision_id == component_request.activation_decision_id
        assert decision.authorization.actor_id == "product:coding"
        assert decision.authorization.source == (
            "coding-lsp-default-product-policy"
        )
        assert decision.subject.plugin_id == "coding.lsp.default"
        assert decision.subject.capability_id == "coding.lsp"
        assert isinstance(decision.subject, ContributionActivationApprovalSubject)
        with pytest.raises(CodingLspPluginOptInError) as captured:
            request.approval_owner.approve_activation(
                journal=journal,
                subject=replace(decision.subject, provider_id="foreign"),
            )
        assert captured.value.code == (
            "coding_lsp_default_activation_subject_rejected"
        )
    finally:
        assembled.close()


def test_default_product_approval_spans_the_provider_admission_window(
    tmp_path: Path,
) -> None:
    now = [2_500]
    assembled = assemble_coding_lsp_plugin_opt_in(
        create_coding_lsp_default_plugin_opt_in_request(clock=lambda: now[0]),
        session_id="session-test",
        config=CodingLspPluginConfigV1.from_runtime_inputs(
            workspace_root=tmp_path,
            definitions=(),
            baseline_environment={"PATH": "/admitted/bin"},
        ),
        package_materializer=CodingPackageMaterializer(
            install_root=tmp_path / "installed",
            plugin_revision_root=tmp_path / "revisions",
        ),
        workspace_binding=workspace_capability_provider_binding(
            operations=LocalToolOperations(),
            process_launcher=_UnusedWorkspaceLauncher(),
            scope_instance_id="workspace:test",
            binding_input_fingerprint="8" * 64,
            source_id="coding-lsp-opt-in-test",
        ),
        state_root=tmp_path / "state",
        host_boot_id="3" * 32,
        tool_mode="on_demand",
        clock=lambda: now[0],
    )
    try:
        now[0] += 61_000
        [request] = assembled.session_inputs.component_requests
        prepared = assembled.component_host.prepare_component(
            request.resolved,
            package=request.package,
            owner_snapshot=request.owner_snapshot,
            trust_snapshot=request.trust_snapshot,
            decision_id=request.activation_decision_id,
        )
        assert prepared.cancel_before_start() is True
    finally:
        assembled.close()
