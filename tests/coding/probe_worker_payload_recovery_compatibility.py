"""Explicit fixed original complete recovery observations, outside default discovery.

Real PayloadStorage/RepairJournal/RootedSupervisor IO, DTOs, files and descriptors.
Product quiescence/GC/admission ports are controlled; this does not prove native
Product contention or actual Task.cancel. Interruptions are synchronous injected
KeyboardInterrupt/CancelledError exceptions. Device/inode values are normalized
by identity, preserving relationships; byte templates retain other byte content.
Raw full observations and source guards remain outside Product. No recapture.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import shutil
import stat
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import package_product_worker_payload as code
from loushang.coding.package_product_worker_history_read_v2 import _HISTORY_READER
from loushang.harness.worker.history._rooted_supervisor import RootedSupervisorJournal
from loushang.harness.worker.payload._repair import RepairJournal
from loushang.harness.worker.payload._storage import PayloadStorage
from tests.coding.probe_native_release_readers_compatibility import error_graph
from tests.harness.worker.test_journal import _identity, _settle

ATTEMPT = "a" * 32
COMMON = (
    "fresh",
    "prior",
    "prior-absent",
    "prior-mismatch",
    "supervisor-present",
    "supervisor-late",
    "stale-stage",
    "stage-missing",
    "write-zero",
    "write-short",
    "link-after",
    "fsync-after",
    "settle-after",
    "remove-before",
    "remove-partial",
    "remove-after",
    "interrupt",
    "async-interrupt",
    "close-error",
    "close-and-body",
    "root-close",
    "guard-enter",
    "guard-exit",
    "current-first",
    "current-last",
    "active-runtime",
    "root-open",
    "stage-open",
    "read-short",
    "invalid-type",
    "intent-mode",
    "intent-body",
)
CASES = tuple(
    f"{kind}:{case}" for kind in ("complete", "empty", "unmarked") for case in COMMON
)
CASES += ("unmarked:payload-mode",)
CASES += tuple(
    f"{kind}:preview-{case}"
    for kind in ("complete", "empty", "unmarked")
    for case in ("normal", "changed", "supervisor")
    if not (kind == "complete" and case == "changed")
)
CASES += tuple(
    "complete:review-" + c for c in ("absent", "claimed", "settled", "changed")
)
CASES += tuple(
    "complete:list-" + c for c in ("normal", "bad-name", "bad-stage", "error")
)


def observe(name, base, patch):
    kind, case = name.split(":")
    base.chmod(0o700)
    root = base / "root"
    root.mkdir(mode=0o700)
    stage = root / f"worker-payload-{ATTEMPT}"
    stage.mkdir(mode=0o700)
    body = b"payload for fixed recovery\n"
    trace = []
    phase = "seed"
    fired = False
    published = False
    gc_exited = False
    current_count = 0
    sup_count = 0
    borrowed_root_fd = None
    inode_ids = {}
    device_ids = {}

    def number(value, device=False):
        target = device_ids if device else inode_ids
        return target.setdefault(value, ("D" if device else "I") + str(len(target) + 1))

    def register():
        for p in [root, *sorted(root.rglob("*"))]:
            st = p.lstat()
            number(st.st_dev, True)
            number(st.st_ino)

    register()

    def norm(value, key=""):
        if dataclasses.is_dataclass(value):
            return {
                "type": type(value).__name__,
                "fields": {
                    f.name: norm(getattr(value, f.name), f.name)
                    for f in dataclasses.fields(value)
                },
            }
        if isinstance(value, dict):
            return {str(k): norm(v, str(k)) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [norm(v) for v in value]
        if isinstance(value, Path):
            return str(value).replace(str(base), "<ROOT>")
        if isinstance(value, str):
            return value.replace(str(base), "<ROOT>")
        if key in ("stage_inode", "stageInode", "inode"):
            return number(value)
        if key in ("stage_device", "stageDevice", "device"):
            return number(value, True)
        return value

    def normal_bytes(raw):
        def fix(m):
            return (
                m[1] + number(int(m[2]), m[3] in (b"stageDevice", b"device")).encode()
            )

        return re.sub(
            rb'(("(stageDevice|stageInode|device|inode)"\s*:\s*))([0-9]+)',
            lambda m: (
                m[1] + number(int(m[4]), m[3] in (b"stageDevice", b"device")).encode()
            ),
            raw,
        )

    def tree():
        result = {}
        for p in [root, *sorted(root.rglob("*"))]:
            st = p.lstat()
            entry = {
                "mode": stat.S_IMODE(st.st_mode),
                "kind": "dir" if p.is_dir() else "file",
                "device": number(st.st_dev, True),
                "inode": number(st.st_ino),
                "nlink": st.st_nlink,
            }
            if p.is_file():
                entry["body"] = normal_bytes(p.read_bytes()).hex()
            result["." if p == root else p.relative_to(root).as_posix()] = entry
        return result

    def fault():
        nonlocal fired
        fired = True
        trace.append(["fault", case])
        if case == "interrupt":
            raise KeyboardInterrupt("injected recovery interruption")
        if case == "async-interrupt":
            raise asyncio.CancelledError("injected synchronous cancellation exception")
        raise OSError("injected " + case)

    def inject(wanted):
        return phase == "repair" and case == wanted and not fired

    @contextmanager
    def quiescence(**kwargs):
        nonlocal gc_exited
        gc_exited = False
        trace.append(["quiescence-enter", kwargs])
        try:
            yield NS(
                active_runtime_lease_ids=("active",) if case == "active-runtime" else ()
            )
        finally:
            trace.append(["quiescence-exit"])

    @contextmanager
    def gc_guard(**kwargs):
        nonlocal gc_exited
        trace.append(["gc-enter", kwargs])
        if inject("guard-enter"):
            fault()
        try:
            yield
        finally:
            gc_exited = True
            trace.append(["gc-exit"])
            if inject("guard-exit"):
                fault()

    class Product:
        epoch_runtime = NS(
            registry=NS(store_id="fixed-store", exclusive_runtime_quiescence=quiescence)
        )
        gc_gate = NS(guard=gc_guard)

        @property
        def state_root(self):
            trace.append(["state-root"])
            return root

        def assert_root_gc_authority_current(self):
            nonlocal current_count
            current_count += 1
            trace.append(["current", current_count])
            if inject("current-first") or inject("current-last") and gc_exited:
                fault()

    product = Product()
    patch.setattr(code, "PosixLocalWheelProductSessionOwner", Product)

    class Access:
        scope_id = "session-one"
        store_id = "fixed-store"

        @contextmanager
        def guard(self, *, require_write):
            trace.append(["history-guard", require_write])
            yield

        def assert_current(self):
            trace.append(["history-current"])

    def journal():
        return RootedSupervisorJournal(
            root / "worker-supervisor.jsonl",
            access=Access(),
            history_reader=_HISTORY_READER,
        )

    seed_journal = journal()
    if (
        kind == "complete"
        and case not in ("review-absent", "preview-normal", "preview-changed")
        or case in ("supervisor-present", "preview-supervisor", "review-claimed")
    ):
        seed_journal.claim(_identity(attempt="a", epoch=1), max_attempts=1)
        if kind == "complete" and case not in ("supervisor-present", "review-claimed"):
            _settle(seed_journal, attempt_id=ATTEMPT, epoch=1)

    def supervisor_factory(product):
        nonlocal sup_count
        sup_count += 1
        trace.append(["supervisor-factory", sup_count])
        j = journal()
        original_status = j.status

        def status(attempt):
            trace.append(["status", attempt])
            record = original_status(attempt)
            if phase == "repair" and published and case == "supervisor-late":
                if record is None:
                    record = j.claim(_identity(attempt="a", epoch=1), max_attempts=1)
                else:
                    record = dataclasses.replace(
                        record, record_revision=record.record_revision + 1
                    )
            if case in ("preview-changed", "review-changed"):
                if kind == "empty":
                    (stage / "unexpected").write_bytes(b"changed")
                else:
                    (stage / "bin" / "worker").chmod(0o600)
                    (stage / "bin" / "worker").write_bytes(b"changed")
            return record

        j.status = status
        return j

    patch.setattr(code, "CodingProductWorkerSupervisorJournal", supervisor_factory)
    fd = os.open(root, code._DIR_FLAGS)
    stage_fd = os.open(stage, code._DIR_FLAGS)
    try:
        if kind == "empty":
            expected = code._verify_empty_debt(fd, ATTEMPT)
        else:
            code._write_payload(stage_fd, "bin/worker", body)
            if kind == "complete":
                info = os.fstat(stage_fd)
                expected = code.CodingWorkerPayloadDebtPlanV1(
                    ATTEMPT,
                    "bin/worker",
                    sha256(body).hexdigest(),
                    len(body),
                    "f" * 64,
                    info.st_dev,
                    info.st_ino,
                )
                code._write_marker(stage_fd, expected)
            else:
                (stage / "bin" / "worker").chmod(0o600)
                expected = code._scan_unmarked_debt(fd, ATTEMPT)
        if case == "payload-mode" and kind == "unmarked":
            (stage / "bin" / "worker").chmod(0o500)
            expected = code._scan_unmarked_debt(fd, ATTEMPT)
        if case in (
            "prior",
            "prior-absent",
            "prior-mismatch",
            "intent-mode",
            "intent-body",
        ):
            args = (
                (
                    expected,
                    sha256(
                        json.dumps(
                            seed_journal.status(ATTEMPT).to_dict(),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                )
                if kind == "complete"
                else (expected,)
            )
            getattr(code, f"_publish_{kind}_repair_intent")(fd, *args)
        if case == "prior-absent" or case == "stage-missing":
            shutil.rmtree(stage)
        if case == "prior-mismatch":
            expected = dataclasses.replace(
                expected, stage_inode=expected.stage_inode + 100
            )
        if case == "stale-stage":
            stage.chmod(0o755)
        if case == "intent-mode":
            (root / getattr(code, f"_{kind}_repair_names")(ATTEMPT)[0]).chmod(0o644)
        if case == "intent-body":
            (root / getattr(code, f"_{kind}_repair_names")(ATTEMPT)[0]).write_bytes(
                b"{}\n"
            )
        if case == "list-bad-name":
            (root / "worker-payload-invalid").mkdir(mode=0o700)
        if case == "list-bad-stage":
            (root / ("worker-payload-" + "b" * 32)).mkdir(mode=0o700)
    finally:
        os.close(stage_fd)
        os.close(fd)
    register()
    trace.clear()
    current_count = 0
    sup_count = 0
    original_publish = RepairJournal.publish
    original_settle = RepairJournal.settle

    def publish(self, *args):
        nonlocal published
        trace.append(["publish", kind])
        result = original_publish(self, *args)
        published = True
        if phase == "repair" and case == "supervisor-late" and kind == "empty":
            seed_journal.claim(_identity(attempt="a", epoch=1), max_attempts=1)
        return result

    def settle(self, *args):
        trace.append(["settle", kind])
        result = original_settle(self, *args)
        if inject("settle-after"):
            fault()
        return result

    patch.setattr(RepairJournal, "publish", publish)
    patch.setattr(RepairJournal, "settle", settle)
    remove_name = {
        "empty": "_remove_empty_stage",
        "complete": "_remove_verified_stage",
        "unmarked": "_remove_unmarked_repair_remainder",
    }[kind]
    original_remove = getattr(code, remove_name)

    def remove(*args, **kwargs):
        trace.append(["remove", kind])
        if (
            inject("remove-before")
            or inject("interrupt")
            or inject("async-interrupt")
            or inject("close-and-body")
        ):
            fault()
        if inject("remove-partial"):
            if kind == "empty":
                pass
            else:
                (stage / "bin" / "worker").unlink()
            fault()
        result = original_remove(*args, **kwargs)
        if inject("remove-after"):
            fault()
        return result

    if hasattr(code, "_recovery"):

        def method(self, *args, **kwargs):
            return remove(*args, **kwargs)

        patch.setattr(PayloadStorage, remove_name, method)
    else:
        patch.setattr(code, remove_name, remove)
    originals = {
        name: getattr(os, name)
        for name in (
            "open",
            "close",
            "write",
            "read",
            "link",
            "fsync",
            "unlink",
            "rmdir",
            "listdir",
        )
    }

    def fdpath(value):
        if isinstance(value, int):
            try:
                return (
                    os.readlink(f"/proc/self/fd/{value}")
                    .removesuffix(" (deleted)")
                    .replace(str(base), "<ROOT>")
                )
            except OSError:
                return "<closed>"
        return str(value).replace(str(base), "<ROOT>")

    def wrap(operation):
        def invoke(*args, **kwargs):
            nonlocal borrowed_root_fd
            relevant = phase != "seed"
            path = fdpath(args[0]) if args else ""
            if relevant:
                detail = None
                trace.append(
                    [
                        operation,
                        path,
                        detail,
                        fdpath(kwargs["dir_fd"]) if "dir_fd" in kwargs else None,
                    ]
                )
            if phase == "repair":
                if operation == "open" and (
                    inject("root-open")
                    and str(args[0]) == str(root)
                    or inject("stage-open")
                    and str(args[0]) == stage.name
                ):
                    fault()
                if operation == "write" and inject("write-zero"):
                    nonlocal fired
                    fired = True
                    trace.append(["fault", case])
                    return 0
                if operation == "write" and inject("write-short"):
                    fired = True
                    trace.append(["fault", case])
                    return originals[operation](
                        args[0], args[1][: max(1, len(args[1]) // 2)]
                    )
                if operation == "read" and inject("read-short"):
                    value = originals[operation](*args, **kwargs)
                    if value:
                        fired = True
                        trace.append(["fault", case])
                        return value[: max(0, len(value) // 2)]
                    return value
            if operation == "listdir" and case == "list-error" and phase == "operation":
                raise OSError("injected inventory listing")
            result = originals[operation](*args, **kwargs)
            if (
                operation == "open"
                and str(args[0]) == str(root)
                and borrowed_root_fd is None
            ):
                borrowed_root_fd = result
            if phase == "repair":
                if (
                    operation == "link"
                    and inject("link-after")
                    or operation == "fsync"
                    and inject("fsync-after")
                ):
                    fault()
                if (
                    operation == "close"
                    and path == str(stage).replace(str(base), "<ROOT>")
                    and published
                    and case in ("close-error", "close-and-body")
                ):
                    if case == "close-error" and not fired:
                        fault()
                    if case == "close-and-body":
                        raise OSError("injected stage close after body")
                if (
                    operation == "close"
                    and inject("root-close")
                    and args[0] == borrowed_root_fd
                ):
                    fault()
            return result

        return invoke

    for operation in originals:
        patch.setattr(os, operation, wrap(operation))

    def capture(label, operation):
        nonlocal phase, borrowed_root_fd
        borrowed_root_fd = None
        phase = label
        try:
            value = operation()
            error = None
            identity = value is expected
        except BaseException as exc:
            value = None
            identity = False
            error = error_graph(exc, lambda x: x.replace(str(base), "<ROOT>"))
            error["code"] = getattr(exc, "code", None)
        phase = "seed"
        return {
            "value": norm(value),
            "identity": identity,
            "error": error,
            "tree": tree(),
        }

    if case.startswith("preview-"):
        function = getattr(
            code,
            {
                "complete": "preview_coding_product_worker_payload_debt",
                "empty": "preview_coding_product_worker_empty_payload_debt",
                "unmarked": "review_coding_product_worker_unmarked_payload_debt",
            }[kind],
        )
        outputs = {
            "preview": capture(
                "operation", lambda: function(product, attempt_id=ATTEMPT)
            )
        }
    elif case.startswith("review-"):
        outputs = {
            "review": capture(
                "operation",
                lambda: code.review_coding_product_worker_payload_recovery(
                    product, attempt_id=ATTEMPT
                ),
            )
        }
    elif case.startswith("list-"):
        outputs = {
            "list": capture(
                "operation",
                lambda: code.list_coding_product_worker_payload_debts(product),
            )
        }
    else:
        repair = getattr(
            code,
            {
                "complete": "repair_coding_product_worker_payload_debt",
                "empty": "repair_coding_product_worker_empty_payload_debt",
                "unmarked": "repair_coding_product_worker_unmarked_payload_debt",
            }[kind],
        )
        arg = "expected_review" if kind == "unmarked" else "expected_plan"

        def invoke():
            return repair(
                product, **{arg: object() if case == "invalid-type" else expected}
            )

        outputs = {"repair": capture("repair", invoke)}
        if kind != "empty":
            outputs["read"] = capture(
                "followup",
                lambda: getattr(
                    code,
                    "read_coding_product_worker_"
                    + ("payload" if kind == "complete" else "unmarked_payload")
                    + "_repair_intent",
                )(product, attempt_id=ATTEMPT),
            )
        outputs["reopen"] = capture(
            "followup",
            lambda: getattr(
                code,
                "reopen_coding_product_worker_"
                + ("payload" if kind == "complete" else kind + "_payload")
                + "_repair",
            )(product, attempt_id=ATTEMPT),
        )
        outputs["retry"] = capture("followup", invoke)
    return {"outputs": outputs, "trace": trace, "fired": fired}


def compact_observation(raw):
    """Hash all normalized bytes and ordered traces; preserve outcomes/metadata."""
    result = json.loads(json.dumps(raw))
    trace = result.pop("trace")
    temporary_names = {}

    def normalize_temporary(value):
        if isinstance(value, str):

            def replace_name(match):
                original = match.group()
                return temporary_names.setdefault(
                    original,
                    ".worker-supervisor.head.json.<TMP-"
                    + str(len(temporary_names) + 1)
                    + ">.tmp",
                )

            return re.sub(
                r"\.worker-supervisor\.head\.json\.[0-9a-f]{24}\.tmp",
                replace_name,
                value,
            )
        if isinstance(value, list):
            return [normalize_temporary(item) for item in value]
        return value

    trace = normalize_temporary(trace)
    result["trace_count"] = len(trace)
    result["trace_sha256"] = sha256(
        json.dumps(trace, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    for output in result["outputs"].values():
        for entry in output["tree"].values():
            if "body" in entry:
                body = bytes.fromhex(entry.pop("body"))
                entry["body_bytes"] = len(body)
                entry["body_sha256"] = sha256(body).hexdigest()
    return result


@pytest.mark.parametrize("case", CASES)
def test_original_worker_payload_recovery(case, tmp_path, monkeypatch):
    fixture = json.loads(
        (
            Path(__file__).with_name("fixtures") / "worker_payload_recovery_v1.json"
        ).read_text()
    )
    assert (
        compact_observation(observe(case, tmp_path, monkeypatch))
        == fixture["observations"][case]
    )
