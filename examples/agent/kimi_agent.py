"""loushang-agent example with Moonshot Kimi model.

Demonstrates:
- Basic conversation with kimi-k2.6
- Streaming events for typewriter effect
- Simple tool execution (calculator)
- Chinese interaction

Requirements:
    export MOONSHOT_API_KEY="your-api-key"
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, replace
from typing import Any

from loushang.agent import (
    Agent,
    AgentState,
    AgentToolResult,
)
from loushang.ai import (
    ApiKeyAuth,
    CallOptions,
    Model,
    TextPart,
    get_model,
)

BASE_URL = "https://api.moonshot.cn/v1"
MODEL_ID = "kimi-k2.6"


@dataclass
class CalcTool:
    """Simple calculator tool for demonstration."""

    name: str = "calculate"
    description: str = "Perform basic arithmetic calculations"
    parameters: dict[str, Any] = None
    label: str = "Calculator"
    prepare_arguments: None = None

    def __post_init__(self) -> None:
        if self.parameters is None:
            self.parameters = {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate, e.g., '23 * 45' or '1 + 1'",
                    }
                },
                "required": ["expression"],
            }

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: object | None = None,
        on_update: Any = None,
    ) -> AgentToolResult[dict[str, Any]]:
        expression = params.get("expression", "")
        try:
            # Safe eval for basic arithmetic
            result = eval(expression, {"__builtins__": {}}, {})
            return AgentToolResult(
                content=[TextPart(type="text", text=str(result))],
                details={"expression": expression, "result": result},
            )
        except Exception as e:
            return AgentToolResult(
                content=[TextPart(type="text", text=f"Error: {e}")],
                details={"error": str(e)},
            )


def _resolve_api_key() -> str:
    api_key = os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError("请先导出 KIMI_API_KEY 或 MOONSHOT_API_KEY 环境变量")
    return api_key


def _build_model() -> Model:
    """Build public Model for Kimi via Moonshot OpenAI-compatible API."""
    return replace(
        get_model("moonshot", "openai-completions", MODEL_ID),
        base_url=BASE_URL,
    )


async def main() -> None:
    model = _build_model()

    # Explicit request auth is an AI SDK concern; the agent only forwards options.
    agent = Agent(
        initial_state=AgentState(
            system_prompt=(
                "你是 Kimi，由 Moonshot AI 提供的人工智能助手。"
                "你更擅长中文和英文的对话，会为用户提供安全、有帮助、准确的回答。"
            ),
            model=model,
            thinking_level="off",
            tools=[CalcTool()],
        ),
        call_options=CallOptions(auth=ApiKeyAuth(_resolve_api_key())),
    )

    # Subscribe to events for streaming output
    def on_event(event: dict, signal: object) -> None:
        event_type = event.get("type")
        if event_type == "message_update":
            assistant_event = event.get("assistant_message_event", {})
            if assistant_event.get("type") == "text_delta":
                delta = assistant_event.get("delta", "")
                print(delta, end="", flush=True)
        elif event_type == "message_end":
            print()  # New line after message completes
        elif event_type == "tool_execution_start":
            print(f"\n[使用工具: {event.get('tool_name')}({event.get('args')})]")
        elif event_type == "tool_execution_end":
            result = event.get("result")
            if result and hasattr(result, "content"):
                content_text = "".join(
                    p.text for p in result.content if getattr(p, "type", None) == "text"
                )
                print(f"[工具结果: {content_text}]")

    agent.subscribe(on_event)

    print("=== Kimi Agent Demo ===")
    print(f"Model: {MODEL_ID}")
    print("Type 'quit' to exit\n")

    # Demo 1: Simple greeting
    print("User: 你好，1+1等于多少？")
    print("Kimi: ", end="", flush=True)
    await agent.prompt("你好，1+1等于多少？")
    print()

    # Demo 2: Tool usage
    print("\nUser: 请用计算器工具计算 23 * 45")
    print("Kimi: ", end="", flush=True)
    await agent.prompt("请用计算器工具计算 23 * 45")
    print()

    # Demo 3: Interactive mode (only in TTY)
    if sys.stdin.isatty():
        print("\n=== 交互模式 ===")
        while True:
            try:
                user_input = input("\nUser: ").strip()
                if user_input.lower() in ("quit", "exit", "q"):
                    break
                if not user_input:
                    continue

                print("Kimi: ", end="", flush=True)
                await agent.prompt(user_input)
                print()

            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"\nError: {e}")
    else:
        print("\n=== 非交互模式，跳过交互演示 ===")

    print("\n=== 对话结束 ===")
    print(f"Total messages: {len(agent.messages)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
