from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from loushang.harness.session import (
    SessionOperationAvailability,
    SessionOperationCapability,
    SessionOperationResolver,
    SessionOperationUnavailableError,
    SessionPromptRequest,
)

ResolverFactory = Callable[
    ["CurrentSessionSlot", SessionOperationAvailability | None],
    SessionOperationResolver,
]


class ContractControl:
    """Minimal control whose observations define the shared operation contract."""

    session_id = "contract-session"
    session_name = "Contract"
    pending_message_count = 0
    is_retrying = False
    is_compacting = False
    auto_retry_enabled = True
    auto_compaction_enabled = True

    def __init__(self) -> None:
        self.events: list[str] = []
        self.steering: list[str] = []
        self.follow_ups: list[str] = []
        self.abort_calls = 0
        self.clear_calls = 0
        self._idle = asyncio.Event()
        self._idle.set()

    async def prompt(self, text: str, images=None, **kwargs: object) -> None:
        del images
        self.events.append(f"prompt:{text}")
        callback = kwargs.get("preflight_result")
        if callable(callback):
            callback(True)

    async def wait_for_idle(self) -> None:
        self.events.append("wait_for_idle")
        await self._idle.wait()

    def steer(self, text: str, images=None) -> None:
        del images
        self.steering.append(text)

    def follow_up(self, text: str, images=None) -> None:
        del images
        self.follow_ups.append(text)

    def get_steering_messages(self) -> list[str]:
        return list(self.steering)

    def get_follow_up_messages(self) -> list[str]:
        return list(self.follow_ups)

    def clear_queue(self) -> dict[str, list[str]]:
        self.clear_calls += 1
        return {"steering": [], "follow_up": []}

    async def continue_run(self) -> None:
        return None

    def abort(self) -> bool:
        self.abort_calls += 1
        return True

    async def set_session_name(self, name: str | None) -> None:
        self.session_name = name

    def abort_retry(self) -> None:
        return None

    async def wait_for_retry(self) -> None:
        return None

    def set_auto_retry_enabled(self, enabled: bool) -> None:
        self.auto_retry_enabled = enabled

    def set_auto_compaction_enabled(self, enabled: bool) -> None:
        self.auto_compaction_enabled = enabled

    async def compact(self, custom_instructions: str | None = None) -> object:
        return {"instructions": custom_instructions}

    def abort_compaction(self) -> None:
        return None

    async def refresh_resources(self) -> None:
        return None

    def request_resource_refresh(self) -> None:
        return None

    def subscribe_runtime_events(self, listener):
        del listener
        return lambda: None


class CurrentSessionSlot:
    def __init__(self, control: ContractControl) -> None:
        self.current_session = SimpleNamespace(session_control=control)

    def get_current_session(self) -> object:
        return self.current_session

    def replace(self, control: ContractControl) -> None:
        self.current_session = SimpleNamespace(session_control=control)


class SessionOperationContract:
    """Reusable behavioral suite for every Product session-operation binding."""

    resolver_factory: ResolverFactory

    def _resolve(
        self,
        slot: CurrentSessionSlot,
        availability: SessionOperationAvailability | None = None,
    ) -> SessionOperationResolver:
        return self.resolver_factory(slot, availability)

    def test_prompt_is_a_settled_operation(self) -> None:
        async def scenario() -> None:
            control = ContractControl()
            control._idle.clear()
            resolve = self._resolve(CurrentSessionSlot(control))
            preflight: list[bool] = []

            pending = asyncio.create_task(
                resolve().prompt(
                    SessionPromptRequest("review", source="contract"),
                    on_preflight=preflight.append,
                )
            )
            await asyncio.sleep(0)

            assert not pending.done()
            assert control.events == ["prompt:review", "wait_for_idle"]
            assert preflight == [True]

            control._idle.set()
            await pending

        asyncio.run(scenario())

    def test_queue_and_abort_primitives_remain_distinct(self) -> None:
        control = ContractControl()
        operations = self._resolve(CurrentSessionSlot(control))()

        operations.steer("adjust")
        operations.follow_up("later")
        assert operations.abort_turn() is True

        assert control.steering == ["adjust"]
        assert control.follow_ups == ["later"]
        assert control.abort_calls == 1
        assert control.clear_calls == 0

    def test_resolver_rebinds_after_current_session_changes(self) -> None:
        first = ContractControl()
        first.session_id = "first"
        second = ContractControl()
        second.session_id = "second"
        slot = CurrentSessionSlot(first)
        resolve = self._resolve(slot)

        assert resolve().session_id == "first"
        slot.replace(second)
        assert resolve().session_id == "second"

    def test_unavailable_capability_uses_the_typed_error(self) -> None:
        resolve = self._resolve(
            CurrentSessionSlot(ContractControl()),
            SessionOperationAvailability.from_capabilities(
                (SessionOperationCapability.IDENTITY,)
            ),
        )

        with pytest.raises(SessionOperationUnavailableError, match="input"):
            resolve().follow_up("later")

    def test_product_errors_are_not_reclassified_as_unavailable(self) -> None:
        class BrokenControl(ContractControl):
            def steer(self, text: str, images=None) -> None:
                del text, images
                raise AttributeError("product steering bug")

        operations = self._resolve(CurrentSessionSlot(BrokenControl()))()

        with pytest.raises(AttributeError, match="product steering bug"):
            operations.steer("adjust")


__all__ = [
    "CurrentSessionSlot",
    "ResolverFactory",
    "SessionOperationContract",
]
