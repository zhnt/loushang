"""Freeze actual append-tail statements; native/authority ports are inert.

The surrounding public admission is covered by the original business tests.
These observations cover operation order, exception causes and append debt.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import textwrap
from pathlib import Path

import pytest

from loushang.harness.worker.journal import WorkerSupervisorJournalError

KINDS = (
    "activation_state_journal",
    "receipt",
    "start_gate_journal",
    "supervisor_journal",
    "opt_in",
)
CASES = (
    "plain",
    "generation_one",
    "legacy_name",
    "seal_count",
    "seal_bytes",
    "seal_capacity",
    "seal_corrupt",
    "seal_oserror",
    "target",
    "append_before",
    "append_after",
    "commit_before",
    "commit_after",
    "late_config",
    "encoding_drift",
)


def tail(module):
    source = Path(module.__file__).read_text()
    tree = ast.parse(source)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    shared = next(
        (n for n in calls if n.func.id == "append_coding_worker_active_record"), None
    )
    if shared is not None:
        start = max(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "append"
                and n.lineno < shared.lineno
            ),
            key=lambda n: n.lineno,
        )
        first, last = start.lineno, shared.end_lineno
    else:
        seal = next(
            n for n in calls if n.func.id == "seal_coding_worker_active_segment"
        )
        choices = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.If)
            and n.lineno < seal.lineno <= n.end_lineno
            and isinstance(n.test, ast.BoolOp)
            and any(
                isinstance(x, ast.Call)
                and isinstance(x.func, ast.Name)
                and x.func.id == "len"
                for x in ast.walk(n.test)
            )
        ]
        choose = min(choices, key=lambda n: n.end_lineno - n.lineno)
        commit = next(
            n
            for n in calls
            if n.func.id == "commit_coding_worker_active_segment"
            and n.lineno > choose.end_lineno
        )
        first, last = choose.lineno, commit.end_lineno
    body = textwrap.dedent("".join(source.splitlines(keepends=True)[first - 1 : last]))
    args = "self, rooted, history, record, decision, line, record_bytes, current_revision, last_revision, revision, active_records"
    program = "def run_tail(" + args + "):\n" + textwrap.indent(body, "    ")
    scope = {}
    exec(compile(program, str(module.__file__), "exec"), module.__dict__, scope)
    return (
        scope["run_tail"],
        (first, last),
        hashlib.sha256(program.encode()).hexdigest(),
    )


def observe(kind, case, patch):
    module = importlib.import_module("loushang.coding.package_product_worker_" + kind)
    value_module = module
    migrated = {
        "supervisor_journal": (
            "CodingProductWorkerSupervisorJournal",
            "_append_unlocked",
        ),
        "activation_state_journal": (
            "CodingProductWorkerActivationStateJournal",
            "compare_and_swap",
        ),
        "opt_in": ("CodingWorkerOptInJournal", "change"),
        "start_gate_journal": ("CodingWorkerStartGateJournal", "_append_record"),
        "receipt": ("CodingWorkerProductReceiptOwner", "_append_record"),
    }
    if kind in migrated:
        class_name, hook = migrated[kind]
        for base in getattr(module, class_name).__mro__:
            method = base.__dict__.get(hook)
            if (
                method is not None
                and "append_coding_worker_active_record" in method.__code__.co_names
            ):
                module = inspect.getmodule(method)
                assert module is not None
                break
        else:
            raise AssertionError("actual segmented append hook not found")
    value_modules = [module] if module is value_module else [module, value_module]
    core = importlib.import_module("loushang.harness.worker._segmented_history")
    run, _, _ = tail(module)
    stem = (
        "worker-activation-receipts"
        if kind == "receipt"
        else "worker-start-gates"
        if kind == "start_gate_journal"
        else module._STEM
    )
    raw = b"old\n"
    line = b"new\n"
    trace = []
    need_seal = case in {
        "seal_count",
        "seal_bytes",
        "seal_capacity",
        "seal_corrupt",
        "seal_oserror",
        "late_config",
        "encoding_drift",
    }
    if case == "generation_one":
        sealed = b"sealed\n"
        item = core.CodingWorkerSealedSegmentV1(
            0, 1, 1, len(sealed), hashlib.sha256(sealed).hexdigest()
        )
        manifest = core.CodingWorkerSegmentManifestV1(stem, 1, (item,))
        history = core.CodingWorkerSegmentedHistoryV1(manifest, (sealed, raw))
        last = 2
    else:
        history = core.CodingWorkerSegmentedHistoryV1(None, (raw,))
        last = 1
    active = history.active_generation
    data = {active: raw}
    heads = {active: raw}
    before_codec, after_codec, before_format, after_format = (
        object(),
        object(),
        object(),
        object(),
    )
    before_durable, after_durable = object(), object()
    for target in value_modules:
        for name in ("_CODEC", "WORKER_ATTEMPT_JOURNAL_CODEC"):
            if hasattr(target, name):
                patch.setattr(target, name, before_codec)
        for name in ("_FORMAT", "SORTED_UNICODE_JSONL_FORMAT"):
            if hasattr(target, name):
                patch.setattr(target, name, before_format)
    cap = 1 if need_seal and case != "seal_bytes" else 100
    size = len(raw) + len(line) - 1 if case == "seal_bytes" else 1024
    for target in value_modules:
        for name in ("_MAX_EVENTS", "_MAX_RECEIPTS", "_MAX_RECORDS", "_MAX_REVISIONS"):
            if hasattr(target, name):
                patch.setattr(target, name, cap)
        for name in ("_MAX_BYTES", "_MAX_SEGMENT_BYTES", "_MAX_RECEIPT_SEGMENT_BYTES"):
            if hasattr(target, name):
                patch.setattr(target, name, size)

    class Owner:
        _path = (
            Path.cwd()
            / "inert"
            / ("custom.jsonl" if case == "legacy_name" else stem + ".jsonl")
        )
        _durability = before_durable
        _error_type = getattr(
            value_module,
            "CodingWorkerOptInJournalError",
            getattr(
                value_module,
                "CodingWorkerStartGateJournalError",
                getattr(value_module, "CodingWorkerReceiptError", None),
            ),
        )

        @property
        def _record_codec(self):
            return value_module._CODEC

        @property
        def _record_format(self):
            return (
                value_module._FORMAT
                if hasattr(value_module, "_FORMAT")
                else value_module.SORTED_UNICODE_JSONL_FORMAT
            )

        @property
        def path(self):
            trace.append("path")
            return self._path

        def _error(self, message, *, code):
            if kind == "supervisor_journal":
                # Use the inherited domain exception, not a missing module re-export.
                return WorkerSupervisorJournalError(message, code=code, path=self.path)
            return module.WorkerSupervisorJournalError(
                message, code=code, path=self.path
            )

        def _max_history_bytes(self):
            return (
                value_module._MAX_BYTES
                if hasattr(value_module, "_MAX_BYTES")
                else value_module._MAX_SEGMENT_BYTES
                if hasattr(value_module, "_MAX_SEGMENT_BYTES")
                else value_module._MAX_RECEIPT_SEGMENT_BYTES
            )

        def _max_history_records(self):
            for name in (
                "_MAX_RECORDS",
                "_MAX_REVISIONS",
                "_MAX_EVENTS",
                "_MAX_RECEIPTS",
            ):
                if hasattr(value_module, name):
                    return getattr(value_module, name)
            raise AssertionError("original capacity not found")

    owner = Owner()

    class Target:
        def __init__(self, name):
            self.name = name

    class Rooted:
        def sibling(self, name):
            trace.append(["target", name])
            if case == "target":
                raise OSError("target")
            return Target(name)

    rooted = Rooted()

    def seal(actual, **kwargs):
        assert actual is rooted
        assert kwargs == dict(
            stem=stem, stream_id=stem, history=history, last_revision=last
        )
        trace.append("seal")
        if case in {"seal_capacity", "seal_corrupt"}:
            raise core.CodingWorkerHistorySegmentError(
                "coding_worker_segment_capacity"
                if case == "seal_capacity"
                else "coding_worker_segment_head_corrupt"
            )
        if case == "seal_oserror":
            raise OSError("seal")
        data[active + 1] = b""
        heads[active + 1] = b""
        if case in {"late_config", "encoding_drift"}:
            for target in value_modules:
                for name in ("_CODEC", "WORKER_ATTEMPT_JOURNAL_CODEC"):
                    if hasattr(target, name):
                        patch.setattr(target, name, after_codec)
                for name in ("_FORMAT", "SORTED_UNICODE_JSONL_FORMAT"):
                    if hasattr(target, name):
                        patch.setattr(target, name, after_format)
            owner._durability = after_durable

    def append(path, record, **kwargs):
        chosen = active + 1 if need_seal else active
        codec = kwargs["record_codec"]
        fmt = kwargs["format_profile"]
        durable = kwargs["durability"]
        trace.append(
            [
                "append",
                kwargs["bound_file"].name,
                "after" if codec is after_codec else "before",
                "after" if fmt is after_format else "before",
                "after" if durable is after_durable else "before",
            ]
        )
        if case == "append_before":
            raise OSError("append")
        data[chosen] += (
            b"drift\n" if case == "encoding_drift" and codec is after_codec else line
        )
        if case == "append_after":
            raise OSError("append")

    def commit(actual, **kwargs):
        assert actual is rooted
        chosen = active + 1 if need_seal else active
        assert kwargs == dict(
            stem=stem,
            stream_id=stem,
            generation=chosen,
            previous_raw=b"" if need_seal else raw,
            appended_line=line,
        )
        trace.append("commit")
        if case == "commit_before":
            raise OSError("commit")
        expected = kwargs["previous_raw"] + line
        if data[chosen] != expected:
            raise core.CodingWorkerHistorySegmentError(
                "coding_worker_segment_active_changed"
            )
        heads[chosen] = expected
        if case == "commit_after":
            raise OSError("commit")

    patch.setattr(module, "append_jsonl_record", append)
    for target in (module, core):
        for name, fn in [
            ("seal_coding_worker_active_segment", seal),
            ("commit_coding_worker_active_segment", commit),
        ]:
            if hasattr(target, name):
                patch.setattr(target, name, fn)

    class Record:
        record_revision = last + 1

    record = Record()
    error = None
    try:
        run(owner, rooted, history, record, record, line, line, last, last, last, 1)
    except BaseException as exc:
        error = []
        while exc is not None:
            error.append(
                [
                    type(exc).__name__,
                    str(exc),
                    getattr(exc, "code", None),
                    exc.__suppress_context__,
                ]
            )
            exc = exc.__cause__ or exc.__context__
    return dict(
        trace=trace,
        error=error,
        data={str(k): v.hex() for k, v in data.items()},
        heads={str(k): v.hex() for k, v in heads.items()},
    )


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", CASES)
def test_original_worker_append_tails(kind, case, monkeypatch):
    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "worker_append_tails_v2.json").read_text()
    )
    assert observe(kind, case, monkeypatch) == expected[f"{kind}:{case}"]
