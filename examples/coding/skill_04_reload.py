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

SKILL_ALPHA = """\
---
name: alpha
description: First skill
---
Alpha skill content.
"""

SKILL_BETA = """\
---
name: beta
description: Second skill added after initial discovery
---
Beta skill content.
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


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-skill-reload-") as tmpdir:
        project_root = Path(tmpdir)
        skills_dir = project_root / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "alpha").mkdir(parents=True)
        (skills_dir / "alpha" / "SKILL.md").write_text(SKILL_ALPHA, encoding="utf-8")

        print("=== Skill Hot Reload ===")
        print(f"Project root: {project_root}")
        print()

        loader = SkillLoader()
        loader.discover_skills(project_root)

        print("--- Initial discovery ---")
        for skill in loader.list_enabled_skills():
            print(f"  {skill.name}: {skill.description}")
        print()

        runtime = create_agent_session_runtime(
            session_dir=project_root / ".loushang-sessions",
            model=_model(),
            stream_fn=_stream_fn,
            system_prompt="Skill reload demo.",
            persist=False,
        )
        session = await runtime.create_session(cwd=str(project_root))

        print("--- Session commands before reload ---")
        for cmd in session.list_commands():
            if cmd.source == "skill":
                print(f"  /{cmd.name}")
        print()

        # Add a new skill to the filesystem
        print("--- Adding new skill 'beta' to filesystem ---")
        (skills_dir / "beta").mkdir(parents=True)
        (skills_dir / "beta" / "SKILL.md").write_text(SKILL_BETA, encoding="utf-8")
        print()

        # Reload skills via loader
        print("--- Reloading skills via SkillLoader.reload_skills() ---")
        reloaded = loader.reload_skills()
        for skill in reloaded:
            print(f"  {skill.name}: {skill.description}")
        print()

        # Reload session resources to pick up the new skill
        print("--- Reloading session resources ---")
        await session.refresh_resources()
        print("--- Session commands after reload ---")
        for cmd in session.list_commands():
            if cmd.source == "skill":
                print(f"  /{cmd.name}")
        print()

        print("--- System prompt after reload ---")
        print("The standard session refresh rebuilds the prompt and tool view.")
        print()
        print(session.agent.system_prompt)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
