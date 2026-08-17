from __future__ import annotations

from pathlib import Path


def test_load_workflow_from_yaml(tmp_path) -> None:
    from loushang.harness.scenario import load_workflow

    workflow_file = tmp_path / "bmi.workflow.yaml"
    workflow_file.write_text(
        """
name: bmi smoke
steps:
  - prompt: create tmp/bmi.py
    timeout_s: 120
    expect:
      assistant_contains: created
      files_exist:
        - tmp/bmi.py
      files_contain:
        tmp/bmi.py: BMI
      command:
        run: python tmp/bmi.py --help
        exit_code: 0
        stdout_contains: usage
""".lstrip(),
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_file)

    assert workflow.name == "bmi smoke"
    assert len(workflow.steps) == 1
    step = workflow.steps[0]
    assert step.prompt == "create tmp/bmi.py"
    assert step.timeout_s == 120.0
    assert step.expect.assistant_contains == ("created",)
    assert step.expect.files_exist == ("tmp/bmi.py",)
    assert step.expect.files_contain == {"tmp/bmi.py": "BMI"}
    assert step.expect.command is not None
    assert step.expect.command.run == "python tmp/bmi.py --help"
    assert step.expect.command.exit_code == 0
    assert step.expect.command.stdout_contains == ("usage",)


def test_load_workflow_from_json(tmp_path) -> None:
    from loushang.harness.scenario import load_workflow

    workflow_file = tmp_path / "workflow.json"
    workflow_file.write_text(
        """
{
  "name": "chat",
  "steps": [
    {
      "prompt": "hello",
      "expect": {
        "assistant_contains_any": ["你好", "您好"]
      }
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_file)

    assert workflow.name == "chat"
    assert workflow.steps[0].prompt == "hello"
    assert workflow.steps[0].expect.assistant_contains_any == ("你好", "您好")


def test_load_action_workflow_from_yaml(tmp_path) -> None:
    from loushang.harness.scenario import load_workflow

    workflow_file = tmp_path / "abort.workflow.yaml"
    workflow_file.write_text(
        """
name: abort recovery
backend: fake
steps:
  - prompt: long task
    hold: true
  - wait_for:
      event: run.started
      timeout_s: 1
  - wait: 0.25
  - steer: change direction
  - follow_up: next turn
  - abort: {}
  - expect:
      queue:
        steering: []
        follow_up: []
      session_state:
        runStatus: idle
        pendingMessageCount: 0
        queue:
          steering: []
          followUp: []
      session_stats:
        totalMessages: 0
        tokens:
          total: 0
        latestCompaction:
      context_usage:
        messageCount: 0
        estimatedContextTokens: 0
""".lstrip(),
        encoding="utf-8",
    )

    workflow = load_workflow(workflow_file)

    assert workflow.name == "abort recovery"
    assert workflow.backend == "fake"
    assert workflow.steps[0].kind == "prompt"
    assert workflow.steps[0].prompt == "long task"
    assert workflow.steps[0].hold is True
    assert workflow.steps[1].kind == "wait_for"
    assert workflow.steps[1].event == "run.started"
    assert workflow.steps[1].timeout_s == 1.0
    assert workflow.steps[2].kind == "wait"
    assert workflow.steps[2].duration_s == 0.25
    assert workflow.steps[3].kind == "steer"
    assert workflow.steps[3].text == "change direction"
    assert workflow.steps[4].kind == "follow_up"
    assert workflow.steps[4].text == "next turn"
    assert workflow.steps[5].kind == "abort"
    assert workflow.steps[6].kind == "expect"
    assert workflow.steps[6].expect.queue == {"steering": (), "follow_up": ()}
    assert workflow.steps[6].expect.session_state == {
        "runStatus": "idle",
        "pendingMessageCount": 0,
        "queue": {"steering": [], "followUp": []},
    }
    assert workflow.steps[6].expect.session_stats == {
        "totalMessages": 0,
        "tokens": {"total": 0},
        "latestCompaction": None,
    }
    assert workflow.steps[6].expect.context_usage == {
        "messageCount": 0,
        "estimatedContextTokens": 0,
    }


def test_builtin_workflow_scenarios_load() -> None:
    from loushang.harness.scenario import load_workflow

    paths = sorted(Path("scenarios/coding/workflows").glob("*.workflow.yaml"))

    assert paths
    for path in paths:
        workflow = load_workflow(path)
        assert workflow.backend == "fake"
        assert workflow.steps
