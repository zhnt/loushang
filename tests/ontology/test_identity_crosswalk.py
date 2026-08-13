from __future__ import annotations

import json
from dataclasses import replace
from uuid import UUID

import pytest

from loushang.ontology.identity import (
    IdentityCrosswalkSnapshot,
    IdentityResolution,
    IdentityResolutionError,
    IdentityResolutionStatus,
    IdentityResolver,
    SourceRecordIdentity,
    require_confirmed_identity,
)

ASSET_ID = UUID("00000000-0000-0000-0000-000000000201")
OTHER_ASSET_ID = UUID("00000000-0000-0000-0000-000000000202")
THIRD_ASSET_ID = UUID("00000000-0000-0000-0000-000000000203")


def _source(key: str, *, record_type: str = "asset") -> SourceRecordIdentity:
    return SourceRecordIdentity(
        source_instance_id="erp:province-alpha",
        binding_id="reference.erp.assets",
        record_type=record_type,
        source_record_key=key,
    )


def _confirmed(
    key: str,
    canonical_id: UUID = ASSET_ID,
) -> IdentityResolution:
    return IdentityResolution(
        source_identity=_source(key),
        status=IdentityResolutionStatus.CONFIRMED,
        canonical_object_id=canonical_id,
        resolution_ref=f"identity-decision:{key}",
    )


def _unresolved(key: str) -> IdentityResolution:
    return IdentityResolution(
        source_identity=_source(key),
        status=IdentityResolutionStatus.UNRESOLVED,
        resolution_ref=f"identity-review:{key}",
    )


def _conflict(key: str) -> IdentityResolution:
    return IdentityResolution(
        source_identity=_source(key),
        status=IdentityResolutionStatus.CONFLICT,
        candidate_object_ids=(OTHER_ASSET_ID, ASSET_ID),
        resolution_ref=f"identity-conflict:{key}",
    )


def _snapshot() -> IdentityCrosswalkSnapshot:
    return IdentityCrosswalkSnapshot(
        deployment_id="bureau-alpha",
        identity_namespace="urn:loushang:test:bureau-alpha",
        revision="identity-revision:17",
        entries=(_unresolved("A-2"), _confirmed("A-1"), _conflict("A-3")),
    )


def test_crosswalk_round_trip_is_deterministic_and_structurally_resolvable() -> None:
    snapshot = _snapshot()
    restored = IdentityCrosswalkSnapshot.from_json(snapshot.to_json())

    assert restored == snapshot
    assert isinstance(restored, IdentityResolver)
    assert [item.source_identity.source_record_key for item in restored.entries] == [
        "A-1",
        "A-2",
        "A-3",
    ]
    assert restored.entries[2].candidate_object_ids == (ASSET_ID, OTHER_ASSET_ID)
    assert restored.resolve_identity(_source("A-1")) == _confirmed("A-1")
    assert restored.resolve_identity(_source("missing")) is None
    assert len(restored.crosswalk_digest) == 64
    assert replace(
        restored,
        entries=tuple(reversed(restored.entries)),
    ).crosswalk_digest == restored.crosswalk_digest
    assert IdentityCrosswalkSnapshot.from_json(
        restored.to_json()
    ).crosswalk_digest == restored.crosswalk_digest


def test_confirmed_resolution_is_the_only_path_to_a_canonical_id() -> None:
    snapshot = _snapshot()

    assert require_confirmed_identity(snapshot, _source("A-1")) == ASSET_ID


@pytest.mark.parametrize(
    ("source_identity", "code"),
    [
        (_source("missing"), "identity_missing"),
        (_source("A-2"), "identity_unresolved"),
        (_source("A-3"), "identity_conflict"),
    ],
)
def test_non_confirmed_records_fail_without_candidate_selection(
    source_identity: SourceRecordIdentity,
    code: str,
) -> None:
    with pytest.raises(IdentityResolutionError) as exc_info:
        require_confirmed_identity(_snapshot(), source_identity)

    assert exc_info.value.code == code
    assert exc_info.value.source_identity == source_identity


@pytest.mark.parametrize(
    "resolution",
    [
        IdentityResolution(
            source_identity=_source("valid-unresolved"),
            status=IdentityResolutionStatus.UNRESOLVED,
        ),
        _confirmed("valid-confirmed"),
        _conflict("valid-conflict"),
    ],
)
def test_resolution_state_contracts_round_trip(
    resolution: IdentityResolution,
) -> None:
    assert IdentityResolution.from_dict(resolution.to_dict()) == resolution


def test_invalid_resolution_state_combinations_are_rejected() -> None:
    with pytest.raises(ValueError, match="requires canonical_object_id"):
        IdentityResolution(
            source_identity=_source("A-1"),
            status=IdentityResolutionStatus.CONFIRMED,
            resolution_ref="decision:1",
        )
    with pytest.raises(ValueError, match="requires resolution_ref"):
        IdentityResolution(
            source_identity=_source("A-1"),
            status=IdentityResolutionStatus.CONFIRMED,
            canonical_object_id=ASSET_ID,
        )
    with pytest.raises(ValueError, match="cannot contain"):
        IdentityResolution(
            source_identity=_source("A-1"),
            status=IdentityResolutionStatus.UNRESOLVED,
            candidate_object_ids=(ASSET_ID,),
        )
    with pytest.raises(ValueError, match="at least two candidates"):
        IdentityResolution(
            source_identity=_source("A-1"),
            status=IdentityResolutionStatus.CONFLICT,
            candidate_object_ids=(ASSET_ID,),
            resolution_ref="conflict:1",
        )
    with pytest.raises(ValueError, match="must not contain duplicates"):
        IdentityResolution(
            source_identity=_source("A-1"),
            status=IdentityResolutionStatus.CONFLICT,
            candidate_object_ids=(ASSET_ID, ASSET_ID),
            resolution_ref="conflict:1",
        )


def test_crosswalk_rejects_duplicate_source_records_and_unknown_json_fields() -> None:
    with pytest.raises(ValueError, match="duplicate source records"):
        replace(_snapshot(), entries=(_confirmed("A-1"), _confirmed("A-1")))

    document = json.loads(_snapshot().to_json())
    document["matching_algorithm"] = "forbidden"
    with pytest.raises(ValueError, match="fields do not match"):
        IdentityCrosswalkSnapshot.from_json(json.dumps(document))

    entry_document = json.loads(_snapshot().to_json())
    entry_document["entries"][0]["confidence"] = 0.9
    with pytest.raises(ValueError, match="identity resolution fields"):
        IdentityCrosswalkSnapshot.from_json(json.dumps(entry_document))


def test_resolver_cannot_return_a_resolution_for_another_source() -> None:
    requested = _source("A-1")

    class WrongResolver:
        def resolve_identity(
            self,
            _source_identity: SourceRecordIdentity,
        ) -> IdentityResolution:
            return _confirmed("another", THIRD_ASSET_ID)

    with pytest.raises(IdentityResolutionError) as exc_info:
        require_confirmed_identity(WrongResolver(), requested)

    assert exc_info.value.code == "identity_source_mismatch"


def test_source_identity_is_scoped_by_instance_binding_type_and_key() -> None:
    base = _source("A-1")
    variants = {
        replace(base, source_instance_id="erp:province-beta"),
        replace(base, binding_id="reference.erp.other-assets"),
        replace(base, record_type="owner"),
        replace(base, source_record_key="A-2"),
    }

    assert len(variants) == 4
    assert base not in variants
