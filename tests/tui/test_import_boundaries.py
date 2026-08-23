from __future__ import annotations

import ast
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def test_import_loushang_tui_does_not_import_legacy_rendering_libraries() -> None:
    _assert_loushang_tui_import_boundary_in_subprocess()


def test_loushang_tui_does_not_export_legacy_settings_primitives() -> None:
    import loushang.tui as tui

    removed_names = (
        "SettingItem",
        "SettingsList",
        "SettingsListRenderer",
        "SettingsSurface",
    )

    for name in removed_names:
        assert not hasattr(tui, name)
        assert name not in tui.__all__


def test_loushang_tui_public_models_are_not_owned_by_compat_module() -> None:
    import loushang.tui as tui

    expected_modules = {
        "CompletionItem": "loushang.tui.completion_models",
        "CompletionSuggestions": "loushang.tui.completion_models",
        "CompletionApplication": "loushang.tui.completion_models",
        "CompletionProvider": "loushang.tui.completion_models",
        "CommandPaletteItem": "loushang.tui.command_palette",
        "CommandPalette": "loushang.tui.command_palette",
        "InfoPanel": "loushang.tui.info_panel",
        "PlaybackScenarioResult": "loushang.tui.playback_suite",
        "PlaybackScenarioSpec": "loushang.tui.playback_suite",
        "PlaybackSuite": "loushang.tui.playback_suite",
        "format_terminal_diagnostics": "loushang.tui.terminal_diagnostics",
    }

    assert not Path("src/loushang/tui/compat.py").exists()
    for name, module_name in expected_modules.items():
        assert getattr(tui, name).__module__ == module_name


def test_tui_input_router_defines_no_conversation_state_or_submit_mode() -> None:
    from dataclasses import fields

    import loushang.tui.input as input_module
    from loushang.tui import InputRouter

    router_fields = {router_field.name for router_field in fields(InputRouter)}

    assert "running" not in router_fields
    assert "steering_supported" not in router_fields
    assert not hasattr(input_module, "SubmitMode")


def test_tui_package_does_not_construct_conversation_input_intents() -> None:
    violations: list[str] = []
    for source_path in sorted(Path("src/loushang/tui").rglob("*.py")):
        violations.extend(
            _conversation_intent_producer_violations(
                source_path.read_text(encoding="utf-8"),
                filename=str(source_path),
            )
        )

    assert violations == []


def test_tui_and_harnesstui_production_use_parameterized_input_intent_annotations() -> None:
    violations: list[str] = []
    for source_path in _production_input_paths():
        violations.extend(
            _bare_input_intent_reference_violations(
                source_path.read_text(encoding="utf-8"),
                filename=str(source_path),
            )
        )

    assert violations == []


def test_bare_input_intent_checker_distinguishes_types_from_runtime_uses() -> None:
    rejected_sources = (
        "def handle(intent: InputIntent) -> InputIntent: ...",
        "Handler = Callable[[InputIntent], None]",
    )
    allowed_sources = (
        "def handle(intent: InputIntent[str]) -> InputIntent[str]: ...",
        'InputIntent(kind="surface_close")',
        "isinstance(intent, InputIntent)",
    )

    for source in rejected_sources:
        assert _bare_input_intent_reference_violations(source), source
    for source in allowed_sources:
        assert _bare_input_intent_reference_violations(source) == (), source


def test_input_intent_kind_is_only_a_compatibility_alias_in_input_module() -> None:
    input_source = Path("src/loushang/tui/input.py").read_text(encoding="utf-8")
    assert "InputIntentKind: TypeAlias = str" in input_source

    violations: list[str] = []
    for source_path in _production_input_paths():
        if source_path == Path("src/loushang/tui/input.py"):
            continue
        violations.extend(
            _input_intent_kind_reference_violations(
                source_path.read_text(encoding="utf-8"),
                filename=str(source_path),
            )
        )

    assert violations == []


def test_conversation_intent_producer_checker_rejects_direct_constants() -> None:
    call_forms = (
        'InputIntent("steer")',
        'InputIntent(kind="steer")',
        'InputIntent("follow_up")',
        'InputIntent(kind="follow_up")',
        'InputIntent("command", "", "edit_last_queued_prompt")',
        'InputIntent(kind="command", note="edit_last_queued_prompt")',
    )

    for call_form in call_forms:
        for expression in (call_form, f"tui.{call_form}"):
            assert _conversation_intent_producer_violations(expression), expression


def test_conversation_intent_producer_checker_allows_generic_and_dynamic_forms() -> None:
    allowed_sources = (
        'InputIntent("abort")',
        'tui.InputIntent(kind="abort")',
        "InputIntent(kind=kind, note=note)",
        'tui.InputIntent(kind=kind, note="edit_last_queued_prompt")',
        "InputIntentKind: TypeAlias = str",
        '"InputIntent(kind=\\"steer\\")"',
    )

    for source in allowed_sources:
        assert _conversation_intent_producer_violations(source) == (), source


