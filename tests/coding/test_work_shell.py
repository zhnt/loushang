from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.coding.adapters import _goal_driver as driver
from loushang.coding.adapters._goal_calculator import inventory
from loushang.coding.adapters.goal import CodingGoal, inspect_goal
from loushang.coding.adapters.harnesswork import create_coding_work_runtime
from loushang.harness.events import RuntimeEvent
from loushang.harnesswork.event_log import EventLogBackend
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.integrations.session import (
    SessionWorkRuntime,
    SessionWorkTurn,
)


def _verification_owner(
    tmp_path, *, result=None, policy=None, backend=None, session_id="session-1"
):
    from loushang.coding.adapters._verification_work import CodingVerificationWork
    from loushang.harness.artifacts import SessionBlobStore
    from loushang.harnesswork import InMemoryEventLogBackend

    class CommandSession:
        async def execute_bash(self, command):
            assert command == "check-project"
            return (
                {
                    "exit_code": 0,
                    "output": "checked\n",
                    "cancelled": False,
                    "truncated": False,
                    "stdio_complete": True,
                    "stdio_drain_reason": None,
                }
                if result is None
                else result
            )

    session = CommandSession()
    session.session_id = session_id
    store = SessionBlobStore(
        tmp_path / "data", session_id, **({"policy": policy} if policy else {})
    )
    log = backend if backend is not None else InMemoryEventLogBackend()
    return (
        CodingVerificationWork(session=session, blobs=store, event_log=log),
        store,
        log,
    )


@pytest.mark.parametrize(
    "change",
    [
        "version_bool",
        "version_zero",
        "version_future",
        "missing_step",
        "empty_step",
        "wrong_step",
        "empty_role",
        "control_role",
        "bad_blob",
        "extra_blob_field",
        "foreign_blob",
        "extra_evidence_field",
    ],
)
def test_private_evidence_schema_is_strict_and_versioned(tmp_path, change):
    from dataclasses import replace

    from loushang.coding.adapters._work_evidence import (
        EvidenceReplayError,
        UnsupportedEvidenceVersion,
        project_work_evidence,
    )
    from loushang.harnesswork import WorkRunReplayError

    async def scenario():
        work, store, log = _verification_owner(tmp_path)
        await work.run("check-project", run_id="schema")
        history = log.query()
        entry = next(e for e in history if e.payload["kind"] == "WorkEvidenceReported")
        body = dict(entry.payload["payload"]["evidence"])
        if change == "version_bool":
            body["version"] = True
        elif change == "version_zero":
            body["version"] = 0
        elif change == "version_future":
            body = {"version": 2}
        elif change == "missing_step":
            body.pop("reported_step_id")
        elif change == "empty_step":
            body["reported_step_id"] = ""
        elif change == "wrong_step":
            body["reported_step_id"] = []
        elif change == "empty_role":
            body["role"] = ""
        elif change == "control_role":
            body["role"] = "report\n"
        elif change == "bad_blob":
            body["blob"] = None
        elif change == "extra_blob_field":
            body["blob"] = {**body["blob"], "extra": True}
        elif change == "foreign_blob":
            body["blob"] = {**body["blob"], "sessionId": "foreign"}
        elif change == "extra_evidence_field":
            body["extra"] = True
        changed = replace(
            entry, payload={**entry.payload, "payload": {"evidence": body}}
        )
        selected = [changed if item == entry else item for item in history]
        if change == "extra_evidence_field":
            assert project_work_evidence(selected) == project_work_evidence(history)
        else:
            error_type = (
                UnsupportedEvidenceVersion
                if change == "version_future"
                else EvidenceReplayError
            )
            with pytest.raises(error_type):
                project_work_evidence(selected)
        with pytest.raises(WorkRunReplayError):
            project_work_evidence([*selected, selected[-1]])
        operation = replace(
            history[0], payload={**history[0].payload, "kind": "WorkEvidenceReported"}
        )
        assert project_work_evidence([operation]) == ()

    asyncio.run(scenario())


def test_private_evidence_full_reference_and_reader_authority(tmp_path, monkeypatch):
    import math
    from dataclasses import replace

    from loushang.coding.adapters._verification_work import inspect_verification
    from loushang.harness.artifacts import (
        ArtifactSourceRejected,
        SessionBlobRef,
        SessionBlobStore,
    )

    async def scenario():
        work, store, log = _verification_owner(tmp_path)
        await work.run("check-project", run_id="refs")
        view = inspect_verification(log.query(), run_id="refs", blobs=store)
        ref = view.records[0].blob
        assert store.read_bytes(
            SessionBlobRef.from_manifest_entry(ref.manifest_entry())
        )
        for changed in [
            replace(ref, created_at=math.nextafter(ref.created_at, math.inf)),
            replace(ref, source="different"),
        ]:
            with pytest.raises(ArtifactSourceRejected):
                store.read_bytes(changed)
        with pytest.raises(ValueError, match="another Session"):
            inspect_verification(
                log.query(),
                run_id="refs",
                blobs=SessionBlobStore(tmp_path / "data", "foreign"),
            )
        busy = BlockingIOError("busy")

        def fail_inspection(*args):
            raise busy

        monkeypatch.setattr(store, "inspect", fail_inspection)
        with pytest.raises(BlockingIOError) as caught:
            inspect_verification(log.query(), run_id="refs", blobs=store)
        assert caught.value is busy

    asyncio.run(scenario())


@pytest.mark.parametrize("missing", ["truncated", "cancelled", "stdio_complete"])
def test_verification_requires_explicit_sdk_completeness_flags(tmp_path, missing):
    async def scenario():
        result = {
            "exit_code": 0,
            "output": "tail",
            "cancelled": False,
            "truncated": False,
            "stdio_complete": True,
        }
        result.pop(missing)
        work, store, log = _verification_owner(tmp_path, result=result)
        with pytest.raises(ValueError, match="explicitly report"):
            await work.run("check-project", run_id="unknown-output")
        assert work.runtime.get_run("unknown-output").status == "failed"
        assert store.records == ()

    asyncio.run(scenario())


def test_incomplete_exec_drain_survives_tool_sdk_and_fails_verification(tmp_path):
    from loushang.coding.adapters._verification_work import (
        CodingVerificationFailed,
        inspect_verification,
    )
    from loushang.harness.session.bash import bash_result_from_tool_result
    from loushang.harness.tools.workspace.bash import _exec_result_to_tool_result
    from loushang.harness.workspace.exec import ExecResult

    result = bash_result_from_tool_result(
        _exec_result_to_tool_result(
            ExecResult(
                exit_code=0,
                stdout="done",
                stdio_complete=False,
                stdio_drain_reason="idle_timeout",
            )
        )
    )
    assert result["stdio_complete"] is False and result["truncated"] is False
    assert result["stdio_drain_reason"] == "idle_timeout"

    async def scenario():
        work, store, log = _verification_owner(tmp_path, result=result)
        with pytest.raises(CodingVerificationFailed):
            await work.run("check-project", run_id="incomplete")
        view = inspect_verification(log.query(), run_id="incomplete", blobs=store)
        assert view.passed is False and view.run.status == "failed"
        assert len(view.records) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "complete,reason", [(None, None), (1, None), ("true", None), (True, "idle_timeout")]
)
def test_verification_does_not_infer_stdio_completeness(tmp_path, complete, reason):
    from loushang.coding.adapters._verification_work import (
        CodingVerificationFailed,
        inspect_verification,
    )

    async def scenario():
        result = {
            "exit_code": 0,
            "output": "tail",
            "cancelled": False,
            "truncated": False,
            "stdio_complete": complete,
            "stdio_drain_reason": reason,
        }
        work, store, log = _verification_owner(tmp_path, result=result)
        with pytest.raises(
            CodingVerificationFailed if complete is True else ValueError
        ):
            await work.run("check-project", run_id="unknown-stdio")
        view = inspect_verification(log.query(), run_id="unknown-stdio", blobs=store)
        assert view.passed is not True and view.run.status == "failed"

    asyncio.run(scenario())


def test_one_retained_stream_does_not_prove_both_streams_complete(tmp_path):
    from loushang.coding.adapters._verification_work import (
        CodingVerificationFailed,
        inspect_verification,
    )
    from loushang.harness.artifacts import SessionBlobStore

    store = SessionBlobStore(tmp_path / "data", "session-1")
    stdout = store.put_bytes(
        b"stdout", logical_name="stdout", kind="command-stdout", media_type="text/plain"
    )

    async def scenario():
        work, store, log = _verification_owner(
            tmp_path,
            result={
                "exit_code": 0,
                "output": "stdout plus stderr",
                "cancelled": False,
                "truncated": False,
                "stdio_complete": True,
                "stdio_drain_reason": None,
                "stdout_blob": stdout.manifest_entry(),
            },
        )
        with pytest.raises(CodingVerificationFailed):
            await work.run("check-project", run_id="partial-stream")
        assert (
            inspect_verification(
                log.query(), run_id="partial-stream", blobs=store
            ).passed
            is False
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["command", "digest", "passed", "single_stream"])
def test_verification_consumer_rechecks_document_bindings(tmp_path, change):
    from dataclasses import replace

    from loushang.coding.adapters._verification_work import inspect_verification
    from loushang.coding.adapters._work_evidence import work_evidence_fact

    async def scenario():
        work, store, log = _verification_owner(tmp_path)
        await work.run("check-project", run_id="bindings")
        history = log.query()
        original = inspect_verification(history, run_id="bindings", blobs=store)
        report, validation = [
            json.loads(store.read_bytes(r.blob)) for r in original.records
        ]
        if change == "command":
            report["command"] = "another-check"
        elif change == "single_stream":
            report["output_basis"] = "sdk-retained-streams"
        report_ref = store.put_bytes(
            json.dumps(report).encode(),
            logical_name="replacement-report",
            kind="coding-report",
            media_type="application/json",
        )
        validation["report_sha256"] = (
            "0" * 64 if change == "digest" else report_ref.sha256
        )
        if change == "passed":
            validation["passed"] = False
        validation_ref = store.put_bytes(
            json.dumps(validation).encode(),
            logical_name="replacement-validation",
            kind="coding-validation",
            media_type="application/json",
        )
        replacements = dict(
            zip(
                [r.sequence for r in original.records],
                [report_ref, validation_ref],
                strict=True,
            )
        )
        altered = []
        for entry in history:
            if entry.sequence in replacements:
                role = (
                    "report"
                    if entry.sequence == original.records[0].sequence
                    else "validation"
                )
                payload = work_evidence_fact(
                    replacements[entry.sequence], role=role, reported_step_id="GHOST"
                ).payload
                entry = replace(entry, payload={**entry.payload, "payload": payload})
            altered.append(entry)
        view = inspect_verification(altered, run_id="bindings", blobs=store)
        assert view.passed is None and "verification_mismatch" in view.issues

    asyncio.run(scenario())


@pytest.mark.parametrize("terminal", ["WorkRunFailed", "WorkRunCancelled"])
def test_successful_materials_do_not_override_noncompleted_work(tmp_path, terminal):
    from dataclasses import replace

    from loushang.coding.adapters._verification_work import inspect_verification

    async def scenario():
        work, store, log = _verification_owner(tmp_path)
        await work.run("check-project", run_id="terminal")
        history = log.query()
        last = history.pop()
        if terminal == "WorkRunCancelled":
            history.append(
                replace(
                    last,
                    sequence=last.sequence,
                    event_id="cancelling",
                    payload={"kind": "WorkRunCancelling", "payload": {}},
                )
            )
            last = replace(last, sequence=last.sequence + 1)
        history.append(replace(last, payload={**last.payload, "kind": terminal}))
        view = inspect_verification(history, run_id="terminal", blobs=store)
        assert view.passed is None and "work_not_completed" in view.issues

    asyncio.run(scenario())


