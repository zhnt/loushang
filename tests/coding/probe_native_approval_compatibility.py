"""Fixed original values, two-platform decisions, and real Rooted journal IO.

Explicit local validation with immutable expectations and no capture path.
Product authority and Windows ACL/custody are controlled; POSIX journal IO is real.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import pickle
from contextlib import contextmanager
from dataclasses import MISSING, fields, replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import package_product_worker_native_approval as code
from loushang.coding.package_product_worker_windows_native_approval_journal import (
    CodingWindowsWorkerNativeApprovalJournal,
)
from loushang.harness.journal import _rooted_io
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

OBSERVATIONS = json.loads(
    (Path(__file__).parent / "fixtures" / "native_approval_v1.json").read_text()
)["observations"]

Approval = code.CodingWorkerNativeReleaseApprovalV1
Review = code.CodingWorkerNativeReleaseReviewV1
Decision = code.CodingWorkerNativeApprovalDecisionV1


class ApprovalSubclass(Approval):
    pass


class ReviewSubclass(Review):
    pass


class DecisionSubclass(Decision):
    pass


class DictSubclass(dict):
    pass


class Duck:
    def to_dict(self):
        return approval().to_dict()

    def __repr__(self):
        return "DuckApproval()"


def approval():
    return Approval("a" * 64, "b" * 64, "c" * 64, "d" * 64)


def decision(revision=1, *, action="approve", value=None, op=None, scope="scope"):
    return Decision.create(
        journal_revision=revision,
        scope_id=scope,
        operation_id=op or f"op-{revision}",
        generation=revision,
        action=action,
        approval=approval() if action == "approve" and value is None else value,
    )


def errors(exc, normalize, seen=None):
    if exc is None:
        return None
    seen = {} if seen is None else seen
    if id(exc) in seen:
        return {"ref": seen[id(exc)]}
    seen[id(exc)] = len(seen)
    return {
        "id": seen[id(exc)],
        "type": type(exc).__name__,
        "message": normalize(str(exc)),
        "code": getattr(exc, "code", None),
        "notes": getattr(exc, "__notes__", []),
        "suppress": exc.__suppress_context__,
        "cause": errors(exc.__cause__, normalize, seen),
        "context": errors(exc.__context__, normalize, seen),
    }


def result(value):
    if isinstance(value, (Approval, Review, Decision)):
        return value.to_dict()
    if isinstance(value, tuple):
        return [result(v) for v in value]
    return value


def reflect(value):
    cls = type(value)
    concrete = cls in (Approval, Review, Decision)
    serializable = concrete and not (
        isinstance(value, Decision) and isinstance(value.approval, Duck)
    )
    cloned = pickle.loads(pickle.dumps(value, protocol=4)) if serializable else value
    frozen = None
    try:
        setattr(value, fields(value)[0].name, "changed")
    except BaseException as exc:
        frozen = type(exc).__name__
    return {
        "value": value.to_dict(),
        "type": cls.__name__,
        "fqcn": f"{cls.__module__}.{cls.__qualname__}" if concrete else "subclass",
        "repr": repr(value),
        "slots": list(cls.__slots__),
        "dict": hasattr(value, "__dict__"),
        "annotations": cls.__annotations__ if concrete else None,
        "match_args": list(cls.__match_args__),
        "fields": [
            [f.name, f.type, "MISSING" if f.default is MISSING else f.default]
            for f in fields(value)
        ],
        "signature": str(inspect.signature(cls)) if concrete else None,
        "create": str(inspect.signature(cls.create))
        if concrete and hasattr(cls, "create")
        else None,
        "from_dict": str(inspect.signature(cls.from_dict))
        if concrete and hasattr(cls, "from_dict")
        else None,
        "pickle": pickle.dumps(value, protocol=4).hex() if serializable else None,
        "pickle_same": cloned == value and type(cloned) is cls,
        "frozen": frozen,
        "keys": list(value.to_dict()),
    }


DTO_CASES = (
    "approval",
    "review",
    "decision",
    "approval-subclass",
    "review-subclass",
    "decision-subclass",
    "approval-extra",
    "approval-missing",
    "approval-dict-subclass",
    "approval-uppercase",
    "approval-short",
    "review-version-bool",
    "review-version-float",
    "review-version-zero",
    "review-digest",
    "review-opaque",
    "review-approval",
    "decision-version-bool",
    "decision-version-float",
    "decision-version-zero",
    "decision-revision-bool",
    "decision-generation-bool",
    "decision-scope",
    "decision-digest",
    "decision-revoke",
    "decision-revoke-value",
    "decision-revoke-duck",
    "decision-revoke-object",
    "decision-shape",
    "decision-extra",
    "decision-from-dict-duck",
    "codec-error",
)


def dto(case, patch):
    a = approval()
    if case.startswith("approval"):
        if case == "approval-subclass":
            return reflect(ApprovalSubclass.from_dict(a.to_dict()))
        value = a.to_dict()
        if case == "approval-extra":
            value["extra"] = True
        if case == "approval-missing":
            value.pop("wheelSha256")
        if case == "approval-dict-subclass":
            value = DictSubclass(value)
        if case == "approval-uppercase":
            value["wheelSha256"] = "A" * 64
        if case == "approval-short":
            value["wheelSha256"] = "a"
        return reflect(Approval.from_dict(value))
    if case.startswith("review"):
        r = Review.create(
            scope_id="scope", product_policy_revision="policy", approval=a
        )
        if case == "review-subclass":
            return reflect(
                ReviewSubclass.create(
                    scope_id="scope", product_policy_revision="policy", approval=a
                )
            )
        values = {f.name: getattr(r, f.name) for f in fields(r)}
        if case == "review-version-bool":
            values["review_version"] = True
        if case == "review-version-float":
            values["review_version"] = 1.0
        if case == "review-version-zero":
            values["review_version"] = 0
        if case == "review-opaque":
            values["scope_id"] = " bad scope "
        if case == "review-approval":
            values["approval"] = None
        if case == "review-digest":
            values["review_id"] = "0" * 64
        elif case == "review-version-bool":
            unsigned = {
                "approval": a.to_dict(),
                "productPolicyRevision": "policy",
                "reviewVersion": values["review_version"],
                "scopeId": "scope",
            }
            values["review_id"] = hashlib.sha256(
                canonical_json_bytes(unsigned)
            ).hexdigest()
        return reflect(Review(**values))
    if case == "codec-error":
        return code._decode({"bad": True})
    d = decision()
    if case == "decision-subclass":
        return reflect(
            DecisionSubclass.create(
                journal_revision=1,
                scope_id="scope",
                operation_id="op-1",
                generation=1,
                action="approve",
                approval=a,
            )
        )
    if case == "decision-revoke":
        return reflect(decision(action="revoke"))
    if case == "decision-revoke-value":
        return reflect(decision(action="revoke", value=a))
    if case == "decision-revoke-duck":
        return reflect(decision(action="revoke", value=Duck()))
    if case == "decision-revoke-object":
        return reflect(decision(action="revoke", value=object()))
    wire = d.to_dict()
    if case == "decision-shape":
        wire = DictSubclass(wire)
    if case == "decision-extra":
        wire["extra"] = 1
    if case == "decision-from-dict-duck":
        wire = decision(action="revoke", value=Duck()).to_dict()
    if case == "decision-version-bool":
        wire["recordVersion"] = True
    if case == "decision-version-float":
        wire["recordVersion"] = 1.0
    if case == "decision-version-zero":
        wire["recordVersion"] = 0
    if case == "decision-revision-bool":
        wire["journalRevision"] = True
    if case == "decision-generation-bool":
        wire["generation"] = True
    if case == "decision-scope":
        wire["scopeId"] = "bad scope"
    if case == "decision-digest":
        wire["recordDigest"] = "0" * 64
    elif case in {
        "decision-version-bool",
        "decision-version-zero",
        "decision-revision-bool",
        "decision-generation-bool",
        "decision-scope",
    }:
        unsigned = {k: v for k, v in wire.items() if k != "recordDigest"}
        wire["recordDigest"] = hashlib.sha256(
            canonical_json_bytes(unsigned)
        ).hexdigest()
    return reflect(Decision.from_dict(wire))


DECODE_CASES = (
    "empty",
    "valid",
    "whitespace",
    "reordered",
    "no-newline",
    "bad-json",
    "utf8",
    "partial-tail",
    "too-big",
    "wrong-scope",
    "first-revoke",
    "double-revoke",
    "duplicate",
    "revision",
    "generation",
    "capacity-first",
    "decode-first",
    "limits-after-codec",
    "approve-again",
)


def decode(case, patch):
    events = [decision()]
    if case == "wrong-scope":
        events = [decision(scope="other")]
    if case == "first-revoke":
        events = [decision(action="revoke")]
    if case == "double-revoke":
        events += [decision(2, action="revoke"), decision(3, action="revoke")]
    if case == "duplicate":
        events += [decision(2, op="op-1")]
    if case == "revision":
        events = [decision(2)]
    if case == "generation":
        events = [
            Decision.create(
                journal_revision=1,
                scope_id="scope",
                operation_id="op-1",
                generation=2,
                action="approve",
                approval=approval(),
            )
        ]
    if case == "approve-again":
        events += [decision(2)]
    raw = b"".join(canonical_json_bytes(e.to_dict()) + b"\n" for e in events)
    if case == "empty":
        raw = b""
    if case == "whitespace":
        raw = b" \n" + b"".join(
            json.dumps(e.to_dict(), indent=0).replace("\n", " ").encode() + b"\n\n"
            for e in events
        )
    if case == "reordered":
        raw = (
            json.dumps(dict(reversed(list(events[0].to_dict().items())))).encode()
            + b"\n"
        )
    if case == "no-newline":
        raw = raw[:-1]
    if case == "bad-json":
        raw = b"{\n"
    if case == "utf8":
        raw = b"\xff\n"
    if case == "partial-tail":
        raw += b"{"
    if case == "too-big":
        raw = b"\xff" * (4 * 1024 * 1024 + 1)
    if case in {"capacity-first", "decode-first"}:
        patch.setattr(code, "_MAX_EVENTS", 0)
        if case == "decode-first":
            raw = b"{\n"
        else:
            raw = canonical_json_bytes(decision(scope="other").to_dict()) + b"\n"
    if case == "limits-after-codec":
        prior = code._CODEC

        class Codec:
            def decode_record(self, value):
                patch.setattr(code, "_MAX_EVENTS", 0)
                return prior.decode_record(value)

        patch.setattr(code, "_CODEC", Codec())
    return result(
        code._decode_coding_worker_native_approval_history(
            raw, path=Path("/state/history.jsonl"), scope_id="scope"
        )
    )


FLOW_CASES = (
    "fresh",
    "retry",
    "retry-full",
    "retry-conflict",
    "stale",
    "absent",
    "capacity",
    "revoke",
    "revoke-duck",
    "bad-operation",
    "bad-generation",
    "bad-action",
    "bad-approval",
    "read-error",
    "append-error",
    "append-partial",
    "current-error",
    "cleanup-error",
    "body-cleanup-error",
    "gc-error",
    "gc-exit-error",
    "current-absent",
    "current-noncanonical",
    "revoke-duck-reopen",
    "error-type-change",
    "lock-error",
    "read-oversize",
)


def posix(case, base, patch):
    trace = []
    root = base / "state"
    root.mkdir(mode=0o700)

    @contextmanager
    def guard(*, require_write=False):
        trace.append(["gc-enter", require_write])
        if case == "gc-error":
            raise OSError("injected GC entry")
        try:
            yield
        finally:
            trace.append(["gc-exit"])
            if case == "gc-exit-error":
                raise OSError("injected GC exit")

    class Product(PosixLocalWheelProductSessionOwner):
        def assert_root_gc_authority_current(self):
            trace.append(["current"])
            if case == "current-error":
                raise OSError("injected currentness")

    owner = object.__new__(Product)
    object.__setattr__(owner, "state_root", root)
    object.__setattr__(owner, "gc_gate", NS(guard=guard))
    object.__setattr__(
        owner,
        "policy",
        NS(
            product_id="coding",
            project_scope_id="scope",
            bindings=(NS(source_trust_class="local-worker-candidate"),),
        ),
    )
    journal = code.CodingWorkerNativeApprovalJournal(owner)
    initial = case in {
        "retry",
        "retry-full",
        "retry-conflict",
        "stale",
        "revoke",
        "revoke-duck",
        "revoke-duck-reopen",
        "current-noncanonical",
        "read-oversize",
    }
    if initial:
        raw = (
            json.dumps(
                decision().to_dict(), sort_keys=case != "current-noncanonical"
            ).encode()
            + b"\n"
        )
        if case == "read-oversize":
            raw = b"\0" * (4 * 1024 * 1024 + 1)
        journal.path.write_bytes(raw)
        journal.path.chmod(0o600)
    if case == "error-type-change":

        class ReplacementApprovalError(code.CodingWorkerNativeApprovalError):
            pass

        patch.setattr(code, "CodingWorkerNativeApprovalError", ReplacementApprovalError)
        root.chmod(0o770)
    if case in {"retry-full", "capacity"}:
        patch.setattr(code, "_MAX_EVENTS", 1 if initial else 0)
    real_read, real_append, real_lock = (
        _rooted_io.RootedFile.read_bytes,
        _rooted_io.RootedFile.append_bytes,
        _rooted_io.RootedFile.acquire_lock,
    )
    real_cleanup = _rooted_io.RootedFileIO.cleanup

    def read(self, *args, **kwargs):
        trace.append(["read", kwargs])
        if case == "read-error":
            raise OSError("injected read")
        return real_read(self, *args, **kwargs)

    def append(self, data, *, fsync=True):
        trace.append(["append", data.decode(), fsync])
        if case in {"append-error", "body-cleanup-error"}:
            raise OSError("injected append")
        if case == "append-partial":
            real_append(self, data[: len(data) // 2], fsync=fsync)
            raise OSError("injected partial append")
        return real_append(self, data, fsync=fsync)

    def lock(self, **kwargs):
        trace.append(["lock", kwargs])
        if case == "lock-error":
            raise OSError("injected lock")
        return real_lock(self, **kwargs)

    def cleanup(self):
        trace.append(["cleanup"])
        real_cleanup(self)
        if case in {"cleanup-error", "body-cleanup-error"}:
            raise OSError("injected cleanup")

    patch.setattr(_rooted_io.RootedFile, "read_bytes", read)
    patch.setattr(_rooted_io.RootedFile, "append_bytes", append)
    patch.setattr(_rooted_io.RootedFile, "acquire_lock", lock)
    patch.setattr(_rooted_io.RootedFileIO, "cleanup", cleanup)
    observed = []
    old_load = journal._load

    def load(rooted):
        values = old_load(rooted)
        observed[:] = values
        return values

    patch.setattr(journal, "_load", load)
    operation = "op-1" if case.startswith("retry") else "new-op"
    expected = 0 if case.startswith("retry") or not initial else 1
    action = (
        "revoke"
        if case in {"absent", "revoke", "revoke-duck", "revoke-duck-reopen"}
        else "approve"
    )
    selected = None if action == "revoke" else approval()
    if case in {"revoke-duck", "revoke-duck-reopen"}:
        selected = Duck()
    if case == "retry-conflict":
        selected = replace(approval(), wheel_sha256="e" * 64)
    if case == "stale":
        expected = 0
    if case == "bad-operation":
        operation = "bad operation"
    if case == "bad-generation":
        expected = True
    if case == "bad-action":
        action = "unsupported"
    if case == "bad-approval":
        selected = None
    if case.startswith("current-"):
        value = journal.current()
    else:
        value = journal.change(
            operation_id=operation,
            expected_generation=expected,
            action=action,
            approval=selected,
        )
    if case == "revoke-duck-reopen":
        journal.current()
    return (
        {
            "record": result(value),
            "replayIdentity": bool(observed) and value is observed[0],
        },
        trace,
        journal.path,
    )


WINDOWS_CASES = (
    "fresh",
    "retry",
    "retry-full",
    "retry-conflict",
    "stale",
    "absent",
    "capacity",
    "revoke",
    "bad-operation",
    "bad-generation",
    "bad-action",
    "bad-approval",
    "read-error",
    "append-error",
    "byte-capacity",
    "initialize-error",
    "visible-error",
    "cleanup-error",
    "body-cleanup-error",
    "noncanonical",
    "no-newline",
    "empty-bytes",
    "code-limit",
)


def windows(case, base, patch):
    trace = []
    journal = CodingWindowsWorkerNativeApprovalJournal(
        base / "worker-native-release-approvals.jsonl", scope_id="scope"
    )
    events = (
        (decision(),)
        if case
        in {
            "retry",
            "retry-full",
            "retry-conflict",
            "stale",
            "revoke",
            "noncanonical",
            "no-newline",
            "code-limit",
        }
        else ()
    )
    raw = (
        None
        if not events
        else b"".join(canonical_json_bytes(e.to_dict()) + b"\n" for e in events)
    )
    if case == "noncanonical":
        raw = json.dumps(events[0].to_dict()).encode() + b"\n"
    if case == "no-newline":
        raw = raw[:-1]
    if case == "empty-bytes":
        raw = b""
    if case == "code-limit":
        patch.setattr(code, "_MAX_EVENTS", 0)

    @contextmanager
    def custody():
        trace.append(["custody-enter"])
        try:
            yield
        finally:
            trace.append(["custody-exit"])
            if case in {"cleanup-error", "body-cleanup-error"}:
                raise OSError("injected cleanup")

    class IO:
        def bind_append_snapshot(self, fd, *, custody: object, **kwargs):
            trace.append(["bind", fd])
            custody.enter_context(globals_custody())
            if case == "read-error":
                raise OSError("injected read")
            return "acl", "lock", raw, False

        def mark_initialized(self, lock):
            trace.append(["initialize", lock])
            if case == "initialize-error":
                raise OSError("injected initialize")

        def append(self, fd, acl, *, expected, line):
            trace.append(
                [
                    "append",
                    fd,
                    acl,
                    expected.decode() if expected else expected,
                    line.decode(),
                ]
            )
            if case in {"append-error", "body-cleanup-error"}:
                raise OSError("injected append")

    globals_custody = custody
    patch.setattr(journal, "_file_io", IO())
    patch.setattr(journal, "_require_root", lambda fd: trace.append(["root", fd]))

    def visible(fd):
        trace.append(["visible", fd])
        if case == "visible-error":
            raise OSError("injected visibility")

    patch.setattr(journal, "_assert_visible_root", visible)

    def max_events():
        trace.append(["max-events"])
        return 0 if case in {"capacity", "retry-full"} else 256

    patch.setattr(journal, "_max_events", max_events)
    patch.setattr(
        journal, "_max_bytes", lambda: 0 if case == "byte-capacity" else 4 * 1024 * 1024
    )
    observed = []
    old_decode = journal._decode

    def decode_raw(data):
        values = old_decode(data)
        observed[:] = values
        return values

    patch.setattr(journal, "_decode", decode_raw)
    op = "op-1" if case.startswith("retry") else "new-op"
    expected = 0 if case.startswith("retry") or not events else 1
    action = "revoke" if case in {"absent", "revoke"} else "approve"
    selected = None if action == "revoke" else approval()
    if case == "retry-conflict":
        selected = replace(approval(), wheel_sha256="e" * 64)
    if case == "stale":
        expected = 0
    if case == "bad-operation":
        op = "bad operation"
    if case == "bad-generation":
        expected = True
    if case == "bad-action":
        action = "unsupported"
    if case == "bad-approval":
        selected = None
    value = journal.change(
        directory_fd=10,
        operation_id=op,
        expected_generation=expected,
        action=action,
        approval=selected,
    )
    return (
        {
            "record": result(value),
            "replayIdentity": bool(observed) and value is observed[0],
        },
        trace,
        None,
    )


CASES = (
    tuple(("dto", c) for c in DTO_CASES)
    + tuple(("decode", c) for c in DECODE_CASES)
    + tuple(("posix", c) for c in FLOW_CASES)
    + tuple(("windows", c) for c in WINDOWS_CASES)
)


def observe(kind, case, base, patch):
    def normalize(value):
        return value.replace(str(base), "<ROOT>")

    trace = []
    path = base / "state" / "worker-native-release-approvals.jsonl"
    try:
        if kind == "dto":
            value = dto(case, patch)
        elif kind == "decode":
            value = decode(case, patch)
        else:
            # Keep a trace reference even if the full public call raises.
            def profile_trace(frame, event, arg):
                if event == "return" and frame.f_code.co_name in {"posix", "windows"}:
                    trace[:] = frame.f_locals.get("trace", [])

            import sys

            sys.setprofile(profile_trace)
            try:
                value, trace, path = (posix if kind == "posix" else windows)(
                    case, base, patch
                )
            finally:
                sys.setprofile(None)
        error = None
    except BaseException as exc:
        value = None
        error = errors(exc, normalize)
    disk = None if kind not in {"posix"} or not path.exists() else path.read_text()
    if kind == "posix" and case == "read-oversize":
        disk = {"bytes": len(disk), "sha256": hashlib.sha256(disk.encode()).hexdigest()}
    return {"value": value, "error": error, "trace": trace, "disk": disk}


@pytest.mark.parametrize("kind,case", CASES)
def test_original_native_approval(kind, case, tmp_path, monkeypatch):
    actual = observe(kind, case, tmp_path, monkeypatch)
    assert_semantic_case(kind, case, actual)
    assert actual == OBSERVATIONS[f"{kind}-{case}"]


def assert_semantic_case(kind, case, actual):
    accepted = {
        "dto": {
            "approval",
            "review",
            "decision",
            "approval-subclass",
            "review-subclass",
            "decision-subclass",
            "review-version-bool",
            "decision-version-bool",
            "decision-revoke",
            "decision-revoke-duck",
        },
        "decode": {"empty", "valid", "whitespace", "reordered", "approve-again"},
        "posix": {
            "fresh",
            "retry",
            "retry-full",
            "revoke",
            "revoke-duck",
            "current-absent",
            "current-noncanonical",
        },
        "windows": {"fresh", "retry", "retry-full", "revoke"},
    }
    error = actual["error"]
    if case in accepted[kind]:
        assert error is None, json.dumps(actual, sort_keys=True)
        if kind in {"posix", "windows"} and case.startswith("retry"):
            assert actual["value"]["replayIdentity"] is True
        return
    assert error is not None, json.dumps(actual, sort_keys=True)
    if kind == "dto":
        expected = (
            "TypeError"
            if case.endswith("version-float")
            else "JournalCodecError"
            if case == "codec-error"
            else "AttributeError"
            if case == "decision-revoke-object"
            else "ValueError"
        )
    elif kind == "decode":
        expected = (
            "UnicodeDecodeError"
            if case == "utf8"
            else "JournalFileError"
            if case in {"bad-json", "decode-first", "no-newline", "partial-tail"}
            else "CodingWorkerNativeApprovalError"
        )
    elif case.startswith("bad-"):
        expected = "ValueError"
    elif kind == "posix" and case == "error-type-change":
        expected = "ReplacementApprovalError"
    elif kind == "posix" and case == "revoke-duck-reopen":
        expected = "JournalFileError"
    elif case in {
        "retry-conflict",
        "stale",
        "absent",
        "capacity",
        "byte-capacity",
        "noncanonical",
        "no-newline",
        "empty-bytes",
        "code-limit",
    }:
        expected = "CodingWorkerNativeApprovalError"
    else:
        expected = "OSError"
    assert error["type"] == expected, json.dumps(actual, sort_keys=True)
    if expected == "CodingWorkerNativeApprovalError":
        code = (
            "operation_conflict"
            if case == "retry-conflict"
            else "capacity"
            if case
            in {
                "capacity",
                "capacity-first",
                "too-big",
                "limits-after-codec",
                "byte-capacity",
                "code-limit",
            }
            else case
            if case in {"stale", "absent"}
            else "corrupt"
        )
        assert error["code"] == "coding_worker_native_approval_" + code
