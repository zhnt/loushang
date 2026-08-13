from __future__ import annotations

import asyncio

from loushang.agent import Agent
from loushang.ai.context import normalize_context
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
)
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.foundation.observability import log_context
from loushang.foundation.observability._router import (
    get_problem_store,
    reset_observability,
)
from loushang.harness.tools.workspace import create_write_tool_definition
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry


def _usage() -> Usage:
    return Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )


def _model() -> Model:
    return Model(
        id="kimi-for-coding",
        name="Kimi for Coding",
        provider="moonshot",
        endpoint="kimi-code-anthropic",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _assistant_text(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="moonshot",
        model="kimi-for-coding",
        response_id=None,
        usage=_usage(),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _assistant_tool_calls(*tool_calls: ToolCall) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=list(tool_calls),
        api="anthropic-messages",
        provider="moonshot",
        model="kimi-for-coding",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


def _stream_with_message(message: AssistantMessage) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def _feed() -> None:
        stream.push({"type": "start", "partial": message})
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})  # type: ignore[typeddict-item]

    asyncio.create_task(_feed())
    return stream


def test_agent_session_recovers_after_malformed_write_tool_call_history(
    tmp_path,
) -> None:
    reset_observability()
    prompts = [
        "你好",
        "你是谁",
        "你能干什么",
        "请生成一个计算BMI的python程序，放在tmp目录",
        "请生成一个计算BMI的html程序，放在tmp目录",
        "你好",
        "你是谁",
    ]
    html = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>BMI</title></head>
<body>
  <label>身高 <input id="height" type="number" step="0.01"></label>
  <label>体重 <input id="weight" type="number" step="0.1"></label>
  <button id="calc">计算</button>
  <output id="result"></output>
  <script>
    document.getElementById('calc').addEventListener('click', () => {
      const h = Number(document.getElementById('height').value);
      const w = Number(document.getElementById('weight').value);
      document.getElementById('result').value = (w / (h * h)).toFixed(2);
    });
  </script>
</body>
</html>
"""
    responses = [
        _assistant_text("你好，我在。"),
        _assistant_text("我是 Loushang coding agent。"),
        _assistant_text("我可以读写文件、运行命令并帮助修改代码。"),
        _assistant_tool_calls(
            ToolCall(
                type="toolCall",
                id="write-python",
                name="write",
                arguments={
                    "path": "tmp/bmi.py",
                    "content": "def bmi(height, weight):\n    return weight / (height * height)\n",
                },
            )
        ),
        _assistant_text("Python BMI 程序已生成。"),
        _assistant_tool_calls(
            ToolCall(type="toolCall", id="write-empty", name="write", arguments={}),
            ToolCall(
                type="toolCall",
                id="write-html",
                name="write",
                arguments={"path": "tmp/bmi.html", "content": html},
            ),
        ),
        _assistant_text("HTML BMI 程序已生成。"),
        _assistant_text("你好，还可以继续。"),
        _assistant_text("我是 Loushang coding agent，还在同一个会话里。"),
    ]
    provider_calls = 0

    async def stream_fn(model, context, options=None):
        nonlocal provider_calls
        del model, options
        normalize_context(context)
        provider_calls += 1
        return _stream_with_message(responses.pop(0))

    async def scenario() -> None:
        registry = WorkspaceToolRegistry()
        registry.register_tool(create_write_tool_definition())
        agent = Agent(
            stream_fn=stream_fn,
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
                "tools": [],
            },
        )
        session = AgentSession(
            agent=agent,
            session_manager=await SessionManager.new(
                session_dir=tmp_path / ".sessions", cwd=str(tmp_path), persist=False
            ),
            tool_registry=registry,
            active_tool_names=["write"],
        )

        with log_context(session_id="bmi-session", cwd=str(tmp_path), mode="scenario"):
            for prompt in prompts:
                await session.prompt(prompt)

        messages = session.get_session_context().messages
        error_results = [
            message
            for message in messages
            if isinstance(message, ToolResultMessage)
            and message.tool_call_id == "write-empty"
            and message.is_error
        ]
        assistant_texts = [
            part.text
            for message in messages
            if isinstance(message, AssistantMessage)
            for part in message.content
            if isinstance(part, TextPart)
        ]

        assert error_results
        validation_problems = [
            record
            for record in get_problem_store().all()
            if record.code == "tool_validation_failed"
        ]
        assert validation_problems
        assert validation_problems[0].source == "tool"
        assert validation_problems[0].recoverable is True
        assert validation_problems[0].details == {
            "tool_call_id": "write-empty",
            "tool_name": "write",
            "error_type": "ValueError",
        }
        assert "Validation failed" in validation_problems[0].message
        assert validation_problems[0].session_id == "bmi-session"
        assert "你好，还可以继续。" in assistant_texts
        assert "我是 Loushang coding agent，还在同一个会话里。" in assistant_texts
        assert (tmp_path / "tmp" / "bmi.py").exists()
        assert (tmp_path / "tmp" / "bmi.html").read_text(encoding="utf-8") == html

    try:
        asyncio.run(scenario())
        assert provider_calls == 9
        assert responses == []
    finally:
        reset_observability()
