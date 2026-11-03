"""Deterministically partition collected pytest cases across CI jobs."""

from __future__ import annotations

import pytest
from shard_hash import shard_for_nodeid


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("loushang-ci-shard")
    group.addoption("--ci-shard-index", type=int)
    group.addoption("--ci-shard-count", type=int)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    index = config.getoption("ci_shard_index")
    count = config.getoption("ci_shard_count")
    if index is None and count is None:
        return
    if count is None or index is None or count < 1 or not 0 <= index < count:
        raise pytest.UsageError("invalid CI pytest shard index/count")
    selected = []
    deselected = []
    for item in items:
        (selected if shard_for_nodeid(item.nodeid, count) == index else deselected).append(item)
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
