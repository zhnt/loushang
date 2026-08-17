from __future__ import annotations

import pytest

_HOST_RUNTIME_MARKER = "requires_host_runtime"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("loushang")
    group.addoption(
        "--skip-host-runtime",
        action="store_true",
        default=False,
        help="skip tests that require host capabilities unavailable in a restricted sandbox",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if not config.getoption("--skip-host-runtime"):
        return

    skip_host_runtime = pytest.mark.skip(
        reason="requires host runtime; rerun without --skip-host-runtime outside the sandbox"
    )
    for item in items:
        if _HOST_RUNTIME_MARKER in item.keywords:
            item.add_marker(skip_host_runtime)
