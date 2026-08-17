from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def project_tool_details_for_protocol(details: object | None) -> dict[str, Any]:
    """Project Python tool details into the pi-compatible protocol shape."""
    if not isinstance(details, Mapping):
        return {}
    projected = dict(details)
    _copy_alias(projected, details, "full_output_path", "fullOutputPath")
    _copy_alias(projected, details, "first_changed_line", "firstChangedLine")
    _copy_limit_alias(
        projected, details, "match_limit_reached", "match_limit", "matchLimitReached"
    )
    _copy_limit_alias(
        projected, details, "result_limit_reached", "result_limit", "resultLimitReached"
    )
    _copy_limit_alias(
        projected, details, "entry_limit_reached", "entry_limit", "entryLimitReached"
    )
    if "linesTruncated" not in projected and "lines_truncated" in details:
        projected["linesTruncated"] = bool(details.get("lines_truncated"))
    return projected


def tool_artifact_paths_for_protocol(details: object | None) -> list[str]:
    projected = project_tool_details_for_protocol(details)
    paths: list[str] = []
    for key in ("fullOutputPath", "stdout_artifact_path", "stderr_artifact_path"):
        value = projected.get(key)
        if isinstance(value, str) and value and value not in paths:
            paths.append(value)
    return paths


def normalize_bash_result_from_protocol(
    result: Mapping[str, object],
) -> dict[str, object]:
    return {
        "output": result.get("output") or "",
        "exit_code": result.get("exit_code", result.get("exitCode")),
        "cancelled": bool(result.get("cancelled", False)),
        "truncated": bool(result.get("truncated", False)),
        "full_output_path": result.get(
            "full_output_path", result.get("fullOutputPath")
        ),
    }


def _copy_alias(
    projected: dict[str, Any],
    details: Mapping[str, object],
    snake_key: str,
    protocol_key: str,
) -> None:
    if protocol_key not in projected and snake_key in details:
        projected[protocol_key] = details.get(snake_key)


def _copy_limit_alias(
    projected: dict[str, Any],
    details: Mapping[str, object],
    reached_key: str,
    limit_key: str,
    protocol_key: str,
) -> None:
    if protocol_key in projected:
        return
    limit = _int_or_none(details.get(limit_key))
    if details.get(reached_key) and limit is not None:
        projected[protocol_key] = limit


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


__all__ = [
    "normalize_bash_result_from_protocol",
    "project_tool_details_for_protocol",
    "tool_artifact_paths_for_protocol",
]
