"""CLI serialization of the transport-neutral current Plugin preview port."""

from __future__ import annotations

import json

from loushang.harness.plugin_management.current_preview import (
    PluginCurrentPreviewQueryPort,
    PluginCurrentPreviewRequestV1,
    project_plugin_current_preview,
)


def format_plugin_current_preview(
    query: PluginCurrentPreviewQueryPort,
    request: PluginCurrentPreviewRequestV1,
) -> str:
    return json.dumps(
        project_plugin_current_preview(query, request),
        ensure_ascii=False,
        sort_keys=True,
    ) + "\n"


__all__ = ["format_plugin_current_preview"]
