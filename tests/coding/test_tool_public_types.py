from __future__ import annotations

import importlib
from importlib import resources
from typing import is_typeddict

import pytest


def test_workspace_tool_types_are_owned_by_harness() -> None:
    from loushang.harness.tools.core import ToolDefinition, tool
    from loushang.harness.tools.workspace.bash import BashToolDetails, BashToolInput
    from loushang.harness.tools.workspace.edit import EditToolDetails, EditToolInput
    from loushang.harness.tools.workspace.find import FindToolDetails, FindToolInput
    from loushang.harness.tools.workspace.grep import GrepToolDetails, GrepToolInput
    from loushang.harness.tools.workspace.ls import LsToolDetails, LsToolInput
    from loushang.harness.tools.workspace.read import ReadToolDetails, ReadToolInput
    from loushang.harness.tools.workspace.write import WriteToolDetails, WriteToolInput

    for typed_dict in (
        BashToolDetails,
        BashToolInput,
        EditToolDetails,
        EditToolInput,
        FindToolDetails,
        FindToolInput,
        GrepToolDetails,
        GrepToolInput,
        LsToolDetails,
        LsToolInput,
        ReadToolDetails,
        ReadToolInput,
        WriteToolDetails,
        WriteToolInput,
    ):
        assert is_typeddict(typed_dict)
    assert ToolDefinition is not None
    assert tool is not None


def test_coding_exports_only_its_tool_pack_choices() -> None:
    import loushang.coding as coding
    from loushang.coding.tool_pack import (
        CODING_BUILTIN_TOOL_NAMES,
        CODING_BUILTIN_TOOL_PACK,
        CODING_TOOL_NAMES,
        create_coding_tool_definition,
    )

    assert CODING_TOOL_NAMES == ("read", "bash", "edit", "write")
    assert CODING_BUILTIN_TOOL_NAMES == (
        "bash",
        "read",
        "ls",
        "find",
        "grep",
        "write",
        "edit",
    )
    assert CODING_BUILTIN_TOOL_PACK.name == "coding.builtin"
    assert "coding workspace" in create_coding_tool_definition("read").description
    assert "ToolDefinition" not in coding.__all__
    assert "create_tool_definition" not in coding.__all__


def test_legacy_coding_tool_facade_is_not_importable() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loushang.coding.tools")


def test_loushang_package_declares_typed_sdk_surface() -> None:
    assert resources.files("loushang").joinpath("py.typed").is_file()
