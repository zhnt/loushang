from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    assistant_text_message,
    assistant_tool_call_message,
    build_runtime,
    latest_tool_results,
    print_messages,
    stream_with_final_message,
)

EXTENSION_SOURCE = """
from loushang.harness.tools.core import tool


@tool(label="Echo Extension")
async def echo_extension(message: str) -> str:
    '''Echo a message from an extension-registered tool.'''
    return f"echo-extension: {message}"


def register(api):
    api.register_tool(echo_extension)
"""


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-ext-tool-") as tmpdir:
        project_root = Path(tmpdir)
        extensions_dir = project_root / "extensions"
        extensions_dir.mkdir(parents=True)
        extension_file = extensions_dir / "custom_tool.py"
        extension_file.write_text(EXTENSION_SOURCE.strip() + "\n", encoding="utf-8")

        async def stream_fn(model, context, options=None):
            has_tool_result = any(getattr(message, "role", None) == "toolResult" for message in context.messages)
            if has_tool_result:
                return stream_with_final_message(assistant_text_message("The extension tool call finished."))
            return stream_with_final_message(
                assistant_tool_call_message("echo_extension", {"message": "hello from the extension tool"})
            )

        runtime = build_runtime(
            session_dir=project_root / ".loushang-sessions",
            stream_fn=stream_fn,
            system_prompt="Custom tool extension example.",
        )
        session = await runtime.create_session(cwd=str(project_root))

        print("=== Extension Example: Custom Tool ===")
        print(f"Project root: {project_root}")
        print(f"Extension file: {extension_file}")
        print(f"Active tools: {', '.join(session.get_active_tool_names())}")
        print()

        await session.prompt("Call the custom extension tool.")

        print("Messages:")
        print_messages(session)
        print()

        tool_results = latest_tool_results(session)
        if tool_results:
            print("Latest tool result:")
            print(f"- tool_name: {tool_results[-1].tool_name}")
            print(f"- text: {tool_results[-1].content[0].text}")
            print(f"- details: {tool_results[-1].details}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
