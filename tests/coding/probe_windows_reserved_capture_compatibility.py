"""Reserved capture over shared real-FD probes; no native Windows claim.

Public type/all fields/canonical wire/fingerprint are independently checked from
frozen original schemas and prior physical inputs before identity-role projection.
Cancellation and StopIteration are synchronous IO-boundary faults, not Task.cancel.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import importlib
import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from tests.coding import probe_windows_stage_capture_compatibility as shared

CASES = (
    "valid-flat",
    "valid-nested",
    "valid-deep",
    "invalid-intent",
    "acl-enter-error",
    "acl-exit-error",
    "root-enter-error",
    "root-exit-error",
    "root-validate-error",
    "root-fstat-error",
    "root-lstat-error",
    "root-mismatch",
    "stage-open-error",
    "stage-validate-error",
    "stage-unsafe",
    "stage-link-unsafe",
    "stage-stream-unsafe",
    "intent-stage-mismatch",
    "stage-name-mismatch",
    "marker-open-error",
    "marker-validate-error",
    "marker-too-large",
    "marker-overflow",
    "marker-read-error",
    "marker-short-read",
    "marker-after-change",
    "marker-name-change",
    "marker-invalid-json",
    "marker-invalid-path",
    "marker-invalid-fields",
    "tree-top-extra",
    "child-open-error",
    "child-validate-error",
    "child-name-change",
    "tree-child-extra",
    "second-child-open-error",
    "second-child-validate-error",
    "executable-open-error",
    "executable-too-large",
    "executable-read-error",
    "executable-short-read",
    "executable-after-change",
    "executable-name-change",
    "digest-mismatch",
    "marker-size-mismatch",
    "child-close-error",
    "child-and-stage-close-error",
    "body-and-child-close-error",
    "marker-and-stage-close-error",
    "final-stage-fstat-error",
    "final-stage-change",
    "final-stage-name-change",
    "final-tree-change",
    "stage-close-error",
    "stage-and-root-close-error",
    "public-constructor-error",
    "cancel-marker-read",
    "cancel-child-open",
    "cancel-executable-read",
    "keyboardinterrupt-marker-read",
)
CASES = CASES + (
    "native-revision-two",
    "native-revision-none",
    "native-revision-zero",
    "native-revision-three",
    "native-revision-bool",
    "native-revision-float",
    "lease-revision-zero",
    "public-constructor-stage-close-error",
    "public-constructor-root-exit-error",
    "public-constructor-acl-exit-error",
    "public-constructor-stopiteration",
    "public-constructor-stopiteration-stage-close-error",
    "stop-marker-read",
    "stop-marker-read-stage-close-error",
    "stop-root-fstat",
)


class ReservedObserver(shared.Observer):
    def fail(self, event):
        case = self.case
        if (
            case in {"stop-marker-read", "stop-marker-read-stage-close-error"}
            and event == "read:marker:1"
        ) or (case == "stop-root-fstat" and event == "fstat:root:1"):
            self.add(event)
            raise StopIteration("injected " + event)
        if (
            (
                case
                in {
                    "public-constructor-stage-close-error",
                    "public-constructor-stopiteration-stage-close-error",
                    "stop-marker-read-stage-close-error",
                }
                and event == "close:stage"
            )
            or (case == "public-constructor-root-exit-error" and event == "root.exit")
            or (case == "public-constructor-acl-exit-error" and event == "acl.exit")
        ):
            self.add(event)
            raise OSError("injected " + event)
        return super().fail(event)


def value(instance):
    return {
        "type": type(instance).__module__ + "." + type(instance).__qualname__,
        "fields": {
            field.name: shared.value(getattr(instance, field.name))
            for field in dataclasses.fields(instance)
        },
        "bytes": instance.to_bytes().hex(),
        "fingerprint": instance.fingerprint,
    }


def scenario(case):
    module = importlib.import_module(
        "loushang.coding.package_product_worker_windows_reserved_review"
    )
    io = importlib.import_module("loushang.harness.worker.payload._windows_stage_io")
    consumption = importlib.import_module(
        "loushang.harness.resources.packages._file_consumption"
    )
    intent_module = importlib.import_module(
        "loushang.coding.package_product_worker_windows_launch_intent"
    )
    root, stage, entrypoint = shared.seeded(case)
    observer = ReservedObserver(case, root)
    port = shared.OsPort(observer)
    m = stage.stat()
    stage_identity = (m.st_dev, m.st_ino)
    intent = intent_module.CodingWindowsWorkerLaunchIntentV1(
        attempt_id=shared.ATTEMPT,
        stage_identity=stage_identity,
        receipt_fingerprint="b" * 64,
        request_fingerprint="c" * 64,
        identity_fingerprint="d" * 64,
        runtime_fingerprint="e" * 64,
        payload_digest=hashlib.sha256(shared.BODY).hexdigest(),
        owner_id="worker-owner",
        supervisor_epoch=1,
    )
    if case == "intent-stage-mismatch":
        intent = dataclasses.replace(intent, stage_identity=(m.st_dev, m.st_ino + 1))
    if case == "invalid-intent":
        intent = NS()
    product = NS(
        epoch_runtime=NS(borrow_product_state_root_descriptor=observer.root_borrow),
        state_root=NS(lstat=observer.root_lstat),
    )
    effect = importlib.import_module(
        "loushang.harness.package_product._worker_windows_attempt"
    )
    result = None
    error = None
    with ExitStack() as stack:
        for owner in (effect, io):
            stack.enter_context(patch.object(owner, "os", port))
            stack.enter_context(
                patch.object(owner, "open_windows_directory", observer.open_dir)
            )
            stack.enter_context(
                patch.object(owner, "windows_stat_at", observer.stat_at)
            )
            stack.enter_context(
                patch.object(owner, "windows_listdir_at", observer.listdir)
            )
        stack.enter_context(
            patch.object(effect, "WindowsPrivateDirectoryAcl", observer.acl_type())
        )
        stack.enter_context(
            patch.object(io, "open_windows_regular_file_at", observer.open_file)
        )
        stack.enter_context(
            patch.object(io, "windows_directory_stream_names", observer.streams)
        )
        stack.enter_context(
            patch.object(io, "windows_regular_file_stream_names", observer.streams)
        )
        stack.enter_context(patch.object(consumption, "os", port))
        if case.startswith("public-constructor"):

            def broken(self, **kwargs):
                observer.add("public.construct", keys=sorted(kwargs))
                if "stopiteration" in case:
                    raise StopIteration("public construction stopped")
                raise ValueError("public construction failed")

            stack.enter_context(
                patch.object(
                    module.CodingWindowsWorkerReservedNoEffectReviewV1,
                    "__init__",
                    broken,
                )
            )
        try:
            revision = {
                "native-revision-two": 2,
                "native-revision-none": None,
                "native-revision-zero": 0,
                "native-revision-three": 3,
                "native-revision-bool": True,
                "native-revision-float": 1.0,
            }.get(case, 1)
            result = value(
                module._capture_reserved_stage(
                    product,
                    intent=intent,
                    native_revision=revision,
                    lease_owner_revision=0 if case == "lease-revision-zero" else 7,
                )
            )
        except BaseException as exc:
            error = shared.error_data(exc)
    outstanding = [role for role, _path in observer.opened.values()]
    for fd, (role, _path) in list(observer.opened.items()):
        shared.REAL_OS.close(fd)
        observer.opened.pop(fd)
        observer.raw.append({"event": "observer.cleanup", "fd": fd, "role": role})
    return {
        "result": result,
        "error": error,
        "trace": observer.rows,
        "outstanding_before_observer_cleanup": outstanding,
        "outstanding_after_observer_cleanup": [],
    }, observer.raw


def _canonical(document):
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _public_input_fields(context, case):
    def identity(role):
        item = context["stats"][role]
        return [item[0], item[1], 1, item[3], item[4]]

    entry = shared._entrypoint(case)
    stage = context["stats"]["stage"][:2]
    intent = {
        "attemptId": shared.ATTEMPT,
        "stageIdentity": list(stage),
        "receiptFingerprint": "b" * 64,
        "requestFingerprint": "c" * 64,
        "identityFingerprint": "d" * 64,
        "runtimeFingerprint": "e" * 64,
        "payloadDigest": hashlib.sha256(shared.BODY).hexdigest(),
        "ownerId": "worker-owner",
        "supervisorEpoch": 1,
        "intentVersion": 1,
    }
    intent_fingerprint = hashlib.sha256(
        b"loushang.coding-windows-worker-launch-intent/v1\0" + _canonical(intent)
    ).hexdigest()
    fields = {
        "attempt_id": shared.ATTEMPT,
        "intent_fingerprint": intent_fingerprint,
        "lease_owner_revision": 7,
        "native_revision": 2 if case == "native-revision-two" else 1,
        "stage_identity": identity("stage"),
        "directory_identities": [
            [name, identity(role)] for name, role in context["directory_roles"].items()
        ],
        "marker_identity": identity("marker"),
        "executable_identity": identity("executable"),
        "executable_digest": hashlib.sha256(shared.BODY).hexdigest(),
        "entrypoint": entry,
    }
    return fields, intent


def _public_wire(fields):
    return {
        "attemptId": fields["attempt_id"],
        "directoryIdentities": fields["directory_identities"],
        "entrypoint": fields["entrypoint"],
        "executableDigest": fields["executable_digest"],
        "executableIdentity": fields["executable_identity"],
        "intentFingerprint": fields["intent_fingerprint"],
        "leaseOwnerRevision": fields["lease_owner_revision"],
        "markerIdentity": fields["marker_identity"],
        "nativeRevision": fields["native_revision"],
        "stageIdentity": fields["stage_identity"],
        "version": 1,
    }


def portable_observation(observed, context, case):
    normalized = shared._portable_observation(
        {**observed, "result": None}, context, case
    )
    result = observed["result"]
    if result is None:
        return normalized
    assert set(result) == {"type", "fields", "bytes", "fingerprint"}
    assert (
        result["type"]
        == "loushang.coding.package_product_worker_windows_reserved_review.CodingWindowsWorkerReservedNoEffectReviewV1"
    )
    expected, intent = _public_input_fields(context, case)
    fields = result["fields"]
    assert set(fields) == set(expected) and len(fields) == 10
    assert (
        type(fields["lease_owner_revision"]) is int
        and type(fields["native_revision"]) is int
    )
    assert fields == expected, (
        case,
        "public fields differ from independent original input formula",
    )
    wire = _canonical(_public_wire(expected))
    assert result["bytes"] == wire.hex(), (case, "public canonical wire changed")
    domain = b"loushang.coding-windows-worker-reserved-review/v1\0"
    assert result["fingerprint"] == hashlib.sha256(domain + wire).hexdigest(), (
        case,
        "public fingerprint changed",
    )
    projected = dict(fields)
    for name, role in [
        ("stage_identity", "stage"),
        ("marker_identity", "marker"),
        ("executable_identity", "executable"),
    ]:
        projected[name] = shared._metadata_token(
            fields[name], role, context, case, "return"
        )
    projected["directory_identities"] = [
        [
            name,
            shared._metadata_token(
                identity, context["directory_roles"][name], context, case, "return"
            ),
        ]
        for name, identity in fields["directory_identities"]
    ]
    intent_symbolic = {
        **intent,
        "stageIdentity": ["input.dev:stage", "input.ino:stage+0"],
    }
    projected["intent_fingerprint"] = {
        "algorithm": "sha256",
        "domain_hex": b"loushang.coding-windows-worker-launch-intent/v1\0".hex(),
        "canonical_intent": intent_symbolic,
    }
    wire_symbolic = _public_wire(projected)
    normalized["result"] = {
        "type": result["type"],
        "fields": projected,
        "bytes": {"canonical_json": wire_symbolic},
        "fingerprint": {
            "algorithm": "sha256",
            "domain_hex": domain.hex(),
            "canonical_wire": wire_symbolic,
        },
    }
    return normalized


_FIXTURE = Path(__file__).parent / "fixtures" / "reserved_stage_capture_v1.json.gz"
_EXPECTED = json.loads(gzip.decompress(_FIXTURE.read_bytes()))


@pytest.mark.parametrize("case", CASES)
def test_reserved_capture_runtime(case, tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "HERE", tmp_path)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    root, _stage, _entry = shared.seeded(case)
    context = shared._input_context(case, root)
    observed, _raw = scenario(case)
    assert portable_observation(observed, context, case) == _EXPECTED[case], case
