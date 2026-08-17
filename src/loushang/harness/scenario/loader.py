from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from loushang.harness.scenario.events import EventPattern
from loushang.harness.scenario.schema import (
    AbortStep,
    CommandExpectation,
    ExpectStep,
    FollowUpStep,
    PromptStep,
    SteerStep,
    StepExpectation,
    WaitForStep,
    WaitStep,
    Workflow,
    WorkflowExpectation,
    WorkflowStep,
)


def load_workflow(path: str | Path) -> Workflow:
    workflow_path = Path(path).expanduser()
    raw = workflow_path.read_text(encoding="utf-8")
    if workflow_path.suffix.lower() == ".json":
        payload = json.loads(raw)
    elif workflow_path.suffix.lower() in {".yaml", ".yml"}:
        payload = _load_simple_yaml(raw)
    else:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = _load_simple_yaml(raw)
    return _workflow_from_payload(payload, default_name=workflow_path.stem)


def resolve_workflow_files(
    cwd: str | Path, workflow_path: str | Path
) -> tuple[Path, ...]:
    root = Path(cwd).resolve()
    path = Path(workflow_path).expanduser()
    if not path.is_absolute():
        path = root / path
    if not path.is_dir():
        return (path,)
    files = tuple(
        sorted(
            item
            for pattern in ("*.workflow.yaml", "*.workflow.yml", "*.workflow.json")
            for item in path.glob(pattern)
            if item.is_file()
        )
    )
    if not files:
        raise FileNotFoundError(f"No workflow files found in {path}")
    return files


def _workflow_from_payload(payload: object, *, default_name: str) -> Workflow:
    if not isinstance(payload, Mapping):
        raise ValueError("workflow file must contain an object")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, str | bytes):
        raise ValueError("workflow file must contain a steps list")
    steps = tuple(
        _step_from_payload(item, index=index)
        for index, item in enumerate(raw_steps, start=1)
    )
    if not steps:
        raise ValueError("workflow must contain at least one step")
    raw_name = payload.get("name", default_name)
    raw_backend = payload.get("backend")
    backend = str(raw_backend) if raw_backend is not None else None
    return Workflow(name=str(raw_name or default_name), steps=steps, backend=backend)


def _step_from_payload(payload: object, *, index: int) -> WorkflowStep:
    if not isinstance(payload, Mapping):
        raise ValueError(f"workflow step {index} must be an object")
    if "prompt" in payload:
        return _prompt_step_from_payload(payload, index=index)
    if "wait_for" in payload:
        return _wait_for_step_from_payload(payload, index=index)
    if "wait" in payload:
        return _wait_step_from_payload(payload, index=index)
    if "steer" in payload:
        return _text_step_from_payload(payload, key="steer", index=index)
    if "follow_up" in payload:
        return _text_step_from_payload(payload, key="follow_up", index=index)
    if "abort" in payload:
        return AbortStep()
    if "expect" in payload:
        return _expect_step_from_payload(payload, index=index)
    raise ValueError(f"workflow step {index} must contain one action")


def _prompt_step_from_payload(
    payload: Mapping[object, object], *, index: int
) -> PromptStep:
    raw_prompt = payload.get("prompt")
    if not isinstance(raw_prompt, str) or not raw_prompt.strip():
        raise ValueError(f"workflow step {index} must contain a non-empty prompt")
    expect = _expectation_from_payload(payload.get("expect", {}), index=index)
    return PromptStep(
        prompt=raw_prompt,
        timeout_s=_float_value(payload.get("timeout_s")),
        hold=bool(payload.get("hold", False)),
        expect=expect,
    )


def _wait_for_step_from_payload(
    payload: Mapping[object, object], *, index: int
) -> WaitForStep:
    raw_wait_for = _nested_action_payload(payload, "wait_for")
    if not isinstance(raw_wait_for, Mapping):
        raise ValueError(f"workflow step {index} wait_for must be an object")
    raw_event = raw_wait_for.get("event")
    if not isinstance(raw_event, str) or not raw_event.strip():
        raise ValueError(f"workflow step {index} wait_for must contain event")
    timeout_s = _float_value(raw_wait_for.get("timeout_s"))
    return WaitForStep(
        event=raw_event, timeout_s=5.0 if timeout_s is None else timeout_s
    )


