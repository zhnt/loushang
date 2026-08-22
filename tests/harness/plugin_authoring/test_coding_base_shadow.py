"""Inert ``coding.base`` shadow parity across all declaration routes."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.capabilities import (
    CapabilityContractRange,
    CapabilityRequirement,
)
from loushang.harness.plugin_authoring.builder import PluginDeclarationBuilder
from loushang.harness.plugin_authoring.consumer_pack import (
    CommandPackDeclarationPayload,
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.plugin_authoring.semantic_fingerprint import (
    compile_plugin_contribution_semantic_fingerprint,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionKind,
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationSource,
)
from loushang.harness.resources.plugins.selection import (
    AcceptedPluginPreflight,
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionCandidate,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionCurrent,
    PluginExecutionDecisionLookupResult,
    PluginExecutionDecisionRecord,
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
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)

_SHADOW_ROOT = (
    Path(__file__).parent.parent
    / "resources"
    / "plugins"
    / "fixtures"
    / "coding_base_shadow"
)


@dataclass(frozen=True, slots=True)
class _PublishedShadow:
    runtime: PluginRuntimeResolution
    package: PublishedPluginPackage
    binding: PluginSourceBinding


@dataclass(frozen=True, slots=True)
class _ShadowPayloads:
    command_standard: CommandPackDeclarationPayload
    prompt_standard: ResourceItemDeclarationPayload
    skill_standard: ResourceItemDeclarationPayload
    tool_builtin: ToolPackDeclarationPayload

    def by_contribution_id(self) -> dict[
        str,
        CommandPackDeclarationPayload
        | ResourceItemDeclarationPayload
        | ToolPackDeclarationPayload,
    ]:
        return {
            "coding.builtin": self.tool_builtin,
            "coding.standard": self.command_standard,
            "prompt-standard": self.prompt_standard,
            "skill-standard": self.skill_standard,
        }


@dataclass(frozen=True, slots=True)
class _CurrentDecisionLookup:
    decision: PluginExecutionDecisionRecord

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult:
        return PluginExecutionDecisionCurrent(decision=self.decision)


def test_coding_base_shadow_proves_three_route_semantic_parity_without_effects(
    tmp_path: Path,
) -> None:
    document_shadow = _publish_shadow(
        _SHADOW_ROOT,
        install_root=tmp_path / "document-installed",
        revision_root=tmp_path / "document-revisions",
    )
    builder_shadow, import_marker = _publish_builder_shadow(tmp_path)
    resolver = PluginSelectionResolver()
    accepted: AcceptedPluginPreflight | None = None
    try:
        first_selection = PluginDeclarationHost().resolve(
            (document_shadow.package,),
            bindings=(document_shadow.binding,),
            plan=_plan(document_shadow, scope_id="workspace:first"),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        second_selection = PluginDeclarationHost().resolve(
            (document_shadow.package,),
            bindings=(document_shadow.binding,),
            plan=_plan(document_shadow, scope_id="workspace:second"),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        assert isinstance(first_selection, PluginSelection)
        assert isinstance(second_selection, PluginSelection)

        document_candidates = _candidate_map(first_selection)
        hand_authored = _hand_authored_declarations(document_shadow.package)
        assert {
            item.contribution_id: item.required
            for item in document_shadow.package.contribution_index.items
        } == {
            "coding.builtin": True,
            "coding.standard": True,
            "prompt-standard": False,
            "skill-standard": False,
        }
        accepted = _accept_builder_source(resolver, builder_shadow)
        [source_group] = accepted.source_groups
        builder = PluginDeclarationBuilder(source_group=source_group)
        payloads = _shadow_payloads()
        builder.add_command_pack(
            contribution_id="coding.standard",
            payload=payloads.command_standard,
        )
        builder.add_resource_item(
            contribution_id="prompt-standard",
            payload=payloads.prompt_standard,
        )
        builder.add_resource_item(
            contribution_id="skill-standard",
            payload=payloads.skill_standard,
        )
        builder.add_tool_pack(
            contribution_id="coding.builtin",
            payload=payloads.tool_builtin,
        )
        builder_declarations = {
            item.contribution_id: item for item in builder.build()
        }

        assert tuple(document_candidates) == tuple(hand_authored)
        assert tuple(document_candidates) == tuple(builder_declarations)
        for contribution_id, candidate in document_candidates.items():
            hand_declaration = hand_authored[contribution_id]
            builder_declaration = builder_declarations[contribution_id]
            assert candidate.declaration == hand_declaration
            assert candidate.declaration.to_dict()["payload"] == (
                builder_declaration.to_dict()["payload"]
            )
            semantic_digests = {
                compile_plugin_contribution_semantic_fingerprint(item).digest
                for item in (
                    hand_declaration,
                    candidate.declaration,
                    builder_declaration,
                )
            }
            assert len(semantic_digests) == 1
            assert hand_declaration.fingerprint != builder_declaration.fingerprint
            assert candidate.fingerprint not in semantic_digests

        second_candidates = _candidate_map(second_selection)
        assert {
            item.declaration.fingerprint for item in document_candidates.values()
        } == {
            item.declaration.fingerprint for item in second_candidates.values()
        }
        assert {
            item.fingerprint for item in document_candidates.values()
        }.isdisjoint({item.fingerprint for item in second_candidates.values()})

        assert import_marker.exists() is False
        assert not (_SHADOW_ROOT / "definition.py").exists()
        for candidate in document_candidates.values():
            assert not hasattr(candidate, "registration_scope")
            assert not hasattr(candidate, "registry")
            assert not hasattr(candidate, "session")
            assert not hasattr(candidate, "model_input")
            assert not hasattr(candidate, "disposer")
        _assert_candidate_payloads_are_inert(document_candidates)
    finally:
        if accepted is not None:
            resolver._abort(accepted)
        builder_shadow.runtime.close()
        document_shadow.runtime.close()


def _publish_shadow(
    source_root: Path,
    *,
    install_root: Path,
    revision_root: Path,
) -> _PublishedShadow:
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=source_root))
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=PackageMaterializer(
            install_root=install_root,
            plugin_revision_root=revision_root,
        ),
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    return _PublishedShadow(runtime=runtime, package=package, binding=binding)


def _publish_builder_shadow(tmp_path: Path) -> tuple[_PublishedShadow, Path]:
    source_root = tmp_path / "builder-source"
    source_root.mkdir()
    shutil.copytree(_SHADOW_ROOT / "prompts", source_root / "prompts")
    shutil.copytree(_SHADOW_ROOT / "skills", source_root / "skills")
    import_marker = tmp_path / "builder-definition-imported.txt"
    (source_root / "definition.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(import_marker)!r}).write_text('imported', encoding='utf-8')\n"
        "def define():\n"
        "    raise AssertionError('PLC1B must not evaluate a Definition')\n",
        encoding="utf-8",
    )
    source = PluginDeclarationSource.in_process("definition.py:define")
    contribution_specs: tuple[tuple[str, PluginContributionKind, str], ...] = (
        ("coding.builtin", "tool_pack", "tools.workspace"),
        ("coding.standard", "command_pack", "commands.session"),
        ("prompt-standard", "resource_item", "resources.prompt"),
        ("skill-standard", "resource_item", "resources.skill"),
    )
    contributions = tuple(
        PluginContributionReservation(
            contribution_id=contribution_id,
            kind=kind,
            owner=owner,
            declaration_source=source,
            contribution_execution_model="data_only",
            requested_authorities=(),
            required=kind != "resource_item",
        )
        for contribution_id, kind, owner in contribution_specs
    )
    (source_root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "coding.base",
                "version": "1",
                "contributionIndex": {
                    "version": 2,
                    "items": [item.to_dict() for item in contributions],
                },
            },
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return (
        _publish_shadow(
            source_root,
            install_root=tmp_path / "builder-installed",
            revision_root=tmp_path / "builder-revisions",
        ),
        import_marker,
    )


def _accept_builder_source(
    resolver: PluginSelectionResolver,
    shadow: _PublishedShadow,
) -> AcceptedPluginPreflight:
    plan = _plan(shadow, scope_id="workspace:builder")
    pending = resolver.preflight(
        (shadow.package,),
        bindings=(shadow.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
    [subject] = pending.subjects
    outcome = resolver.preflight(
        (shadow.package,),
        bindings=(shadow.binding,),
        plan=plan,
        decision_lookup=_CurrentDecisionLookup(
            PluginExecutionDecisionRecord(
                decision_id="decision-coding-base-shadow-builder",
                subject_digest=subject.digest,
                policy_revision=plan.context.policy_revision,
                disposition="approved",
            )
        ),
    )
    assert isinstance(outcome, PluginPreflightAcceptedOutcome)
    return outcome.accepted


def _plan(shadow: _PublishedShadow, *, scope_id: str) -> PluginSelectionPlanV2:
    plugin_id = shadow.package.manifest.name
    contributions = shadow.package.contribution_index.items
    return PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id=scope_id,
            policy_revision="policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id="coding.base@product",
                    plugin_id=plugin_id,
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=(plugin_id,),
        selected_contributions=tuple(
            PluginContributionRef(plugin_id, item.contribution_id)
            for item in contributions
        ),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id=plugin_id,
                package_source_identity=shadow.binding.source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="trust-1",
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id=plugin_id,
                    contribution_id=item.contribution_id,
                    configuration={},
                )
                for item in contributions
            )
        ),
        allowed_authority_ceiling=(),
    )


def _shadow_payloads() -> _ShadowPayloads:
    return _ShadowPayloads(
        command_standard=CommandPackDeclarationPayload(
            catalog_id="harness.session.standard",
            catalog_revision=1,
            item_ids=(
                "changelog",
                "clone",
                "compact",
                "copy",
                "delete",
                "export",
                "extensions",
                "fork",
                "import",
                "new",
                "reload",
                "rename",
                "resume",
                "session",
                "tools",
                "tree",
            ),
            owner_namespace="commands.session",
        ),
        prompt_standard=ResourceItemDeclarationPayload(
            locator="prompts/standard.md",
            locator_kind="file",
            media_type="text/markdown",
            owner_namespace="resources.prompt",
            resource_kind="prompt",
            schema_id="loushang.resource.prompt",
            schema_version=1,
        ),
        skill_standard=ResourceItemDeclarationPayload(
            locator="skills/standard/SKILL.md",
            locator_kind="file",
            media_type="text/markdown",
            owner_namespace="resources.skill",
            resource_kind="skill",
            schema_id="loushang.resource.skill",
            schema_version=1,
        ),
        tool_builtin=ToolPackDeclarationPayload(
            catalog_id="harness.workspace.core",
            catalog_revision=1,
            item_ids=("bash", "edit", "find", "grep", "ls", "read", "write"),
            owner_namespace="tools.workspace",
            requirements=(
                CapabilityRequirement(
                    capability="harness.workspace",
                    facets=("edit", "list", "process.launch", "read", "search", "write"),
                    compatible_contract=CapabilityContractRange.exact(1),
                ),
            ),
        ),
    )


def _hand_authored_declarations(
    package: PublishedPluginPackage,
) -> dict[str, PluginDeclaration]:
    payloads = _shadow_payloads().by_contribution_id()
    return {
        item.contribution_id: PluginDeclaration(
            plugin_id=package.manifest.name,
            contribution_id=item.contribution_id,
            kind=item.kind,
            owner=item.owner,
            reservation_fingerprint=item.fingerprint,
            source_descriptor_fingerprint=item.source_descriptor_fingerprint,
            source_kind=item.declaration_source.kind,
            payload=payloads[item.contribution_id].to_dict(),
        )
        for item in package.contribution_index.items
    }


def _candidate_map(
    selection: PluginSelection,
) -> dict[str, PluginContributionCandidate]:
    return {item.declaration.contribution_id: item for item in selection.candidates}


def _assert_candidate_payloads_are_inert(
    candidates: dict[str, PluginContributionCandidate],
) -> None:
    assert CommandPackDeclarationPayload.from_candidate(
        candidates["coding.standard"]
    ).to_dict() == _shadow_payloads().command_standard.to_dict()
    assert ResourceItemDeclarationPayload.from_candidate(
        candidates["prompt-standard"]
    ).to_dict() == _shadow_payloads().prompt_standard.to_dict()
    assert ResourceItemDeclarationPayload.from_candidate(
        candidates["skill-standard"]
    ).to_dict() == _shadow_payloads().skill_standard.to_dict()
    assert ToolPackDeclarationPayload.from_candidate(
        candidates["coding.builtin"]
    ).to_dict() == _shadow_payloads().tool_builtin.to_dict()
