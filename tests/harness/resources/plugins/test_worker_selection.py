from __future__ import annotations

import json
from pathlib import Path

from loushang.harness.plugin_authoring.coordinator import PluginDeclarationCoordinator
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import PluginResolutionAuthority
from loushang.harness.resources.plugins.declarations import (
    PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
    PluginContributionIndex,
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.engine import required_plugin_engine_features
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightAcceptedOutcome,
    PluginPreflightContextV1,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import PluginSource


def test_worker_document_survives_publication_preflight_and_selection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source/review-pack"
    declaration_path = source / "declarations/providers.json"
    executable = source / "worker/query-worker"
    declaration_path.parent.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o500)
    item = {
        "configuration": {},
        "contributionExecutionModel": "local_worker",
        "declarationSource": {
            "kind": "document",
            "locator": "declarations/providers.json",
            "mediaType": "application/vnd.loushang.plugin-declarations+json",
            "schemaId": "loushang.plugin-declaration-document",
            "schemaVersion": 2,
            "sourceVersion": 1,
        },
        "id": "review-provider",
        "kind": "capability_provider",
        "owner": "coding.lsp",
        "requestedAuthorities": [],
        "required": True,
        "workerConfiguration": {
            "configurationVersion": 1,
            "entrypoint": "worker/query-worker",
            "protocol": "capability.query",
            "protocolVersion": 1,
        },
    }
    contribution = PluginContributionReservation.from_dict(
        item,
        index_version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    )
    index = PluginContributionIndex(
        items=(contribution,),
        version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    )
    declaration = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id=contribution.contribution_id,
        kind=contribution.kind,
        owner=contribution.owner,
        reservation_fingerprint=contribution.fingerprint,
        source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
        source_kind="document",
        payload={"querySchema": "loushang.capability-query/read-only/v1"},
        ir_version=PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
        contribution_execution_model="local_worker",
        worker_configuration=contribution.worker_configuration,
    )
    declaration_path.write_bytes(
        PluginDeclarationDocumentCodec.encode_bytes(
            PluginDeclarationDocument(
                declarations=(declaration,),
                document_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
            )
        )
    )
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "contributionIndex": index.to_dict(),
                "engine": {
                    "apiVersion": 1,
                    "declarationIrVersion": 3,
                    "requiredFeatures": sorted(required_plugin_engine_features(index)),
                },
                "manifestVersion": 1,
                "name": "review-pack",
                "packageRoot": ".",
                "version": "1",
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=source))
    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    runtime = authority.publish_runtime((inspection,), binding_store=materializer)
    try:
        [package] = runtime.packages
        [binding] = runtime.bindings
        context = PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id="review-pack@product",
                    plugin_id="review-pack",
                    revision=1,
                ),
            ),
        )
        plan = PluginSelectionPlanV2(
            context=context,
            selected_plugin_ids=("review-pack",),
            selected_contributions=(
                PluginContributionRef("review-pack", "review-provider"),
            ),
            source_trust_snapshots=(
                PluginSourceTrustSnapshotV1(
                    plugin_id="review-pack",
                    package_source_identity=binding.source_identity,
                    source_trust_class="host-equivalent-local",
                    source_trust_policy_revision="trust-1",
                    trusted=True,
                ),
            ),
            effective_configuration_set=PluginEffectiveConfigurationSetV1(
                entries=(
                    PluginEffectiveConfigurationEntry(
                        plugin_id="review-pack",
                        contribution_id="review-provider",
                        configuration={},
                    ),
                )
            ),
            allowed_authority_ceiling=(),
        )
        resolver = PluginSelectionResolver()
        outcome = resolver.preflight(
            (package,),
            bindings=(binding,),
            plan=plan,
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        assert isinstance(outcome, PluginPreflightAcceptedOutcome)

        selection = PluginDeclarationCoordinator(resolver).finalize(outcome.accepted)

        [candidate] = selection.candidates
        assert candidate.declaration == declaration
        assert candidate.declaration.contribution_execution_model == "local_worker"
        assert candidate.evidence.document_schema_version == 2
    finally:
        runtime.close()
