"""Compare closed record decoding and explicit selection with Python reference."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

from loushang.appserver.local_record import (
    LocalRecordError,
    decode_connection_record,
    encode_connection_record,
)

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "gui/contracts/rust"


def vectors():
    base = json.loads((ROOT / "gui/contracts/fixtures/local-record.json").read_bytes())
    endpoint, profile = "workspace", "local-detachable-execution/v1"
    cases = []

    def add(name, value, valid, selected=endpoint, expected_profile=profile):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        cases.append((name, raw, valid, selected, expected_profile))

    add("execution", base, True)
    caps = ["named_mux", "text_turns", "approvals"]
    for suffix, tail in (
        ("", []),
        ("-discovery", ["session_discovery"]),
        ("-discovery-execution", ["session_discovery", "session_execution"]),
    ):
        value = copy.deepcopy(base)
        value["capabilities"] = caps + tail
        add(
            f"profile{suffix}",
            value,
            True,
            expected_profile=f"local-detachable{suffix}/v1",
        )
    mutations = [
        ("unknown", "extra", "x", False),
        ("schema", "schemaVersion", "other", False),
        ("transport-profile", "profile", profile, False),
        ("protocol", "protocolVersion", "other", False),
        ("port-zero", "port", 0, False),
        ("port-max", "port", 65535, True),
        ("port-overflow", "port", 65536, False),
        ("port-bool", "port", True, False),
        ("port-float", "port", 1.0, False),
        ("port-string", "port", "12345", False),
        ("key-upper", "key", "AB" * 32, False),
        ("key-short", "key", "a", False),
        ("key-null", "key", None, False),
        ("key-changed", "key", "ff" * 32, True),
        ("instance-upper", "instance", "A" * 32, False),
        ("application-upper", "applicationId", "App", False),
        ("application-max", "applicationId", "a" * 128, True),
        ("application-long", "applicationId", "a" * 129, False),
        ("product-unicode", "productId", "产品", False),
        ("endpoint-traversal", "endpoint", "../workspace", False),
        ("caps-reordered", "capabilities", list(reversed(base["capabilities"])), False),
        ("caps-extra", "capabilities", base["capabilities"] + ["unknown"], False),
        ("caps-duplicate", "capabilities", caps + ["approvals"], False),
        ("caps-missing", "capabilities", [], False),
        ("scopes-empty", "scopes", [], False),
        ("scopes-duplicate", "scopes", base["scopes"] * 2, False),
        (
            "scope-unknown",
            "scopes",
            [{"scope": "other", "fingerprint": "a" * 64}],
            False,
        ),
        ("scope-extra", "scopes", [{**base["scopes"][0], "extra": "x"}], False),
        ("scope-null", "scopes", [{"scope": "cwd", "fingerprint": None}], False),
    ]
    for name, field, mutation, valid in mutations:
        value = copy.deepcopy(base)
        value[field] = mutation
        add(name, value, valid)
    for field in base:
        value = copy.deepcopy(base)
        del value[field]
        add(f"missing-{field}", value, False)
    value = copy.deepcopy(base)
    value["scopes"].append({"scope": "user_home", "fingerprint": "c" * 64})
    add("two-scopes", value, True)
    value["scopes"].reverse()
    add("scope-order-preserved", value, True)
    raw = json.dumps(base).encode()
    add("duplicate-field", raw[:-1] + b',"port":12345}', False)
    add(
        "duplicate-scope-field",
        raw.replace(b'"scope": "cwd"', b'"scope":"cwd","scope":"cwd"'),
        False,
    )
    add("invalid-utf8", b"\xff", False)
    add("record-limit", raw + b" " * (8192 - len(raw)), True)
    add("record-over-limit", raw + b" " * (8193 - len(raw)), False)
    add("endpoint-mismatch", base, False, selected="other")
    add("profile-mismatch", base, False, expected_profile="local-detachable/v1")
    return cases


def run() -> None:
    cases = vectors()
    inputs, expected = [], []
    for name, raw, valid, endpoint, profile in cases:
        result = None
        try:
            record = decode_connection_record(raw)
            if record.endpoint == endpoint and record.semantic_profile.value == profile:
                public = json.loads(encode_connection_record(record))
                del public["key"]
                result = {
                    "public": public,
                    "semanticProfile": profile,
                    "recordDigest": record.authentication.record_digest.hex(),
                    "filename": hashlib.sha256(endpoint.encode()).hexdigest() + ".json",
                }
        except LocalRecordError:
            pass
        assert (result is not None) == valid, f"Python reference changed: {name}"
        expected.append(result)
        inputs.append(
            json.dumps({"payload": list(raw), "endpoint": endpoint, "profile": profile})
        )
    exe = (
        CRATE
        / "target/debug"
        / ("record_value_probe.exe" if os.name == "nt" else "record_value_probe")
    )
    process = subprocess.run(
        [str(exe)],
        input="\n".join(inputs) + "\n",
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=15,
    )
    assert process.returncode == 0 and not process.stderr, "Record probe failed"
    actual = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(actual) == len(expected)
    for case, want, got in zip(cases, expected, actual, strict=True):
        assert got == want, f"Record parity mismatch: {case[0]}"
    index = {case[0]: result for case, result in zip(cases, actual, strict=True)}
    assert index["execution"]["recordDigest"] == index["key-changed"]["recordDigest"]
    assert (
        index["two-scopes"]["recordDigest"]
        != index["scope-order-preserved"]["recordDigest"]
    )
    print(
        f"Record values: {len(cases)} cases passed ({sum(value is not None for value in actual)} accepted)"
    )


if __name__ == "__main__":
    cargo = Path.home() / ".cargo/bin" / ("cargo.exe" if os.name == "nt" else "cargo")
    subprocess.run(
        [
            str(cargo),
            "+1.98.1",
            "build",
            "--locked",
            "--offline",
            "--manifest-path",
            str(CRATE / "Cargo.toml"),
            "--bin",
            "record_value_probe",
        ],
        check=True,
        cwd=ROOT,
    )
    run()
