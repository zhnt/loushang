"""Agent access to files explicitly submitted to the current Session."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, cast

from loushang.agent.types import AgentToolResult
from loushang.ai.types import TextPart, ToolCall
from loushang.appserver.protocol import AppServiceError
from loushang.coding.workspace.operations import CodingWorkspaceOperations
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    constrain_execution_profile,
)
from loushang.harness.policy import (
    PolicyDecision,
    PolicyEvaluator,
    PolicySubject,
    ToolPolicySubject,
    evaluate_policy,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    AuthorizedToolAction,
    AuthorizedToolContext,
    CallableToolActionAdapter,
    DirectExecution,
    DirectToolContext,
    PreparedToolAction,
    ToolCallContext,
)
from loushang.harness.tools.workspace.factory import (
    ToolName,
    ToolsOptions,
    create_tool_definition,
)
from loushang.harness.workspace.operations import ToolOperations

from .resources import HostedResourceAccess

SESSION_FILES = "session_files"


def session_files_tool(get_access: Callable[[], HostedResourceAccess]) -> ToolDefinition:
    async def handle(call: ToolCall, context: DirectToolContext) -> AgentToolResult[None]:
        arguments = call.arguments
        action = arguments.get("action")
        access = get_access()
        try:
            if action == "list":
                text = json.dumps([
                    {"id": item.id, "name": item.name, "sizeBytes": item.size_bytes,
                     "kind": item.kind, "source": item.source}
                    for item in access.associated(kind="file")
                ], ensure_ascii=False)
            elif action == "read" and isinstance(arguments.get("id"), str):
                text = json.dumps(
                    access.read_text(arguments["id"], offset=arguments.get("offset", 0)),
                    ensure_ascii=False,
                )
            else:
                text = "Select list or read. Reading requires a Session file ID."
        except (AppServiceError, OSError, ValueError):
            text = "The selected Session file is unavailable."
        return AgentToolResult([TextPart(type="text", text=text)], None)

    return ToolDefinition(
        name=SESSION_FILES,
        label="Session files",
        description="List resources attached to this session and read managed UTF-8 files by ID. Use resource_ tools for Host references.",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "read"]},
                "id": {"type": "string", "description": "File ID returned by list."},
                "offset": {"type": "integer", "minimum": 0, "description": "Use nextOffset to read the next page."},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        execution=DirectExecution(handle),
    )


HOST_RESOURCE_TOOLS: tuple[ToolName, ...] = ("read", "ls", "find", "grep", "edit", "write")
_HOST_TOOL_PREFIX = "resource_"


def original_workspace_tool(name: str) -> str:
    operation = name.removeprefix(_HOST_TOOL_PREFIX)
    return operation if operation in HOST_RESOURCE_TOOLS else name


@dataclass(frozen=True)
class HostReferencePolicy:
    policy: PolicyEvaluator

    async def evaluate(self, subject: PolicySubject, /) -> PolicyDecision | None:
        result = await evaluate_policy(self.policy, subject)
        if not isinstance(subject, ToolPolicySubject) or (result and result.disposition == "deny"):
            return result
        original = original_workspace_tool(subject.tool_name)
        if original == subject.tool_name:
            return result
        original_result = await evaluate_policy(self.policy, replace(subject, tool_name=original))
        if original_result and original_result.disposition in {"deny", "ask"}:
            return original_result
        return result or original_result


def hosted_resource_tools(get_access: Callable[[], HostedResourceAccess], *, host_paths: bool) -> list[ToolDefinition]:
    return [session_files_tool(get_access), *(_host_reference_tools(get_access) if host_paths else ())]


def _host_reference_tools(get_access: Callable[[], HostedResourceAccess]) -> list[ToolDefinition]:
    return [_host_reference_tool(operation, get_access) for operation in HOST_RESOURCE_TOOLS]


def _host_reference_tool(
    operation: ToolName, get_access: Callable[[], HostedResourceAccess],
) -> ToolDefinition:
    base = create_tool_definition(operation)
    assert isinstance(base.execution, AuthorizedExecution)
    adapter = base.execution.action_adapter
    binding_key = base.operation_binding_key
    assert binding_key is not None
    name = _HOST_TOOL_PREFIX + operation
    writes = operation in {"write", "edit"}

    def prepare(call: ToolCall, context: ToolCallContext) -> PreparedToolAction:
        args = dict(call.arguments)
        resource_id = args.pop("resourceId")
        relative = args.get("path") or "."
        if not isinstance(resource_id, str) or not isinstance(relative, str):
            raise ValueError("Select a Session resource ID and relative path")
        ref, target = get_access().resolve_host(resource_id, relative)
        if ref.kind == "file" and operation != "read":
            raise ValueError("This operation requires a directory resource")
        args["path"] = str(target)
        action = adapter.prepare(replace(call, arguments=args), context)
        return replace(
            action,
            execution_arguments={**args, "resourceId": resource_id, "relative": relative},
            authorization_arguments={**action.authorization_arguments, "resourceId": resource_id},
        )

    async def execute(
        action: AuthorizedToolAction, context: AuthorizedToolContext,
    ) -> AgentToolResult[Any]:
        args = dict(action.execution_arguments)
        resource_id = args.pop("resourceId")
        relative = args.pop("relative")
        access = get_access()
        ref, target = access.resolve_host(resource_id, relative)
        binding = context.operation_bindings.get(binding_key)
        if str(target) != args["path"] or action.execution_profile is None or binding is None:
            raise PermissionError("Session resource authority changed")
        profile = action.execution_profile
        bounds = EffectiveExecutionProfile(
            readable_roots=(ref.path,),
            writable_roots=(ref.path,) if writes else (),
        )

        def current() -> EffectiveExecutionProfile:
            access.resolve_host(resource_id, relative)
            return constrain_execution_profile(profile, bounds)

        operations = CodingWorkspaceOperations(ref.path, cast(ToolOperations, binding), current(), current)
        scoped = create_tool_definition(operation, options=ToolsOptions(operations=operations))
        assert isinstance(scoped.execution, AuthorizedExecution)
        return await scoped.execution.handler(replace(action, execution_arguments=args), context)

    schema = dict(base.parameters)
    fields = dict(schema["properties"])
    fields["resourceId"] = {"type": "string", "description": "Host resource ID returned by session_files."}
    if "path" in fields:
        fields["path"] = {"type": "string", "description": "Relative path inside the directory. Use '.' for the root or an individual file."}
    schema["properties"] = fields
    schema["required"] = ["resourceId", *schema.get("required", [])]
    return ToolDefinition(
        name=name,
        label=f"Session resource · {base.label}",
        description=f"{base.description} Use a Host reference ID and a relative path.",
        parameters=schema,
        execution=AuthorizedExecution(CallableToolActionAdapter(prepare), execute),
        execution_mode=base.execution_mode,
        operation_binding_key=binding_key,
    )
