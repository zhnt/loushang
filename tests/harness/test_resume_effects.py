from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from loushang.harness.resume_effects import (
    RESUME_EFFECT_PARENT_CONTEXT_MAX_BYTES,
    ResumeEffectParentContextV1,
)


def _context():
    return ResumeEffectParentContextV1(
        product_id="coding",
        session_id="session-1",
        attempt_id="intent-1",
        request_id="request-1",
        intent_digest="a" * 64,
        owner_id="harness.plugin-execution",
        scope_digest="b" * 64,
        contract_digest="c" * 64,
    )


def test_context_is_immutable_and_round_trip_keeps_exact_intent_and_owner_identity():
    context = _context()
    wire = context.to_dict()
    decoded = ResumeEffectParentContextV1.from_dict(dict(reversed(tuple(wire.items()))))
    assert decoded == context
    assert decoded.canonical_bytes() == context.canonical_bytes()
    assert decoded.digest == context.digest
    wire["intentDigest"] = "d" * 64
    assert decoded.intent_digest == "a" * 64
    assert decoded.digest != ResumeEffectParentContextV1.from_dict(wire).digest
    assert len(context.canonical_bytes()) <= RESUME_EFFECT_PARENT_CONTEXT_MAX_BYTES
    with pytest.raises(FrozenInstanceError):
        context.intent_digest = "d" * 64


@pytest.mark.parametrize(
    "field",
    [
        "product_id",
        "session_id",
        "attempt_id",
        "request_id",
        "intent_digest",
        "owner_id",
        "scope_digest",
        "contract_digest",
    ],
)
def test_context_digest_changes_for_each_exact_owner_or_parent_identity(field):
    context = _context()
    changed = replace(
        context, **{field: "d" * 64 if field.endswith("digest") else "another"}
    )
    assert changed.digest != context.digest


@pytest.mark.parametrize(
    "mutate",
    [
        lambda doc: {**doc, "contextVersion": True},
        lambda doc: {**doc, "contextVersion": 2},
        lambda doc: {**doc, "contextVersion": "1"},
        lambda doc: {**doc, "scopeDigest": "B" * 64},
        lambda doc: {**doc, "intentDigest": "not-a-digest"},
        lambda doc: {**doc, "sessionId": "x" * 129},
        lambda doc: {**doc, "sessionId": "../../history"},
        lambda doc: {**doc, "ownerId": []},
        lambda doc: {**doc, "credential": "grant"},
        lambda doc: {key: value for key, value in doc.items() if key != "requestId"},
    ],
)
def test_context_rejects_unknown_or_unbounded_wire_without_coercion(mutate):
    with pytest.raises(ValueError):
        ResumeEffectParentContextV1.from_dict(mutate(_context().to_dict()))
