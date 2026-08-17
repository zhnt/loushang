from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

FOUNDATION_ROOT = Path("src/loushang/foundation")
CANONICAL_OBSERVABILITY_ROOT = FOUNDATION_ROOT / "observability"
RETIRED_NAMESPACES = ("loushang.observability", "loushang.protocol")


def test_foundation_uses_only_stdlib_and_relative_imports() -> None:
    failures: list[str] = []
    for path in FOUNDATION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root not in sys.stdlib_module_names:
                        failures.append(f"{path.as_posix()} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue
                root = node.module.split(".", 1)[0]
                if root not in sys.stdlib_module_names:
                    failures.append(f"{path.as_posix()} imports {node.module}")

    assert failures == []


def test_foundation_json_import_does_not_load_observability() -> None:
    source_root = str(Path("src").resolve())
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (source_root, environment.get("PYTHONPATH", ""))
        if value
    )
    command = (
        "import sys; import loushang.foundation.json; "
        "assert not any(name == 'loushang.foundation.observability' or "
        "name.startswith('loushang.foundation.observability.') "
        "for name in sys.modules)"
    )

    subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        cwd=Path.cwd(),
        env=environment,
    )


def test_retired_foundation_namespaces_are_absent() -> None:
    for path in (
        Path("src/loushang/protocol"),
        Path("src/loushang/observability"),
    ):
        assert list(path.glob("*.py")) == []


def test_repository_does_not_import_retired_foundation_namespaces() -> None:
    offenders = [
        f"{path.as_posix()} imports {imported}"
        for root in ("src", "tests", "examples", "scripts", "scenarios")
        for path in sorted(Path(root).rglob("*.py"))
        for imported in _absolute_imports(path)
        if imported.startswith(RETIRED_NAMESPACES)
    ]

    assert offenders == []


def test_canonical_observability_has_no_migration_modules() -> None:
    assert {path.name for path in CANONICAL_OBSERVABILITY_ROOT.glob("*.py")} == {
        "__init__.py",
        "_router.py",
        "_time.py",
        "context.py",
        "debug_sink.py",
        "identity.py",
        "logger.py",
        "problem_text.py",
        "projection.py",
        "records.py",
        "runtime.py",
        "trace_sink.py",
    }


def test_canonical_observability_router_does_not_depend_on_concrete_sinks() -> None:
    router_imports = _relative_import_targets(
        CANONICAL_OBSERVABILITY_ROOT / "_router.py"
    )
    assert router_imports.isdisjoint(
        {"debug_sink", "logger", "runtime", "trace_sink"}
    )

    for module_name in ("debug_sink", "trace_sink"):
        sink_imports = _relative_import_targets(
            CANONICAL_OBSERVABILITY_ROOT / f"{module_name}.py"
        )
        assert "records" in sink_imports
        assert "_router" not in sink_imports


def _relative_import_targets(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level
    }


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports
