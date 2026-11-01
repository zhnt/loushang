from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.coding.adapters import _goal_repository_driver as driver
from loushang.coding.adapters._goal_repository import (
    inspect_repository_goal,
    open_repository_goal,
    parse_repository_proposal,
    validate_check_result,
)
from loushang.coding.adapters._goal_repository_task import (
    RepositoryTask,
    digest,
    inventory,
)
from loushang.harnesswork.goal import GoalError


def task_package(tmp_path, *, initial="VALUE = 1\n"):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "target.py").write_text(initial)
    (root / ".gitignore").write_text(".loushang/\n__pycache__/\n")
    for name in (
        "tests/method/test_contract.py",
        "tests/coding/domain/test_coding_domain_app.py",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_preserved():\n    assert True\n")
    (root / "conftest.py").write_text(
        "def pytest_addoption(parser):\n    parser.addoption('--skip-host-runtime', action='store_true')\n"
    )
    package = tmp_path / "package"
    package.mkdir()
    (package / "test_contract.py").write_text(
        f"from pathlib import Path\ndef test_target():\n    assert (Path({str(root)!r}) / 'target.py').read_text().splitlines()[0] == 'VALUE = 1'\n"
    )
    shutil.copyfile(driver.__file__, package / "driver.py")
    (package / "method.json").write_text(
        json.dumps(
            {
                "id": "repo-method",
                "name": "repo-method",
                "description": "",
                "content": "Preserve the contract.",
                "kind": "method_resource",
                "metadata": {
                    "frontmatter": {"plan_mode": "fixed", "steps": ["repair"]}
                },
            }
        )
    )
    config = {
        "version": 1,
        "accepted": True,
        "workspace": str(root),
        "allowed_files": ["target.py"],
        "read_files": ["target.py"],
        "requirements": [
            {"id": f"RC-0{i}", "text": f"requirement {i}"} for i in range(1, 7)
        ],
        "workspace_start": inventory(root),
        "inspect_files": {
            "reader": ["target.py"],
            "operations": ["target.py"],
            "tests": ["target.py"],
        },
        "check_selectors": {
            "reader": ["tests/method"],
            "regression": [
                "tests/method",
                "tests/coding/domain/test_coding_domain_app.py",
            ],
        },
        "python": sys.executable,
        "temporary_root": str(tmp_path),
        "check_timeout_seconds": 20,
        "protected": {p.name: digest(p.read_bytes()) for p in package.iterdir()},
    }
    path = package / "manifest.json"
    path.write_text(json.dumps(config))
    return RepositoryTask(path, digest(path.read_bytes()))


async def submit(owner, goal_id, *, expected_inventory, approved, reviewer, reason):
    identity, _ = owner.review_basis(goal_id)
    if identity["inventory"] != expected_inventory:
        raise GoalError("review basis changed")
    return await owner.submit_review(
        goal_id,
        command_id=f"review-{identity['epoch']}",
        review_id=f"review-{identity['epoch']}",
        expected_identity=identity,
        decision="approved" if approved else "rejected",
        reviewer=reviewer,
        reason=reason,
        coverage=["RC-05", "RC-06"],
        findings=[],
    )


class Adapter:
    api = "repository-goal-offline"
    calls = 0

    async def invoke_raw(self, request):
        async for part in self.invoke_prepared_raw(
            request, self.prepare_request(request)
        ):
            yield part

    def prepare_request(self, request):
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "system": request.context.system_prompt,
                "messages": [serialize_message(m) for m in request.context.messages],
                "tools": [t.name for t in request.context.tools or ()],
                "model": request.model.id,
            },
        )

    async def invoke_prepared_raw(self, request, prepared):
        self.calls += 1
        assert not request.context.tools
        prepared.payload_for_transport()
        yield {"type": "response_start", "response_id": f"response-{self.calls}"}
        yield {
            "type": "text_delta",
            "text": json.dumps(
                {
                    "next_action": "verify_all",
                    "targets": [],
                    "requirement_ids": [f"RC-0{i}" for i in range(1, 7)],
                    "rationale": "Verify actual work",
                    "expected_evidence": ["report", "validation"],
                    "remaining_route": [{"action": "verify_all", "targets": []}],
                    "change_reason": "",
                    "evidence_refs": [],
                }
            ),
        }
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


