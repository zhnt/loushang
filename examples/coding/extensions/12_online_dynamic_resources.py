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
)

from loushang.coding import ToolRegistry, register_builtin_tools

EXTENSION_SOURCE = """
from pathlib import Path

from loushang.harness.extensions.agent import ExtensionResourceContribution
from loushang.harness.resources.types import PromptFragmentDescriptor, SkillDescriptor


def register(api):
    def _resources_discover(bundle, ctx):
        source = Path(__file__).resolve()
        return ExtensionResourceContribution(
            prompt_descriptors=[
                PromptFragmentDescriptor(
                    name="online-dynamic-resource",
                    source_path=source,
                    text="Every final answer must begin with [dynamic-resource].",
                )
            ],
            skills=[
                SkillDescriptor(
                    name="dynamic-online-summary",
                    source_path=source,
                    content="Prefer concise repo-aware summaries when README or docs are inspected.",
                )
            ],
        )

    api.on("resources_discover", _resources_discover)
"""


def _tool_prompt() -> str:
    return (
        "你有一个 bash 工具。\n"
        "请先使用 bash 查看 README.md，然后用一小段中文摘要它。"
    )


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-online-ext-resources-") as tmpdir:
        project_root = Path(tmpdir)
        (project_root / "README.md").write_text(
            "# Dynamic Resource Demo\\n\\nThis project exists to verify online extension resource loading.\\n",
            encoding="utf-8",
        )
        extensions_dir = project_root / "extensions"
        extensions_dir.mkdir(parents=True)
        extension_file = extensions_dir / "online_dynamic_resources.py"
        extension_file.write_text(EXTENSION_SOURCE.strip() + "\n", encoding="utf-8")

        registry = ToolRegistry()
        register_builtin_tools(registry)
        model = build_kimi_model()
        model_info = describe_model(model)
        runtime, session = await create_kimi_runtime_session(
            cwd=project_root,
            model=model,
            system_prompt="Online dynamic resources extension example.",
            tools=registry.list_enabled_tools(),
            persist=False,
        )
        attach_stream_printer(session)

        print("=== Online Extension Example: Dynamic Resources ===")
        print(f"Project root: {project_root}")
        print(f"Extension file: {extension_file}")
        print(f"Provider: {model_info['provider']}")
        print(f"Model: {model_info['model']}")
        print(f"API: {model_info['api']}")
        print()
        print("System prompt preview:")
        print(session.agent.system_prompt)
        print()

        try:
            await session.prompt(_tool_prompt())
        finally:
            await runtime.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
