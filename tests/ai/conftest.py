from __future__ import annotations

import os

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.bootstrap import register_builtin_api_adapters


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.getenv("LOUSHANG_AI_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="set LOUSHANG_AI_LIVE=1 to run live AI tests")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def _isolate_default_api_registry():
    registry = get_default_api_registry()
    registry.clear_api_adapters()
    register_builtin_api_adapters(registry)
    yield
    registry.clear_api_adapters()
    register_builtin_api_adapters(registry)
