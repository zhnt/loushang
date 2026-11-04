"""Ordinary TUI commands reach the original Session, planning, tools and Work."""

from __future__ import annotations

import asyncio
import json
import shlex
import sys
from dataclasses import replace

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.coding import create_agent_session_runtime
from loushang.coding.ui.product_binding import build_coding_ui_controller
from loushang.harnesstui.conversation.intents import PromptIntent

from .test_current_session_goal import _model, _PreparedAdapter


class TaskAdapter(_PreparedAdapter):
    api = "interactive-development-offline"

    def __init__(self, workspace, filename, *, checks=False, blocked=False):
        super().__init__()
        self.workspace, self.filename, self.checks = workspace, filename, checks
        self.plans = self.calls = 0
        self.wrote = False
        self.blocked = blocked
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def invoke_prepared_raw(self, request, prepared):
        prepared.payload_for_transport()
        self.calls += 1
        assert request.options.retry.max_attempts == 1
        assert request.options.max_output_tokens <= 4096
        yield {"type": "response_start", "response_id": f"reply-{self.calls}"}
        self.entered.set()
        if self.blocked:
            await self.release.wait()
        if not request.context.tools:
            actions = (
                ["execute", "verify", "request_review"]
                if self.checks
                else ["execute", "request_review"]
            )
            action = actions[min(self.plans, len(actions) - 1)]
            self.plans += 1
            targets = ["check-1"] if action == "verify" else []
            value = dict(
                next_action=action,
                targets=targets,
                requirement_ids=["R1"],
                rationale=f"Create {self.filename} with the requested greeting.",
                expected_evidence=["report", "validation"]
                if action == "verify"
                else ["task_report"]
                if action == "execute"
                else [],
                remaining_route=[dict(action=action, targets=targets)],
                change_reason="",
                evidence_refs=[],
            )
            yield {"type": "text_delta", "text": json.dumps(value)}
        elif not self.wrote:
            self.wrote = True
            yield {"type": "tool_call_start", "id": "write-task-file", "name": "write"}
            yield {
                "type": "tool_call_args_delta",
                "delta": json.dumps(
                    {"path": str(self.workspace / self.filename), "content": "hello\n"}
                ),
            }
            yield {"type": "tool_call_done"}
            yield {"type": "stop_reason", "stop_reason": "toolUse"}
            yield {"type": "response_done"}
            return
        else:
            yield {
                "type": "text_delta",
                "text": "Implementation ready for independent checking and user review.",
            }
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


