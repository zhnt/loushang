from __future__ import annotations

from pathlib import Path

from loushang.harness.extensions.commands import (
    list_extension_command_descriptors,
)
from loushang.harness.extensions.types import ResolvedCommand
from loushang.harness.resources.source import SourceInfo


async def _handle_command(_args: str, _context: object) -> None:
    return None


def test_extension_command_descriptors_preserve_conflict_and_provenance() -> None:
    descriptors = list_extension_command_descriptors(
        (
            ResolvedCommand(
                name="deploy",
                handler=_handle_command,
                description="Deploy the current revision",
                invocation_name="deploy:1",
                source_info=SourceInfo(
                    path=Path("/tmp/extensions/deploy.py"),
                    source="filesystem",
                    scope="project",
                    origin="top-level",
                ),
                extension_name="deploy-a",
            ),
            ResolvedCommand(
                name="inspect",
                handler=_handle_command,
                invocation_name="inspect",
                source_info=SourceInfo(
                    path=Path("/tmp/extensions/inspect.py"),
                    base_dir=Path("/tmp/extensions"),
                ),
                extension_name="inspect",
            ),
        )
    )

    assert [descriptor.name for descriptor in descriptors] == ["deploy:1", "inspect"]
    assert descriptors[0].conflict_group == "deploy"
    assert descriptors[0].source_info.path == "/tmp/extensions/deploy.py"
    assert descriptors[0].source_info.base_dir == "/tmp/extensions"
    assert descriptors[1].conflict_group is None
    assert descriptors[1].source_info.base_dir == "/tmp/extensions"


def test_extension_command_descriptor_projection_is_independent_of_coding() -> None:
    module_path = (
        Path(__file__).parents[3] / "src/loushang/harness/extensions/commands.py"
    )
    assert "loushang.coding" not in module_path.read_text(encoding="utf-8")
