from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest

from loushang.coding.lsp._provider_api import CodingLspPluginConfigV1
from loushang.coding.plugin_dependency_grants import (
    coding_lsp_default_plugin_root,
    coding_plugin_distribution_evidence_resolver,
)
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.capabilities.component_host import (
    _PROVIDER_HOST_API_PREFIXES,
)
from loushang.harness.plugin_authoring.capability_provider import (
    PLUGIN_PROVIDER_SELECTION_RULE,
    CapabilityProviderDeclarationPayload,
)
from loushang.harness.plugin_authoring.consumer_pack import (
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.coordinator import (
    PluginDeclarationCoordinator,
)
from loushang.harness.plugin_authoring.evaluator import (
    PluginDefinitionEvaluationError,
    PluginDefinitionEvaluator,
)
from loushang.harness.plugin_authoring.import_realm import PluginImportRealm
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceResolver,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.python_symbols import (
    load_verified_plugin_python_module,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginDeclarationSourceGroup,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightAcceptedOutcome,
    PluginPreflightContextV1,
    PluginPreflightPendingApprovalOutcome,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
    PublishedPluginPackage,
)


def test_checked_in_lsp_plugin_is_published_with_exact_loushang_evidence(
    tmp_path: Path,
) -> None:
    evidence_resolver = coding_plugin_distribution_evidence_resolver()
    materializer = CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
        installed_distribution_evidence_resolver=evidence_resolver,
    )
    package = PluginManifestParser().parse(coding_lsp_default_plugin_root())

    [published] = materializer.publish_plugin_packages((package,))
    [binding] = materializer.bind_plugin_packages((published,))

    assert package.manifest.name == "coding.lsp.default"
    assert len(package.contribution_index.items) == 2
    [distribution] = published.dependency_lock.python_distributions
    assert distribution.name == "loushang"
    assert distribution.version == importlib.metadata.version("loushang")
    assert binding.dependency_lock == published.dependency_lock


def test_checked_in_lsp_definition_requires_its_product_distribution_grant(
    tmp_path: Path,
) -> None:
    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    [published] = materializer.publish_plugin_packages(
        (PluginManifestParser().parse(coding_lsp_default_plugin_root()),)
    )
    [binding] = materializer.bind_plugin_packages((published,))

    with pytest.raises(PluginDefinitionEvaluationError) as captured:
        _evaluate_definition(
            tmp_path,
            published=published,
            binding=binding,
            distribution_evidence_resolver=(
                coding_plugin_distribution_evidence_resolver()
            ),
        )

    assert captured.value.code == "plugin_definition_evaluation_failed"


def test_checked_in_lsp_definition_emits_only_reserved_provider_ir(
    tmp_path: Path,
) -> None:
    evidence_resolver = coding_plugin_distribution_evidence_resolver()
    materializer = CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
        installed_distribution_evidence_resolver=evidence_resolver,
    )
    [published] = materializer.publish_plugin_packages(
        (PluginManifestParser().parse(coding_lsp_default_plugin_root()),)
    )
    [binding] = materializer.bind_plugin_packages((published,))

    selection, source_group, config = _evaluate_definition(
        tmp_path,
        published=published,
        binding=binding,
        distribution_evidence_resolver=evidence_resolver,
    )

    candidate = next(
        item
        for item in selection.candidates
        if item.declaration.kind == "capability_provider"
    )
    payload = CapabilityProviderDeclarationPayload.from_reserved_declaration(
        candidate.declaration,
        source_group=source_group,
    )
    assert candidate.declaration.contribution_id == "coding-lsp-default"
    assert payload.provider.capability_id == "coding.lsp"
    assert payload.provider.provider_id == "coding.lsp.default"
    assert payload.provider.selection_rule == PLUGIN_PROVIDER_SELECTION_RULE
    configuration_entry = next(
        item
        for item in source_group.effective_configuration_entries
        if item.contribution_id == "coding-lsp-default"
    )
    assert payload.binding_inputs == configuration_entry.configuration
    assert configuration_entry.to_dict()["configuration"] == config.to_dict()
    assert payload.factory.path == "definition.py"
    assert payload.factory.symbol == "create_provider"
    assert payload.disposer is not None
    assert payload.disposer.path == "definition.py"
    assert payload.disposer.symbol == "dispose_provider"

    tool_candidate = next(
        item
        for item in selection.candidates
        if item.declaration.kind == "tool_pack"
    )
    tool_payload = ToolPackDeclarationPayload.from_candidate(tool_candidate)
    assert tool_candidate.declaration.contribution_id == "coding-lsp-tools"
    assert tool_payload.catalog_id == "coding.lsp.tools"
    assert tool_payload.item_ids == ("document_outline", "inspect_symbol")
    assert tool_payload.owner_namespace == "coding.tools"
    assert [requirement.capability for requirement in tool_payload.requirements] == [
        "coding.lsp"
    ]


