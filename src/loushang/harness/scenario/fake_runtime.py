from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loushang.harness.scenario.events import EventPattern, WorkflowEvent, find_event


@dataclass(frozen=True)
class QueueState:
    steering: tuple[str, ...] = ()
    follow_up: tuple[str, ...] = ()


class FakeWorkflowAdapter:
    def __init__(self) -> None:
        self._events: list[WorkflowEvent] = []
        self._steering: list[str] = []
        self._follow_up: list[str] = []
        self._active_run_id: int | None = None
        self._next_run_id = 0
        self._condition = asyncio.Condition()

    async def run_prompt(self, prompt: str) -> str:
        return await self.prompt(prompt)

    async def prompt(self, prompt: str, *, hold: bool = False) -> str:
        if self._active_run_id is not None:
            raise RuntimeError("cannot start a prompt while a run is active")
        self._next_run_id += 1
        run_id = self._next_run_id
        self._active_run_id = run_id
        await self._emit(
            WorkflowEvent(type="run.started", text=prompt, data={"run_id": run_id})
        )
        if hold:
            return ""
        await self._emit(
            WorkflowEvent(
                type="assistant.message", text=prompt, data={"run_id": run_id}
            )
        )
        await self._emit(
            WorkflowEvent(type="run.ended", text=prompt, data={"run_id": run_id})
        )
        self._active_run_id = None
        return prompt

    async def steer(self, text: str) -> None:
        self._require_active_run("steer")
        self._steering.append(text)
        await self._emit(
            WorkflowEvent(
                type="queue.steer_added",
                text=text,
                data={
                    "queue": "steering",
                    "size": len(self._steering),
                    "run_id": self._active_run_id,
                },
            )
        )

    async def follow_up(self, text: str) -> None:
        self._require_active_run("follow_up")
        self._follow_up.append(text)
        await self._emit(
            WorkflowEvent(
                type="queue.follow_up_added",
                text=text,
                data={
                    "queue": "follow_up",
                    "size": len(self._follow_up),
                    "run_id": self._active_run_id,
                },
            )
        )

    async def abort(self) -> None:
        if self._active_run_id is None:
            return
        run_id = self._active_run_id
        self._active_run_id = None
        self._steering.clear()
        self._follow_up.clear()
        await self._emit(WorkflowEvent(type="run.aborted", data={"run_id": run_id}))

    async def wait_for(self, pattern: EventPattern, timeout_s: float) -> WorkflowEvent:
        existing = find_event(self.events(), pattern)
        if existing is not None:
            return existing

        async def wait_until_found() -> WorkflowEvent:
            async with self._condition:
                while True:
                    matched = find_event(self.events(), pattern)
                    if matched is not None:
                        return matched
                    await self._condition.wait()

        return await asyncio.wait_for(wait_until_found(), timeout=timeout_s)

    def events(self) -> tuple[WorkflowEvent, ...]:
        return tuple(self._events)

    def queue_state(self) -> QueueState:
        return QueueState(
            steering=tuple(self._steering), follow_up=tuple(self._follow_up)
        )

    def session_state(self) -> dict[str, object]:
        return {
            "runStatus": "running" if self._active_run_id is not None else "idle",
            "queue": {
                "steering": tuple(self._steering),
                "followUp": tuple(self._follow_up),
            },
            "pendingMessageCount": len(self._steering) + len(self._follow_up),
        }

    def session_stats(self) -> dict[str, object]:
        total_tokens = self._next_run_id * 10
        return {
            "totalMessages": self._next_run_id,
            "tokens": {"total": total_tokens},
            "contextUsage": self.context_usage(),
            "latestCompaction": None,
        }

    def context_usage(self) -> dict[str, object]:
        return {
            "messageCount": self._next_run_id,
            "estimatedContextTokens": self._next_run_id * 10,
            "compactPercent": 80,
        }

    async def _emit(self, event: WorkflowEvent) -> None:
        async with self._condition:
            self._events.append(event)
            self._condition.notify_all()

    def _require_active_run(self, action: str) -> None:
        if self._active_run_id is None:
            raise RuntimeError(f"cannot {action} without an active run")
