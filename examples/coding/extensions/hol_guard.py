from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping

from loushang.harness.extensions.agent import ToolCallDecision

_GUARDED_TOOLS = {"shell"}
_TIMEOUT_SECONDS = 10.0


def _block(reason: str) -> ToolCallDecision:
    return ToolCallDecision(block=True, reason=reason)


def _guard_decision(command: str) -> ToolCallDecision | None:
    try:
        completed = subprocess.run(
            ["hol-guard", "command", "test", command, "--json"],
            capture_output=True,
            check=False,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _block("HOL Guard command inspection failed")

    if completed.returncode != 0:
        return _block("HOL Guard command inspection failed")

    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return _block("HOL Guard returned malformed JSON")

    if not isinstance(payload, Mapping):
        return _block("HOL Guard returned an unexpected response")

    classification = payload.get("classification")
    if not isinstance(classification, Mapping):
        return _block("HOL Guard returned an unexpected classification")

    if (
        payload.get("minimum_action") == "allow"
        and classification.get("explicitly_benign") is True
    ):
        return None

    return _block("HOL Guard did not explicitly allow this command")


def register(api) -> None:
    def before_tool_call(event, ctx):
        del ctx
        if event.tool_call.name not in _GUARDED_TOOLS:
            return None

        command = event.args.get("command")
        if not isinstance(command, str) or not command.strip():
            return _block("HOL Guard requires a non-empty command")

        return _guard_decision(command)

    api.on("tool_call", before_tool_call)
