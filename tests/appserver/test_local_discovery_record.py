from __future__ import annotations

import json
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import ModuleType

import pytest

from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordError,
    decode_connection_record,
    encode_connection_record,
)
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1

from .test_local_record import _record, _scopes


def test_G17_COMPAT_default_record_retains_exact_legacy_bytes():
    expected = {
        "schemaVersion": "loushang.appserver.local-record/v1",
        "profile": "local-detachable/v1",
        "protocolVersion": "loushang.app/v1",
        "endpoint": "workspace",
        "applicationId": "application",
        "productId": "coding",
        "instance": "c" * 32,
        "port": 12345,
        "key": (b"k" * 32).hex(),
        "scopes": [
            {"scope": "cwd", "fingerprint": "a" * 64},
            {"scope": "user_home", "fingerprint": "b" * 64},
        ],
        "capabilities": ["named_mux", "text_turns", "approvals"],
    }
    assert encode_connection_record(_record()) == json.dumps(
        expected,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


@pytest.mark.parametrize("enabled", [False, True])
def test_G17_COMPAT_record_binds_exact_optional_capability(enabled):
    record = replace(_record(), session_discovery=enabled)
    payload = encode_connection_record(record)
    assert decode_connection_record(payload) == record
    raw = json.loads(payload)
    assert raw["profile"] == "local-detachable/v1"
    assert "session_discovery" not in raw
    assert raw["capabilities"] == ["named_mux", "text_turns", "approvals"] + (
        ["session_discovery"] if enabled else []
    )
    assert record.semantic_profile is (
        AppConnectionProfileV1.LOCAL_DISCOVERY
        if enabled
        else AppConnectionProfileV1.LOCAL
    )
    changed = replace(record, session_discovery=not enabled)
    assert changed.authentication.key == record.authentication.key
    assert changed.authentication.record_digest != record.authentication.record_digest


@pytest.mark.parametrize(
    "capabilities",
    [
        [],
        None,
        "session_discovery",
        ["named_mux", "text_turns", "approvals", "unknown"],
        ["session_discovery", "named_mux", "text_turns", "approvals"],
        [
            "named_mux",
            "text_turns",
            "approvals",
            "session_discovery",
            "session_discovery",
        ],
        ["named_mux", "text_turns", "approvals", True],
    ],
)
def test_G17_COMPAT_record_rejects_non_closed_capabilities(capabilities):
    raw = json.loads(encode_connection_record(_record()))
    raw["capabilities"] = capabilities
    with pytest.raises(LocalRecordError):
        decode_connection_record(json.dumps(raw).encode())


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_G17_COMPAT_record_requires_exact_boolean_activation(value):
    with pytest.raises((TypeError, ValueError), match="invalid discovery activation"):
        replace(_record(), session_discovery=value)


def test_G17_COMPAT_publication_preserves_selected_capability(tmp_path):
    directory = LocalConnectionDirectoryV1(tmp_path / "connections")
    try:
        lease = directory.acquire("workspace")
        record = lease.publish(
            application_id="application",
            product_id="coding",
            port=12345,
            scopes=_scopes(),
            session_discovery=True,
        )
        assert directory.read("workspace") == record
        assert record.session_discovery
    finally:
        directory.close()


def test_G17_COMPAT_frozen_g16_decoder_accepts_default_and_rejects_discovery(
    monkeypatch,
):
    # Exact source from 7bf9e35f, blob b711e677cc9039117eda87995920db4f04d00b55.
    # This is baseline decoder evidence, not an old installed-client stack.
    path = Path(__file__).parent / "fixtures" / "g16_local_record_values.py.txt"
    source = path.read_bytes()
    assert (
        sha256(source).hexdigest()
        == "9023d485ed1066523ddf186afa28266deb54dac65b65a85d5ae5f53dffe279b1"
    )
    name = "loushang.appserver._g17_test_frozen_g16_record"
    module = ModuleType(name)
    module.__package__ = "loushang.appserver"
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(source, str(path), "exec"), vars(module))
    legacy = encode_connection_record(_record())
    decoded = module.decode_connection_record(legacy)
    assert module.encode_connection_record(decoded) == legacy
    with pytest.raises(module.LocalRecordError) as refused:
        module.decode_connection_record(
            encode_connection_record(replace(_record(), session_discovery=True))
        )
    assert refused.value.code is module.LocalRecordErrorCodeV1.CORRUPT
