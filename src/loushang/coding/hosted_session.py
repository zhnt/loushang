"""Real Coding AgentSession binding behind the product-neutral hosted port."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from secrets import token_hex
from typing import cast

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.ai.types import AssistantMessage, UserMessage
from loushang.apphost import SessionBindingKeyV1
from loushang.appserver.protocol import (
    SessionEventKindV1,
    SessionIdentityV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)
from loushang.harness.approval import DenyApprovalResolver, InteractiveApprovalResolver
from loushang.harness.events import RuntimeEvent
from loushang.harness.events.runtime_projection import project_session_runtime_event
from loushang.harness.session import SessionControlPort
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace import workspace_tool_runtime_settings

from .appservice_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSnapshotProjectionV1,
)
from .bootstrap import BootstrapServices, create_agent_session
from .hosted_catalog import CodingHostedCandidateBindingV1, CodingHostedCatalogError
from .session.agent_session import AgentSession

_TEXT_LIMIT = 16_384
_MAX_INTERACTIONS = 16


class CodingRealHostedSessionV1:
    def __init__(
        self,
        session: AgentSession,
        identity: SessionIdentityV1,
        approval: InteractiveApprovalResolver,
    ) -> None:
        self._session = session
        self.identity = identity
        self._approval = approval
        self._interactions: dict[str, str] = {}
        self._interrupted = False
        self._revision = 0
        self._close_task: asyncio.Task[None] | None = None
        session.set_approval_presenter(
            self._present_approval, dismisser=self._dismiss_approval
        )

    @property
    def control(self) -> SessionControlPort:
        return self._session

    def project_snapshot(self) -> CodingHostedSnapshotProjectionV1:
        records: list[TranscriptRecordV1] = []
        remaining = _TEXT_LIMIT
        omitted = False
        for message in reversed(self._session.messages):
            record = _message_record(message)
            if record is None:
                continue
            if len(records) >= 128 or len(record.text) > remaining:
                omitted = True
                break
            records.append(record)
            remaining -= len(record.text)
        records.reverse()
        if omitted:
            records.insert(
                0,
                TranscriptRecordV1(
                    TranscriptRecordKindV1.STATUS,
                    "Earlier messages omitted from this bounded snapshot; the canonical transcript is unchanged.",
                ),
            )
        return CodingHostedSnapshotProjectionV1(
            title=_bounded(
                (self._session.session_name or "").strip() or "Coding", limit=256
            ),
            revision=self._revision,
            running=self._session.is_streaming,
            records=tuple(records),
        )

    def project_event(
        self, event: RuntimeEvent[object]
    ) -> CodingHostedEventProjectionV1 | None:
        self._revision += 1
        payload = project_session_runtime_event(event)
        if payload is None:
            return None
        kind = payload.get("type")
        if kind == "agent_start":
            self._interrupted = False
            return CodingHostedEventProjectionV1(SessionEventKindV1.TURN_STARTED)
        if kind == "agent_end":
            return CodingHostedEventProjectionV1(
                SessionEventKindV1.TURN_INTERRUPTED
                if self._interrupted
                else SessionEventKindV1.TURN_COMPLETED
            )
        if kind == "message_end":
            message = payload.get("message")
            if (
                isinstance(message, AssistantMessage)
                and message.stop_reason == "aborted"
            ):
                self._interrupted = True
            record = _message_record(message)
            if record is not None:
                return CodingHostedEventProjectionV1(
                    SessionEventKindV1.USER_MESSAGE
                    if record.kind is TranscriptRecordKindV1.USER
                    else SessionEventKindV1.ASSISTANT_MESSAGE,
                    record.text,
                )
        if kind == "message_update":
            update = payload.get("assistant_message_event")
            if isinstance(update, Mapping) and update.get("type") == "text_delta":
                delta = update.get("delta")
                if isinstance(delta, str):
                    return CodingHostedEventProjectionV1(
                        SessionEventKindV1.ASSISTANT_DELTA, _bounded(delta)
                    )
        if payload.get("hosted_presentation") is True and kind in {
            "tool_approval_requested",
            "tool_approval_resolved",
        }:
            return CodingHostedEventProjectionV1(
                SessionEventKindV1.INTERACTION_REQUESTED
                if kind == "tool_approval_requested"
                else SessionEventKindV1.INTERACTION_DISMISSED,
                cast(str | None, payload.get("text")),
                cast(str, payload["interaction_id"]),
            )
        return None

    async def _present_approval(self, request: dict[str, object]) -> None:
        action_id = request.get("action_id")
        if (
            not isinstance(action_id, str)
            or len(self._interactions) >= _MAX_INTERACTIONS
        ):
            raise RuntimeError("hosted_approval_unavailable")
        # Publish only once the existing ApprovalBroker has registered its waiter.
        text = "\n".join(
            (
                str(request.get("action", "Tool approval")),
                str(request.get("risk", "")),
                json.dumps(
                    request.get("arguments", {}), ensure_ascii=False, sort_keys=True
                ),
            )
        )
        if len(text) > _TEXT_LIMIT:
            raise RuntimeError("hosted_approval_too_large")
        interaction_id = token_hex(16)
        self._interactions[interaction_id] = action_id
        try:
            await self._session.runtime.dispatch_event(
                {
                    "type": "tool_approval_requested",
                    "hosted_presentation": True,
                    "interaction_id": interaction_id,
                    "text": text,
                }
            )
        except BaseException:
            self._interactions.pop(interaction_id, None)
            raise

    async def _dismiss_approval(self, action_id: str) -> None:
        for interaction_id, pending in tuple(self._interactions.items()):
            if pending == action_id:
                self._interactions.pop(interaction_id, None)
                await self._session.runtime.dispatch_event(
                    {
                        "type": "tool_approval_resolved",
                        "hosted_presentation": True,
                        "interaction_id": interaction_id,
                    }
                )

    async def respond_interaction(self, interaction_id: str, outcome: str) -> bool:
        action_id = self._interactions.get(interaction_id)
        if action_id is None or outcome not in {"allow_once", "deny", "abort"}:
            return False
        return await self._session.handle_screen_approval(
            {
                "action_id": action_id,
                "outcome": outcome,
            }
        )

    async def close(self) -> None:
        task = self._close_task
        if task is None or (
            task.done() and (task.cancelled() or task.exception() is not None)
        ):
            task = asyncio.create_task(self._close_once())
            task.add_done_callback(_observe_close)
            self._close_task = task
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        self._approval.end_session()
        await self._session.dispose()
        self._interactions.clear()


class CodingRealHostedSessionFactoryV1:
    """Trusted outer configuration; no remote module, model or factory names."""

    def __init__(
        self,
        *,
        services_factory: Callable[[Path], BootstrapServices],
        model: Model | ModelSelection | None = None,
        stream_fn: StreamFn | None = None,
        tools: list[ToolDefinition] | None = None,
    ) -> None:
        self._services_factory = services_factory
        self._model = model
        self._stream_fn = stream_fn
        self._tools = tools

    async def create_session(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        opaque_session_binding: object,
    ) -> CodingRealHostedSessionV1:
        if type(opaque_session_binding) is not CodingHostedCandidateBindingV1:
            raise CodingHostedCatalogError()
        identity = opaque_session_binding.record.identity
        if binding_key != SessionBindingKeyV1(
            identity.product_id, identity.continuity_id, identity.session_id
        ):
            raise CodingHostedCatalogError()
        manager = opaque_session_binding.manager_for_construction()
        try:
            approval = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
            services = self._services_factory(opaque_session_binding.record.scope.cwd)
            policy = workspace_tool_runtime_settings(services.settings_manager)
            session = create_agent_session(
                session_manager=manager,
                model=self._model,
                stream_fn=self._stream_fn,
                services=services,
                tools=self._tools,
                approval_resolver=approval,
                tool_policy_evaluator=policy.policy_engine,
            )
            opaque_session_binding.retain_constructed_owner(session.dispose)
            binding = CodingRealHostedSessionV1(session, identity, approval)
            opaque_session_binding.take_manager()
            return binding
        except BaseException:
            # The claimed candidate retains failed cleanup for the outer
            # AppHost owner to retry; no acquired owner disappears on failure.
            await opaque_session_binding.close()
            raise


def _bounded(text: str, *, limit: int = _TEXT_LIMIT) -> str:
    marker = " … [truncated]"
    return text if len(text) <= limit else text[: limit - len(marker)] + marker


def _message_record(message: object) -> TranscriptRecordV1 | None:
    if not isinstance(message, UserMessage | AssistantMessage):
        return None
    content = message.content
    text = (
        content
        if isinstance(content, str)
        else "".join(
            getattr(part, "text", "")
            for part in content
            if getattr(part, "type", None) == "text"
        )
    )
    return TranscriptRecordV1(
        TranscriptRecordKindV1.USER
        if isinstance(message, UserMessage)
        else TranscriptRecordKindV1.ASSISTANT,
        _bounded(text),
    )


def _observe_close(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = ["CodingRealHostedSessionFactoryV1", "CodingRealHostedSessionV1"]
