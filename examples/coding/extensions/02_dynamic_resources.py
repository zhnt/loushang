from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    assistant_text_message,
    build_runtime,
    print_messages,
    stream_with_final_message,
)

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
                    name="dynamic-extension-prompt",
                    source_path=source,
                    text="Always mention that dynamic extension resources were loaded.",
                )
            ],
            skills=[
                SkillDescriptor(
                    name="dynamic-review",
                    source_path=source,
                    content="Review dynamic resources before answering.",
                )
            ],
        )

    api.on("resources_discover", _resources_discover)
"""


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-ext-resources-") as tmpdir:
        project_root = Path(tmpdir)
        extensions_dir = project_root / "extensions"
        extensions_dir.mkdir(parents=True)
        extension_file = extensions_dir / "dynamic_resources.py"
        extension_file.write_text(EXTENSION_SOURCE.strip() + "\n", encoding="utf-8")

        async def stream_fn(model, context, options=None):
            return stream_with_final_message(assistant_text_message("Dynamic resources example ran offline."))

        runtime = build_runtime(
            session_dir=project_root / ".loushang-sessions",
            stream_fn=stream_fn,
            system_prompt="Base dynamic resources example prompt.",
        )
        session = await runtime.create_session(cwd=str(project_root))

        print("=== Extension Example: Dynamic Resources ===")
        print(f"Project root: {project_root}")
        print(f"Extension file: {extension_file}")
        print()
        print("System prompt assembled for the session:")
        print(session.agent.system_prompt)
        print()
        print("Prompt fragments:")
        for fragment in session.resource_bundle.prompt_fragments:
            print(f"- {fragment}")
        print()
        print("Skills:")
        for skill in session.resource_bundle.skills:
            print(f"- {skill.name}: {skill.content}")
        print()

        await session.prompt("Run one turn to show the session still works with dynamic resources.")
        print("Messages:")
        print_messages(session)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
