from __future__ import annotations

import ast
from pathlib import Path


def _imports_package(path: Path, package: str) -> bool:
    root, leaf = package.rsplit(".", 1)
    source = path.read_text(encoding="utf-8")
    if package not in source and f"from {root} import" not in source:
        return False
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = (node.module or "",)
            if node.module == root and any(
                alias.name == leaf for alias in node.names
            ):
                return True
        else:
            continue
        if any(name == package or name.startswith(package + ".") for name in names):
            return True
    return False


def test_work_package_has_no_coding_compatibility_module() -> None:
    assert not Path("src/loushang/work/coding.py").exists()


def test_work_standard_projection_does_not_depend_on_coding() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/loushang/work").glob("*.py")
    )

    assert "loushang.coding" not in sources
    assert "loushang.harnesswork.integrations.agent_session" in sources
    assert "loushang.coding" not in Path(
        "src/loushang/harnesswork/integrations/agent_session.py"
    ).read_text(encoding="utf-8")


def test_work_runtime_is_product_neutral_and_harness_does_not_import_work() -> None:
    work_runtime = Path("src/loushang/harnesswork/runtime.py").read_text(
        encoding="utf-8"
    )
    work_runtime_facade = Path("src/loushang/work/runtime.py").read_text(
        encoding="utf-8"
    )
    session_runtime = Path(
        "src/loushang/harnesswork/integrations/session.py"
    ).read_text(encoding="utf-8")
    session_runtime_facade = Path("src/loushang/work/session.py").read_text(
        encoding="utf-8"
    )
    coding_binding = Path("src/loushang/coding/adapters/harnesswork.py").read_text(
        encoding="utf-8"
    )
    assert "loushang.coding" not in work_runtime
    assert "loushang.agent" not in work_runtime
    assert "class WorkRuntime" in work_runtime
    assert "WorkRunStarted" in work_runtime
    assert "WorkRunCompleted" in work_runtime
    assert "from loushang.harnesswork.runtime import" in work_runtime_facade

    assert "loushang.coding" not in session_runtime
    assert "loushang.agent" not in session_runtime
    assert "class SessionWorkRuntime" in session_runtime
    assert "WorkRuntime(" in session_runtime
    assert "loushang.harnesswork.integrations.session" in session_runtime_facade
    assert "class CodingWorkRuntime" not in coding_binding
    assert "class CodingWorkShell" not in coding_binding
    assert "SessionWorkProfile(" in coding_binding

    for source in Path("src/loushang/harness").rglob("*.py"):
        assert not _imports_package(source, "loushang.work"), source
        assert not _imports_package(source, "loushang.harnesswork"), source
    assert not Path("src/loushang/harness/work").exists()


def test_channel_adapter_delegates_operation_lifecycle_to_work_runtime() -> None:
    shared_source = Path("src/loushang/channel/adapters/harnesswork.py").read_text(
        encoding="utf-8"
    )
    legacy_source = Path(
        "src/loushang/channel/adapters/session_work.py"
    ).read_text(encoding="utf-8")
    coding_source = Path("src/loushang/coding/adapters/harnesswork.py").read_text(
        encoding="utf-8"
    )

    assert "class SessionWorkChannelPort" in shared_source
    assert "SessionWorkRuntime" in shared_source
    assert "self._session.prompt(" not in shared_source
    assert "self._session.abort(" not in shared_source
    assert "self._active_operation_id" not in shared_source
    assert "self._tasks" not in shared_source
    assert "loushang.channel.adapters.harnesswork" in legacy_source
    assert "CODING_WORK_CHANNEL_PROFILE" in coding_source
    assert "run_session_work_channel_host" in coding_source
    assert not Path("src/loushang/work/channel.py").exists()
    assert "loushang.channel" not in "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/loushang/work").glob("*.py")
    )
    assert not tuple(Path("src/loushang/coding/mode").glob("*.py"))
