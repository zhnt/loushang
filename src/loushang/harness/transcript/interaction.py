"""Reusable interaction mechanics for one Agent transcript session.

This optional Agent/AI profile owns selected-branch navigation, model and
thinking selection persistence, and read-only transcript inspection.  Product
code supplies model catalogs, summary generation, extension hooks, diagnostics,
and presentation.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast

from loushang.agent.types import ThinkingLevel
from loushang.ai.model import Model, ModelSelection
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from loushang.foundation.json import JSONValue, require_json_value
from loushang.harness.events import (
    BranchSummaryCompleted,
    BranchSummaryStarted,
    SessionRuntimeEventPayload,
)
from loushang.harness.runtime import (
    CancellationController,
    CancellationSignal,
    NavigationFailure,
    NavigationTransactionCoordinator,
)
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
)
from loushang.harness.transcript.session import AgentTranscriptSession
from loushang.harness.transcript.types import ApplicationMessage

_THINKING_LEVEL_ORDER: tuple[ThinkingLevel, ...] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)

RuntimeEventDispatcher = Callable[[SessionRuntimeEventPayload], Awaitable[None] | None]
NavigationFailureHandler = Callable[[Exception], Awaitable[None] | None]
ContextApplier = Callable[[], None]
BranchSummaryRunner = Callable[
    [Sequence[object], CancellationSignal], Awaitable["BranchSummaryOutput"]
]


class ModelSelectionCatalog(Protocol):
    """Product-supplied model catalog used by the optional transcript profile."""

    def list_models(self) -> list[ModelSelection]: ...

    def build_model(self, selection: ModelSelection) -> Model: ...


@dataclass(frozen=True)
class BranchSummaryOutput:
    """Product-generated branch summary normalized for transcript persistence."""

    summary: str | None = None
    details: JSONValue = None
    from_hook: bool = False
    aborted: bool = False
    error: str | None = None
    model_input_snapshot_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "details",
            require_json_value(self.details, name="branch_summary.details"),
        )
        if not isinstance(self.model_input_snapshot_ids, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.model_input_snapshot_ids
        ):
            raise TypeError(
                "branch summary Model Input snapshot ids must be non-empty strings"
            )
        if len(set(self.model_input_snapshot_ids)) != len(
            self.model_input_snapshot_ids
        ):
            raise ValueError("branch summary Model Input snapshot ids must be unique")


@dataclass(frozen=True)
class TranscriptNavigationPlan:
    target_id: str
    old_leaf_id: str | None
    new_leaf_id: str | None
    editor_text: str | None
    divergent_records: tuple[object, ...]


@dataclass(frozen=True)
class TranscriptNavigationResult:
    cancelled: bool
    aborted: bool = False
    editor_text: str | None = None
    summary_entry_id: str | None = None


@dataclass(frozen=True)
class TranscriptForkCandidate:
    record_id: str
    text: str


@dataclass(frozen=True)
class TranscriptMessageCounts:
    message_count: int
    assistant_message_count: int
    user_message_count: int
    tool_call_count: int
    tool_result_count: int
    application_message_count: int


@dataclass
class AgentTranscriptInspector:
    """Read-only standard projections over one active transcript branch."""

    session: AgentTranscriptSession

    def message_counts(self) -> TranscriptMessageCounts:
        context = self.session.build_context()
        assistant_message_count = 0
        user_message_count = 0
        tool_call_count = 0
        tool_result_count = 0
        for message in context.messages:
            if isinstance(message, AssistantMessage):
                assistant_message_count += 1
                tool_call_count += sum(
                    1 for part in message.content if isinstance(part, ToolCall)
                )
            elif isinstance(message, UserMessage):
                user_message_count += 1
            elif isinstance(message, ToolResultMessage):
                tool_result_count += 1
        return TranscriptMessageCounts(
            message_count=len(context.messages),
            assistant_message_count=assistant_message_count,
            user_message_count=user_message_count,
            tool_call_count=tool_call_count,
            tool_result_count=tool_result_count,
            application_message_count=sum(
                1
                for record in self.session.get_entries()
                if record.kind == APPLICATION_MESSAGE_KIND
            ),
        )

    def has_compaction_checkpoint(self) -> bool:
        return any(
            record.kind == CONTEXT_COMPACTION_CHECKPOINT_KIND
            for record in self.session.get_entries()
        )

    def fork_candidates(self) -> tuple[TranscriptForkCandidate, ...]:
        candidates: list[TranscriptForkCandidate] = []
        for record in self.session.get_entries():
            if record.kind != AGENT_MESSAGE_KIND or not isinstance(
                record.payload, UserMessage
            ):
                continue
            text = user_message_text(record.payload)
            if text:
                candidates.append(
                    TranscriptForkCandidate(record_id=record.record_id, text=text)
                )
        return tuple(candidates)

    def entry_text(self, record_id: str) -> str | None:
        record = self.session.get_entry(record_id)
        if record is None:
            return None
        if record.kind == AGENT_MESSAGE_KIND and isinstance(
            record.payload, UserMessage
        ):
            return user_message_text(record.payload) or None
        if record.kind == APPLICATION_MESSAGE_KIND and isinstance(
            record.payload, ApplicationMessage
        ):
            return application_message_text(record.payload) or None
        return None

    def recent_assistant_texts(
        self,
        messages: Sequence[object] | None = None,
    ) -> tuple[str, ...]:
        texts: list[str] = []
        source = self.session.build_context().messages if messages is None else messages
        for message in reversed(source):
            if not isinstance(message, AssistantMessage):
                continue
            text = assistant_message_text(message)
            if text is not None:
                texts.append(text)
        return tuple(texts)

    def branch_leaf_count(self) -> int:
        def count(node: object) -> int:
            children = getattr(node, "children", ())
            if not children:
                return 1
            return sum(count(child) for child in children)

        return sum(count(node) for node in self.session.get_tree())


@dataclass
class AgentTranscriptSelectionRuntime:
    """Persisted Agent model/thinking selection without Product policy."""

    session: AgentTranscriptSession
    get_model: Callable[[], Model]
    set_model: Callable[[Model], None]
    get_thinking_level: Callable[[], ThinkingLevel]
    set_thinking_level_value: Callable[[ThinkingLevel], None]
    get_model_catalog: Callable[[], ModelSelectionCatalog | None]
    _scoped_models: list[dict[str, object]] = field(default_factory=list)

    def get_model_selection(self) -> ModelSelection | None:
        return model_selection_from_model(self.get_model())

    def get_available_models(self) -> list[ModelSelection]:
        catalog = self.get_model_catalog()
        return [] if catalog is None else catalog.list_models()

    def get_scoped_models(self) -> list[dict[str, object]]:
        return [dict(scoped) for scoped in self._scoped_models]

    def set_scoped_models(self, scoped_models: list[dict[str, object]]) -> None:
        self._scoped_models = [dict(scoped) for scoped in scoped_models]

    def resolve_model(self, model: Model | ModelSelection) -> Model:
        if isinstance(model, ModelSelection):
            catalog = self.get_model_catalog()
            if catalog is None:
                raise RuntimeError("ModelSelection requires a model catalog")
            return validate_model(catalog.build_model(model))
        return validate_model(model)

    async def apply_model(
        self,
        model: Model,
    ) -> None:
        validated = validate_model(model)
        provider = str(getattr(validated, "provider_id", None))
        endpoint_id = str(getattr(validated, "endpoint_id", None))
        await self.session.append_model_change(
            provider,
            validated.id,
            endpoint_id=endpoint_id,
        )
        self.set_model(validated)

    def cycle_model_selection(
        self, direction: str = "forward"
    ) -> ModelSelection | None:
        models = self.get_available_models()
        if not isinstance(models, list):
            raise TypeError("Model catalog returned an invalid response.")
        if not models:
            return None
        current = self.get_model_selection()
        try:
            index = models.index(current) if current is not None else -1
        except ValueError:
            index = -1
        return cycle_selection(models, index, direction)

    def cycle_scoped_selection(
        self,
        direction: str,
    ) -> tuple[ModelSelection, ThinkingLevel | None] | None:
        selections: list[tuple[ModelSelection, ThinkingLevel | None]] = []
        for scoped in self._scoped_models:
            selection = self.model_selection_from_scoped_model(scoped)
            if selection is None:
                continue
            thinking = scoped.get("thinkingLevel") or scoped.get("thinking_level")
            selections.append(
                (
                    selection,
                    (
                        cast(ThinkingLevel, thinking)
                        if thinking in _THINKING_LEVEL_ORDER
                        else None
                    ),
                )
            )
        if len(selections) <= 1:
            return None
        current = self.get_model_selection()
        if current is None:
            index = -1
        else:
            try:
                index = [selection for selection, _ in selections].index(current)
            except ValueError:
                index = -1
        return cycle_selection_pair(selections, index, direction)

    def model_selection_from_scoped_model(
        self,
        scoped: dict[str, object],
    ) -> ModelSelection | None:
        model = scoped.get("model", scoped)
        if isinstance(model, ModelSelection):
            return model
        if isinstance(model, Model):
            return model_selection_from_model(model)
        if not isinstance(model, dict):
            return None
        provider = (
            model.get("provider") or model.get("provider_id") or model.get("providerId")
        )
        model_id = model.get("model_id") or model.get("modelId") or model.get("id")
        endpoint_id = (
            model.get("endpoint_id") or model.get("endpointId") or model.get("endpoint")
        )
        if (
            isinstance(provider, str)
            and isinstance(endpoint_id, str)
            and isinstance(model_id, str)
        ):
            return ModelSelection(
                provider=provider,
                endpoint_id=endpoint_id,
                model_id=model_id,
            )
        return None

    async def set_thinking_level(self, level: ThinkingLevel) -> None:
        available = self.get_available_thinking_levels()
        effective = level if level in available else available[-1]
        if effective == self.get_thinking_level():
            return
        await self.session.append_thinking_level_change(effective)
        self.set_thinking_level_value(effective)

    async def cycle_thinking_level(self) -> ThinkingLevel | None:
        if not self.supports_thinking():
            await self.set_thinking_level("off")
            return None
        levels = self.get_available_thinking_levels()
        current = self.get_thinking_level()
        index = levels.index(current) if current in levels else 0
        next_level = levels[(index + 1) % len(levels)]
        await self.set_thinking_level(next_level)
        return next_level

    def supports_thinking(self) -> bool:
        return bool(getattr(self.get_model(), "reasoning", False))

    def get_available_thinking_levels(self) -> list[ThinkingLevel]:
        return list(_THINKING_LEVEL_ORDER) if self.supports_thinking() else ["off"]


@dataclass
class AgentTranscriptNavigationRuntime:
    """Navigate active transcript branches and persist optional summaries."""

    session: AgentTranscriptSession
    apply_context: ContextApplier
    dispatch_event: RuntimeEventDispatcher | None = None
    on_failure: NavigationFailureHandler | None = None
    _transaction: NavigationTransactionCoordinator[CancellationController] = field(
        default_factory=lambda: NavigationTransactionCoordinator(
            create_abort_scope=CancellationController,
            abort=lambda controller: controller.abort(),
        ),
        init=False,
        repr=False,
    )

    @property
    def is_summarizing(self) -> bool:
        return self._transaction.is_active

    def owns_current_task(self) -> bool:
        return self._transaction.owns_current_task()

    def abort(self) -> bool:
        return self._transaction.abort()

    async def cancel_and_wait(self) -> None:
        """Abort and join the active summary transaction before disposal."""

        self.abort()
        await self._transaction.wait()

    def prepare(self, target_id: str) -> TranscriptNavigationPlan | None:
        old_leaf_id = self.session.get_leaf_id()
        if target_id == old_leaf_id:
            return None
        target = self.session.get_entry(target_id)
        if target is None:
            raise ValueError(f"Entry {target_id} not found")
        if target.kind == AGENT_MESSAGE_KIND and isinstance(
            target.payload, UserMessage
        ):
            new_leaf_id = target.parent_id
            editor_text = user_message_text(target.payload)
        elif target.kind == APPLICATION_MESSAGE_KIND and isinstance(
            target.payload, ApplicationMessage
        ):
            new_leaf_id = target.parent_id
            editor_text = application_message_text(target.payload)
        else:
            new_leaf_id = target_id
            editor_text = None
        divergent_records: tuple[object, ...] = ()
        if old_leaf_id is not None:
            divergent_records = tuple(
                self.session.get_branch_delta(old_leaf_id, target_id).divergent_records
            )
        return TranscriptNavigationPlan(
            target_id=target_id,
            old_leaf_id=old_leaf_id,
            new_leaf_id=new_leaf_id,
            editor_text=editor_text,
            divergent_records=divergent_records,
        )

    async def navigate(
        self,
        plan: TranscriptNavigationPlan,
        *,
        summarize: bool = False,
        label: str | None = None,
        summary_override: BranchSummaryOutput | None = None,
        summary_runner: BranchSummaryRunner | None = None,
    ) -> TranscriptNavigationResult:
        if not summarize:
            await self._apply_leaf(plan.new_leaf_id)
            return TranscriptNavigationResult(
                cancelled=False,
                editor_text=plan.editor_text,
            )
        return await self._transaction.run(
            plan,
            before_commit=self._publish_summary_started,
            commit=lambda current, controller: self._commit_summary_navigation(
                current,
                controller.signal,
                label=label,
                summary_override=summary_override,
                summary_runner=summary_runner,
            ),
            after_commit=self._publish_summary_completed,
            on_failure=self._handle_failure,
        )

    async def _commit_summary_navigation(
        self,
        plan: TranscriptNavigationPlan,
        signal: CancellationSignal,
        *,
        label: str | None,
        summary_override: BranchSummaryOutput | None,
        summary_runner: BranchSummaryRunner | None,
    ) -> TranscriptNavigationResult:
        if signal.aborted:
            return _aborted_navigation_result(plan)
        summary = summary_override
        if summary is None and plan.divergent_records:
            if summary_runner is None:
                raise RuntimeError("Branch summary requires a Product summary runner")
            summary = await summary_runner(plan.divergent_records, signal)
        if signal.aborted:
            return _aborted_navigation_result(plan)
        if summary is not None and summary.aborted:
            return _aborted_navigation_result(plan)
        if summary is not None and summary.error:
            raise RuntimeError(summary.error)
        summary_record_id: str | None = None
        if summary is not None and summary.summary is not None:
            if signal.aborted:
                return _aborted_navigation_result(plan)
            summary_record_id = await self.session.branch_with_summary(
                plan.new_leaf_id,
                summary.summary,
                details=summary.details,
                from_hook=summary.from_hook,
                model_input_snapshot_ids=summary.model_input_snapshot_ids,
            )
            if label:
                await self.session.append_label(summary_record_id, label)
        else:
            if plan.new_leaf_id is None:
                self.session.reset_leaf()
            else:
                self.session.branch(plan.new_leaf_id)
            if label:
                await self.session.append_label(plan.target_id, label)
        self.apply_context()
        return TranscriptNavigationResult(
            cancelled=False,
            editor_text=plan.editor_text,
            summary_entry_id=summary_record_id,
        )

    async def _apply_leaf(self, leaf_id: str | None) -> None:
        if leaf_id is None:
            self.session.reset_leaf()
        else:
            self.session.branch(leaf_id)
        self.apply_context()

    async def _publish_summary_started(self, plan: TranscriptNavigationPlan) -> None:
        if self.dispatch_event is None:
            return
        await maybe_await(
            self.dispatch_event(
                BranchSummaryStarted(
                    target_id=plan.target_id,
                    old_leaf_id=plan.old_leaf_id,
                    summarize=True,
                )
            )
        )

    async def _publish_summary_completed(
        self,
        plan: TranscriptNavigationPlan,
        result: TranscriptNavigationResult,
    ) -> None:
        if self.dispatch_event is None:
            return
        await maybe_await(
            self.dispatch_event(
                BranchSummaryCompleted(
                    target_id=plan.target_id,
                    old_leaf_id=plan.old_leaf_id,
                    new_leaf_id=(
                        plan.old_leaf_id
                        if result.aborted
                        else self.session.get_leaf_id()
                    ),
                    summary_record_id=result.summary_entry_id,
                    cancelled=result.cancelled,
                    aborted=result.aborted,
                )
            )
        )

    async def _handle_failure(
        self,
        failure: NavigationFailure[TranscriptNavigationPlan],
    ) -> None:
        if self.on_failure is not None:
            await maybe_await(self.on_failure(failure.error))
        if self.dispatch_event is not None:
            await maybe_await(
                self.dispatch_event(
                    BranchSummaryCompleted(
                        target_id=failure.plan.target_id,
                        old_leaf_id=failure.plan.old_leaf_id,
                        new_leaf_id=failure.plan.old_leaf_id,
                        summary_record_id=None,
                        cancelled=False,
                        aborted=False,
                        error_message=str(failure.error),
                    )
                )
            )


def _aborted_navigation_result(
    plan: TranscriptNavigationPlan,
) -> TranscriptNavigationResult:
    return TranscriptNavigationResult(
        cancelled=True,
        aborted=True,
        editor_text=plan.editor_text,
    )


def user_message_text(message: UserMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(part.text for part in message.content if isinstance(part, TextPart))


def application_message_text(message: ApplicationMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(part.text for part in message.content if isinstance(part, TextPart))


def assistant_message_text(message: AssistantMessage) -> str | None:
    if isinstance(message.content, str):
        return message.content if message.content.strip() else None
    text = "".join(part.text for part in message.content if isinstance(part, TextPart))
    return text if text.strip() else None


def model_selection_from_model(model: object) -> ModelSelection | None:
    provider = getattr(model, "provider_id", None) or getattr(model, "provider", None)
    endpoint_id = getattr(model, "endpoint_id", None) or getattr(
        model, "endpoint", None
    )
    model_id = getattr(model, "id", None)
    if not provider or not endpoint_id or not model_id:
        return None
    return ModelSelection(
        provider=str(provider),
        endpoint_id=str(endpoint_id),
        model_id=str(model_id),
    )


def validate_model(model: object) -> Model:
    provider = getattr(model, "provider_id", None) or getattr(model, "provider", None)
    endpoint_id = getattr(model, "endpoint_id", None) or getattr(
        model, "endpoint", None
    )
    model_id = getattr(model, "id", None)
    if not provider or not endpoint_id or not model_id:
        raise ValueError("Model updates require provider, endpoint, and model ids.")
    return model  # type: ignore[return-value]


def cycle_selection(
    selections: list[ModelSelection],
    index: int,
    direction: str,
) -> ModelSelection:
    if direction == "backward":
        return selections[(index - 1) % len(selections)]
    if direction == "forward":
        return selections[(index + 1) % len(selections)]
    raise ValueError("cycle_model direction must be 'forward' or 'backward'")


def cycle_selection_pair(
    selections: list[tuple[ModelSelection, ThinkingLevel | None]],
    index: int,
    direction: str,
) -> tuple[ModelSelection, ThinkingLevel | None]:
    if direction == "backward":
        return selections[(index - 1) % len(selections)]
    if direction == "forward":
        return selections[(index + 1) % len(selections)]
    raise ValueError("cycle_model direction must be 'forward' or 'backward'")


async def maybe_await(value: Awaitable[None] | None) -> None:
    if inspect.isawaitable(value):
        await value


__all__ = [
    "AgentTranscriptInspector",
    "AgentTranscriptNavigationRuntime",
    "AgentTranscriptSelectionRuntime",
    "BranchSummaryOutput",
    "BranchSummaryRunner",
    "ModelSelectionCatalog",
    "TranscriptForkCandidate",
    "TranscriptMessageCounts",
    "TranscriptNavigationPlan",
    "TranscriptNavigationResult",
    "application_message_text",
    "assistant_message_text",
    "model_selection_from_model",
    "user_message_text",
    "validate_model",
]
