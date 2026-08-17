from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from pprint import pprint
from tempfile import TemporaryDirectory

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import assistant_text_message, build_runtime, stream_with_final_message

EXTENSION_SOURCE = """
from loushang.harness.tools.core import tool


@tool(label="Manifest Echo")
async def manifest_echo(message: str) -> str:
    '''Echo a message from a manifest-backed extension tool.'''
    return f"manifest-echo: {message}"


def register(api):
    api.register_tool(manifest_echo)
"""

MANIFEST_SOURCE = """
[extension]
id = "examples.manifest-visibility"
name = "Manifest Visibility"
version = "0.1.0"
description = "Demonstrates /extensions visibility."

[permissions]
level = "safe"

[[tools]]
name = "manifest_echo"
description = "Echo a message from a manifest-backed extension tool."
"""


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-ext-manifest-") as tmpdir:
        project_root = Path(tmpdir)
        extension_dir = project_root / "extensions" / "manifest_visibility"
        extension_dir.mkdir(parents=True)
        extension_file = extension_dir / "extension.py"
        manifest_file = extension_dir / "loushang-extension.toml"
        extension_file.write_text(EXTENSION_SOURCE.strip() + "\n", encoding="utf-8")
        manifest_file.write_text(MANIFEST_SOURCE.strip() + "\n", encoding="utf-8")

        async def stream_fn(model, context, options=None):
            return stream_with_final_message(assistant_text_message("Manifest visibility example ready."))

        runtime = build_runtime(
            session_dir=project_root / ".loushang-sessions",
            stream_fn=stream_fn,
            system_prompt="Manifest visibility extension example.",
        )
        session = await runtime.create_session(cwd=str(project_root))

        print("=== Extension Example: Manifest Visibility ===")
        print(f"Project root: {project_root}")
        print(f"Extension file: {extension_file}")
        print(f"Manifest file: {manifest_file}")
        print()

        extensions_result = await session.execute_command_async("/extensions", "")
        tools_result = await session.execute_command_async("/tools", "")

        print("/extensions result:")
        pprint(extensions_result.result if extensions_result is not None else None)
        print()

        print("/tools extension entry:")
        tools_payload = tools_result.result if tools_result is not None else {}
        available_tools = tools_payload.get("available_tools", []) if isinstance(tools_payload, dict) else []
        pprint([tool for tool in available_tools if tool.get("name") == "manifest_echo"])

        await session.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