def test_cancelling_verification_uses_original_work_control(tmp_path):
    from loushang.coding.adapters._verification_work import (
        CodingVerificationWork,
        inspect_verification,
    )
    from loushang.harness.artifacts import SessionBlobStore
    from loushang.harnesswork import InMemoryEventLogBackend

    async def scenario():
        started = asyncio.Event()

        class Session:
            session_id = "session-1"

            async def execute_bash(self, command):
                started.set()
                await asyncio.Event().wait()

        store, log = (
            SessionBlobStore(tmp_path / "data", "session-1"),
            InMemoryEventLogBackend(),
        )
        work = CodingVerificationWork(session=Session(), blobs=store, event_log=log)
        task = asyncio.create_task(work.run("blocked", run_id="cancel"))
        await started.wait()
        assert (await work.runtime.cancel("cancel")).status == "cancelled"
        with pytest.raises(asyncio.CancelledError):
            await task
        view = inspect_verification(log.query(), run_id="cancel", blobs=store)
        assert view.passed is None and not view.records
        assert work.runtime.get_cancellation("cancel").status == "unsupported"

    asyncio.run(scenario())


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(
    sys.platform != "linux", reason="first local owned-SDK delivery is Linux"
)
def test_real_coding_sdk_verification_consumes_and_reopens_evidence(
    tmp_path, monkeypatch
):
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import create_agent_session_runtime
    from loushang.coding.adapters._verification_work import (
        CodingVerificationWork,
        inspect_verification,
    )
    from loushang.harness.artifacts import SessionBlobStore
    from loushang.harnesswork import JsonlEventLogBackend

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    workspace = tmp_path / "project"
    workspace.mkdir(mode=0o700)
    (workspace / "test_project.py").write_text(
        "import unittest\nclass ProjectCheck(unittest.TestCase):\n"
        "    def test_result(self): self.assertEqual(sum([2, 3]), 5)\n",
        encoding="utf-8",
    )
    data = tmp_path / "data"
    path = tmp_path / "work.jsonl"

    async def scenario():
        sdk = create_agent_session_runtime(
            session_dir=data / "sessions",
            model=Model(
                id="offline",
                name="Offline",
                provider="offline",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    input=("text",), context_window=128000, max_tokens=1024
                ),
            ),
            system_prompt="Local verification only; no model invocation.",
        )
        try:
            session = await sdk.create_session(cwd=str(workspace))
            store = SessionBlobStore(data, session.session_id)
            work = CodingVerificationWork(
                session=session, blobs=store, event_log=JsonlEventLogBackend(path)
            )
            command = shlex.join(
                [sys.executable, "-m", "unittest", "discover", "-s", "."]
            )
            run = await work.run(command, operation_id="check-1", run_id="check-1")
            view = inspect_verification(
                work.runtime.query(), run_id=run.run_id, blobs=store
            )
            assert view.passed is True and view.run.status == "completed"
            assert [record.role for record in view.records] == ["report", "validation"]
            assert all(h.state == "available" for h in view.health)
            report, validation = [
                json.loads(store.read_bytes(r.blob)) for r in view.records
            ]
            assert validation["report_sha256"] == view.records[0].blob.sha256
            output = view.health[-1].reference
            assert b"Ran 1 test" in store.read_bytes(output)
            assert b"OK" in store.read_bytes(output)
            return session.session_id, view.records, output
        finally:
            await sdk.dispose_session_runtime()

    session_id, records, output = asyncio.run(scenario())
    store = SessionBlobStore(data, session_id)
    cold = JsonlEventLogBackend(path)
    reopened = inspect_verification(cold.query(), run_id="check-1", blobs=store)
    assert reopened.passed is True and reopened.records == records
    original = store.read_bytes(output)
    object_path = store.objects_root / output.blob_id
    object_path.write_bytes(b"X" + original[1:])
    corrupt = inspect_verification(cold.query(), run_id="check-1", blobs=store)
    assert corrupt.passed is None and "output_unavailable" in corrupt.issues
    assert corrupt.health[-1].state == "corrupt"
    object_path.write_bytes(original)
    object_path.unlink()
    missing = inspect_verification(cold.query(), run_id="check-1", blobs=store)
    assert missing.passed is None and missing.health[-1].state == "missing"
    assert missing.run.status == "completed"  # availability doesn't rewrite history


@pytest.mark.parametrize(
    "result",
    [
        {
            "exit_code": 2,
            "output": "failed",
            "cancelled": False,
            "truncated": False,
            "stdio_complete": True,
        },
        {
            "exit_code": 0,
            "output": "tail",
            "cancelled": False,
            "truncated": True,
            "stdio_complete": True,
        },
        {
            "exit_code": 0,
            "output": "view",
            "cancelled": False,
            "truncated": False,
            "stdio_complete": True,
            "stdio_drain_reason": None,
            "artifact_retention_error": "not retained",
        },
    ],
)
def test_verification_failure_is_not_a_successful_work(tmp_path, result):
    from loushang.coding.adapters._verification_work import (
        CodingVerificationFailed,
        inspect_verification,
    )

    async def scenario():
        work, store, log = _verification_owner(tmp_path, result=result)
        with pytest.raises(CodingVerificationFailed):
            await work.run("check-project", run_id="failed")
        view = inspect_verification(log.query(), run_id="failed", blobs=store)
        assert view.run.status == "failed" and view.passed is False
        assert [r.role for r in view.records] == ["report", "validation"]

    asyncio.run(scenario())


def test_verification_reuses_original_output_refs_without_copying(tmp_path):
    from loushang.coding.adapters._verification_work import inspect_verification
    from loushang.harness.artifacts import SessionBlobStore

    store = SessionBlobStore(tmp_path / "data", "session-1")
    stdout = store.put_bytes(
        b"retained",
        logical_name="stdout.log",
        kind="command-stdout",
        media_type="text/plain",
    )
    stderr = store.put_bytes(
        b"", logical_name="stderr.log", kind="command-stderr", media_type="text/plain"
    )

    async def scenario():
        work, store, log = _verification_owner(
            tmp_path,
            result={
                "exit_code": 0,
                "output": "tail",
                "cancelled": False,
                "truncated": True,
                "stdio_complete": True,
                "stdio_drain_reason": None,
                "stdout_blob": stdout.manifest_entry(),
                "stderr_blob": stderr.manifest_entry(),
            },
        )
        await work.run("check-project", run_id="reuse")
        view = inspect_verification(log.query(), run_id="reuse", blobs=store)
        report = json.loads(store.read_bytes(view.records[0].blob))
        assert view.passed is True and report["output_basis"] == "sdk-retained-streams"
        assert report["outputs"] == [stdout.manifest_entry(), stderr.manifest_entry()]
        assert len(store.records) == 4  # original two + report + validation only

    asyncio.run(scenario())


def test_validation_quota_failure_keeps_report_and_fails_work(tmp_path):
    from loushang.coding.adapters._verification_work import inspect_verification
    from loushang.harness.artifacts import ArtifactStoreQuotaExceeded, SessionBlobPolicy

    async def scenario():
        work, store, log = _verification_owner(
            tmp_path, policy=SessionBlobPolicy(max_blobs=2)
        )
        with pytest.raises(ArtifactStoreQuotaExceeded):
            await work.run("check-project", run_id="quota")
        view = inspect_verification(log.query(), run_id="quota", blobs=store)
        assert view.run.status == "failed" and view.passed is None
        assert [r.role for r in view.records] == ["report"]
        assert store.read_bytes(view.records[0].blob)
        assert len(store.records) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("after_write", [False, True])
def test_evidence_append_failure_preserves_error_and_durable_bytes(
    tmp_path, after_write
):
    from loushang.coding.adapters._work_evidence import project_work_evidence
    from loushang.harnesswork import JsonlEventLogBackend

    error = OSError("injected append failure")

    class Backend(JsonlEventLogBackend):
        def append(self, entry):
            if entry.payload["kind"] == "WorkEvidenceReported":
                if after_write:
                    super().append(entry)
                raise error
            return super().append(entry)

    path = tmp_path / "work.jsonl"

    async def scenario():
        work, store, log = _verification_owner(tmp_path, backend=Backend(path))
        with pytest.raises(OSError) as caught:
            await work.run("check-project", run_id="write-failed")
        assert caught.value is error
        assert len(store.records) == 2
        assert work.runtime.get_run("write-failed").status == "failed"

    asyncio.run(scenario())
    assert len(project_work_evidence(JsonlEventLogBackend(path).query())) == int(
        after_write
    )


@pytest.mark.parametrize(
    "key",
    [
        "plan_id",
        "step_id",
        "method_id",
        "error",
        "deviation",
        "step_index",
        "audit_policy",
        "planned_constraint",
        "plan_facts",
        "step_facts",
        "step_title",
        "other",
    ],
)
def test_evidence_guard_rejects_every_extra_top_level_key(tmp_path, key):
    from dataclasses import replace

    from loushang.coding.adapters._work_evidence import (
        EvidenceReplayError,
        project_work_evidence,
        validate_evidence_fact,
        work_evidence_fact,
    )

    async def scenario():
        work, store, log = _verification_owner(tmp_path)
        await work.run("check-project", run_id="guard")
        history = log.query()
        record, _ = project_work_evidence(history)
        fact = work_evidence_fact(record.blob, role="report", reported_step_id="report")
        dirty = replace(fact, payload={**fact.payload, key: "GHOST"})
        with pytest.raises(EvidenceReplayError, match="top-level"):
            validate_evidence_fact(dirty, session_id="session-1")
        entry = next(e for e in history if e.sequence == record.sequence)
        changed = replace(entry, payload={**entry.payload, "payload": dirty.payload})
        with pytest.raises(EvidenceReplayError, match="top-level"):
            project_work_evidence([changed if e == entry else e for e in history])

    asyncio.run(scenario())


def test_evidence_legacy_references_remain_edges_not_duplicate_reports(tmp_path):
    from dataclasses import replace

    from loushang.coding.adapters._work_evidence import (
        deviation_support,
        project_work_evidence,
    )

    async def scenario():
        work, store, log = _verification_owner(
            tmp_path, session_id="legacy logical session"
        )
        await work.run("check-project", run_id="legacy")
        history = log.query()
        completed = next(e for e in history if e.payload["kind"] == "WorkStepCompleted")
        changed = replace(
            completed,
            payload={
                **completed.payload,
                "payload": {
                    **completed.payload["payload"],
                    "deviation": {
                        "type": "adapted",
                        "reason": "legacy",
                        "evidence_refs": ["report-note", "unknown-path"],
                    },
                },
            },
        )
        history = [changed if e == completed else e for e in history]
        records = project_work_evidence(history)
        support = deviation_support(
            history, records, bindings={"report-note": records[0].key}
        )
        assert len(records) == 2 and len(support) == 2
        assert support[0].target == records[0].key and support[1].target is None
        assert support[1].reference == "unknown-path"
        assert records[0].session_id == "legacy logical session"
        assert records[0].blob.session_id == store.session_id

    asyncio.run(scenario())


class FakePromptSession:
    def __init__(
        self, events: list[dict[str, object]], *, error: Exception | None = None
    ) -> None:
        self.events = events
        self.error = error
        self.prompts: list[str] = []
        self.listeners: list[
            Callable[[RuntimeEvent[object]], Awaitable[None] | None]
        ] = []

    def subscribe_runtime_events(
        self,
        listener: Callable[[RuntimeEvent[object]], Awaitable[None] | None],
    ) -> Callable[[], None]:
        self.listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self.listeners:
                self.listeners.remove(listener)

        return unsubscribe

    async def prompt(self, text: str) -> None:
        self.prompts.append(text)
        if self.error is not None:
            raise self.error
        for sequence, payload in enumerate(self.events, start=1):
            event = RuntimeEvent(
                event_id=f"event-{sequence}",
                kind=f"agent.{payload['type']}",
                stream_id="session:test",
                sequence=sequence,
                occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
                payload=payload,
            )
            for listener in list(self.listeners):
                result = listener(event)
                if result is not None:
                    await result


