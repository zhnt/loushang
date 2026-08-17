from __future__ import annotations


def test_extension_loader_supports_register_api_modules(tmp_path) -> None:
    from loushang.harness.extensions.agent.loader import ExtensionLoader
    from loushang.harness.resources.types import ExtensionDescriptor

    extension_file = tmp_path / "register_extension.py"
    extension_file.write_text(
        """
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace import ToolDefinition


async def _execute_tool(tool_name, arguments, context, signal):
    return {"tool_name": tool_name, "arguments": arguments}


def register(api):
    api.on("session_start", lambda event, ctx: None)
    api.register_tool(
        ToolDefinition(
            name="registered_tool",
            label="Registered Tool",
            description="tool from register(api)",
            parameters={},
            execution=direct_execution(_execute_tool),
        )
    )
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    loader = ExtensionLoader()
    loaded = loader.load_extensions(
        [
            ExtensionDescriptor(
                name="register_extension",
                source_path=extension_file,
                entry_path=extension_file,
            )
        ]
    )

    assert len(loaded) == 1
    assert loaded[0].name == "register_extension"
    assert "session_start" in loaded[0].hooks
    assert [tool.name for tool in loaded[0].tool_definitions] == ["registered_tool"]
    assert loader.get_diagnostics() == []


def test_extension_loader_keeps_build_extension_compatibility(tmp_path) -> None:
    from loushang.harness.extensions.agent.loader import ExtensionLoader
    from loushang.harness.resources.types import ExtensionDescriptor

    extension_file = tmp_path / "legacy_builder.py"
    extension_file.write_text(
        """
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace import ToolDefinition


async def _execute_tool(tool_name, arguments, context, signal):
    return {"tool_name": tool_name, "arguments": arguments}


class LegacyExtension:
    def session_start(self, session):
        return None

    def get_tools(self):
        return [
            ToolDefinition(
                name="legacy_tool",
                label="Legacy Tool",
                description="tool from build_extension()",
                parameters={},
                execution=direct_execution(_execute_tool),
            )
        ]


def build_extension():
    return LegacyExtension()
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    loader = ExtensionLoader()
    loaded = loader.load_extensions(
        [
            ExtensionDescriptor(
                name="legacy_builder",
                source_path=extension_file,
                entry_path=extension_file,
            )
        ]
    )

    assert len(loaded) == 1
    assert "session_start" in loaded[0].hooks
    assert [tool.name for tool in loaded[0].tool_definitions] == ["legacy_tool"]


def test_extension_loader_keeps_extension_object_compatibility(tmp_path) -> None:
    from loushang.harness.extensions.agent.loader import ExtensionLoader
    from loushang.harness.resources.types import ExtensionDescriptor

    extension_file = tmp_path / "legacy_object.py"
    extension_file.write_text(
        """
class LegacyObjectExtension:
    def session_shutdown(self, session):
        return None


EXTENSION = LegacyObjectExtension()
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    loader = ExtensionLoader()
    loaded = loader.load_extensions(
        [
            ExtensionDescriptor(
                name="legacy_object",
                source_path=extension_file,
                entry_path=extension_file,
            )
        ]
    )

    assert len(loaded) == 1
    assert "session_shutdown" in loaded[0].hooks


def test_extension_loader_records_invalid_export_diagnostics(tmp_path) -> None:
    from loushang.harness.extensions.agent.loader import ExtensionLoader
    from loushang.harness.resources.types import ExtensionDescriptor

    extension_file = tmp_path / "invalid.py"
    extension_file.write_text("VALUE = 1\n", encoding="utf-8")

    loader = ExtensionLoader()
    loaded = loader.load_extensions(
        [
            ExtensionDescriptor(
                name="invalid",
                source_path=extension_file,
                entry_path=extension_file,
            )
        ]
    )

    assert loaded == []
    assert [diagnostic.code for diagnostic in loader.get_diagnostics()] == [
        "invalid_extension_export"
    ]
