"""Executable smoke for the Product-neutral Harness tool authoring surface."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.ai.types import ToolCall
from loushang.harness.effects import PublicationEffect
from loushang.harness.policy import PolicyDecision
from loushang.harness.tools import (
    FilesystemActionAdapter,
    ToolContext,
    ToolRegistry,
    authorized_tool,
    direct_tool,
    tool,
)
from loushang.harness.tools.execution import PreparedToolAction, ToolCallContext
from loushang.harness.tools.workspace.authorization import (
    create_workspace_tool_execution_host,
)


@tool()
async def add(left: int, right: int) -> int:
    """Add two integers without consuming a protected resource."""

    return left + right


@tool()
async def save_note(path: str, content: str, context: ToolContext) -> str:
    """Write one note after its filesystem action has been authorized."""

    target = Path(context.cwd or ".") / path
    target.write_text(content, encoding="utf-8")
    return str(target.resolve())


@dataclass(frozen=True, slots=True)
class DeployActionAdapter:
    """Describe one publication without performing it during authorization."""

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        target = call.arguments.get("target")
        if not isinstance(target, str) or not target:
            raise TypeError("target must be a non-empty string")
        return PreparedToolAction(
            tool_name=call.name,
            authorization_arguments={"target": target},
            execution_arguments=call.arguments,
            cwd=context.cwd,
            effects=(PublicationEffect(target),),
        )


@tool()
async def deploy(target: str) -> str:
    """Return the publication target after authorization."""

    return f"deployed {target}"


@dataclass(frozen=True, slots=True)
class AllowExamplePolicy:
    def evaluate(self, _subject: object) -> PolicyDecision:
        return PolicyDecision.allow()


async def run_example(cwd: Path) -> dict[str, object]:
    registry = ToolRegistry(
        execution_host=create_workspace_tool_execution_host(
            policy_evaluator=AllowExamplePolicy(),
        )
    )
    definitions = (
        direct_tool(add),
        authorized_tool(
            save_note,
            action=FilesystemActionAdapter(
                "write",
                authorization_fields=("content",),
            ),
        ),
        authorized_tool(deploy, action=DeployActionAdapter()),
    )
    for definition in definitions:
        registry.register_tool(definition)
    materialized = {
        item.name: item
        for item in registry.materialize_definitions(
            definitions,
            context_provider=lambda *, tool_call_id: ToolContext(
                tool_call_id=tool_call_id,
                cwd=str(cwd),
            ),
        )
    }

    add_result = await materialized["add"].execute(
        "example-add",
        {"left": 2, "right": 3},
    )
    note_result = await materialized["save_note"].execute(
        "example-save",
        {"path": "note.txt", "content": "hello"},
    )
    deploy_result = await materialized["deploy"].execute(
        "example-deploy",
        {"target": "staging"},
    )
    return {
        "add": add_result.details,
        "note": note_result.details,
        "note_content": (cwd / "note.txt").read_text(encoding="utf-8"),
        "deploy": deploy_result.details,
    }


def main() -> None:
    with TemporaryDirectory(prefix="loushang-tool-authoring-") as directory:
        print(
            json.dumps(
                asyncio.run(run_example(Path(directory))),
                ensure_ascii=False,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