def _create_work_runtime(
    *,
    session: object,
    event_log: EventLogBackend,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SessionWorkRuntime:
    return create_coding_work_runtime(
        session=session,
        event_log=event_log,
        clock=clock,
    )


async def _submit_turn(
    runtime: SessionWorkRuntime,
    text: str,
    *,
    session_id: str,
    operation_id: str,
    run_id: str,
    images: Sequence[object] | None = None,
    method_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    step_index: int | None = None,
    step_title: str | None = None,
    planned_constraint: Mapping[str, object] | None = None,
    audit_policy: Mapping[str, object] | None = None,
    plan_facts: Mapping[str, object] | None = None,
    step_facts: Mapping[str, object] | None = None,
):
    return await runtime.submit_turn(
        SessionWorkTurn(
            text=text,
            images=images,
            method_id=method_id,
            plan_id=plan_id,
            step_id=step_id,
            step_index=step_index,
            step_title=step_title,
            planned_constraint=planned_constraint,
            audit_policy=audit_policy,
            plan_facts=plan_facts,
            step_facts=step_facts,
        ),
        session_id=session_id,
        operation_id=operation_id,
        run_id=run_id,
    )


def test_session_work_runtime_logs_coding_operation_and_projected_events() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(
            events=[
                {
                    "type": "message_update",
                    "message": {"role": "assistant"},
                    "assistant_message_event": {"type": "text_delta", "text": "done"},
                },
                {
                    "type": "tool_execution_end",
                    "tool_call_id": "tool-1",
                    "tool_name": "pytest",
                    "result": {"output": "passed"},
                    "is_error": False,
                },
            ],
        )
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        run = await _submit_turn(
            work_runtime,
            "fix this bug",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        assert session.prompts == ["fix this bug"]
        assert run.status == "completed"
        assert len(session.listeners) == 0

        entries = event_log.query(run_id="run-1")
        assert [entry.entry_type for entry in entries] == [
            "operation",
            "event",
            "event",
            "event",
            "event",
        ]
        assert entries[0].payload == {
            "kind": "SubmitCodingTurn",
            "domain": "coding",
            "payload": {"text": "fix this bug"},
            "_harnesswork": {"cancellation_observation_version": 1},
        }
        assert [entry.payload["kind"] for entry in entries[1:]] == [
            "WorkRunStarted",
            "ContentDelta",
            "ToolCallCompleted",
            "WorkRunCompleted",
        ]
        assert entries[2].payload["delivery_hint"] == "coalesce"
        assert entries[3].payload["delivery_hint"] == "coalesce"
        assert entries[4].payload["delivery_hint"] == "immediate"
        assert entries[2].payload["source_event_ref"] == "event-1"
        assert entries[3].payload["source_event_ref"] == "event-2"

    asyncio.run(scenario())


def test_session_work_runtime_projects_custom_messages_with_product_codec() -> None:
    from loushang.harness.transcript import ApplicationMessage
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        message = ApplicationMessage(
            application_message_id="application-1",
            custom_type="review-note",
            content="check this",
            display=True,
            details={"severity": "warning"},
            timestamp=1_780_309_800.0,
        )
        event_log = InMemoryEventLogBackend()
        work_runtime = _create_work_runtime(
            session=FakePromptSession(
                events=[{"type": "message_end", "message": message}]
            ),
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        await _submit_turn(
            work_runtime,
            "review",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        projected = event_log.query(run_id="run-1")[2]
        assert projected.payload["payload"]["message"] == {
            "role": "application",
            "applicationMessageId": "application-1",
            "customType": "review-note",
            "content": "check this",
            "display": True,
            "details": {"severity": "warning"},
            "timestamp": message.timestamp,
            "origin": "application",
            "deliveryMode": "direct",
        }

    asyncio.run(scenario())


def test_session_work_runtime_logs_tool_policy_and_approval_audit_events() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(
            events=[
                {
                    "type": "tool_policy_evaluated",
                    "tool_call_id": "tool-1",
                    "tool_name": "write",
                    "policy_disposition": "ask",
                    "policy_code": "tool_requires_approval",
                    "policy_reason": "Tool write requires approval",
                    "approval_required": True,
                    "argument_keys": ["content", "path"],
                    "path": "/repo/approved.txt",
                },
                {
                    "type": "tool_approval_requested",
                    "tool_call_id": "tool-1",
                    "tool_name": "write",
                    "action_id": "approval-1",
                    "policy_code": "tool_requires_approval",
                    "policy_reason": "Tool write requires approval",
                    "argument_keys": ["content", "path"],
                    "path": "/repo/approved.txt",
                },
                {
                    "type": "tool_approval_resolved",
                    "tool_call_id": "tool-1",
                    "tool_name": "write",
                    "action_id": "approval-1",
                    "approval_decision": "allow",
                    "policy_code": "tool_requires_approval",
                    "policy_reason": "Tool write requires approval",
                },
            ],
        )
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        await _submit_turn(
            work_runtime,
            "write approved file",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "ToolPolicyEvaluated",
            "ToolApprovalRequested",
            "ToolApprovalResolved",
            "WorkRunCompleted",
        ]
        assert entries[2].payload["payload"]["tool_call_id"] == "tool-1"
        assert entries[2].payload["payload"]["policy_disposition"] == "ask"
        assert entries[3].payload["payload"]["action_id"] == "approval-1"
        assert entries[4].payload["payload"]["approval_decision"] == "allow"
        assert entries[2].payload["delivery_hint"] == "immediate"
        assert entries[3].payload["delivery_hint"] == "immediate"
        assert entries[4].payload["delivery_hint"] == "immediate"

    asyncio.run(scenario())


def test_session_work_runtime_jsonl_log_can_replay_persisted_turn(tmp_path) -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.work import JsonlEventLogBackend

    usage = Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )
    assistant = AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="done")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=usage,
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )

    async def scenario() -> None:
        log_path = tmp_path / "events.jsonl"
        session = FakePromptSession(
            events=[
                {
                    "type": "message_update",
                    "message": {"role": "assistant"},
                    "assistant_message_event": {"type": "text_delta", "text": "done"},
                },
                {"type": "message_end", "message": assistant},
            ],
        )
        work_runtime = _create_work_runtime(
            session=session,
            event_log=JsonlEventLogBackend(log_path),
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        run = await _submit_turn(
            work_runtime,
            "persist this turn",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        replayed = JsonlEventLogBackend(log_path).query(run_id=run.run_id)

        assert [entry.payload["kind"] for entry in replayed] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "ContentDelta",
            "ContentDelta",
            "WorkRunCompleted",
        ]
        assert replayed[3].payload["payload"]["message"]["role"] == "assistant"
        assert replayed[4].payload["delivery_hint"] == "immediate"

    asyncio.run(scenario())


def test_session_work_runtime_records_method_id_as_metadata_only() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        run = await _submit_turn(
            work_runtime,
            "fix this bug",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
            method_id="method:task:review",
        )

        assert session.prompts == ["fix this bug"]
        assert run.method_id == "method:task:review"

        entries = event_log.query(run_id="run-1")
        assert entries[0].payload["payload"]["method_id"] == "method:task:review"
        assert entries[1].payload["payload"]["method_id"] == "method:task:review"
        assert entries[2].payload["payload"]["method_id"] == "method:task:review"

    asyncio.run(scenario())


def test_session_work_runtime_records_plan_and_step_lifecycle_events() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )
        plan_facts = {
            "plan_id": "plan:method:task:review",
            "method_id": "method:task:review",
            "mode": "fixed",
        }
        step_facts = {
            "step_id": "inspect",
            "title": "Inspect current changes",
            "step_index": 0,
            "step_count": 2,
        }

        run = await _submit_turn(
            work_runtime,
            "inspect current changes",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
            method_id="method:task:review",
            plan_id="plan:method:task:review",
            step_id="inspect",
            step_index=0,
            step_title="Inspect current changes",
            planned_constraint={"level": "reasoned", "requires_reason": True},
            audit_policy={"record": ["status", "reason"]},
            plan_facts=plan_facts,
            step_facts=step_facts,
        )

        assert run.status == "completed"
        assert run.method_id == "method:task:review"
        assert run.plan_id == "plan:method:task:review"
        assert run.current_step_id == "inspect"

        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepCompleted",
            "WorkPlanCompleted",
            "WorkRunCompleted",
        ]
        assert entries[0].payload["payload"] == {
            "text": "inspect current changes",
            "method_id": "method:task:review",
            "plan_id": "plan:method:task:review",
            "step_id": "inspect",
            "step_index": 0,
            "step_title": "Inspect current changes",
            "planned_constraint": {"level": "reasoned", "requires_reason": True},
            "audit_policy": {"record": ["status", "reason"]},
            "plan_facts": plan_facts,
            "step_facts": step_facts,
        }
        assert entries[2].payload["delivery_hint"] == "coalesce"
        assert entries[3].payload["delivery_hint"] == "coalesce"
        assert entries[4].payload["delivery_hint"] == "coalesce"
        assert entries[5].payload["delivery_hint"] == "final_only"
        assert entries[3].payload["payload"] == {
            "source_type": "work_shell",
            "method_id": "method:task:review",
            "plan_id": "plan:method:task:review",
            "step_id": "inspect",
            "step_index": 0,
            "step_title": "Inspect current changes",
            "planned_constraint": {"level": "reasoned", "requires_reason": True},
            "audit_policy": {"record": ["status", "reason"]},
            "plan_facts": plan_facts,
            "step_facts": step_facts,
        }
        assert entries[2].payload["payload"]["plan_facts"] == plan_facts
        assert entries[2].payload["payload"]["step_facts"] == step_facts
        assert entries[4].payload["payload"]["plan_facts"] == plan_facts
        assert entries[4].payload["payload"]["step_facts"] == step_facts
        assert entries[5].payload["payload"]["plan_facts"] == plan_facts
        assert entries[5].payload["payload"]["step_facts"] == step_facts

    asyncio.run(scenario())


def test_session_work_runtime_always_emits_plan_boundaries_for_a_planned_run() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        run = await _submit_turn(
            work_runtime,
            "verify current changes",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
            method_id="method:task:review",
            plan_id="plan:method:task:review",
            step_id="verify",
            step_index=1,
            step_title="Run focused checks",
        )

        assert run.status == "completed"
        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepCompleted",
            "WorkPlanCompleted",
            "WorkRunCompleted",
        ]

    asyncio.run(scenario())


def test_session_work_runtime_records_complete_plan_failure_lifecycle() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[], error=RuntimeError("middle step failed"))
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )

        try:
            await _submit_turn(
                work_runtime,
                "verify current changes",
                session_id="session-1",
                operation_id="op-1",
                run_id="run-1",
                method_id="method:task:review",
                plan_id="plan:method:task:review",
                step_id="verify",
                step_index=1,
                step_title="Run focused checks",
            )
        except RuntimeError as error:
            assert str(error) == "middle step failed"
        else:
            raise AssertionError("expected prompt failure")

        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepFailed",
            "WorkPlanFailed",
            "WorkRunFailed",
        ]

    asyncio.run(scenario())


