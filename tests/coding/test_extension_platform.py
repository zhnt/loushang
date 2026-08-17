from __future__ import annotations

from types import SimpleNamespace


def test_extension_manifest_parser_accepts_capability_manifest(tmp_path) -> None:
    from loushang.harness.extensions.manifest import parse_extension_manifest

    manifest_path = tmp_path / "loushang-extension.toml"
    manifest_path.write_text(
        """
[extension]
id = "acme.review"
name = "Acme Review"
version = "0.1.0"
description = "Review helpers"

[permissions]
level = "standard"
capabilities = ["filesystem", "model"]

[[commands]]
name = "acme-review"
description = "Run review"

[[tools]]
name = "acme_lookup"
description = "Look up metadata"

[[hooks]]
event = "before_agent_start"
kind = "augment"
handler = "extension:before_agent_start"

[dependencies.python]
packages = ["acme-sdk>=0.3"]
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    result = parse_extension_manifest(manifest_path)

    assert result.manifest is not None
    assert result.diagnostics == []
    assert result.manifest.id == "acme.review"
    assert result.manifest.name == "Acme Review"
    assert result.manifest.permissions.level == "standard"
    assert result.manifest.permissions.capabilities == ("filesystem", "model")
    assert [command.name for command in result.manifest.commands] == ["acme-review"]
    assert [tool.name for tool in result.manifest.tools] == ["acme_lookup"]
    assert [(hook.event, hook.kind) for hook in result.manifest.hooks] == [
        ("before_agent_start", "augment")
    ]
    assert result.manifest.dependencies.python.packages == ("acme-sdk>=0.3",)


def test_extension_manifest_parser_normalizes_identifiers_and_rejects_blank_id(
    tmp_path,
) -> None:
    from loushang.harness.extensions.manifest import parse_extension_manifest

    manifest_path = tmp_path / "loushang-extension.toml"
    manifest_path.write_text(
        '[extension]\nid = "  acme.review  "\nname = "  Acme Review  "\n',
        encoding="utf-8",
    )

    normalized = parse_extension_manifest(manifest_path)

    assert normalized.manifest is not None
    assert normalized.manifest.id == "acme.review"
    assert normalized.manifest.name == "Acme Review"
    assert normalized.diagnostics == []

    manifest_path.write_text(
        '[extension]\nid = "   "\nname = "Acme Review"\n',
        encoding="utf-8",
    )

    blank = parse_extension_manifest(manifest_path)

    assert blank.manifest is None
    assert [diagnostic.code for diagnostic in blank.diagnostics] == [
        "missing_extension_manifest_id"
    ]


def test_extension_manifest_rejects_removed_provider_hooks(tmp_path) -> None:
    from loushang.harness.extensions.contributions import surfaces_from_loaded_extension
    from loushang.harness.extensions.manifest import parse_extension_manifest

    manifest_path = tmp_path / "loushang-extension.toml"
    manifest_path.write_text(
        """
[extension]
id = "bad.provider-hooks"
name = "Bad Provider Hooks"

[[hooks]]
event = "before_provider_request"
kind = "observe"

[[hooks]]
event = "after_provider_response"
kind = "observe"

[[hooks]]
event = "session_start"
kind = "observe"
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    result = parse_extension_manifest(manifest_path)

    assert result.manifest is not None
    assert [(hook.event, hook.kind) for hook in result.manifest.hooks] == [
        ("session_start", "observe")
    ]
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unsupported_extension_hook_event",
        "unsupported_extension_hook_event",
    ]
    assert [
        diagnostic.details["metadata"]["event"] for diagnostic in result.diagnostics
    ] == [
        "before_provider_request",
        "after_provider_response",
    ]
    surfaces = surfaces_from_loaded_extension(
        SimpleNamespace(
            manifest=result.manifest,
            source_path=manifest_path,
            hooks={},
            commands={},
            tool_definitions=(),
        )
    )
    assert [(surface.type, surface.name) for surface in surfaces] == [
        ("hook", "session_start")
    ]


