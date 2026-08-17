# Harness Tool Authoring

Use the Product-neutral authoring surface for every model-visible tool:

```python
from loushang.harness.tools import (
    authorized_tool,
    direct_tool,
    tool,
)
```

The Registry accepts only a completed `ToolDefinition`. Choose exactly one
execution route when defining the tool; do not call Policy or Approval from the
handler.

The complete versions of the three examples below live in
[`examples/harness/tool_authoring.py`](../../../../../examples/harness/tool_authoring.py)
and run without a model or network connection:

```bash
uv run python examples/harness/tool_authoring.py
```

[`examples/harness/document_product.py`](../../../../../examples/harness/document_product.py)
is a minimal executable non-Coding Product. It owns a word-count/export tool
set and Product-specific approval wording while reusing Harness authoring,
Policy, Approval, Gateway, and audit. The adapter defaults to headless deny;
the deterministic example runner explicitly injects an allow reviewer:

```bash
uv run python examples/harness/document_product.py
```

## Pure In-Process Tool

Use `direct_tool` when the handler consumes no common protected resource:

```python
from loushang.harness.tools import direct_tool, tool


@tool()
async def add(left: int, right: int) -> int:
    return left + right


definition = direct_tool(add)
registry.register_tool(definition)
```

A direct handler does not receive the authorization Gateway, process execution,
or generic filesystem/network services.

## Filesystem Tool

Use `authorized_tool` and a common action adapter when the operation touches a
protected resource:

```python
from pathlib import Path

from loushang.harness.tools import (
    FilesystemActionAdapter,
    ToolContext,
    authorized_tool,
    tool,
)


@tool()
async def save_note(path: str, content: str, context: ToolContext) -> str:
    target = Path(context.cwd or ".") / path
    target.write_text(content, encoding="utf-8")
    return str(target)


definition = authorized_tool(
    save_note,
    action=FilesystemActionAdapter(
        "write",
        authorization_fields=("content",),
    ),
)
registry.register_tool(definition)
```

The adapter resolves and freezes the authority-bearing path. The session-owned
Host sends that immutable action through Policy, Approval, execution-profile
revalidation, and audit before invoking the handler.

## Custom Action Adapter

Implement `ToolActionAdapter` only when the common adapters cannot describe the
tool input. Reuse a common typed effect whenever it represents the protected
resource:

```python
from dataclasses import dataclass

from loushang.ai.types import ToolCall
from loushang.harness.effects import PublicationEffect
from loushang.harness.tools import authorized_tool, tool
from loushang.harness.tools.execution import (
    PreparedToolAction,
    ToolCallContext,
)


@dataclass(frozen=True, slots=True)
class DeployActionAdapter:
    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        target = call.arguments.get("target")
        if not isinstance(target, str) or not target:
            raise TypeError("target must be a non-empty string")
        effect = PublicationEffect(target)
        return PreparedToolAction(
            tool_name=call.name,
            authorization_arguments={"target": target},
            execution_arguments=call.arguments,
            cwd=context.cwd,
            effects=(effect,),
        )


@tool()
async def deploy(target: str) -> str:
    return f"deployed {target}"


definition = authorized_tool(deploy, action=DeployActionAdapter())
registry.register_tool(definition)
```

Keep the adapter deterministic: validate input, resolve authority-bearing
resources, and return immutable action data. It must not perform the operation.

## Selection Checklist

```text
Does the handler consume a common protected resource?
  no  -> direct_tool(...)
  yes -> authorized_tool(..., action=...)
```

- Use `FilesystemActionAdapter`, `ProcessActionAdapter`,
  `NetworkActionAdapter`, or `PublicationActionAdapter` first.
- Put effect-changing values in `authorization_arguments`.
- Keep the operation in the handler; keep Policy and Approval in Harness.
- Pass only completed definitions to `ToolRegistry.register_tool`.
- Do not expand `AuthorizedToolContext` with another optional service. A new
  live protected-resource port requires a separate boundary decision based on
  demonstrated consumers.
