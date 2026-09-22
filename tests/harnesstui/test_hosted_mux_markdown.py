from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.protocol import (
    MuxSelectorV1,
    SessionScopeV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)
from loushang.coding.ui.screen_app import ScreenCodingTuiApp, _terminal_transcript_theme
from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.conversation.screen_frame import (
    ScreenFrameCopy,
    ScreenFramePresentation,
)
from loushang.harnesstui.mux.shell import HostedMuxShellV1
from loushang.tui import RenderConstraints, TerminalRuntimeCapabilities
from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.input import InputEvent
from loushang.tui.transcript import AssistantMessageRecord, UserPromptRecord

from .test_hosted_mux_profile import FINGERPRINT, _Client

MARKDOWN = "## Result\n\nUse **bold**, `pytest` and [docs](https://example.invalid).\n\n```python\nprint('中文')\n```"


class EmbeddedView(ScreenConversationApp):
    def _create_frame_presentation(self):
        return ScreenFramePresentation(ScreenFrameCopy("Running", "Steer", "", "Follow-up", ""))


@pytest.mark.parametrize("width", [24, 80])
@pytest.mark.parametrize("streaming", [False, True])
def test_hosted_and_embedded_use_shared_markdown_view(width, streaming):
    async def scenario():
        client = _Client()
        theme = _terminal_transcript_theme()
        shell = HostedMuxShellV1(client, selector=MuxSelectorV1(name="dev"), product_id="coding",
            scopes=((SessionScopeV1.CWD, FINGERPRINT),), transcript_theme=theme)
        await shell.start()
        try:
            window = shell.state.active_window
            window.records = [TranscriptRecordV1(TranscriptRecordKindV1.USER, "prompt")]
            embedded = EmbeddedView(model_label="local", cwd="", branch=None, session_label=None,
                transcript_theme=theme)
            embedded.state.replace_transcript_window([UserPromptRecord("prompt")])
            if streaming:
                window.running = True
                window.assistant_draft = MARKDOWN
                embedded.append_assistant_chunk(MARKDOWN)
            else:
                window.records.append(TranscriptRecordV1(TranscriptRecordKindV1.ASSISTANT, MARKDOWN))
                embedded.state.records.append(AssistantMessageRecord(MARKDOWN, stable=True))
                embedded.state.records_revision += 1
            window.last_cursor += 1
            capabilities = TerminalRuntimeCapabilities(hyperlinks=False)
            embedded.terminal_capabilities = shell.screen.terminal_capabilities = capabilities
            constraints = RenderConstraints(width=width, max_height=40)
            shell.screen.render(constraints).validate(constraints)
            embedded.render(constraints).validate(constraints)
            # Both bindings feed the same retained transcript renderer. Compare
            # rendered content, not just inheritance or a non-None theme.
            hosted = shell.screen._transcript_region.render(constraints)
            local = embedded._transcript_region.render(constraints)
            assert hosted.lines == local.lines
            text = "\n".join(strip_control_sequences(line.text) for line in hosted.lines)
            assert "Result" in text and "## Result" not in text and "**bold**" not in text
            assert "中文" in text and "pytest" in text
            assert not any("\x1b]8;" in line.text for line in hosted.lines)
            assert (window.assistant_draft if streaming else window.records[-1].text) == MARKDOWN
            original_region = shell.screen._transcript_region
            shell.handle(InputEvent(kind="text", text="draft one"))
            shell.handle(InputEvent(kind="key", key="tab"))
            shell.screen.render(constraints).validate(constraints)
            shell.handle(InputEvent(kind="key", key="tab"))
            shell.screen.render(constraints).validate(constraints)
            assert shell.screen.composer.value == "draft one"
            assert shell.screen._transcript_region is original_region
        finally:
            await shell.close()
        assert [name for name, _ in client.calls] == ["attach", "detach"]

    asyncio.run(scenario())


def test_embedded_keeps_shared_default_transcript_theme():
    from loushang.harnesstui.conversation.theme import terminal_transcript_theme

    assert _terminal_transcript_theme is terminal_transcript_theme
    app = ScreenCodingTuiApp(model_label=None, cwd="", branch=None, session_label=None)
    assert app.transcript_theme.defaults == terminal_transcript_theme().defaults


@pytest.mark.parametrize("hyperlinks", [False, True])
def test_hosted_markdown_sanitizes_wire_text_and_respects_terminal_link_capability(hyperlinks):
    async def scenario():
        theme = _terminal_transcript_theme()
        theme.update_overrides({"markdown.link": {"hyperlink": True}})
        shell = HostedMuxShellV1(_Client(), selector=MuxSelectorV1(name="dev"), product_id="coding",
            scopes=((SessionScopeV1.CWD, FINGERPRINT),), transcript_theme=theme)
        await shell.start()
        try:
            payload = "## Safe\x1b[2J\n\x1b]52;c;secret\x07[docs](https://example.invalid)"
            window = shell.state.active_window
            window.records = [TranscriptRecordV1(TranscriptRecordKindV1.ASSISTANT, payload)]
            window.last_cursor += 1
            shell.screen.terminal_capabilities = TerminalRuntimeCapabilities(hyperlinks=hyperlinks)
            result = shell.screen.render(RenderConstraints(width=100, max_height=24))
            text = "\n".join(line.text for line in result.lines)
            assert "\x1b[2J" not in text and "\x1b]52;" not in text and "secret" not in text
            assert ("\x1b]8;" in text) == hyperlinks
            assert "Safe" in text and "## Safe" not in text
            assert window.records[0].text == payload
        finally:
            await shell.close()

    asyncio.run(scenario())