def test_extension_loader_reports_removed_provider_hook_manifest(tmp_path) -> None:
    from loushang.harness.extensions.agent.loader import ExtensionLoader
    from loushang.harness.resources.types import ExtensionDescriptor

    extension_dir = tmp_path / "provider-hooks"
    extension_dir.mkdir()
    extension_file = extension_dir / "extension.py"
    extension_file.write_text("def register(api):\n    pass\n", encoding="utf-8")
    (extension_dir / "loushang-extension.toml").write_text(
        """
[extension]
id = "bad.provider-hooks"
name = "Bad Provider Hooks"

[[hooks]]
event = "before_provider_request"
kind = "observe"

[[hooks]]
event = "session_start"
kind = "observe"
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    loader = ExtensionLoader()
    loaded = loader.load_extensions(
        [
            ExtensionDescriptor(
                name="provider-hooks",
                source_path=extension_dir,
                entry_path=extension_file,
            )
        ]
    )

    assert len(loaded) == 1
    assert [diagnostic.code for diagnostic in loader.get_diagnostics()] == [
        "unsupported_extension_hook_event"
    ]
    assert sorted((surface.type, surface.name) for surface in loaded[0].surfaces) == [
        ("hook", "session_start")
    ]


def test_extension_manifest_parser_reports_invalid_input_without_throwing(
    tmp_path,
) -> None:
    from loushang.harness.extensions.manifest import parse_extension_manifest

    manifest_path = tmp_path / "loushang-extension.toml"
    manifest_path.write_text(
        """
[extension]
id = "bad.extension"
name = "Bad Extension"

[permissions]
level = "root"
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    result = parse_extension_manifest(manifest_path)

    assert result.manifest is None
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "invalid_extension_permission_level"
    ]
    assert result.diagnostics[0].source_path == manifest_path
    assert result.diagnostics[0].details["resource_type"] == "extension"