@pytest.mark.parametrize(
    "filename,checks", [("greeting.txt", False), ("message.md", True)]
)
def test_tui_arbitrary_target_real_tools_work_review_and_parent_survival(
    tmp_path, monkeypatch, filename, checks
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))

    async def scenario():
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "existing.txt").write_text("preexisting user change")
        adapter = TaskAdapter(workspace, filename, checks=checks)
        registry = get_default_api_registry()
        registry.register_api_adapter(adapter, source_id=adapter.api)
        sdk = create_agent_session_runtime(
            session_dir=tmp_path / "data/sessions",
            model=replace(_model(), api=adapter.api),
            enable_multiagent=False,
            active_tool_names=["read", "edit", "write", "bash"],
            allowed_tool_names=["read", "edit", "write", "bash"],
        )
        try:
            session = await sdk.create_session(cwd=str(workspace))
            controller = build_coding_ui_controller(
                session=session, runtime=sdk, verbose=True
            )

            async def command(text):
                result = await controller.dispatch(PromptIntent(text))
                assert not result.error_message, (
                    result.error_message + (result.traceback_text or "")
                    if result.error_message
                    else ""
                )
                return result.status_message

            script = (
                "from pathlib import Path; assert Path("
                + repr(filename)
                + ").read_text() == "
                + repr("hello\n")
            )
            if checks:
                method = workspace / "methods/task/write-note/SKILL.md"
                method.parent.mkdir(parents=True)
                method.write_text(
                    "---\nname: write-note\ndescription: Write the requested note\ntype: task\ndomain: coding\nversion: '1'\nplan_mode: fixed\nsteps:\n  - prepare\n  - compose\nstep_constraints:\n  compose:\n    preserve: user_files\nstep_audit:\n  compose:\n    require: review\n---\nFollow the user target using the original file tools.\n"
                )
            check = shlex.quote(sys.executable) + " -c " + shlex.quote(script)
            create = (
                f"/goal new --check {shlex.quote(check)} --method write-note -- Create {filename} with hello"
                if checks
                else f"/goal Create {filename} with hello"
            )
            text = await command(create)
            assert "Created without running" in text and adapter.calls == 0
            service = session._embedded_goal_commands
            owner, gid = service.owner, service.goal_id
            original_id, original_tools = (
                session.session_id,
                session.get_active_tool_names(),
            )
            await command("/goal review")
            await command(
                "/goal reject "
                + service.review_token
                + " Preserve existing user changes and provide the requested result."
            )
            assert adapter.calls == 0
            text = await command("/goal run")
            assert owner.controller.query(gid).status == "paused", text + repr(
                owner.controller.last_error
            )
            assert owner.controller.query(gid).reason == "review_required", text + repr(
                owner.controller.last_error
            )
            assert (workspace / filename).read_text() == "hello\n"
            assert (workspace / "existing.txt").read_text() == "preexisting user change"
            await command("/goal review")
            result = await controller.dispatch(PromptIntent("/goal accept wrong-token"))
            assert (
                result.error_message and owner.controller.query(gid).status == "paused"
            )
            before = adapter.calls
            await command("/goal accept " + service.review_token)
            assert adapter.calls == before
            assert owner.controller.query(gid).status == "completed", (
                owner.controller.query(gid).reason,
                repr(owner.controller.last_error),
                [
                    (r.status, r.error if hasattr(r, "error") else None)
                    for r in owner.controller.facts().runs
                ],
            )
            assert (await owner.query(gid)).validity == "current"
            if checks:
                from loushang.coding.adapters._work_evidence import (
                    project_work_evidence,
                )
                from loushang.harnesswork.plan_projection import project_work_plan_runs

                repair = next(
                    b
                    for b in owner.controller.history.batches
                    if b.source["phase"] == "repair"
                )
                entries = owner._work.query(operation_id=repair.operation_id)
                reports = [
                    e for e in project_work_evidence(entries) if e.role == "task_report"
                ]
                assert len(reports) == 1
                plan = project_work_plan_runs(entries)[0]
                assert [s.step_id for s in plan.steps] == ["prepare", "compose"]
                assert plan.steps[-1].metadata["planned_constraint"] == {
                    "preserve": "user_files"
                }
                assert plan.steps[-1].metadata["audit_policy"] == {"require": "review"}
                assert plan.metadata["plan_facts"]
                assert plan.steps[-1].metadata["step_facts"]
            assert owner._work is session.work_execution_backend.work_runtime
            assert owner._scope is session.runtime.execution_scope
            previous_calls = owner._allowances[gid].total_calls
            await command("/goal A different development target")
            assert (
                service.goal_id != gid
                and owner._allowances[service.goal_id].total_calls == 0
            )
            assert owner._allowances[gid].total_calls == previous_calls
            await command("/goal abandon")
            await command("/goal close")
            assert "read-only" in await command("/goal status")
            assert session.session_id == original_id
            assert session.get_active_tool_names() == original_tools
        finally:
            await sdk.dispose_session_runtime()
            registry.unregister_api_adapters(adapter.api)

    asyncio.run(scenario())


