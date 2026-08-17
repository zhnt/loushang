from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.harness.extensions.api import ExtensionContributionAPI
from loushang.harness.extensions.dispatch import ExtensionDispatcher
from loushang.harness.extensions.loader import ExtensionLoader
from loushang.harness.extensions.registry import resolve_extension_registry
from loushang.harness.extensions.resources import ExtensionResourceRuntime
from loushang.harness.extensions.runtime import ExtensionRuntime
from loushang.harness.extensions.types import (
    ExtensionPolicyDecision,
    LoadedExtension,
    RegisteredCommand,
    RegisteredFlag,
    RegisteredShortcut,
)
from loushang.harness.resources.types import ExtensionDescriptor, ResourceBundle
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution


def test_extension_runtime_composes_standard_contributions(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompts" / "review.md"
    prompt_path.parent.mkdir()
    prompt_path.write_text("Review carefully", encoding="utf-8")
    contexts: list[tuple[str, str | None]] = []

    async def command_handler(arguments: str, context: object) -> None:
        del arguments, context

    async def complete(prefix: str) -> list[object]:
        return [f"{prefix}-result"]

    def transform_input(event: object, context: object) -> dict[str, object]:
        del context
        return {"action": "transform", "text": f"{event.text} transformed"}

    def discover(bundle: ResourceBundle, context: object) -> dict[str, object]:
        del bundle, context
        return {"promptPaths": [prompt_path]}

    extension = LoadedExtension(
        name="shared",
        source_path=tmp_path / "extension.py",
        hooks={
            "input": [transform_input],
            "resources_discover": [discover],
        },
        commands={
            "inspect": RegisteredCommand(
                name="inspect",
                handler=command_handler,
                get_argument_completions=complete,
            )
        },
        flags={"plan": RegisteredFlag(name="plan", type="boolean", default=False)},
        message_renderers={"progress": lambda message, options, context: message},
    )
    runtime = ExtensionRuntime(
        [extension],
        context_factory=lambda cwd, loaded: (
            contexts.append((cwd, loaded.name if loaded is not None else None))
            or {"cwd": cwd}
        ),
    )

    assert runtime.get_command("inspect") is not None
    assert asyncio.run(runtime.get_command_argument_completions("inspect", "in")) == [
        "in-result"
    ]
    assert runtime.get_flag_value("plan") is False
    runtime.set_flag_value("plan", True)
    assert runtime.get_flag_values() == {"plan": True}
    assert runtime.get_message_renderer("progress") is not None
    assert runtime.list_message_renderers()[0]["extensionName"] == "shared"

    input_result = asyncio.run(runtime.emit_input("start", cwd=str(tmp_path)))
    resource_bundle = runtime.discover_resources(ResourceBundle(cwd=tmp_path))

    assert input_result.text == "start transformed"
    assert [(prompt.name, prompt.text) for prompt in resource_bundle.prompts] == [
        ("review", "Review carefully")
    ]
    assert contexts == [
        (str(tmp_path), "shared"),
        (str(tmp_path), None),
    ]
    assert runtime.get_diagnostic_snapshot()["total"] == 0
    assert runtime.list_extensions()[0]["runtimeName"] == "shared"


def test_extension_runtime_validates_and_applies_flag_values(tmp_path: Path) -> None:
    extension = LoadedExtension(
        name="shared",
        source_path=tmp_path / "extension.py",
        flags={
            "plan": RegisteredFlag(name="plan", type="boolean", default=False),
            "request-id": RegisteredFlag(name="request-id", type="string"),
        },
    )
    runtime = ExtensionRuntime(
        [extension],
        context_factory=lambda cwd, loaded: {"cwd": cwd, "extension": loaded},
    )

    diagnostics = runtime.apply_flag_values(
        {
            "--plan": True,
            "request-id": "request-1",
            "unknown": True,
        }
    )

    assert runtime.get_flag_values() == {
        "plan": True,
        "request-id": "request-1",
    }
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "unknown_extension_flag"
    ]


def test_extension_runtime_rejects_non_string_string_flag(tmp_path: Path) -> None:
    extension = LoadedExtension(
        name="shared",
        source_path=tmp_path / "extension.py",
        flags={
            "request-id": RegisteredFlag(name="request-id", type="string"),
        },
    )
    runtime = ExtensionRuntime(
        [extension],
        context_factory=lambda cwd, loaded: {"cwd": cwd, "extension": loaded},
    )

    diagnostics = runtime.apply_flag_values({"request-id": True})

    assert runtime.get_flag_values() == {}
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "extension_flag_value_required"
    ]


