from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path


def test_import_loushang_tui_does_not_import_legacy_rendering_libraries() -> None:
    _drop_modules_with_prefix("loushang.tui")
    for module_name in ("prompt_toolkit", "rich", "pygments"):
        sys.modules.pop(module_name, None)

    tui_module = importlib.import_module("loushang.tui")

    assert "prompt_toolkit" not in sys.modules
    assert "rich" not in sys.modules
    assert "pygments" not in sys.modules
    assert tui_module.MarkdownRenderer.__module__ == "loushang.tui.markdown.renderer"

    content_module = importlib.import_module("loushang.tui.content")
    markdown_module = importlib.import_module("loushang.tui.markdown")
    assert content_module.MarkdownRenderer is tui_module.MarkdownRenderer
    assert markdown_module.MarkdownRenderer is tui_module.MarkdownRenderer
    assert "rich" not in sys.modules
    assert "pygments" not in sys.modules


def test_pyproject_declares_markdown_it_py_as_direct_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.lower().startswith("markdown-it-py") for dependency in dependencies)


def _drop_modules_with_prefix(prefix: str) -> None:
    for module_name in tuple(sys.modules):
        if module_name == prefix or module_name.startswith(f"{prefix}."):
            sys.modules.pop(module_name, None)
