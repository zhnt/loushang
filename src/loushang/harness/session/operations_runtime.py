"""Shared operations over an assembled Product session.

The operation object owns coordination, not Product policy.  Product code
supplies the branch-summary executor, hook decisions, and shutdown cleanup;
the common runtime owns ordering, cancellation, and resource/lifecycle
coordination.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, TypeAlias

from loushang.agent import Agent
from loushang.ai.types import AssistantMessage
from loushang.harness.extensions.context import (
    SessionBeforeTreeResult,
    SessionShutdownEvent,
)
from loushang.harness.runtime import CancellationSignal
from loushang.harness.runtime.registration import _await_cancellation_atomic
from loushang.harness.session.composition import (
    SessionComposition,
    SessionExtensionCompositionPort,
    apply_agent_session_model_selection,
    supports_prepare_model_call,
)
from loushang.harness.transcript import (
    BranchSummaryOutput,
    CompactionResult,
    CompactionStatus,
    ProductTranscriptSession,
    TranscriptNavigationPlan,
    TranscriptNavigationResult,
    normalize_branch_summary_output,
)

BeforeTreeHookResult: TypeAlias = (
    tuple[str | None, bool, str | None, BranchSummaryOutput | None, bool]
    | SessionBeforeTreeResult
    | None
)


@dataclass(frozen=True)
class SessionOperationsPorts:
    """Product callbacks consumed by the shared operation coordinator."""

    composition: SessionComposition
    agent: Agent
    session_manager: ProductTranscriptSession[Any, Any]
    extension_runner: SessionExtensionCompositionPort | None
    execute_branch_summary: Callable[..., Awaitable[BranchSummaryOutput]]
    before_tree: Callable[..., Awaitable[BeforeTreeHookResult]]
    dispose_runtime_profile: Callable[[], object | None]
    finalize_shutdown: Callable[[], None]
    invalidate_extension_contexts: Callable[[str], None]
    sync_extension_diagnostics: Callable[..., None]
    close_approvals: Callable[[], None]


class SessionOperations:
    """Coordinate standard session operations for any Product adapter."""

    def __init__(self, ports: SessionOperationsPorts) -> None:
        self.ports = ports
        self.composition = ports.composition

    async def dispatch_event(
        self, event: object, *, source_record_id: str | None = None
    ) -> None:
        await self.composition.session_runtime.dispatch_event(
            event,
            source_record_id=source_record_id,
        )

    async def set_active_tools(
        self, tool_names: list[str], *, emit_refresh: bool
    ) -> None:
        self.composition.tool_controller.apply_active_tools(tool_names)
        if emit_refresh:
            await self.composition.extension_bridge.refresh(
                reason="active_tools_changed"
            )

    def apply_active_tools(self, tool_names: list[str]) -> None:
        self.composition.tool_controller.apply_active_tools(tool_names)

    async def set_model(
        self,
        model: object,
        *,
        emit_refresh: bool,
        source: str = "set",
    ) -> None:
        async def refresh_extension_runtime(reason: str) -> None:
            if emit_refresh:
                await self.composition.extension_bridge.refresh(reason=reason)

        await apply_agent_session_model_selection(
            self.composition.selection_runtime,
            model,
            self.ports.agent,
            self.composition.session_runtime,
            self.ports.extension_runner,
            refresh_extension_runtime,
            self.ports.session_manager.get_cwd,
            source=source,
        )

    async def maybe_compact_after_turn(
        self, assistant_message: AssistantMessage
    ) -> CompactionResult | None:
        result = await self.composition.session_runtime.check_auto_compaction(
            assistant_message
        )
        return result

    def get_compaction_status(self) -> CompactionStatus:
        return replace(
            self.composition.compaction_runtime.get_status(),
            is_branch_summarizing=self.composition.navigation_runtime.is_summarizing,
        )

    async def navigate_tree(
        self,
        target_id: str,
        *,
        summarize: bool = False,
        custom_instructions: str | None = None,
        replace_instructions: bool = False,
        label: str | None = None,
    ) -> TranscriptNavigationResult:
        navigation = self.composition.navigation_runtime
        plan = navigation.prepare(target_id)
        if plan is None:
            return TranscriptNavigationResult(cancelled=False)
        summary_override: BranchSummaryOutput | None = None
        if self.ports.extension_runner is not None:
            (
                custom_instructions,
                replace_instructions,
                label,
                summary_override,
                cancelled,
            ) = await self._apply_before_tree_hook(
                plan,
                summarize=summarize,
                custom_instructions=custom_instructions,
                replace_instructions=replace_instructions,
                label=label,
            )
            if cancelled:
                return TranscriptNavigationResult(cancelled=True)
        result = await navigation.navigate(
            plan,
            summarize=summarize,
            label=label,
            summary_override=summary_override,
            summary_runner=(
                self._branch_summary_runner(
                    custom_instructions=custom_instructions,
                    replace_instructions=replace_instructions,
                )
                if summarize
                else None
            ),
        )
        if not summarize and self.ports.extension_runner is not None:
            await self.ports.extension_runner.emit_agent_event(
                {
                    "type": "session_tree",
                    "new_leaf_id": self.ports.session_manager.get_leaf_id(),
                    "old_leaf_id": plan.old_leaf_id,
                    "summary_entry": None,
                    "from_extension": False,
                },
                cwd=self.ports.session_manager.get_cwd(),
            )
        return result

    def abort_branch_summary(self) -> None:
        self.composition.navigation_runtime.abort()

    async def dispose(
        self, session_shutdown_event: SessionShutdownEvent | None = None
    ) -> None:
        try:
            await self.composition.resource_watch_controller.stop()
            if self.ports.extension_runner is not None:
                await self.ports.extension_runner.emit_session_shutdown(
                    session_shutdown_event or SessionShutdownEvent(reason="quit")
                )
        finally:
            self.ports.close_approvals()
            await self._dispose_runtime()

    async def dispose_after_session_shutdown(self) -> None:
        self.ports.close_approvals()
        await self._dispose_runtime()

    async def _dispose_runtime(self) -> None:
        task = asyncio.create_task(self._dispose_runtime_cancellation_atomic())
        await _await_cancellation_atomic(task)

    async def _dispose_runtime_cancellation_atomic(self) -> None:
        try:
            await self.composition.session_runtime.dispose()
        finally:
            try:
                await asyncio.gather(
                    self.composition.compaction_runtime.cancel_and_wait(),
                    self.composition.navigation_runtime.cancel_and_wait(),
                )
            finally:
                try:
                    extension_runtime = self.ports.extension_runner
                    dispose_generation = getattr(
                        extension_runtime,
                        "dispose_runtime_generation",
                        None,
                    )
                    if callable(dispose_generation):
                        generation_result = dispose_generation()
                        if asyncio.iscoroutine(generation_result):
                            await generation_result
                finally:
                    try:
                        result = self.ports.dispose_runtime_profile()
                        if asyncio.iscoroutine(result):
                            await result
                    finally:
                        try:
                            self.composition.capability_runtime.dispose()
                        finally:
                            self.ports.finalize_shutdown()

    async def _apply_before_tree_hook(
        self,
        plan: TranscriptNavigationPlan,
        *,
        summarize: bool,
        custom_instructions: str | None,
        replace_instructions: bool,
        label: str | None,
    ) -> tuple[str | None, bool, str | None, BranchSummaryOutput | None, bool]:
        decision = await self.ports.before_tree(
            plan,
            summarize=summarize,
            custom_instructions=custom_instructions,
            replace_instructions=replace_instructions,
            label=label,
        )
        if isinstance(decision, tuple) and len(decision) == 5:
            return decision
        if decision is None:
            return custom_instructions, replace_instructions, label, None, False
        if decision.cancel:
            self.ports.sync_extension_diagnostics(phase="runtime")
            return custom_instructions, replace_instructions, label, None, True
        return (
            decision.custom_instructions or custom_instructions,
            decision.replace_instructions
            if decision.replace_instructions is not None
            else replace_instructions,
            decision.label or label,
            normalize_branch_summary_output(
                decision.summary,
                from_hook=True,
            )
            if decision.summary is not None
            else None,
            False,
        )

    def _branch_summary_runner(
        self,
        *,
        custom_instructions: str | None,
        replace_instructions: bool,
    ) -> Callable[
        [Sequence[object], CancellationSignal], Awaitable[BranchSummaryOutput]
    ]:
        async def run(
            entries: Sequence[object],
            signal: CancellationSignal,
        ) -> BranchSummaryOutput:
            kwargs: dict[str, object] = {
                "model": self.ports.agent.model,
                "signal": signal,
                "custom_instructions": custom_instructions,
                "replace_instructions": replace_instructions,
            }
            if supports_prepare_model_call(self.ports.execute_branch_summary):
                kwargs["prepare_model_call"] = self.ports.agent.prepare_model_call
            return await self.ports.execute_branch_summary(entries, **kwargs)

        return run
__all__ = ["SessionOperations", "SessionOperationsPorts"]
