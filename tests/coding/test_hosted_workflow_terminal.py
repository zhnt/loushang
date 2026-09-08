"""G17 native local discovery and legacy paths; wheel provenance is separate."""

from __future__ import annotations

import asyncio

from loushang.ai.types import UserMessage
from loushang.coding.hosted_catalog import CodingHostedSessionCatalogV1
from loushang.coding.session_manager import SessionManager
from tests.tui.terminal_process_support import selected_backend_name

from .test_hosted_discovery import _create
from .test_hosted_local import _local_launch
from .test_mux_product_terminal import _command, _product, _see, _terminal
from .test_mux_product_terminal import (
    test_G16_PRODUCT_TERMINAL_two_muxes_approval_detach_reattach_and_interrupt as _interaction,
)


def test_G17_TERMINAL_PRODUCT_discovery_profile_keeps_turn_approval_and_interrupt(
    tmp_path, record_testsuite_property
):
    # Real Product/session/tool execution, with only synthetic model transport;
    # this library seam complements, never replaces, the shipped CLI cases.
    _interaction(tmp_path, record_testsuite_property, discovery=True)


def test_G17_TERMINAL_LOCAL_discovery_picker_detach_reattach_and_stop(
    tmp_path, record_testsuite_property
):
    root = tmp_path.resolve()
    scope = _local_launch(root).application.scopes[0]
    historical = "G17 local canonical history selected"

    async def seed():
        await _create(CodingHostedSessionCatalogV1((scope,)), scope)
        (path,) = scope.session_dir.glob("*.jsonl")
        manager = await SessionManager.open(path)
        try:
            await manager.append_message(UserMessage(role="user", content=historical, timestamp=1.0))
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(seed())
    record_testsuite_property("terminal_backend", selected_backend_name())
    with _product(root, installed=True, discovery=True) as (server, environment):
        _command(root, environment, "create", "discovery")
        with _terminal(root, environment, "discovery") as driver:
            driver.write("/sessions cwd\r")
            _see(driver, "select a saved Session")
            driver.write("\r")
            _see(driver, historical)
            driver.write("\x02d")
            assert driver.wait(timeout=15) == 0, driver.diagnostics
        assert server.poll() is None, "local detach must preserve the application"
        listed = _command(root, environment, "list")
        assert listed["muxes"][0]["members"] == 1
        with _terminal(root, environment, "discovery") as reattached:
            _see(reattached, historical)
            reattached.write("\x02d")
            assert reattached.wait(timeout=15) == 0, reattached.diagnostics
        assert server.poll() is None
        _command(root, environment, "stop")
        assert server.wait(timeout=20) == 0
    assert len(tuple(scope.session_dir.glob("*.jsonl"))) == 1


def test_G17_TERMINAL_LEGACY_local_picker_unavailable_keeps_existing_commands(
    tmp_path, record_testsuite_property
):
    root = tmp_path.resolve()
    record_testsuite_property("terminal_backend", selected_backend_name())
    # No discovery flag: the pre-G17 local protocol and operations stay usable.
    with _product(root, installed=True) as (server, environment):
        _command(root, environment, "create", "legacy")
        with _terminal(root, environment, "legacy") as driver:
            driver.write("/sessions cwd\r")
            _see(driver, "discovery_unavailable")
            checkpoint = len(driver.raw_output)
            driver.write("\x1b")
            _see(driver, "cwd / user_home: /new", after=checkpoint)
            driver.write("/new cwd Legacy member\r")
            _see(driver, "*1")
            driver.write("\x02d")
            assert driver.wait(timeout=15) == 0, driver.diagnostics
        assert server.poll() is None
        assert _command(root, environment, "list")["muxes"][0]["members"] == 1
        _command(root, environment, "stop")
        assert server.wait(timeout=20) == 0
