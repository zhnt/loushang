from __future__ import annotations

import asyncio
import inspect

from loushang.agent.types import AgentToolResult
from loushang.ai.types import TextPart
from loushang.harness.tools import ToolContext, direct_tool, tool
from loushang.harness.tools.workspace.wrapper import wrap_tool_definition


def _provider(*, tool_call_id: str) -> ToolContext:
    return ToolContext(tool_call_id=tool_call_id, cwd="/tmp/project")


@tool()
async def greet(name: str) -> str:
    """Say hello."""
    return f"hello {name}"


@tool(
    name="salute",
    label="Salute",
    description="Offer a formal greeting.",
    prompt_snippet="- salute: Offer a formal greeting.",
    prompt_guidelines=["Keep it brief.", "Use a friendly tone."],
    schema_overrides={},
)
async def salute(name: str) -> str:
    """Offer a formal greeting."""
    return f"salute {name}"


@tool()
async def show_context(path: str, ctx: ToolContext) -> str:
    return f"{ctx.cwd}:{path}"


@tool()
async def explicit_result(name: str) -> AgentToolResult[dict[str, str]]:
    return AgentToolResult(
        content=[TextPart(type="text", text=name)], details={"name": name}
    )


@tool()
async def plain_value(name: str) -> dict[str, str]:
    return {"name": name}


@tool()
async def unsupported_value() -> object:
    return object()


@tool()
async def fail_loudly(name: str) -> str:
    raise ValueError(f"boom: {name}")


def test_direct_tool_compiles_decorated_tool_metadata() -> None:
    definition = direct_tool(greet)
    assert definition.name == "greet"
    assert definition.description == "Say hello."
    assert definition.label == "Greet"


def test_direct_tool_preserves_explicit_decorated_metadata() -> None:
    definition = direct_tool(salute)
    spec = getattr(salute, "__loushang_tool_spec__")
    assert definition.name == "salute"
    assert definition.label == "Salute"
    assert definition.description == "Offer a formal greeting."
    assert definition.prompt_snippet == "- salute: Offer a formal greeting."
    assert definition.prompt_guidelines == ("Keep it brief.", "Use a friendly tone.")
    assert spec.schema_overrides == {}
    assert definition.parameters["properties"]["name"]["type"] == "string"


def test_authoring_private_spec_attr_is_direct_import_only() -> None:
    import loushang.harness.tools.core as authoring
    from loushang.harness.tools.core import _TOOL_SPEC_ATTR

    assert _TOOL_SPEC_ATTR == "__loushang_tool_spec__"
    assert (
        not hasattr(authoring, "__all__") or "_TOOL_SPEC_ATTR" not in authoring.__all__
    )


def test_decorated_tool_spec_remains_callable() -> None:
    assert asyncio.run(salute("Ada")) == "salute Ada"


def test_decorated_tool_receives_tool_context_from_provider() -> None:
    definition = direct_tool(show_context)
    tool = wrap_tool_definition(definition, context_provider=_provider)

    result = asyncio.run(tool.execute("call-1", {"path": "README.md"}))

    assert result.content[0].text == "/tmp/project:README.md"
    assert result.details == "/tmp/project:README.md"
    assert "ctx" not in definition.parameters["properties"]


def test_decorated_tool_passes_through_explicit_agent_tool_result() -> None:
    definition = direct_tool(explicit_result)
    tool = wrap_tool_definition(definition, context_provider=_provider)

    result = asyncio.run(tool.execute("call-2", {"name": "Ada"}))

    assert result.content[0].text == "Ada"
    assert result.details == {"name": "Ada"}


def test_decorated_tool_normalizes_plain_return_values() -> None:
    definition = direct_tool(plain_value)
    tool = wrap_tool_definition(definition, context_provider=_provider)

    result = asyncio.run(tool.execute("call-3", {"name": "Ada"}))

    assert result.content[0].text == '{"name": "Ada"}'
    assert result.details == {"name": "Ada"}


def test_decorated_tool_rejects_unsupported_plain_return_values() -> None:
    definition = direct_tool(unsupported_value)
    tool = wrap_tool_definition(definition, context_provider=_provider)

    try:
        asyncio.run(tool.execute("call-4", {}))
    except TypeError as exc:
        assert "unsupported plain return type" in str(exc)
    else:
        raise AssertionError(
            "expected unsupported plain return type to raise TypeError"
        )


def test_decorated_tool_exceptions_propagate_to_agent_loop_boundary() -> None:
    definition = direct_tool(fail_loudly)
    tool = wrap_tool_definition(definition, context_provider=_provider)

    try:
        asyncio.run(tool.execute("call-5", {"name": "demo"}))
    except ValueError as exc:
        assert str(exc) == "boom: demo"
    else:
        raise AssertionError("expected decorated tool exception to propagate")


def test_tool_decorator_preserves_function_introspection_metadata() -> None:
    signature = inspect.signature(greet)
    assert greet.__name__ == "greet"
    assert greet.__doc__ == "Say hello."
    assert list(signature.parameters) == ["name"]
    assert inspect.iscoroutinefunction(greet) is True
