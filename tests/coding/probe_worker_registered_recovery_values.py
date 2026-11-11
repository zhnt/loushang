"""Pure old API/DTO/codec observations; no Product owner or native IO is opened."""

from __future__ import annotations

import copy
import dataclasses
import inspect
import json
import pickle
from pathlib import Path

import pytest

from loushang.coding import package_product_worker_activation_state as activation
from loushang.coding import package_product_worker_cleanup_evidence as cleanup
from loushang.coding import package_product_worker_crash_c5_settlement as crash
from loushang.coding import (
    package_product_worker_registered_c5_settlement as settlement,
)
from loushang.coding import package_product_worker_registered_payload_repair as repair
from loushang.coding import package_product_worker_registered_recovery as recovery
from loushang.coding.package_product_worker_payload import CodingWorkerPayloadDebtPlanV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

MODULES = (recovery, repair, settlement, crash, cleanup, activation)
CASES = (
    "api",
    "errors",
    "review",
    "review-permissive",
    "authority-closed",
    "intent",
    "intent-zero-generation",
    "intent-unicode",
    "intent-bool-generation",
    "intent-float-generation",
    "intent-negative-generation",
    "intent-bad-plan",
    "intent-plan-subclass",
    "intent-bad-digest",
    "intent-string-subclass",
    "intent-empty-host",
    "intent-empty-boot",
    "dict",
    "dict-outer-true",
    "dict-outer-float",
    "dict-inner-true",
    "dict-inner-float",
    "dict-both-true",
    "dict-extra",
    "dict-missing",
    "dict-list",
    "dict-subclass",
    "dict-inner-extra",
    "dict-inner-missing",
    "dict-inner-list",
    "dict-outer-zero",
    "dict-inner-zero",
    "dict-bool-generation",
    "dict-float-generation",
    "dict-zero-size",
    "dict-bool-size",
    "dict-zero-inode",
    "dict-bool-device",
    "dict-noncanonical-path",
    "codec",
    "codec-no-lf",
    "codec-two-lf",
    "codec-space",
    "codec-reordered",
    "codec-wrong-attempt",
    "codec-json-error",
    "codec-list",
    "codec-extra",
    "codec-outer-true",
    "codec-outer-float",
    "codec-inner-true",
    "codec-inner-float",
    "names",
    "names-uppercase",
    "names-empty",
    "names-subclass",
    "names-int",
)
SUCCESS = frozenset(
    {
        "api",
        "errors",
        "review",
        "review-permissive",
        "authority-closed",
        "intent",
        "intent-zero-generation",
        "intent-unicode",
        "dict",
        "dict-outer-true",
        "dict-outer-float",
        "dict-inner-true",
        "dict-inner-float",
        "dict-both-true",
        "codec",
        "names",
    }
)


def signature(member):
    raw = member.__func__ if inspect.ismethod(member) else member
    return {
        "signature": str(inspect.signature(member)),
        "module": raw.__module__,
        "qualname": raw.__qualname__,
        "annotations": dict(raw.__annotations__),
    }


def reflect():
    result = {}
    for module in MODULES:
        entries = {}
        for name in module.__all__:
            value = getattr(module, name)
            if not inspect.isclass(value):
                entries[name] = signature(value)
                continue
            row = {
                "module": value.__module__,
                "qualname": value.__qualname__,
                "signature": str(inspect.signature(value)),
                "annotations": dict(value.__dict__.get("__annotations__", {})),
                "slots": list(value.__dict__.get("__slots__", ())),
                "methods": {},
            }
            if dataclasses.is_dataclass(value):
                row["fields"] = [
                    {
                        "name": f.name,
                        "type": str(f.type),
                        "init": f.init,
                        "repr": f.repr,
                        "compare": f.compare,
                        "default": "<MISSING>"
                        if f.default is dataclasses.MISSING
                        else f.default,
                    }
                    for f in dataclasses.fields(value)
                ]
                row["frozen"] = value.__dataclass_params__.frozen
            if value is cleanup.CodingPosixWorkerCleanupEvidenceAuthority:
                row["authority_id"] = value.authority_id
                row["authority_fingerprint"] = value.authority_fingerprint
            for member_name, raw in value.__dict__.items():
                if member_name.startswith("_") and member_name != "__init__":
                    continue
                if isinstance(raw, property):
                    row["methods"][member_name] = signature(raw.fget)
                elif isinstance(raw, (classmethod, staticmethod)) or inspect.isfunction(
                    raw
                ):
                    row["methods"][member_name] = signature(getattr(value, member_name))
            entries[name] = row
        result[module.__name__] = entries
    return result


