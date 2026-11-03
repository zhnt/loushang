"""Transport-only JSON formatting for partial Plugin operation evidence."""

from __future__ import annotations

import json


def format_plugin_operation_explanation(
    document: dict[str, object],
) -> str:
    return json.dumps(
        document, ensure_ascii=False, sort_keys=True
    ) + "\n"


__all__ = ["format_plugin_operation_explanation"]
