from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from loushang.agent import AbortSignal, Agent
from loushang.ai import AssistantMessage, TextPart, Usage, UserMessage
from loushang.ai.model import Capabilities, Model
from loushang.coding.control import CompactionSettings, ControlConfig, SettingsManager
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harness.transcript import summarization as summary_module
from loushang.harnesstui.conversation.agent_binding import (
    agent_session_history_records,
    build_agent_screen_conversation_projection,
)
from loushang.tui import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    ProcessTerminalPort,
    RenderLoop,
    TerminalSize,
    TuiRuntime,
)

_PRIVATE_SUMMARY = "AUTO_COMPACT_PRIVATE_SUMMARY"


def _usage(total_tokens: int) -> Usage:
    return Usage(
        input=total_tokens,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=total_tokens,
        cost={},
    )


def _assistant(text: str, *, total_tokens: int) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)] if text else [],
        api="anthropic-messages",
        provider="faux",
        model="tiny-auto-compact",
        response_id=None,
        usage=_usage(total_tokens),
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )


class _SummaryStream:
    async def result(self) -> AssistantMessage:
        return _assistant(_PRIVATE_SUMMARY, total_tokens=1)


async def _fake_summary_stream(
    model: object,
    context: object,
    options: object | None = None,
) -> _SummaryStream:
    del model, context, options
    return _SummaryStream()


def _message_text(message: object) -> str:
    content = getattr(message, "content", ())
    return "".join(part.text for part in content if isinstance(part, TextPart))


async def _emit_assistant_turn(
    *,
    session: AgentSession,
    runtime: TuiRuntime,
    lines: tuple[str, ...],
    total_tokens: int,
) -> None:
    signal = AbortSignal()
    session_runtime = session._composition.session_runtime
    await session_runtime.handle_agent_event(
        {"type": "message_start", "message": _assistant("", total_tokens=0)},
        signal,
    )
    text = ""
    for index, line in enumerate(lines):
        delta = f"{line}\n" if index < len(lines) - 1 else line
        text += delta
        await session_runtime.handle_agent_event(
            {
                "type": "message_update",
                "message": _assistant(text, total_tokens=total_tokens),
                "assistant_message_event": {
                    "type": "text_delta",
                    "delta": delta,
                },
            },
            signal,
        )
        runtime.render_now()
    assistant = _assistant(text, total_tokens=total_tokens)
    await session_runtime.handle_agent_event(
        {"type": "message_end", "message": assistant},
        signal,
    )
    runtime.render_now()
    await session_runtime.handle_agent_event(
        {"type": "agent_end", "messages": [assistant]},
        signal,
    )
    runtime.render_now()


async def _render_auto_compact_playback(
    *,
    ready_file: Path,
    evidence_file: Path,
    session_dir: Path,
) -> None:
    app = ScreenCodingTuiApp(
        model_label="faux/tiny-auto-compact",
        cwd="/repo",
        branch="main",
        session_label="pty-auto-compact",
        now=lambda: 3.0,
    )
    terminal = ProcessTerminalPort(
        output=sys.stdout,
        size_provider=lambda: TerminalSize(columns=80, rows=18),
        track_screen=False,
    )
    runtime = TuiRuntime(render_loop=RenderLoop(app), terminal=terminal)
    projector = build_agent_screen_conversation_projection(app)
    manager = await SessionManager.new(
        session_dir=session_dir,
        cwd="/repo",
        persist=True,
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": Model(
                    id="tiny-auto-compact",
                    name="Tiny Auto Compact",
                    provider="faux",
                    endpoint="anthropic-messages",
                    capabilities=Capabilities(
                        input=("text",),
                        stream=True,
                        context_window=32_768,
                        max_tokens=32,
                    ),
                ),
                "thinking_level": "off",
            }
        ),
        session_manager=manager,
        settings_manager=SettingsManager(
            ControlConfig(
                compaction=CompactionSettings(
                    enabled=True,
                    compact_percent=80,
                    reserve_tokens=10,
                    keep_recent_tokens=1,
                )
            )
        ),
    )
    events: list[dict[str, object]] = []

    def handle_event(event: dict[str, object]) -> None:
        events.append(event)
        projector.handle(event)

    unsubscribe = session.subscribe(handle_event)
    original_stream = summary_module.stream
    summary_module.stream = _fake_summary_stream
    early_lines = tuple(f"AUTO_EARLY_{index:03d}" for index in range(1, 81))
    after_lines = tuple(f"AUTO_AFTER_{index:03d}" for index in range(1, 41))
    try:
        await manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="trigger automatic compaction")],
                timestamp=0.0,
            )
        )
        app.start_prompt("trigger automatic compaction", started_at=0.0)
        runtime.render_now()
        await _emit_assistant_turn(
            session=session,
            runtime=runtime,
            lines=early_lines,
            total_tokens=31_000,
        )

        await manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="continue after auto compact")],
                timestamp=2.0,
            )
        )
        app.start_prompt("continue after auto compact", started_at=2.0)
        runtime.render_now()
        await _emit_assistant_turn(
            session=session,
            runtime=runtime,
            lines=after_lines,
            total_tokens=10,
        )
    finally:
        summary_module.stream = original_stream
        unsubscribe()

    session_file = manager.get_session_file()
    if session_file is None:
        raise AssertionError("persistent playback did not materialize a session file")
    await manager.dispose_runtime_profile()

    resumed = await SessionManager.load(session_file, persist=True)
    try:
        resumed_entries = resumed.get_entries()
        resumed_context = resumed.build_session_context()
        resumed_history = agent_session_history_records(resumed.get_branch())
        full_history = "\n".join(
            _message_text(entry.payload)
            for entry in resumed_entries
            if entry.kind == "agent.message"
        )
        context_text = "\n".join(
            _message_text(message) for message in resumed_context.messages
        )
        rendered_history_text = "\n".join(
            record.text
            for record in resumed_history
            if isinstance(record, AssistantMessageRecord)
        )
        compaction_events = [
            event
            for event in events
            if event.get("type") in {"compaction_start", "compaction_end"}
        ]
        evidence = {
            "sessionFile": str(session_file),
            "entryCount": len(resumed_entries),
            "checkpointCount": sum(
                entry.kind == "context.compaction_checkpoint"
                for entry in resumed_entries
            ),
            "compactionEventTypes": [
                str(event.get("type")) for event in compaction_events
            ],
            "compactionReasons": [
                str(event.get("reason")) for event in compaction_events
            ],
            "compactionStages": [
                str(event.get("stage")) for event in compaction_events
            ],
            "fullHistoryHasEarly": early_lines[0] in full_history
            and early_lines[-1] in full_history,
            "fullHistoryHasAfter": after_lines[0] in full_history
            and after_lines[-1] in full_history,
            "resumeContextHasSummary": _PRIVATE_SUMMARY in context_text,
            "resumeContextHasAfter": after_lines[0] in context_text
            and after_lines[-1] in context_text,
            "resumeHistoryCheckpointCount": sum(
                isinstance(record, ContextCompactionRecord)
                for record in resumed_history
            ),
            "resumeHistoryHasEarly": early_lines[0] in rendered_history_text
            and early_lines[-1] in rendered_history_text,
            "resumeHistoryHasAfter": after_lines[0] in rendered_history_text
            and after_lines[-1] in rendered_history_text,
        }
    finally:
        await resumed.dispose_runtime_profile()

    evidence_file.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ready_file.touch()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--session-dir", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(
        _render_auto_compact_playback(
            ready_file=args.ready_file,
            evidence_file=args.evidence_file,
            session_dir=args.session_dir,
        )
    )
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