def test_session_work_runtime_records_step_and_plan_failures_before_run_failure() -> (
    None
):
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[], error=RuntimeError("agent failed"))
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
            clock=lambda: datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
        )
        plan_facts = {
            "plan_id": "plan:method:task:review",
            "method_id": "method:task:review",
        }
        step_facts = {"step_id": "inspect", "step_index": 0}

        try:
            await _submit_turn(
                work_runtime,
                "inspect current changes",
                session_id="session-1",
                operation_id="op-1",
                run_id="run-1",
                method_id="method:task:review",
                plan_id="plan:method:task:review",
                step_id="inspect",
                step_index=0,
                step_title="Inspect current changes",
                plan_facts=plan_facts,
                step_facts=step_facts,
            )
        except RuntimeError as error:
            assert str(error) == "agent failed"
        else:
            raise AssertionError("expected prompt failure")

        entries = event_log.query(run_id="run-1")
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepFailed",
            "WorkPlanFailed",
            "WorkRunFailed",
        ]
        assert entries[4].payload["delivery_hint"] == "immediate"
        assert entries[5].payload["delivery_hint"] == "immediate"
        assert entries[4].payload["payload"]["error"] == "agent failed"
        assert entries[5].payload["payload"]["error"] == "agent failed"
        assert entries[4].payload["payload"]["plan_facts"] == plan_facts
        assert entries[4].payload["payload"]["step_facts"] == step_facts
        assert entries[5].payload["payload"]["plan_facts"] == plan_facts
        assert entries[5].payload["payload"]["step_facts"] == step_facts
        assert entries[6].payload["payload"]["method_id"] == "method:task:review"
        assert entries[6].payload["payload"]["plan_id"] == "plan:method:task:review"
        assert entries[6].payload["payload"]["step_id"] == "inspect"

    asyncio.run(scenario())


def test_session_work_runtime_unsubscribes_on_success_failure_and_cancellation() -> (
    None
):
    from loushang.work import InMemoryEventLogBackend

    class TrackingSession:
        def __init__(self, outcome: str) -> None:
            self.outcome = outcome
            self.listener = None
            self.prompt_started = asyncio.Event()
            self.unsubscribe_calls = 0

        def subscribe_runtime_events(self, listener):
            self.listener = listener

            def unsubscribe() -> None:
                self.unsubscribe_calls += 1
                self.listener = None

            return unsubscribe

        async def prompt(self, text: str, images=None) -> None:
            del text, images
            self.prompt_started.set()
            if self.outcome == "failure":
                raise RuntimeError("prompt failed")
            if self.outcome == "cancellation":
                await asyncio.Event().wait()

    async def scenario() -> None:
        for outcome in ("success", "failure", "cancellation"):
            event_log = InMemoryEventLogBackend()
            session = TrackingSession(outcome)
            work_runtime = _create_work_runtime(
                session=session,
                event_log=event_log,
            )
            task = asyncio.create_task(
                _submit_turn(
                    work_runtime,
                    outcome,
                    session_id="session-1",
                    operation_id=f"op-{outcome}",
                    run_id=f"run-{outcome}",
                )
            )
            await session.prompt_started.wait()
            if outcome == "cancellation":
                task.cancel()
            try:
                await task
            except RuntimeError:
                assert outcome == "failure"
            except asyncio.CancelledError:
                assert outcome == "cancellation"

            assert session.unsubscribe_calls == 1
            assert session.listener is None
            entries = event_log.query(run_id=f"run-{outcome}")
            terminal_kinds = {
                "WorkRunCompleted",
                "WorkRunFailed",
                "WorkRunCancelled",
            }
            assert (
                sum(entry.payload["kind"] in terminal_kinds for entry in entries) == 1
            )
            assert entries[-1].payload["kind"] in terminal_kinds

    asyncio.run(scenario())


def test_session_work_runtime_runs_method_plan_as_one_sequential_run() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
        )
        turns = (
            SessionWorkTurn(
                text="inspect",
                method_id="method-1",
                plan_id="plan-1",
                step_id="step-1",
                step_index=0,
                step_title="Inspect",
            ),
            SessionWorkTurn(
                text="verify",
                method_id="method-1",
                plan_id="plan-1",
                step_id="step-2",
                step_index=1,
                step_title="Verify",
            ),
        )

        run = await work_runtime.submit_plan(
            turns,
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        assert run.status == "completed"
        assert session.prompts == ["inspect", "verify"]
        entries = event_log.query(run_id="run-1")
        assert {entry.run_id for entry in entries} == {"run-1"}
        assert [entry.payload["kind"] for entry in entries] == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "WorkPlanStarted",
            "WorkStepStarted",
            "WorkStepCompleted",
            "WorkStepStarted",
            "WorkStepCompleted",
            "WorkPlanCompleted",
            "WorkRunCompleted",
        ]

    asyncio.run(scenario())


def test_session_work_runtime_reuses_one_session_scoped_work_runtime() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        session = FakePromptSession(events=[])
        work_runtime = _create_work_runtime(
            session=session,
            event_log=event_log,
        )

        first = await _submit_turn(
            work_runtime,
            "first",
            session_id="session-1",
            operation_id="op-first",
            run_id="run-first",
        )
        second = await _submit_turn(
            work_runtime,
            "second",
            session_id="session-1",
            operation_id="op-second",
            run_id="run-second",
        )

        assert first.status == second.status == "completed"
        assert work_runtime.work_runtime.get_run_for_operation("op-first") == first
        assert work_runtime.work_runtime.get_run_for_operation("op-second") == second
        assert event_log.checkpoint().offset == 6

    asyncio.run(scenario())


def test_agent_start_and_end_are_non_terminal_invocation_facts() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        work_runtime = _create_work_runtime(
            session=FakePromptSession(
                events=[
                    {"type": "agent_start"},
                    {"type": "agent_end", "messages": []},
                ]
            ),
            event_log=event_log,
        )

        await _submit_turn(
            work_runtime,
            "run",
            session_id="session-1",
            operation_id="op-1",
            run_id="run-1",
        )

        kinds = [entry.payload["kind"] for entry in event_log.query(run_id="run-1")]
        assert kinds == [
            "SubmitCodingTurn",
            "WorkRunStarted",
            "AgentInvocationStarted",
            "AgentInvocationCompleted",
            "WorkRunCompleted",
        ]
        assert kinds.count("WorkRunStarted") == 1
        assert kinds.count("WorkRunCompleted") == 1

    asyncio.run(scenario())


# Reviewed optional Goal contracts and finite Coding acceptance.
_GOAL_FIXTURE = Path(__file__).resolve().parents[2] / "examples/coding/goal_calculator"


def _planning_proposal(**changes):
    return {
        "next_action": "check",
        "targets": ["subtraction"],
        "requirement_ids": ["R-SUB"],
        "rationale": "Measure the current implementation before choosing a repair.",
        "expected_evidence": ["report", "validation"],
        "remaining_route": [
            {"action": "check", "targets": ["subtraction"]},
            {"action": "repair", "targets": ["calculator"]},
            {"action": "verify_all", "targets": []},
        ],
        "change_reason": "",
        "evidence_refs": [],
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"goal_id": "forged"},
        {"version": True},
        {"next_action": "bash"},
        {"targets": ["../../calculator.py"]},
        {"targets": ["subtraction", "subtraction"]},
        {"targets": "subtraction"},
        {"requirement_ids": []},
        {"requirement_ids": ["R-SUB", "NEW-REQUIREMENT"]},
        {"expected_evidence": []},
        {"evidence_refs": ["foreign-run:report"]},
        {"remaining_route": [{"action": "repair", "targets": ["calculator"]}]},
        {"remaining_route": [{"action": "check", "targets": ["subtraction"]}] * 7},
        {"next_action": "repair", "targets": ["subtraction"]},
        {"next_action": "verify_all", "targets": ["subtraction"]},
        {"rationale": "a" * 2049},
        {"rationale": "\ud800"},
        {"change_reason": float("nan")},
    ],
)
def test_goal_planning_proposal_rejects_authority_and_contract_changes(changes):
    from loushang.coding.adapters._goal_proposal import ProposalRejected, parse_proposal

    with pytest.raises(ProposalRejected):
        parse_proposal(
            json.dumps(_planning_proposal(**changes)).encode(), known_evidence=()
        )


def test_goal_planning_proposal_strict_json_and_semantic_action_identity():
    from loushang.coding.adapters._goal_proposal import (
        Action,
        ProposalRejected,
        parse_proposal,
    )

    raw = json.dumps(_planning_proposal(evidence_refs=["op-1:report"])).encode()
    proposal = parse_proposal(raw, known_evidence=("op-1:report",))
    assert (
        parse_proposal(
            json.dumps(proposal.data()).encode(), known_evidence=proposal.evidence_refs
        )
        == proposal
    )
    assert proposal.action.effect == Action.parse("check", ["clamp"]).effect
    assert proposal.action.effect == Action.parse("verify_all", []).effect
    assert (
        Action.parse("inspect", ["clamp"]).effect
        != Action.parse("inspect", ["subtraction"]).effect
    )
    assert Action.parse("inspect", ["clamp", "subtraction"]) == Action.parse(
        "inspect", ["subtraction", "clamp"]
    )
    for invalid in (
        b'{"next_action":"repair",' + raw[1:],
        b"```json\n" + raw + b"\n```",
        raw + raw,
        b" " * (16 * 1024 + 1),
        b'{"x":' + b"[" * 1500 + b"0" + b"]" * 1500 + b"}",
    ):
        with pytest.raises(ProposalRejected):
            parse_proposal(invalid, known_evidence=("op-1:report",))


def test_goal_planning_stream_allowance_preserves_transport_and_bounds_continuation(
    monkeypatch,
):
    from loushang.agent import is_prepared_request_conformant
    from loushang.ai import CallOptions, RetryOptions
    from loushang.coding.adapters import _goal_planning_limits as limits

    async def scenario():
        received = []
        response = object()

        async def original(model, context, options):
            received.append((model, context, options))
            return response

        monkeypatch.setattr(limits, "stream", original)
        allowance = limits.PlanningCallAllowance()
        assert is_prepared_request_conformant(allowance.stream)
        model, context, cancellation = object(), object(), object()
        options = CallOptions(
            cancellation=cancellation, retry=RetryOptions(max_attempts=3)
        )
        with pytest.raises(limits.PlanningCallLimit, match="outside"):
            await allowance.stream(model, context, options)
        assert received == []
        allowance.enter("plan", "planning")
        assert await allowance.stream(model, context, options) is response
        assert (
            received[0][0] is model
            and received[0][1] is context
            and received[0][2] is options
        )
        # A hallucinated tool continuation cannot make a second provider call.
        with pytest.raises(limits.PlanningCallLimit, match="exhausted"):
            await allowance.stream(model, context, options)
        assert len(received) == 1 and allowance.failed
        allowance.leave("plan")
        with pytest.raises(limits.PlanningCallLimit, match="already failed"):
            allowance.enter("plan", "planning")
        allowance.enter("repair", "repair")
        for _ in range(5):
            await allowance.stream(model, context, options)
        allowance.leave("repair")
        allowance.enter("repair", "repair")
        for _ in range(7):
            await allowance.stream(model, context, options)
        with pytest.raises(limits.PlanningCallLimit, match="exhausted"):
            await allowance.stream(model, context, options)
        assert len(received) == 13  # 1 planning + 12 over both Method steps.
        allowance.leave("repair")
        allowance.enter("new-plan", "planning")
        with pytest.raises(limits.PlanningCallLimit, match="retry"):
            await allowance.stream(
                model, context, CallOptions(retry=RetryOptions(max_attempts=4))
            )
        assert len(received) == 13 and allowance.calls == 0

    asyncio.run(scenario())


def test_goal_planning_stream_cancellation_is_sticky_and_wrong_owner_fences(
    monkeypatch,
):
    from loushang.coding.adapters import _goal_planning_limits as limits

    async def cancelled(*args):
        raise asyncio.CancelledError()

    async def scenario():
        monkeypatch.setattr(limits, "stream", cancelled)
        allowance = limits.PlanningCallAllowance()
        allowance.enter("op", "planning")
        with pytest.raises(asyncio.CancelledError):
            await allowance.stream(None, None)
        assert allowance.failed and allowance.calls == 1
        allowance.leave("op")
        with pytest.raises(limits.PlanningCallLimit):
            allowance.enter("op", "planning")
        with pytest.raises(limits.PlanningCallLimit, match="ownership"):
            allowance.leave("other-op")
        with pytest.raises(limits.PlanningCallLimit):
            allowance.enter("new-op", "planning")
        assert allowance.fenced

    asyncio.run(scenario())