def test_extension_runtime_contains_completion_errors(tmp_path: Path) -> None:
    errors: list[tuple[str, str, str]] = []

    async def command_handler(arguments: str, context: object) -> None:
        del arguments, context

    def broken_completion(prefix: str) -> list[object]:
        del prefix
        raise RuntimeError("completion failed")

    extension = LoadedExtension(
        name="shared",
        source_path=tmp_path / "extension.py",
        commands={
            "inspect": RegisteredCommand(
                name="inspect",
                handler=command_handler,
                get_argument_completions=broken_completion,
            )
        },
    )
    runtime = ExtensionRuntime(
        [extension],
        context_factory=lambda cwd, loaded: {"cwd": cwd, "extension": loaded},
        runtime_error_handler=lambda extension, event, error: errors.append(
            (extension.name, event, str(error))
        ),
    )

    assert (
        asyncio.run(runtime.get_command_argument_completions("inspect", "in")) is None
    )
    assert errors == [("shared", "command_argument_completions", "completion failed")]
    assert [diagnostic.code for diagnostic in runtime.get_diagnostics()] == [
        "extension_command_argument_completions_failed"
    ]


def test_contribution_api_builds_product_neutral_extension() -> None:
    async def command_handler(arguments: str, context: object) -> None:
        del arguments, context

    api = ExtensionContributionAPI(
        name="shared",
        source_path=Path("/tmp/shared.py"),
    )
    api.on("agent_start", lambda event, context: None)
    api.register_command("inspect", handler=command_handler)
    api.register_flag("verbose", type="boolean", default=False)

    extension = api.build_loaded_extension()

    assert extension.name == "shared"
    assert list(extension.hooks) == ["agent_start"]
    assert list(extension.commands) == ["inspect"]
    assert extension.flags["verbose"].default is False


def test_loaded_extension_preserves_legacy_positional_field_order() -> None:
    async def execute(
        tool_call_id: str,
        arguments: dict[str, object],
        signal: object | None,
        on_update: object | None,
    ) -> object:
        del tool_call_id, arguments, signal, on_update
        return object()

    tool = ToolDefinition(
        name="lookup",
        label="Lookup",
        description="Lookup",
        parameters={},
        execution=direct_execution(execute),  # type: ignore[arg-type]
    )

    def hook(event: object, context: object) -> None:
        del event, context

    extension = LoadedExtension(
        "legacy",
        Path("/tmp/legacy.py"),
        None,
        "filesystem",
        "project_local",
        "project",
        None,
        {"context": [hook]},
        [tool],
    )

    assert extension.hooks == {"context": [hook]}
    assert extension.tool_definitions == [tool]
    assert extension.handler_registrations == []
    assert extension.control_contributions == []