def test_import_boundary_check_does_not_replace_loaded_tui_classes() -> None:
    import loushang.coding.presentation.tui.plain as renderer
    import loushang.harnesstui.commands.presentation as command_presentation
    from loushang.tui import CompletionProvider
    from loushang.tui.render import MarkdownBlock

    original_completion_provider = command_presentation.CompletionProvider
    original_markdown_block = renderer.MarkdownBlock
    assert original_completion_provider is CompletionProvider
    assert original_markdown_block is MarkdownBlock

    _assert_loushang_tui_import_boundary_in_subprocess()

    from loushang.tui import CompletionProvider as current_completion_provider
    from loushang.tui.render import MarkdownBlock as current_markdown_block

    assert original_completion_provider is current_completion_provider
    assert original_markdown_block is current_markdown_block


def _assert_loushang_tui_import_boundary_in_subprocess() -> None:
    result = _run_python_import_boundary_check(
        """
import importlib
import sys

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
"""
    )

    assert result.returncode == 0, result.stderr


def test_import_loushang_tui_without_posix_terminal_modules() -> None:
    result = _run_python_without_posix_terminal_modules(
        """
import loushang.tui

print(loushang.tui.TerminalInputMode.__name__)
"""
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "TerminalInputMode"


def test_terminal_input_mode_is_noop_without_posix_terminal_modules() -> None:
    result = _run_python_without_posix_terminal_modules(
        """
from io import StringIO

from loushang.tui.terminal_input import TerminalInputMode


class TtyInput:
    def fileno(self):
        return 42

    def isatty(self):
        return True


stdout = StringIO()
with TerminalInputMode(stdin=TtyInput(), stdout=stdout):
    pass

print(repr(stdout.getvalue()))
"""
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "''"


def test_pyproject_declares_markdown_it_py_as_direct_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.lower().startswith("markdown-it-py") for dependency in dependencies)


def test_pyproject_does_not_declare_legacy_tui_dependencies() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    normalized_dependencies = tuple(dependency.lower() for dependency in dependencies)

    assert not any(dependency.startswith("prompt-toolkit") for dependency in normalized_dependencies)
    assert not any(dependency.startswith("rich") for dependency in normalized_dependencies)


def _run_python_import_boundary_check(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path.cwd() / "src")
    env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_python_without_posix_terminal_modules(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path.cwd() / "src")
    env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    block_posix_modules = """
import importlib.abc
import sys


class BlockPosixTerminalModules(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"termios", "tty"}:
            raise ModuleNotFoundError(f"No module named {fullname!r}")
        return None


sys.meta_path.insert(0, BlockPosixTerminalModules())
"""
    return subprocess.run(
        [sys.executable, "-c", f"{block_posix_modules}\n{script}"],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _conversation_intent_producer_violations(
    source: str,
    *,
    filename: str = "<source>",
) -> tuple[str, ...]:
    violations: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call) or not _is_input_intent_constructor(node.func):
            continue
        kind = _literal_call_argument(node, position=0, keyword="kind")
        note = _literal_call_argument(node, position=2, keyword="note")
        if kind in {"steer", "follow_up"}:
            violations.append(f"{filename}:{node.lineno}: forbidden {kind} InputIntent producer")
        elif kind == "command" and note == "edit_last_queued_prompt":
            violations.append(f"{filename}:{node.lineno}: forbidden queued-edit InputIntent producer")
    return tuple(violations)


def _production_input_paths() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for root in (Path("src/loushang/tui"), Path("src/loushang/harnesstui"))
            for path in root.rglob("*.py")
        )
    )


def _bare_input_intent_reference_violations(
    source: str,
    *,
    filename: str = "<source>",
) -> tuple[str, ...]:
    tree = ast.parse(source, filename=filename)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        if not _is_input_intent_constructor(node):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Call) and parent.func is node:
            continue
        if isinstance(parent, ast.Subscript) and parent.value is node:
            continue
        if (
            isinstance(parent, ast.Call)
            and isinstance(parent.func, ast.Name)
            and parent.func.id == "isinstance"
            and len(parent.args) >= 2
            and parent.args[1] is node
        ):
            continue
        violations.append(f"{filename}:{node.lineno}: bare InputIntent type reference")
    return tuple(violations)


def _input_intent_kind_reference_violations(
    source: str,
    *,
    filename: str = "<source>",
) -> tuple[str, ...]:
    violations: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.ImportFrom) and any(
            alias.name == "InputIntentKind" for alias in node.names
        ):
            violations.append(f"{filename}:{node.lineno}: InputIntentKind import")
        elif isinstance(node, ast.Name) and node.id == "InputIntentKind":
            violations.append(f"{filename}:{node.lineno}: InputIntentKind reference")
        elif isinstance(node, ast.Attribute) and node.attr == "InputIntentKind":
            violations.append(f"{filename}:{node.lineno}: InputIntentKind reference")
    return tuple(violations)


def _is_input_intent_constructor(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "InputIntent") or (
        isinstance(node, ast.Attribute) and node.attr == "InputIntent"
    )


def _literal_call_argument(
    call: ast.Call,
    *,
    position: int,
    keyword: str,
) -> str | None:
    if len(call.args) > position:
        return _string_literal(call.args[position])
    for item in call.keywords:
        if item.arg == keyword:
            return _string_literal(item.value)
    return None


def _string_literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
