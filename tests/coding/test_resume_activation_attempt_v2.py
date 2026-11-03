from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from loushang.coding.resume_activation_attempt import (
    CodingResumeRecoveryRequired,
    prepare_coding_activation_attempt_record,
    project_coding_activation_attempt_path,
    require_no_unsettled_coding_activation,
    validate_coding_activation_attempt_record,
)
from loushang.coding.resume_activation_attempt_v2 import (
    CodingActivationAttemptV2,
    CodingResumeEffectOwnerV1,
    prepare_coding_activation_attempt_v2_record,
    validate_coding_activation_attempt_v2_record,
)
from loushang.harness.transcript.types import ExtensionData


def _owner(**changes):
    return replace(
        CodingResumeEffectOwnerV1(
            "harness.plugin-execution",
            "a" * 64,
            "b" * 64,
            ("declaration",),
            ("import",),
        ),
        **changes,
    )


def _intent(**changes):
    return replace(
        CodingActivationAttemptV2(
            attempt_id="intent-1",
            request_id="request-1",
            session_id="session-1",
            original_leaf_id=None,
            ancestry_digest="a" * 64,
            plan_fingerprint="b" * 64,
            epoch_fingerprint="c" * 64,
            subject_digest="d" * 64,
            effect_owners=(_owner(),),
        ),
        **changes,
    )


def _record():
    return prepare_coding_activation_attempt_v2_record(
        _intent(), created_at=datetime(2026, 10, 13, tzinfo=timezone.utc)
    )


def test_v2_intent_roundtrips_with_exact_frozen_owner_and_parent_context():
    intent = _intent()
    assert validate_coding_activation_attempt_v2_record(_record()) == intent
    context = intent.parent_context(intent.effect_owners[0])
    assert context.intent_digest == intent.digest
    assert context.owner_id == "harness.plugin-execution"
    assert context.attempt_id == intent.attempt_id
    assert context.scope_digest == intent.effect_owners[0].scope_digest
    with pytest.raises(FrozenInstanceError):
        intent.effect_owners = ()
    with pytest.raises(ValueError, match="frozen owner"):
        intent.parent_context(_owner(contract_digest="e" * 64))
    assert (
        replace(intent, effect_owners=(_owner(contract_digest="e" * 64),)).digest
        != intent.digest
    )


def test_old_intent_reader_keeps_v2_inert_and_refuses_mutation():
    record = _record()
    assert (
        project_coding_activation_attempt_path(
            (record,), current_session_id="session-1"
        ).status
        == "unknown_version"
    )
    with pytest.raises(CodingResumeRecoveryRequired):
        require_no_unsettled_coding_activation(
            (record,), current_session_id="session-1"
        )
    with pytest.raises(ValueError):
        validate_coding_activation_attempt_record(record)
    with pytest.raises(ValueError):
        prepare_coding_activation_attempt_record(
            _intent(), created_at=datetime(2026, 10, 13, tzinfo=timezone.utc)
        )


@pytest.mark.parametrize(
    "mutation", ["extra", "future", "bool_version", "missing", "unknown_owner_field"]
)
def test_strict_v2_record_fields_and_version(mutation):
    record = _record()
    raw = _intent().to_data()
    if mutation == "extra":
        raw["approval"] = True
    elif mutation == "future":
        raw["version"] = 3
    elif mutation == "bool_version":
        raw["version"] = True
    elif mutation == "missing":
        del raw["effectOwners"]
    else:
        raw["effectOwners"][0]["approval"] = True
    changed = replace(
        record, payload=ExtensionData("coding.activation-attempt/v2", raw)
    )
    with pytest.raises(ValueError):
        validate_coding_activation_attempt_v2_record(changed)


@pytest.mark.parametrize(
    "owners",
    [
        (_owner(), _owner()),
        tuple(_owner(owner_id=f"owner-{i}") for i in range(9)),
        (_owner(owner_id="z"), _owner(owner_id="a")),
    ],
)
def test_v2_owner_membership_is_bounded_sorted_and_unique(owners):
    with pytest.raises(ValueError):
        _intent(effect_owners=owners)


def test_v2_intent_enforces_total_eight_kib_budget():
    codes = tuple(f"c{i:02d}" + "x" * 61 for i in range(16))
    owners = tuple(
        _owner(owner_id=f"owner-{i}", phases=codes, effect_classes=codes)
        for i in range(8)
    )
    with pytest.raises(ValueError, match="8 KiB"):
        _intent(effect_owners=owners)
