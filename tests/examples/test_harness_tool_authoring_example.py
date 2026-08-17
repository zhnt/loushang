from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType


def _load_example() -> ModuleType:
    path = Path("examples/harness/tool_authoring.py")
    spec = importlib.util.spec_from_file_location(
        "examples_harness_tool_authoring",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_harness_tool_authoring_example_runs_all_three_routes(
    tmp_path: Path,
) -> None:
    module = _load_example()

    result = asyncio.run(module.run_example(tmp_path))

    assert result == {
        "add": 5,
        "note": str((tmp_path / "note.txt").resolve()),
        "note_content": "hello",
        "deploy": "deployed staging",
    }
