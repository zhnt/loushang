"""Original Windows-backend public value/API oracle; no backend IO or launch."""

from __future__ import annotations

import dataclasses
import gzip
import inspect
import json
import pickle
import types
import typing
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.coding import package_product_worker_windows_backend_release as release
from loushang.coding import (
    package_product_worker_windows_installed_backend as installed,
)
from loushang.coding import (
    package_product_worker_windows_native_approval_owner as owner,
)
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeReleaseApprovalV1,
    CodingWorkerNativeReleaseReviewV1,
)
from loushang.hosting.windows_backend_material import (
    WindowsBackendMaterialExpectationV1,
)

HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures" / "backend_dto_contract_v1.json.gz"
PROFILE = "loushang/hosting/_windows_launch_preparation.py"
MEMBERS = ((PROFILE, "e" * 64),)
VALUE_CASES = (
    "candidate-valid",
    "candidate-none",
    "candidate-list",
    "candidate-maltyped",
    "material-valid",
    "material-none",
    "material-maltyped",
    "installed-valid",
    "installed-bool",
    "installed-float",
    "installed-negative",
    "installed-none-generation",
    "installed-none-review",
    "installed-none-expectation",
)
CASES = ("api", "reader", *VALUE_CASES)


def fqn(value):
    return value.__module__ + "." + value.__qualname__


def annotation(value):
    if isinstance(value, str):
        return {"forward": value}
    if value is Ellipsis:
        return {"ellipsis": True}
    origin = typing.get_origin(value)
    if origin is not None:
        return {
            "origin": fqn(origin) if hasattr(origin, "__qualname__") else str(origin),
            "args": [annotation(arg) for arg in typing.get_args(value)],
        }
    if isinstance(value, type):
        return {"type": fqn(value)}
    return {"typing": str(value)}


def value_data(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "type": fqn(type(value)),
            "fields": [
                [field.name, value_data(getattr(value, field.name))]
                for field in dataclasses.fields(value)
            ],
        }
    if value is None or type(value) in (bool, int, float, str):
        return {"type": fqn(type(value)), "value": value}
    if type(value) in (tuple, list):
        return {"type": fqn(type(value)), "items": [value_data(item) for item in value]}
    if type(value) is dict:
        return {
            "type": fqn(type(value)),
            "items": [
                [value_data(key), value_data(item)] for key, item in value.items()
            ],
        }
    raise AssertionError(("unplanned oracle value", type(value)))


def error_data(error, seen=frozenset()):
    if id(error) in seen:
        return {"cycle": fqn(type(error))}
    seen = seen | {id(error)}
    return {
        "type": fqn(type(error)),
        "message": str(error),
        "notes": list(getattr(error, "__notes__", ())),
        "cause": None if error.__cause__ is None else error_data(error.__cause__, seen),
        "context": None
        if error.__context__ is None
        else error_data(error.__context__, seen),
        "suppress_context": error.__suppress_context__,
    }


def outcome(operation):
    try:
        return {"value": value_data(operation())}
    except BaseException as error:
        return {"error": error_data(error)}


def callable_api(function):
    return {
        "signature": str(inspect.signature(function)),
        "hints": {
            key: annotation(item)
            for key, item in typing.get_type_hints(function).items()
        },
    }


def public_methods(cls):
    result = {}
    for name in dir(cls):
        if name.startswith("_"):
            continue
        raw = inspect.getattr_static(cls, name)
        if isinstance(raw, property):
            result[name] = {"property": callable_api(raw.fget)}
        elif isinstance(raw, (classmethod, staticmethod)):
            result[name] = {"callable": callable_api(getattr(cls, name))}
        elif inspect.isfunction(raw):
            result[name] = {"callable": callable_api(raw)}
    return result