def model(adapter):
    get_default_api_registry().register_api_adapter(adapter, source_id=adapter.api)
    return Model(
        id="offline-repo",
        provider="offline",
        endpoint="offline",
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


@pytest.mark.parametrize("pause", [False, True])
def test_original_goal_review_epoch_cached_advance_and_cold_read(
    tmp_path, monkeypatch, pause
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task = task_package(tmp_path)
    adapter = Adapter()

    async def scenario():
        owner = await open_repository_goal(
            task=task, data_root=tmp_path / "data", model=model(adapter)
        )
        try:
            owner.create("g", command_id="create")
            for n in range(2):
                result = await owner.advance(
                    "g", command_id=f"a-{n}", revision=1, epoch=1
                )
                assert result.outcome == "work_finished", owner.controller.last_error
            view = await owner.query("g")
            assert view.reason == "review_required" and view.goal.epoch == 1
            assert adapter.calls == 1
            assert (
                await owner.advance("g", command_id="a-1", revision=1, epoch=1)
                == result
            )
            with pytest.raises(GoalError, match="review_required"):
                await owner.advance("g", command_id="pending", revision=1, epoch=1)
            with pytest.raises(GoalError, match="review_required"):
                await owner.controller.advance(
                    "g", command_id="raw-pending", revision=1, epoch=1
                )
            assert owner.controller.query("g").epoch == 1 and adapter.calls == 1
            with pytest.raises(GoalError, match="review basis"):
                await submit(
                    owner,
                    "g",
                    expected_inventory={},
                    approved=True,
                    reviewer="test",
                    reason="reviewed",
                )
            if pause:
                owner.controller.control(
                    "g", "pause", command_id="pause", revision=1, epoch=1, reason="user"
                )
                owner.controller.control(
                    "g",
                    "resume",
                    command_id="resume",
                    revision=1,
                    epoch=2,
                    reason="user",
                )
                view = await owner.query("g")
                assert (
                    view.goal.epoch == 3
                    and view.reason == "repository_verification_required"
                )
                assert (
                    await owner.advance("g", command_id="new-plan", revision=1, epoch=3)
                ).outcome == "work_finished"
                assert adapter.calls == 2
                assert (
                    await owner.advance(
                        "g", command_id="new-verify", revision=1, epoch=3
                    )
                ).outcome == "work_finished"
                assert (await owner.query("g")).reason == "review_required"
                await submit(
                    owner,
                    "g",
                    expected_inventory=task.snapshot(),
                    approved=True,
                    reviewer="test",
                    reason="new epoch reviewed",
                )
            if not pause:
                await submit(
                    owner,
                    "g",
                    expected_inventory=task.snapshot(),
                    approved=True,
                    reviewer="test",
                    reason="reviewed scope",
                )
            assert owner.controller.query("g").status == "completed"
            session_id = owner.session_id
        finally:
            await owner.close()
        with pytest.raises(GoalError, match="closing"):
            await owner.advance("g", command_id="closed", revision=1, epoch=1)
        cold = inspect_repository_goal(
            task=task, data_root=tmp_path / "data", session_id=session_id, goal_id="g"
        )
        assert cold.goal.status == "completed" and cold.validity == "current", cold
        assert cold.planning["status"] == "known"
        (task.root / "target.py").write_text("VALUE = 2\n")
        cold = inspect_repository_goal(
            task=task, data_root=tmp_path / "data", session_id=session_id, goal_id="g"
        )
        assert cold.goal.status == "completed" and cold.validity == "outdated"
        # The original transcript is timestamp-prefixed; Goal/Work sidecars have different names.
        transcripts = [
            p
            for p in (tmp_path / "data/sessions").glob("*.jsonl")
            if p.name[:4].isdigit() and p.name[4:5] == "-"
        ]
        assert len(transcripts) == 1
        transcripts[0].unlink()
        cold = inspect_repository_goal(
            task=task, data_root=tmp_path / "data", session_id=session_id, goal_id="g"
        )
        assert cold.goal.status == "completed" and cold.validity == "unknown"

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


@pytest.mark.parametrize(
    "change", ["version", "coverage", "collection", "exit", "setup_error", "bool_count"]
)
def test_repository_result_refuses_unknown_or_incomplete_proof(change):
    result = {
        "version": 1,
        "results": [
            {
                "name": n,
                "exit_code": 0,
                "collected": 1,
                "skipped": 0,
                "failed": [],
                "errors": [],
                "output": "passed",
            }
            for n in ("contract", "regression")
        ],
    }
    validate_check_result(result, "all")
    damaged = copy.deepcopy(result)
    if change == "version":
        damaged["version"] = True
    elif change == "coverage":
        damaged["results"].pop()
    elif change == "collection":
        damaged["results"][0]["collected"] = 0
    elif change == "exit":
        damaged["results"][0]["exit_code"] = 2
    elif change == "setup_error":
        damaged["results"][0]["errors"] = ["fixture failed"]
    else:
        damaged["results"][0]["collected"] = True
    with pytest.raises(GoalError):
        validate_check_result(damaged, "all")


@pytest.mark.parametrize("recover", [False, True])
def test_provider_failure_stops_without_invalid_plan_retry_and_can_resume(
    tmp_path, monkeypatch, recover
):
    from loushang.ai.errors import AIRateLimitError

    class LimitedAdapter(Adapter):
        limited = True

        async def invoke_prepared_raw(self, request, prepared):
            if self.limited:
                self.calls += 1
                raise AIRateLimitError("Provider quota exhausted")
            async for part in super().invoke_prepared_raw(request, prepared):
                yield part

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task, adapter = task_package(tmp_path), LimitedAdapter()

    async def scenario():
        owner = await open_repository_goal(
            task=task, data_root=tmp_path / "data", model=model(adapter)
        )
        try:
            owner.create("g", command_id="create")
            await owner.advance("g", command_id="limited", revision=1, epoch=1)
            view = await owner.query("g")
            assert view.goal.status == "paused", view
            assert view.reason == "planning_model_call_failed:rate_limit"
            assert view.validity == "current"
            trace = owner.planning_trace("g")
            assert trace["consecutive_invalid"] == 0 and trace["rejections"] == []
            assert len(trace["batches"]) == 1 and trace["routes"] == []
            calls = adapter.calls
            if recover:
                adapter.limited = False
                owner.controller.control(
                    "g",
                    "resume",
                    command_id="resume",
                    revision=1,
                    epoch=view.goal.epoch,
                    reason="provider recovered",
                )
                state = owner.controller.query("g")
                result = await owner.advance(
                    "g",
                    command_id="recovered",
                    revision=1,
                    epoch=state.epoch,
                )
                assert result.outcome == "work_finished", owner.controller.last_error
                assert adapter.calls == calls + 1
                trace = owner.planning_trace("g")
                assert len(trace["routes"]) == 1 and trace["consecutive_invalid"] == 0
        finally:
            await owner.close()
        if not recover:
            cold = inspect_repository_goal(
                task=task,
                data_root=tmp_path / "data",
                session_id=owner.session_id,
                goal_id="g",
            )
            assert cold.reason == view.reason and cold.validity == "current"
            assert cold.goal.status == "paused"

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


@pytest.mark.parametrize(
    "closeout", ["model", "host", "host_failed_check", "host_rejected_review"]
)
def test_repository_method_executes_original_write_tool_then_independent_verifier(
    tmp_path, monkeypatch, closeout
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task = task_package(tmp_path, initial="VALUE = 0\n")

    host = closeout != "model"
    content = "VALUE = 2\n" if closeout == "host_failed_check" else "VALUE = 1\n"

    class ImplementAdapter(Adapter):
        wrote = False
        sealed = False

        async def invoke_prepared_raw(self, request, prepared):
            assert not self.sealed, "host closeout must not call the model"
            if not request.context.tools:
                initial = self.calls == 0
                async for part in super().invoke_prepared_raw(request, prepared):
                    if initial and part["type"] == "text_delta":
                        proposal = json.loads(part["text"])
                        proposal.update(
                            next_action="implement",
                            targets=["reader"],
                            expected_evidence=["method_execution"],
                            remaining_route=[
                                {"action": "implement", "targets": ["reader"]},
                                {"action": "verify_all", "targets": []},
                            ],
                        )
                        part = {"type": "text_delta", "text": json.dumps(proposal)}
                    yield part
                return
            self.calls += 1
            prepared.payload_for_transport()
            assert {t.name for t in request.context.tools} == {"read", "edit", "write"}
            yield {"type": "response_start", "response_id": f"impl-{self.calls}"}
            if not self.wrote:
                self.wrote = True
                yield {"type": "tool_call_start", "id": "write-target", "name": "write"}
                yield {
                    "type": "tool_call_args_delta",
                    "delta": json.dumps(
                        {
                            "path": str(task.root / "target.py"),
                            "content": content,
                        }
                    ),
                }
                yield {"type": "tool_call_done"}
            else:
                yield {
                    "type": "text_delta",
                    "text": "Changed target; host must verify.",
                }
                yield {"type": "stop_reason", "stop_reason": "stop"}
            yield {"type": "response_done"}

    adapter = ImplementAdapter()

    async def scenario():
        owner = await open_repository_goal(
            task=task, data_root=tmp_path / "data", model=model(adapter)
        )
        try:
            owner.create("g", command_id="create")
            session_id = owner.session_id
            for n in range(2 if host else 4):
                result = await owner.advance(
                    "g", command_id=f"a-{n}", revision=1, epoch=1
                )
                assert result.outcome == "work_finished", (
                    result,
                    owner.controller.last_error,
                )
            assert (task.root / "target.py").read_text() == content
            before_closeout = owner.planning_trace("g")
            expected_phases = ["planning", "repair"]
            if host:
                # One plan, one tool call and its continuation.
                assert adapter.calls == 3
                adapter.sealed = True
                assert [
                    b["phase"] for b in before_closeout["batches"]
                ] == expected_phases
                assert (await owner.query("g")).goal.status == "active"
                assert (
                    await owner.query("g")
                ).reason == "repository_verification_required"
                inventory = task.snapshot()
                # Reject the pre-repair inventory without admitting another Work.
                with pytest.raises(GoalError, match="inventory changed"):
                    await owner.verify_current(
                        "g",
                        command_id="stale",
                        revision=1,
                        epoch=1,
                        expected_inventory=task.config["workspace_start"],
                    )
                assert len(owner.controller.history.batches) == 2
                verification = await owner.verify_current(
                    "g",
                    command_id="verify",
                    revision=1,
                    epoch=1,
                    expected_inventory=inventory,
                )
                assert verification.outcome == "work_finished"
                assert (
                    await owner.verify_current(
                        "g",
                        command_id="verify",
                        revision=1,
                        epoch=1,
                        expected_inventory=inventory,
                    )
                    == verification
                )
                assert len(owner.controller.history.batches) == 3
            else:
                expected_phases.append("planning")
            expected_phases.append("verification")
            trace = owner.planning_trace("g")
            assert [b["phase"] for b in trace["batches"]] == expected_phases
            repair = next(
                e["result"] for e in trace["evidence"] if e["phase"] == "repair"
            )
            assert repair["before"] != repair["after"]
            identity, passed = owner.review_basis("g")
            assert identity["goal_id"] == "g" and identity["session_id"] == session_id
            assert identity["inventory"] == repair["after"] == task.snapshot()
            assert (
                identity["verification_operation_id"]
                == trace["batches"][-1]["operation_id"]
            )
            assert identity["verification_run_id"] == trace["batches"][-1]["run_id"]
            if closeout == "host_failed_check":
                assert not passed
                assert trace["batches"][-1]["work_status"] == "failed"
                with pytest.raises(GoalError, match="not passed"):
                    await submit(
                        owner,
                        "g",
                        expected_inventory=task.snapshot(),
                        approved=True,
                        reviewer="offline independent host",
                        reason="cannot approve failed proof",
                    )
                expected_reason = "repository_verification_required"
            else:
                assert passed and (await owner.query("g")).reason == "review_required"
                assert owner.controller.query("g").status == "active"
                if host:
                    with pytest.raises(GoalError, match="review_required"):
                        await owner.advance(
                            "g", command_id="no-extra-plan", revision=1, epoch=1
                        )
                if closeout == "host_rejected_review":
                    await owner.submit_review(
                        "g",
                        command_id="review",
                        review_id="review",
                        expected_identity=identity,
                        decision="rejected",
                        reviewer="offline independent host",
                        reason="scope finding remains",
                        coverage=["RC-05"],
                        findings=[
                            dict(
                                requirement_id="RC-05",
                                evidence="target.py fixture change",
                                expected="independent scope acceptance",
                                actual="unresolved scope finding",
                            )
                        ],
                    )
                    expected_reason = "review_rejected"
                else:
                    await submit(
                        owner,
                        "g",
                        expected_inventory=task.snapshot(),
                        approved=True,
                        reviewer="offline independent host",
                        reason="bounded fixture change verified",
                    )
                    expected_reason = "repository_contract_and_review_satisfied"
                expected_phases.append("review")
            final = await owner.query("g")
            completed = closeout in {"model", "host"}
            assert final.goal.status == ("completed" if completed else "active")
            assert final.reason == expected_reason
            assert final.goal.id == "g" and final.goal.revision == final.goal.epoch == 1
            assert list(owner.controller.history.goals) == ["g"]
            assert owner.session_id == session_id
            # Original profile budget is not reset or enlarged.
            assert final.goal.limit == 20
            final_trace = owner.planning_trace("g")
            assert [b["phase"] for b in final_trace["batches"]] == expected_phases
            assert final_trace["planning_intents"] == (1 if host else 2)
            assert adapter.calls == (3 if host else 4)
            assert not owner.controller.facts().unresolved
            assert not owner._work.active_runs()
            if host:
                assert len(final_trace["batches"]) == (
                    3 if closeout == "host_failed_check" else 4
                )
                assert (
                    await owner.verify_current(
                        "g",
                        command_id="verify",
                        revision=1,
                        epoch=1,
                        expected_inventory=inventory,
                    )
                    == verification
                )
                assert owner.planning_trace("g") == final_trace
        finally:
            await owner.close()
        cold = inspect_repository_goal(
            task=task, data_root=tmp_path / "data", session_id=session_id, goal_id="g"
        )
        assert cold.goal.status == final.goal.status and cold.reason == expected_reason
        assert cold.validity == ("current" if completed else "not_satisfied")
        assert cold.planning == final_trace
        assert not cold.execution_unresolved
        assert adapter.calls == (3 if host else 4)

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


def test_task_protected_inputs_and_extra_file_are_rejected(tmp_path):
    task = task_package(tmp_path)
    task.snapshot()
    (task.root / "unexpected.py").write_text("pass")
    with pytest.raises(GoalError, match="file set"):
        task.snapshot()
    (task.root / "unexpected.py").unlink()
    (task.path.parent / "test_contract.py").write_text("pass")
    with pytest.raises(GoalError, match="protected"):
        task.snapshot()


def test_model_cannot_supply_review_or_arbitrary_command():
    value = {
        "next_action": "bash",
        "targets": ["rm"],
        "requirement_ids": [],
        "rationale": "run",
        "expected_evidence": [],
        "remaining_route": [{"action": "bash", "targets": ["rm"]}],
        "change_reason": "",
        "evidence_refs": [],
    }
    with pytest.raises(GoalError):
        parse_repository_proposal(json.dumps(value).encode(), known_evidence=[])

    value["approved"] = True
    with pytest.raises(GoalError):
        parse_repository_proposal(json.dumps(value).encode(), known_evidence=[])


@pytest.mark.parametrize("finish", [False, True])
def test_rejected_review_reaches_next_plan_and_survives_cold_read(
    tmp_path, monkeypatch, finish
):
    """A real SDK loop with deterministic provider, not proof of live replanning."""
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task = task_package(tmp_path)

    class FeedbackAdapter(Adapter):
        saw_feedback = False
        repaired = False

        async def invoke_prepared_raw(self, request, prepared):
            if not request.context.tools:
                payload = json.dumps(prepared.payload_for_transport())
                feedback = "missing explanation" in payload
                self.saw_feedback |= feedback
                async for part in super().invoke_prepared_raw(request, prepared):
                    if feedback and not self.repaired and part["type"] == "text_delta":
                        proposal = json.loads(part["text"])
                        proposal.update(
                            next_action="implement",
                            targets=["reader"],
                            expected_evidence=["method_execution"],
                            remaining_route=[
                                {"action": "implement", "targets": ["reader"]},
                                {"action": "verify_all", "targets": []},
                            ],
                            change_reason="Address the newly observed review finding",
                        )
                        part = {"type": "text_delta", "text": json.dumps(proposal)}
                    yield part
                return
            self.calls += 1
            prepared.payload_for_transport()
            yield {"type": "response_start", "response_id": f"repair-{self.calls}"}
            if not self.repaired:
                self.repaired = True
                yield {"type": "tool_call_start", "id": "write", "name": "write"}
                yield {
                    "type": "tool_call_args_delta",
                    "delta": json.dumps(
                        {
                            "path": str(task.root / "target.py"),
                            "content": "VALUE = 1\n# explanation\n",
                        }
                    ),
                }
                yield {"type": "tool_call_done"}
            else:
                yield {"type": "text_delta", "text": "Ready for independent checks."}
                yield {"type": "stop_reason", "stop_reason": "stop"}
            yield {"type": "response_done"}

    adapter = FeedbackAdapter()

    async def scenario():
        owner = await open_repository_goal(
            task=task, data_root=tmp_path / "data", model=model(adapter)
        )
        try:
            owner.create("g", command_id="create")
            for n in range(2):
                await owner.advance("g", command_id=f"initial-{n}", revision=1, epoch=1)
            identity, passed = owner.review_basis("g")
            assert passed
            args = dict(
                command_id="negative",
                review_id="negative",
                expected_identity=identity,
                decision="rejected",
                reviewer="trusted fixture reviewer",
                reason="missing explanation",
                coverage=["RC-05"],
                findings=[
                    {
                        "requirement_id": "RC-05",
                        "evidence": "target.py:1",
                        "expected": "explanation comment",
                        "actual": "missing explanation",
                    }
                ],
            )
            receipt = await owner.submit_review("g", **args)
            assert receipt.outcome == "work_finished"
            assert owner.controller.query("g").status == "active"
            count = len(owner.controller.history.batches)
            assert await owner.submit_review("g", **args) == receipt
            assert len(owner.controller.history.batches) == count and adapter.calls == 1
            with pytest.raises(GoalError, match="different content"):
                await owner.submit_review("g", **{**args, "reason": "changed"})
            with pytest.raises(GoalError, match="belongs to review"):
                await owner.advance("g", command_id="negative", revision=1, epoch=1)
            with pytest.raises(GoalError, match="conflicting review"):
                await owner.submit_review(
                    "g", **{**args, "command_id": "overwrite", "review_id": "overwrite"}
                )
            assert (await owner.query("g")).reason == "review_rejected"
            if not finish:
                await owner.close()
                cold = inspect_repository_goal(
                    task=task,
                    data_root=tmp_path / "data",
                    session_id=owner.session_id,
                    goal_id="g",
                )
                assert (
                    cold.reason == "review_rejected"
                    and cold.planning["status"] == "known"
                )
                reviews = [
                    e for e in cold.planning["evidence"] if e["phase"] == "review"
                ]
                assert reviews[0]["result"]["findings"] == args["findings"]
                assert reviews[0]["report_ref"]["blob"]["sessionId"] == owner.session_id
                assert len(reviews[0]["report_ref"]["blob"]["sha256"]) == 64
                return
            for n in range(4):
                result = await owner.advance(
                    "g", command_id=f"after-{n}", revision=1, epoch=1
                )
                assert result.outcome == "work_finished", owner.controller.last_error
            assert adapter.saw_feedback and adapter.repaired
            assert (await owner.query("g")).reason == "review_required"
            new_identity, passed = owner.review_basis("g")
            assert passed and new_identity["inventory"] != identity["inventory"]
            with pytest.raises(GoalError, match="basis changed"):
                await owner.submit_review(
                    "g", **{**args, "command_id": "stale", "review_id": "stale"}
                )
            positive = {
                **args,
                "command_id": "positive",
                "review_id": "positive",
                "expected_identity": new_identity,
                "decision": "approved",
                "reason": "finding resolved",
                "coverage": ["RC-05", "RC-06"],
                "findings": [],
            }
            receipt = await owner.submit_review("g", **positive)
            assert receipt.outcome == "completed"
            assert await owner.submit_review("g", **positive) == receipt
        finally:
            await owner.close()
        cold = inspect_repository_goal(
            task=task,
            data_root=tmp_path / "data",
            session_id=owner.session_id,
            goal_id="g",
        )
        assert cold.goal.status == "completed" and cold.validity == "current"
        assert (
            len([e for e in cold.planning["evidence"] if e["phase"] == "review"]) == 2
        )

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


@pytest.mark.parametrize("fault", ["publish_failed", "busy", "missing_blob"])
def test_review_failure_never_becomes_approval(tmp_path, monkeypatch, fault):
    from loushang.coding.adapters import _goal_repository_review as reviews
    from loushang.coding.adapters._work_evidence import project_work_evidence

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task, adapter = task_package(tmp_path), Adapter()

    async def scenario():
        owner = await open_repository_goal(
            task=task, data_root=tmp_path / "data", model=model(adapter)
        )
        try:
            owner.create("g", command_id="create")
            for n in range(2):
                await owner.advance("g", command_id=f"a-{n}", revision=1, epoch=1)
            identity, _ = owner.review_basis("g")
            args = dict(
                command_id="r",
                review_id="r",
                expected_identity=identity,
                decision="approved",
                reviewer="trusted",
                reason="scope verified",
                coverage=["RC-05", "RC-06"],
                findings=[],
            )
            if fault == "publish_failed":
                original = reviews.publish_report

                def failed(*a, **kw):
                    original(*a, **kw)
                    raise OSError("append acknowledgement unknown")

                monkeypatch.setattr(reviews, "publish_report", failed)
                await owner.submit_review("g", **args)
                assert owner.controller.query("g").status != "completed"
                assert (await owner.query("g")).validity == "unknown"
            elif fault == "busy":
                entered, release = asyncio.Event(), asyncio.Event()
                original = reviews.ReviewWork.execute

                async def slow(executor, operation, context):
                    entered.set()
                    await release.wait()
                    return await original(executor, operation, context)

                monkeypatch.setattr(reviews.ReviewWork, "execute", slow)
                pending = asyncio.create_task(owner.submit_review("g", **args))
                await entered.wait()
                try:
                    with pytest.raises(GoalError, match="busy"):
                        await owner.advance(
                            "g", command_id="parallel", revision=1, epoch=1
                        )
                    with pytest.raises(GoalError, match="busy"):
                        await owner.submit_review("g", **args)
                finally:
                    release.set()
                assert (await pending).outcome == "completed"
            else:
                assert (await owner.submit_review("g", **args)).outcome == "completed"
                record = next(
                    r
                    for r in project_work_evidence(owner._policy.log.query())
                    if r.role == "repository_review"
                )
                original = owner._policy.blobs.read_bytes

                def missing(ref):
                    if ref == record.blob:
                        raise FileNotFoundError("review lost")
                    return original(ref)

                monkeypatch.setattr(owner._policy.blobs, "read_bytes", missing)
                assert (await owner.query("g")).validity == "unknown"
        finally:
            await owner.close()

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


@pytest.mark.skipif(os.name != "posix", reason="process group contract")
def test_verifier_settles_descendant_after_parent_exits():
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,time; pid=os.fork(); print(pid, flush=True) if pid else time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    descendant = int(child.stdout.readline())
    child.wait(timeout=5)
    try:
        driver.terminate_group(child)
        # A reaped parent does not imply the process group is empty; inspect the child.
        import time

        for _ in range(100):
            path = Path(f"/proc/{descendant}/stat")
            if not path.exists() or path.read_text().split()[2] == "Z":
                break
            time.sleep(0.01)
        else:
            pytest.fail("descendant remained alive")
    finally:
        driver.terminate_group(child)
        child.stdout.close()


class DelegatingAdapter(Adapter):
    """Real SDK file tools, deterministic provider; no network calls."""

    def __init__(self, task, repairs=4):
        self.task, self.repairs = task, repairs
        self.writes = 0
        self.in_tool = False
        self.contexts = []

    async def invoke_prepared_raw(self, request, prepared):
        if not request.context.tools:
            async for part in super().invoke_prepared_raw(request, prepared):
                if self.writes < self.repairs and part["type"] == "text_delta":
                    proposal = json.loads(part["text"])
                    proposal.update(
                        next_action="implement",
                        targets=["reader"],
                        expected_evidence=["method_execution"],
                        remaining_route=[
                            {"action": "implement", "targets": ["reader"]},
                            {"action": "verify_all", "targets": []},
                        ],
                    )
                    part = {**part, "text": json.dumps(proposal)}
                yield part
            return
        self.calls += 1
        self.contexts.append(prepared.payload_for_transport())
        assert {t.name for t in request.context.tools} == {"read", "edit", "write"}
        yield {"type": "response_start", "response_id": f"delegate-{self.calls}"}
        if not self.in_tool:
            self.in_tool = True
            self.writes += 1
            yield {
                "type": "tool_call_start",
                "id": f"write-{self.writes}",
                "name": "write",
            }
            yield {
                "type": "tool_call_args_delta",
                "delta": json.dumps(
                    {
                        "path": str(self.task.root / "target.py"),
                        "content": f"VALUE = 1\n# change {self.writes}\n",
                    }
                ),
            }
            yield {"type": "tool_call_done"}
        else:
            self.in_tool = False
            yield {
                "type": "text_delta",
                "text": "Implementation ready for independent verification.",
            }
            yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


def test_delegated_goal_reuse_fresh_inherit_and_cold_proof(tmp_path, monkeypatch):
    from loushang.coding.adapters._goal_execution_context import (
        SessionChoice,
        SessionExecutionPolicy,
    )
    from loushang.harness.multiagent import ForkTier

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task = task_package(tmp_path)
    adapter = DelegatingAdapter(task)

    async def scenario():
        owner = await open_repository_goal(
            task=task,
            data_root=tmp_path / "data",
            model=model(adapter),
            execution_policy=SessionExecutionPolicy(),
        )
        try:
            owner.create("g", command_id="create")
            with pytest.raises(GoalError, match="fresh owner"):
                owner.create("other", command_id="other")
            for action in (owner.steer, owner.follow_up):
                with pytest.raises(GoalError, match="direct input"):
                    action("g", "unadmitted input")
            with pytest.raises(GoalError, match="direct input"):
                owner.clear_queue()
            for n in range(10):
                if n == 4:
                    owner.set_execution_context(SessionChoice("fresh"))
                if n == 6:
                    owner.set_execution_context(
                        SessionChoice("inherit", tier=ForkTier.last(1))
                    )
                result = await owner.advance(
                    "g", command_id=f"a-{n}", revision=1, epoch=1
                )
                assert result.outcome == "work_finished", (
                    result,
                    owner.controller.last_error,
                    owner.planning_trace("g"),
                )
                assert all(
                    r.status == "completed" for r in owner.controller.facts().runs
                ), [(r.status, r.operation_id) for r in owner.controller.facts().runs]
            contexts = owner.execution_contexts()
            assert len(contexts) == 3
            assert [c.round_id for c in contexts] == [2, 1, 1]
            assert len({c.session_id for c in contexts}) == 3
            assert owner._session.pending_message_count == 0
            view = await owner.query("g")
            assert view.reason == "review_required", (view, owner.planning_trace("g"))
            await submit(
                owner,
                "g",
                expected_inventory=task.snapshot(),
                approved=True,
                reviewer="offline reviewer",
                reason="checked frozen requirements",
            )
            assert (await owner.query("g")).validity == "current"
            from loushang.harness.artifacts import SessionBlobStore

            original_read = SessionBlobStore.read_bytes
            for field, invalid in (
                ("version", True),
                ("round_id", 99),
                ("origin_operation_id", "wrong-origin"),
                ("child_session_id", owner.session_id),
            ):

                def damaged(store, ref, field=field, invalid=invalid):
                    content = original_read(store, ref)
                    if ref.logical_name.endswith("/delegated_method_report.json"):
                        value = json.loads(content)
                        value[field] = invalid
                        return json.dumps(value).encode()
                    return content

                with monkeypatch.context() as patch:
                    patch.setattr(SessionBlobStore, "read_bytes", damaged)
                    assert (await owner.query("g")).validity == "unknown"
            sid = owner.session_id
        finally:
            await owner.close()
        assert all(v.status == "closed" for v in owner._delegation.views())
        cold = inspect_repository_goal(
            task=task, data_root=tmp_path / "data", session_id=sid, goal_id="g"
        )
        assert cold.validity == "current", cold
        from loushang.coding.adapters._goal_store import goal_journal_path
        from loushang.coding.adapters.goal import read_goal_work_sources
        from loushang.harness.transcript.source_reader import TranscriptSourceReader

        reader = TranscriptSourceReader(
            session_file=Path(owner._session.session_manager.get_session_file()),
            conversation_id=sid,
            store_state_root=tmp_path / "platform/state/session-stores",
        )
        work_file = goal_journal_path(tmp_path / "data/sessions", sid).with_suffix(
            ".work.jsonl"
        )
        original_work = work_file.read_bytes()
        try:
            views = await read_goal_work_sources(
                data_root=tmp_path / "data", session_id=sid, goal_id="g", reader=reader
            )
            assert all(v.status == "not_declared" for v in views)
            lines = [json.loads(line) for line in original_work.splitlines()]
            for line in lines:
                payload = line.get("payload", {}).get("payload", {})
                if "coding_goal_context" in payload:
                    payload["coding_goal_context"]["version"] = 999
                    break
            work_file.write_text("".join(json.dumps(line) + "\n" for line in lines))
            with pytest.raises(GoalError, match="delegated"):
                await read_goal_work_sources(
                    data_root=tmp_path / "data",
                    session_id=sid,
                    goal_id="g",
                    reader=reader,
                )
        finally:
            work_file.write_bytes(original_work)
            await reader.aclose()
        blobs = owner._policy.blobs
        evidence = next(
            r
            for r in blobs.records
            if r.logical_name.endswith("/delegated_method_report.json")
        )
        path = blobs.objects_root / evidence.blob_id
        content = path.read_bytes()
        path.unlink()
        missing = inspect_repository_goal(
            task=task, data_root=tmp_path / "data", session_id=sid, goal_id="g"
        )
        assert missing.validity == "unknown"
        path.write_bytes(content)
        # Unchanged bytes at a replacement physical store are not the source
        # admitted for inheritance; no Goal/Work/report content is modified.
        root = tmp_path / "data/sessions"
        saved = tmp_path / "data/original-sessions"
        root.rename(saved)
        shutil.copytree(saved, root)
        try:
            replaced = inspect_repository_goal(
                task=task, data_root=tmp_path / "data", session_id=sid, goal_id="g"
            )
            assert replaced.validity == "unknown", replaced
        finally:
            shutil.rmtree(root)
            saved.rename(root)

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


@pytest.mark.parametrize("stage", ["create", "round", "reuse"])
def test_delegated_cancellation_joins_actual_child(tmp_path, monkeypatch, stage):
    from loushang.coding.adapters import _goal_delegation as delegation
    from loushang.coding.adapters._goal_execution_context import SessionExecutionPolicy

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task = task_package(tmp_path)

    async def scenario():
        started, stopped = asyncio.Event(), asyncio.Event()

        class WaitingAdapter(DelegatingAdapter):
            async def invoke_prepared_raw(self, request, prepared):
                if request.context.tools and (
                    stage != "reuse" or (self.writes >= 1 and not self.in_tool)
                ):
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        stopped.set()
                async for chunk in super().invoke_prepared_raw(request, prepared):
                    yield chunk

        adapter = WaitingAdapter(task)
        owner = await open_repository_goal(
            task=task,
            data_root=tmp_path / "data",
            model=model(adapter),
            execution_policy=SessionExecutionPolicy(),
        )
        original_create = delegation._ChildRuntime.create_session
        if stage == "create":

            async def wait_create(self, *, cwd):
                await original_create(self, cwd=cwd)
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

            monkeypatch.setattr(delegation._ChildRuntime, "create_session", wait_create)
        try:
            owner.create("g", command_id="create")
            count = 3 if stage == "reuse" else 1
            for n in range(count):
                assert (
                    await owner.advance("g", command_id=f"a-{n}", revision=1, epoch=1)
                ).outcome == "work_finished"
            running = asyncio.create_task(
                owner.advance("g", command_id="cancel-work", revision=1, epoch=1)
            )
            await asyncio.wait_for(started.wait(), 15)
            owner.controller.control(
                "g",
                "pause",
                command_id="pause",
                revision=1,
                epoch=1,
                reason="stop actual child",
            )
            await asyncio.wait_for(owner.controller.request_cancel("g"), 15)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(running, 15)
            await owner.controller.settle_work()
            assert stopped.is_set()
            runs = owner.controller.facts().runs
            assert runs[-1].status == "cancelled", runs[-1]
            assert owner._work.get_cancellation(runs[-1].run_id).status == "settled"
            assert not any(c.status == "running" for c in owner.execution_contexts())
            assert owner._allowance.phase is None
        finally:
            await owner.close()
            get_default_api_registry().unregister_api_adapters(adapter.api)

    asyncio.run(scenario())


def test_delegated_close_retains_parent_until_child_retry(tmp_path, monkeypatch):
    from loushang.coding.adapters._goal_execution_context import SessionExecutionPolicy

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task = task_package(tmp_path)
    adapter = DelegatingAdapter(task)

    async def scenario():
        owner = await open_repository_goal(
            task=task,
            data_root=tmp_path / "data",
            model=model(adapter),
            execution_policy=SessionExecutionPolicy(),
        )
        owner.create("g", command_id="create")
        for n in range(2):
            assert (
                await owner.advance("g", command_id=f"a-{n}", revision=1, epoch=1)
            ).outcome == "work_finished"
        child = next(iter(owner._delegation.children.values()))
        original = child.sdk.dispose_session_runtime
        attempts = 0

        async def fail_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("injected child cleanup failure")
            await original()

        monkeypatch.setattr(child.sdk, "dispose_session_runtime", fail_once)
        with pytest.raises(ExceptionGroup):
            await owner.close()
        assert (
            not owner._session_retired
            and not owner._source_retired
            and not owner._writer_closed
        )
        assert not owner._closed
        await owner.close()
        assert attempts == 2 and owner._closed

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


@pytest.mark.parametrize("tier", ["all", "last"])
def test_goal_inherited_context_fixed_watermark_and_original_codecs(tier):
    from types import SimpleNamespace

    from loushang.ai.types import (
        AssistantMessage,
        TextPart,
        ToolCall,
        ToolResultMessage,
        Usage,
        UserMessage,
    )
    from loushang.coding.adapters._goal_execution_context import (
        SessionChoice,
        build_context,
    )
    from loushang.harness.conversation.types import ConversationRecord
    from loushang.harness.multiagent import ForkTier
    from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND

    def assistant(content):
        return AssistantMessage(
            role="assistant",
            content=content,
            api="test",
            provider="test",
            endpoint="test",
            model="test",
            response_id=None,
            usage=Usage(0, 0, 0, 0, 0, None),
            stop_reason="stop",
            error_message=None,
            timestamp=0,
        )

    messages = [
        UserMessage(role="user", timestamp=0, content="earlier"),
        assistant(content=[TextPart(type="text", text="earlier answer")]),
        UserMessage(role="user", timestamp=0, content="current"),
        assistant(
            content=[
                ToolCall(type="toolCall", id="t1", name="read", arguments={"path": "a"})
            ]
        ),
        ToolResultMessage(
            role="toolResult",
            is_error=False,
            timestamp=0,
            tool_call_id="t1",
            tool_name="read",
            content=[TextPart(type="text", text="contents")],
        ),
        assistant(content=[TextPart(type="text", text="current answer")]),
    ]
    records = tuple(
        ConversationRecord(
            str(n),
            str(n - 1) if n else None,
            AGENT_MESSAGE_KIND,
            1,
            "2026-10-31T00:00:00Z",
            msg,
        )
        for n, msg in enumerate(messages)
    )
    manager = SimpleNamespace(
        header=SimpleNamespace(conversation_id="parent"),
        get_leaf_id=lambda: "5",
        get_branch=lambda leaf: records[: int(leaf) + 1],
    )
    session = SimpleNamespace(session_id="parent", session_manager=manager)
    choice = SessionChoice(
        "inherit", tier=ForkTier.all() if tier == "all" else ForkTier.last(1)
    )
    plan, material = build_context(
        session=session,
        blobs=None,
        choice=choice,
        system_prompt="bounded",
        source_identity="trusted",
        watermark="5",
    )
    assert list(plan.history.messages) == (messages if tier == "all" else messages[2:])
    messages[3].content[0].arguments["path"] = "changed"
    assert plan.history.messages[-3].content[0].arguments["path"] == "a"
    _, changed = build_context(
        session=session,
        blobs=None,
        choice=choice,
        system_prompt="bounded",
        source_identity="trusted",
        watermark="5",
    )
    assert material["messages_sha256"] != changed["messages_sha256"]
    # A subsequent parent append is outside the explicitly selected watermark.
    records += (
        ConversationRecord(
            "6",
            "5",
            AGENT_MESSAGE_KIND,
            1,
            "2026-10-31T00:00:00Z",
            UserMessage(role="user", timestamp=0, content="later"),
        ),
    )
    manager.get_leaf_id = lambda: "6"
    _, fixed = build_context(
        session=session,
        blobs=None,
        choice=choice,
        system_prompt="bounded",
        source_identity="trusted",
        watermark="5",
    )
    assert fixed == changed


def test_goal_inherited_history_refuses_orphans_unknown_versions_and_empty_fallback():
    from types import SimpleNamespace

    from loushang.ai.types import TextPart, ToolResultMessage
    from loushang.coding.adapters._goal_execution_context import (
        SessionChoice,
        build_context,
    )
    from loushang.harness.conversation.types import ConversationRecord
    from loushang.harness.multiagent import ForkTier
    from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND

    records = (
        ConversationRecord(
            "r",
            None,
            AGENT_MESSAGE_KIND,
            1,
            "2026-10-31T00:00:00Z",
            ToolResultMessage(
                role="toolResult",
                is_error=False,
                timestamp=0,
                tool_call_id="orphan",
                tool_name="read",
                content=[TextPart(type="text", text="unknown")],
            ),
        ),
    )
    manager = SimpleNamespace(
        header=SimpleNamespace(conversation_id="p"),
        get_leaf_id=lambda: "r",
        get_branch=lambda leaf: records,
    )
    kwargs = dict(
        session=SimpleNamespace(session_id="p", session_manager=manager),
        blobs=None,
        system_prompt="bounded",
        source_identity="trusted",
    )
    with pytest.raises(GoalError, match="repair"):
        build_context(**kwargs, choice=SessionChoice("inherit", tier=ForkTier.all()))
    from dataclasses import replace

    records = (replace(records[0], payload_version=999),)
    with pytest.raises(GoalError, match="unsupported"):
        build_context(**kwargs, choice=SessionChoice("inherit", tier=ForkTier.all()))
    from loushang.harness.transcript.kinds import CONVERSATION_METADATA_PATCH_KIND
    from loushang.harness.transcript.types import ConversationMetadataPatch

    records = (
        replace(
            records[0],
            payload_version=1,
            kind=CONVERSATION_METADATA_PATCH_KIND,
            payload=ConversationMetadataPatch(),
        ),
    )
    # An entirely non-context branch cannot silently mean fresh.
    with pytest.raises(GoalError, match="empty"):
        build_context(**kwargs, choice=SessionChoice("inherit", tier=ForkTier.last(1)))
    plan, material = build_context(
        **kwargs,
        choice=SessionChoice("inherit", tier=ForkTier.last(1), allow_empty=True),
    )
    assert (
        plan.history.effective_tier.mode == "none" and material["allow_empty"] is True
    )


def test_inherited_images_are_preserved_or_rejected(tmp_path):
    from types import SimpleNamespace

    from loushang.ai.types import ImagePart, UserMessage
    from loushang.coding.adapters._goal_execution_context import (
        SessionChoice,
        build_context,
    )
    from loushang.harness.artifacts import SessionBlobStore
    from loushang.harness.conversation.types import ConversationRecord
    from loushang.harness.multiagent import ForkTier
    from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
    from loushang.harness.transcript.types import SessionImagePart

    blobs = SessionBlobStore(tmp_path, "p")
    ref = blobs.put_bytes(
        b"image-bytes", logical_name="image.png", kind="image", media_type="image/png"
    )
    msg = UserMessage(
        role="user", content=[SessionImagePart(type="image", blob=ref)], timestamp=0
    )
    records = (
        ConversationRecord(
            "r", None, AGENT_MESSAGE_KIND, 1, "2026-10-31T00:00:00Z", msg
        ),
    )
    session = SimpleNamespace(
        session_id="p",
        session_manager=SimpleNamespace(
            header=SimpleNamespace(conversation_id="p"),
            get_leaf_id=lambda: "r",
            get_branch=lambda leaf: records,
        ),
    )
    kwargs = dict(
        session=session,
        choice=SessionChoice("inherit", tier=ForkTier.all()),
        system_prompt="bounded",
        source_identity="trusted",
    )
    plan, _ = build_context(**kwargs, blobs=blobs)
    assert isinstance(plan.history.messages[0].content[0], ImagePart)
    with pytest.raises(GoalError, match="image could not be preserved"):
        build_context(**kwargs, blobs=SessionBlobStore(tmp_path, "other"))


@pytest.mark.parametrize("failure", ["preflight", "dispatch"])
def test_delegated_capacity_failure_keeps_partial_facts_and_existing_child(
    tmp_path, monkeypatch, failure
):
    from loushang.coding.adapters._goal_execution_context import (
        SessionChoice,
        SessionExecutionPolicy,
    )
    from loushang.harness.multiagent import AgentRef, ControlLimits

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task = task_package(tmp_path)
    adapter = DelegatingAdapter(task, repairs=2)

    async def scenario():
        owner = await open_repository_goal(
            task=task,
            data_root=tmp_path / "data",
            model=model(adapter),
            execution_policy=SessionExecutionPolicy(
                limits=ControlLimits(max_open_agents=2 if failure == "preflight" else 3)
            ),
        )
        try:
            owner.create("g", command_id="create")
            for n in range(2):
                await owner.advance("g", command_id=f"a-{n}", revision=1, epoch=1)
            ref = owner.execution_contexts()[0].ref
            family = owner._delegation
            with pytest.raises(GoalError, match="unavailable"):
                family._reusable(AgentRef(ref.path, ref.incarnation + 1))
            child = family.children[ref]
            child.session.follow_up("not an admitted Work")
            with pytest.raises(GoalError, match="not idle"):
                family._reusable(ref)
            child.session.clear_queue()
            owner.set_execution_context(SessionChoice("fresh"))
            original_spawn = family.runtime.spawn_child
            if failure == "dispatch":

                async def fail_spawn(**kwargs):
                    raise RuntimeError("injected dispatch failure after admission")

                monkeypatch.setattr(family.runtime, "spawn_child", fail_spawn)
            for n in range(2, 4):
                receipt = await owner.advance(
                    "g", command_id=f"a-{n}", revision=1, epoch=1
                )
            assert adapter.writes == 1
            epoch = 1
            if failure == "preflight":
                assert receipt.outcome == "paused"
                assert len(owner.controller.facts().runs) == 3
                assert (
                    owner.controller.query("g").reason
                    == "child_session_admission:agent_limit_reached"
                )
                owner.controller.control(
                    "g",
                    "resume",
                    command_id="resume",
                    revision=1,
                    epoch=2,
                    reason="reuse existing child",
                )
                epoch = 3
            else:
                assert receipt.outcome == "work_finished"
                assert owner.controller.facts().runs[-1].status == "failed"
                trace = owner.planning_trace("g")
                assert trace["status"] == "known", trace
                assert trace["evidence"][-1]["result"]["status"] == "partial"
                monkeypatch.setattr(family.runtime, "spawn_child", original_spawn)
            owner.set_execution_context(SessionChoice("reuse", target=ref))
            for n in range(4, 8):
                await owner.advance("g", command_id=f"a-{n}", revision=1, epoch=epoch)
            assert (await owner.query("g")).reason == "review_required", (
                owner.planning_trace("g")
            )
            await submit(
                owner,
                "g",
                expected_inventory=task.snapshot(),
                approved=True,
                reviewer="test",
                reason="partial failure did not invent evidence",
            )
            assert (await owner.query("g")).validity == "current"
            await owner.release_execution_context(ref)
            with pytest.raises(GoalError, match="unavailable"):
                family._reusable(ref)
        finally:
            await owner.close()

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


def test_cancelled_release_retains_cleanup_debt_until_original_owner_settles(
    tmp_path, monkeypatch
):
    from loushang.coding.adapters._goal_execution_context import (
        SessionChoice,
        SessionExecutionPolicy,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task = task_package(tmp_path)
    adapter = DelegatingAdapter(task, repairs=3)

    async def scenario():
        owner = await open_repository_goal(
            task=task,
            data_root=tmp_path / "data",
            model=model(adapter),
            execution_policy=SessionExecutionPolicy(),
        )
        started, fail_now = asyncio.Event(), asyncio.Event()
        child = original = None
        try:
            owner.create("g", command_id="create")
            for n in range(4):
                if n == 2:
                    owner.set_execution_context(SessionChoice("fresh"))
                assert (
                    await owner.advance("g", command_id=f"a-{n}", revision=1, epoch=1)
                ).outcome == "work_finished"
            first, second = owner.execution_contexts()
            family = owner._delegation
            child = family.children[second.ref]
            original = child.sdk.dispose_session_runtime

            async def fail_close():
                started.set()
                await fail_now.wait()
                raise RuntimeError("cleanup failed after waiting caller was cancelled")

            monkeypatch.setattr(child.sdk, "dispose_session_runtime", fail_close)
            release = asyncio.create_task(owner.release_execution_context(second.ref))
            await asyncio.wait_for(started.wait(), 15)
            release.cancel()
            with pytest.raises(asyncio.CancelledError):
                await release
            cleanup = tuple(family.runtime._cleanup_tasks)
            fail_now.set()
            results = await asyncio.gather(*cleanup)
            assert any(r.dispose_errors for r in results)
            assert family.cleanup_pending == {second.ref}
            with pytest.raises(GoalError, match="unavailable"):
                owner.set_execution_context(SessionChoice("reuse", target=first.ref))
            assert (await owner.query("g")).validity == "unknown"
            monkeypatch.setattr(child.sdk, "dispose_session_runtime", original)
            await owner.release_execution_context(second.ref)
            assert not family.cleanup_pending
            owner.set_execution_context(SessionChoice("reuse", target=first.ref))
            for n in range(4, 6):
                assert (
                    await owner.advance("g", command_id=f"a-{n}", revision=1, epoch=1)
                ).outcome == "work_finished"
            assert adapter.writes == 3
        finally:
            fail_now.set()
            if original is not None:
                monkeypatch.setattr(child.sdk, "dispose_session_runtime", original)
            await owner.close()

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


class NoModelAdapter(Adapter):
    async def invoke_prepared_raw(self, request, prepared):
        self.calls += 1
        raise AssertionError("host closeout must not call a model")
        yield  # pragma: no cover


def test_host_verification_zero_model_closeout_and_request_identity(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from loushang.coding.adapters._goal_store import goal_journal_path
    from loushang.harnesswork.goal import GoalBasis, GoalFacts
    from loushang.harnesswork.goal.records import plain, replay

    def corrupt_source(data):
        if "host_verification" in data.get("source", {}):
            data["source"]["basis"].update(
                scope_id="foreign-scope",
                session_id="foreign-session",
                policy_id="foreign-policy",
                policy_version=True,
            )
        return data

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task, adapter = task_package(tmp_path), NoModelAdapter()

    async def scenario():
        owner = await open_repository_goal(
            task=task, data_root=tmp_path / "data", model=model(adapter)
        )
        args = dict(
            command_id="verify", revision=1, epoch=1, expected_inventory=task.snapshot()
        )
        try:
            owner.create("g", command_id="create")
            for change in (
                {"revision": 2},
                {"epoch": 2},
                {"expected_inventory": {"target.py": "wrong"}},
            ):
                with pytest.raises(GoalError):
                    await owner.verify_current("g", **{**args, **change})
            assert not owner.controller.history.batches
            # Even when the planning observer reports its exhausted allowance,
            # trusted deterministic verification must not request another plan.
            original = owner._policy._observations

            def exhausted(*a):
                evidence, routes, rejections, _, invalid, stalled = original(*a)
                return evidence, routes, rejections, 8, invalid, stalled

            monkeypatch.setattr(owner._policy, "_observations", exhausted)
            result = await owner.verify_current("g", **args)
            monkeypatch.setattr(owner._policy, "_observations", original)
            assert result.outcome == "work_finished"
            assert await owner.verify_current("g", **args) == result
            with pytest.raises(GoalError, match="matching host"):
                await owner.verify_current(
                    "g", **{**args, "expected_inventory": {"target.py": "wrong"}}
                )
            with pytest.raises(GoalError, match="belongs to host"):
                await owner.advance("g", command_id="verify", revision=1, epoch=1)
            with pytest.raises(GoalError, match="review_required"):
                await owner.verify_current("g", **{**args, "command_id": "duplicate"})
            assert len(owner.controller.history.batches) == 1
            assert (
                await submit(
                    owner,
                    "g",
                    expected_inventory=task.snapshot(),
                    approved=True,
                    reviewer="independent test",
                    reason="verified fixed task and scope",
                )
            ).outcome == "completed"
            assert await owner.verify_current("g", **args) == result
            assert len(owner.controller.history.batches) == 2
            assert owner._policy.pending_verification is None
            assert adapter.calls == 0 and owner._allowance.calls == 0
            sid = owner.session_id
            core = owner.controller
            changed = replay(
                core.header,
                [
                    replace(record, data=corrupt_source(plain(record.data)))
                    for record in core.history.records
                ],
            )
            assessment = owner._policy.assess_now(
                GoalBasis(core.header, changed.goal("g"), changed.sequence),
                GoalFacts(changed.batches, core.facts().runs),
            )
            assert assessment.proof["validity"] == "unknown"
        finally:
            await owner.close()
        cold = inspect_repository_goal(
            task=task, data_root=tmp_path / "data", session_id=sid, goal_id="g"
        )
        assert cold.goal.status == "completed" and cold.validity == "current"
        assert cold.planning["planning_intents"] == 0
        journal = goal_journal_path(tmp_path / "data/sessions", sid)
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        for row in rows:
            if row.get("kind") == "batch_intent":
                corrupt_source(row["data"])
        journal.write_text("".join(json.dumps(row) + "\n" for row in rows))
        cold = inspect_repository_goal(
            task=task, data_root=tmp_path / "data", session_id=sid, goal_id="g"
        )
        assert cold.goal.status == "completed" and cold.validity == "unknown"

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


@pytest.mark.parametrize(
    "fault",
    [
        "intent_gap",
        "append_unknown",
        "paused",
        "failed_check",
        "rejected_review",
        "changed_candidate",
    ],
)
def test_host_verification_failures_never_complete_or_replay(
    tmp_path, monkeypatch, fault
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task = task_package(
        tmp_path, initial="VALUE = 2\n" if fault == "failed_check" else "VALUE = 1\n"
    )
    adapter = NoModelAdapter()

    async def scenario():
        owner = await open_repository_goal(
            task=task, data_root=tmp_path / "data", model=model(adapter)
        )
        args = dict(
            command_id="v", revision=1, epoch=1, expected_inventory=task.snapshot()
        )
        try:
            owner.create("g", command_id="create")
            if fault == "paused":
                owner.controller.control(
                    "g",
                    "pause",
                    command_id="p",
                    revision=1,
                    epoch=1,
                    reason="explicit pause",
                )
                with pytest.raises(GoalError, match="active"):
                    await owner.verify_current("g", **args)
                assert not owner.controller.history.batches
            elif fault in {"intent_gap", "append_unknown"}:
                core = owner.controller
                original = core._store.append

                def interrupted(expected, record):
                    if record.kind == "batch_intent":
                        if fault == "append_unknown":
                            original(expected, record)
                        raise OSError("intent append interrupted")
                    return original(expected, record)

                monkeypatch.setattr(core._store, "append", interrupted)
                with pytest.raises(OSError, match="interrupted"):
                    await owner.verify_current("g", **args)
                assert core.fenced
                assert not owner._work.active_runs()
                with pytest.raises(GoalError):
                    await owner.verify_current("g", **args)
                assert (
                    owner._policy.pending_verification is None
                    and not owner._repository_busy
                )
            else:
                await owner.verify_current("g", **args)
                identity, passed = owner.review_basis("g")
                if fault == "failed_check":
                    assert passed is False
                    with pytest.raises(GoalError, match="not passed"):
                        await submit(
                            owner,
                            "g",
                            expected_inventory=task.snapshot(),
                            approved=True,
                            reviewer="test",
                            reason="must reject",
                        )
                elif fault == "changed_candidate":
                    (task.root / "target.py").write_text("VALUE = 2\n")
                    with pytest.raises(GoalError):
                        await owner.submit_review(
                            "g",
                            command_id="r",
                            review_id="r",
                            expected_identity=identity,
                            decision="approved",
                            reviewer="test",
                            reason="old candidate",
                            coverage=["RC-05", "RC-06"],
                            findings=[],
                        )
                else:
                    await owner.submit_review(
                        "g",
                        command_id="r",
                        review_id="r",
                        expected_identity=identity,
                        decision="rejected",
                        reviewer="test",
                        reason="independent finding",
                        coverage=["RC-05"],
                        findings=[
                            dict(
                                requirement_id="RC-05",
                                evidence="fixture evidence",
                                expected="independent acceptance",
                                actual="unresolved finding",
                            )
                        ],
                    )
                    assert (await owner.query("g")).reason == "review_rejected"
            assert owner.controller.query("g").status != "completed"
            assert adapter.calls == 0
        finally:
            await owner.close()

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)


def test_host_verification_capacity_and_source_contract():
    from types import SimpleNamespace as NS

    from loushang.coding.adapters._goal_repository import (
        RepositoryDomain,
        _host_intent,
        _host_request,
    )

    request = _host_request("g", "v", 1, 1, {"target.py": "digest"})
    basis = NS(
        goal=NS(id="g", limit=20),
        sequence=100,
        identity={
            "goal_id": "g",
            "revision": 1,
            "epoch": 1,
            "sequence": 100,
            "scope_id": "scope",
            "session_id": "session",
            "policy_id": "policy",
            "policy_version": 1,
        },
    )
    source = {
        "phase": "verification",
        "check": "all",
        "basis": basis.identity,
        "inventory": request["expected_inventory"],
        "host_verification": request,
    }
    own = NS(
        operation_id="own",
        goal_id="g",
        command_id="v",
        revision=1,
        epoch=1,
        intent_sequence=101,
        source=source,
    )
    old = [NS(operation_id=f"old-{n}", goal_id="g") for n in range(18)]
    policy = object.__new__(RepositoryDomain)
    policy.pending_verification = request
    history = NS(
        records=(None,) * 100
        + (NS(kind="batch_intent", data={"basis": basis.identity}),)
    )
    policy.history = lambda: NS(batches=tuple(old), records=history.records)
    assert policy._host_capacity(basis)
    old.append(own)
    assert not policy._host_capacity(basis)
    assert policy._host_capacity(basis, "own")
    old.append(NS(operation_id="other", goal_id="g"))
    assert not policy._host_capacity(basis, "own")
    for mutation in (
        {"version": True},
        {"version": 2},
        {"revision": True},
        {"command_id": "other"},
        {"epoch": 2},
    ):
        own.source = {**source, "host_verification": {**request, **mutation}}
        with pytest.raises(GoalError):
            _host_intent(own, history)
    own.source = {**source, "proposal_id": "fake-model-plan"}
    with pytest.raises(GoalError):
        _host_intent(own, history)
    for mutation in (
        {"scope_id": "foreign"},
        {"session_id": "foreign"},
        {"policy_id": "foreign"},
        {"policy_version": True},
        {"policy_version": 2},
        {"sequence": 99},
    ):
        own.source = {**source, "basis": {**basis.identity, **mutation}}
        with pytest.raises(GoalError, match="intent mismatch"):
            _host_intent(own, history)


def test_host_verification_cancelled_waiter_keeps_original_work(tmp_path, monkeypatch):
    from loushang.coding.adapters._verification_work import CodingVerificationExecutor

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    task, adapter = task_package(tmp_path), NoModelAdapter()

    async def scenario():
        owner = await open_repository_goal(
            task=task, data_root=tmp_path / "data", model=model(adapter)
        )
        entered, release = asyncio.Event(), asyncio.Event()
        original = CodingVerificationExecutor.execute
        executions = []

        async def held(executor, operation, context):
            if context.step_id == "report":
                executions.append(operation.operation_id)
                entered.set()
                await release.wait()
            return await original(executor, operation, context)

        monkeypatch.setattr(CodingVerificationExecutor, "execute", held)
        args = dict(
            command_id="v", revision=1, epoch=1, expected_inventory=task.snapshot()
        )
        try:
            owner.create("g", command_id="create")
            pending = asyncio.create_task(owner.verify_current("g", **args))
            await asyncio.wait_for(entered.wait(), 15)
            with pytest.raises(GoalError, match="busy"):
                await owner.verify_current("g", **args)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert owner._policy.pending_verification is None
            assert not owner._repository_busy
            assert (await owner.verify_current("g", **args)).outcome == "pending"
            with pytest.raises(GoalError, match="unresolved"):
                await owner.verify_current("g", **{**args, "command_id": "new"})
            assert len(owner.controller.history.batches) == 1
            release.set()
            run = owner._work.get_run_for_operation(executions[0])
            # The original Work.wait cancellation path cancels its run; a
            # cached host request must preserve that outcome, not resubmit.
            assert run.status == "cancelled"
            with pytest.raises(asyncio.CancelledError):
                await owner._work.wait(run.run_id)
            assert len(executions) == 1 and adapter.calls == 0
            assert owner.controller.query("g").status != "completed"
        finally:
            release.set()
            await owner.close()

    try:
        asyncio.run(scenario())
    finally:
        get_default_api_registry().unregister_api_adapters(adapter.api)
