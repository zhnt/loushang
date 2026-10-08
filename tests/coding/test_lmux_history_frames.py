"""Shared renderer and current viewport checks for the fixed history ending."""

import asyncio

import pytest

from loushang.appserver.protocol import (
    MuxSelectorV1,
    SessionScopeV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)
from loushang.harnesstui.conversation.theme import terminal_transcript_theme
from loushang.harnesstui.mux.shell import HostedMuxShellV1
from loushang.tui import RenderConstraints
from loushang.tui.cell_width import strip_control_sequences
from tests.harnesstui.test_hosted_mux_profile import FINGERPRINT, _Client

from ._lmux_history_frames import history_content_visible
from ._lmux_history_recipe import history_records


def test_long_history_ending_is_visible_with_real_shared_renderer():
    async def run():
        shell = HostedMuxShellV1(_Client(), selector=MuxSelectorV1(name="dev"), product_id="coding",
            scopes=((SessionScopeV1.CWD, FINGERPRINT),), transcript_theme=terminal_transcript_theme())
        await shell.start()
        try:
            window = shell.state.active_window
            window.records = [TranscriptRecordV1(TranscriptRecordKindV1(kind), text)
                              for kind, text in history_records()[-14:]]
            window.last_cursor += 1
            constraints = RenderConstraints(width=100, max_height=30)
            frame = shell.screen.render(constraints)
            frame.validate(constraints)
            lines = tuple(strip_control_sequences(line.text) for line in frame.lines)
            normalized = tuple(line.strip() for line in lines)
            start = normalized.index("History 0127")
            assert normalized[start:start + 9] == (
                "History 0127", "", "- completed round 0127", "", "```text",
                "code-0127", "```", "", "LMUX_HISTORY_0127_END",
            )
            assert history_content_visible(lines), "\n".join(lines)
        finally:
            await shell.close()
    asyncio.run(run())


@pytest.mark.parametrize("fault", [None, "raw-markdown", "missing-header", "reordered", "tail-only", "duplicate",
                                  "bare-list", "wrong-bullet", "missing-fence", "wrong-language", "inline-code",
                                  "prose-header", "prose-list", "prose-code", "prose-tail"])
def test_marker_alone_or_wrong_markdown_cannot_pass(fault):
    lines = ["History 0127", "", "- completed round 0127", "", "```text",
             "code-0127", "```", "", "LMUX_HISTORY_0127_END"]
    if fault == "raw-markdown":
        lines[0] = "## History 0127"
    elif fault == "missing-header":
        lines.pop(0)
    elif fault == "reordered":
        lines[0], lines[1] = lines[1], lines[0]
    elif fault == "tail-only":
        lines = lines[-1:]
    elif fault == "duplicate":
        lines.append(lines[-1])
    elif fault == "bare-list":
        lines[2] = "completed round 0127"
    elif fault == "wrong-bullet":
        lines[2] = "• completed round 0127"
    elif fault == "missing-fence":
        lines.pop(6)
    elif fault == "wrong-language":
        lines[4] = "```python"
    elif fault == "inline-code":
        lines[4:7] = ["code-0127"]
    elif fault is not None and fault.startswith("prose-"):
        index = {"prose-header": 0, "prose-list": 2, "prose-code": 5, "prose-tail": 8}[fault]
        lines[index] = "unrelated " + lines[index] + " prose"
    assert history_content_visible(lines) is (fault is None)
