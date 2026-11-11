"""A88 original full/reserved lexical cleanup, real FDs, controlled native ports."""

from __future__ import annotations

import gzip
import hashlib
import importlib
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from tests.coding import probe_windows_reserved_capture_compatibility as reserved_shared
from tests.coding import probe_windows_stage_capture_compatibility as shared

HERE = Path(__file__).parent
CASES = tuple(
    f"{role}-{body}-{mask:02d}"
    for role in ("full", "reserved")
    for body in ("normal", "value", "stop")
    for mask in range(1, 16)
)


class Observer(shared.Observer):
    def __init__(self, case, root):
        super().__init__(case, root)
        self.fired = []

    def fail(self, event):
        self.add(event)
        role, body, number = self.case.split("-")
        mask = int(number)
        if event == "construct" and body != "normal":
            self.fired.append(event)
            raise (ValueError if body == "value" else StopIteration)(
                "injected " + event
            )
        if any(
            mask & bit and event == selected
            for bit, selected in (
                (1, "close:dir1"),
                (2, "close:stage"),
                (4, "root.exit"),
                (8, "acl.exit"),
            )
        ):
            self.fired.append(event)
            raise OSError("injected " + event)


def observed(case):
    role, body, number = case.split("-")
    mask = int(number)
    full = importlib.import_module(
        "loushang.coding.package_product_worker_windows_stage_review"
    )
    reserved = importlib.import_module(
        "loushang.coding.package_product_worker_windows_reserved_review"
    )
    effect = importlib.import_module(
        "loushang.harness.package_product._worker_windows_attempt"
    )
    io = importlib.import_module("loushang.harness.worker.payload._windows_stage_io")
    consumption = importlib.import_module(
        "loushang.harness.resources.packages._file_consumption"
    )
    retirement = importlib.import_module(
        "loushang.harness.worker.payload._windows_stage_retirement"
    )
    intents = importlib.import_module(
        "loushang.coding.package_product_worker_windows_launch_intent"
    )
    with patch.object(shared, "HERE", HERE / "adjacent-inputs"):
        root, stage, _entrypoint = shared.seeded(case)
    observer = Observer(case, root)
    port = shared.OsPort(observer)
    meta = stage.stat()
    identity = (meta.st_dev, meta.st_ino)
    intent = intents.CodingWindowsWorkerLaunchIntentV1(
        attempt_id=shared.ATTEMPT,
        stage_identity=identity,
        receipt_fingerprint="b" * 64,
        request_fingerprint="c" * 64,
        identity_fingerprint="d" * 64,
        runtime_fingerprint="e" * 64,
        payload_digest=hashlib.sha256(shared.BODY).hexdigest(),
        owner_id="worker-owner",
        supervisor_epoch=1,
    )
    product = NS(
        epoch_runtime=NS(borrow_product_state_root_descriptor=observer.root_borrow),
        state_root=NS(lstat=observer.root_lstat),
    )
    result = error = None
    with ExitStack() as patches:
        for owner in (full, reserved, effect, io):
            if hasattr(owner, "os"):
                patches.enter_context(patch.object(owner, "os", port))
            for name, replacement in [
                ("open_windows_directory", observer.open_dir),
                ("windows_stat_at", observer.stat_at),
                ("windows_listdir_at", observer.listdir),
            ]:
                if hasattr(owner, name):
                    patches.enter_context(patch.object(owner, name, replacement))
            if hasattr(owner, "WindowsPrivateDirectoryAcl"):
                patches.enter_context(
                    patch.object(
                        owner, "WindowsPrivateDirectoryAcl", observer.acl_type()
                    )
                )
        for owner in (consumption, retirement):
            patches.enter_context(patch.object(owner, "os", port))
        patches.enter_context(
            patch.object(io, "open_windows_regular_file_at", observer.open_file)
        )
        for name in (
            "windows_directory_stream_names",
            "windows_regular_file_stream_names",
        ):
            patches.enter_context(patch.object(io, name, observer.streams))
        if body != "normal":
            target = (
                full._CapturedStageBytesV1
                if role == "full"
                else reserved.CodingWindowsWorkerReservedNoEffectReviewV1
            )

            def constructor(self, **kw):
                observer.add(
                    "constructor.fields",
                    target="private-full-six-fields"
                    if role == "full"
                    else "reserved-public",
                    fields=shared.value(tuple(kw.items())),
                )
                observer.fail("construct")

            patches.enter_context(patch.object(target, "__init__", constructor))
        try:
            if role == "full":
                captured = full._capture_stage_bytes(
                    product,
                    attempt_id=shared.ATTEMPT,
                    expected_stage=identity,
                    intent=intent,
                )
                result = shared.value(captured)["fields"]
            else:
                result = reserved_shared.value(
                    reserved._capture_reserved_stage(
                        product,
                        intent=intent,
                        native_revision=1,
                        lease_owner_revision=7,
                    )
                )
        except BaseException as exc:
            error = shared.error_data(exc)
    outstanding = [role for role, _ in observer.opened.values()]
    for fd, (name, _path) in list(observer.opened.items()):
        shared.REAL_OS.close(fd)
        observer.opened.pop(fd)
        observer.raw.append({"event": "observer.cleanup", "fd": fd, "role": name})
    assert error is not None and error["type"] == "builtins.OSError", (case, error)
    # Both original programs close children before final stage rechecks and ctor.
    expected = [] if body == "normal" or mask & 1 else ["construct"]
    expected += [
        event
        for bit, event in (
            (1, "close:dir1"),
            (2, "close:stage"),
            (4, "root.exit"),
            (8, "acl.exit"),
        )
        if mask & bit
    ]
    assert observer.fired == expected, (case, observer.fired, expected)
    assert outstanding == (["dir0"] if mask & 1 else []), (case, outstanding)
    return {
        "case": case,
        "result": result,
        "error": error,
        "trace": observer.rows,
        "fired": observer.fired,
        "outstanding_before_observer_cleanup": outstanding,
        "outstanding_after_observer_cleanup": [],
    }, observer.raw


