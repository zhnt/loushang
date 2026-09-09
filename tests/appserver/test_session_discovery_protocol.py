from __future__ import annotations

import json
from dataclasses import replace

import pytest

from loushang.appserver.client import AppClientV1, SessionDiscoveryClientV1
from loushang.appserver.protocol import (
    AppOperationV1,
    AppRequestV1,
    AppResponseV1,
    InvalidAppMessageError,
    SessionAvailabilityV1,
    SessionCompatibilityV1,
    SessionDiscoveryCandidateV1,
    SessionIdentityV1,
    SessionListResultV1,
    SessionListV1,
    SessionScopeV1,
    decode_request,
    decode_response,
    encode_request,
    encode_response,
)

FINGERPRINT = "a" * 64


def _candidate(number: int = 1) -> SessionDiscoveryCandidateV1:
    return SessionDiscoveryCandidateV1(
        SessionIdentityV1(
            "coding", "continuity", f"session-{number}", SessionScopeV1.CWD,
            FINGERPRINT,
        ),
        "历史会话",
        SessionCompatibilityV1.COMPATIBLE,
        SessionAvailabilityV1.AVAILABLE,
    )


def _page() -> SessionListResultV1:
    return SessionListResultV1(
        "coding", SessionScopeV1.CWD, FINGERPRINT, "snapshot-1",
        (_candidate(),), True,
    )


@pytest.mark.parametrize("scope", list(SessionScopeV1))
@pytest.mark.parametrize("continuation", [None, "opaque-continuation"])
def test_G17_DISCOVERY_request_round_trip(scope, continuation):
    value = SessionListV1("coding", scope, FINGERPRINT, 64, continuation)
    request = AppRequestV1("1", AppOperationV1.SESSIONS_LIST, value)
    assert decode_request(encode_request(request)) == request
    assert "path" not in json.loads(encode_request(request))["payload"]


def test_G17_DISCOVERY_page_round_trip_and_incomplete_final_page():
    complete = _page()
    partial = replace(
        complete,
        candidates=(replace(_candidate(), availability=SessionAvailabilityV1.UNVERIFIED),),
        complete=False, omitted_count=1, omitted_count_exact=False,
    )
    for value in (complete, partial, replace(complete, continuation="next-page")):
        response = AppResponseV1("1", value)
        assert decode_response(encode_response(response)) == response
    assert partial.continuation is None and not partial.complete


@pytest.mark.parametrize("limit", [0, 65, True, 1.0, "1"])
def test_G17_DISCOVERY_request_limit_is_exact_and_bounded(limit):
    with pytest.raises((ValueError, TypeError)):
        SessionListV1("coding", SessionScopeV1.CWD, FINGERPRINT, limit)


@pytest.mark.parametrize("cursor", ["", "../secret", "/tmp/secret", "x" * 513])
def test_G17_DISCOVERY_cursor_is_bounded_pathless_token(cursor):
    with pytest.raises((ValueError, TypeError)):
        SessionListV1("coding", SessionScopeV1.CWD, FINGERPRINT, continuation=cursor)


@pytest.mark.parametrize("changes", [
    {"candidates": (_candidate(),) * 65},
    {"candidates": (_candidate(), _candidate())},
    {"candidates": [_candidate()]},
    {"product_id": "work"},
    {"scope": SessionScopeV1.USER_HOME},
    {"scope_fingerprint": "b" * 64},
    {"complete": False},
    {"complete": 1},
    {"omitted_count": -1},
    {"omitted_count": True},
    {"omitted_count": 257},
    {"omitted_count_exact": 1},
    {"candidates": (), "continuation": "next"},
])
def test_G17_DISCOVERY_rejects_inconsistent_or_unbounded_page(changes):
    with pytest.raises((ValueError, TypeError)):
        replace(_page(), **changes)


def test_G17_DISCOVERY_incompatible_candidate_cannot_be_available():
    with pytest.raises(ValueError):
        replace(_candidate(), compatibility=SessionCompatibilityV1.UNSUPPORTED)
    assert replace(
        _candidate(), compatibility=SessionCompatibilityV1.UNSUPPORTED,
        availability=SessionAvailabilityV1.UNAVAILABLE,
    ).compatibility is SessionCompatibilityV1.UNSUPPORTED


def test_G17_DISCOVERY_largest_page_fits_single_wire_frame():
    page = replace(
        _page(), candidates=tuple(
            replace(_candidate(i), title="界" * 256) for i in range(64)
        ),
    )
    encoded = encode_response(AppResponseV1("1", page))
    assert len(encoded) < 1_048_576
    assert decode_response(encoded).result == page


@pytest.mark.parametrize("field,value", [
    ("limit", True), ("scope", "global"), ("continuation", "/tmp/session"),
    ("scopeFingerprint", "not-a-fingerprint"), ("path", "/private/secret"),
])
def test_G17_DISCOVERY_codec_rejects_malformed_request(field, value):
    raw = json.loads(encode_request(AppRequestV1(
        "1", AppOperationV1.SESSIONS_LIST,
        SessionListV1("coding", SessionScopeV1.CWD, FINGERPRINT),
    )))
    raw["payload"][field] = value
    with pytest.raises(InvalidAppMessageError):
        decode_request(json.dumps(raw).encode())


def test_G17_DISCOVERY_codec_rejects_oversize_and_cross_scope_candidate_page():
    raw = json.loads(encode_response(AppResponseV1("1", _page())))
    raw["result"]["candidates"] *= 65
    with pytest.raises(InvalidAppMessageError):
        decode_response(json.dumps(raw).encode())
    raw = json.loads(encode_response(AppResponseV1("1", _page())))
    raw["result"]["candidates"][0]["identity"]["scope"] = "user_home"
    with pytest.raises(InvalidAppMessageError):
        decode_response(json.dumps(raw).encode())


def test_G17_DISCOVERY_is_optional_not_a_new_legacy_client_requirement():
    assert "list_sessions" not in AppClientV1.__dict__
    assert "list_sessions" in SessionDiscoveryClientV1.__dict__
