from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    ENV_EXAMPLES_SESSION_DIR,
    _resolve_model_catalog,
    build_kimi_model,
    create_kimi_runtime_session,
    describe_model,
    resolve_api_key,
)

from loushang.agent.types import AgentToolResult
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage
from loushang.coding import create_agent_session_runtime
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution


def print_event(name: str, payload: dict[str, object]) -> None:
    print(f"{name}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


# ── Git primitives ──


@dataclass(frozen=True)
class StashEntry:
    ref: str
    label: str
    sha: str


class Checkpointer:
    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = repo_dir

    def _run(
        self, *args: str, check: bool = True, capture: bool = True
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo_dir),
            check=check,
            capture_output=capture,
            text=True,
        )

    def has_changes(self) -> bool:
        result = self._run("status", "--porcelain")
        return bool(result.stdout.strip())

    def create(self, label: str) -> StashEntry | None:
        if not self.has_changes():
            return None
        sha_proc = self._run("stash", "create")
        sha = sha_proc.stdout.strip()
        if not sha:
            return None
        self._run("stash", "store", "-m", label, sha)
        return StashEntry(ref="stash@{0}", label=label, sha=sha[:10])

    def list_entries(self) -> list[StashEntry]:
        result = self._run("stash", "list", "--format=%gd|%gs|%H")
        entries: list[StashEntry] = []
        for line in result.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            ref, subject, sha = parts
            label = subject
            if subject.startswith("On "):
                colon = subject.find(":")
                if colon >= 0:
                    label = subject[colon + 1 :].strip()
            entries.append(StashEntry(ref=ref.strip(), label=label, sha=sha[:10]))
        return entries

    def show_stat(self, ref: str) -> str:
        result = self._run("stash", "show", "--stat", ref)
        return result.stdout.strip()

    def restore(self, ref: str) -> str:
        result = self._run("stash", "apply", ref)
        return result.stdout.strip() or "<no apply output>"

    def reset_workdir(self) -> None:
        self._run("checkout", "--", ".")
        self._run("clean", "-fd")


def _bootstrap_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo_dir), check=True)
    subprocess.run(
        ["git", "config", "user.email", "demo@loushang.local"],
        cwd=str(repo_dir),
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "loushang demo"], cwd=str(repo_dir), check=True
    )
    (repo_dir / "hello.py").write_text(
        'def main() -> None:\n    print("hello")\n\n\nif __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "hello.py"], cwd=str(repo_dir), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init: hello.py"], cwd=str(repo_dir), check=True
    )


def _apply_dirty(path: Path, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    line = f"# checkpoint marker: {marker}\n"
    if line not in text:
        text = text + line
    path.write_text(text, encoding="utf-8")


# ── AgentTool ──


class GitCheckpointTool:
    name: str = "git_checkpoint"
    description: str = (
        "Create or manage non-destructive git stash checkpoints. "
        "Actions: create (label), list, restore (ref), reset_workdir."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "restore", "reset_workdir", "show_stat"],
                "description": "Which checkpoint action to perform",
            },
            "label": {
                "type": "string",
                "description": "Label for create action",
            },
            "ref": {
                "type": "string",
                "description": "Stash ref for restore or show_stat",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    label: str = "Git Checkpoint"
    prepare_arguments: None = None
    execution_mode: str = "sequential"

    def __init__(self, repo_dir: Path) -> None:
        self._cp = Checkpointer(repo_dir)

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: object | None = None,
        on_update: Any = None,
    ) -> AgentToolResult[dict[str, Any]]:
        action = params.get("action")
        if action == "create":
            label = params.get("label", "untitled")
            entry = self._cp.create(label)
            text = (
                f"created {entry.ref} ({entry.label}) {entry.sha}"
                if entry
                else "no changes to checkpoint"
            )
            return AgentToolResult(
                content=[TextPart(type="text", text=text)],
                details={"action": "create", "entry": entry},
            )
        if action == "list":
            entries = self._cp.list_entries()
            lines = [f"{e.ref}  {e.label}  {e.sha}" for e in entries]
            return AgentToolResult(
                content=[
                    TextPart(type="text", text="\n".join(lines) or "<no checkpoints>")
                ],
                details={"action": "list", "entries": entries},
            )
        if action == "restore":
            ref = params.get("ref", "stash@{0}")
            out = self._cp.restore(ref)
            return AgentToolResult(
                content=[TextPart(type="text", text=out)],
                details={"action": "restore", "ref": ref},
            )
        if action == "reset_workdir":
            self._cp.reset_workdir()
            return AgentToolResult(
                content=[TextPart(type="text", text="workdir reset")],
                details={"action": "reset_workdir"},
            )
        if action == "show_stat":
            ref = params.get("ref", "stash@{0}")
            stat = self._cp.show_stat(ref)
            return AgentToolResult(
                content=[TextPart(type="text", text=stat or "<empty>")],
                details={"action": "show_stat", "ref": ref},
            )
        return AgentToolResult(
            content=[TextPart(type="text", text=f"unknown action: {action}")],
            details={"action": action, "error": "unknown"},
        )


