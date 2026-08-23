from __future__ import annotations

import json
from dataclasses import dataclass, field

from loushang.harnesstui.conversation.attachments import (
    PromptImageAttachmentOutcome,
)
from loushang.harnesstui.conversation.input import (
    ConversationAbortResult,
    ConversationClipboardResult,
    ConversationExitResult,
    ConversationFollowupResult,
    ConversationInputHandled,
    ConversationInputIgnored,
    ConversationLocalResult,
    ConversationPromptResult,
    ConversationSteerResult,
    ConversationSurfaceResult,
)
from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.testing.input_playback import (
    ConversationInputPlayback,
    ConversationInputScenario,
    default_conversation_result_payload,
)
from loushang.tui.core import (
    CURSOR_MARKER,
    RenderConstraints,
    RenderResult,
)
from loushang.tui.framework import SurfaceHost
from loushang.tui.input import InputIntent
from loushang.tui.playback import PlaybackEvent
from loushang.tui.ui_parts.composer import Composer


@dataclass(slots=True)
class _PlaybackApp:
    composer: Composer = field(default_factory=Composer)
    state: ScreenConversationState = field(default_factory=ScreenConversationState)
    active_surface: object | None = None
    surface_host: SurfaceHost | None = None

    def open_transcript_reader(self) -> bool:
        return False

    def start_prompt(self, text: str) -> None:
        self.state.start_prompt(text, started_at=1.0)
        self.composer.add_history(text)
        self.composer.clear()

    def queue_followup(self, text: str) -> None:
        self.state.queue_followup(text)

    def queue_steer(self, text: str) -> None:
        self.state.queue_steer(text)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_text(
            f"› {self.composer.value}{CURSOR_MARKER}",
            constraints=constraints,
        )


def test_input_playback_drives_router_frames_and_neutral_snapshots() -> None:
    app = _PlaybackApp()
    playback = ConversationInputPlayback(app, columns=40, rows=8)

    result = playback.run(
        (
            PlaybackEvent("render"),
            PlaybackEvent.input("hello"),
            PlaybackEvent.input("\r"),
        )
    )

    result.assert_prompt_texts("hello")
    result.assert_composer_text("")
    result.assert_all_flush_succeeded()
    result.assert_no_clear_screen()
    assert result.step_state_snapshots[1]["composer_text"] == "hello"
    assert result.step_state_snapshots[2]["running"] is True
    assert result.visible_text.startswith("›")


def test_input_scenario_is_a_product_neutral_fluent_recipe() -> None:
    playback = ConversationInputPlayback(
        _PlaybackApp(),
        is_local_command=lambda text: text == "/local",
    )

    result = (
        ConversationInputScenario(playback=playback)
        .render()
        .type_text("/local")
        .enter()
        .run()
    )

    result.assert_local_texts("/local")
    result.assert_composer_text("")


def test_default_result_payload_preserves_legacy_schema_for_every_variant() -> None:
    neutral = {
        "prompt_text": None,
        "prompt_attachment_count": 0,
        "local_text": None,
        "steer_text": None,
        "steer_attachment_count": 0,
        "followup_text": None,
        "followup_attachment_count": 0,
        "surface_intent": None,
        "abort_requested": False,
        "exit_code": None,
        "render_requested": True,
    }
    cases = (
        (ConversationInputHandled(), {}),
        (ConversationInputIgnored(), {"render_requested": False}),
        (
            ConversationPromptResult(text="prompt", attachments=(object(),)),
            {"prompt_text": "prompt", "prompt_attachment_count": 1},
        ),
        (ConversationLocalResult(text="/local"), {"local_text": "/local"}),
        (
            ConversationSteerResult(text="steer", attachments=(object(),)),
            {"steer_text": "steer", "steer_attachment_count": 1},
        ),
        (
            ConversationFollowupResult(text="later", attachments=(object(),)),
            {"followup_text": "later", "followup_attachment_count": 1},
        ),
        (
            ConversationSurfaceResult(intent=InputIntent(kind="select", text="one")),
            {"surface_intent": {"kind": "select", "text": "one"}},
        ),
        (
            ConversationClipboardResult(
                outcome=PromptImageAttachmentOutcome(kind="empty")
            ),
            {},
        ),
        (ConversationAbortResult(), {"abort_requested": True}),
        (ConversationExitResult(exit_code=7), {"exit_code": 7}),
    )

    for result, changed in cases:
        assert dict(default_conversation_result_payload(result)) == (
            neutral | changed
        )


def test_input_playback_artifact_uses_injected_snapshot_and_result_payload(
    tmp_path,
) -> None:
    app = _PlaybackApp()
    playback = ConversationInputPlayback(
        app,
        state_snapshot=lambda current: {"draft": current.composer.value},
        result_payload=lambda result: {
            "submitted": isinstance(result, ConversationPromptResult),
        },
    )
    result = playback.run((PlaybackEvent.input("question"), PlaybackEvent.input("\r")))

    artifacts = result.write_artifacts(tmp_path, basename="neutral")
    rows = [
        json.loads(line)
        for line in artifacts.trace.read_text(encoding="utf-8").splitlines()
    ]

    assert rows[0]["conversation"] == {
        "state": {"draft": "question"},
        "input_results": [{"submitted": False}],
    }
    assert rows[1]["conversation"] == {
        "state": {"draft": ""},
        "input_results": [{"submitted": True}],
    }