def _planning_response_fixture():
    from types import SimpleNamespace

    from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
    from loushang.harness.conversation.types import ConversationRecord
    from loushang.harness.transcript.model_call import project_model_call_invocations
    from loushang.harness.transcript.model_call_types import ModelCallOutcome
    from loushang.harness.transcript.model_input_types import (
        ModelInputComponent,
        ModelInputComponentReference,
        ModelInputSnapshot,
        hash_model_input_json,
    )

    prompt = "planning operation op-1; input digest abc"
    raw = json.dumps(_planning_proposal()).encode()
    user = UserMessage("user", prompt, 0.0)
    usage = Usage(1, 1, 0, 0, 2, None)
    assistant = AssistantMessage(
        "assistant",
        [TextPart("text", raw.decode())],
        "api",
        "provider",
        "endpoint",
        "model",
        None,
        usage,
        "stop",
        None,
        0.0,
    )
    from loushang.harness.transcript.kinds import (
        MODEL_INPUT_COMPONENT_KIND,
        MODEL_INPUT_PREPARED_KIND,
    )
    from loushang.harness.transcript.model_input import rebuild_model_input

    logical = {
        "system_prompt": "plan",
        "messages": [{"role": "user", "content": prompt}],
        "tools": [],
        "request_options": {},
    }
    prepared = {"messages": logical["messages"]}
    components = []
    refs = {}
    for name, content in {**logical, "model_visible_headers": {}}.items():
        digest = hash_model_input_json(content, name=name)
        refs[name] = ModelInputComponentReference(name, f"component:{name}", digest)
        components.append((f"component:{name}", ModelInputComponent(digest, content)))
    snapshot = ModelInputSnapshot(
        snapshot_id="snapshot",
        invocation_id="invocation",
        attempt=1,
        purpose="main",
        product_id="coding",
        runtime_id="runtime",
        mount_generation=1,
        profile_fingerprint="a" * 64,
        registration_revision="b" * 64,
        conversation_id="session",
        source_leaf_id="user",
        source_revision=1,
        commit_revision=2 + len(components),
        provider_id="provider",
        model_id="model",
        api_id="api",
        endpoint_id="endpoint",
        logical_components=tuple(refs[name] for name in logical),
        prepared_payload_components=(refs["messages"],),
        model_visible_headers_component=refs["model_visible_headers"],
        logical_input_hash=hash_model_input_json(logical, name="logical"),
        prepared_payload_hash=hash_model_input_json(
            {"model_visible_headers": {}, "payload": prepared}, name="prepared"
        ),
    )
    outcome = ModelCallOutcome("invocation", ("snapshot",), "completed", "stop", usage)
    records = []
    parent = None
    for record_id, payload in [
        ("user", user),
        *components,
        ("snapshot", snapshot),
        ("outcome", outcome),
        ("assistant", assistant),
    ]:
        records.append(
            ConversationRecord(
                record_id,
                parent,
                MODEL_INPUT_PREPARED_KIND
                if record_id == "snapshot"
                else MODEL_INPUT_COMPONENT_KIND
                if record_id.startswith("component:")
                else "fixture",
                1,
                "2026-10-26T00:00:00Z",
                payload,
            )
        )
        parent = record_id

    class Manager:
        def rebuild_model_input(self, snapshot_id):
            return rebuild_model_input(
                SimpleNamespace(
                    records=tuple(records),
                    records_to=self.get_branch,
                    header=SimpleNamespace(conversation_id="session"),
                ),
                snapshot_id,
            )

        def get_active_entries(self):
            return list(records)

        def get_model_call_invocations(self):
            return project_model_call_invocations(records)

        def get_branch(self, leaf):
            for index, record in enumerate(records):
                if record.record_id == leaf:
                    return records[: index + 1]
            raise ValueError("record missing")

    events = [
        RuntimeEvent(
            event_id=f"event-{index}",
            kind="agent.message_end",
            stream_id="stream",
            sequence=index + 1,
            occurred_at=datetime.now(UTC),
            payload={"type": "message_end", "message": record.payload},
            session_id="session",
            source_record_id=record.record_id,
        )
        for index, record in enumerate((records[0], records[-1]))
    ]
    return Manager(), records, events, prompt, raw


def test_goal_planning_response_rechecks_original_records_not_last_message():
    from loushang.coding.adapters._goal_planning_response import (
        ResponseBoundary,
        capture_response,
        verify_response,
    )
    from loushang.coding.adapters._goal_proposal import ProposalRejected

    manager, _, events, prompt, raw = _planning_response_fixture()
    returned, proof = capture_response(
        manager,
        ResponseBoundary((), ()),
        session_id="session",
        prompt=prompt,
        events=events,
    )
    assert returned == raw and proof["invocation_id"] == "invocation"
    verify_response(manager, proof, session_id="session", prompt=prompt, raw=raw)
    with pytest.raises(ProposalRejected, match="provenance"):
        verify_response(
            manager,
            {**proof, "invocation_id": "other"},
            session_id="session",
            prompt=prompt,
            raw=raw,
        )
    with pytest.raises(ProposalRejected, match="trusted input"):
        verify_response(
            manager, proof, session_id="session", prompt="other-op", raw=raw
        )


@pytest.mark.parametrize(
    "change",
    [
        "length",
        "tool_block",
        "missing_outcome",
        "wrong_snapshot_session",
        "snapshot_without_user",
        "extra_user",
        "changed_parent",
        "foreign_event",
        "duplicate_event",
        "missing_event",
        "conflicting_event",
        "changed_prefix",
    ],
)
def test_goal_planning_response_refuses_ambiguous_or_unsuccessful_provenance(change):
    from dataclasses import replace

    from loushang.ai.types import ToolCall, UserMessage
    from loushang.coding.adapters._goal_planning_response import (
        ResponseBoundary,
        capture_response,
    )
    from loushang.coding.adapters._goal_proposal import ProposalRejected

    manager, records, events, prompt, _ = _planning_response_fixture()
    boundary = ResponseBoundary((), ())
    snap_index = next(i for i, r in enumerate(records) if r.record_id == "snapshot")
    outcome_index = next(i for i, r in enumerate(records) if r.record_id == "outcome")
    if change == "length":
        records[-1] = replace(
            records[-1], payload=replace(records[-1].payload, stop_reason="length")
        )
        records[outcome_index] = replace(
            records[outcome_index],
            payload=replace(records[outcome_index].payload, stop_reason="length"),
        )
    elif change == "tool_block":
        records[-1] = replace(
            records[-1],
            payload=replace(
                records[-1].payload, content=[ToolCall("toolCall", "tc", "unknown", {})]
            ),
        )
    elif change == "missing_outcome":
        records[-1] = replace(records[-1], parent_id="snapshot")
        records.pop(outcome_index)
    elif change == "wrong_snapshot_session":
        records[snap_index] = replace(
            records[snap_index],
            payload=replace(records[snap_index].payload, conversation_id="foreign"),
        )
    elif change == "snapshot_without_user":
        records[snap_index] = replace(
            records[snap_index],
            payload=replace(records[snap_index].payload, source_leaf_id="unknown"),
        )
    elif change == "extra_user":
        records[-1] = replace(records[-1], parent_id="extra")
        records.insert(
            -1,
            replace(
                records[0],
                record_id="extra",
                parent_id="outcome",
                payload=UserMessage("user", "steer", 0.0),
            ),
        )
    elif change == "changed_parent":
        records[-1] = replace(records[-1], parent_id="user")
    elif change == "foreign_event":
        events[-1] = replace(events[-1], session_id="foreign")
    elif change == "duplicate_event":
        events[-1] = events[0]
    elif change == "missing_event":
        events.pop()
    elif change == "conflicting_event":
        events[-1] = replace(events[-1], payload={"message": "different content"})
    elif change == "changed_prefix":
        boundary = ResponseBoundary(("missing-prefix",), ())
    with pytest.raises(ProposalRejected):
        capture_response(
            manager, boundary, session_id="session", prompt=prompt, events=events
        )


@pytest.mark.parametrize(
    "damage",
    ["missing_component", "component_hash", "snapshot_hash", "origin_revision"],
)
def test_goal_planning_response_rejects_incomplete_actual_model_input(damage):
    from dataclasses import replace

    from loushang.coding.adapters._goal_planning_response import (
        ResponseBoundary,
        capture_response,
    )
    from loushang.coding.adapters._goal_proposal import ProposalRejected

    manager, records, events, prompt, _ = _planning_response_fixture()
    index = next(i for i, r in enumerate(records) if r.record_id == "snapshot")
    if damage == "missing_component":
        records[2] = replace(records[2], parent_id=records[0].record_id)
        records.pop(1)
    elif damage == "component_hash":
        snapshot = records[index].payload
        refs = snapshot.logical_components
        records[index] = replace(
            records[index],
            payload=replace(
                snapshot,
                logical_components=(replace(refs[0], content_hash="0" * 64), *refs[1:]),
            ),
        )
    elif damage == "snapshot_hash":
        records[index] = replace(
            records[index],
            payload=replace(records[index].payload, logical_input_hash="0" * 64),
        )
    else:
        records[index] = replace(
            records[index], payload=replace(records[index].payload, commit_revision=99)
        )
    with pytest.raises(ProposalRejected, match="reconstruction"):
        capture_response(
            manager,
            ResponseBoundary((), ()),
            session_id="session",
            prompt=prompt,
            events=events,
        )


def test_goal_planning_refuses_context_replacement_before_model_or_writer(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from loushang.coding.adapters import goal as module

    calls = []

    class SDK:
        async def create_session(self, **kwargs):
            return SimpleNamespace(
                session_id="session",
                session_manager=SimpleNamespace(get_cwd=lambda: str(tmp_path)),
                extension_runner=SimpleNamespace(
                    has_handlers=lambda name: name == "context"
                ),
            )

        async def dispose_session_runtime(self):
            calls.append("disposed")

    monkeypatch.setattr(module, "create_agent_session_runtime", lambda **kwargs: SDK())
    with pytest.raises(GoalError, match="execution-replacing hooks"):
        asyncio.run(
            CodingGoal.open(
                workspace=tmp_path, data_root=tmp_path / "data", model_planning=True
            )
        )
    assert calls == ["disposed"] and not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "steps",
    [
        "  - inspect\n  - repair\n  - audit",
        "  - repair\n  - inspect",
        "  - repair",
        "step_constraints",
        "step_audit",
    ],
)
def test_goal_planning_refuses_unsupported_method_before_admission(tmp_path, steps):
    from types import SimpleNamespace

    from loushang.coding.adapters._goal_calculator import REQUIREMENTS, initial_metadata
    from loushang.coding.adapters._goal_planning import ModelPlanningPolicy
    from loushang.harness.artifacts import SessionBlobStore
    from loushang.harnesswork.goal import GoalBasis, GoalHeader
    from loushang.harnesswork.goal.records import GoalState

    root = _goal_project(tmp_path)
    method = root / "methods/task/goal-calculator-repair/SKILL.md"
    content = method.read_text()
    if steps.startswith("step_"):
        content = content.replace(
            "plan_mode: fixed",
            f"plan_mode: fixed\n{steps}:\n  repair:\n    unsupported: true",
        )
    else:
        content = content.replace("  - inspect\n  - repair", steps)
    method.write_text(content)
    blobs = SessionBlobStore(tmp_path / "data", "session")
    metadata = initial_metadata(root, blobs)
    policy = ModelPlanningPolicy(
        workspace=root,
        session=SimpleNamespace(),
        blobs=blobs,
        event_log=None,
        prepared={},
        allowance=None,
        tool_policy=None,
        history=None,
    )
    state = GoalState("g", REQUIREMENTS, limit=20, metadata=metadata)
    basis = GoalBasis(GoalHeader("session", "session", policy.policy_id), state, 1)
    before = inventory(root)
    if steps.startswith("step_"):
        from loushang.harnesswork.goal import PolicyStop

        result = policy.prepare_repair(basis, before, {})
        assert isinstance(result, PolicyStop) and "constraint/audit" in result.reason
        assert policy.prepared == {} and inventory(root) == before
        return
    with pytest.raises(GoalError, match="supported inspect/repair"):
        policy.prepare_repair(
            basis, before, {"failures": "actual report supplied by caller"}
        )
    assert policy.prepared == {} and inventory(root) == before