def _git_checkpoint_definition(tool: GitCheckpointTool) -> ToolDefinition:
    return ToolDefinition(
        name=tool.name,
        label=tool.label,
        description=tool.description,
        parameters=tool.parameters,
        execution=direct_execution(tool.execute),
        execution_mode="sequential",
    )


# ── Offline mock stream ──

_OFFLINE_USAGE = Usage(
    input=0,
    output=0,
    cache_read=0,
    cache_write=0,
    total_tokens=0,
    cost=None,
)


def _offline_model() -> Model:
    return Model(
        id="offline-git-checkpoint-model",
        name="Offline Git Checkpoint",
        provider="offline",
        endpoint="offline",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=4096,
            max_tokens=1024,
        ),
    )


def _assistant_text(text: str) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="offline",
        provider="offline",
        endpoint="offline",
        model="offline-git-checkpoint-model",
        response_id=None,
        usage=_OFFLINE_USAGE,
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _assistant_tool_call(
    tool_name: str, arguments: dict[str, object]
) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="tc_1",
                name=tool_name,
                arguments=arguments,
            )
        ],
        api="offline",
        provider="offline",
        endpoint="offline",
        model="offline-git-checkpoint-model",
        response_id=None,
        usage=_OFFLINE_USAGE,
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


def _stream_with_message(message: AssistantMessage) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def _feed() -> None:
        stream.push({"type": "start", "partial": message})
        if message.content and isinstance(message.content[0], TextPart):
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
        elif message.content and isinstance(message.content[0], ToolCall):
            stream.push(
                {"type": "toolcall_start", "content_index": 0, "partial": message}
            )
            stream.push(
                {
                    "type": "toolcall_delta",
                    "content_index": 0,
                    "delta": str(message.content[0].arguments),
                    "partial": message,
                }
            )
            stream.push(
                {
                    "type": "toolcall_end",
                    "content_index": 0,
                    "tool_call": message.content[0],
                    "partial": message,
                }
            )
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})  # type: ignore[typeddict-item]

    asyncio.create_task(_feed())
    return stream


# ── Demo runners ──


async def _run_offline(repo_dir: Path) -> dict[str, object]:
    print("=== Git Checkpoint (offline) ===")
    print_event("message.start", {"mode": "offline", "step": "bootstrap"})

    _bootstrap_repo(repo_dir)
    cp = Checkpointer(repo_dir)
    head_sha = cp._run("rev-parse", "--short", "HEAD").stdout.strip()
    print(f"head_sha: {head_sha}")

    session_dir = repo_dir / ".loushang-sessions"
    os.environ[ENV_EXAMPLES_SESSION_DIR] = str(session_dir)

    async def _offline_stream_fn(
        model: Model, context: Any, options: Any = None
    ) -> AssistantMessageEventStream:
        del model, options
        messages = getattr(context, "messages", context)
        tool_results = [m for m in messages if getattr(m, "role", None) == "toolResult"]
        if len(tool_results) == 0:
            _apply_dirty(repo_dir / "hello.py", "before-cleanup")
            return _stream_with_message(
                _assistant_tool_call(
                    "git_checkpoint",
                    {"action": "create", "label": "loushang/checkpoint/before-cleanup"},
                )
            )
        if len(tool_results) == 1:
            _apply_dirty(repo_dir / "hello.py", "after-cleanup")
            return _stream_with_message(
                _assistant_tool_call(
                    "git_checkpoint",
                    {"action": "create", "label": "loushang/checkpoint/after-cleanup"},
                )
            )
        if len(tool_results) == 2:
            return _stream_with_message(
                _assistant_tool_call("git_checkpoint", {"action": "list"})
            )
        return _stream_with_message(
            _assistant_text(
                f"Offline checkpoint flow complete after {len(tool_results)} tool calls."
            )
        )

    tool = GitCheckpointTool(repo_dir)
    tool_definition = _git_checkpoint_definition(tool)
    runtime = create_agent_session_runtime(
        session_dir=session_dir,
        model=_offline_model(),
        system_prompt="You are a git checkpoint assistant. Use the git_checkpoint tool to create and list checkpoints.",
        stream_fn=_offline_stream_fn,
        tools=[tool_definition],
        persist=False,
    )
    session = await runtime.create_session(cwd=str(repo_dir))
    print_event("tool.start", {"name": "session_create", "mode": "offline"})
    print_event(
        "tool.end", {"name": "session_create", "status": "ok", "tools": [tool.name]}
    )

    print_event("message.start", {"step": "prompt", "mode": "offline"})
    await session.prompt("Create two checkpoints and list them.")
    print_event("message.end", {"step": "prompt", "mode": "offline"})

    # Gather results from messages
    tool_results = [
        m
        for m in session.get_session_context().messages
        if getattr(m, "role", None) == "toolResult"
    ]
    labels = []
    for tr in tool_results:
        details = getattr(tr, "details", {})
        entry = details.get("entry") if isinstance(details, dict) else None
        if entry:
            labels.append(getattr(entry, "label", "?"))

    entries = cp.list_entries()
    print("checkpoints:")
    for entry in entries:
        print(f"  {entry.ref}  {entry.label}  {entry.sha}")

    ok = len(entries) == 2
    print_event(
        "message.end",
        {
            "result": "pass" if ok else "fail",
            "checkpoint_count": len(entries),
            "labels": labels,
        },
    )
    return {
        "head_sha": head_sha,
        "checkpoint_count": len(entries),
        "labels": [e.label for e in entries],
    }


