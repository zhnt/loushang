from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from loushang.coding.lsp._plugin_opt_in import (
    CodingLspPluginOptInError,
    CodingLspPluginOptInRequest,
    assemble_coding_lsp_plugin_opt_in,
)
from loushang.coding.lsp._provider_api import CodingLspPluginConfigV1
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
from loushang.harness.capabilities.workspace_provider import (
    workspace_capability_provider_binding,
)
from loushang.harness.resources.plugins.selection import (
    PluginExecutionApprovalSubject,
)
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyError,
)
from loushang.harness.workspace.operations import LocalToolOperations
from loushang.harness.workspace.process import (
    ProcessHandle,
    ProcessLaunchRequest,
)


@dataclass(slots=True)
class _ApprovalOwner:
    now: int
    definition_disposition: str = "approved"
    definition_calls: int = 0
    activation_calls: int = 0

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
        del journal, subject
        self.activation_calls += 1
        raise AssertionError("assembly must not request activation")


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


def test_product_opt_in_request_rejects_an_object_without_approval_owner_ports(
) -> None:
    assert tuple(item.name for item in fields(CodingLspPluginOptInRequest)) == (
        "approval_owner",
    )
    with pytest.raises(TypeError, match="Approval owner"):
        CodingLspPluginOptInRequest(approval_owner=object())


def test_product_opt_in_composer_owns_selection_admission_and_resolution(
    tmp_path: Path,
) -> None:
    now = 2_500
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
        clock=lambda: now,
    )
    revision_handle = assembled.runtime.packages[0].revision_handle
    assert revision_handle.closed is False
    try:
        assert approval_owner.definition_calls == 1
        assert approval_owner.activation_calls == 0
        assert {item.declaration.kind for item in assembled.selection.candidates} == {
            "capability_provider",
            "tool_pack",
        }
        [catalog_admission] = assembled.plugin_assembly.product_composition.catalog_admissions
        assert catalog_admission.owner_id == "coding.tools"
        assert catalog_admission.candidate.contribution.item_ids == (
            "document_outline",
            "inspect_symbol",
        )
        [resolved] = assembled.plugin_assembly.resolved_providers.entries
        [component] = assembled.plugin_assembly.component_candidates
        assert resolved.capability_id == "coding.lsp"
        assert resolved.provider.provider_id == "coding.lsp.default"
        assert component.resolved is resolved
        assert component.package is assembled.runtime.packages[0]
        with pytest.raises(ProductCompositionAssemblyError) as activation:
            assembled.plugin_assembly.bind_session_inputs({})
        assert activation.value.code == "product_provider_activation_missing"
    finally:
        assembled.close()
    assert revision_handle.closed is True
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
            clock=lambda: now,
        )

    assert captured.value.code == "coding_lsp_plugin_definition_denied"
    assert approval_owner.definition_calls == 1
    assert approval_owner.activation_calls == 0
