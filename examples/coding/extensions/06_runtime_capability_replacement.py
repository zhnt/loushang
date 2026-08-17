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
    stream_with_final_message,
)

EXTENSION_SOURCE = '''
from pathlib import Path

from loushang.harness.runtime import SideQuestionAnswer


LOG_PATH = Path(__file__).resolve().parent / "runtime-capability.log"


def _append(event: str) -> None:
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{event}\\n")


class DemoProvider:
    async def ask(self, question, *, on_update=None):
        del on_update
        _append(f"ask:{question}")
        return SideQuestionAnswer(text=f"extension:{question}")

    def cancel(self):
        _append("cancel")


class DemoProviderFactory:
    def bind(self, context):
        del context
        _append("bind")
        return DemoProvider()


def _create_provider_factory():
    _append("create")
    return DemoProviderFactory()


def _dispose_provider_factory(factory):
    del factory
    _append("dispose")


def register(api):
    api.register_side_question_provider(
        "demo",
        create=_create_provider_factory,
        dispose=_dispose_provider_factory,
        priority=30,
    )
'''

MANIFEST_SOURCE = '''
[extension]
id = "examples.side-question"
name = "Runtime Capability Replacement"
version = "0.1.0"
description = "Replaces Coding's side-question Provider."

[permissions]
level = "safe"
capabilities = ["interaction.side_question"]
'''


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-ext-runtime-capability-") as tmpdir:
        project_root = Path(tmpdir)
        extension_dir = project_root / "extensions" / "side_question"
        extension_dir.mkdir(parents=True)
        extension_file = extension_dir / "extension.py"
        manifest_file = extension_dir / "loushang-extension.toml"
        lifecycle_file = extension_dir / "runtime-capability.log"
        extension_file.write_text(
            EXTENSION_SOURCE.strip() + "\n",
            encoding="utf-8",
        )
        manifest_file.write_text(
            MANIFEST_SOURCE.strip() + "\n",
            encoding="utf-8",
        )

        async def stream_fn(model, context, options=None):
            del model, context, options
            return stream_with_final_message(
                assistant_text_message("The main Agent was not needed.")
            )

        runtime = build_runtime(
            session_dir=project_root / ".loushang-sessions",
            stream_fn=stream_fn,
            system_prompt="Runtime Capability replacement example.",
        )
        session = await runtime.create_session(cwd=str(project_root))

        try:
            selected = session.capability_profile.capability(
                "interaction.side_question"
            ).selections[0]
            answer = await session.ask_side_question("What is the current status?")

            print("=== Extension Example: Runtime Capability Replacement ===")
            print(f"Selected source: {selected.source}")
            print(f"Selected layer: {selected.layer_id}")
            print(
                "Implementation: "
                f"{selected.selection.implementation}"
            )
            print(f"Answer: {answer.text}")
        finally:
            await session.dispose()

        lifecycle = lifecycle_file.read_text(encoding="utf-8").splitlines()
        print(f"Lifecycle: {' -> '.join(lifecycle)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
