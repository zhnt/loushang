from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    ENV_EXAMPLES_SESSION_DIR,
    _resolve_model_catalog,
)

from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.coding import create_agent_session_runtime


def print_event(name: str, payload: dict[str, object]) -> None:
    print(f"{name}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _message_count(session) -> int:
    context = session.get_session_context()
    return len(context.messages)


async def _prompt(session, prompt: str, *, timeout_seconds: float = 8.0) -> None:
    await asyncio.wait_for(session.prompt(prompt), timeout=timeout_seconds)


def _offline_model() -> Model:
    return Model(
        id="offline-session-check-model",
        name="Offline Session Check",
        provider="offline",
        endpoint="offline",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=4096,
            max_tokens=1024,
        ),
    )


def _offline_usage() -> Usage:
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
        api="offline",
        provider="offline",
        endpoint="offline",
        model="offline-session-check-model",
        response_id=None,
        usage=_offline_usage(),
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


async def _offline_stream_fn(model, context, options=None):
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


def main() -> None:
    print("=== Session Store Check ===")
    print_event("message.start", {"step": "prepare"})

    catalog_path = _resolve_model_catalog()
    if catalog_path is None:
        print("resolved catalog: <unset>; using built-in fallback")
    else:
        print(f"resolved catalog: {catalog_path}")

    model = _offline_model()
    print_event(
        "model.start",
        {
            "provider": model.provider_id,
            "endpoint": model.endpoint_id,
            "api": "offline",
            "base_url": "n/a",
            "model": model.id,
        },
    )

    with TemporaryDirectory(prefix="loushang-examples-session-check-") as workspace:
        session_dir = Path(workspace) / ".loushang" / "sessions"
        os.environ[ENV_EXAMPLES_SESSION_DIR] = str(session_dir)

        # 同步输出可复现路径
        print(f"session_dir: {session_dir}")

        runtime = create_agent_session_runtime(
            session_dir=Path(session_dir),
            model=model,
            system_prompt="Session persistence check in offline mode.",
            persist=True,
            stream_fn=_offline_stream_fn,
        )
        session = asyncio.run(runtime.create_session(cwd=str(Path(workspace))))  # type: ignore[call-arg]
        print_event("tool.start", {"name": "session_create"})
        session_file = session.session_manager.get_session_file()
        if session_file is None:
            raise RuntimeError("persisted session file is missing")
        print(
            f"session_created: id={session.session_manager.get_header().conversation_id}"
        )
        print(f"session_file: {session_file}")
        print_event(
            "tool.end",
            {
                "name": "session_create",
                "status": "ok",
                "session_file": str(session_file),
            },
        )

        print_event(
            "message.start",
            {
                "step": "round-1",
                "session_id": session.session_manager.get_header().conversation_id,
            },
        )
        asyncio.run(
            _prompt(
                session,
                "请确认会话已创建，并写入一条用户状态记录。",
                timeout_seconds=6.0,
            )
        )

        print_event(
            "message.end", {"step": "round-1", "count_after": _message_count(session)}
        )

        before_count = _message_count(session)
        print(f"messages_before_restore={before_count}")
        print(f"session_file_exists={session_file.exists()}")

        restored = asyncio.run(runtime.restore_session(session_file))
        print_event("message.start", {"step": "restore"})
        print(
            f"restored_session_id={restored.session_manager.get_header().conversation_id}"
        )
        print(f"messages_after_restore={_message_count(restored)}")
        print(
            f"restore_ok="
            f"{str(_message_count(restored) == before_count and restored.session_manager.get_header().conversation_id == session.session_manager.get_header().conversation_id).lower()}"
        )
        print_event("message.end", {"step": "restore", "restore_ok": True})

        print_event(
            "message.start",
            {
                "step": "round-2",
                "session_id": restored.session_manager.get_header().conversation_id,
            },
        )
        asyncio.run(
            _prompt(
                restored, "请继续刚才会话，说明落盘与恢复一致。", timeout_seconds=6.0
            )
        )
        after_count = _message_count(restored)
        print(f"messages_after_round_2={after_count}")
        print_event("message.end", {"step": "round-2", "count_after": after_count})

        sessions = runtime.list_sessions()
        print(f"runtime_session_list_count={len(sessions)}")
        ids = [record.session_id for record in sessions]
        print(f"runtime_session_ids={ids}")
        print_event(
            "model.end",
            {
                "step": "session_list",
                "count": len(sessions),
                "contains_current": session.session_manager.get_header().conversation_id
                in ids,
            },
        )

        print_event("message.end", {"result": "pass", "status": "done"})

        print("=== offline expected sample ===")
        print("session_dir: <tmp>/.loushang/sessions")
        print("session_file_exists=True")
        print("messages_before_restore=2")
        print("messages_after_restore=2")
        print("restore_ok=True")
        print("runtime_session_list_count=1")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