def test_stale_user_approval_and_required_checks_cannot_be_bypassed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))

    async def scenario():
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        sdk = create_agent_session_runtime(
            session_dir=tmp_path / "data/sessions",
            model=_model(),
            enable_multiagent=False,
            active_tool_names=["read", "edit", "write"],
        )
        try:
            session = await sdk.create_session(cwd=str(workspace))
            controller = build_coding_ui_controller(session=session, runtime=sdk)
            result = await controller.dispatch(
                PromptIntent("/goal new --check false -- Write a note")
            )
            assert not result.error_message, result.error_message
            service = session._embedded_goal_commands
            await controller.dispatch(PromptIntent("/goal review"))
            token = service.review_token
            (workspace / "note.txt").write_text("changed after review")
            result = await controller.dispatch(PromptIntent("/goal accept " + token))
            assert "changed" in result.error_message
            await controller.dispatch(PromptIntent("/goal review"))
            result = await controller.dispatch(
                PromptIntent("/goal accept " + service.review_token)
            )
            assert "required check" in result.error_message, result.error_message
            assert service.owner.controller.query(service.goal_id).status != "completed"
        finally:
            await sdk.dispose_session_runtime()

    asyncio.run(scenario())


@pytest.mark.parametrize("fenced", [False, True, "append_error"])
def test_running_goal_cancel_uses_original_work_and_retains_session(
    tmp_path, monkeypatch, fenced
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))

    async def scenario():
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        adapter = TaskAdapter(workspace, "note.txt", blocked=True)
        registry = get_default_api_registry()
        registry.register_api_adapter(adapter, source_id=adapter.api)
        sdk = create_agent_session_runtime(
            session_dir=tmp_path / "data/sessions",
            model=replace(_model(), api=adapter.api),
            enable_multiagent=False,
            active_tool_names=["read", "edit", "write"],
        )
        running = None
        try:
            session = await sdk.create_session(cwd=str(workspace))
            controller = build_coding_ui_controller(session=session, runtime=sdk)
            assert not (
                await controller.dispatch(PromptIntent("/goal Write a greeting"))
            ).error_message
            running = asyncio.create_task(
                controller.dispatch(PromptIntent("/goal run"))
            )
            await asyncio.wait_for(adapter.entered.wait(), 10)
            status = await controller.dispatch(PromptIntent("/goal status"))
            assert "validity=not_checked" in status.status_message
            if fenced == "append_error":

                def append_error(expected_sequence, record):
                    raise OSError("simulated control append failure")

                monkeypatch.setattr(
                    session._embedded_goal_commands.owner._store, "append", append_error
                )
            elif fenced:
                session._embedded_goal_commands.owner.controller.fence()
            else:
                paused = await controller.dispatch(PromptIntent("/goal pause"))
                assert not paused.error_message, paused.error_message
                assert (
                    session._embedded_goal_commands.owner.controller.query(
                        session._embedded_goal_commands.goal_id
                    ).status
                    == "paused"
                )
            cancelled = await asyncio.wait_for(
                controller.dispatch(PromptIntent("/goal cancel")), 10
            )
            assert not cancelled.error_message, cancelled.error_message
            await asyncio.wait_for(running, 10)
            service = session._embedded_goal_commands
            assert service.owner.controller.query(service.goal_id).status == (
                "active" if fenced else "paused"
            )
            assert adapter.calls == 1 and not (workspace / "note.txt").exists()
            assert not service.owner.controller.facts().unresolved
        finally:
            adapter.release.set()
            if running is not None and not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
            await sdk.dispose_session_runtime()
            registry.unregister_api_adapters(adapter.api)

    asyncio.run(scenario())


