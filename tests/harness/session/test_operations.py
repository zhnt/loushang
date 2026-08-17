from __future__ import annotations

import asyncio

import pytest

from loushang.harness.runtime import SessionOperationResult
from loushang.harness.session import (
    SessionLifecycleOperationPorts,
    SessionOperationAvailability,
    SessionOperationCapability,
    SessionOperationRuntime,
    SessionOperationUnavailableError,
    SessionPromptRequest,
    current_session_operation_resolver,
    require_active_session,
)


class _Control:
    session_id = "session-1"
    session_name = "Initial"
    pending_message_count = 2
    is_retrying = False
    is_compacting = False
    auto_retry_enabled = True
    auto_compaction_enabled = True

    def __init__(self) -> None:
        self.prompts: list[tuple[str, object, dict[str, object]]] = []
        self.steering: list[tuple[str, object]] = []
        self.follow_up_messages: list[tuple[str, object]] = []
        self.aborted = False
        self.waited = 0
        self.updated_names: list[str | None] = []
        self.retry_aborted = False
        self.compact_requests: list[str | None] = []
        self.compaction_aborted = False

    async def prompt(self, text: str, images=None, **kwargs) -> None:
        self.prompts.append((text, images, kwargs))
        callback = kwargs.get("preflight_result")
        if callable(callback):
            callback(True)

    def steer(self, text: str, images=None) -> None:
        self.steering.append((text, images))

    def follow_up(self, text: str, images=None) -> None:
        self.follow_up_messages.append((text, images))

    def get_steering_messages(self) -> list[str]:
        return ["steer"]

    def get_follow_up_messages(self) -> list[str]:
        return ["follow-up"]

    def clear_queue(self) -> dict[str, list[str]]:
        return {"steering": ["steer"], "follow_up": ["follow-up"]}

    async def continue_run(self) -> None:
        return None

    def abort(self) -> bool:
        self.aborted = True
        return True

    async def wait_for_idle(self) -> None:
        self.waited += 1

    async def set_session_name(self, name: str | None) -> None:
        self.updated_names.append(name)
        self.session_name = name

    def abort_retry(self) -> None:
        self.retry_aborted = True

    async def wait_for_retry(self) -> None:
        return None

    def set_auto_retry_enabled(self, enabled: bool) -> None:
        self.auto_retry_enabled = enabled

    def set_auto_compaction_enabled(self, enabled: bool) -> None:
        self.auto_compaction_enabled = enabled

    async def compact(self, custom_instructions: str | None = None) -> object:
        self.compact_requests.append(custom_instructions)
        return {"summary": "done"}

    def abort_compaction(self) -> None:
        self.compaction_aborted = True

    async def refresh_resources(self) -> None:
        return None

    def request_resource_refresh(self) -> None:
        return None

    def subscribe_runtime_events(self, listener):
        del listener
        return lambda: None


class _Lifecycle:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def new_session(self, cwd, parent_session):
        self.calls.append(("new", cwd, parent_session))
        return SessionOperationResult(None, "new", None, False)

    async def restore_session(self, session_ref):
        self.calls.append(("restore", session_ref))
        return SessionOperationResult("old", "restored", None, True)

    async def fork_session(self, entry_id, position):
        self.calls.append(("fork", entry_id, position))
        return SessionOperationResult("old", "forked", "text", False)

    async def clone_session(self):
        self.calls.append(("clone",))
        return SessionOperationResult("clone", "cloned", None, False)


