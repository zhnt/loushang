from __future__ import annotations

import random

from loushang.harness.tools.workspace.output_preview import (
    drop_tool_timing_tail_line,
)


def test_drop_tool_timing_tail_line_matches_full_splitlines_oracle() -> None:
    def original(output: str) -> str:
        lines = output.splitlines()
        if not lines or not (
            len(parts := lines[-1].strip().split()) == 2
            and parts[0] in {"Took", "Elapsed"}
            and _is_duration(parts[1])
        ):
            return output
        return "\n".join(lines[:-1])

    rng = random.Random(798)
    fragments = ("hello", "Took 1.2s", "Elapsed 4ms", "Took nope", "", "  ")
    separators = ("\n", "\r", "\r\n", "\v", "\f", "\x85", "\u2028", "\u2029")
    cases = [
        "ok\n" * 100_000,
        "ok\r\n" * 100_000 + "Took 1s\r\n",
        "x" * 2048 + "\nTook 2s",
        "x" * 2048,
    ]
    for _ in range(300):
        cases.append(
            "".join(
                rng.choice(fragments) + rng.choice(separators)
                for _ in range(rng.randrange(8))
            ) + rng.choice(fragments)
        )
    for output in cases:
        assert drop_tool_timing_tail_line(output) == original(output)


def _is_duration(value: str) -> bool:
    if value.endswith("ms"):
        value = value[:-2]
    elif value.endswith(("s", "m", "h")):
        value = value[:-1]
    try:
        float(value)
    except ValueError:
        return False
    return bool(value)
