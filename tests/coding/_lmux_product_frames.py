"""Current-frame witnesses for the fixed fresh-Session Product scenario.

This proves only the displayed state. Explicit post-detach authenticated
snapshot verification is still required; no native settlement is inferred.
"""

from __future__ import annotations

import re

from ._g18_native_probe import _replay_embedded_output


def _frame_lines(output: str, *, after: int) -> tuple[str, ...]:
    marker = "\x1b[?2026l"
    end = output.rfind(marker)
    if end < after:
        return ()
    return tuple(line.strip() for line in _replay_embedded_output(output[:end + len(marker)]).visible_lines)


def approval_pending_visible(output: str, *, after: int) -> bool:
    lines = _frame_lines(output, after=after)
    notice = "Approval pending: F2 details; /approve /deny"
    statuses = {
        "Hosted | FirstUse | running | " + prefix + notice
        for prefix in ("", "submit: request_pending; ")
    }
    return (
        ">" in lines and "perf | *1! | /help /detach" in lines
        and any(line in statuses for line in lines)
    )


def approval_details_visible(output: str, *, after: int) -> bool:
    lines = _frame_lines(output, after=after)
    complete_page = any(
        (match := re.fullmatch(r"1-([1-9][0-9]*)/([1-9][0-9]*) \| PgUp/PgDn \| Esc back", line))
        and int(match[1]) == int(match[2]) and int(match[1]) >= 3 for line in lines
    )
    return (
        "Approval details — Esc back, then /approve or /deny" in lines
        and "lmux_evidence tool call" in lines and "{}" in lines and complete_page
        and "perf | *1! | /help /detach" in lines
    )


def tool_reply_completed(output: str, *, after: int) -> bool:
    lines = _frame_lines(output, after=after)
    return (
        ("LMUX_TOOL_COMPLETED" in lines or "* LMUX_TOOL_COMPLETED" in lines)
        and _completed_lines(lines)
    )


def denied_tool_reply_completed(output: str, *, after: int) -> bool:
    lines = _frame_lines(output, after=after)
    expected = "Tool lmux_evidence requires approval"
    return (expected in lines or "* " + expected in lines) and _completed_lines(lines)


def _settled_statuses(state: str, acknowledgement: str) -> set[str]:
    base = f"Hosted | FirstUse | {state}"
    return {base} | {
        base + " | " + prefix + hint
        for prefix in ("", acknowledgement + ": request_acknowledged; ")
        for hint in ("cwd / user_home; /help", "cwd / user_home: /new <scope>; /help")
    }


def target_state_visible(output: str, *, running: bool, after: int = 0) -> bool:
    """Current target state for reattach/interrupt; not reply completion."""
    marker = "\x1b[?2026l"
    end = output.rfind(marker)
    if end < after:
        return False
    lines = tuple(line.strip() for line in _replay_embedded_output(output[:end + len(marker)]).visible_lines)
    state = "running" if running else "idle"
    prefix = f"Hosted | FirstUse | {state} | "
    statuses = _settled_statuses(state, "interrupt")
    if running:
        statuses.add(prefix + "running; earlier partial output is not in the v1 snapshot")
    footer = "perf | *1~ | /help /detach" if running else "perf | *1 | /help /detach"
    return ">" in lines and footer in lines and any(line in statuses for line in lines)


def _reply_lines(output: str, expected: str, *, after: int) -> tuple[str, ...]:
    if re.fullmatch(r"LMUX_REPLY_[0-9a-f]{32}", expected) is None:
        return ()
    marker = "\x1b[?2026l"
    end = output.rfind(marker)
    if end < after:
        return ()
    screen = _replay_embedded_output(output[:end + len(marker)])
    lines = tuple(line.strip() for line in screen.visible_lines)
    if expected not in lines and "* " + expected not in lines:
        return ()
    return lines


def reply_streaming(output: str, expected: str, *, after: int) -> bool:
    """Full text in the explicitly running target is not completion."""
    lines = _reply_lines(output, expected, after=after)
    statuses = {
        "Hosted | FirstUse | running | cwd / user_home; /help",
        "Hosted | FirstUse | running | cwd / user_home: /new <scope>; /help",
        "Hosted | FirstUse | running | submit: request_acknowledged; cwd / user_home; /help",
        "Hosted | FirstUse | running | submit: request_pending; cwd / user_home; /help",
    }
    return (
        ">" in lines and "perf | *1~ | /help /detach" in lines
        and any(line in statuses for line in lines)
    )


def reply_completed(output: str, expected: str, *, after: int) -> bool:
    lines = _reply_lines(output, expected, after=after)
    return _completed_lines(lines)


def _completed_lines(lines: tuple[str, ...]) -> bool:
    statuses = _settled_statuses("idle", "submit")
    return (
        ">" in lines and "perf | *1 | /help /detach" in lines
        and any(line in statuses for line in lines)
    )


def assert_no_completed_reply(output: str, expected: str, *, before_send: str) -> None:
    """After PTY settlement, inspect every retained complete post-input frame."""
    assert output.startswith(before_send), "terminal output window was truncated"
    marker = "\x1b[?2026l"
    offset = len(before_send)
    start = offset
    while (end := output.find(marker, start)) >= 0:
        end += len(marker)
        assert not reply_completed(output[:end], expected, after=offset), "blocked final reported complete"
        start = end
