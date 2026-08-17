from __future__ import annotations

import asyncio
import json
from io import StringIO


def test_prompt_steps_commands_use_the_live_session_exec_service(
    tmp_path,
    monkeypatch,
) -> None:
    import loushang.coding.workflow.command as command_module
    from loushang.harness.workspace.exec import ExecResult

    calls: list[object] = []

    class ExecService:
        async def execute(self, request, **kwargs):
            del kwargs
            calls.append(request)
            return ExecResult(exit_code=0, stdout="bound\n")

    class Session:
        def get_exec_service(self):
            return ExecService()

    async def fake_run_workflow_cli(**kwargs):
        result = await kwargs["command_runner"](
            "printf bound",
            cwd=tmp_path,
            timeout_s=5,
        )
        assert result.stdout == "bound\n"
        return 0

    monkeypatch.setattr(
        command_module,
        "run_workflow_cli",
        fake_run_workflow_cli,
    )

    exit_code = asyncio.run(
        command_module.run_prompt_steps_workflow(
            runtime=object(),
            session=Session(),
            workflow_path=tmp_path / "unused.yaml",
            cwd=tmp_path,
            stdout=StringIO(),
            stderr=StringIO(),
        )
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0].cwd == str(tmp_path)


def test_prompt_steps_command_prints_progress_before_waiting(tmp_path) -> None:
    from loushang.coding.workflow import run_prompt_steps_workflow

    workflow_file = tmp_path / "workflow.json"
    workflow_file.write_text(
        '{"name": "smoke", "steps": [{"prompt": "hello"}]}', encoding="utf-8"
    )

    class FakeSession:
        async def prompt(self, prompt: str) -> None:
            del prompt
            await asyncio.sleep(10)

    async def scenario() -> tuple[int, str]:
        stdout = StringIO()
        exit_code = await run_prompt_steps_workflow(
            runtime=object(),
            session=FakeSession(),
            workflow_path=workflow_file,
            cwd=tmp_path,
            stdout=stdout,
            stderr=StringIO(),
            default_step_timeout_s=0.01,
        )
        return exit_code, stdout.getvalue()

    exit_code, output = asyncio.run(scenario())

    assert exit_code == 1
    assert "workflow: smoke\n" in output
    assert "[1/1] running: hello\n" in output
    assert "timed out after 0.01s" in output


def test_prompt_steps_command_handles_cancelled_prompt_cleanly(tmp_path) -> None:
    from loushang.coding.workflow import run_prompt_steps_workflow

    workflow_file = tmp_path / "workflow.json"
    workflow_file.write_text(
        '{"name": "cancel", "steps": [{"prompt": "hello"}]}', encoding="utf-8"
    )

    class FakeSession:
        def __init__(self) -> None:
            self.abort_calls = 0

        async def prompt(self, prompt: str) -> None:
            del prompt
            raise asyncio.CancelledError

        async def abort(self) -> None:
            self.abort_calls += 1

    async def scenario() -> tuple[int, str, str, int]:
        session = FakeSession()
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_prompt_steps_workflow(
            runtime=object(),
            session=session,
            workflow_path=workflow_file,
            cwd=tmp_path,
            stdout=stdout,
            stderr=stderr,
        )
        return exit_code, stdout.getvalue(), stderr.getvalue(), session.abort_calls

    exit_code, stdout_text, stderr_text, abort_calls = asyncio.run(scenario())

    assert exit_code == 130
    assert "[1/1] running: hello\n" in stdout_text
    assert stderr_text == "Interrupted.\n"
    assert abort_calls == 1


def test_prompt_steps_command_runs_fake_workflow_without_session_prompt(
    tmp_path,
) -> None:
    from loushang.coding.workflow import run_prompt_steps_workflow

    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(
        """
name: fake
backend: fake
steps:
  - prompt: old task
    hold: true
  - abort: {}
  - prompt: 你好
  - expect:
      events:
        - event: assistant.message
          contains: 你好
""".lstrip(),
        encoding="utf-8",
    )

    class FakeSession:
        async def prompt(self, prompt: str) -> None:
            raise AssertionError(f"session prompt should not run: {prompt}")

    async def scenario() -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_prompt_steps_workflow(
            runtime=object(),
            session=FakeSession(),
            workflow_path=workflow_file,
            cwd=tmp_path,
            stdout=stdout,
            stderr=stderr,
        )
        return exit_code, stdout.getvalue(), stderr.getvalue()

    exit_code, stdout_text, stderr_text = asyncio.run(scenario())

    assert exit_code == 0
    assert "[1/4] running: old task\n" in stdout_text
    assert "[2/4] running: abort\n" in stdout_text
    assert "PASS\n" in stdout_text
    assert stderr_text == ""


def test_prompt_steps_command_runs_workflow_directory_matrix(tmp_path) -> None:
    from loushang.coding.workflow import run_prompt_steps_workflow

    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    (workflows_dir / "01-one.workflow.yaml").write_text(
        """
name: one
backend: fake
steps:
  - prompt: 你好
""".lstrip(),
        encoding="utf-8",
    )
    (workflows_dir / "02-two.workflow.yaml").write_text(
        """
name: two
backend: fake
steps:
  - prompt: 再见
""".lstrip(),
        encoding="utf-8",
    )

    async def scenario() -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_prompt_steps_workflow(
            runtime=None,
            session=None,
            workflow_path=workflows_dir,
            cwd=tmp_path,
            stdout=stdout,
            stderr=stderr,
        )
        return exit_code, stdout.getvalue(), stderr.getvalue()

    exit_code, stdout_text, stderr_text = asyncio.run(scenario())

    assert exit_code == 0
    assert "workflow: one\n" in stdout_text
    assert "workflow: two\n" in stdout_text
    assert "workflow summary: 2 passed, 0 failed\n" in stdout_text
    assert stderr_text == ""


def test_prompt_steps_command_outputs_json_matrix_report(tmp_path) -> None:
    from loushang.coding.workflow import run_prompt_steps_workflow

    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    (workflows_dir / "01-one.workflow.yaml").write_text(
        """
name: one
backend: fake
steps:
  - prompt: 你好
  - expect:
      events:
        - event: assistant.message
          contains: 你好
""".lstrip(),
        encoding="utf-8",
    )

    async def scenario() -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_prompt_steps_workflow(
            runtime=None,
            session=None,
            workflow_path=workflows_dir,
            cwd=tmp_path,
            stdout=stdout,
            stderr=stderr,
            output_mode="json",
        )
        return exit_code, stdout.getvalue(), stderr.getvalue()

    exit_code, stdout_text, stderr_text = asyncio.run(scenario())
    payload = json.loads(stdout_text)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["passed"] == 1
    assert payload["failed"] == 0
    assert payload["workflows"][0]["name"] == "one"
    assert payload["workflows"][0]["events"][0]["type"] == "run.started"
    assert payload["workflows"][0]["events"][1]["type"] == "assistant.message"
    assert payload["workflows"][0]["events"][1]["text"] == "你好"
    assert payload["workflows"][0]["steps"][0]["prompt"] == "你好"
    assert (
        payload["workflows"][0]["steps"][1]["checks"][0]["label"]
        == "event exists assistant.message"
    )
    assert "workflow: one" not in stdout_text
    assert stderr_text == ""
