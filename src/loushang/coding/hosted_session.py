"""Real Coding AgentSession binding behind the product-neutral hosted port."""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from secrets import token_hex
from typing import TYPE_CHECKING, cast

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.ai.types import AssistantMessage, UserMessage
from loushang.apphost import SessionBindingKeyV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionEventKindV1,
    SessionIdentityV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)
from loushang.appserver.resume_model import (
    ResumeInputLookupQueryV1,
    ResumeInputLookupResultV1,
)
from loushang.appservice.execution_guard import ExecutionWorkV1
from loushang.harness.approval import (
    DenyApprovalResolver,
    InteractiveApprovalResolver,
)
from loushang.harness.capabilities.tools import ToolSelection
from loushang.harness.events import RuntimeEvent
from loushang.harness.events.runtime_projection import project_session_runtime_event
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeFactoryPort,
)
from loushang.harness.policy import PolicyEvaluator, PolicyEvaluatorChain
from loushang.harness.session import SessionControlPort
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace import workspace_tool_runtime_settings
from loushang.harness.workspace.exec.capture_lease import ExecCaptureFactory

from .appservice_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSessionBindingV1,
    CodingHostedSnapshotProjectionV1,
)
from .bootstrap import BootstrapServices, create_agent_session
from .hosted_catalog import (
    CodingHostedCandidateBindingV1,
    CodingHostedCatalogError,
    CodingHostedHistoryCandidateBindingV1,
)
from .package_product_runtime import (
    CodingFencedProductApplicationSelection,
)
from .resume_history import CodingResumeHistoryPreview
from .resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    CodingResumeInputLookupResultV1,
)
from .session.agent_session import AgentSession
from .session_manager import SessionManager

_TEXT_LIMIT = 16_384
_MAX_INTERACTIONS = 16
CodingHostedProductRuntimeFactoryForSession = Callable[
    [SessionManager], PackageProductRuntimeFactoryPort
]

if TYPE_CHECKING:
    from .hosted_resume import CodingDeferredHostedSessionV1


class CodingHostedHistoryBindingV1:
    """Detached historical display with no Writer or execution control.

    The catalog admits identity and the source revision before constructing this
    binding. AppService still owns caller read authorization. A display snapshot
    cannot be promoted into a current runtime or used as activation evidence.
    """

    def __init__(
        self, identity: SessionIdentityV1, history: CodingResumeHistoryPreview,
    ) -> None:
        if (
            type(identity) is not SessionIdentityV1
            or identity.product_id != "coding"
            or type(history) is not CodingResumeHistoryPreview
            or identity.session_id != history.header_preview.header.conversation_id
        ):
            raise CodingHostedCatalogError()
        self.identity = identity
        self._history = history
        self._closed = False
        records: list[TranscriptRecordV1] = []
        remaining = _TEXT_LIMIT
        omitted = False
        for entry in reversed(history.selected_records):
            record = _message_record(entry.payload)
            if record is None:
                continue
            if len(records) >= 128 or len(record.text) > remaining:
                omitted = True
                break
            records.append(record)
            remaining -= len(record.text)
        records.reverse()
        if omitted:
            records.insert(0, TranscriptRecordV1(
                TranscriptRecordKindV1.STATUS,
                "Earlier messages omitted from this bounded snapshot; the canonical transcript is unchanged.",
            ))
        records.append(TranscriptRecordV1(
            TranscriptRecordKindV1.STATUS,
            "Historical session is read-only; continuing requires current runtime activation.",
        ))
        self._projection = CodingHostedSnapshotProjectionV1(
            title="Coding", revision=0, running=False, records=tuple(records),
            truncated=omitted,
        )

    @property
    def control(self) -> None:
        return None

    @property
    def resume_history(self) -> CodingResumeHistoryPreview:
        if self._closed:
            raise RuntimeError("coding_hosted_session_closed")
        return self._history

    def project_snapshot(self) -> CodingHostedSnapshotProjectionV1:
        if self._closed:
            raise RuntimeError("coding_hosted_session_closed")
        return self._projection

    def project_event(
        self, event: RuntimeEvent[object],
    ) -> CodingHostedEventProjectionV1 | None:
        return None

    async def respond_interaction(self, interaction_id: str, outcome: str) -> bool:
        return False

    async def close(self) -> None:
        self._closed = True


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
        self._execution_claimed = False
        session.set_approval_presenter(
            self._present_approval, dismisser=self._dismiss_approval
        )

    @property
    def control(self) -> SessionControlPort:
        return self._session

    @property
    def execution_claimed(self) -> bool:
        return self._execution_claimed

    def claim_execution(self) -> None:
        if self._execution_claimed or self._close_task is not None:
            raise ValueError("Coding Session already has an execution owner")
        self._execution_claimed = True

    def release_failed_execution_claim(self) -> None:
        self._execution_claimed = False

    async def lookup_resume_input(
        self, query: CodingResumeInputLookupQueryV1,
    ) -> CodingResumeInputLookupResultV1:
        """Product observation for an already read-authorized Hosted caller.

        This internal port does not negotiate a new client protocol, authorize
        reads, or infer model outcome from durable message presence.
        """

        if self._close_task is not None:
            raise CodingHostedCatalogError()
        manager = self._session.session_manager
        if not isinstance(manager, SessionManager) or manager.header.conversation_id != self.identity.session_id:
            raise CodingHostedCatalogError()
        return await manager.lookup_resume_input(query)

    def project_snapshot(self) -> CodingHostedSnapshotProjectionV1:
        records: list[TranscriptRecordV1] = []
        remaining = _TEXT_LIMIT
        omitted = False
        truncated = False
        for message in reversed(self._session.messages):
            record = _message_record(message)
            if record is None:
                continue
            if len(records) >= 128 or len(record.text) > remaining:
                omitted = True
                break
            records.append(record)
            truncated |= len(_message_text(message)) > _TEXT_LIMIT
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
            truncated=omitted or truncated,
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
                        SessionEventKindV1.ASSISTANT_DELTA,
                        _bounded(delta),
                        truncated=len(delta) > _TEXT_LIMIT,
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

    @property
    def execution_available(self) -> bool:
        return self._session.execution_available

    def create_execution_work(
        self, text: str, cancel_requested: Callable[[], bool],
    ) -> ExecutionWorkV1:
        from ._hosted_execution_work import CodingExecutionWorkV1

        return CodingExecutionWorkV1(self._session, text, cancel_requested)