def dto_api(cls):
    fields = dataclasses.fields(cls)
    params = cls.__dataclass_params__
    return {
        "type": fqn(cls),
        "signature": str(inspect.signature(cls)),
        "init": callable_api(cls.__init__),
        "own_annotations": {
            key: annotation(item) for key, item in cls.__annotations__.items()
        },
        "public_field_hints": {
            key: annotation(item)
            for key, item in typing.get_type_hints(cls).items()
            if not key.startswith("_")
        },
        "fields": [
            {
                "name": field.name,
                "type": annotation(field.type),
                "default_missing": field.default is dataclasses.MISSING,
                "factory_missing": field.default_factory is dataclasses.MISSING,
                "init": field.init,
                "repr": field.repr,
                "compare": field.compare,
                "hash": field.hash,
                "kw_only": field.kw_only,
                "metadata": dict(field.metadata),
            }
            for field in fields
        ],
        "params": {
            key: getattr(params, key)
            for key in ("init", "repr", "eq", "order", "unsafe_hash", "frozen")
        },
        "slots": list(cls.__slots__),
        "match_args": list(cls.__match_args__),
        "public_methods": public_methods(cls),
    }


def inputs(case):
    approval = CodingWorkerNativeReleaseApprovalV1(
        "1" * 64, "2" * 64, "3" * 64, "4" * 64
    )
    review = CodingWorkerNativeReleaseReviewV1.create(
        scope_id="scope-a93", product_policy_revision="policy-a93", approval=approval
    )
    expectation = WindowsBackendMaterialExpectationV1("a" * 64, "b" * 64, MEMBERS)
    if case.startswith("candidate-"):
        cls = release.CodingWindowsWorkerBackendCandidateV1
        kwargs = dict(
            approval=approval,
            package_members=MEMBERS,
            python_executable_sha256="a" * 64,
            python_runtime_dll_sha256="b" * 64,
        )
        if case == "candidate-none":
            kwargs = dict.fromkeys(kwargs)
        elif case == "candidate-list":
            kwargs["package_members"] = [[PROFILE, "e" * 64]]
        elif case == "candidate-maltyped":
            kwargs.update(
                approval=0,
                package_members=(),
                python_executable_sha256=True,
                python_runtime_dll_sha256=1.0,
            )
    elif case.startswith("material-"):
        cls = release.CodingWindowsWorkerBackendMaterialReviewV1
        kwargs = dict(review=review, expectation=expectation)
        if case == "material-none":
            kwargs = dict.fromkeys(kwargs)
        elif case == "material-maltyped":
            kwargs = dict(
                review="unvalidated-review", expectation={"unvalidated": True}
            )
    else:
        cls = installed.CodingWindowsWorkerInstalledBackendV1
        kwargs = dict(review=review, approval_generation=7, expectation=expectation)
        for name, replacement in [
            ("installed-bool", True),
            ("installed-float", 1.0),
            ("installed-negative", -1),
            ("installed-none-generation", None),
        ]:
            if case == name:
                kwargs["approval_generation"] = replacement
        if case == "installed-none-review":
            kwargs["review"] = None
        elif case == "installed-none-expectation":
            kwargs["expectation"] = None
    return cls, kwargs


def instance_contract(instance, kwargs):
    cls = type(instance)
    ordered = tuple(kwargs[field.name] for field in dataclasses.fields(cls))
    try:
        actual_hash = hash(instance)
    except BaseException as error:
        hash_fact = {"error": error_data(error)}
    else:
        # Hash integers vary with the interpreter's randomized hash seed.
        # Verify the original tuple-of-input-fields formula, never normalize
        # an arbitrary observed hash into a successful fact.
        hash_fact = {
            "equals_input_tuple_hash": actual_hash == hash(ordered),
            "repeat_equal": actual_hash == hash(instance),
        }
    twin = cls(**kwargs)
    changed = dict(kwargs)
    changed[next(iter(changed))] = "different-first-field"
    return {
        "value": value_data(instance),
        "repr": repr(instance),
        "has_dict": hasattr(instance, "__dict__"),
        "eq_same_inputs": instance == twin,
        "eq_changed_input": instance == cls(**changed),
        "eq_foreign_tuple": instance == ordered,
        "hash": hash_fact,
    }


