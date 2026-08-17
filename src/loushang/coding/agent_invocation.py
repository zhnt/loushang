"""Coding's CLI semantics for the Harness one-shot agent invocation tool."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

from loushang.ai.model import model_selection_ref, normalize_model_selection
from loushang.coding.multiagent import (
    coding_agent_type_system_prompt,
    coding_read_only_agent_types,
)
from loushang.harness.multiagent import AgentTypeRegistry, AgentTypeSpec
from loushang.harness.tools.agent_delegate import (
    AGENT_DELEGATE_TOOL_NAME,
    AgentDelegateToolPack,
    AgentInvocationRequest,
    AgentInvocationResult,
    PreparedAgentInvocation,
)
from loushang.harness.tools.multiagent import MULTIAGENT_TOOL_NAMES
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harness.workspace.exec import (
    ExecRequest,
    ExecResult,
    materialize_exec_request,
)
from loushang.harness.workspace.truncation import truncate_tail

DEFAULT_AGENT_INVOCATION_TIMEOUT_SECONDS = 300.0
DEFAULT_AGENT_INVOCATION_PREVIEW_BYTES = 64 * 1024
DEFAULT_AGENT_INVOCATION_PREVIEW_LINES = 1_000
DEFAULT_AGENT_INVOCATION_ROLLING_BYTES = 128 * 1024
_SUBPROCESS_FORBIDDEN_TOOL_NAMES = frozenset(
    {
        AGENT_DELEGATE_TOOL_NAME,
        *MULTIAGENT_TOOL_NAMES,
        "bash",
        "write",
        "edit",
    }
)
_ONE_SHOT_READ_ONLY_PROMPT = (
    "This one-shot subprocess exposes only the listed read/search tools. "
    "Bash and mutation tools are intentionally unavailable; do not attempt "
    "to modify the workspace or spawn another agent."
)


class CodingCliAgentInvocationAdapter:
    """Compile a finite Coding role into a hardened ``loushang`` subprocess."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        parent_allowed_tools: Iterable[str],
        executable: str | Path | None = None,
        environment: Mapping[str, str] | None = None,
        agent_types: AgentTypeRegistry | None = None,
        timeout_seconds: float = DEFAULT_AGENT_INVOCATION_TIMEOUT_SECONDS,
        preview_max_bytes: int = DEFAULT_AGENT_INVOCATION_PREVIEW_BYTES,
        preview_max_lines: int = DEFAULT_AGENT_INVOCATION_PREVIEW_LINES,
        rolling_max_bytes: int = DEFAULT_AGENT_INVOCATION_ROLLING_BYTES,
    ) -> None:
        root = (
            Path(workspace_root).expanduser().resolve(strict=False)
            if workspace_root is not None
            else None
        )
        if root is not None and not root.is_dir():
            raise NotADirectoryError(20, "Not a directory", str(root))
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if preview_max_bytes < 1 or preview_max_lines < 1:
            raise ValueError("preview limits must be positive")
        if rolling_max_bytes < preview_max_bytes:
            raise ValueError("rolling_max_bytes must be at least preview_max_bytes")

        parent_tools = tuple(parent_allowed_tools)
        if any(not isinstance(name, str) or not name for name in parent_tools):
            raise ValueError("parent_allowed_tools must contain non-empty names")
        self._workspace_root = root
        self._parent_allowed_tools = frozenset(parent_tools)
        self._executable = str(executable) if executable is not None else None
        self._environment = dict(environment) if environment is not None else None
        self._agent_types = agent_types or coding_read_only_agent_types()
        self._timeout_seconds = float(timeout_seconds)
        self._preview_max_bytes = preview_max_bytes
        self._preview_max_lines = preview_max_lines
        self._rolling_max_bytes = rolling_max_bytes

    @property
    def admitted_agent_types(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self._agent_types.values())

    def prepare(
        self,
        request: AgentInvocationRequest,
        *,
        default_cwd: str | None,
        model: object | None,
    ) -> PreparedAgentInvocation:
        spec = self._resolve_agent_type(request.agent_type)
        cwd = self._resolve_cwd(request.cwd, default_cwd=default_cwd)
        allowed_tools = self._resolve_allowed_tools(spec)
        resolved_model = spec.default_model or _model_ref(model)
        command = [
            self._resolve_executable(),
            "--mode",
            "print",
            "--no-session",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--system-prompt",
            (
                f"{coding_agent_type_system_prompt(spec.name)}\n\n"
                f"{_ONE_SHOT_READ_ONLY_PROMPT}"
            ),
            "--tools",
            ",".join(allowed_tools),
            "--cwd",
            str(cwd),
        ]
        if resolved_model is not None:
            command.extend(("--model", resolved_model))
        exec_request = materialize_exec_request(
            ExecRequest(
                command=tuple(command),
                cwd=str(cwd),
                timeout_seconds=self._timeout_seconds,
                stdin=request.task,
                preview_max_lines=self._preview_max_lines,
                preview_max_bytes=self._preview_max_bytes,
                capture_full_output=False,
                retain_output_artifacts=False,
                rolling_max_bytes=self._rolling_max_bytes,
            ),
            environ=self._environment,
        )
        return PreparedAgentInvocation(
            request=request,
            exec_request=exec_request,
            allowed_tools=allowed_tools,
            model_ref=resolved_model,
        )

    def project(
        self,
        prepared: PreparedAgentInvocation,
        result: ExecResult,
    ) -> AgentInvocationResult:
        del prepared
        if result.exit_code == 0 and not result.timed_out and not result.cancelled:
            raw_output = result.stdout_preview or result.stdout
            truncated = result.stdout_truncated
        else:
            raw_output = (
                result.stderr_preview
                or result.stderr
                or result.stdout_preview
                or result.stdout
            )
            truncated = result.stderr_truncated or result.stdout_truncated
        bounded = truncate_tail(
            raw_output,
            max_lines=self._preview_max_lines,
            max_bytes=self._preview_max_bytes,
        )
        return AgentInvocationResult(
            output_text=bounded.content,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            cancelled=result.cancelled,
            truncated=truncated or bounded.truncated,
        )

    def _resolve_agent_type(self, name: str) -> AgentTypeSpec:
        spec = self._agent_types.resolve(name)
        if spec is None:
            raise ValueError(f"unknown or non-read-only Coding agent type: {name!r}")
        return spec

    def _resolve_allowed_tools(self, spec: AgentTypeSpec) -> tuple[str, ...]:
        allowed = tuple(
            name
            for name in spec.allowed_tools
            if name in self._parent_allowed_tools
            and name not in _SUBPROCESS_FORBIDDEN_TOOL_NAMES
        )
        if not allowed:
            raise PermissionError(
                f"parent grants no admitted tools to Coding agent type {spec.name!r}"
            )
        return allowed

    def _resolve_cwd(
        self,
        requested_cwd: str | None,
        *,
        default_cwd: str | None,
    ) -> Path:
        if default_cwd is None and self._workspace_root is None:
            raise ValueError("delegated agent invocation requires a workspace cwd")
        workspace_root = (
            self._workspace_root
            if self._workspace_root is not None
            else Path(default_cwd or "").expanduser().resolve(strict=False)
        )
        base = (
            Path(default_cwd).expanduser()
            if default_cwd is not None
            else workspace_root
        )
        candidate = Path(requested_cwd).expanduser() if requested_cwd else base
        if not candidate.is_absolute():
            candidate = base / candidate
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(workspace_root):
            raise PermissionError(
                f"delegated agent cwd is outside the Coding workspace: {resolved}"
            )
        if not resolved.is_dir():
            raise NotADirectoryError(20, "Not a directory", str(resolved))
        return resolved

    def _resolve_executable(self) -> str:
        if self._executable is not None:
            return _require_executable(self._executable)
        adjacent = Path(sys.executable).resolve(strict=False).parent / "loushang"
        if adjacent.is_file() and os.access(adjacent, os.X_OK):
            return str(adjacent)
        discovered = shutil.which("loushang")
        if discovered is None:
            raise FileNotFoundError(
                "cannot locate the loushang CLI for delegated agent invocation"
            )
        return _require_executable(discovered)


def register_coding_agent_delegate_tool(
    registry: WorkspaceToolRegistry,
    *,
    workspace_root: str | Path | None = None,
    parent_allowed_tools: Iterable[str],
    executable: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> WorkspaceToolRegistry:
    adapter = CodingCliAgentInvocationAdapter(
        workspace_root=workspace_root,
        parent_allowed_tools=parent_allowed_tools,
        executable=executable,
        environment=environment,
    )
    return AgentDelegateToolPack(adapter=adapter).register(registry)


def _model_ref(model: object | None) -> str | None:
    selection = normalize_model_selection(model)
    return model_selection_ref(selection) if selection is not None else None


def _require_executable(value: str | Path) -> str:
    path = Path(value).expanduser().resolve(strict=False)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"loushang CLI is not executable: {path}")
    return str(path)


__all__ = [
    "DEFAULT_AGENT_INVOCATION_PREVIEW_BYTES",
    "DEFAULT_AGENT_INVOCATION_PREVIEW_LINES",
    "DEFAULT_AGENT_INVOCATION_ROLLING_BYTES",
    "DEFAULT_AGENT_INVOCATION_TIMEOUT_SECONDS",
    "CodingCliAgentInvocationAdapter",
    "register_coding_agent_delegate_tool",
]
