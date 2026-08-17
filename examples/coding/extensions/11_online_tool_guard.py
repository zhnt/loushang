from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    attach_stream_printer,
    build_kimi_model,
    create_kimi_runtime_session,
    describe_model,
    latest_tool_results,
)

from loushang.coding import ToolRegistry, register_builtin_tools

EXTENSION_SOURCE = """
from loushang.agent.types import AgentToolResult
from loushang.ai.types import TextPart
from loushang.harness.extensions.agent import ToolCallDecision, ToolResultDecision


def register(api):
    def _tool_call(event, ctx):
        if event.tool_call.name != "bash":
            return None
        command = list(event.args.get("command", []))
        if command == ["ls", "-1"]:
            return ToolCallDecision(arguments={"command": ["ls", "-la"]})
        if command[:2] == ["git", "push"]:
            return ToolCallDecision(block=True, reason="online extension blocked git push")
        return None

    def _tool_result(event, ctx):
        if event.tool_call.name != "bash":
            return None
        text = "".join(part.text for part in event.result.content if getattr(part, "type", None) == "text")
        return ToolResultDecision(
            result=AgentToolResult(
                content=[TextPart(type="text", text=f"[guarded bash result]\\n{text}")],
                details=event.result.details,
            )
        )

    api.on("tool_call", _tool_call)
    api.on("tool_result", _tool_result)
"""


def _tool_prompt() -> str:
    return (
        "你有一个 bash 工具。\n"
        "请先调用 bash，执行 `ls -1` 查看当前目录，然后用一句话概括你看到了什么。"
    )


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-online-ext-guard-") as tmpdir:
        project_root = Path(tmpdir)
        (project_root / "README.md").write_text("# Online Extension Tool Guard\\n", encoding="utf-8")
        extensions_dir = project_root / "extensions"
        extensions_dir.mkdir(parents=True)
        extension_file = extensions_dir / "online_tool_guard.py"
        extension_file.write_text(EXTENSION_SOURCE.strip() + "\n", encoding="utf-8")

        registry = ToolRegistry()
        register_builtin_tools(registry)
        model = build_kimi_model()
        model_info = describe_model(model)
        runtime, session = await create_kimi_runtime_session(
            cwd=project_root,
            model=model,
            system_prompt="Online extension tool interception example.",
            tools=registry.list_enabled_tools(),
            persist=False,
        )
        attach_stream_printer(session)

        print("=== Online Extension Example: Tool Guard ===")
        print(f"Project root: {project_root}")
        print(f"Extension file: {extension_file}")
        print(f"Provider: {model_info['provider']}")
        print(f"Model: {model_info['model']}")
        print(f"API: {model_info['api']}")
        print("Tools: bash")
        print()

        try:
            await session.prompt(_tool_prompt())
        finally:
            await runtime.dispose()

        tool_results = latest_tool_results(session)
        print()
        if tool_results:
            latest = tool_results[-1]
            print("Latest tool result:")
            print(f"- tool_name: {latest.tool_name}")
            print(f"- text:\n{latest.content[0].text}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