def test_loader_executes_register_api_without_coding_runtime(tmp_path: Path) -> None:
    entry_path = tmp_path / "extension.py"
    entry_path.write_text(
        """
async def _inspect(arguments, context):
    return None


def register(api):
    api.on("agent_start", lambda event, context: None)
    api.register_command("inspect", handler=_inspect)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    descriptor = ExtensionDescriptor(
        name="shared",
        source_path=entry_path,
        entry_path=entry_path,
    )

    loader = ExtensionLoader()
    extension = loader.load_extension(descriptor)

    assert extension is not None
    assert extension.api is not None
    assert list(extension.commands) == ["inspect"]
    assert extension.policy is not None
    assert extension.policy.active
    assert loader.get_diagnostics() == []


def test_loader_adapts_legacy_hooks_without_product_configuration(
    tmp_path: Path,
) -> None:
    entry_path = tmp_path / "legacy.py"
    entry_path.write_text(
        """
class LegacyExtension:
    def agent_start(self, event):
        return None


EXTENSION = LegacyExtension()
""".strip()
        + "\n",
        encoding="utf-8",
    )

    extension = ExtensionLoader().load_extension(
        ExtensionDescriptor(
            name="legacy",
            source_path=entry_path,
            entry_path=entry_path,
        )
    )

    assert extension is not None
    assert list(extension.hooks) == ["agent_start"]


def test_registry_resolves_contributions_and_preserves_first_wins() -> None:
    async def command_handler(arguments: str, context: object) -> None:
        del arguments, context

    async def execute(
        tool_call_id: str,
        arguments: dict[str, object],
        signal: object | None,
        on_update: object | None,
    ) -> object:
        del tool_call_id, arguments, signal, on_update
        return object()

    first = LoadedExtension(
        name="first",
        source_path=Path("/tmp/first.py"),
        commands={
            "inspect": RegisteredCommand(name="inspect", handler=command_handler)
        },
        flags={
            "verbose": RegisteredFlag(name="verbose", type="boolean", default=False)
        },
        tool_definitions=[
            ToolDefinition(
                name="lookup",
                label="Lookup",
                description="Lookup data",
                parameters={},
                execution=direct_execution(execute),  # type: ignore[arg-type]
            )
        ],
    )
    second = LoadedExtension(
        name="second",
        source_path=Path("/tmp/second.py"),
        commands={
            "inspect": RegisteredCommand(name="inspect", handler=command_handler)
        },
        flags={"verbose": RegisteredFlag(name="verbose", type="boolean", default=True)},
        tool_definitions=list(first.tool_definitions),
    )

    registry = resolve_extension_registry([first, second])

    assert [command.invocation_name for command in registry.commands] == [
        "inspect:1",
        "inspect:2",
    ]
    assert [flag.extension_name for flag in registry.flags] == ["first"]
    assert registry.flag_defaults == {"verbose": False}
    assert [tool.extension_name for tool in registry.tools] == ["first"]
    assert [diagnostic.code for diagnostic in registry.diagnostics] == [
        "duplicate_extension_tool",
        "duplicate_extension_flag",
    ]


def test_registry_excludes_every_surface_from_inactive_extensions() -> None:
    async def command_handler(arguments: str, context: object) -> None:
        del arguments, context

    async def execute(
        tool_call_id: str,
        arguments: dict[str, object],
        signal: object | None,
        on_update: object | None,
    ) -> object:
        del tool_call_id, arguments, signal, on_update
        return object()

    inactive = LoadedExtension(
        name="inactive",
        source_path=Path("/tmp/inactive.py"),
        commands={"deploy": RegisteredCommand(name="deploy", handler=command_handler)},
        flags={
            "verbose": RegisteredFlag(
                name="verbose",
                type="boolean",
                default=True,
            )
        },
        shortcuts={
            "ctrl+d": RegisteredShortcut(
                shortcut="ctrl+d",
                handler=lambda context: context,
            )
        },
        tool_definitions=[
            ToolDefinition(
                name="deploy",
                label="Deploy",
                description="Deploy",
                parameters={},
                execution=direct_execution(execute),  # type: ignore[arg-type]
            )
        ],
        policy=ExtensionPolicyDecision(enabled=False),
    )

    registry = resolve_extension_registry([inactive])

    assert registry.commands == ()
    assert registry.flags == ()
    assert registry.shortcuts == ()
    assert registry.tools == ()
    assert registry.flag_defaults == {}
    assert registry.diagnostics == ()


def test_dispatcher_preserves_order_and_contains_failures() -> None:
    calls: list[str] = []
    errors: list[tuple[str, str]] = []

    def broken(event: object, context: object) -> None:
        del event, context
        calls.append("broken")
        raise RuntimeError("boom")

    async def succeeding(event: object, context: object) -> str:
        del event, context
        calls.append("succeeding")
        return "handled"

    extensions = [
        LoadedExtension(
            name="broken",
            source_path=Path("/tmp/broken.py"),
            hooks={"agent_start": [broken]},
        ),
        LoadedExtension(
            name="succeeding",
            source_path=Path("/tmp/succeeding.py"),
            hooks={"agent_start": [succeeding]},
        ),
    ]
    diagnostics = []
    dispatcher = ExtensionDispatcher(
        extensions,
        context_factory=lambda extension: {"extension": extension.name},
        diagnostics=diagnostics,
        runtime_error_handler=lambda extension, event, error: errors.append(
            (extension.name, event)
        ),
    )

    results = asyncio.run(dispatcher.dispatch("agent_start", object()))

    assert results == ("handled",)
    assert calls == ["broken", "succeeding"]
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "extension_agent_start_failed"
    ]
    assert errors == [("broken", "agent_start")]


def test_dispatcher_reduces_input_transformations_in_order() -> None:
    def first(event: object, context: object) -> dict[str, object]:
        del context
        return {"action": "transform", "text": f"{event.text} first"}

    async def second(event: object, context: object) -> dict[str, object]:
        del context
        return {"action": "transform", "text": f"{event.text} second"}

    extension = LoadedExtension(
        name="input",
        source_path=Path("/tmp/input.py"),
        hooks={"input": [first, second]},
    )
    diagnostics = []
    dispatcher = ExtensionDispatcher(
        [extension],
        context_factory=lambda loaded: loaded.name,
        diagnostics=diagnostics,
    )

    result = asyncio.run(dispatcher.dispatch_input("start"))

    assert result.action == "transform"
    assert result.text == "start first second"
    assert diagnostics == []


def test_resource_runtime_normalizes_extension_paths(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompts" / "review.md"
    prompt_path.parent.mkdir()
    prompt_path.write_text("Review carefully", encoding="utf-8")

    def discover(bundle: ResourceBundle, context: object) -> dict[str, object]:
        del bundle, context
        return {"promptPaths": [prompt_path]}

    extension = LoadedExtension(
        name="resources",
        source_path=tmp_path / "extension.py",
        hooks={"resources_discover": [discover]},
    )
    diagnostics = []
    runtime = ExtensionResourceRuntime([extension], diagnostics=diagnostics)

    bundle = runtime.discover(
        ResourceBundle(cwd=tmp_path),
        context={"cwd": str(tmp_path)},
    )

    assert [(prompt.name, prompt.text) for prompt in bundle.prompts] == [
        ("review", "Review carefully")
    ]
    assert diagnostics == []