class CodingRealHostedSessionFactoryV1:
    """Trusted outer configuration; no remote module, model or factory names."""

    def __init__(
        self,
        *,
        services_factory: Callable[[Path], BootstrapServices],
        model: Model | ModelSelection | None = None,
        stream_fn: StreamFn | None = None,
        tools: list[ToolDefinition] | None = None,
        session_tool_policy: PolicyEvaluator | None = None,
        session_active_tools: list[str] | None = None,
        session_allowed_tools: list[str] | None = None,
        session_system_prompt: str | None = None,
        output_capture_factory: ExecCaptureFactory | None = None,
        package_product_runtime_factory_for_session: (
            CodingHostedProductRuntimeFactoryForSession | None
        ) = None,
    ) -> None:
        self._services_factory = services_factory
        self._model = model
        self._stream_fn = stream_fn
        self._tools = tools
        self._session_tool_policy = session_tool_policy
        self._session_active_tools = session_active_tools
        self._session_allowed_tools = session_allowed_tools
        self._session_system_prompt = session_system_prompt
        self._output_capture_factory = output_capture_factory
        self._package_product_runtime_factory_for_session = (
            package_product_runtime_factory_for_session
        )
        self._product_owner_selection = CodingFencedProductApplicationSelection(
            windows_candidate=sys.platform == "win32"
        )
        self._closing = False
        self._closed = False

    def _default_product_factory_for_session(
        self, manager: SessionManager, services: BootstrapServices
    ) -> PackageProductRuntimeFactoryPort | None:
        return self._product_owner_selection.factory_for_session(
            manager, settings_manager=services.settings_manager
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closing = True
        self._product_owner_selection.close()
        self._closed = True

    async def create_session(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        opaque_session_binding: object,
    ) -> (
        CodingRealHostedSessionV1
        | CodingHostedHistoryBindingV1
        | CodingDeferredHostedSessionV1
    ):
        if self._closing:
            raise CodingHostedCatalogError()
        if type(opaque_session_binding) not in (
            CodingHostedCandidateBindingV1, CodingHostedHistoryCandidateBindingV1,
        ):
            raise CodingHostedCatalogError()
        opaque_session_binding = cast(
            CodingHostedCandidateBindingV1 | CodingHostedHistoryCandidateBindingV1,
            opaque_session_binding,
        )
        identity = opaque_session_binding.record.identity
        if binding_key != SessionBindingKeyV1(
            identity.product_id, identity.continuity_id, identity.session_id
        ):
            raise CodingHostedCatalogError()
        if isinstance(opaque_session_binding, CodingHostedHistoryCandidateBindingV1):
            if not opaque_session_binding.supports_writable_resume:
                return opaque_session_binding.take_binding()
            from .hosted_resume import CodingDeferredHostedSessionV1

            source = opaque_session_binding.take_resume_source()
            try:
                binding = CodingDeferredHostedSessionV1(
                    source,
                    services=self._services_factory(source.record.scope.cwd),
                    model=self._model,
                    stream_fn=self._stream_fn,
                    tools=self._tools,
                    output_capture_factory=self._output_capture_factory,
                    product_owner_selection=self._product_owner_selection,
                )
                await binding.start_background_planning()
                return binding
            except BaseException:
                await source.close()
                raise
        manager = opaque_session_binding.manager_for_construction()
        try:
            approval = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
            services = self._services_factory(opaque_session_binding.record.scope.cwd)
            policy = workspace_tool_runtime_settings(services.settings_manager)
            runtime_factory = None
            if self._package_product_runtime_factory_for_session is not None:
                runtime_factory = self._package_product_runtime_factory_for_session(
                    manager
                )
                if runtime_factory is None:
                    raise TypeError("Package Product runtime factory is required")
            else:
                runtime_factory = self._default_product_factory_for_session(
                    manager, services
                )
            session = create_agent_session(
                session_manager=manager,
                model=self._model,
                stream_fn=self._stream_fn,
                services=services,
                tools=self._tools,
                approval_resolver=approval,
                tool_policy_evaluator=(PolicyEvaluatorChain(
                    tuple(p for p in (self._session_tool_policy, policy.policy_engine) if p is not None),
                    strategy="most_restrictive",
                ) if self._session_tool_policy is not None else policy.policy_engine),
                active_tool_names=self._session_active_tools,
                allowed_tool_names=self._session_allowed_tools if self._session_allowed_tools is not None else ToolSelection.ALL,
                system_prompt=self._session_system_prompt,
                output_capture_factory=self._output_capture_factory,
                package_product_runtime_factory=runtime_factory,
            )
            opaque_session_binding.retain_constructed_owner(session.dispose)
            real_binding = CodingRealHostedSessionV1(session, identity, approval)
            opaque_session_binding.take_manager()
            return real_binding
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
    return TranscriptRecordV1(
        TranscriptRecordKindV1.USER
        if isinstance(message, UserMessage)
        else TranscriptRecordKindV1.ASSISTANT,
        _bounded(_message_text(message)),
    )


def _message_text(message: object) -> str:
    if not isinstance(message, UserMessage | AssistantMessage):
        return ""
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
    return text


def _observe_close(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = [
    "CodingHostedHistoryBindingV1",
    "CodingHostedProductRuntimeFactoryForSession",
    "CodingRealHostedSessionFactoryV1",
    "CodingRealHostedSessionV1",
]


def _require_coding_hosted_binding(binding: object) -> None:
    for name in ("project_snapshot", "project_event"):
        if not callable(getattr(binding, name, None)):
            raise TypeError("Coding hosted Session binding is invalid")
    for name in ("respond_interaction", "close"):
        if not inspect.iscoroutinefunction(getattr(binding, name, None)):
            raise TypeError("Coding hosted Session binding is invalid")
    try:
        control = cast(CodingHostedSessionBindingV1, binding).control
    except BaseException:
        raise TypeError("Coding hosted Session binding is invalid") from None
    if control is None:
        return
    for name in (
        "subscribe_runtime_events",
        "prompt",
        "wait_for_idle",
        "steer",
        "follow_up",
        "abort",
    ):
        if not callable(getattr(control, name, None)):
            raise TypeError("Coding hosted Session control is invalid")


async def _lookup_coding_resume_input(
    binding: CodingHostedSessionBindingV1, query: ResumeInputLookupQueryV1,
) -> ResumeInputLookupResultV1:
    lookup = getattr(binding, "lookup_resume_input", None)
    if not inspect.iscoroutinefunction(lookup):
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    result = await lookup(CodingResumeInputLookupQueryV1(query.input_id, query.record_digest))
    if type(result) is not CodingResumeInputLookupResultV1:
        raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
    return ResumeInputLookupResultV1(result.input_id, result.record_id, result.status)
