from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import (
    PLUGIN_CONTRIBUTION_INDEX_VERSION,
    PLUGIN_DECLARATION_DOCUMENT_VERSION,
    PLUGIN_DECLARATION_IR_VERSION,
    PLUGIN_LOCAL_WORKER_CONFIGURATION_VERSION,
    PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
    PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
    PluginContributionIndex,
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
    PluginDeclarationSource,
    PluginLocalWorkerConfiguration,
)
from loushang.harness.resources.plugins.engine import (
    inspect_plugin_engine_contract,
    required_plugin_engine_features,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.worker import WorkerRuntimeBindingV1


def _worker_configuration() -> PluginLocalWorkerConfiguration:
    return PluginLocalWorkerConfiguration(
        entrypoint="worker/bin/query-worker",
        protocol="capability.query",
        protocol_version=1,
    )


def _worker_reservation() -> PluginContributionReservation:
    return PluginContributionReservation(
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        declaration_source=PluginDeclarationSource.document(
            "declarations/providers.json",
            schema_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
        ),
        contribution_execution_model="local_worker",
        requested_authorities=(),
        worker_configuration=_worker_configuration(),
        index_version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    )


def test_worker_index_v3_is_additive_and_v2_bytes_retain_exact_meaning() -> None:
    worker = _worker_reservation()
    worker_index = PluginContributionIndex(
        items=(worker,),
        version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    )

    assert PLUGIN_CONTRIBUTION_INDEX_VERSION == 2
    assert PLUGIN_DECLARATION_IR_VERSION == 2
    assert PLUGIN_DECLARATION_DOCUMENT_VERSION == 1
    assert PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION == 3
    assert PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION == 3
    assert PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION == 2
    assert PLUGIN_LOCAL_WORKER_CONFIGURATION_VERSION == 1
    assert worker_index.to_dict() == {
        "items": [
            {
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
                    "entrypoint": "worker/bin/query-worker",
                    "protocol": "capability.query",
                    "protocolVersion": 1,
                },
            }
        ],
        "version": 3,
    }
    assert PluginContributionIndex.from_dict(worker_index.to_dict()) == worker_index

    legacy_source = PluginDeclarationSource.in_process("provider.py:declare")
    legacy = PluginContributionReservation(
        contribution_id="legacy-provider",
        kind="capability_provider",
        owner="coding.lsp",
        declaration_source=legacy_source,
        contribution_execution_model="in_process",
        requested_authorities=(),
    )
    legacy_index = PluginContributionIndex(items=(legacy,))
    assert legacy_index.version == 2
    assert "workerConfiguration" not in legacy.to_dict()
    assert PluginContributionIndex.from_dict(legacy_index.to_dict()) == legacy_index

    with pytest.raises(ValueError, match="requires a local Worker"):
        PluginContributionIndex(
            items=(),
            version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
        )
    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginContributionIndex.from_dict({"items": [], "version": 3})
    assert caught.value.code == "plugin_local_worker_contribution_missing"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda value: value["items"][0].__setitem__(
                "contributionExecutionModel", "local_worker"
            ),
            "unsupported_plugin_contribution_execution_model",
        ),
        (
            lambda value: value["items"][0].pop("workerConfiguration"),
            "plugin_declaration_exact_field_mismatch",
        ),
        (
            lambda value: value["items"][0]["workerConfiguration"].__setitem__(
                "configurationVersion", 2
            ),
            "unsupported_plugin_local_worker_configuration_version",
        ),
        (
            lambda value: value["items"][0]["workerConfiguration"].__setitem__(
                "ambientEnvironment", ["PATH"]
            ),
            "plugin_declaration_exact_field_mismatch",
        ),
    ],
)
def test_worker_index_rejects_downgrade_partial_and_unknown_records(
    mutate: object,
    code: str,
) -> None:
    worker_index = PluginContributionIndex(
        items=(_worker_reservation(),),
        version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    ).to_dict()
    candidate = copy.deepcopy(worker_index)
    if code == "unsupported_plugin_contribution_execution_model":
        candidate["version"] = 2
        candidate["items"][0].pop("workerConfiguration")
    mutate(candidate)  # type: ignore[operator]

    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginContributionIndex.from_dict(candidate)

    assert caught.value.code == code


def test_worker_declaration_requires_ir_v3_document_v2_and_exact_topology() -> None:
    reservation = _worker_reservation()
    declaration = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id=reservation.contribution_id,
        kind=reservation.kind,
        owner=reservation.owner,
        reservation_fingerprint=reservation.fingerprint,
        source_descriptor_fingerprint=reservation.source_descriptor_fingerprint,
        source_kind="document",
        payload={"querySchema": "loushang.capability-query/read-only/v1"},
        ir_version=PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
        contribution_execution_model="local_worker",
        worker_configuration=reservation.worker_configuration,
    )
    document = PluginDeclarationDocument(
        declarations=(declaration,),
        document_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
    )
    encoded = PluginDeclarationDocumentCodec.encode_bytes(document)

    assert StrictPluginJsonCodec.decode_bytes(encoded) == document.to_dict()
    assert PluginDeclarationDocumentCodec.decode_bytes(encoded) == document

    downgraded = declaration.to_dict()
    downgraded["irVersion"] = 2
    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginDeclaration.from_dict(downgraded)
    assert caught.value.code == "plugin_declaration_exact_field_mismatch"

    with pytest.raises(ValueError, match="must match"):
        PluginDeclarationDocument(declarations=(declaration,))


