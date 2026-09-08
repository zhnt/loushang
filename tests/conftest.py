from __future__ import annotations

from pathlib import Path

import pytest

_HOST_RUNTIME_MARKER = "requires_host_runtime"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("loushang")
    group.addoption(
        "--g17-installed-evidence",
        action="store_true",
        default=False,
        help="explicitly activate the dedicated G17 wheel-only acceptance selector",
    )
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
    if not config.getoption("--g17-installed-evidence"):
        selector = Path(__file__).parent / "coding/test_hosted_installed_evidence.py"
        deselected = [item for item in items if item.path == selector]
        if deselected:
            items[:] = [item for item in items if item.path != selector]
            config.hook.pytest_deselected(items=deselected)
    if not config.getoption("--skip-host-runtime"):
        return

    skip_host_runtime = pytest.mark.skip(
        reason="requires host runtime; rerun without --skip-host-runtime outside the sandbox"
    )
    for item in items:
        if _HOST_RUNTIME_MARKER in item.keywords:
            item.add_marker(skip_host_runtime)
