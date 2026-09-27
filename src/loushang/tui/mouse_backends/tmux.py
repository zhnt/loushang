"""Read the containing tmux pane's current mouse setting without changing it."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping

from loushang.tui.mouse_policy import TmuxMouseState


def probe(env: Mapping[str, str]) -> TmuxMouseState:
    args = ["tmux", "display-message", "-p"]
    pane = env.get("TMUX_PANE")
    if pane:
        args.extend(("-t", pane))
    args.append("#{mouse}")
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=0.2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    value = result.stdout.strip().lower()
    return {"on": "on", "1": "on", "off": "off", "0": "off"}.get(value, "unknown")


__all__ = ["probe"]