def sample():
    plan = CodingWorkerPayloadDebtPlanV1(
        "a" * 32, "bin/worker", "b" * 64, 4, "c" * 64, 3, 7
    )
    return repair.CodingWorkerRegisteredPayloadRepairIntentV1(
        plan, "d" * 64, "e" * 64, "f" * 64, "1" * 64, "host", "old-boot", 1
    )


def value_result(value):
    if isinstance(value, repair.CodingWorkerRegisteredPayloadRepairIntentV1):
        cloned = pickle.loads(pickle.dumps(value, protocol=4))
        wire = canonical_json_bytes(value.to_dict()) + b"\n"
        return {
            "type": type(value).__module__ + "." + type(value).__qualname__,
            "dict": value.to_dict(),
            "wire_hex": wire.hex(),
            "attempt_id": value.attempt_id,
            "pickle_type_identity": type(cloned) is type(value),
            "pickle_value_equal": cloned == value,
        }
    return value


def error_graph(error, seen=None):
    if error is None:
        return None
    seen = {} if seen is None else seen
    if id(error) in seen:
        return {"ref": seen[id(error)]}
    seen[id(error)] = len(seen)
    return {
        "id": seen[id(error)],
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "args": list(error.args),
        "message": str(error),
        "code": getattr(error, "code", None),
        "suppress": error.__suppress_context__,
        "notes": getattr(error, "__notes__", []),
        "cause": error_graph(error.__cause__, seen),
        "context": error_graph(error.__context__, seen),
    }