def test_screen_goal_controls_reuse_surface_starter_without_blocking_input():
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.coding.ui.screen_surfaces import ScreenSurfaceManager
    from loushang.harness.host.types import HostActionResult
    from loushang.harnesstui.conversation.input import (
        ConversationInputHandled,
        ConversationLocalResult,
        ConversationPromptResult,
    )
    from loushang.tui import InputEvent

    from .test_screen_coding_tui_surfaces import _app, _Session, _status_provider

    async def scenario():
        app = _app()
        entered, release = asyncio.Event(), asyncio.Event()

        async def command(text):
            entered.set()
            await release.wait()
            return HostActionResult(status_message="Original cancellation settled")

        manager = ScreenSurfaceManager(
            app=app,
            session=_Session(),
            status_provider=_status_provider(app),
            goal_command=command,
        )
        router = build_screen_input_router(
            app, should_exit=lambda _: False, is_local_command=manager.is_local_command
        )
        app.composer.set_text("/goal run")
        assert isinstance(
            router.handle(InputEvent(kind="key", key="enter")), ConversationPromptResult
        )
        app.composer.set_text("/goal run")
        assert isinstance(
            router.handle(InputEvent(kind="key", key="enter")), ConversationInputHandled
        )
        assert app.composer.value == "/goal run" and not app.state.pending_steers
        app.composer.set_text("/goal cancel")
        assert isinstance(
            router.handle(InputEvent(kind="key", key="enter")), ConversationLocalResult
        )
        await manager.handle_text("/goal cancel")
        await asyncio.wait_for(entered.wait(), 1)
        task = manager._surface_task
        assert task is not None and not task.done()
        release.set()
        await task
        assert "settled" in manager.current.content.pager.text
        manager.close()

    asyncio.run(scenario())


def test_gitlink_is_explicitly_unsupported_instead_of_reusing_missing_identity(
    tmp_path,
):
    import subprocess

    from loushang.coding.adapters.interactive_goal import workspace_snapshot
    from loushang.harnesswork.goal import GoalError

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            "160000," + "1" * 40 + ",vendor",
        ],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor/lib.py").write_text("before")
    with pytest.raises(GoalError, match="submodules"):
        workspace_snapshot(tmp_path)


def test_snapshot_worker_keeps_ui_responsive_and_close_joins_it(tmp_path, monkeypatch):
    import threading

    from loushang.coding.adapters import interactive_goal

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))
    original = interactive_goal.workspace_snapshot

    async def scenario():
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        def slow_sample(root):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            return original(root)

        monkeypatch.setattr(interactive_goal, "workspace_snapshot", slow_sample)
        sdk = create_agent_session_runtime(
            session_dir=tmp_path / "data/sessions",
            model=_model(),
            enable_multiagent=False,
            active_tool_names=["read", "edit", "write"],
        )
        pending = closing = None
        try:
            session = await sdk.create_session(cwd=str(workspace))
            controller = build_coding_ui_controller(session=session, runtime=sdk)
            pending = asyncio.create_task(
                controller.dispatch(PromptIntent("/goal Write a note"))
            )
            await asyncio.wait_for(entered.wait(), 10)
            ticks = []
            for _ in range(3):
                await asyncio.sleep(0)
                ticks.append(True)
            assert len(ticks) == 3 and not pending.done()
            closing = asyncio.create_task(
                controller.dispatch(PromptIntent("/goal close"))
            )
            await asyncio.sleep(0.02)
            assert not closing.done(), (
                "close must retain original resources until sampling has settled"
            )
            release.set()
            await asyncio.wait_for(asyncio.gather(pending, closing), 10)
            assert session._embedded_goal_commands.owner._closed
            assert not session.runtime.execution_admission.closed
        finally:
            release.set()
            for value in (pending, closing):
                if value is not None and not value.done():
                    value.cancel()
            await asyncio.gather(
                *(v for v in (pending, closing) if v is not None),
                return_exceptions=True,
            )
            await sdk.dispose_session_runtime()

    asyncio.run(scenario())


def test_goal_control_failure_still_runs_original_shell_abort():
    from types import SimpleNamespace

    from loushang.harnesstui.conversation.intents import AbortIntent

    from .test_ui_controller import _Session

    session = _Session()

    async def fail(_):
        raise RuntimeError("Goal control could not be recorded")

    session._embedded_goal_commands = SimpleNamespace(running=True, execute=fail)
    result = asyncio.run(
        build_coding_ui_controller(session=session).dispatch(AbortIntent())
    )
    assert result.error_message and session.aborted and session.bash_aborted