def test_session_operation_runtime_runs_input_and_maintenance_through_control() -> None:
    async def scenario() -> None:
        control = _Control()
        runtime = SessionOperationRuntime(control)
        preflight: list[bool] = []

        await runtime.prompt(
            SessionPromptRequest(
                text="review this",
                streaming_behavior="follow_up",
                source="remote",
            ),
            on_preflight=preflight.append,
        )
        runtime.steer("watch")
        runtime.follow_up("continue")
        assert runtime.clear_queue() == {
            "steering": ["steer"],
            "follow_up": ["follow-up"],
        }
        assert runtime.abort() is True
        await runtime.set_session_name("Renamed")
        runtime.abort_retry()
        runtime.set_auto_retry_enabled(False)
        runtime.set_auto_compaction_enabled(False)
        assert await runtime.compact("retain decisions") == {"summary": "done"}
        runtime.abort_compaction()

        assert preflight == [True]
        assert control.prompts == [
            (
                "review this",
                None,
                {
                    "streaming_behavior": "follow_up",
                    "source": "remote",
                    "preflight_result": preflight.append,
                },
            )
        ]
        assert control.waited == 1
        assert control.steering == [("watch", None)]
        assert control.follow_up_messages == [("continue", None)]
        assert control.aborted is True
        assert control.updated_names == ["Renamed"]
        assert control.retry_aborted is True
        assert control.auto_retry_enabled is False
        assert control.auto_compaction_enabled is False
        assert control.compact_requests == ["retain decisions"]
        assert control.compaction_aborted is True

    asyncio.run(scenario())


def test_session_operation_runtime_routes_lifecycle_through_product_ports() -> None:
    async def scenario() -> None:
        lifecycle = _Lifecycle()
        runtime = SessionOperationRuntime(
            _Control(),
            lifecycle=SessionLifecycleOperationPorts(
                new_session=lifecycle.new_session,
                restore_session=lifecycle.restore_session,
                fork_session=lifecycle.fork_session,
                clone_session=lifecycle.clone_session,
            ),
        )

        assert (
            await runtime.new_session(cwd="/project", parent_session="parent")
        ).current == "new"
        assert (await runtime.restore_session("saved.jsonl")).current == "restored"
        assert (await runtime.fork_session("leaf", position="before")).payload == "text"
        assert (await runtime.clone_session()).current == "cloned"
        assert lifecycle.calls == [
            ("new", "/project", "parent"),
            ("restore", "saved.jsonl"),
            ("fork", "leaf", "before"),
            ("clone",),
        ]

    asyncio.run(scenario())


def test_session_operation_runtime_rejects_unbound_operation_group() -> None:
    runtime = SessionOperationRuntime(
        _Control(),
        availability=SessionOperationAvailability.from_capabilities(
            [SessionOperationCapability.INPUT]
        ),
    )

    assert runtime.availability.supports(SessionOperationCapability.INPUT)
    assert not runtime.availability.supports(SessionOperationCapability.MAINTENANCE)
    with pytest.raises(SessionOperationUnavailableError, match="maintenance"):
        runtime.abort_compaction()


def test_session_prompt_request_requires_non_empty_text() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        SessionPromptRequest(text="")


def test_current_session_operation_resolver_rebinds_after_session_change() -> None:
    first = _Control()
    first.session_id = "first"
    second = _Control()
    second.session_id = "second"

    class _Session:
        def __init__(self, control: _Control) -> None:
            self.session_control = control

    class _Runtime:
        def __init__(self) -> None:
            self.current = _Session(first)

        def get_current_session(self) -> _Session:
            return self.current

    product = _Runtime()
    resolve = current_session_operation_resolver(product)

    assert resolve().session_id == "first"
    product.current = _Session(second)
    assert resolve().session_id == "second"


def test_dynamic_session_resolution_rejects_a_missing_active_session() -> None:
    class _Runtime:
        def get_current_session(self) -> None:
            return None

    product = _Runtime()
    resolve = current_session_operation_resolver(product)

    with pytest.raises(RuntimeError, match="requires an active session"):
        resolve()
    with pytest.raises(RuntimeError, match="requires an active session"):
        require_active_session(product)


def test_active_session_resolution_requires_the_runtime_contract() -> None:
    with pytest.raises(TypeError, match="provide get_current_session"):
        require_active_session(object())


def test_abort_turn_does_not_clear_queue() -> None:
    control = _Control()
    runtime = SessionOperationRuntime(control)

    assert runtime.abort_turn() is True
    assert control.aborted is True
    assert control.get_steering_messages() == ["steer"]
