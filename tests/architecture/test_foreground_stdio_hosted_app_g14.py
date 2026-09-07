from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path("src/loushang/appserver")


def _imports(path: Path) -> set[str]:
    package = path.parent.relative_to("src").parts
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else ()
            imported.add(".".join((*base, node.module or "")))
    return imported


def test_G14_BOUNDARIES_connection_has_no_reverse_semantic_or_process_dependency() -> (
    None
):
    for path in ROOT.rglob("*.py"):
        for imported in _imports(path):
            assert (
                imported.startswith("loushang.appserver.")
                or imported.partition(".")[0] in sys.stdlib_module_names
            ), (path, imported)
            assert imported.partition(".")[0] not in {"subprocess", "socket"}
    client_imports = _imports(ROOT / "remote_client.py")
    assert "loushang.appserver.connection" not in client_imports
    assert "loushang.appserver.dispatch" not in client_imports
    for path in (ROOT / "client.py", ROOT / "ports.py", ROOT / "__init__.py"):
        assert not _imports(path).intersection(
            {
                "loushang.appserver.connection",
                "loushang.appserver.stdio",
                "loushang.appserver.remote_client",
            }
        )


def test_G14_BOUNDARIES_dispatch_is_exhaustive_and_not_remote_reflection() -> None:
    from loushang.appserver.protocol import AppOperationV1

    tree = ast.parse((ROOT / "dispatch.py").read_text())
    arms = {
        node.value.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.MatchValue)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "AppOperationV1"
    }
    assert arms == {operation.name for operation in AppOperationV1}
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"getattr", "eval", "exec", "__import__"}
        for node in ast.walk(tree)
    )
