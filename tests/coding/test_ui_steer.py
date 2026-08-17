from __future__ import annotations

import asyncio


class _Lifecycle:
    active_id = 9


class _Renderer:
    def __init__(self) -> None:
        self.statuses: list[str] = []

    def render_status(self, text: str) -> None:
        self.statuses.append(text)


class _Controller:
    def __init__(self, result) -> None:
        self.result = result
        self.steers: list[str] = []

    async def steer(self, text: str):
        self.steers.append(text)
        return self.result


def test_steer_handler_sends_text_to_controller_and_traces() -> None:
    from loushang.harness.host.types import HostActionResult
    from loushang.harnesstui.conversation.control import SteerActionHandler

    controller = _Controller(HostActionResult(exit_code=3))
    renderer = _Renderer()
    traces: list[tuple[str, dict[str, object]]] = []

    handler = SteerActionHandler(
        lifecycle=_Lifecycle(),
        controller=controller,
        renderer=renderer,
        emit=lambda write, *, label: _emit(write),
        trace=lambda name, **data: traces.append((name, data)),
    )

    exit_code = asyncio.run(handler.steer("change tone"))

    assert exit_code == 3
    assert controller.steers == ["change tone"]
    assert renderer.statuses == []
    assert traces == [
        ("prompt.steer.start", {"active_run_id": 9}),
        ("prompt.steer.end", {"error_message": None, "exit_code": 3}),
    ]


def test_steer_handler_renders_controller_error() -> None:
    from loushang.harness.host.types import HostActionResult
    from loushang.harnesstui.conversation.control import SteerActionHandler

    controller = _Controller(
        HostActionResult(exit_code=2, error_message="steer failed")
    )
    renderer = _Renderer()
    emitted: list[str] = []

    async def emit(write, *, label: str) -> None:
        emitted.append(label)
        write()

    handler = SteerActionHandler(
        lifecycle=_Lifecycle(),
        controller=controller,
        renderer=renderer,
        emit=emit,
        trace=lambda _name, **_data: None,
    )

    exit_code = asyncio.run(handler.steer("change tone"))

    assert exit_code == 2
    assert controller.steers == ["change tone"]
    assert emitted == ["steer:error"]
    assert renderer.statuses == ["steer failed"]


async def _emit(write) -> None:
    write()