def test_worker_topology_never_carries_ambient_authority_or_unversioned_config() -> (
    None
):
    common = {
        "contribution_id": "review-provider",
        "kind": "capability_provider",
        "owner": "coding.lsp",
        "declaration_source": PluginDeclarationSource.document(
            "declarations/providers.json",
            schema_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
        ),
        "contribution_execution_model": "local_worker",
        "worker_configuration": _worker_configuration(),
        "index_version": PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    }
    with pytest.raises(ValueError, match="ambient"):
        PluginContributionReservation(
            **common,
            requested_authorities=("workspace.read",),
        )
    with pytest.raises(ValueError, match="versioned Worker field"):
        PluginContributionReservation(
            **common,
            requested_authorities=(),
            configuration={"entrypoint": "worker.py"},
        )
    with pytest.raises(ValueError, match="document v2"):
        PluginContributionReservation(
            **{
                **common,
                "declaration_source": PluginDeclarationSource.document(
                    "declarations/providers.json"
                ),
            },
            requested_authorities=(),
        )


def test_index_document_versions_and_v3_execution_topology_are_exact() -> None:
    with pytest.raises(ValueError, match="configuration version"):
        PluginLocalWorkerConfiguration(
            entrypoint="worker",
            protocol="capability.query",
            protocol_version=1,
            configuration_version=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="bounded identifier"):
        PluginLocalWorkerConfiguration(
            entrypoint="worker",
            protocol="a" * 129,
            protocol_version=1,
        )
    with pytest.raises(ValueError, match="index v2 requires declaration document v1"):
        PluginContributionReservation(
            contribution_id="legacy-data",
            kind="resource_item",
            owner="coding.resources",
            declaration_source=PluginDeclarationSource.document(
                "declarations/resources.json",
                schema_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
            ),
            contribution_execution_model="data_only",
            requested_authorities=(),
        )

    with pytest.raises(ValueError, match="must be data-only"):
        PluginDeclaration(
            plugin_id="review-pack",
            contribution_id="bad-resource",
            kind="resource_item",
            owner="coding.resources",
            reservation_fingerprint="a" * 64,
            source_descriptor_fingerprint="b" * 64,
            source_kind="document",
            payload={},
            ir_version=PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
            contribution_execution_model="in_process",
        )


def test_worker_engine_negotiation_requires_matching_v3_and_exact_feature() -> None:
    index = PluginContributionIndex(
        items=(_worker_reservation(),),
        version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    )
    features = required_plugin_engine_features(index)
    payload = {
        "contributionIndex": index.to_dict(),
        "engine": {
            "apiVersion": 1,
            "declarationIrVersion": 3,
            "requiredFeatures": sorted(features),
        },
        "manifestVersion": 1,
        "name": "review-pack",
        "packageRoot": ".",
        "version": "1",
    }

    contract, diagnostics = inspect_plugin_engine_contract(
        payload,
        contribution_index=index,
    )
    assert diagnostics == ()
    assert contract is not None
    assert contract.declaration_ir_version == 3
    assert "local-worker-v1" in contract.required_features

    mismatched = copy.deepcopy(payload)
    mismatched["engine"]["declarationIrVersion"] = 2
    contract, diagnostics = inspect_plugin_engine_contract(
        mismatched,
        contribution_index=index,
    )
    assert contract is None
    assert {item.code for item in diagnostics} == {
        "plugin_engine_declaration_index_version_mismatch"
    }

    missing = copy.deepcopy(payload)
    missing["engine"]["requiredFeatures"].remove("local-worker-v1")
    contract, diagnostics = inspect_plugin_engine_contract(
        missing,
        contribution_index=index,
    )
    assert contract is None
    assert {item.code for item in diagnostics} == {
        "plugin_engine_feature_declaration_incomplete"
    }


def test_worker_manifest_engine_declaration_and_runtime_binding_join_exactly(
    tmp_path: Path,
) -> None:
    reservation = _worker_reservation()
    index = PluginContributionIndex(
        items=(reservation,),
        version=PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    )
    declaration = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id=reservation.contribution_id,
        kind=reservation.kind,
        owner=reservation.owner,
        reservation_fingerprint=reservation.fingerprint,
        source_descriptor_fingerprint=reservation.source_descriptor_fingerprint,
        source_kind="document",
        payload={"querySchema": "loushang.capability-query/read-only/v1"},
        ir_version=PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION,
        contribution_execution_model="local_worker",
        worker_configuration=reservation.worker_configuration,
    )
    document = PluginDeclarationDocument(
        declarations=(declaration,),
        document_version=PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
    )
    declaration_path = tmp_path / "declarations/providers.json"
    declaration_path.parent.mkdir()
    declaration_path.write_bytes(PluginDeclarationDocumentCodec.encode_bytes(document))
    executable = tmp_path / "worker/bin/query-worker"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o500)
    (tmp_path / "plugin.json").write_text(
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

    resolved = PluginManifestParser().parse(tmp_path)
    [actual_reservation] = resolved.contribution_index.items
    actual_document = PluginDeclarationDocumentCodec.decode_bytes(
        declaration_path.read_bytes()
    )
    assert actual_reservation.worker_configuration is not None
    runtime = WorkerRuntimeBindingV1.capture(
        package_root=resolved.package_root,
        configuration=actual_reservation.worker_configuration,
    )

    assert actual_reservation.fingerprint == declaration.reservation_fingerprint
    assert actual_document == document
    assert runtime.worker_configuration_fingerprint == (
        actual_reservation.worker_configuration.fingerprint
    )
    assert runtime.executable == executable