def _wait_step_from_payload(
    payload: Mapping[object, object], *, index: int
) -> WaitStep:
    raw_wait = _nested_action_payload(payload, "wait")
    if isinstance(raw_wait, Mapping):
        duration_s = _float_value(raw_wait.get("duration_s", raw_wait.get("seconds")))
    else:
        duration_s = _float_value(raw_wait)
    if duration_s is None:
        raise ValueError(f"workflow step {index} wait must contain duration_s")
    if duration_s < 0:
        raise ValueError(f"workflow step {index} wait duration_s must be non-negative")
    return WaitStep(duration_s=duration_s)


def _text_step_from_payload(
    payload: Mapping[object, object], *, key: str, index: int
) -> SteerStep | FollowUpStep:
    raw_text = payload.get(key)
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError(f"workflow step {index} {key} must contain text")
    if key == "steer":
        return SteerStep(text=raw_text)
    return FollowUpStep(text=raw_text)


def _expect_step_from_payload(
    payload: Mapping[object, object], *, index: int
) -> ExpectStep:
    raw_expect = _nested_action_payload(payload, "expect")
    return ExpectStep(
        expect=_workflow_expectation_from_payload(raw_expect, index=index)
    )


def _nested_action_payload(payload: Mapping[object, object], key: str) -> object:
    raw = payload.get(key)
    if isinstance(raw, Mapping) and raw:
        return raw
    if raw is not None and raw != {}:
        return raw
    return {
        str(item_key): item_value
        for item_key, item_value in payload.items()
        if item_key != key
    }


def _expectation_from_payload(payload: object, *, index: int) -> StepExpectation:
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise ValueError(f"workflow step {index} expect must be an object")
    command_payload = payload.get("command")
    return StepExpectation(
        assistant_contains=_string_tuple(payload.get("assistant_contains")),
        assistant_contains_any=_string_tuple(payload.get("assistant_contains_any")),
        assistant_not_contains=_string_tuple(payload.get("assistant_not_contains")),
        files_exist=_string_tuple(payload.get("files_exist")),
        files_not_exist=_string_tuple(payload.get("files_not_exist")),
        files_contain=_string_mapping(payload.get("files_contain")),
        command=_command_from_payload(command_payload, index=index)
        if command_payload is not None
        else None,
        no_traceback=bool(payload.get("no_traceback", False)),
    )


def _command_from_payload(payload: object, *, index: int) -> CommandExpectation:
    if not isinstance(payload, Mapping):
        raise ValueError(f"workflow step {index} command expectation must be an object")
    raw_run = payload.get("run")
    if not isinstance(raw_run, str) or not raw_run.strip():
        raise ValueError(f"workflow step {index} command expectation must contain run")
    return CommandExpectation(
        run=raw_run,
        exit_code=_int_value(payload.get("exit_code", 0), field="exit_code"),
        stdout_contains=_string_tuple(payload.get("stdout_contains")),
        stderr_contains=_string_tuple(payload.get("stderr_contains")),
        stderr_not_contains=_string_tuple(payload.get("stderr_not_contains")),
        timeout_s=_float_value(payload.get("timeout_s")),
    )


def _workflow_expectation_from_payload(
    payload: object, *, index: int
) -> WorkflowExpectation:
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise ValueError(f"workflow step {index} expect must be an object")
    queue = _queue_expectation_from_payload(payload.get("queue"))
    return WorkflowExpectation(
        events=_event_patterns_from_payload(
            payload.get("events"), index=index, field="events"
        ),
        not_events=_event_patterns_from_payload(
            payload.get("not_events"), index=index, field="not_events"
        ),
        queue=queue,
        session_state=_state_expectation_from_payload(payload.get("session_state")),
        session_stats=_state_expectation_from_payload(payload.get("session_stats")),
        context_usage=_state_expectation_from_payload(payload.get("context_usage")),
    )