async def _run_live(repo_dir: Path, timeout_seconds: float) -> dict[str, object]:
    print("=== Git Checkpoint (live) ===")
    print_event("message.start", {"mode": "live", "step": "bootstrap"})

    try:
        resolve_api_key()
    except Exception:
        print("live path skipped: no resolvable key")
        return {"checkpoint_count": 0, "labels": [], "skipped": True}

    _bootstrap_repo(repo_dir)
    cp = Checkpointer(repo_dir)
    head_sha = cp._run("rev-parse", "--short", "HEAD").stdout.strip()
    print(f"head_sha: {head_sha}")

    _apply_dirty(repo_dir / "hello.py", "before-cleanup")

    model = build_kimi_model()
    info = describe_model(model)
    print_event(
        "model.start",
        {
            "provider": info["provider"],
            "endpoint": info["endpoint"],
            "api": info["api"],
            "model": info["model"],
            "base_url": info["base_url"],
        },
    )

    tool = GitCheckpointTool(repo_dir)
    tool_definition = _git_checkpoint_definition(tool)
    runtime, session = await create_kimi_runtime_session(
        cwd=repo_dir,
        model=model,
        system_prompt=(
            "You are a git checkpoint assistant. "
            "Use the git_checkpoint tool to create a checkpoint with label 'loushang/checkpoint/before-cleanup', "
            "then list all checkpoints. Reply with a short summary of what you did."
        ),
        tools=[tool_definition],
        persist=False,
    )
    print_event(
        "tool.start", {"name": "session_create", "mode": "live", "tools": [tool.name]}
    )
    print_event("tool.end", {"name": "session_create", "status": "ok"})

    print_event("message.start", {"step": "prompt", "mode": "live"})
    try:
        await asyncio.wait_for(
            session.prompt(
                "Create a checkpoint named loushang/checkpoint/before-cleanup and list checkpoints."
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        print_event("message.end", {"step": "prompt", "status": "timeout"})
        return {"checkpoint_count": 0, "labels": [], "skipped": True}

    entries = cp.list_entries()
    print("checkpoints:")
    for entry in entries:
        print(f"  {entry.ref}  {entry.label}  {entry.sha}")

    ok = len(entries) >= 1
    print_event(
        "message.end",
        {"result": "pass" if ok else "fail", "checkpoint_count": len(entries)},
    )
    return {
        "head_sha": head_sha,
        "checkpoint_count": len(entries),
        "labels": [e.label for e in entries],
    }


def _print_offline_sample() -> None:
    print("=== offline expected sample ===")
    print("head_sha=<short>")
    print("checkpoint_count=2")
    print("entry[0].label=loushang/checkpoint/after-cleanup")
    print("entry[1].label=loushang/checkpoint/before-cleanup")
    print("final_status=pass")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Git checkpoint as an AgentTool, with offline mock and optional live Kimi path.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the live Kimi-driven path (requires API key).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Live path prompt timeout in seconds.",
    )
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Keep the temporary repo after the run (prints its path).",
    )
    return parser.parse_args()


async def main_async() -> int:
    args = parse_args()

    catalog = _resolve_model_catalog()
    if catalog is None:
        print("resolved catalog: <unset>; using built-in fallback")
    else:
        print(f"resolved catalog: {catalog}")

    if args.keep_workspace:
        repo_dir = Path.cwd() / ".loushang-git-checkpoint-demo"
        if repo_dir.exists():
            print(f"workspace already exists, refusing to overwrite: {repo_dir}")
            print_event("message.end", {"result": "fail", "reason": "workspace_exists"})
            return 2
    else:
        repo_dir = (
            Path(TemporaryDirectory(prefix="loushang-git-checkpoint-").name) / "repo"
        )

    try:
        if args.live:
            summary = await _run_live(repo_dir, args.timeout)
        else:
            summary = await _run_offline(repo_dir)
    finally:
        if args.keep_workspace:
            print(f"workspace_kept: {repo_dir}")

    expected_count = 2 if not args.live else 1
    ok = summary.get("checkpoint_count", 0) >= expected_count
    print_event(
        "message.end",
        {
            "result": "pass" if ok else "fail",
            "checkpoint_count": summary.get("checkpoint_count", 0),
            "expected_count": expected_count,
            "mode": "live" if args.live else "offline",
        },
    )

    if not args.live:
        _print_offline_sample()

    return 0 if ok else 1


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
