from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
while not (REPO_ROOT / "src").exists() and REPO_ROOT.parent != REPO_ROOT:
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.coding import create_agent_session_runtime
from loushang.coding.resource_runtime import CodingSkillLoader as SkillLoader

SKILL_REVIEW = """\
---
name: review
description: Perform a code review with structured feedback
---
Review the code for correctness, style, and potential bugs.
Provide line-specific suggestions where applicable.
"""

SKILL_TEST = """\
---
name: test
description: Generate unit tests for the given code
---
Write comprehensive unit tests covering edge cases.
Use the project's testing framework.
"""


def _model() -> Model:
    return Model(
        id="offline-demo-model",
        name="Offline Demo",
        provider="offline",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _usage() -> Usage:
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
        api="anthropic-messages",
        provider="offline",
        endpoint="offline",
        model="offline-demo-model",
        response_id=None,
        usage=_usage(),
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
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})

    asyncio.create_task(_feed())
    return stream


async def _stream_fn(model, context, options=None):
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
    return _stream_with_final_message(_assistant_text_message(f"Echo: {user_text}"))


def _print_messages(session) -> None:
    for index, message in enumerate(session.get_session_context().messages, start=1):
        role = getattr(message, "role", "unknown")
        content = getattr(message, "content", [])
        text = " ".join(
            part.text for part in content if getattr(part, "type", None) == "text"
        )
        print(f"{index}. {role}: {text}")


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-skill-") as tmpdir:
        project_root = Path(tmpdir)
        skills_dir = project_root / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "review").mkdir(parents=True)
        (skills_dir / "test").mkdir(parents=True)

        (skills_dir / "review" / "SKILL.md").write_text(SKILL_REVIEW, encoding="utf-8")
        (skills_dir / "test" / "SKILL.md").write_text(SKILL_TEST, encoding="utf-8")

        print("=== Skill Discovery, Filtering, and Replacement ===")
        print(f"Project root: {project_root}")
        print()

        loader = SkillLoader()
        discovered = loader.discover_skills(project_root)
        print(f"Discovered {len(discovered)} skill(s):")
        for skill in discovered:
            print(
                f"  - {skill.name}: {skill.description} (source_kind={skill.source_kind})"
            )
        print()

        all_skills = loader.list_skills()
        print(f"list_skills() returns {len(all_skills)}:")
        for skill in all_skills:
            print(f"  - {skill.name} (enabled={skill.enabled})")
        print()

        enabled = loader.list_enabled_skills()
        print(f"Enabled skills before disable: {[s.name for s in enabled]}")
        print()

        loader.disable_skill("test")
        enabled_after_disable = loader.list_enabled_skills()
        print(
            f"Enabled skills after disable('test'): {[s.name for s in enabled_after_disable]}"
        )
        print()

        loader.enable_skill("test")
        enabled_after_enable = loader.list_enabled_skills()
        print(
            f"Enabled skills after enable('test'): {[s.name for s in enabled_after_enable]}"
        )
        print()

        runtime = create_agent_session_runtime(
            session_dir=project_root / ".loushang-sessions",
            model=_model(),
            stream_fn=_stream_fn,
            system_prompt="Skill discovery demo.",
            persist=False,
        )
        session = await runtime.create_session(cwd=str(project_root))

        commands = session.list_commands()
        skill_commands = [c for c in commands if c.source == "skill"]
        print(f"Session commands from skills ({len(skill_commands)}):")
        for cmd in skill_commands:
            print(f"  /{cmd.name}: {cmd.description}")
        print()

        await session.prompt("Demonstrate skill integration.")
        print("Messages after prompt:")
        _print_messages(session)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
