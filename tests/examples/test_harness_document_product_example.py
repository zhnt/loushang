from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_example() -> ModuleType:
    path = Path("examples/harness/document_product.py")
    spec = importlib.util.spec_from_file_location(
        "examples_harness_document_product",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_document_reference_product_uses_public_harness_gateway(
    tmp_path: Path,
) -> None:
    module = _load_example()

    result = asyncio.run(module.run_example(tmp_path))

    assert result == {
        "word_count": 5,
        "exported": "brief.txt",
        "content": "Harness keeps Product policy thin.",
        "audit_events": [
            "tool_action_frozen",
            "tool_policy_evaluated",
            "tool_approval_requested",
            "tool_approval_resolved",
            "tool_execution_started",
            "tool_execution_completed",
        ],
        "policy_code": "document_export",
    }
    assert "loushang.coding" not in Path(
        "examples/harness/document_product.py"
    ).read_text(encoding="utf-8")


def test_document_reference_product_denies_export_without_an_injected_reviewer(
    tmp_path: Path,
) -> None:
    module = _load_example()
    product = module.DocumentProduct(tmp_path)

    with pytest.raises(PermissionError, match="Confirm document export"):
        asyncio.run(product.export("denied.txt", "not exported"))

    assert not (tmp_path / "denied.txt").exists()