def portable_observation(observation, context, case, raw):
    for row in raw:
        if row["event"] == "acquire":
            role = row["role"]
            path = Path(row["path"])
            expected = context["paths"][role]
            assert path == expected, (
                case,
                "acquired path differs from prior input role",
            )
        if row["event"] == "stat":
            assert row["identity"] == list(context["stats"][row["role"]]), (
                case,
                "raw metadata differs from prior input",
            )
    rows = []
    for original in observation["trace"]:
        row = dict(original)
        if row["event"] == "constructor.fields":
            fields = dict(row["fields"])
            expected, intent = reserved_shared._public_input_fields(context, case)
            if case.startswith("full-"):
                expected = {
                    key: expected[key]
                    for key in (
                        "entrypoint",
                        "stage_identity",
                        "directory_identities",
                        "marker_identity",
                        "executable_identity",
                        "executable_digest",
                    )
                }
            assert set(fields) == set(expected)
            assert json.dumps(fields, sort_keys=True) == json.dumps(
                expected, sort_keys=True
            ), (case, "constructor fields/types differ from independent input formula")
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
                        identity,
                        context["directory_roles"][name],
                        context,
                        case,
                        "return",
                    ),
                ]
                for name, identity in fields["directory_identities"]
            ]
            if case.startswith("reserved-"):
                projected["intent_fingerprint"] = {
                    "algorithm": "sha256",
                    "domain_hex": b"loushang.coding-windows-worker-launch-intent/v1\0".hex(),
                    "canonical_intent": {
                        **intent,
                        "stageIdentity": ["input.dev:stage", "input.ino:stage+0"],
                    },
                }
            row["fields"] = [[key, projected[key]] for key, _value in row["fields"]]
        rows.append(row)
    # Every mask is a cleanup failure: do not fabricate public wire/result data.
    assert observation["result"] is None
    return shared._portable_observation({**observation, "trace": rows}, context, case)


def input_context(case, root):
    context = shared._input_context(case, root)
    paths = {"root": root, "stage": root / ("worker-payload-" + shared.ATTEMPT)}
    paths["marker"] = paths["stage"] / "worker-payload.json"
    paths["executable"] = paths["stage"] / shared._entrypoint(case)
    for name, role in context["directory_roles"].items():
        paths[role] = paths["stage"] / name
    return {**context, "paths": paths}


_FIXTURE = Path(__file__).parent / "fixtures" / "windows_stage_cleanup_v1.json.gz"


@pytest.mark.parametrize("case", CASES)
def test_stage_cleanup(case, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "HERE", tmp_path)
    with patch.object(shared, "HERE", tmp_path / "adjacent-inputs"):
        root, _stage, _entrypoint = shared.seeded(case)
        context = input_context(case, root)
    result, raw = observed(case)
    assert (
        portable_observation(result, context, case, raw)
        == json.loads(gzip.decompress(_FIXTURE.read_bytes()))[case]
    )