def test_goal_planning_work_uses_original_runtime_and_publishes_bound_evidence(
    tmp_path, monkeypatch
):
    from loushang.coding.adapters import _goal_planning_limits as limits
    from loushang.coding.adapters._goal_planning_work import (
        PlanningToolPolicy,
        PlanningWork,
        ScopedSessionWork,
    )
    from loushang.coding.adapters._work_evidence import project_work_evidence
    from loushang.coding.adapters.harnesswork import (
        CODING_WORK_PROFILE,
        project_coding_runtime_event,
    )
    from loushang.harness.artifacts import SessionBlobStore
    from loushang.harnesswork import (
        InMemoryEventLogBackend,
        WorkRunSpec,
        WorkRuntime,
        WorkStepSpec,
    )
    from loushang.harnesswork.integrations.session import SessionTurnExecutor
    from loushang.harnesswork.ports import WorkExecutionBinding

    async def scenario():
        manager, records, events, prompt, raw = _planning_response_fixture()
        completed = list(records)
        records.clear()
        listeners = []
        allowance = limits.PlanningCallAllowance()

        async def original(*args):
            return object()

        monkeypatch.setattr(limits, "stream", original)

        class Session:
            session_id = "session"
            session_manager = manager
            active = ["read", "edit", "write"]

            def subscribe_runtime_events(self, listener):
                listeners.append(listener)
                return lambda: listeners.remove(listener)

            def get_active_tool_names(self):
                return list(self.active)

            async def set_active_tools(self, tools):
                self.active = list(tools)

            async def prompt(self, text, **kwargs):
                assert text == prompt and self.active == []
                await allowance.stream(None, None)
                records.extend(completed)
                for event in events:
                    for listener in tuple(listeners):
                        await listener(event)

            async def wait_for_idle(self):
                pass

        session = Session()
        tools = PlanningToolPolicy(tmp_path)
        original_executor = SessionTurnExecutor(
            session=session,
            profile=CODING_WORK_PROFILE,
            project_event_facts=project_coding_runtime_event,
            turn=SessionWorkTurn(prompt),
        )
        scoped = ScopedSessionWork(
            original_executor,
            session=session,
            allowance=allowance,
            policy=tools,
            phase="planning",
        )
        blobs = SessionBlobStore(tmp_path / "blobs", "session")
        executor = PlanningWork(
            scoped,
            session=session,
            blobs=blobs,
            allowance=allowance,
            prompt=prompt,
            input_ref={},
            known_evidence=(),
        )

        class Resolver:
            def resolve(self, operation, spec):
                return WorkExecutionBinding(executor, executor)

        log = InMemoryEventLogBackend()
        runtime = WorkRuntime(event_log=log, resolver=Resolver())
        operation = SessionWorkTurn(prompt).to_operation(
            profile=CODING_WORK_PROFILE, session_id="session", operation_id="op-1"
        )
        run = await runtime.accept(
            operation,
            spec=WorkRunSpec(
                plan_id="planning:op-1", steps=(WorkStepSpec("planning"),)
            ),
        )
        settled = await runtime.wait(run.run_id)
        assert settled.status == "completed"
        reports = project_work_evidence(log.query())
        assert len(reports) == 1 and reports[0].operation_id == "op-1"
        report = json.loads(blobs.read_bytes(reports[0].blob))
        assert report["rejection"] is None
        assert report["proposal"]["next_action"] == "check"
        assert report["response_proof"]["response_sha256"] == driver.digest(raw)
        assert session.active == ["read", "edit", "write"]
        assert allowance.phase is None and tools.step is None and listeners == []

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["planning", "repair"])
@pytest.mark.parametrize("restore", ["okay", "raises", "mismatch"])
def test_goal_planning_original_work_cancel_retains_scope_until_idle(
    tmp_path, phase, restore
):
    from types import SimpleNamespace

    from loushang.coding.adapters._goal_planning_limits import (
        PlanningCallAllowance,
        PlanningCallLimit,
    )
    from loushang.coding.adapters._goal_planning_work import (
        PlanningToolPolicy,
        ScopedSessionWork,
    )
    from loushang.coding.adapters.harnesswork import (
        CODING_WORK_PROFILE,
        project_coding_runtime_event,
    )
    from loushang.harnesswork import (
        InMemoryEventLogBackend,
        WorkRunSpec,
        WorkRuntime,
        WorkStepSpec,
    )
    from loushang.harnesswork.integrations.session import SessionTurnExecutor
    from loushang.harnesswork.ports import WorkExecutionBinding

    async def scenario():
        entered, aborted, idle_waiting, idle = (asyncio.Event() for _ in range(4))
        prior = ["read", "edit", "write"]

        class Session:
            active = list(prior)
            selections = 0

            def get_active_tool_names(self):
                return list(self.active)

            async def set_active_tools(self, names):
                self.selections += 1
                if self.selections > 1 and restore == "raises":
                    raise RuntimeError("restoration failed")
                self.active = (
                    [] if self.selections > 1 and restore == "mismatch" else list(names)
                )

            def subscribe_runtime_events(self, listener):
                return lambda: None

            async def prompt(self, *args, **kwargs):
                entered.set()
                await aborted.wait()

            async def abort(self):
                aborted.set()

            async def wait_for_idle(self):
                idle_waiting.set()
                await idle.wait()

        session = Session()
        allowance, policy = PlanningCallAllowance(), PlanningToolPolicy(tmp_path)
        delegate = SessionTurnExecutor(
            session=session,
            profile=CODING_WORK_PROFILE,
            project_event_facts=project_coding_runtime_event,
            turn=SessionWorkTurn("execute"),
        )
        scoped = ScopedSessionWork(
            delegate, session=session, allowance=allowance, policy=policy, phase=phase
        )

        class Resolver:
            def resolve(self, operation, spec):
                return WorkExecutionBinding(scoped, scoped)

        runtime = WorkRuntime(event_log=InMemoryEventLogBackend(), resolver=Resolver())
        operation = SessionWorkTurn("execute").to_operation(
            profile=CODING_WORK_PROFILE, session_id="session", operation_id="op"
        )
        run = await runtime.accept(
            operation,
            spec=WorkRunSpec(
                plan_id="cancel-plan",
                steps=(WorkStepSpec("repair" if phase == "repair" else "planning"),),
            ),
        )
        await entered.wait()
        cancel = asyncio.create_task(runtime.cancel(run.run_id))
        await idle_waiting.wait()
        assert allowance.phase == phase and not cancel.done()
        assert runtime.get_run(run.run_id).status == "cancelling"
        idle.set()
        await cancel
        assert allowance.phase is None and policy.step is None
        assert runtime.get_cancellation(run.run_id).status == "settled"
        if restore == "okay":
            assert not allowance.fenced and session.active == prior
        else:
            assert allowance.fenced
            with pytest.raises(PlanningCallLimit):
                allowance.enter("another-op", "planning")
            owner = CodingGoal(tmp_path, tmp_path / "data")
            owner._core = SimpleNamespace(fenced=False)
            owner._allowance = allowance
            with pytest.raises(GoalError, match="configuration fenced"):
                await owner.advance("g", command_id="next", revision=1, epoch=1)
        await runtime.dispose()

    asyncio.run(scenario())


def test_goal_planning_tool_scope_uses_resolved_effects_and_preserves_caller_denial(
    tmp_path,
):
    from loushang.coding.adapters._goal_planning_work import PlanningToolPolicy
    from loushang.harness.effects import FilesystemEffect, ProcessEffect
    from loushang.harness.policy import (
        PathPolicySubject,
        PolicyDecision,
        PolicyEvaluatorChain,
        ToolPolicySubject,
    )

    policy = PlanningToolPolicy(tmp_path)

    def subject(name, path, effects=None):
        return ToolPolicySubject(
            name,
            {"path": str(path)},
            cwd=str(tmp_path),
            paths=(PathPolicySubject(str(path), str(path)),),
            effects=effects
            or (FilesystemEffect("read" if name == "read" else "write", (str(path),)),),
        )

    source = tmp_path / "calculator.py"
    assert policy.evaluate(subject("read", source)).disposition == "deny"
    policy.step = "inspect"
    assert policy.evaluate(subject("read", source)).disposition == "allow"
    assert policy.evaluate(subject("write", source)).disposition == "deny"
    policy.step = "repair"
    assert policy.evaluate(subject("edit", source)).disposition == "allow"
    assert (
        policy.evaluate(subject("write", tmp_path / "TESTS.json")).disposition == "deny"
    )
    assert (
        policy.evaluate(subject("read", tmp_path.parent / "outside")).disposition
        == "deny"
    )
    assert (
        policy.evaluate(subject("read", source, (ProcessEffect(("sh",)),))).disposition
        == "deny"
    )
    assert (
        policy.evaluate(
            subject(
                "write",
                source,
                (FilesystemEffect("write", (str(tmp_path / "TESTS.json"),)),),
            )
        ).disposition
        == "deny"
    )

    class Caller:
        def evaluate(self, subject):
            return PolicyDecision.deny("caller denied")

    chain = PolicyEvaluatorChain((policy, Caller()), strategy="most_restrictive")
    assert asyncio.run(chain.evaluate(subject("write", source))).disposition == "deny"


def test_goal_model_planning_sdk_bounds_failed_calls_without_implementation(
    tmp_path, monkeypatch
):
    from loushang.coding.adapters import _goal_planning_limits as limits

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    calls = []

    async def fail_model(model, context, options):
        calls.append(context)
        raise RuntimeError("offline model failure")

    monkeypatch.setattr(limits, "stream", fail_model)

    async def scenario():
        owner = await CodingGoal.open(
            workspace=_goal_project(tmp_path),
            data_root=tmp_path / "data",
            model=_goal_offline_model(),
            model_planning=True,
        )
        try:
            owner.create("g", command_id="create")
            assert owner.controller.query("g").limit == 20
            assert (
                not owner._session.auto_retry_enabled
                and not owner._session.auto_compaction_enabled
            )
            assert calls == []
            for number in range(3):
                state = owner.controller.query("g")
                receipt = await owner.advance(
                    "g",
                    command_id=f"advance-{number}",
                    revision=state.revision,
                    epoch=state.epoch,
                )
                if number < 2:
                    assert receipt.outcome == "work_finished", (
                        receipt,
                        owner.controller.last_error,
                    )
                else:
                    assert receipt.outcome == "paused"
            assert owner.controller.query("g").status == "paused"
            assert owner.controller.query("g").reason == "planning_invalid_limit"
            assert len(calls) == 3
            assert len(owner.controller.history.batches) == 3
            assert all(
                batch.source["phase"] == "planning"
                for batch in owner.controller.history.batches
            )
            assert owner._allowance.phase is None
            with pytest.raises(GoalError, match="outside running repair"):
                owner.steer("g", "do not queue this")
        finally:
            await owner.close()

    asyncio.run(scenario())


