from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path


def test_G16_BOUNDARIES_owned_execution_stays_private_and_off_default_routes() -> None:
    source = Path("src/loushang/appservice/_operations.py")
    tree = ast.parse(source.read_text())
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert {name for name in imports if name.startswith("loushang.")} == {
        "loushang.appserver.protocol"
    }
    for facade in (
        "src/loushang/appservice/__init__.py",
        "src/loushang/coding/cli/__main__.py",
        "src/loushang/coding/ui/cli.py",
    ):
        path = Path(facade)
        package = path.parent.relative_to("src").parts
        imported: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = package[: len(package) - node.level + 1] if node.level else ()
                module = ".".join((*base, node.module or "")).rstrip(".")
                imported.add(module)
                imported.update(f"{module}.{alias.name}" for alias in node.names)
        assert not any(
            name == "loushang.appservice._operations"
            or name.startswith("loushang.appservice._operations.")
            for name in imported
        )
    assert len(source.read_text().splitlines()) <= 250


def test_G16_BOUNDARIES_optional_scopes_have_separate_reviewable_budgets() -> None:
    for name, limit in (("client_scope.py", 600), ("_scope_interactions.py", 220)):
        source = Path("src/loushang/appservice") / name
        assert len(source.read_text().splitlines()) <= limit
        imports = {
            node.module for node in ast.walk(ast.parse(source.read_text()))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert {name for name in imports if name.startswith("loushang.")} == {
            "loushang.appserver.protocol"
        }
    # Explicit optional construction is not activation of G14 or a CLI.
    for name in (
        "src/loushang/appservice/__init__.py",
        "src/loushang/apphost/foreground.py",
        "src/loushang/coding/cli/hosted.py",
    ):
        assert "client_scope" not in Path(name).read_text()


def test_G16_BOUNDARIES_authentication_is_stdlib_only_and_off_default_routes() -> None:
    from loushang.appserver.framing import AppFramedStreamV1

    source = Path("src/loushang/appserver/local_auth.py")
    assert len(source.read_text().splitlines()) <= 350
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            assert all(alias.name.partition(".")[0] in sys.stdlib_module_names
                       for alias in node.names)
        if isinstance(node, ast.ImportFrom) and not node.level:
            assert node.module.partition(".")[0] in sys.stdlib_module_names
    assert set(inspect.signature(AppFramedStreamV1).parameters) == {
        "transport", "io_timeout"
    }
    for name in (
        "src/loushang/appserver/__init__.py",
        "src/loushang/appserver/framing.py",
        "src/loushang/appserver/protocol/stdio_profile.py",
        "src/loushang/apphost/foreground.py",
        "src/loushang/coding/cli/hosted.py",
    ):
        assert "local_auth" not in Path(name).read_text()
