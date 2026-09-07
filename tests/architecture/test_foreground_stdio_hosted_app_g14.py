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
            assert imported.partition(".")[0] != "subprocess"
            if path != ROOT / "local.py":
                assert imported.partition(".")[0] != "socket"
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


def test_G14_BOUNDARIES_foreground_lifetime_is_an_exact_optional_apphost_edge() -> None:
    foreground = Path("src/loushang/apphost/foreground.py")
    imports = _imports(foreground)
    allowed = {
        "loushang.apphost.application",
        "loushang.apphost.continuity",
        "loushang.appserver.connection",
        "loushang.appserver.framing",
    }
    assert (
        imports
        - {
            item
            for item in imports
            if item.partition(".")[0] in sys.stdlib_module_names
        }
        == allowed
    )
    for name in ("__init__", "_ownership", "catalog", "contracts", "router", "runtime"):
        assert "loushang.apphost.foreground" not in _imports(
            Path(f"src/loushang/apphost/{name}.py")
        )
    source = foreground.read_text()
    for forbidden in ("subprocess", "os.environ", "getcwd", "Path(", "retire("):
        assert forbidden not in source


def test_G14_BOUNDARIES_only_explicit_product_command_composes_native_stdio() -> None:
    command = Path("src/loushang/coding/cli/hosted.py")
    imports = _imports(command)
    assert "loushang.apphost.foreground" in imports
    assert "loushang.appserver.stdio" in imports
    assert "loushang.appservice.continuity_file" in imports
    assert "loushang.coding.hosted_session" in imports
    for default in (
        "src/loushang/coding/cli/__main__.py",
        "src/loushang/coding/ui/cli.py",
        "src/loushang/coding/__init__.py",
    ):
        assert "loushang.coding.cli.hosted" not in _imports(Path(default))
    for path in Path("src/loushang/harnesstui/mux").rglob("*.py"):
        imports = _imports(path)
        assert not any(
            item.startswith(
                ("loushang.coding", "loushang.apphost", "loushang.appservice")
            )
            for item in imports
        )