@pytest.mark.requires_host_runtime
def test_goal_planning_fixed_verifier_scope_executes_without_model_authority(
    tmp_path, monkeypatch
):
    from loushang.coding.adapters._verification_work import inspect_verification

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))

    async def scenario():
        owner = await CodingGoal.open(
            workspace=_goal_project(tmp_path),
            data_root=tmp_path / "data",
            model=_goal_offline_model(),
            model_planning=True,
        )
        try:
            owner.create("g", command_id="create")

            async def verification(basis, facts):
                snapshot, source, tests, code = owner._policy._current_inputs(basis)
                return owner._policy.prepare_verification(
                    basis, snapshot, source, tests, code
                )

            monkeypatch.setattr(owner._policy, "prepare", verification)
            receipt = await owner.advance("g", command_id="verify", revision=1, epoch=1)
            assert receipt.outcome == "work_finished", owner.controller.last_error
            run = owner.controller.facts().runs[-1]
            assert run.status == "failed"
            view = inspect_verification(
                owner._policy.log.query(), run_id=run.run_id, blobs=owner._policy.blobs
            )
            assert view.passed is False and not view.issues, view
            assert owner._allowance.calls == 0
            assert owner._policy.tool_policy.verification is None
        finally:
            await owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("pause_while_planning", [False, True])
def test_goal_planning_standard_pipeline_admits_once_and_discards_late_proposal(
    tmp_path, monkeypatch, pause_while_planning
):
    from loushang.ai.api_registry import get_default_api_registry
    from loushang.ai.json_codec import serialize_message
    from loushang.ai.model import Auth
    from loushang.ai.prepared_request import PreparedModelRequest

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        if not pause_while_planning:
            release.set()
        raw = json.dumps(
            _planning_proposal(
                next_action="inspect",
                expected_evidence=["goal_inspection_report"],
                remaining_route=[{"action": "inspect", "targets": ["subtraction"]}],
            )
        )

        class Adapter:
            api = "goal-planning-offline-contract"
            calls = 0

            def prepare_request(self, request):
                return PreparedModelRequest.from_provider_request(
                    request,
                    payload={
                        "system": request.context.system_prompt,
                        "messages": [
                            serialize_message(m) for m in request.context.messages
                        ],
                        "tools": [t.name for t in request.context.tools or ()],
                        "model": request.model.id,
                    },
                )

            async def invoke_prepared_raw(self, request, prepared):
                self.calls += 1
                assert not request.context.tools
                prepared.payload_for_transport()
                entered.set()
                await release.wait()
                yield {
                    "type": "response_start",
                    "response_id": f"response-{self.calls}",
                }
                yield {"type": "text_delta", "text": raw}
                yield {"type": "stop_reason", "stop_reason": "stop"}
                yield {"type": "response_done"}

            async def invoke_raw(self, request):
                async for part in self.invoke_prepared_raw(
                    request, self.prepare_request(request)
                ):
                    yield part

        adapter = Adapter()
        registry = get_default_api_registry()
        registry.register_api_adapter(adapter, source_id=adapter.api)
        owner = None
        task = None
        try:
            model = Model(
                id="goal-offline",
                provider="goal-offline",
                endpoint="goal-offline",
                api=adapter.api,
                base_url="https://unused.invalid",
                auth=Auth(kind="none"),
                capabilities=Capabilities(
                    input=("text",),
                    output=("text",),
                    context_window=128000,
                    stream=True,
                    tool_use=True,
                ),
            )
            owner = await CodingGoal.open(
                workspace=_goal_project(tmp_path),
                data_root=tmp_path / "data",
                model=model,
                model_planning=True,
            )
            owner.create("g", command_id="create")
            task = asyncio.create_task(
                owner.advance("g", command_id="first-plan", revision=1, epoch=1)
            )
            await asyncio.wait_for(entered.wait(), 10)
            with pytest.raises(GoalError, match="outside running repair"):
                owner.follow_up("g", "must not enter planning input")
            if pause_while_planning:
                owner.controller.control(
                    "g",
                    "pause",
                    command_id="pause",
                    revision=1,
                    epoch=1,
                    reason="user pause",
                )
            release.set()
            first = await task
            assert first.outcome == (
                "stale" if pause_while_planning else "work_finished"
            ), owner.controller.last_error
            first_op = owner.controller.history.batches[0].operation_id
            trace = owner.planning_trace("g")
            assert trace["status"] == "known" and len(trace["routes"]) == 1, trace
            if pause_while_planning:
                state = owner.controller.query("g")
                owner.controller.control(
                    "g",
                    "resume",
                    command_id="resume",
                    revision=state.revision,
                    epoch=state.epoch,
                    reason="continue",
                )
            state = owner.controller.query("g")
            second = await owner.advance(
                "g", command_id="second", revision=state.revision, epoch=state.epoch
            )
            assert second.outcome == "work_finished", owner.controller.last_error
            batches = owner.controller.history.batches
            assert len(batches) == 2
            if pause_while_planning:
                assert batches[-1].source["phase"] == "planning"
                assert all(b.source.get("proposal_id") != first_op for b in batches)
                assert adapter.calls == 2
            else:
                assert batches[-1].source["phase"] == "inspect"
                assert batches[-1].source["proposal_id"] == first_op
                assert adapter.calls == 1
                repeated = await owner.advance(
                    "g", command_id="second", revision=state.revision, epoch=state.epoch
                )
                assert repeated == second and len(owner.controller.history.batches) == 2
                assert len(owner.planning_trace("g")["evidence"]) == 1
        finally:
            release.set()
            if task is not None and not task.done():
                await task
            if owner is not None:
                await owner.close()
            registry.unregister_api_adapters(adapter.api)
        assert owner is not None
        before = {
            str(p.relative_to(tmp_path)): driver.digest(p.read_bytes())
            for p in tmp_path.rglob("*")
            if p.is_file()
        }
        cold = inspect_goal(
            workspace=owner.workspace,
            data_root=owner.data_root,
            session_id=owner.session_id,
            goal_id="g",
        )
        assert cold.planning["status"] == "known", cold.planning
        assert len(cold.planning["routes"]) == (2 if pause_while_planning else 1)
        if not pause_while_planning:
            assert cold.planning["routes"][0]["consumed_by"] == [
                batches[-1].operation_id
            ]
            assert cold.planning["batches"][-1]["admission"] == "admitted"
        after = {
            str(p.relative_to(tmp_path)): driver.digest(p.read_bytes())
            for p in tmp_path.rglob("*")
            if p.is_file()
        }
        assert before == after
        # Missing original Transcript is unknown, regardless of exported trace copies.
        transcript = next(
            p
            for p in (owner.data_root / "sessions").glob("*.jsonl")
            if p.name.startswith("20")
        )
        original_transcript = transcript.read_bytes()
        rows = [json.loads(line) for line in original_transcript.splitlines()]
        outcome = next(row for row in rows if row.get("kind") == "model.call.outcome")
        outcome["payload"]["modelInputSnapshotIds"] = ["foreign-snapshot"]
        transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        inconsistent = inspect_goal(
            workspace=owner.workspace,
            data_root=owner.data_root,
            session_id=owner.session_id,
            goal_id="g",
        )
        assert inconsistent.goal == cold.goal
        assert inconsistent.planning["status"] == "unknown"
        transcript.write_bytes(original_transcript)
        transcript.unlink()
        damaged = inspect_goal(
            workspace=owner.workspace,
            data_root=owner.data_root,
            session_id=owner.session_id,
            goal_id="g",
        )
        assert damaged.planning["status"] == "unknown"
        assert "Transcript" in damaged.planning["reason"]

    asyncio.run(scenario())


def _goal_project(tmp_path):
    root = tmp_path / "_goal_project"
    shutil.copytree(_GOAL_FIXTURE, root)
    return root


def _goal_offline_model():
    return Model(
        id="offline-goal",
        name="Offline Goal",
        provider="offline",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            input=("text",), context_window=128000, max_tokens=4096
        ),
    )


@pytest.mark.parametrize(
    "source",
    [
        "import os\ndef subtract(a,b): return a-b\ndef clamp(value,lower,upper): return value",
        "def subtract(a,b): return print(a)\ndef clamp(value,lower,upper): return value",
        "def subtract(a,b): return a.__class__\ndef clamp(value,lower,upper): return value",
        "def subtract(a,b):\n while a: a-1\n return a\ndef clamp(value,lower,upper): return value",
        "def subtract(a,b): return 2**a\ndef clamp(value,lower,upper): return value",
        "def subtract(a,b): return [a][0]\ndef clamp(value,lower,upper): return value",
        "def subtract(a,b=0): return a-b\ndef clamp(value,lower,upper): return value",
        "def subtract(a,b): return True\ndef clamp(value,lower,upper): return value",
        "def subtract(a,b): return 1001\ndef clamp(value,lower,upper): return value",
    ],
)
def test_driver_rejects_outside_language_without_execution(source):
    with pytest.raises(ValueError):
        driver.validate_source(source.encode())


def test_original_fixture_bytes_and_actual_driver_failures(tmp_path):
    root = _goal_project(tmp_path)
    source, tests = (
        (root / "calculator.py").read_bytes(),
        (root / "TESTS.json").read_bytes(),
    )
    assert (
        driver.digest(source)
        == "4d47897f8b404b3b22dd4616658ee9e30aea0719b4617ec48487cd6fad8bccfb"
    )
    assert (
        driver.digest(tests)
        == "1fd53db853feb6f499777566d4226d102010ffd902d0424569cd4d43a1de12fe"
    )
    value = {
        "version": 1,
        "identity": {"goal_id": "g", "revision": 1, "epoch": 1, "operation_id": "op"},
        "source": driver.content_entry(source),
        "tests": driver.content_entry(tests),
        "driver_sha256": driver.digest(Path(driver.__file__).read_bytes()),
    }
    result = driver.verify(json.dumps(value).encode())
    assert (
        result["tests_run"],
        result["failures"],
        result["errors"],
        result["skipped"],
    ) == (23, 13, 0, 0)


def test_inventory_detects_unlisted_files_and_links(tmp_path):
    from loushang.coding.adapters._goal_calculator import check_inventory

    root = _goal_project(tmp_path)
    baseline = inventory(root)
    (root / "new.txt").write_text("unrelated")
    with pytest.raises(GoalError, match="paths changed"):
        check_inventory(root, baseline)
    (root / "new.txt").unlink()
    (root / "TESTS.json").unlink()
    (root / "TESTS.json").symlink_to("/dev/null")
    with pytest.raises(GoalError, match="unsupported project entry"):
        check_inventory(root, baseline)


