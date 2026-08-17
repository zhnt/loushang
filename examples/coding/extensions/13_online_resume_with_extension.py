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
    create_kimi_runtime,
    describe_model,
    print_messages,
    resolve_api_key,
)

from loushang.ai import ApiKeyAuth, CallOptions
from loushang.coding import ToolRegistry, register_builtin_tools

EXTENSION_SOURCE = """
from pathlib import Path

from loushang.harness.extensions.agent import ExtensionResourceContribution
from loushang.harness.resources.types import PromptFragmentDescriptor


def register(api):
    def _resources_discover(bundle, ctx):
        source = Path(__file__).resolve()
        return ExtensionResourceContribution(
            prompt_descriptors=[
                PromptFragmentDescriptor(
                    name="online-resume-extension",
                    source_path=source,
                    text="Every final answer must begin with [resume-extension].",
                )
            ]
        )

    api.on("resources_discover", _resources_discover)
"""


def _tool_prompt(user_request: str) -> str:
    return (
        "你有一个 bash 工具。\n"
        "如果问题涉及本地 README.md 或文件内容，请先调用 bash，再回答。\n\n"
        f"用户请求：{user_request}"
    )


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-online-ext-resume-") as tmpdir:
        project_root = Path(tmpdir)
        (project_root / "README.md").write_text(
            "# Resume Extension Demo\\n\\nThis README is used to verify online resume with extension resources.\\n",
            encoding="utf-8",
        )
        extensions_dir = project_root / "extensions"
        extensions_dir.mkdir(parents=True)
        extension_file = extensions_dir / "online_resume_extension.py"
        extension_file.write_text(EXTENSION_SOURCE.strip() + "\n", encoding="utf-8")

        registry = ToolRegistry()
        register_builtin_tools(registry)
        model = build_kimi_model()
        model_info = describe_model(model)
        runtime = create_kimi_runtime(
            cwd=project_root,
            model=model,
            system_prompt="Online resume with extension example.",
            tools=registry.list_enabled_tools(),
            persist=True,
        )

        session = await runtime.create_session(cwd=str(project_root))
        session.agent.call_options = CallOptions(auth=ApiKeyAuth(resolve_api_key()))
        attach_stream_printer(session)

        print("=== Online Extension Example: Resume With Extension ===")
        print(f"Project root: {project_root}")
        print(f"Extension file: {extension_file}")
        print(f"Provider: {model_info['provider']}")
        print(f"Model: {model_info['model']}")
        print(f"API: {model_info['api']}")
        print()

        await session.prompt(_tool_prompt("请查看 README.md，并告诉我标题是什么。"))
        session_file = session.session_manager.get_session_file()
        if session_file is None:
            raise RuntimeError("Expected a persisted session file for resume example.")

        restored = await runtime.restore_session(session_file)
        restored.agent.call_options = CallOptions(auth=ApiKeyAuth(resolve_api_key()))
        attach_stream_printer(restored)
        await restored.prompt(_tool_prompt("继续摘要 README.md 的主要内容。"))

        print()
        print(f"Session file: {session_file}")
        print("Messages after restore:")
        print_messages(restored)

        await runtime.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
