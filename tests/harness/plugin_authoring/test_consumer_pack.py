"""Strict inert Tool/Command Catalog Consumer declaration contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityRequirement,
)
from loushang.harness.plugin_authoring.builder import PluginDeclarationBuilder
from loushang.harness.plugin_authoring.consumer_pack import (
    CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION,
    CommandPackDeclarationPayload,
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
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
class _PublishedConsumerPlugin:
    runtime: PluginRuntimeResolution
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contributions: tuple[PluginContributionReservation, ...]
    import_marker: Path | None


@dataclass(frozen=True, slots=True)
class _CurrentDecisionLookup:
    decision: PluginExecutionDecisionRecord

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult:
        return PluginExecutionDecisionCurrent(decision=self.decision)


def _requirement_document(
    capability: str,
    facets: list[str],
    *,
    binding: str = "direct",
    maximum: int = 1,
    minimum: int = 1,
    optional: bool = False,
) -> dict[str, object]:
    return {
        "binding": binding,
        "capability": capability,
        "compatibleContract": {"maximum": maximum, "minimum": minimum},
        "facets": facets,
        "optional": optional,
    }


def _tool_payload_document(
    *,
    owner_namespace: str = "tools.workspace",
) -> dict[str, object]:
    return {
        "catalogId": "harness.workspace.core",
        "catalogRevision": 1,
        "ownerNamespace": owner_namespace,
        "payloadVersion": CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION,
        "requirements": [
            _requirement_document(
                "harness.workspace",
                ["process.launch", "read"],
            )
        ],
        "tools": ["bash", "edit", "read"],
    }


def _command_payload_document() -> dict[str, object]:
    return {
        "catalogId": "harness.session.standard",
        "catalogRevision": 1,
        "commands": ["help", "model", "status"],
        "ownerNamespace": "commands.session",
        "payloadVersion": CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION,
        "requirements": [
            _requirement_document(
                "harness.session",
                ["transcript"],
                binding="stable_reference",
                maximum=2,
                optional=True,
            )
        ],
    }


@pytest.mark.parametrize(
    ("payload_type", "item_field", "document"),
    [
        (ToolPackDeclarationPayload, "tools", lambda: _tool_payload_document()),
        (
            CommandPackDeclarationPayload,
            "commands",
            lambda: _command_payload_document(),
        ),
    ],
)
def test_catalog_consumer_payloads_roundtrip_one_shared_typed_primitive(
    payload_type: type[ToolPackDeclarationPayload]
    | type[CommandPackDeclarationPayload],
    item_field: str,
    document: object,
) -> None:
    assert callable(document)
    expected = document()

    payload = payload_type.from_dict(expected)

    assert payload.to_dict() == expected
    assert payload_type.from_dict(payload.to_dict()) == payload
    assert payload.item_ids == tuple(expected[item_field])
    assert len(payload.fingerprint) == 64
    assert not hasattr(payload, "activation")
    assert not hasattr(payload, "registry")
    assert not hasattr(payload, "provider")
    assert not hasattr(payload, "factory")


def test_direct_catalog_consumer_payload_uses_the_shared_requirement_codec() -> None:
    with pytest.raises(PluginDeclarationCodecError) as caught:
        ToolPackDeclarationPayload(
            catalog_id="harness.workspace.core",
            catalog_revision=1,
            item_ids=("read",),
            owner_namespace="tools.workspace",
            requirements=(
                CapabilityRequirement(
                    capability="harness workspace",
                    facets=("read",),
                    compatible_contract=CapabilityContractRange.exact(1),
                ),
            ),
        )

    assert caught.value.code == "plugin_declaration_field_value_mismatch"


@pytest.mark.parametrize(
    ("payload_type", "document_factory", "mutation", "code"),
    [
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.pop("payloadVersion"),
            "unsupported_tool_pack_declaration_payload_version",
        ),
        (
            CommandPackDeclarationPayload,
            _command_payload_document,
            lambda value: value.update({"payloadVersion": 2}),
            "unsupported_command_pack_declaration_payload_version",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.update({"unknown": True}),
            "plugin_declaration_exact_field_mismatch",
        ),
        (
            CommandPackDeclarationPayload,
            _command_payload_document,
            lambda value: value.pop("catalogId"),
            "plugin_declaration_exact_field_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.update({"catalogRevision": True}),
            "plugin_declaration_field_type_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.update({"catalogRevision": 0}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.update({"catalogId": "workspace catalog"}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            CommandPackDeclarationPayload,
            _command_payload_document,
            lambda value: value.update({"ownerNamespace": "commands owner"}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.update({"tools": "read"}),
            "plugin_declaration_field_type_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.update({"tools": []}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.update({"tools": ["read", "bash"]}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            CommandPackDeclarationPayload,
            _command_payload_document,
            lambda value: value.update({"commands": ["help", "help"]}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            CommandPackDeclarationPayload,
            _command_payload_document,
            lambda value: value.update({"commands": ["bad command"]}),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.update({"tools": [lambda: None]}),
            "plugin_declaration_field_type_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value.update({"requirements": {}}),
            "plugin_declaration_field_type_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value["requirements"][0].update({"optional": 0}),
            "plugin_declaration_field_type_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value["requirements"][0].update(
                {"binding": "provider_lookup"}
            ),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value["requirements"][0].update(
                {"facets": ["read", "process.launch"]}
            ),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value["requirements"].append(
                deepcopy(value["requirements"][0])
            ),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value["requirements"].append(
                _requirement_document("a.capability", ["read"])
            ),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value["requirements"][0].update(
                {"capability": "harness workspace"}
            ),
            "plugin_declaration_field_value_mismatch",
        ),
        (
            ToolPackDeclarationPayload,
            _tool_payload_document,
            lambda value: value["requirements"][0].update(
                {"facets": ["bad facet"]}
            ),
            "plugin_declaration_field_value_mismatch",
        ),
    ],
)
def test_catalog_consumer_payloads_reject_noncanonical_documents(
    payload_type: type[ToolPackDeclarationPayload]
    | type[CommandPackDeclarationPayload],
    document_factory: object,
    mutation: object,
    code: str,
) -> None:
    assert callable(document_factory)
    assert callable(mutation)
    document = deepcopy(document_factory())
    mutation(document)

    with pytest.raises(PluginDeclarationCodecError) as caught:
        payload_type.from_dict(document)

    assert caught.value.code == code


@pytest.mark.parametrize("kind", ["tool_pack", "command_pack"])
def test_catalog_consumer_index_reservations_are_data_only_and_authority_free(
    kind: str,
) -> None:
    source = PluginDeclarationSource.document("declarations/packs.json")
    reservation = PluginContributionReservation(
        contribution_id=f"{kind}-standard",
        kind=kind,
        owner=f"{kind}.owner",
        declaration_source=source,
        contribution_execution_model="data_only",
        requested_authorities=(),
    )

    with pytest.raises(ValueError, match="data-only"):
        PluginContributionReservation(
            contribution_id=f"{kind}-executable",
            kind=kind,
            owner=f"{kind}.owner",
            declaration_source=source,
            contribution_execution_model="in_process",
            requested_authorities=(),
        )
    with pytest.raises(ValueError, match="authorities"):
        PluginContributionReservation(
            contribution_id=f"{kind}-authority",
            kind=kind,
            owner=f"{kind}.owner",
            declaration_source=source,
            contribution_execution_model="data_only",
            requested_authorities=("workspace.read",),
        )

    incompatible_model = reservation.to_dict()
    incompatible_model["contributionExecutionModel"] = "in_process"
    with pytest.raises(PluginDeclarationCodecError) as model_error:
        PluginContributionReservation.from_dict(incompatible_model)
    assert (
        model_error.value.code
        == "unsupported_plugin_contribution_execution_model"
    )

    direct_authority = reservation.to_dict()
    direct_authority["requestedAuthorities"] = ["workspace.read"]
    with pytest.raises(PluginDeclarationCodecError) as authority_error:
        PluginContributionReservation.from_dict(direct_authority)
    assert authority_error.value.code == "plugin_declaration_field_value_mismatch"


def test_document_catalog_consumers_reach_inert_sibling_candidates(
    tmp_path: Path,
) -> None:
    fixture = _publish_consumer_plugin(tmp_path, source_kind="document")
    try:
        result = PluginDeclarationHost().resolve(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=_plan(fixture),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )

        assert isinstance(result, PluginSelection)
        candidates = {item.declaration.kind: item for item in result.candidates}
        tool_payload = ToolPackDeclarationPayload.from_candidate(
            candidates["tool_pack"]
        )
        command_payload = CommandPackDeclarationPayload.from_candidate(
            candidates["command_pack"]
        )
        assert tool_payload.to_dict() == _tool_payload_document()
        assert command_payload.to_dict() == _command_payload_document()
        for candidate in candidates.values():
            assert not hasattr(candidate, "registration_scope")
            assert not hasattr(candidate, "catalog")
            assert not hasattr(candidate, "provider")
    finally:
        fixture.runtime.close()


def test_catalog_consumer_candidate_bridge_rejects_wrong_owner_and_kind(
    tmp_path: Path,
) -> None:
    fixture = _publish_consumer_plugin(
        tmp_path,
        source_kind="document",
        tool_owner_namespace="tools.forged",
    )
    try:
        result = PluginDeclarationHost().resolve(
            (fixture.package,),
            bindings=(fixture.binding,),
            plan=_plan(fixture),
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        assert isinstance(result, PluginSelection)
        candidates = {item.declaration.kind: item for item in result.candidates}

        with pytest.raises(PluginDeclarationCodecError) as owner_error:
            ToolPackDeclarationPayload.from_candidate(candidates["tool_pack"])
        assert owner_error.value.code == "plugin_declaration_cross_field_mismatch"

        with pytest.raises(PluginDeclarationCodecError) as kind_error:
            ToolPackDeclarationPayload.from_candidate(candidates["command_pack"])
        assert kind_error.value.code == "plugin_declaration_cross_field_mismatch"
    finally:
        fixture.runtime.close()


def test_builder_consumes_tool_and_command_siblings_without_definition_import(
    tmp_path: Path,
) -> None:
    fixture = _publish_consumer_plugin(tmp_path, source_kind="in_process")
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
                    decision_id="decision-catalog-consumers",
                    subject_digest=subject.digest,
                    policy_revision=plan.context.policy_revision,
                    disposition="approved",
                )
            ),
        )
        assert isinstance(outcome, PluginPreflightAcceptedOutcome)
        [group] = outcome.accepted.source_groups
        builder = PluginDeclarationBuilder(source_group=group)

        command_declaration = builder.add_command_pack(
            contribution_id="command-standard",
            payload=CommandPackDeclarationPayload.from_dict(
                _command_payload_document()
            ),
        )
        tool_declaration = builder.add_tool_pack(
            contribution_id="tool-builtin",
            payload=ToolPackDeclarationPayload.from_dict(_tool_payload_document()),
        )

        assert command_declaration == _declaration(
            fixture.contributions[0],
            _command_payload_document(),
        )
        assert tool_declaration == _declaration(
            fixture.contributions[1],
            _tool_payload_document(),
        )
        assert builder.build() == (command_declaration, tool_declaration)
        assert (
            CommandPackDeclarationPayload.from_reserved_declaration(
                command_declaration,
                source_group=group,
            ).to_dict()
            == _command_payload_document()
        )
        assert (
            ToolPackDeclarationPayload.from_reserved_declaration(
                tool_declaration,
                source_group=group,
            ).to_dict()
            == _tool_payload_document()
        )
        assert fixture.import_marker is not None
        assert fixture.import_marker.exists() is False
        resolver._abort(outcome.accepted)
    finally:
        fixture.runtime.close()


def _publish_consumer_plugin(
    tmp_path: Path,
    *,
    source_kind: str,
    tool_owner_namespace: str = "tools.workspace",
) -> _PublishedConsumerPlugin:
    source_root = tmp_path / f"catalog-consumers-{source_kind}"
    source_root.mkdir()
    import_marker: Path | None = None
    if source_kind == "document":
        declaration_source = PluginDeclarationSource.document(
            "declarations/packs.json"
        )
    else:
        import_marker = tmp_path / "consumer-definition-imported.txt"
        (source_root / "definition.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(import_marker)!r}).write_text('imported', encoding='utf-8')\n",
            encoding="utf-8",
        )
        declaration_source = PluginDeclarationSource.in_process(
            "definition.py:declare"
        )
    contributions = (
        PluginContributionReservation(
            contribution_id="command-standard",
            kind="command_pack",
            owner="commands.session",
            declaration_source=declaration_source,
            contribution_execution_model="data_only",
            requested_authorities=(),
        ),
        PluginContributionReservation(
            contribution_id="tool-builtin",
            kind="tool_pack",
            owner="tools.workspace",
            declaration_source=declaration_source,
            contribution_execution_model="data_only",
            requested_authorities=(),
        ),
    )
    if source_kind == "document":
        declarations = (
            _declaration(contributions[0], _command_payload_document()),
            _declaration(
                contributions[1],
                _tool_payload_document(owner_namespace=tool_owner_namespace),
            ),
        )
        declaration_path = source_root / "declarations" / "packs.json"
        declaration_path.parent.mkdir()
        declaration_path.write_bytes(
            PluginDeclarationDocumentCodec.encode_bytes(
                PluginDeclarationDocument(declarations=declarations)
            )
        )
    (source_root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "coding-base-consumers",
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
            install_root=tmp_path / f"installed-{source_kind}",
            plugin_revision_root=tmp_path / f"revisions-{source_kind}",
        ),
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    return _PublishedConsumerPlugin(
        runtime=runtime,
        package=package,
        binding=binding,
        contributions=package.contribution_index.items,
        import_marker=import_marker,
    )


def _declaration(
    contribution: PluginContributionReservation,
    payload: dict[str, object],
) -> PluginDeclaration:
    return PluginDeclaration(
        plugin_id="coding-base-consumers",
        contribution_id=contribution.contribution_id,
        kind=contribution.kind,
        owner=contribution.owner,
        reservation_fingerprint=contribution.fingerprint,
        source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
        source_kind=contribution.declaration_source.kind,
        payload=payload,
    )


def _plan(fixture: _PublishedConsumerPlugin) -> PluginSelectionPlanV2:
    plugin_id = fixture.package.manifest.name
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
        selected_contributions=tuple(
            PluginContributionRef(plugin_id, item.contribution_id)
            for item in fixture.contributions
        ),
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
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id=plugin_id,
                    contribution_id=item.contribution_id,
                    configuration={},
                )
                for item in fixture.contributions
            )
        ),
        allowed_authority_ceiling=(),
    )