@pytest.mark.requires_host_runtime
def test_real_sdk_initial_failure_persistence_and_read_only_reopen(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    root, data = _goal_project(tmp_path), tmp_path / "data"

    async def scenario():
        goal = await CodingGoal.open(
            workspace=root, data_root=data, model=_goal_offline_model()
        )
        try:
            receipt = goal.create("g", command_id="create")
            assert goal.create("g", command_id="create") == receipt
            first = await goal.advance("g", command_id="initial", revision=1, epoch=1)
            assert first.outcome == "work_finished", (first, goal.controller.last_error)
            batches = goal.controller.history.batches
            assert len(batches) == 1 and batches[0].source["phase"] == "verification"
            view = await goal.query("g")
            assert view.goal.status == "active" and view.validity == "not_satisfied"
            assert view.reason == "actual_tests_failed"
            return goal.session_id
        finally:
            await goal.close()

    sid = asyncio.run(scenario())
    before = {p: p.read_bytes() for p in (data / "sessions").glob("*.goal.jsonl")}
    cold = inspect_goal(workspace=root, data_root=data, session_id=sid, goal_id="g")
    assert cold.goal.status == "active" and cold.reason == "actual_tests_failed"
    assert all(p.read_bytes() == content for p, content in before.items())


def test_goal_writer_excludes_second_product_owner_and_rejects_bad_tail(tmp_path):
    from loushang.coding.adapters._goal_store import GoalJournal
    from loushang.harness.journal._directory_lease import DirectoryWriterError
    from loushang.harnesswork.goal import GoalHeader

    root = tmp_path.resolve()
    header = GoalHeader("s", "s", "test")
    first = GoalJournal(root, header)
    second = GoalJournal(root, header)
    try:
        first.open(create=True)
        with pytest.raises(DirectoryWriterError, match="busy"):
            second.open()
        with first.path.open("ab") as stream:
            stream.write(b'{"partial":')
        with pytest.raises(Exception):
            first.load()
    finally:
        second.close()
        first.close()


def test_goal_driver_rejects_unreachable_nested_definition():
    source = (
        b"def subtract(a,b):\n return a-b\n def hidden(a=1) -> a: return a\n"
        b"def clamp(value,lower,upper):\n if value < lower: return lower\n"
        b" if value > upper: return upper\n return value\n"
    )
    with pytest.raises(ValueError, match="top-level"):
        driver.validate_source(source)


@pytest.mark.requires_host_runtime
def test_goal_resume_checks_protected_inputs_before_active(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    root = _goal_project(tmp_path)

    async def scenario():
        goal = await CodingGoal.open(
            workspace=root, data_root=tmp_path / "data", model=_goal_offline_model()
        )
        try:
            goal.create("g", command_id="create")
            goal.controller.control(
                "g", "pause", command_id="pause", revision=1, epoch=1, reason="user"
            )
            (root / "README.md").write_text("changed protected file")
            with pytest.raises(GoalError, match="protected project"):
                goal.controller.control(
                    "g",
                    "resume",
                    command_id="resume",
                    revision=1,
                    epoch=2,
                    reason="user",
                )
            assert goal.controller.query("g").status == "paused"
            assert not goal.controller.history.batches
        finally:
            await goal.close()

    asyncio.run(scenario())


@pytest.mark.requires_host_runtime
def test_goal_cold_completion_validity_and_original_work_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    root, data = _goal_project(tmp_path), tmp_path / "data"
    source = (
        (root / "calculator.py")
        .read_text()
        .replace("return a + b", "return a - b")
        .replace(
            "if value < lower:\n        return upper",
            "if value < lower:\n        return lower",
        )
        .replace(
            "if value > upper:\n        return lower",
            "if value > upper:\n        return upper",
        )
    )
    (root / "calculator.py").write_text(source)

    async def scenario():
        goal = await CodingGoal.open(
            workspace=root, data_root=data, model=_goal_offline_model()
        )
        try:
            goal.create("g", command_id="create")
            assert (
                await goal.advance("g", command_id="verify", revision=1, epoch=1)
            ).outcome == "completed"
            return goal.session_id
        finally:
            await goal.close()

    sid = asyncio.run(scenario())
    assert (
        inspect_goal(
            workspace=root, data_root=data, session_id=sid, goal_id="g"
        ).validity
        == "current"
    )
    (root / "calculator.py").write_text(source.replace("return a - b", "return a + b"))
    assert (
        inspect_goal(
            workspace=root, data_root=data, session_id=sid, goal_id="g"
        ).validity
        == "outdated"
    )
    (root / "calculator.py").write_text(source)
    journal = next((data / "sessions").glob("*.goal.jsonl"))
    original = journal.read_bytes()
    rows = [json.loads(line) for line in original.splitlines()]
    for row in rows:
        if row.get("kind") == "batch_associated":
            row["data"]["run_id"] = "foreign-run"
    journal.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(GoalError, match="association mismatch"):
        inspect_goal(workspace=root, data_root=data, session_id=sid, goal_id="g")
    journal.write_bytes(original)
    from loushang.harness.artifacts import SessionBlobStore

    store = SessionBlobStore(data, sid, read_only=True)
    created = next(row for row in rows if row.get("kind") == "created")
    ref = created["data"]["metadata"]["tests_ref"]
    blob = store.objects_root / ref["blobId"]
    contents = blob.read_bytes()
    blob.write_bytes(b"corrupted fixed test bytes")
    assert (
        inspect_goal(
            workspace=root, data_root=data, session_id=sid, goal_id="g"
        ).validity
        == "corrupt"
    )
    blob.unlink()
    assert (
        inspect_goal(
            workspace=root, data_root=data, session_id=sid, goal_id="g"
        ).validity
        == "missing"
    )
    blob.write_bytes(contents)
    assert (
        inspect_goal(
            workspace=root, data_root=data, session_id=sid, goal_id="g"
        ).validity
        == "current"
    )


@pytest.mark.requires_host_runtime
@pytest.mark.parametrize("field", ["step_constraints", "step_audit"])
def test_goal_rejects_real_method_metadata_it_cannot_enforce(
    tmp_path, monkeypatch, field
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    root = _goal_project(tmp_path)
    method = root / "methods/task/goal-calculator-repair/SKILL.md"
    original = method.read_text()
    method.write_text(
        original.replace(
            "plan_mode: fixed",
            f"plan_mode: fixed\n{field}:\n  repair:\n    must_execute_unavailable_check: true",
        )
    )

    async def scenario():
        goal = await CodingGoal.open(
            workspace=root, data_root=tmp_path / "data", model=_goal_offline_model()
        )
        try:
            goal.create("g", command_id="create")
            assert (
                await goal.advance("g", command_id="initial", revision=1, epoch=1)
            ).outcome == "work_finished"
            rejected = await goal.advance("g", command_id="repair", revision=1, epoch=1)
            assert rejected.outcome == "paused"
            assert "constraint/audit" in rejected.details["reason"]
            assert len(goal.controller.history.batches) == 1
            assert all(
                b.source["phase"] == "verification"
                for b in goal.controller.history.batches
            )
        finally:
            await goal.close()

    asyncio.run(scenario())


def test_goal_writer_last_retry_does_not_reenter_retired_core(tmp_path):
    calls = []

    class Core:
        retired = False

        def fence(self):
            calls.append("fence")

        def begin_close(self):
            self.fence()

        async def quiesce(self):
            assert not self.retired
            calls.append("quiet")

        async def settle_work(self):
            assert not self.retired
            calls.append("work")

        def retire(self):
            calls.append("retire")
            self.retired = True

    class SDK:
        async def dispose_session_runtime(self):
            calls.append("session")

    class Store:
        failed = False

        def close(self):
            calls.append("writer")
            if not self.failed:
                self.failed = True
                raise OSError("writer close pending")

    async def scenario():
        owner = CodingGoal(tmp_path, tmp_path / "data")
        owner._core, owner._sdk, owner._store = Core(), SDK(), Store()
        with pytest.raises(OSError, match="writer close pending"):
            await owner.close()
        assert not owner._closed and owner._core.retired
        await owner.close()
        await owner.close()
        assert owner._closed
        assert (
            calls.count("quiet")
            == calls.count("work")
            == calls.count("session")
            == calls.count("retire")
            == 1
        )
        assert calls.count("writer") == 2

    asyncio.run(scenario())


def test_goal_query_cleanup_error_is_retained_without_disposing_resources(tmp_path):
    disposed = []

    class SDK:
        async def dispose_session_runtime(self):
            disposed.append("session")

    class Store:
        def close(self):
            disposed.append("writer")

    async def scenario():
        owner = CodingGoal(tmp_path, tmp_path / "data")
        owner._sdk, owner._store = SDK(), Store()
        started = asyncio.Event()

        async def query():
            task = asyncio.current_task()
            owner._queries.add(task)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                owner._queries.discard(task)
                raise OSError("query reader cleanup pending")

        task = asyncio.create_task(query())
        await started.wait()
        with pytest.raises(OSError, match="reader cleanup pending"):
            await owner.close()
        assert task.done() and not disposed and not owner._closed
        with pytest.raises(OSError, match="reader cleanup pending"):
            await owner.close()
        assert not disposed

    asyncio.run(scenario())


def test_goal_original_input_forwarding_preserves_images_and_terminal_window(tmp_path):
    from types import SimpleNamespace

    seen = []
    phase, status = "repair", "running"
    batch = SimpleNamespace(
        goal_id="g", not_submitted=False, operation_id="op", source={"phase": phase}
    )

    class Core:
        fenced = False
        history = SimpleNamespace(batches=(batch,))

        def query(self, goal_id):
            return SimpleNamespace(status="active")

    class Work:
        def get_run_for_operation(self, operation_id):
            return SimpleNamespace(status=status)

    class Session:
        def steer(self, text, images):
            seen.append(("steer", text, images))

        def follow_up(self, text, images):
            seen.append(("follow_up", text, images))

    owner = CodingGoal(tmp_path, tmp_path / "data")
    owner._core, owner._work, owner._session = Core(), Work(), Session()
    images = [object()]
    owner.steer("g", "steer text", images=images)
    owner.follow_up("g", "follow text", images=images)
    assert [row[0] for row in seen] == ["steer", "follow_up"]
    assert all(row[2] is images for row in seen)
    status = "completed"
    with pytest.raises(GoalError, match="outside running repair"):
        owner.steer("g", "late", images=images)
    assert len(seen) == 2


@pytest.mark.parametrize("matching_bytes", [True, False])
def test_goal_verifier_nonzero_uses_last_cumulative_preview_not_exception_text(
    tmp_path, matching_bytes
):
    from loushang.coding.adapters._verification_work import (
        CodingVerificationFailed,
        CodingVerificationWork,
        inspect_verification,
    )
    from loushang.harness.artifacts import SessionBlobStore
    from loushang.harness.workspace.exec import ExecOutputChunk
    from loushang.harnesswork import (
        InMemoryEventLogBackend,
        WorkOperation,
        WorkRunSpec,
        WorkStepSpec,
    )

    class Session:
        session_id = "s"

        async def execute_bash(self, command, **options):
            options["on_output"](ExecOutputChunk(stream="stdout", text="partial"))
            options["on_output"](
                ExecOutputChunk(stream="stdout", text="actual failure\n")
            )
            error = RuntimeError("THIS ERROR TEXT IS NOT OUTPUT")
            error.tool_result_details = {
                "exit_code": 1,
                "cancelled": False,
                "timed_out": False,
                "truncated": False,
                "stdio_complete": True,
                "stdio_drain_reason": None,
                "stdout_total_bytes": len(b"actual failure\n") if matching_bytes else 1,
                "stderr_total_bytes": 0,
            }
            raise error

    async def scenario():
        log = InMemoryEventLogBackend()
        blobs = SessionBlobStore(tmp_path / "data", "s")
        work = CodingVerificationWork(session=Session(), blobs=blobs, event_log=log)
        run = await work.runtime.accept(
            WorkOperation(
                "op",
                "VerifyCodingCommand",
                "s",
                "coding",
                {"command": "check", "execution": {"stdin": "input"}},
            ),
            spec=WorkRunSpec(
                plan_id="verify",
                steps=(WorkStepSpec("report"), WorkStepSpec("validation")),
            ),
        )
        with pytest.raises(
            CodingVerificationFailed if matching_bytes else RuntimeError
        ):
            await work.runtime.wait(run.run_id)
        view = inspect_verification(log.query(), run_id=run.run_id, blobs=blobs)
        assert view.run.status == "failed"
        if matching_bytes:
            assert view.passed is False
            report = json.loads(
                blobs.read_bytes(
                    next(r.blob for r in view.records if r.role == "report")
                )
            )
            from loushang.harness.artifacts import SessionBlobRef

            output = blobs.read_bytes(
                SessionBlobRef.from_manifest_entry(report["outputs"][0])
            )
            assert output == b"actual failure\n"
        else:
            assert view.passed is None and not view.records

    asyncio.run(scenario())
