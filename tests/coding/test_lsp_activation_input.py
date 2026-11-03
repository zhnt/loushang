"""Observe input and timer frames during real deferred LSP admission."""

from __future__ import annotations

import asyncio
import re
import threading
from contextlib import nullcontext
from io import StringIO

import pytest

from loushang.agent import synthetic_model_transport
from loushang.ai.model import Capabilities, Model
from loushang.coding import bootstrap
from loushang.coding.control import ControlConfig, SettingsManager
from loushang.coding.session_manager import SessionManager
from loushang.coding.ui.product_binding import (
    build_coding_ui_controller,
    build_screen_coding_action_host,
)
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.tui import strip_control_sequences
from loushang.tui.transcript import WorkedDividerRecord
from tests.coding.tui_support.scenario_binding import run_coding_test_screen


@pytest.mark.usefixtures("legacy_coding_route")
@pytest.mark.parametrize("interrupt", [False, True])
def test_lsp_admission_keeps_input_timer_and_escape_live(
    tmp_path, monkeypatch, interrupt: bool
) -> None:
    async def scenario() -> None:
        @synthetic_model_transport
        async def reject_model(*_args, **_kwargs):
            raise AssertionError("tool activation must not call a model")

        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path), persist=False
        )
        session = bootstrap.create_agent_session(
            session_manager=manager,
            model=Model(
                id="offline",
                name="Offline",
                provider="faux",
                endpoint="anthropic-messages",
                capabilities=Capabilities(input=("text",), context_window=128000),
            ),
            stream_fn=reject_model,
            services=bootstrap.create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.arch": "disabled"})
                )
            ),
        )
        await session.prepare_model_call_runtime()
        slot = session._deferred_lsp_slot
        assert slot is not None and slot.state == "dormant"
        loop = asyncio.get_running_loop()
        ui_thread = threading.get_ident()
        assembling, first_frame, second_frame, stopping, edited, settled = (
            asyncio.Event() for _ in range(6)
        )
        release = threading.Event()
        prepare = bootstrap.prepare_coding_capability_plugin_composition

        def controlled_prepare(*args, **kwargs):
            assert threading.get_ident() != ui_thread
            loop.call_soon_threadsafe(assembling.set)
            if not release.wait(10):
                raise AssertionError("input loop did not release LSP preparation")
            return prepare(*args, **kwargs)

        monkeypatch.setattr(
            bootstrap,
            "prepare_coding_capability_plugin_composition",
            controlled_prepare,
        )
        clock = [10.0]

        class Output(StringIO):
            def write(self, text):
                written = super().write(text)
                visible = strip_control_sequences(self.getvalue())
                elapsed = {
                    float(value)
                    for value in re.findall(r"Working (\d+\.\d+)s", visible)
                }
                if "› draft" in visible and 1.0 in elapsed:
                    first_frame.set()
                if 2.0 in elapsed:
                    second_frame.set()
                if "Stopping…" in visible:
                    stopping.set()
                if "› draft after Esc" in visible:
                    edited.set()
                if "Worked for" in visible:
                    settled.set()
                return written

        app = ScreenCodingTuiApp(
            model_label="offline",
            cwd=str(tmp_path),
            branch=None,
            session_label="lsp-admission",
            now=lambda: clock[0],
        )
        output = Output()
        host = build_screen_coding_action_host(
            presenter=app,
            controller=build_coding_ui_controller(session=session),
            stderr=StringIO(),
            verbose=False,
        )
        queue = asyncio.Queue()

        async def read(_stdin):
            return await queue.get()

        async def drive():
            queue.put_nowait("/tools on document_outline\r")
            await assembling.wait()
            assert slot.state == "activating"
            clock[0] = 11.0
            queue.put_nowait("draft")
            await first_frame.wait()
            clock[0] = 12.0
            app.request_render("product")
            await second_frame.wait()
            assert slot.state == "activating" and not release.is_set()
            if interrupt:
                queue.put_nowait("\x1b")
                await stopping.wait()
                queue.put_nowait(" after Esc")
                await edited.wait()
                assert slot.state == "activating" and not release.is_set()
            release.set()
            await settled.wait()
            queue.put_nowait("\x15/quit\r")

        driver = asyncio.create_task(drive())
        try:
            async with asyncio.timeout(20):
                assert (
                    await run_coding_test_screen(
                        app=app,
                        stdin=StringIO(),
                        stdout=output,
                        action_host=host,
                        should_exit=lambda text: text == "/quit",
                        terminal_mode_factory=lambda *_args: nullcontext(),
                        input_chunk_reader=read,
                    )
                    == 0
                )
                await driver
            assert slot.state == "active"
            assert not app.state.running
            assert (
                len(
                    [
                        record
                        for record in app.state.records
                        if isinstance(record, WorkedDividerRecord)
                    ]
                )
                == 1
            )
        except BaseException:
            print(
                "LSP input phases:",
                {
                    "assembling": assembling.is_set(),
                    "first_frame": first_frame.is_set(),
                    "second_frame": second_frame.is_set(),
                    "stopping": stopping.is_set(),
                    "edited": edited.is_set(),
                    "settled": settled.is_set(),
                    "slot": slot.state,
                    "composer": app.composer.value,
                },
            )
            print(strip_control_sequences(output.getvalue())[-4000:])
            raise
        finally:
            release.set()
            driver.cancel()
            await asyncio.gather(driver, return_exceptions=True)
            await session.dispose()
        assert slot.state == "closed"

    asyncio.run(scenario())
