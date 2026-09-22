"""Deterministic test-only long-history bytes; no runtime or filesystem IO."""

from __future__ import annotations

import hashlib
import json

RECIPE = "lmux-history-128x2048/v1"
ROUNDS = 128
REPLY_BYTES = 2048
TEXT_BYTES = 263680
OMITTED = "Earlier messages omitted from this bounded snapshot; the canonical transcript is unchanged."


def history_turn(index: int) -> tuple[str, str]:
    if type(index) is not int or not 0 <= index < ROUNDS:
        raise ValueError("invalid history round")
    title = f"{index:04d}"
    ending = (
        f"\n\n## History {title}\n\n"
        f"- completed round {title}\n\n"
        f"```text\ncode-{title}\n```\n\n"
        f"LMUX_HISTORY_{title}_END"
    )
    pattern = f"history-{title} deterministic evidence. "
    size = REPLY_BYTES - len(ending)
    body = (pattern * ((size + len(pattern) - 1) // len(pattern)))[:size]
    return "history " + title, body + ending


def history_records() -> list[list[str]]:
    return [[kind, text] for index in range(ROUNDS)
            for kind, text in zip(("user", "assistant"), history_turn(index), strict=True)]


def history_digest(records: list[list[str]]) -> str:
    """Exact canonical text projection, not a Session or file identity proof."""
    if type(records) is not list or any(
        type(row) is not list or len(row) != 2 or row[0] not in ("user", "assistant")
        or type(row[0]) is not str or type(row[1]) is not str for row in records
    ):
        raise ValueError("invalid history text records")
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_history(records: list[list[str]]) -> dict:
    if records != history_records():
        raise ValueError("history differs from fixed recipe")
    digest = history_digest(records)
    return {"recipe": RECIPE, "rounds": ROUNDS, "records": len(records),
            "text_bytes": sum(len(text.encode("utf-8")) for _, text in records), "sha256": digest}


def validate_history_window(records: list[list[str]], index: int) -> None:
    """Exact current Product tail, not proof of idle, identity or persistence.

    The 16,384-character Product budget fits seven complete 2,060-byte turns.
    The preceding assistant cannot fit, so no partial eighth turn is admitted.
    Keep this independent of the production projection to detect drift.
    """
    history_turn(index)  # Reject invalid/bool round numbers before slicing.
    first = max(0, index - 6)
    expected = [[kind, text] for turn in range(first, index + 1)
                for kind, text in zip(("user", "assistant"), history_turn(turn), strict=True)]
    if first:
        expected.insert(0, ["status", OMITTED])
    if type(records) is not list or records != expected:
        raise ValueError("history snapshot differs from expected bounded tail")
