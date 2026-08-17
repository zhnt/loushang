"""Shared Work event-log inspection for product command hosts."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import TextIO

from loushang.harnesswork.event_log import JsonlEventLogBackend
from loushang.harnesswork.plan_projection import project_work_plan_runs


class WorkLogInspectionError(RuntimeError):
    """Raised when a Work event log cannot be read or projected."""


def inspect_work_log(
    raw_path: str | Path,
    *,
    project_root: Path,
    run_id: str | None = None,
    output_format: str = "text",
    limit: int = 20,
) -> str:
    """Read and format a Work event log without Product-specific imports."""

    try:
        event_log = JsonlEventLogBackend(resolve_work_log_path(raw_path, project_root))
        entries = event_log.query(run_id=run_id)
        if output_format == "json":
            return (
                json.dumps(
                    [_work_log_entry_summary(entry) for entry in entries[-limit:]],
                    ensure_ascii=False,
                )
                + "\n"
            )
        if output_format == "plans-json":
            return (
                json.dumps(
                    [asdict(plan) for plan in project_work_plan_runs(entries)],
                    ensure_ascii=False,
                )
                + "\n"
            )
        if output_format == "plans":
            return _work_log_plan_summary(entries)
        return _work_log_text(entries[-limit:])
    except WorkLogInspectionError:
        raise
    except Exception as error:
        raise WorkLogInspectionError(str(error)) from error


def run_work_log_inspection_operation(
    *,
    path: str | None,
    project_root: Path,
    run_id: str | None,
    output_format: str,
    limit: int,
    stdout: TextIO,
    stderr: TextIO,
    format_error: Callable[[BaseException], str] = str,
) -> int | None:
    """Run the shared Work log inspection CLI operation."""

    if path is None:
        return None
    try:
        output = inspect_work_log(
            path,
            project_root=project_root,
            run_id=run_id,
            output_format=output_format,
            limit=limit,
        )
    except WorkLogInspectionError as error:
        stderr.write(f"Error: {format_error(error)}\n")
        return 1
    stdout.write(output)
    return 0


def resolve_work_log_path(raw_path: str | Path, project_root: Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else project_root / path


def create_work_event_log(
    raw_path: str | Path | None,
    project_root: Path,
) -> JsonlEventLogBackend | None:
    """Create the standard JSONL Work event log for an optional CLI path."""

    if raw_path is None:
        return None
    return JsonlEventLogBackend(resolve_work_log_path(raw_path, project_root))


def _work_log_text(entries: list[object]) -> str:
    lines = [
        "\t".join(
            [
                "sequence",
                "kind",
                "run_id",
                "session_id",
                "delivery_hint",
                "method_id",
                "plan_id",
                "step_id",
                "step_index",
                "step_title",
            ]
        )
    ]
    for entry in entries:
        step_index = _work_log_entry_step_index(entry)
        lines.append(
            "\t".join(
                [
                    str(entry.sequence),
                    _work_log_entry_kind(entry),
                    entry.run_id,
                    entry.session_id,
                    _work_log_entry_delivery_hint(entry),
                    _work_log_entry_method_id(entry),
                    _work_log_entry_plan_id(entry),
                    _work_log_entry_step_id(entry),
                    "" if step_index is None else str(step_index),
                    _work_log_entry_step_title(entry),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _work_log_plan_summary(entries: list[object]) -> str:
    lines = [
        "\t".join(
            [
                "type",
                "index",
                "id",
                "status",
                "run_id",
                "method_id",
                "completed_steps",
                "failed_steps",
                "current_step",
                "title",
                "deviation",
            ]
        )
    ]
    for plan in project_work_plan_runs(entries):
        lines.append(
            "\t".join(
                [
                    "plan",
                    "",
                    plan.plan_id,
                    plan.status,
                    "",
                    plan.method_id or "",
                    f"{plan.completed_step_count}/{plan.step_count}",
                    str(plan.failed_step_count),
                    plan.current_step_id or "",
                    "",
                    "",
                ]
            )
        )
        for fallback_index, step in enumerate(plan.steps, start=1):
            lines.append(
                "\t".join(
                    [
                        "step",
                        _work_log_plan_step_index(step.metadata, fallback_index),
                        step.step_id,
                        step.status,
                        step.run_id,
                        step.method_id or plan.method_id or "",
                        "",
                        "",
                        "",
                        step.title or "",
                        _work_log_plan_step_deviation_summary(step.deviation),
                    ]
                )
            )
    return "\n".join(lines) + "\n"


def _work_log_plan_step_index(metadata: Mapping[str, object], fallback_index: int) -> str:
    step_index = metadata.get("step_index")
    if isinstance(step_index, int) and not isinstance(step_index, bool):
        return str(step_index + 1)
    return str(fallback_index)


def _work_log_plan_step_deviation_summary(deviation: object) -> str:
    if deviation is None:
        return ""
    deviation_type = getattr(deviation, "deviation_type", "")
    reason = getattr(deviation, "reason", "")
    if deviation_type and reason:
        return f"{deviation_type}: {reason}"
    return str(deviation_type or reason or "")


def _work_log_entry_summary(entry: object) -> dict[str, object]:
    summary: dict[str, object] = {
        "entry_id": entry.entry_id,
        "entry_type": entry.entry_type,
        "sequence": entry.sequence,
        "kind": _work_log_entry_kind(entry),
        "run_id": entry.run_id,
        "session_id": entry.session_id,
        "operation_id": entry.operation_id,
        "event_id": entry.event_id,
        "delivery_hint": _work_log_entry_delivery_hint(entry),
    }
    for field, getter in (
        ("method_id", _work_log_entry_method_id),
        ("plan_id", _work_log_entry_plan_id),
        ("step_id", _work_log_entry_step_id),
    ):
        value = getter(entry)
        if value:
            summary[field] = value
    step_index = _work_log_entry_step_index(entry)
    if step_index is not None:
        summary["step_index"] = step_index
    step_title = _work_log_entry_step_title(entry)
    if step_title:
        summary["step_title"] = step_title
    for key in (
        "tool_call_id",
        "tool_name",
        "action_id",
        "policy_disposition",
        "policy_code",
        "policy_reason",
        "approval_required",
        "approval_decision",
        "approval_reason",
        "argument_keys",
        "path",
        "file_path",
        "command",
    ):
        value = _work_log_entry_payload_value(entry, key)
        if isinstance(value, str | bool | int | float | list | tuple):
            summary[key] = value
    return summary


def _work_log_entry_kind(entry: object) -> str:
    kind = entry.payload.get("kind")
    return kind if isinstance(kind, str) and kind else str(entry.entry_type)


def _work_log_entry_delivery_hint(entry: object) -> str:
    value = entry.payload.get("delivery_hint")
    return value if isinstance(value, str) else ""


def _work_log_entry_method_id(entry: object) -> str:
    return _work_log_entry_string_payload_value(entry, "method_id")


def _work_log_entry_plan_id(entry: object) -> str:
    return _work_log_entry_string_payload_value(entry, "plan_id")


def _work_log_entry_step_id(entry: object) -> str:
    return _work_log_entry_string_payload_value(entry, "step_id")


def _work_log_entry_step_title(entry: object) -> str:
    return _work_log_entry_string_payload_value(entry, "step_title")


def _work_log_entry_step_index(entry: object) -> int | None:
    value = _work_log_entry_payload_value(entry, "step_index")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _work_log_entry_string_payload_value(entry: object, key: str) -> str:
    value = _work_log_entry_payload_value(entry, key)
    return value if isinstance(value, str) else ""


def _work_log_entry_payload_value(entry: object, key: str) -> object | None:
    value = entry.payload.get(key)
    if value is not None:
        return value
    nested_payload = entry.payload.get("payload")
    return nested_payload.get(key) if isinstance(nested_payload, dict) else None


__all__ = [
    "WorkLogInspectionError",
    "inspect_work_log",
    "create_work_event_log",
    "run_work_log_inspection_operation",
    "resolve_work_log_path",
]
