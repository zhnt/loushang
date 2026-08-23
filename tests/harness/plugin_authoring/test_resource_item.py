"""Strict Resource Item declaration and package-binding contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from loushang.harness.plugin_authoring.builder import PluginDeclarationBuilder
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.plugin_authoring.resource_item import (
    RESOURCE_ITEM_DECLARATION_PAYLOAD_VERSION,
    ResourceItemDeclarationPayload,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
    PluginDeclarationSource,
)
from loushang.harness.resources.plugins.selection import (
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


@dataclass(frozen=True, slots=True)
class _PublishedResourcePlugin:
    runtime: PluginRuntimeResolution
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contribution: PluginContributionReservation
    declaration: PluginDeclaration | None
    import_marker: Path | None


@dataclass(frozen=True, slots=True)
class _CurrentDecisionLookup:
    decision: PluginExecutionDecisionRecord

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult:
        return PluginExecutionDecisionCurrent(decision=self.decision)


@pytest.mark.parametrize(
    ("resource_kind", "locator", "locator_kind"),
    [
        ("skill", "skills/review/SKILL.md", "file"),
        ("skill", "skills/review", "directory"),
        ("prompt", "prompts/review.md", "file"),
        ("method", "methods/review.md", "file"),
        ("theme", "themes/review.json", "file"),
        ("asset", "assets/logo.svg", "file"),
        ("source", "sources/reference", "directory"),
    ],
)
def test_resource_item_subtypes_roundtrip_one_strict_payload_union(
    resource_kind: str,
    locator: str,
    locator_kind: str,
) -> None:
    document = _payload_document(
        resource_kind=resource_kind,
        locator=locator,
        locator_kind=locator_kind,
    )

    payload = ResourceItemDeclarationPayload.from_dict(document)

    assert payload.to_dict() == document
    assert ResourceItemDeclarationPayload.from_dict(payload.to_dict()) == payload
    assert len(payload.fingerprint) == 64
    assert not hasattr(payload, "package_digest")
    assert not hasattr(payload, "configuration_fingerprint")
    assert not hasattr(payload, "factory")


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: value.pop("payloadVersion"),
            "unsupported_resource_item_declaration_payload_version",
        ),
        (
            lambda value: value.update({"payloadVersion": 2}),
            "unsupported_resource_item_declaration_payload_version",
        ),
        (
            lambda value: value.update({"resourceKind": "tool"}),
            "unsupported_resource_item_kind",
        ),
        (
            lambda value: value.update({"resourceKind": 1}),
            "plugin_declaration_field_type_mismatch",
        ),
        (
            lambda value: value.update({"locatorKind": "callable"}),
            "unsupported_resource_item_locator_kind",
        ),
        (
            lambda value: value.update({"locatorKind": False}),
            "plugin_declaration_field_type_mismatch",
        ),
        (
            lambda value: value.update({"unknown": True}),
            "plugin_declaration_exact_field_mismatch",
        ),
        (
            lambda value: value.pop("schemaId"),
            "plugin_declaration_exact_field_mismatch",
        ),
        (
            lambda value: value.update({"locator": "../SKILL.md"}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            lambda value: value.update({"locator": "/skills/review/SKILL.md"}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            lambda value: value.update({"locator": r"skills\review\SKILL.md"}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            lambda value: value.update({"locator": "C:/skills/review/SKILL.md"}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            lambda value: value.update({"locator": lambda: None}),
            "plugin_declaration_field_type_mismatch",
        ),
        (
            lambda value: value.update({"schemaVersion": True}),
            "plugin_declaration_field_type_mismatch",
        ),
        (
            lambda value: value.update({"schemaVersion": 0}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            lambda value: value.update({"ownerNamespace": "resources skill"}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            lambda value: value.update({"schemaId": "resource skill"}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            lambda value: value.update({"mediaType": "Text/Markdown"}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            lambda value: value.update({"mediaType": "markdown"}),
            "plugin_declaration_field_value_mismatch",
        ),
    ],
)
def test_resource_item_payload_rejects_noncanonical_documents(
    mutation: object,
    code: str,
) -> None:
    document = deepcopy(_payload_document())
    assert callable(mutation)
    mutation(document)

    with pytest.raises(PluginDeclarationCodecError) as caught:
        ResourceItemDeclarationPayload.from_dict(document)

    assert caught.value.code == code


@pytest.mark.parametrize(
    ("resource_kind", "locator", "locator_kind"),
    [
        ("skill", "skills/review.md", "file"),
        ("prompt", "prompts/review.txt", "file"),
        ("prompt", "prompts/review", "directory"),
        ("method", "methods/review.txt", "file"),
        ("theme", "themes/review.yaml", "file"),
    ],
)
def test_resource_item_structured_subtypes_reject_wrong_locator_shape(
    resource_kind: str,
    locator: str,
    locator_kind: str,
) -> None:
    with pytest.raises(PluginDeclarationCodecError) as caught:
        ResourceItemDeclarationPayload.from_dict(
            _payload_document(
                resource_kind=resource_kind,
                locator=locator,
                locator_kind=locator_kind,
            )
        )

    assert caught.value.code == "plugin_declaration_field_value_mismatch"


def test_resource_item_reservation_is_data_only_and_authority_free() -> None:
    source = PluginDeclarationSource.document("declarations/resources.json")
    reservation = PluginContributionReservation(
        contribution_id="review-skill",
        kind="resource_item",
        owner="resources.skill",
        declaration_source=source,
        contribution_execution_model="data_only",
        requested_authorities=(),
    )

    assert reservation.kind == "resource_item"
    assert reservation.contribution_execution_model == "data_only"
    with pytest.raises(ValueError, match="data-only"):
        PluginContributionReservation(
            contribution_id="review-skill",
            kind="resource_item",
            owner="resources.skill",
            declaration_source=source,
            contribution_execution_model="in_process",
            requested_authorities=(),
        )
    with pytest.raises(ValueError, match="authorities"):
        PluginContributionReservation(
            contribution_id="review-skill",
            kind="resource_item",
            owner="resources.skill",
            declaration_source=source,
            contribution_execution_model="data_only",
            requested_authorities=("workspace.read",),
        )

    reservation_document = reservation.to_dict()
    reservation_document["contributionExecutionModel"] = "in_process"
    with pytest.raises(PluginDeclarationCodecError) as model_error:
        PluginContributionReservation.from_dict(reservation_document)
    assert (
        model_error.value.code
        == "unsupported_plugin_contribution_execution_model"
    )

    reservation_document = reservation.to_dict()
    reservation_document["requestedAuthorities"] = ["workspace.read"]
    with pytest.raises(PluginDeclarationCodecError) as authority_error:
        PluginContributionReservation.from_dict(reservation_document)
    assert authority_error.value.code == "plugin_declaration_field_value_mismatch"


def test_document_resource_reaches_inert_candidate_and_verified_locator(
    tmp_path: Path,
) -> None:
    fixture = _publish_resource_plugin(tmp_path, source_kind="document")
    try:
        result = PluginDeclarationHost().resolve(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=_plan(fixture),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )

        assert isinstance(result, PluginSelection)
        [candidate] = result.candidates
        assert isinstance(candidate, PluginContributionCandidate)
        assert candidate.declaration.kind == "resource_item"
        payload = ResourceItemDeclarationPayload.from_candidate(candidate)
        assert payload == ResourceItemDeclarationPayload.from_dict(
            _payload_document()
        )
        assert candidate.package.revision_handle.entry_kind(payload.locator) == "file"
        assert not hasattr(candidate, "resource_generation")
        assert not hasattr(candidate, "registration_scope")
    finally:
        fixture.runtime.close()


def test_resource_candidate_bridge_rejects_owner_namespace_mismatch(
    tmp_path: Path,
) -> None:
    fixture = _publish_resource_plugin(
        tmp_path,
        source_kind="document",
        payload_owner="resources.prompt",
    )
    try:
        result = PluginDeclarationHost().resolve(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=_plan(fixture),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        assert isinstance(result, PluginSelection)
        [candidate] = result.candidates

        with pytest.raises(PluginDeclarationCodecError) as caught:
            ResourceItemDeclarationPayload.from_candidate(candidate)

        assert caught.value.code == "plugin_declaration_cross_field_mismatch"
    finally:
        fixture.runtime.close()


def test_resource_candidate_bridge_rejects_verified_entry_kind_mismatch(
    tmp_path: Path,
) -> None:
    fixture = _publish_resource_plugin(
        tmp_path,
        source_kind="document",
        payload_locator_kind="directory",
    )
    try:
        result = PluginDeclarationHost().resolve(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=_plan(fixture),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        assert isinstance(result, PluginSelection)
        [candidate] = result.candidates

        with pytest.raises(PluginDeclarationCodecError) as caught:
            ResourceItemDeclarationPayload.from_candidate(candidate)

        assert caught.value.code == "plugin_declaration_cross_field_mismatch"
    finally:
        fixture.runtime.close()


def test_resource_candidate_bridge_rejects_source_descriptor_mismatch(
    tmp_path: Path,
) -> None:
    fixture = _publish_resource_plugin(tmp_path, source_kind="document")
    try:
        result = PluginDeclarationHost().resolve(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=_plan(fixture),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        assert isinstance(result, PluginSelection)
        [candidate] = result.candidates
        object.__setattr__(
            candidate,
            "declaration",
            replace(
                candidate.declaration,
                source_descriptor_fingerprint="0" * 64,
            ),
        )

        with pytest.raises(PluginDeclarationCodecError) as caught:
            ResourceItemDeclarationPayload.from_candidate(candidate)

        assert caught.value.code == "plugin_declaration_cross_field_mismatch"
    finally:
        fixture.runtime.close()


def test_resource_candidate_bridge_rejects_missing_verified_locator(
    tmp_path: Path,
) -> None:
    fixture = _publish_resource_plugin(
        tmp_path,
        source_kind="document",
        payload_locator="skills/missing/SKILL.md",
    )
    try:
        result = PluginDeclarationHost().resolve(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=_plan(fixture),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        assert isinstance(result, PluginSelection)
        [candidate] = result.candidates

        with pytest.raises(PluginDeclarationCodecError) as caught:
            ResourceItemDeclarationPayload.from_candidate(candidate)

        assert caught.value.code == "plugin_declaration_cross_field_mismatch"
    finally:
        fixture.runtime.close()


def test_resource_item_builder_consumes_in_process_reservation_without_import(
    tmp_path: Path,
) -> None:
    fixture = _publish_resource_plugin(tmp_path, source_kind="in_process")
    try:
        resolver = PluginSelectionResolver()
        plan = _plan(fixture)
        pending = resolver.preflight(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=plan,
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
        [subject] = pending.subjects
        outcome = resolver.preflight(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=plan,
            decision_lookup=_CurrentDecisionLookup(
                PluginExecutionDecisionRecord(
                    decision_id="decision-resource",
                    subject_digest=subject.digest,
                    policy_revision=plan.context.policy_revision,
                    disposition="approved",
                )
            ),
        )
        assert isinstance(outcome, PluginPreflightAcceptedOutcome)
        [group] = outcome.accepted.source_groups
        payload = ResourceItemDeclarationPayload.from_dict(_payload_document())
        builder = PluginDeclarationBuilder(source_group=group)

        declaration = builder.add_resource_item(
            contribution_id=fixture.contribution.contribution_id,
            payload=payload,
        )

        assert builder.build() == (declaration,)
        assert (
            ResourceItemDeclarationPayload.from_reserved_declaration(
                declaration,
                source_group=group,
            )
            == payload
        )
        assert fixture.import_marker is not None
        assert fixture.import_marker.exists() is False
        resolver._abort(outcome.accepted)
    finally:
        fixture.runtime.close()


def _publish_resource_plugin(
    tmp_path: Path,
    *,
    source_kind: str,
    payload_owner: str = "resources.skill",
    payload_locator: str = "skills/review/SKILL.md",
    payload_locator_kind: str = "file",
) -> _PublishedResourcePlugin:
    source_root = tmp_path / f"resource-{source_kind}-{payload_owner.replace('.', '-')}"
    (source_root / "skills" / "review").mkdir(parents=True)
    (source_root / "skills" / "review" / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review files\n---\n",
        encoding="utf-8",
    )
    import_marker: Path | None = None
    if source_kind == "document":
        declaration_source = PluginDeclarationSource.document(
            "declarations/resources.json"
        )
    else:
        import_marker = tmp_path / "resource-definition-imported.txt"
        (source_root / "definition.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(import_marker)!r}).write_text('imported', encoding='utf-8')\n",
            encoding="utf-8",
        )
        declaration_source = PluginDeclarationSource.in_process(
            "definition.py:declare"
        )
    contribution = PluginContributionReservation(
        contribution_id="review-skill",
        kind="resource_item",
        owner="resources.skill",
        declaration_source=declaration_source,
        contribution_execution_model="data_only",
        requested_authorities=(),
        configuration={},
    )
    declaration: PluginDeclaration | None = None
    if source_kind == "document":
        declaration = PluginDeclaration(
            plugin_id="review-resources",
            contribution_id=contribution.contribution_id,
            kind=contribution.kind,
            owner=contribution.owner,
            reservation_fingerprint=contribution.fingerprint,
            source_descriptor_fingerprint=(
                contribution.source_descriptor_fingerprint
            ),
            source_kind=contribution.declaration_source.kind,
            payload=_payload_document(
                locator=payload_locator,
                owner_namespace=payload_owner,
                locator_kind=payload_locator_kind,
            ),
        )
        declaration_path = source_root / "declarations" / "resources.json"
        declaration_path.parent.mkdir()
        declaration_path.write_bytes(
            PluginDeclarationDocumentCodec.encode_bytes(
                PluginDeclarationDocument(declarations=(declaration,))
            )
        )
    (source_root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "review-resources",
                "version": "1",
                "contributionIndex": {
                    "version": 2,
                    "items": [contribution.to_dict()],
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
            install_root=tmp_path / f"installed-{source_kind}",
            plugin_revision_root=tmp_path / f"revisions-{source_kind}",
        ),
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    [published_contribution] = package.contribution_index.items
    return _PublishedResourcePlugin(
        runtime=runtime,
        package=package,
        binding=binding,
        contribution=published_contribution,
        declaration=declaration,
        import_marker=import_marker,
    )


def _plan(fixture: _PublishedResourcePlugin) -> PluginSelectionPlanV2:
    plugin_id = fixture.package.manifest.name
    contribution_id = fixture.contribution.contribution_id
    return PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id=f"{plugin_id}@product",
                    plugin_id=plugin_id,
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=(plugin_id,),
        selected_contributions=(PluginContributionRef(plugin_id, contribution_id),),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id=plugin_id,
                package_source_identity=fixture.binding.source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="trust-1",
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=(
                PluginEffectiveConfigurationEntry(
                    plugin_id=plugin_id,
                    contribution_id=contribution_id,
                    configuration={},
                ),
            )
        ),
        allowed_authority_ceiling=(),
    )


def _payload_document(
    *,
    resource_kind: str = "skill",
    locator: str = "skills/review/SKILL.md",
    locator_kind: str = "file",
    owner_namespace: str = "resources.skill",
) -> dict[str, object]:
    return {
        "locator": locator,
        "locatorKind": locator_kind,
        "mediaType": "text/markdown",
        "ownerNamespace": owner_namespace,
        "payloadVersion": RESOURCE_ITEM_DECLARATION_PAYLOAD_VERSION,
        "resourceKind": resource_kind,
        "schemaId": f"loushang.resource.{resource_kind}",
        "schemaVersion": 1,
    }
