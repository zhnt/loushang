"""Current-frame history witness; never a replacement for canonical evidence."""

from ._lmux_product_frames import _frame_lines, target_state_visible


def history_content_visible(lines) -> bool:
    lines = tuple(line.strip() for line in lines)
    # The shared terminal theme retains code fences; headings lose Markdown
    # prefixes. Do not require a different rendering style from this observer.
    if any("## History 0127" in line for line in lines):
        return False
    markers = ("History 0127", "completed round 0127", "code-0127", "LMUX_HISTORY_0127_END")
    positions = []
    for marker in markers:
        found = [index for index, line in enumerate(lines) if marker in line]
        if len(found) != 1:
            return False
        positions.append(found[0])
    expected = (
        "History 0127", "", "- completed round 0127", "", "```text",
        "code-0127", "```", "", "LMUX_HISTORY_0127_END",
    )
    # Pin the actual terminal theme, not an imagined bullet or code border.
    # Exact lines also reject markers embedded in unrelated prose.
    return lines[positions[0]:positions[-1] + 1] == expected


def history_frame_visible(output: str, *, after: int = 0) -> bool:
    return (history_content_visible(_frame_lines(output, after=after))
            and target_state_visible(output, running=False, after=after))
