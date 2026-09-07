from __future__ import annotations

import ast
from pathlib import Path


def test_G16_BOUNDARIES_owned_execution_stays_private_and_uncomposed() -> None:
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