def test_checked_in_lsp_activation_symbols_import_through_component_host_boundary(
    tmp_path: Path,
) -> None:
    evidence_resolver = coding_plugin_distribution_evidence_resolver()
    materializer = CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
        installed_distribution_evidence_resolver=evidence_resolver,
    )
    [published] = materializer.publish_plugin_packages(
        (PluginManifestParser().parse(coding_lsp_default_plugin_root()),)
    )

    module = load_verified_plugin_python_module(
        revision_handle=published.revision_handle,
        dependency_lock=published.dependency_lock,
        relative_path="definition.py",
        module_name="_test_coding_lsp_default_component",
        host_api_prefixes=_PROVIDER_HOST_API_PREFIXES,
        distribution_evidence_resolver=evidence_resolver,
    )

    assert callable(module.resolve("create_provider"))
    assert callable(module.resolve("dispose_provider"))


def _evaluate_definition(
    tmp_path: Path,
    *,
    published: PublishedPluginPackage,
    binding: PluginSourceBinding,
    distribution_evidence_resolver: InstalledPythonDistributionEvidenceResolver,
) -> tuple[
    PluginSelection,
    PluginDeclarationSourceGroup,
    CodingLspPluginConfigV1,
]:
    config = CodingLspPluginConfigV1.from_runtime_inputs(
        workspace_root=tmp_path,
        definitions=(),
        baseline_environment={"PATH": "/admitted/bin"},
    )
    contributions = published.contribution_index.items
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="coding-plugin-policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id="coding.lsp.default@product",
                    plugin_id="coding.lsp.default",
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=("coding.lsp.default",),
        selected_contributions=tuple(
            PluginContributionRef(
                "coding.lsp.default",
                contribution.contribution_id,
            )
            for contribution in contributions
        ),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id="coding.lsp.default",
                package_source_identity=binding.source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="coding-plugin-trust-1",
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id="coding.lsp.default",
                    contribution_id=contribution.contribution_id,
                    configuration=(
                        config.to_dict()
                        if contribution.kind == "capability_provider"
                        else {}
                    ),
                )
                for contribution in contributions
            )
        ),
        allowed_authority_ceiling=("filesystem", "process"),
    )
    resolver = PluginSelectionResolver()
    journal = PluginExecutionDecisionJournal(
        tmp_path / "plugin-execution-decisions.jsonl",
        scope_kind="workspace",
        scope_id="workspace:test",
        decision_id_factory=lambda: "1" * 48,
        execution_use_id_factory=lambda: "2" * 48,
        clock=lambda: 2_500,
    )
    pending = resolver.preflight(
        (published,),
        bindings=(binding,),
        plan=plan,
        decision_lookup=journal,
    )
    assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
    [subject] = pending.subjects
    journal.issue_execution_decision(
        subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="operator:test",
            source="test",
        ),
        revocation_epoch=0,
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=5_000,
        expected_journal_revision=0,
    )
    outcome = resolver.preflight(
        (published,),
        bindings=(binding,),
        plan=plan,
        decision_lookup=journal,
    )
    assert isinstance(outcome, PluginPreflightAcceptedOutcome)
    source_group = next(
        item
        for item in outcome.accepted.source_groups
        if item.declaration_source.kind == "in_process"
    )
    selection = PluginDeclarationCoordinator(
        resolver,
        execution_evaluator=PluginDefinitionEvaluator(
            decision_journal=journal,
            import_realm=PluginImportRealm(
                import_realm_id_factory=lambda: "4" * 32
            ),
            clock=lambda: 2_500,
            distribution_evidence_resolver=distribution_evidence_resolver,
        ),
    ).finalize(outcome.accepted)
    assert isinstance(selection, PluginSelection)
    return selection, source_group, config
