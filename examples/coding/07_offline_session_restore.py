from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
while not (REPO_ROOT / "src").exists() and REPO_ROOT.parent != REPO_ROOT:
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.coding import create_agent_session_runtime


def _model() -> Model:
    return Model(
        id="offline-demo-model",
        name="Offline Demo",
        provider="offline",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost=None,
    )


def _assistant_text_message(text: str) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="offline",
        endpoint="offline",
        model="offline-demo-model",
        response_id=None,
        usage=_usage(),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _stream_with_final_message(
    message: AssistantMessage,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def _feed() -> None:
        stream.push({"type": "start", "partial": message})
        stream.push({"type": "text_start", "content_index": 0, "partial": message})
        stream.push(
            {
                "type": "text_delta",
                "content_index": 0,
                "delta": message.content[0].text,
                "partial": message,
            }
        )
        stream.push(
            {
                "type": "text_end",
                "content_index": 0,
                "content": message.content[0].text,
                "partial": message,
            }
        )
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})  # type: ignore[typeddict-item]

    asyncio.create_task(_feed())
    return stream


async def _stream_fn(model, context, options=None):
    del model, options
    last_message = context.messages[-1] if context.messages else None
    if isinstance(last_message, UserMessage):
        user_text = " ".join(
            part.text
            for part in last_message.content
            if getattr(part, "type", None) == "text"
        )
    else:
        user_text = "unknown"
    return _stream_with_final_message(
        _assistant_text_message(f"Offline assistant reply to: {user_text}")
    )


def _print_messages(session) -> None:
    for index, message in enumerate(session.get_session_context().messages, start=1):
        role = getattr(message, "role", "unknown")
        content = getattr(message, "content", [])
        text = " ".join(
            part.text for part in content if getattr(part, "type", None) == "text"
        )
        print(f"{index}. {role}: {text}")


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-session-restore-") as session_dir:
        runtime = create_agent_session_runtime(
            session_dir=Path(session_dir),
            model=_model(),
            stream_fn=_stream_fn,
            system_prompt="Offline session restore demo.",
            persist=True,
        )

        session = await runtime.create_session(cwd=str(Path.cwd()))
        await session.prompt("第一轮：请记录这是一个离线 session restore 示例。")

        session_file = session.session_manager.get_session_file()
        if session_file is None:
            raise RuntimeError("Expected a persisted session file")

        print("=== Offline Session Restore Roundtrip ===")
        print(f"Session dir: {session_dir}")
        print(f"Session file: {session_file}")
        print(f"Session id: {session.session_manager.get_header().conversation_id}")
        print()
        print("Messages after first prompt:")
        _print_messages(session)
        print()

        restored = await runtime.restore_session(session_file)
        print("Messages immediately after restore:")
        _print_messages(restored)
        print()

        await restored.prompt(
            "第二轮：请继续这个已经恢复的会话，并确认你看到了前一轮消息。"
        )
        print("Messages after continuing restored session:")
        _print_messages(restored)
        print()
        print(f"Known sessions in runtime: {len(runtime.list_sessions())}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
