"""A minimal non-Coding Product that consumes the public Harness tool runtime."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from loushang.agent.types import AgentTool
from loushang.harness.approval import ApprovalResolver, HeadlessApprovalResolver
from loushang.harness.effects import FilesystemEffect
from loushang.harness.policy import PolicyDecision, ToolPolicySubject
from loushang.harness.tools import (
    FilesystemActionAdapter,
    ToolContext,
    ToolRegistry,
    authorized_tool,
    direct_tool,
    tool,
)
from loushang.harness.tools.workspace.authorization import (
    create_workspace_tool_execution_host,
)


@tool()
async def count_words(text: str) -> int:
    """Count words without consuming a protected resource."""

    return len(text.split())


@tool()
async def export_document(
    path: str,
    content: str,
    context: ToolContext,
) -> str:
    """Export one document after the write effect has been authorized."""

    target = Path(context.cwd or ".") / path
    target.write_text(content, encoding="utf-8")
    return str(target.resolve())


@dataclass(frozen=True, slots=True)
class DocumentProductPolicy:
    """Own Product wording and defaults without reimplementing the Gateway."""

    def evaluate(self, subject: ToolPolicySubject) -> PolicyDecision:
        if any(
            isinstance(effect, FilesystemEffect)
            and effect.operation == "write"
            for effect in subject.effects
        ):
            return PolicyDecision.ask(
                "Confirm document export",
                code="document_export",
            )
        return PolicyDecision.allow()


@dataclass(slots=True)
class DocumentProduct:
    """Small executable Product adapter over the common Harness boundaries."""

    export_root: Path
    approval_resolver: ApprovalResolver = field(
        default_factory=lambda: HeadlessApprovalResolver(mode="deny"),
        repr=False,
    )
    events: list[dict[str, object]] = field(default_factory=list)
    _tools: dict[str, AgentTool[Any]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.export_root.mkdir(parents=True, exist_ok=True)
        registry = ToolRegistry(
            execution_host=create_workspace_tool_execution_host(
                policy_evaluator=DocumentProductPolicy(),
                approval_resolver=self.approval_resolver,
            )
        )
        definitions = (
            direct_tool(count_words),
            authorized_tool(
                export_document,
                action=FilesystemActionAdapter(
                    "write",
                    authorization_fields=("content",),
                ),
            ),
        )
        for definition in definitions:
            registry.register_tool(definition)
        self._tools = {
            item.name: item
            for item in registry.materialize_definitions(
                definitions,
                context_provider=lambda *, tool_call_id: ToolContext(
                    tool_call_id=tool_call_id,
                    cwd=str(self.export_root),
                    event_sink=self.events.append,
                ),
            )
        }

    async def count(self, text: str) -> int:
        tool = self._tools["count_words"]
        result = await tool.execute("document-count", {"text": text})
        return int(result.details)

    async def export(self, path: str, content: str) -> Path:
        tool = self._tools["export_document"]
        result = await tool.execute(
            "document-export",
            {"path": path, "content": content},
        )
        return Path(str(result.details))


async def run_example(export_root: Path) -> dict[str, object]:
    product = DocumentProduct(
        export_root,
        approval_resolver=HeadlessApprovalResolver(mode="allow"),
    )
    content = "Harness keeps Product policy thin."
    word_count = await product.count(content)
    exported = await product.export("brief.txt", content)
    return {
        "word_count": word_count,
        "exported": exported.name,
        "content": exported.read_text(encoding="utf-8"),
        "audit_events": [event["type"] for event in product.events],
        "policy_code": next(
            event["policy_code"]
            for event in product.events
            if event["type"] == "tool_policy_evaluated"
        ),
    }


def main() -> None:
    with TemporaryDirectory(prefix="loushang-document-product-") as directory:
        print(
            json.dumps(
                asyncio.run(run_example(Path(directory))),
                ensure_ascii=False,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
