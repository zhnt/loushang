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