def test_extension_manifest_parser_keeps_manifest_for_partial_surface_declaration_errors(
    tmp_path,
) -> None:
    from loushang.harness.extensions.manifest import parse_extension_manifest

    manifest_path = tmp_path / "loushang-extension.toml"
    manifest_path.write_text(
        """
[extension]
id = "demo.partial"
name = "Demo Partial"

[[commands]]
description = "missing name"

[[tools]]
name = "valid_tool"
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    result = parse_extension_manifest(manifest_path)

    assert result.manifest is not None
    assert result.manifest.id == "demo.partial"
    assert result.manifest.commands == ()
    assert [tool.name for tool in result.manifest.tools] == ["valid_tool"]
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "missing_extension_command_name"
    ]


def test_extension_loader_attaches_manifest_policy_and_surface_snapshot(
    tmp_path,
) -> None:
    from loushang.harness.extensions.agent.loader import ExtensionLoader
    from loushang.harness.resources.types import ExtensionDescriptor

    extension_dir = tmp_path / "review"
    extension_dir.mkdir()
    extension_file = extension_dir / "extension.py"
    extension_file.write_text(
        """
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace import ToolDefinition


async def _execute_tool(tool_name, arguments, context, signal):
    return {"ok": True}


def register(api):
    api.on("session_start", lambda event, ctx: None)
    api.register_tool(
        ToolDefinition(
            name="runtime_lookup",
            label="Runtime Lookup",
            description="runtime tool",
            parameters={},
            execution=direct_execution(_execute_tool),
        )
    )
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    (extension_dir / "loushang-extension.toml").write_text(
        """
[extension]
id = "acme.review"
name = "Acme Review"

[permissions]
level = "standard"
capabilities = ["filesystem"]

[[commands]]
name = "acme-review"

[[tools]]
name = "manifest_lookup"

[[hooks]]
event = "before_agent_start"
kind = "augment"
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    loader = ExtensionLoader()
    loaded = loader.load_extensions(
        [
            ExtensionDescriptor(
                name="review",
                source_path=extension_dir,
                entry_path=extension_file,
            )
        ]
    )

    assert len(loaded) == 1
    extension = loaded[0]
    assert extension.name == "review"
    assert [tool.name for tool in extension.tool_definitions] == ["runtime_lookup"]
    assert extension.manifest is not None
    assert extension.manifest.id == "acme.review"
    assert extension.policy is not None
    assert extension.policy.permission_level == "standard"
    assert extension.policy.capabilities == ("filesystem",)
    assert sorted((surface.type, surface.name) for surface in extension.surfaces) == [
        ("command", "acme-review"),
        ("hook", "before_agent_start"),
        ("hook", "session_start"),
        ("tool", "manifest_lookup"),
        ("tool", "runtime_lookup"),
    ]
    assert extension.contributions == extension.surfaces
    assert loader.get_diagnostics() == []


def test_extension_runner_lists_extension_visibility_snapshot() -> None:
    from pathlib import Path

    from loushang.harness.diagnostics.types import DiagnosticDraft
    from loushang.harness.extensions.agent import (
        ExtensionManifest,
        ExtensionPermissionDeclaration,
        ExtensionPolicyDecision,
        ExtensionRunner,
        ExtensionSurfaceDescriptor,
        LoadedExtension,
    )

    manifest = ExtensionManifest(
        id="acme.review",
        name="Acme Review",
        version="0.1.0",
        description="Review helpers",
        permissions=ExtensionPermissionDeclaration(
            level="standard", capabilities=("filesystem",)
        ),
    )
    extension = LoadedExtension(
        name="review",
        source_path=Path("/tmp/project/extensions/review/extension.py"),
        manifest=manifest,
        policy=ExtensionPolicyDecision(
            permission_level="standard", capabilities=("filesystem",)
        ),
        contributions=[
            ExtensionSurfaceDescriptor(
                type="command",
                name="acme-review",
                extension_id="acme.review",
                source_path=Path("/tmp/project/extensions/review/extension.py"),
                metadata={"source": "manifest"},
            ),
            ExtensionSurfaceDescriptor(
                type="tool",
                name="review_lookup",
                extension_id="acme.review",
                source_path=Path("/tmp/project/extensions/review/extension.py"),
                metadata={"source": "runtime"},
            ),
        ],
        diagnostics=[
            DiagnosticDraft(
                code="missing_extension_hook_event",
                message="Extension manifest hook declaration requires an event.",
                source_path=Path(
                    "/tmp/project/extensions/review/loushang-extension.toml"
                ),
            )
        ],
    )

    snapshot = ExtensionRunner([extension]).list_extensions()

    assert snapshot == [
        {
            "id": "acme.review",
            "name": "Acme Review",
            "runtimeName": "review",
            "version": "0.1.0",
            "description": "Review helpers",
            "sourcePath": "/tmp/project/extensions/review/extension.py",
            "manifestPath": None,
            "enabled": True,
            "permissionLevel": "standard",
            "capabilities": ["filesystem"],
            "surfaces": [
                {
                    "type": "command",
                    "name": "acme-review",
                    "active": True,
                    "priority": 0,
                    "source": "manifest",
                    "sourcePath": "/tmp/project/extensions/review/extension.py",
                    "diagnostics": [],
                },
                {
                    "type": "tool",
                    "name": "review_lookup",
                    "active": True,
                    "priority": 0,
                    "source": "runtime",
                    "sourcePath": "/tmp/project/extensions/review/extension.py",
                    "diagnostics": [],
                },
            ],
            "contributions": [
                {
                    "type": "command",
                    "name": "acme-review",
                    "active": True,
                    "priority": 0,
                    "source": "manifest",
                    "sourcePath": "/tmp/project/extensions/review/extension.py",
                    "diagnostics": [],
                },
                {
                    "type": "tool",
                    "name": "review_lookup",
                    "active": True,
                    "priority": 0,
                    "source": "runtime",
                    "sourcePath": "/tmp/project/extensions/review/extension.py",
                    "diagnostics": [],
                },
            ],
            "diagnostics": [
                {
                    "code": "missing_extension_hook_event",
                    "message": "Extension manifest hook declaration requires an event.",
                    "sourcePath": "/tmp/project/extensions/review/loushang-extension.toml",
                    "resourceId": None,
                    "resourceType": None,
                    "sourceKind": None,
                    "metadata": {},
                }
            ],
        }
    ]


def test_extension_inventory_indexes_loaded_extension_surfaces(tmp_path) -> None:
    from pathlib import Path

    from loushang.harness.extensions.contributions import (
        ExtensionInventory,
        ExtensionSurfaceDescriptor,
    )
    from loushang.harness.extensions.types import LoadedExtension

    extension = LoadedExtension(
        name="review",
        source_path=Path("/tmp/review/extension.py"),
        contributions=[
            ExtensionSurfaceDescriptor(
                type="tool",
                name="lookup",
                extension_id="review",
                source_path=Path("/tmp/review/extension.py"),
            ),
            ExtensionSurfaceDescriptor(
                type="command",
                name="review",
                extension_id="review",
                source_path=Path("/tmp/review/extension.py"),
            ),
        ],
    )

    inventory = ExtensionInventory.from_extensions([extension])

    assert [surface.name for surface in inventory.by_type("tool")] == ["lookup"]
    assert [surface.name for surface in inventory.by_extension("review")] == [
        "lookup",
        "review",
    ]
    assert inventory.get("tool", "lookup").extension_id == "review"


def test_extension_inventory_does_not_silently_overwrite_duplicate_keys() -> None:
    from pathlib import Path

    import pytest

    from loushang.harness.extensions.contributions import (
        DuplicateExtensionSurfaceKeyError,
        ExtensionInventory,
        ExtensionSurfaceDescriptor,
    )

    first = ExtensionSurfaceDescriptor(
        type="command",
        name="review",
        extension_id="one",
        source_path=Path("/tmp/one.py"),
    )
    second = ExtensionSurfaceDescriptor(
        type="command",
        name="review",
        extension_id="two",
        source_path=Path("/tmp/two.py"),
    )

    inventory = ExtensionInventory()
    inventory.add(first)
    inventory.add(second)

    assert [
        surface.extension_id for surface in inventory.by_key("command", "review")
    ] == [
        "one",
        "two",
    ]
    with pytest.raises(DuplicateExtensionSurfaceKeyError):
        inventory.get("command", "review")
