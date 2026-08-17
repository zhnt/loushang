from __future__ import annotations

import asyncio
import json
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from loushang.harness.tools.execution import direct_execution

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loushang.agent.types import AgentToolResult
from loushang.ai.types import TextPart
from loushang.harness.conversation import ConversationHeader
from loushang.harness.tools.core import ToolDefinition
from loushang.harnesstui.conversation.agent_binding import AgentPlainHost


async def _execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: object | None = None,
    on_update: object | None = None,
) -> AgentToolResult[Any]:
    del tool_call_id, params, signal, on_update
    return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})


def _render_call(args: object, theme: dict[str, str], context: object) -> dict[str, str]:
    del theme
    command = args["command"] if isinstance(args, dict) and isinstance(args.get("command"), str) else ""
    context.state["command"] = command
    return {"text": f"$ {command}"}


def _render_result(
    result: AgentToolResult[Any],
    options: object,
    theme: dict[str, str],
    context: object,
) -> dict[str, str]:
    del theme
    text_parts = [
        part.text
        for part in result.content
        if getattr(part, "type", None) == "text" and isinstance(getattr(part, "text", None), str)
    ]
    output = "".join(text_parts).rstrip("\n")
    marker = "partial" if options.isPartial else "final"
    command = context.state.get("command", "")
    return {"text": f"{command}: {marker}: {output}"}


TOOL_DEFINITION = ToolDefinition(
    name="bash",
    label="Bash",
    description="Demonstrate rendered tool event payloads.",
    parameters={
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
        "additionalProperties": False,
    },
    execution=direct_execution(_execute),
    render_call=_render_call,
    render_result=_render_result,
)


class FakeRuntime:
    pass


class FakeSessionManager:
    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def get_header(self) -> ConversationHeader:
        return ConversationHeader(
            conversation_id="render-tool-events-contract",
            version=1,
            created_at="2026-05-09T00:00:00.000Z",
            metadata={"cwd": str(self._cwd)},
        )

    def get_cwd(self) -> str:
        return str(self._cwd)


class FakeSession:
    def __init__(self, cwd: Path, artifact_path: Path) -> None:
        self.session_manager = FakeSessionManager(cwd)
        self._artifact_path = artifact_path
        self._listeners: list[object] = []

    def subscribe(self, listener: object):
        self._listeners.append(listener)

        def unsubscribe() -> None:
            self._listeners.remove(listener)

        return unsubscribe

    def getToolDefinition(self, name: str) -> ToolDefinition | None:
        return TOOL_DEFINITION if name == "bash" else None

    async def prompt(self, user_input: str, images: object | None = None) -> None:
        del user_input, images
        events = [
            {
                "type": "tool_execution_start",
                "tool_call_id": "call-render-1",
                "tool_name": "bash",
                "args": {"command": "printf 'hello\\n'"},
            },
            {
                "type": "tool_execution_update",
                "tool_call_id": "call-render-1",
                "tool_name": "bash",
                "args": {"command": "printf 'hello\\n'"},
                "partial_result": AgentToolResult(
                    content=[TextPart(type="text", text="hello\n")],
                    details={"duration_ms": 5},
                ),
            },
            {
                "type": "tool_execution_end",
                "tool_call_id": "call-render-1",
                "tool_name": "bash",
                "args": {"command": "printf 'hello\\n'"},
                "result": AgentToolResult(
                    content=[TextPart(type="text", text="hello\n")],
                    details={
                        "durationMs": 12,
                        "stdout_artifact_path": str(self._artifact_path),
                    },
                ),
                "is_error": False,
            },
        ]
        for listener in list(self._listeners):
            for event in events:
                listener(event)

    async def wait_for_idle(self) -> None:
        return None


async def _render_jsonl(project_root: Path, artifact_path: Path) -> str:
    stdout = StringIO()
    host = AgentPlainHost(
        runtime=FakeRuntime(),
        session=FakeSession(project_root, artifact_path),
        stdout=stdout,
        output_mode="json",
        event_view="tools",
        render_tool_events=True,
    )
    exit_code = await host.run_once("show rendered tool events")
    if exit_code != 0:
        raise RuntimeError(f"AgentPlainHost exited with {exit_code}")
    return stdout.getvalue()


def _print_summary(raw_output: str) -> None:
    print("Raw JSONL:")
    print(raw_output, end="")

    print("\nRendered payload summary:")
    for line in raw_output.splitlines():
        payload = json.loads(line)
        event_type = payload.get("type")
        if "renderedToolCall" in payload:
            rendered = payload["renderedToolCall"]
            print(
                f"- {event_type}: renderedToolCall "
                f"status={rendered.get('status')} contract={rendered.get('contractVersion')}"
            )
        if "renderedToolResult" in payload:
            rendered = payload["renderedToolResult"]
            print(
                f"- {event_type}: renderedToolResult "
                f"status={rendered.get('status')} partial={rendered.get('isPartial')} "
                f"durationMs={rendered.get('durationMs')} artifacts={len(rendered.get('artifacts', []))}"
            )


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-render-tools-") as tmpdir:
        project_root = Path(tmpdir)
        artifact_path = project_root / "stdout.log"
        artifact_path.write_text("hello\n", encoding="utf-8")

        raw_output = await _render_jsonl(project_root, artifact_path)
        _print_summary(raw_output)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
