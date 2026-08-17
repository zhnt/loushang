from __future__ import annotations

import asyncio

from loushang.harness.runtime import SessionOperationResult
from loushang.harness.session import SessionRpcOperationBinding


class _Operations:
    def __init__(self) -> None:
        self.steers: list[str] = []
        self.follow_ups: list[str] = []
        self.aborts = 0
        self.auto_retry: list[bool] = []
        self.auto_compaction: list[bool] = []
        self.compactions: list[str | None] = []

    def steer(self, text: str, *, images=()) -> None:
        del images
        self.steers.append(text)

    def follow_up(self, text: str, *, images=()) -> None:
        del images
        self.follow_ups.append(text)

    def abort_turn(self) -> bool:
        self.aborts += 1
        return True

    async def new_session(self, *, cwd=None, parent_session=None):
        return SessionOperationResult(None, "new", (cwd, parent_session), False)

    async def restore_session(self, session_ref):
        return SessionOperationResult("old", session_ref, None, False)

    async def fork_session(self, entry_id, *, position="at"):
        return SessionOperationResult("old", "forked", (entry_id, position), False)

    async def clone_session(self):
        return SessionOperationResult("old", "cloned", None, False)

    async def compact(self, instructions=None):
        self.compactions.append(instructions)
        return {"ok": True}

    def set_auto_retry_enabled(self, enabled: bool) -> None:
        self.auto_retry.append(enabled)

    def abort_retry(self) -> None:
        return None

    def set_auto_compaction_enabled(self, enabled: bool) -> None:
        self.auto_compaction.append(enabled)


def test_binding_maps_standard_input_and_maintenance_payloads() -> None:
    operations = _Operations()
    binding = SessionRpcOperationBinding(
        get_operations=lambda: operations, bind_session=lambda session: None
    )

    request = binding.prompt_request(
        {"message": "hello", "streamingBehavior": "followUp", "images": []}
    )
    assert request.text == "hello"
    assert request.streaming_behavior == "followUp"
    binding.steer({"message": "steer"})
    binding.follow_up({"message": "follow"})
    assert binding.abort() is True
    binding.set_auto_retry({"enabled": False})
    binding.abort_retry()
    binding.set_auto_compaction({"enabled": True})
    assert asyncio.run(binding.compact({"customInstructions": "keep API"})) == {
        "ok": True
    }
    assert operations.steers == ["steer"]
    assert operations.follow_ups == ["follow"]
    assert operations.aborts == 1
    assert operations.auto_retry == [False]
    assert operations.auto_compaction == [True]
    assert operations.compactions == ["keep API"]


def test_binding_rebinds_after_lifecycle_operation() -> None:
    operations = _Operations()
    rebound: list[object] = []
    binding = SessionRpcOperationBinding(
        get_operations=lambda: operations, bind_session=rebound.append
    )

    result = asyncio.run(binding.fork({"entryId": "entry-1", "position": "before"}))

    assert result.current == "forked"
    assert rebound == ["forked"]


def test_binding_rejects_invalid_standard_payload() -> None:
    operations = _Operations()
    binding = SessionRpcOperationBinding(
        get_operations=lambda: operations, bind_session=lambda session: None
    )

    try:
        binding.set_auto_retry({"enabled": "false"})
    except ValueError as exc:
        assert str(exc) == "set_auto_retry requires boolean enabled"
    else:
        raise AssertionError("invalid enabled value was accepted")
