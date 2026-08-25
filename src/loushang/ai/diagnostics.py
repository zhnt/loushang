from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

NormalizationDiagnosticCode = Literal[
    "aborted_assistant_repaired",
    "empty_thinking_dropped",
    "error_assistant_dropped",
    "non_visible_assistant_dropped",
    "duplicate_tool_result",
    "late_tool_result",
    "missing_tool_result",
    "missing_tool_result_repaired",
    "orphaned_tool_result",
    "redacted_thinking_dropped",
    "text_signature_removed",
    "thinking_downgraded_to_text",
    "thinking_signature_removed",
    "tool_call_id_normalized",
    "tool_call_thought_signature_removed",
    "tool_result_name_mismatch",
    "tool_result_id_normalized",
    "unknown_tool_result",
]

_PATH_TOKEN_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


@dataclass(frozen=True)
class NormalizationDiagnostic:
    """Diagnostic emitted while normalizing AI context/messages.

    code, path, and level are the stable machine-readable contract. message is
    human-readable guidance and may change without API compatibility guarantees.
    """

    code: NormalizationDiagnosticCode
    path: str
    message: str
    level: Literal["info", "warning"] = "warning"


def sort_normalization_diagnostics(
    diagnostics: Iterable[NormalizationDiagnostic],
) -> tuple[NormalizationDiagnostic, ...]:
    return tuple(
        diagnostic
        for _index, diagnostic in sorted(
            enumerate(diagnostics),
            key=lambda item: (_path_sort_key(item[1].path), item[0]),
        )
    )


def _path_sort_key(path: str) -> tuple[tuple[int, str | int], ...]:
    parts: list[tuple[int, str | int]] = []
    for match in _PATH_TOKEN_PATTERN.finditer(path):
        name = match.group(1)
        if name is not None:
            parts.append((0, name))
            continue
        index = match.group(2)
        if index is not None:
            parts.append((1, int(index)))
    if not parts:
        return ((0, path),)
    return tuple(parts)