def operation(case):
    if case == "api":
        return reflect()
    if case == "errors":
        values = []
        for cls in (
            recovery.CodingWorkerRegisteredRecoveryError,
            repair.CodingWorkerRegisteredPayloadRepairError,
            settlement.CodingWorkerRegisteredC5SettlementError,
            crash.CodingWorkerCrashC5SettlementError,
        ):
            value = cls("fixed-code")
            cloned = pickle.loads(pickle.dumps(value, protocol=4))
            values.append(
                {
                    "error": error_graph(value),
                    "repr": repr(value),
                    "pickle_identity": type(cloned) is cls,
                    "pickle_args": list(cloned.args),
                    "pickle_code": cloned.code,
                }
            )
        return values
    if case in {"review", "review-permissive"}:
        cls = recovery.CodingWorkerRegisteredOrphanReviewV1
        value = cls(
            "a" * 32 if case == "review" else "invalid",
            None,
            None,
            None,
            None,
            None,
            None,
            "host",
            "boot",
            1 if case == "review" else True,
            "root",
            (),
        )
        cloned = pickle.loads(pickle.dumps(value, protocol=4))
        return {
            "type": type(value).__module__ + "." + type(value).__qualname__,
            "dict": dataclasses.asdict(value),
            "registered_candidate": value.registered_candidate,
            "repair_candidate": value.repair_candidate,
            "payload_repair_candidate": value.payload_repair_candidate,
            "pickle_identity": type(cloned) is cls,
            "pickle_equal": cloned == value,
        }
    if case == "authority-closed":
        obj = object.__new__(cleanup.CodingPosixWorkerCleanupEvidenceAuthority)
        return [
            obj.verify_registered_lease_expired(),
            obj.verify_registered_lease_expired(unexpected="opaque"),
        ]
    if case.startswith("names"):

        class String(str):
            pass

        value = {
            "names": "a" * 32,
            "names-uppercase": "A" * 32,
            "names-empty": "",
            "names-subclass": String("a" * 32),
            "names-int": 1,
        }[case]
        return repair._names(value)
    value = sample()
    if case.startswith("intent"):
        changes = {}

        class String(str):
            pass

        class Plan(CodingWorkerPayloadDebtPlanV1):
            pass

        if case == "intent-zero-generation":
            changes["owner_generation"] = 0
        elif case == "intent-unicode":
            changes["host_identity"] = "主机"
        elif case == "intent-bool-generation":
            changes["owner_generation"] = True
        elif case == "intent-float-generation":
            changes["owner_generation"] = 1.0
        elif case == "intent-negative-generation":
            changes["owner_generation"] = -1
        elif case == "intent-bad-plan":
            changes["plan"] = object()
        elif case == "intent-plan-subclass":
            changes["plan"] = Plan(**dataclasses.asdict(value.plan))
        elif case == "intent-bad-digest":
            changes["lease_id"] = "A" * 64
        elif case == "intent-string-subclass":
            changes["host_identity"] = String("host")
        elif case == "intent-empty-host":
            changes["host_identity"] = ""
        elif case == "intent-empty-boot":
            changes["boot_identity"] = ""
        return value_result(dataclasses.replace(value, **changes))
    raw = copy.deepcopy(value.to_dict())
    if case.startswith("dict"):

        class Dict(dict):
            pass

        changes = {
            "dict-outer-true": (raw, "version", True),
            "dict-outer-float": (raw, "version", 1.0),
            "dict-inner-true": (raw["plan"], "version", True),
            "dict-inner-float": (raw["plan"], "version", 1.0),
            "dict-outer-zero": (raw, "version", 0),
            "dict-inner-zero": (raw["plan"], "version", 0),
            "dict-bool-generation": (raw, "ownerGeneration", True),
            "dict-float-generation": (raw, "ownerGeneration", 1.0),
            "dict-zero-size": (raw["plan"], "payloadSize", 0),
            "dict-bool-size": (raw["plan"], "payloadSize", True),
            "dict-zero-inode": (raw["plan"], "stageInode", 0),
            "dict-bool-device": (raw["plan"], "stageDevice", True),
            "dict-noncanonical-path": (raw["plan"], "entrypoint", "bin/../worker"),
        }
        if case in changes:
            target, key, replacement = changes[case]
            target[key] = replacement
        elif case == "dict-both-true":
            raw["version"] = raw["plan"]["version"] = True
        elif case == "dict-extra":
            raw["extra"] = 1
        elif case == "dict-missing":
            raw.pop("leaseId")
        elif case == "dict-list":
            raw = []
        elif case == "dict-subclass":
            raw = Dict(raw)
        elif case == "dict-inner-extra":
            raw["plan"]["extra"] = 1
        elif case == "dict-inner-missing":
            raw["plan"].pop("payloadSize")
        elif case == "dict-inner-list":
            raw["plan"] = []
        return value_result(
            repair.CodingWorkerRegisteredPayloadRepairIntentV1.from_dict(raw)
        )
    if case.startswith("codec"):
        body = canonical_json_bytes(raw) + b"\n"
        if case == "codec-no-lf":
            body = body[:-1]
        elif case == "codec-two-lf":
            body += b"\n"
        elif case == "codec-space":
            body = b" " + body
        elif case == "codec-reordered":
            body = json.dumps(raw, sort_keys=False).encode() + b"\n"
        elif case == "codec-json-error":
            body = b"{"
        elif case == "codec-list":
            body = b"[]\n"
        elif case == "codec-extra":
            raw["extra"] = 1
            body = canonical_json_bytes(raw) + b"\n"
        elif case in {
            "codec-outer-true",
            "codec-outer-float",
            "codec-inner-true",
            "codec-inner-float",
        }:
            (raw if "outer" in case else raw["plan"])["version"] = (
                True if "true" in case else 1.0
            )
            body = (
                json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            )
        return value_result(
            repair._decode_repair_record(
                body, "b" * 32 if case == "codec-wrong-attempt" else "a" * 32
            )
        )
    raise AssertionError("unknown case: " + case)


def observe(case):
    try:
        value = operation(case)
    except BaseException as error:
        result = {"value": None, "error": error_graph(error)}
    else:
        result = {"value": value, "error": None}
    assert (result["error"] is None) == (case in SUCCESS), (case, result)
    if result["error"] is not None:
        assert result["error"]["type"].rsplit(".", 1)[-1] in {
            "ValueError",
            "TypeError",
            "JSONDecodeError",
        }, result
    return json.loads(json.dumps(result, ensure_ascii=False))


_FIXED = json.loads(
    (
        Path(__file__).parent / "fixtures/worker_registered_recovery_values_v1.json"
    ).read_text()
)


@pytest.mark.parametrize("case", CASES)
def test_fixed_registered_recovery_values(case):
    """Compare only immutable original-source observations; never recapture."""
    assert observe(case) == _FIXED["observations"][case]
