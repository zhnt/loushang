"""Freeze the actual cold-read coordinator with controlled effect boundaries."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import ModuleType, SimpleNamespace

import pytest

import loushang.coding.adapters._goal_delegation_report as delegation
import loushang.coding.adapters._goal_work_sources as product
import loushang.harnesswork.integrations.goal_store as core

EVIDENCE = Path(__file__).parent
EXPECTED = EVIDENCE / "fixtures" / "goal_work_sources_v1.jsonl"
CASES = (
    "complete",
    "incomplete",
    "empty",
    "not-submitted",
    "unresolved",
    "recording-missing",
    "not-declared",
    "delegated-only",
    "delegated-parent",
    "binding-mismatch",
    "unsupported-policy",
    "goal-missing",
    "other-goal-conflict",
    "session-mismatch",
    "receipt-mismatch",
    "falsey-receipt",
    "orphaned",
    "active-no-cancel",
    "cancel-unsettled",
    "extra-run",
    "reader-mismatch",
    "root-error",
    "constructor-error",
    "open-error",
    "load-error",
    "query-error",
    "facts-error",
    "recording-error",
    "decoder-error",
    "handoffs-error",
    "bind-error",
    "resolve-error",
    "cancel-bind",
    "cancel-resolve",
    "close-success",
    "close-read-error",
    "close-cancel",
    "view-error",
    "two-batches",
)


def _json(value):
    if dataclasses.is_dataclass(value):
        return {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": {
                f.name: _json(getattr(value, f.name)) for f in dataclasses.fields(value)
            },
        }
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, SimpleNamespace):
        return {key: _json(item) for key, item in vars(value).items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


def _error(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": f"{type(error).__module__}.{type(error).__qualname__}",
        "args": list(error.args),
        "notes": getattr(error, "__notes__", []),
        "suppress": error.__suppress_context__,
        "cause": _error(error.__cause__, seen.copy()),
        "context": _error(error.__context__, seen.copy()),
    }


async def _observe(case):
    trace = []
    state = {
        "store": None,
        "close_attempts": 0,
        "close_fail": case.startswith("close-"),
    }
    entered = asyncio.Event()
    never = asyncio.Event()
    read_failure = OSError(5, "controlled-read")
    close_failure = OSError(5, "controlled-close")
    original_header = product.GoalHeader
    original_view = product.GoalWorkSourceView
    original_path = product.goal_journal_path
    original_journal = product.GoalJournal
    header = original_header("session", "session", product.POLICY_ID)
    if case == "unsupported-policy":
        header = original_header("session", "session", "unsupported")
    batch = SimpleNamespace(
        id="batch-1",
        operation_id="op-1",
        goal_id="g",
        not_submitted=False,
        run_receipt="run-1",
    )
    run = SimpleNamespace(
        operation_id="op-1", run_id="run-1", session_id="session", status="completed"
    )
    batches = [batch]
    runs = [run]
    observations = [SimpleNamespace(run_id="run-1", status="settled")]
    if case == "empty":
        batches, runs = [], []
    if case == "not-submitted":
        batch.not_submitted, runs = True, []
    if case == "unresolved":
        runs = []
    if case == "other-goal-conflict":
        batches.append(
            SimpleNamespace(
                id="other",
                operation_id="op-1",
                goal_id="other",
                not_submitted=True,
                run_receipt=None,
            )
        )
    if case == "session-mismatch":
        run.session_id = "foreign"
    if case == "receipt-mismatch":
        batch.run_receipt = "wrong"
    if case == "falsey-receipt":
        batch.run_receipt = ""
    if case == "orphaned":
        run.status = "orphaned"
    if case == "active-no-cancel":
        run.status, observations = "running", []
    if case == "cancel-unsettled":
        observations[0].status = "requested"
    if case == "extra-run":
        runs.append(
            SimpleNamespace(
                operation_id="extra-op",
                run_id="extra-run",
                session_id="session",
                status="completed",
            )
        )
    if case == "two-batches":
        batches.append(
            SimpleNamespace(
                id="batch-2",
                operation_id="op-2",
                goal_id="g",
                not_submitted=False,
                run_receipt="run-2",
            )
        )
        runs.append(
            SimpleNamespace(
                operation_id="op-2",
                run_id="run-2",
                session_id="session",
                status="completed",
            )
        )
        observations.append(SimpleNamespace(run_id="run-2", status="not_requested"))

    class History:
        def __init__(self):
            self.batches = batches

        def goal(self, goal_id):
            trace.append(["history.goal", goal_id])
            if case == "goal-missing":
                raise product.GoalError("unknown Goal")
            return SimpleNamespace(id=goal_id)

    history = History()

    class Entry:
        def __init__(self, identity):
            self.identity = identity

        @property
        def operation_id(self):
            trace.append(["entry.operation", self.identity])
            return self.identity

    entries = [Entry("op-1"), Entry("extra-op"), Entry("op-2")]

    class Root:
        def resolve(self):
            trace.append(["root.resolve"])
            if case == "root-error":
                raise read_failure
            return PurePosixPath("/model-data")

    class Journal(original_journal):
        def __init__(self, root, initial_header, **kwargs):
            trace.append(["store.construct", str(root), _json(initial_header), kwargs])
            state["store"] = self
            self.opened = self.closed = False
            if case == "constructor-error":
                raise read_failure

        def open(self):
            trace.append(["store.open"])
            if case == "open-error":
                raise read_failure
            self.opened = True

        def load(self):
            trace.append(["store.load"])
            if case == "load-error":
                raise read_failure
            return header, ()

        def close(self):
            state["close_attempts"] += 1
            trace.append(["store.close", state["close_attempts"]])
            if state["close_fail"]:
                raise close_failure
            self.closed = True

    class Reader:
        closed = False

        @property
        def conversation_id(self):
            trace.append(["reader.conversation"])
            return "foreign" if case == "reader-mismatch" else "session"

        async def inspect_identity(self):
            trace.append(["reader.inspect", self.closed])
            assert not self.closed

        async def aclose(self):
            trace.append(["reader.caller_close"])
            self.closed = True

    reader = Reader()

    def make_header(*args):
        trace.append(["header", *args])
        return original_header(*args)

    def replay(*args):
        trace.append(["replay"])
        return history

    def work_path(*args):
        trace.append(["path.policy"])
        return original_path(*args)

    class Log:
        def __init__(self, path):
            trace.append(["log.construct", str(path)])

        def query(self):
            trace.append(["log.query"])
            if case == "query-error":
                raise read_failure
            return entries

    def project_runs(value, **kwargs):
        trace.append(["project.runs", value is entries, kwargs])
        if case == "facts-error":
            raise read_failure
        return runs

    def project_cancellations(value):
        trace.append(["project.cancellations", value is entries])
        return observations

    def recording(value, run_id):
        trace.append(["project.recording", value is entries, run_id])
        if case in {"recording-error", "close-read-error"}:
            raise read_failure
        if case == "recording-missing":
            return None
        return SimpleNamespace(run_id=run_id, payload="original-recording")

    def decode(batch, run, value):
        trace.append(
            ["decode", batch.id, run.run_id, [entry.identity for entry in value]]
        )
        if case == "decoder-error":
            raise read_failure
        return {} if case.startswith("delegated") else None

    class LookupModule(ModuleType):
        def __getattribute__(self, name):
            if name == "decode_selection":
                trace.append(["decoder.lookup"])
            return super().__getattribute__(name)

    def handoffs(recording, value):
        trace.append(["project.handoffs", recording.run_id, value is entries])
        if case == "handoffs-error":
            raise read_failure
        if case in {"not-declared", "delegated-only"}:
            return None
        return SimpleNamespace(
            binding_id="foreign"
            if case == "binding-mismatch"
            else "coding-goal:session",
            retained_until="deadline",
        )

    async def wait_at(where):
        if case in {f"cancel-{where}", "close-cancel"} and where == (
            "bind" if case == "close-cancel" else case.split("-")[1]
        ):
            entered.set()
            try:
                await never.wait()
            except asyncio.CancelledError as error:
                state["read_exception"] = error
                raise

    class Source:
        @classmethod
        async def bind(cls, received_reader, **kwargs):
            trace.append(["source.bind", received_reader is reader, kwargs])
            if case == "bind-error":
                raise read_failure
            await wait_at("bind")
            return SimpleNamespace(reader_marker="borrowed")

    async def resolve(recording, value, *, source):
        trace.append(
            ["source.resolve", recording.run_id, value is entries, _json(source)]
        )
        if case == "resolve-error":
            raise read_failure
        await wait_at("resolve")
        return SimpleNamespace(
            handoffs=SimpleNamespace(complete=case != "incomplete"),
            payload="original-resolution",
        )

    def view(*args):
        trace.append(["view", args[0], args[1], args[2]])
        if case == "view-error":
            raise read_failure
        return original_view(*args)

    replacements = {
        "GoalJournal": Journal,
        "GoalHeader": make_header,
        "replay": replay,
        "goal_journal_path": work_path,
        "JsonlEventLogBackend": Log,
        "project_work_runs": project_runs,
        "project_work_cancellations": project_cancellations,
        "project_work_recording": recording,
        "project_work_transcript": handoffs,
        "WorkTranscriptSource": Source,
        "resolve_work_transcript": resolve,
        "GoalWorkSourceView": view,
    }
    result = {}
    with pytest.MonkeyPatch.context() as patch:
        for module in (product, core):
            for name, value in replacements.items():
                patch.setattr(module, name, value, raising=False)
        patch.setattr(delegation, "__class__", LookupModule)
        patch.setattr(delegation, "decode_selection", decode)
        task = asyncio.create_task(
            product.read_goal_work_sources(
                data_root=Root(),
                session_id="session",
                goal_id="g",
                reader=reader,
            )
        )
        if case in {"cancel-bind", "cancel-resolve", "close-cancel"}:
            await entered.wait()
            task.cancel("controlled-source-cancel")
        try:
            result["views"] = _json(await task)
        except BaseException as error:
            result["failure"] = _error(error)
            if hasattr(error, "owner"):
                result["retained_owner_same"] = error.owner is state["store"]
                result["read_error"] = _error(error.read_error)
                result["read_error_same"] = error.read_error is state.get(
                    "read_exception",
                    read_failure if case == "close-read-error" else None,
                )
                result["cleanup_error_same"] = error.cleanup_error is close_failure
                state["close_fail"] = False
                error.owner.close()
                result["retry_closed_same_owner"] = error.owner.closed
        trace.append(["direct.facts.probe"])
        try:
            result["facts"] = _json(
                product._goal_work_facts(history, entries, "session")
            )
        except BaseException as error:
            result["facts_error"] = _error(error)
        result["borrowed_reader_open"] = not reader.closed
        await reader.inspect_identity()
        await reader.aclose()
    store = state["store"]
    result["store"] = (
        None if store is None else {"opened": store.opened, "closed": store.closed}
    )
    result["close_attempts"] = state["close_attempts"]
    result["trace"] = trace
    return result


def _guard():
    root = Path(__file__).resolve().parents[2]
    for module, name in (
        (product, "src/loushang/coding/adapters/_goal_work_sources.py"),
        (core, "src/loushang/harnesswork/integrations/goal_store.py"),
    ):
        assert Path(module.__file__).resolve() == root / name


_RECORDS = [json.loads(line) for line in EXPECTED.read_text().splitlines()[1:]]


@pytest.mark.parametrize("record", _RECORDS, ids=lambda record: record["case"])
def test_replay(record):
    _guard()
    assert asyncio.run(_observe(record["case"])) == record["result"]