def _event_patterns_from_payload(
    payload: object, *, index: int, field: str
) -> tuple[EventPattern, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, Sequence) or isinstance(payload, str | bytes):
        raise ValueError(f"workflow step {index} {field} must be a list")
    patterns: list[EventPattern] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise ValueError(f"workflow step {index} {field} entries must be objects")
        raw_event = item.get("event")
        if not isinstance(raw_event, str) or not raw_event.strip():
            raise ValueError(
                f"workflow step {index} {field} entries must contain event"
            )
        raw_contains = item.get("contains")
        raw_data = item.get("data", {})
        if raw_data is None:
            raw_data = {}
        if not isinstance(raw_data, Mapping):
            raise ValueError(f"workflow step {index} {field} data must be an object")
        patterns.append(
            EventPattern(
                event=raw_event,
                contains=str(raw_contains) if raw_contains is not None else None,
                data={str(key): value for key, value in raw_data.items()},
            )
        )
    return tuple(patterns)


def _queue_expectation_from_payload(payload: object) -> dict[str, tuple[str, ...]]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ValueError("queue expectation must be an object")
    return {str(key): _string_tuple(value) for key, value in payload.items()}


def _state_expectation_from_payload(payload: object) -> dict[str, object]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ValueError("session_state expectation must be an object")
    return {str(key): _state_expectation_value(value) for key, value in payload.items()}


def _state_expectation_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _state_expectation_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_state_expectation_value(item) for item in value]
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return tuple(str(item) for item in value)
    return (str(value),)


def _string_mapping(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("files_contain must be an object")
    return {str(key): str(item) for key, item in value.items()}


def _int_value(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value)
    raise ValueError(f"{field} must be an integer")


def _float_value(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise ValueError("timeout_s must be a number")


def _load_simple_yaml(raw: str) -> object:
    lines = _yaml_lines(raw)
    if not lines:
        return {}
    payload, index = _parse_yaml_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ValueError(f"unexpected YAML content: {lines[index][1]}")
    return payload


def _yaml_lines(raw: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw_line in raw.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append((indent, raw_line.strip()))
    return lines


def _parse_yaml_block(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[object, int]:
    if lines[index][0] < indent:
        return {}, index
    if lines[index][1].startswith("- "):
        return _parse_yaml_list(lines, index, indent)
    return _parse_yaml_mapping(lines, index, indent)


def _parse_yaml_mapping(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[dict[str, object], int]:
    mapping: dict[str, object] = {}
    while index < len(lines):
        line_indent, text = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(f"unexpected indentation: {text}")
        if text.startswith("- "):
            break
        key, value_text = _split_yaml_key_value(text)
        index += 1
        if value_text:
            mapping[key] = _parse_yaml_scalar(value_text)
            continue
        if index < len(lines) and lines[index][0] > indent:
            mapping[key], index = _parse_yaml_block(lines, index, lines[index][0])
        else:
            mapping[key] = None
    return mapping, index


def _parse_yaml_list(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[list[object], int]:
    items: list[object] = []
    while index < len(lines):
        line_indent, text = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent or not text.startswith("- "):
            break
        item_text = text[2:].strip()
        index += 1
        if not item_text:
            if index < len(lines) and lines[index][0] > indent:
                item, index = _parse_yaml_block(lines, index, lines[index][0])
            else:
                item = None
        elif ":" in item_text and not _looks_like_quoted_scalar(item_text):
            key, value_text = _split_yaml_key_value(item_text)
            item_mapping: dict[str, object] = {
                key: _parse_yaml_scalar(value_text) if value_text else None
            }
            if index < len(lines) and lines[index][0] > indent:
                nested, index = _parse_yaml_block(lines, index, lines[index][0])
                if isinstance(nested, Mapping):
                    item_mapping.update(nested)
                else:
                    raise ValueError(
                        "list item mapping cannot contain a nested list at the same level"
                    )
            item = item_mapping
        else:
            item = _parse_yaml_scalar(item_text)
            if index < len(lines) and lines[index][0] > indent:
                raise ValueError(
                    f"scalar list item cannot contain nested content: {item_text}"
                )
        items.append(item)
    return items, index


def _split_yaml_key_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"expected key: value entry, got: {text}")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"empty YAML key: {text}")
    return key, value.strip()


def _parse_yaml_scalar(value: str) -> object:
    if value == "":
        return ""
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if value.startswith(("[", "{", "'", '"')):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _looks_like_quoted_scalar(value: str) -> bool:
    return value.startswith(("'", '"'))
