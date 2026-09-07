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


def test_G16_BOUNDARIES_native_record_is_one_optional_stdlib_component() -> None:
    root = Path("src/loushang/appserver")
    budgets = {
        "local_record.py": 200, "_local_record_values.py": 180,
        "_local_record_files.py": 300, "_posix_local_record.py": 130,
        "_windows_local_record.py": 380,
    }
    assert sum(len((root / name).read_text().splitlines()) for name in budgets) <= 1100
    for name, limit in budgets.items():
        text = (root / name).read_text()
        assert len(text.splitlines()) <= limit
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                assert all(alias.name.partition(".")[0] in sys.stdlib_module_names
                           for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level or node.module.partition(".")[0] in sys.stdlib_module_names
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == "import_module"):
                assert isinstance(node.args[0], ast.Constant)
                assert node.args[0].value in {"fcntl", "msvcrt"}
        assert "loushang.hosting" not in text
        assert "os.environ" not in text and "getenv(" not in text
        assert "Path.home(" not in text and "Path.cwd(" not in text
    for facade in (
        "src/loushang/appserver/__init__.py", "src/loushang/appserver/framing.py",
        "src/loushang/apphost/foreground.py", "src/loushang/coding/cli/hosted.py",
        "src/loushang/coding/cli/__main__.py", "src/loushang/coding/ui/cli.py",
    ):
        assert "local_record" not in Path(facade).read_text()


def test_G16_BOUNDARIES_native_io_is_confined_to_explicit_local_adapter() -> None:
    from loushang.appserver.connection import AppServerConnectionV1
    from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
    from loushang.appserver.remote_client import StdioAppClientV1

    root = Path("src/loushang/appserver")
    source = (root / "local.py").read_text()
    assert len(source.splitlines()) <= 450
    assert len((root / "_local_peer.py").read_text().splitlines()) <= 240
    assert '_LOOPBACK = "127.0.0.1"' in source
    assert "MAX_LOCAL_CONNECTIONS = 8" in source
    assert "MAX_LOCAL_APP_CONNECTIONS = 7" in source
    assert "MAX_LOCAL_AUTHENTICATING = 8" in source
    assert "SO_EXCLUSIVEADDRUSE" in source
    assert "start_serving=False" in source
    assert "reuse_port=True" not in source
    for path in root.rglob("*.py"):
        if path == root / "local.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"start_server", "open_connection", "sock_connect", "create_server", "create_connection"}
    assert set(inspect.signature(StdioAppClientV1).parameters) == {"stream", "phase_timeout"}
    assert inspect.signature(AppServerConnectionV1).parameters["profile"].default is AppConnectionProfileV1.STDIO
    for name in (
        "src/loushang/appserver/__init__.py", "src/loushang/apphost/foreground.py",
        "src/loushang/coding/cli/hosted.py", "src/loushang/coding/cli/__main__.py",
        "src/loushang/coding/ui/cli.py",
    ):
        assert "LocalAppServerV1" not in Path(name).read_text()
