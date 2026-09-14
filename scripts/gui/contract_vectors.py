"""Offline C1 submit/failure/hello vectors checked by the Python reference codec."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from loushang.appserver.execution.codec import (
    decode_call,
    decode_execution_hello,
    decode_response,
    encode_call,
    encode_response,
    execution_hello,
)
from loushang.appserver.execution.model import ExecutionErrorCodeV1
from loushang.appserver.protocol import InvalidAppMessageError


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    sample = json.loads(
        (root / "tests/appserver/fixtures/execution_v1.json").read_text(
            encoding="utf-8"
        )
    )["submit"]
    cases: list[tuple[str, str, str, bool]] = []

    def add(name: str, value: dict, valid: bool = True, kind: str = "submit") -> None:
        cases.append((name, kind, json.dumps(value, ensure_ascii=False), valid))

    add("official-submit", sample)
    for size in [262_144, 262_145]:
        value = copy.deepcopy(sample)
        value["payload"]["text"] = "x" * size
        add(f"text-boundary-{size}", value, size == 262_144)
    for generation in [1, 2**53 - 1, 2**53 + 1, 2**64 - 1, 2**100 + 1]:
        value = copy.deepcopy(sample)
        value["payload"]["control"]["controllerGeneration"] = generation
        add(f"generation-{generation}", value)
    for generation in [0, -1, True, 1.5, "9007199254740993", None]:
        value = copy.deepcopy(sample)
        value["payload"]["control"]["controllerGeneration"] = generation
        add(f"invalid-generation-{generation}", value, False)
    for name in [
        "version",
        "missing",
        "extra",
        "operation",
        "identifier",
        "empty-text",
    ]:
        value = copy.deepcopy(sample)
        if name == "version":
            value["protocolVersion"] = "loushang.execution/v2"
        elif name == "missing":
            del value["payload"]["control"]["memberId"]
        elif name == "extra":
            value["payload"]["unexpected"] = True
        elif name == "operation":
            value["operation"] = "execution/unknown"
        elif name == "identifier":
            value["requestId"] = "invalid id"
        else:
            value["payload"]["text"] = ""
        add(name, value, False)
    raw = json.dumps(sample)
    cases.append(
        (
            "duplicate-field",
            "submit",
            raw.replace('"requestId": "1"', '"requestId": "1", "requestId": "2"'),
            False,
        )
    )
    cases.append(
        (
            "exponent-generation",
            "submit",
            raw.replace('"controllerGeneration": 1', '"controllerGeneration": 1e0'),
            False,
        )
    )
    for code in [item.value for item in ExecutionErrorCodeV1] + ["unknown_error"]:
        add(
            f"failure-{code}",
            {
                "protocolVersion": "loushang.execution/v1",
                "requestId": "1",
                "resultType": "failure",
                "result": {"code": code},
            },
            code != "unknown_error",
            "failure",
        )
    for name in ["version", "missing", "extra", "null"]:
        value = {
            "protocolVersion": "loushang.execution/v1",
            "requestId": "1",
            "resultType": "failure",
            "result": {"code": "execution_busy"},
        }
        if name == "version":
            value["protocolVersion"] = "loushang.execution/v2"
        elif name == "missing":
            del value["result"]["code"]
        elif name == "extra":
            value["result"]["message"] = "unrecognized"
        else:
            value["result"] = None
        add(f"failure-{name}", value, False, "failure")
    for name, kind, wire, valid in cases:
        try:
            decoded = (
                decode_call(wire.encode())
                if kind == "submit"
                else decode_response(wire.encode())
            )
            encoded = (
                encode_call(decoded) if kind == "submit" else encode_response(decoded)
            )
            expected = json.loads(encoded)
            if kind == "submit":
                expected["payload"]["control"]["controllerGeneration"] = str(
                    decoded.control.controller_generation
                )
            accepted = True
        except InvalidAppMessageError:
            expected, accepted = None, False
        if accepted != valid:
            raise AssertionError(f"Python reference contract changed: {name}")
        print(
            json.dumps(
                {
                    "name": name,
                    "kind": kind,
                    "wire": wire,
                    "expected": expected,
                    "valid": valid,
                },
                ensure_ascii=False,
            )
        )


def hello_vectors() -> None:
    profiles = [
        "local-detachable-execution/v1",
        "local-detachable-discovery-execution/v1",
    ]
    for profile in profiles:
        wire = execution_hello(profile, "instance").decode()
        cases = [
            ("canonical", wire, True),
            ("whitespace", wire + "\n", False),
            ("escaped-id", wire.replace('"instance"', '"inst\\u0061nce"'), False),
            (
                "duplicate",
                wire.replace(
                    '"restartRecovery":false',
                    '"restartRecovery":false,"restartRecovery":false',
                ),
                False,
            ),
        ]
        for name, field, value in [
            ("app-version", "protocolVersion", "loushang.app/v2"),
            ("execution-version", "executionVersion", "loushang.execution/v2"),
            (
                "profile-mismatch",
                "profile",
                profiles[1] if profile == profiles[0] else profiles[0],
            ),
            ("unknown-profile", "profile", "unknown/v1"),
            ("restart-claim", "restartRecovery", True),
            ("restart-number", "restartRecovery", 0),
            ("retention", "submissionRetention", "forever"),
            ("invalid-instance", "serviceInstanceId", "invalid id"),
            ("extra", "unexpected", True),
        ]:
            altered = json.loads(wire)
            altered[field] = value
            cases.append(
                (
                    name,
                    json.dumps(altered, sort_keys=True, separators=(",", ":")),
                    False,
                )
            )
        missing = json.loads(wire)
        del missing["submissionRetention"]
        cases.append(
            (
                "missing",
                json.dumps(missing, sort_keys=True, separators=(",", ":")),
                False,
            )
        )
        reordered = dict(reversed(list(json.loads(wire).items())))
        cases.append(("order", json.dumps(reordered, separators=(",", ":")), False))
        for name, raw, valid in cases:
            try:
                instance = decode_execution_hello(raw.encode(), profile)
                expected = json.loads(execution_hello(profile, instance))
                accepted = True
            except InvalidAppMessageError:
                expected, accepted = None, False
            assert accepted == valid, f"Python hello contract changed: {name}"
            print(
                json.dumps(
                    {
                        "name": f"hello/{profile}/{name}",
                        "kind": "hello",
                        "profile": profile,
                        "wire": raw,
                        "expected": expected,
                        "valid": valid,
                    }
                )
            )


if __name__ == "__main__":
    main()
    hello_vectors()