def observe(case):
    if case == "api":
        dtos = [
            release.CodingWindowsWorkerBackendCandidateV1,
            release.CodingWindowsWorkerBackendMaterialReviewV1,
            installed.CodingWindowsWorkerInstalledBackendV1,
        ]
        functions = [
            release.inspect_coding_windows_worker_backend_candidate,
            release.inspect_coding_windows_worker_backend_material,
            release.review_coding_windows_worker_backend_release,
            installed.install_coding_windows_worker_backend_release,
            installed.read_coding_windows_worker_installed_backend_release,
        ]
        return {
            "case": case,
            "dtos": [dto_api(cls) for cls in dtos],
            "exports": {
                "release": list(release.__all__),
                "installed": list(installed.__all__),
            },
            "functions": {
                function.__name__: callable_api(function) for function in functions
            },
            "reader": {
                "type": fqn(installed.CodingWindowsWorkerInstalledBackendReader),
                "init": callable_api(
                    installed.CodingWindowsWorkerInstalledBackendReader.__init__
                ),
                "public_methods": public_methods(
                    installed.CodingWindowsWorkerInstalledBackendReader
                ),
            },
            "approval_owner": {
                "init": callable_api(
                    owner.CodingWindowsWorkerNativeApprovalOwner.__init__
                ),
                "public_methods": public_methods(
                    owner.CodingWindowsWorkerNativeApprovalOwner
                ),
            },
            "error_type": fqn(installed.CodingWindowsWorkerInstalledBackendError),
        }
    if case == "reader":
        cls, kwargs = inputs("installed-valid")
        material = cls(**kwargs)
        sentinel = types.SimpleNamespace(gc_gate=object())
        reader = object.__new__(installed.CodingWindowsWorkerInstalledBackendReader)
        reader._product = sentinel
        called = []

        def read(product):
            called.append(product is sentinel)
            return material

        with patch.object(
            installed, "read_coding_windows_worker_installed_backend_release", read
        ):
            result = reader.current_closure()
        return {
            "case": case,
            "controlled_read_calls": called,
            "product_identity": reader.product_owner is sentinel,
            "gate_identity": reader.gc_gate is sentinel.gc_gate,
            "closure": value_data(result),
        }
    cls, kwargs = inputs(case)
    instance = cls(**kwargs)
    result = {
        "case": case,
        "contract": instance_contract(instance, kwargs),
        "pickle": {},
    }
    if hasattr(instance, "native_closure"):
        result["closure"] = outcome(instance.native_closure)
    for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
        frozen = pickle.dumps(instance, protocol=protocol)
        restored = pickle.loads(frozen)
        result["pickle"][str(protocol)] = {
            "hex": frozen.hex(),
            "restored": instance_contract(restored, kwargs),
        }
    first = dataclasses.fields(cls)[0].name
    result["frozen"] = {
        "set_field": outcome(lambda: setattr(instance, first, "replacement")),
        "delete_field": outcome(lambda: delattr(instance, first)),
        "set_unknown": outcome(lambda: setattr(instance, "_a93_unknown", 1)),
    }
    return result


@pytest.mark.parametrize("case", CASES)
def test_backend_dto_contract(case):
    result = observe(case)
    expected = json.loads(gzip.decompress(FIXTURE.read_bytes()))[case]
    assert json.dumps(result, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.parametrize("case", VALUE_CASES)
def test_old_pickle_crossload(case):
    expected = json.loads(gzip.decompress(FIXTURE.read_bytes()))[case]
    cls, kwargs = inputs(case)
    for protocol, record in expected["pickle"].items():
        restored = pickle.loads(bytes.fromhex(record["hex"]))
        assert type(restored) is cls
        assert json.dumps(
            instance_contract(restored, kwargs), sort_keys=True
        ) == json.dumps(record["restored"], sort_keys=True), (case, protocol)
