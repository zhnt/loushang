from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import TypeVar, cast
from uuid import uuid4

from loushang.agent.types import (
    AfterToolCallResult,
    AgentMessage,
    BeforeToolCallResult,
)
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.agent.hooks import (
    BeforeAgentStartState,
    ExtensionPromptHookDispatcher,
    ExtensionSessionHookDispatcher,
    ExtensionToolHookDispatcher,
)
from loushang.harness.extensions.context import (
    BoundExtensionContext,
    ExtensionCommandContext,
    ExtensionContext,
    ExtensionRuntimeBindings,
    SessionActionDecision,
    SessionBeforeCompactResult,
    SessionBeforeForkResult,
    SessionBeforeTreeResult,
    SessionRefreshEvent,
    UnboundExtensionContext,
)
from loushang.harness.extensions.generation import (
    ExtensionGenerationDisposalResult,
    ExtensionGenerationRegistrations,
    dispose_extension_generation_registrations,
)
from loushang.harness.extensions.loader import ExtensionLoader
from loushang.harness.extensions.registry import (
    source_info_from_extension as _source_info_from_extension,
)
from loushang.harness.extensions.routing import ResolvedExtensionRoute
from loushang.harness.extensions.runtime import ExtensionRuntime
from loushang.harness.extensions.types import BeforeAgentStartResult, LoadedExtension
from loushang.harness.resources.types import (
    ExtensionDescriptor,
)
from loushang.harness.runtime import (
    RuntimeBindingState,
)
from loushang.harness.runtime.bindings import ProductRuntimeBindings
from loushang.harness.runtime.registration import (
    RegistrationIdentity,
    RegistrationLease,
    RegistrationLeaseState,
    RegistrationOwner,
)


class _RunnerContext(UnboundExtensionContext):
    pass


class _BoundExtensionContext(BoundExtensionContext):
    pass


T = TypeVar("T")


class _RunnerRuntimeState(RuntimeBindingState[ExtensionRuntimeBindings]):
    def __init__(self) -> None:
        super().__init__(
            unbound_message="Extension runner runtime bindings have not been set.",
            stale_message=(
                "Extension context is stale after session replacement or reload."
            ),
        )
        self.flag_values: dict[str, bool | str] = {}


class ExtensionGenerationRetirement:
    """Idempotently retire registrations from one replaced generation."""

    def __init__(
        self,
        runtime: ExtensionRunner,
        registrations: tuple[ExtensionGenerationRegistrations, ...],
    ) -> None:
        self._runtime = runtime
        self._registrations = registrations

    async def retire(self) -> tuple[ExtensionGenerationDisposalResult, ...]:
        return await self._runtime._retire_registrations(self._registrations)


class PreparedExtensionGeneration:
    """Unpublished Extension composition prepared by one stable runner."""

    def __init__(self, host: ExtensionRunner, candidate: ExtensionRunner) -> None:
        self._host = host
        self._candidate = candidate
        self._activated = False
        self._published = False
        self._owns_lifecycle = False

    async def discover_resources_async(
        self,
        bundle,
        *,
        reason: str = "reload",
    ):
        return await self._candidate.discover_resources_async(bundle, reason=reason)

    async def activate(self, bindings: ExtensionRuntimeBindings) -> None:
        if self._published:
            raise RuntimeError("Extension generation is already published")
        if self._activated:
            raise RuntimeError("Extension generation is already activated")
        await self._host._begin_generation_operation()
        self._owns_lifecycle = True
        try:
            await asyncio.sleep(0)
            self._candidate._activate_runtime(bindings, commit=False, staged=True)
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError
        except BaseException:
            try:
                await self._candidate._dispose_current_registrations()
            finally:
                self._release_lifecycle()
            raise
        self._activated = True

    def publish(
        self,
        commit_resource: Callable[[], object],
    ) -> ExtensionGenerationRetirement:
        """Publish atomically while retaining rollback ownership on failure."""

        if not self._activated:
            raise RuntimeError("Extension generation must be activated before publish")
        if self._published:
            raise RuntimeError("Extension generation is already published")
        retirement = self._host._publish_generation(
            self._candidate,
            commit_resource=commit_resource,
        )
        # Reaching this line proves publication succeeded. Failures leave the
        # gate owned until rollback has disposed the staged registrations.
        self._release_lifecycle()
        self._published = True
        return retirement

    async def rollback(self) -> tuple[ExtensionGenerationDisposalResult, ...]:
        if self._published:
            raise RuntimeError("Published Extension generation cannot be rolled back")
        try:
            return await self._candidate._dispose_current_registrations()
        finally:
            try:
                if self._candidate._has_pending_registration_cleanup():
                    self._host._retain_retired_generation_registrations(
                        self._candidate._generation_registrations
                    )
            finally:
                self._release_lifecycle()

    def _release_lifecycle(self) -> None:
        if not self._owns_lifecycle:
            return
        self._owns_lifecycle = False
        self._host._finish_generation_operation()


@dataclass(frozen=True)
class _BeforeAgentStartContext:
    base: ExtensionContext
    get_system_prompt: Callable[[], str]

    def __getattr__(self, name: str):
        return getattr(self.base, name)

    @property
    def ui(self):
        return self.base.ui

    @property
    def has_ui(self) -> bool:
        return self.base.has_ui

    @property
    def cwd(self) -> str:
        return self.base.cwd


class ExtensionRunner(ExtensionRuntime):
    def __init__(
        self,
        extensions: Sequence[LoadedExtension | ExtensionDescriptor] | None = None,
        *,
        loader_factory: Callable[[], ExtensionLoader] = ExtensionLoader,
        _runtime_id: str | None = None,
        _generation: int = 1,
        _bootstrap_generation: bool = True,
    ) -> None:
        if isinstance(_generation, bool) or not isinstance(_generation, int):
            raise TypeError("Extension generation must be an integer")
        if _generation < 1:
            raise ValueError("Extension generation must be at least 1")
        self._diagnostics: list[DiagnosticDraft] = []
        self._runtime_state = _RunnerRuntimeState()
        self._loader_factory = loader_factory
        self._runtime_id = _runtime_id or uuid4().hex
        self._generation = _generation
        self._bootstrap_generation = _bootstrap_generation
        self._activated_generation = False
        self._runtime_disposed = False
        self._generation_lifecycle_lock = asyncio.Lock()
        self._retired_generation_registrations: list[
            tuple[ExtensionGenerationRegistrations, ...]
        ] = []
        loader = loader_factory()
        loaded_extensions: list[LoadedExtension] = []

        for extension in extensions or []:
            if isinstance(extension, ExtensionDescriptor):
                loaded_extension = loader.load_extension(extension)
                self._diagnostics.extend(loader.get_diagnostics())
                loader = loader_factory()
                if loaded_extension is None:
                    continue
            else:
                loaded_extension = extension
            loaded_extensions.append(loaded_extension)
            self._diagnostics.extend(loaded_extension.diagnostics)
        super().__init__(
            loaded_extensions,
            context_factory=lambda fallback_cwd, extension: self._context_from_runtime(
                fallback_cwd=fallback_cwd,
                extension=extension,
            ),
            resource_context_factory=lambda cwd: _RunnerContext(cwd=cwd),
            diagnostics=self._diagnostics,
            runtime_error_handler=self._emit_runtime_error,
        )
        self._runtime_state.flag_values = self._flag_values
        self._generation_registrations = tuple(
            ExtensionGenerationRegistrations(
                RegistrationOwner(
                    owner_kind="extension",
                    owner_id=extension.name,
                    runtime_id=self._runtime_id,
                    generation=self._generation,
                )
            )
            for extension in self._active_extensions
        )
        self._registrations_by_extension = {
            id(extension): registrations
            for extension, registrations in zip(
                self._active_extensions,
                self._generation_registrations,
                strict=True,
            )
        }

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def registration_inventory(
        self,
    ) -> tuple[
        tuple[RegistrationOwner, RegistrationIdentity, RegistrationLeaseState], ...
    ]:
        return tuple(
            item
            for registrations in self._generation_registrations
            for item in registrations.inventory
        )

    @property
    def retired_registration_inventory(
        self,
    ) -> tuple[
        tuple[RegistrationOwner, RegistrationIdentity, RegistrationLeaseState], ...
    ]:
        """Return exact registrations retained for retirement retry."""

        return tuple(
            item
            for generation in self._retired_generation_registrations
            for registrations in generation
            for item in registrations.inventory
        )

    def create_command_context(
        self, *, fallback_cwd: str = ""
    ) -> ExtensionCommandContext:
        return self._context_from_runtime(fallback_cwd=fallback_cwd)

    async def emit_user_bash(self, event: object, *, cwd: str = "") -> object | None:
        return await super().emit_user_bash(_event_object(event), cwd=cwd)

    async def emit_agent_event(self, event: object, *, cwd: str = "") -> None:
        event_type = _event_type(event)
        if event_type is None:
            return
        await super().emit_event(
            event_type,
            _event_object(event),
            cwd=cwd,
        )

    def bind_runtime(self, bindings: ExtensionRuntimeBindings) -> None:
        self._require_runtime_active()
        try:
            self._activate_runtime(
                bindings,
                commit=True,
                staged=self._supports_staged_activation(bindings),
            )
            self._commit_api_admission()
        except BaseException as admission_error:
            self._rollback_initial_admission(admission_error)
            raise

    async def activate_runtime_generation(
        self,
        bindings: ExtensionRuntimeBindings,
    ) -> None:
        self._require_runtime_active()
        if self._activated_generation:
            self.refresh_runtime(bindings)
            return
        try:
            await asyncio.sleep(0)
            self._activate_runtime(
                bindings,
                commit=True,
                staged=self._supports_staged_activation(bindings),
            )
            self._commit_api_admission()
        except BaseException:
            await self._dispose_current_registrations()
            raise

    def refresh_runtime(self, bindings: ExtensionRuntimeBindings) -> None:
        self._require_runtime_active()
        self._runtime_state.refresh(bindings)
        self._bind_extension_apis()

    def prepare_generation(
        self,
        extensions: Sequence[LoadedExtension | ExtensionDescriptor],
    ) -> PreparedExtensionGeneration:
        if self._runtime_disposed:
            raise RuntimeError("Extension runtime is disposed")
        active_extension_ids = {id(extension) for extension in self._active_extensions}
        active_api_ids = {
            id(extension.api)
            for extension in self._active_extensions
            if extension.api is not None
        }
        if any(
            isinstance(extension, LoadedExtension)
            and (
                id(extension) in active_extension_ids
                or (
                    extension.api is not None
                    and id(extension.api) in active_api_ids
                )
            )
            for extension in extensions
        ):
            raise ValueError(
                "Extension generation cannot reuse an active LoadedExtension or API"
            )
        candidate = ExtensionRunner(
            extensions,
            loader_factory=self._loader_factory,
            _runtime_id=self._runtime_id,
            _generation=self._generation + 1,
            _bootstrap_generation=False,
        )
        candidate._flag_values.update(
            {
                name: value
                for name, value in self._flag_values.items()
                if name in {flag.name for flag in candidate._resolved_flags}
            }
        )
        candidate._runtime_state.flag_values = candidate._flag_values
        return PreparedExtensionGeneration(self, candidate)

    async def dispose_runtime_generation(
        self,
    ) -> tuple[ExtensionGenerationDisposalResult, ...]:
        return await _join_cancellation_atomic(
            asyncio.create_task(self._dispose_runtime_generation_sweep())
        )

    async def _dispose_runtime_generation_sweep(
        self,
    ) -> tuple[ExtensionGenerationDisposalResult, ...]:
        async with self._generation_lifecycle_lock:
            self._runtime_disposed = True
            self._runtime_state.invalidate(
                "Extension context is stale after extension runtime disposal."
            )
            reports: list[ExtensionGenerationDisposalResult] = []
            retained: list[tuple[ExtensionGenerationRegistrations, ...]] = []
            for generation in self._retired_generation_registrations:
                generation_reports = (
                    await dispose_extension_generation_registrations(generation)
                )
                reports.extend(generation_reports)
                if any(report.has_failures for report in generation_reports):
                    retained.append(generation)
            current_reports = await dispose_extension_generation_registrations(
                self._generation_registrations
            )
            reports.extend(current_reports)
            self._retired_generation_registrations = retained
            return tuple(reports)

    def _require_runtime_active(self) -> None:
        if self._runtime_disposed:
            raise RuntimeError("Extension runtime is disposed")

    async def _begin_generation_operation(self) -> None:
        await self._generation_lifecycle_lock.acquire()
        if self._runtime_disposed:
            self._generation_lifecycle_lock.release()
            raise RuntimeError("Extension runtime is disposed")

    def _finish_generation_operation(self) -> None:
        if not self._generation_lifecycle_lock.locked():
            raise RuntimeError("Extension generation lifecycle is not active")
        self._generation_lifecycle_lock.release()

    def _activate_runtime(
        self,
        bindings: ExtensionRuntimeBindings,
        *,
        commit: bool,
        staged: bool,
    ) -> None:
        self._require_runtime_active()
        if not isinstance(bindings, ProductRuntimeBindings):
            raise TypeError("Extension runtime bindings are invalid")
        if self._activated_generation:
            self.refresh_runtime(bindings)
            return
        resolved_bindings = self._bindings_for_activation(bindings, staged=staged)
        self._runtime_state.bind(resolved_bindings)
        self._bind_extension_apis()
        self._bind_declared_tools(resolved_bindings)
        if commit:
            committed: list[ExtensionGenerationRegistrations] = []
            try:
                for registrations in self._generation_registrations:
                    registrations.commit()
                    committed.append(registrations)
            except BaseException as commit_error:
                for registrations in reversed(committed):
                    try:
                        registrations.rollback_publication()
                    except BaseException:
                        commit_error.add_note(
                            "Extension registration commit rollback failed"
                        )
                raise
        self._activated_generation = True

    @staticmethod
    def _supports_staged_activation(bindings: ExtensionRuntimeBindings) -> bool:
        return (
            (bindings.bind_tool is None or bindings.stage_tool is not None)
            and (
                bindings.bind_provider is None
                or bindings.stage_provider is not None
            )
            and (
                bindings.bind_provider_removal is None
                or bindings.stage_provider_removal is not None
            )
        )

    @staticmethod
    def _bindings_for_activation(
        bindings: ExtensionRuntimeBindings,
        *,
        staged: bool,
    ) -> ExtensionRuntimeBindings:
        if not staged:
            return bindings
        if bindings.bind_tool is not None and bindings.stage_tool is None:
            raise RuntimeError("Extension Tool binding does not support staging")
        if bindings.bind_provider is not None and bindings.stage_provider is None:
            raise RuntimeError("Extension Provider binding does not support staging")
        if (
            bindings.bind_provider_removal is not None
            and bindings.stage_provider_removal is None
        ):
            raise RuntimeError(
                "Extension Provider removal does not support staging"
            )
        return replace(
            bindings,
            bind_tool=cast(
                Callable[
                    [object, RegistrationOwner | str, object | None],
                    RegistrationLease,
                ]
                | None,
                bindings.stage_tool,
            ),
            bind_provider=bindings.stage_provider,
            bind_provider_removal=bindings.stage_provider_removal,
        )

    def _bind_declared_tools(self, bindings: ExtensionRuntimeBindings) -> None:
        binder = bindings.bind_tool
        adopter = bindings.adopt_tool if self._bootstrap_generation else None
        if binder is None:
            return
        for definition in self._tool_definitions:
            extension_name = self.get_tool_extension_name(definition.name)
            extension = next(
                (
                    item
                    for item in self._active_extensions
                    if item.name == extension_name
                ),
                None,
            )
            if extension is None:
                continue
            registrations = self._registrations_by_extension[id(extension)]
            if adopter is not None:
                lease = adopter(
                    definition,
                    registrations.owner,
                    self.get_tool_source_info(definition.name),
                )
                if lease is None:
                    # Bootstrap composition already resolved Product/Extension
                    # conflicts. A missing exact match means this declaration
                    # was intentionally not admitted and must stay skipped.
                    continue
            else:
                lease = binder(
                    definition,
                    registrations.owner,
                    self.get_tool_source_info(definition.name),
                )
            if not isinstance(lease, RegistrationLease):
                raise TypeError("live tool binding must return a RegistrationLease")
            registrations.capture(lease)

    def _rollback_initial_admission(self, error: BaseException) -> None:
        for extension in self._active_extensions:
            rollback = getattr(extension.api, "_rollback_runtime_admission", None)
            if callable(rollback):
                try:
                    rollback()
                except BaseException:
                    error.add_note("Extension API admission rollback failed")
        for registrations in reversed(self._generation_registrations):
            try:
                report = registrations.rollback_admission()
            except BaseException:
                error.add_note("Extension admission rollback failed")
                continue
            if report.has_failures:
                error.add_note("Extension admission rollback was incomplete")
        self._runtime_state.invalidate(
            "Extension context is stale after failed extension admission."
        )

    def _commit_api_admission(self) -> None:
        for extension in self._active_extensions:
            commit = getattr(extension.api, "_commit_runtime_admission", None)
            if callable(commit):
                commit()

    def _bind_extension_apis(self) -> None:
        for extension in self._active_extensions:
            self._bind_extension_api(extension)

    def _bind_extension_api(self, extension: LoadedExtension) -> None:
        binder = getattr(extension.api, "bind_runtime_state", None)
        if callable(binder):
            registrations = self._registrations_by_extension.get(id(extension))
            if _accepts_registration_collector(binder):
                binder(self._runtime_state, registrations)
            else:
                binder(self._runtime_state)

    def invalidate_contexts(
        self,
        message: str = "Extension context is stale after session replacement or reload.",
    ) -> None:
        self._runtime_state.invalidate(message)

    async def emit_session_start(self, session: object) -> None:
        await self._emit_session_hook("session_start", session)

    async def emit_session_refresh(self, event: SessionRefreshEvent) -> None:
        await self._emit_session_hook("session_refresh", event)

    async def emit_before_agent_start(
        self,
        *,
        prompt: str,
        images: list[object] | None = None,
        system_prompt: str | None = None,
        system_prompt_options: object | None = None,
        cwd: str = "",
    ) -> BeforeAgentStartResult | None:
        prompt_state = [system_prompt or ""]

        def event_factory(
            state: BeforeAgentStartState,
            route: ResolvedExtensionRoute,
        ) -> _ExtensionEvent:
            del route
            prompt_state[0] = state.system_prompt
            return _ExtensionEvent(
                type="before_agent_start",
                prompt=prompt,
                images=images,
                system_prompt=state.system_prompt,
                system_prompt_options=system_prompt_options,
            )

        result = await ExtensionPromptHookDispatcher(
            self._plain_diagnostic_router,
            diagnostics=self._diagnostics,
        ).reduce_before_agent_start(
            system_prompt=system_prompt or "",
            context_factory=lambda extension: _BeforeAgentStartContext(
                base=self._context_from_runtime(
                    fallback_cwd=cwd,
                    extension=extension,
                ),
                get_system_prompt=lambda: prompt_state[0],
            ),
            event_factory=event_factory,
            result_coercer=_coerce_before_agent_start_result,
        )
        if result is not None and result.system_prompt is not None:
            prompt_state[0] = result.system_prompt
        return result

    async def emit_session_shutdown(self, session: object) -> None:
        await self._emit_session_hook("session_shutdown", session)

    async def before_session_switch(
        self, event: object
    ) -> SessionActionDecision | None:
        return await self._emit_decision_hook(
            "session_before_switch", event, fallback_cwd=getattr(event, "cwd", "")
        )

    async def before_session_fork(
        self, event: object
    ) -> SessionBeforeForkResult | None:
        return cast(
            SessionBeforeForkResult | None,
            await self._emit_decision_hook(
                "session_before_fork",
                event,
                fallback_cwd=getattr(event, "cwd", ""),
                result_type=SessionBeforeForkResult,
                decision_coercer=lambda result: SessionBeforeForkResult(
                    cancel=result.cancel,
                    diagnostics=result.diagnostics,
                ),
            ),
        )

    async def before_session_compact(
        self, event: object
    ) -> SessionBeforeCompactResult | None:
        return cast(
            SessionBeforeCompactResult | None,
            await self._emit_decision_hook(
                "session_before_compact",
                event,
                fallback_cwd=getattr(event, "cwd", ""),
                result_type=SessionBeforeCompactResult,
                decision_coercer=lambda result: SessionBeforeCompactResult(
                    cancel=result.cancel,
                    diagnostics=result.diagnostics,
                ),
            ),
        )

    async def before_session_tree(
        self, event: object
    ) -> SessionBeforeTreeResult | None:
        return cast(
            SessionBeforeTreeResult | None,
            await self._emit_decision_hook(
                "session_before_tree",
                event,
                fallback_cwd=getattr(event, "cwd", ""),
                result_type=SessionBeforeTreeResult,
                decision_coercer=lambda result: SessionBeforeTreeResult(
                    cancel=result.cancel,
                    diagnostics=result.diagnostics,
                ),
            ),
        )

    async def emit_context(
        self,
        messages: list[AgentMessage],
        signal: object | None = None,
        *,
        cwd: str = "",
    ) -> list[AgentMessage]:
        del signal
        return await ExtensionPromptHookDispatcher(
            self._plain_diagnostic_router,
            diagnostics=self._diagnostics,
        ).transform_context(
            messages,
            context_factory=lambda extension: self._context_from_runtime(
                fallback_cwd=cwd,
                extension=extension,
            ),
        )

    async def before_tool_call(
        self, event, signal: object | None = None
    ) -> BeforeToolCallResult | None:
        return await self._tool_hook_dispatcher(
            _context_from_agent_event(event).cwd
        ).before_tool_call(event, signal)

    async def after_tool_call(
        self, event, signal: object | None = None
    ) -> AfterToolCallResult | None:
        return await self._tool_hook_dispatcher(
            _context_from_agent_event(event).cwd
        ).after_tool_call(event, signal)

    def _tool_hook_dispatcher(self, fallback_cwd: str) -> ExtensionToolHookDispatcher:
        return ExtensionToolHookDispatcher(
            self._extensions,
            context_factory=lambda extension: self._context_from_runtime(
                fallback_cwd=fallback_cwd,
                extension=extension,
            ),
            diagnostics=self._diagnostics,
            runtime_error_handler=lambda extension, event, error: (
                self._emit_runtime_error(
                    extension=extension,
                    event=event,
                    error=error,
                )
            ),
            route_plan=self._route_plan,
        )

    async def _emit_session_hook(self, hook_name: str, session: object) -> None:
        fallback_cwd = _context_from_session(session).cwd
        await ExtensionSessionHookDispatcher(
            self._router,
            diagnostics=self._diagnostics,
        ).observe_session(
            hook_name,
            session,
            context_factory=lambda extension: self._context_from_runtime(
                fallback_cwd=fallback_cwd,
                extension=extension,
            ),
        )

    async def _emit_decision_hook(
        self,
        hook_name: str,
        event: object,
        *,
        fallback_cwd: str,
        result_type: type[SessionActionDecision] = SessionActionDecision,
        decision_coercer: Callable[[SessionActionDecision], SessionActionDecision]
        | None = None,
    ) -> SessionActionDecision | None:
        return await ExtensionSessionHookDispatcher(
            self._router,
            diagnostics=self._diagnostics,
        ).reduce_session_decision(
            hook_name,
            event,
            context_factory=lambda extension: self._context_from_runtime(
                fallback_cwd=fallback_cwd,
                extension=extension,
            ),
            result_type=result_type,
            decision_coercer=decision_coercer,
        )

    def _context_from_runtime(
        self,
        *,
        fallback_cwd: str = "",
        extension: LoadedExtension | None = None,
    ) -> ExtensionContext:
        if not self._runtime_state.is_bound:
            return cast(
                ExtensionContext,
                _RunnerContext(
                    cwd=fallback_cwd,
                    get_flag_value=self.get_flag_value,
                ),
            )
        return cast(
            ExtensionContext,
            _BoundExtensionContext(
                self._runtime_state.capture(),
                (
                    _source_info_from_extension(extension)
                    if extension is not None
                    else None
                ),
                tool_owner_id=(extension.name if extension is not None else None),
                registrations=(
                    self._registrations_by_extension.get(id(extension))
                    if extension is not None
                    else None
                ),
                get_flag_value=self.get_flag_value,
            ),
        )

    def _publish_generation(
        self,
        candidate: ExtensionRunner,
        *,
        commit_resource: Callable[[], object],
    ) -> ExtensionGenerationRetirement:
        if candidate._runtime_id != self._runtime_id:
            raise ValueError("Extension candidate belongs to another runtime")
        if candidate.generation != self._generation + 1:
            raise ValueError("Extension candidate generation is stale")
        if not candidate._activated_generation:
            raise RuntimeError("Extension candidate is not activated")
        if self._runtime_disposed:
            raise RuntimeError("Extension runtime is disposed")
        previous_state = self._capture_composition_state()
        previous_runtime_state = self._runtime_state
        previous_registrations = self._generation_registrations
        previous_registrations_by_extension = self._registrations_by_extension
        previous_generation = self._generation
        previous_activated = self._activated_generation
        try:
            for registrations in candidate._generation_registrations:
                registrations.commit()
            candidate._commit_api_admission()
            self._install_composition_state(candidate._capture_composition_state())
            self._runtime_state = candidate._runtime_state
            self._generation_registrations = candidate._generation_registrations
            self._registrations_by_extension = (
                candidate._registrations_by_extension
            )
            self._generation = candidate._generation
            self._activated_generation = True
            self._bootstrap_generation = False
            self._runtime_state.flag_values = self._flag_values
            commit_resource()
        except BaseException as publication_error:
            for registrations in reversed(candidate._generation_registrations):
                try:
                    registrations.rollback_publication()
                except BaseException:
                    publication_error.add_note(
                        "candidate registration publication rollback failed"
                    )
            self._install_composition_state(previous_state)
            self._runtime_state = previous_runtime_state
            self._generation_registrations = previous_registrations
            self._registrations_by_extension = previous_registrations_by_extension
            self._generation = previous_generation
            self._activated_generation = previous_activated
            self._runtime_state.flag_values = self._flag_values
            raise

        self._diagnostics.extend(candidate._diagnostics)
        previous_runtime_state.invalidate(
            "Extension context is stale after extension generation replacement."
        )
        self._retired_generation_registrations.append(previous_registrations)
        return ExtensionGenerationRetirement(self, previous_registrations)

    def _has_pending_registration_cleanup(self) -> bool:
        return any(
            state != "disposed"
            for registrations in self._generation_registrations
            for _, _, state in registrations.inventory
        )

    def _retain_retired_generation_registrations(
        self,
        registrations: tuple[ExtensionGenerationRegistrations, ...],
    ) -> None:
        if not registrations or any(
            retained is registrations
            for retained in self._retired_generation_registrations
        ):
            return
        self._retired_generation_registrations.append(registrations)

    async def _dispose_current_registrations(
        self,
    ) -> tuple[ExtensionGenerationDisposalResult, ...]:
        self._runtime_state.invalidate(
            "Extension context is stale after extension generation rollback."
        )
        return await dispose_extension_generation_registrations(
            self._generation_registrations
        )

    async def _retire_registrations(
        self,
        registrations: tuple[ExtensionGenerationRegistrations, ...],
    ) -> tuple[ExtensionGenerationDisposalResult, ...]:
        return await _join_cancellation_atomic(
            asyncio.create_task(self._retire_registrations_once(registrations))
        )

    async def _retire_registrations_once(
        self,
        registrations: tuple[ExtensionGenerationRegistrations, ...],
    ) -> tuple[ExtensionGenerationDisposalResult, ...]:
        async with self._generation_lifecycle_lock:
            reports = await dispose_extension_generation_registrations(registrations)
            if not any(report.has_failures for report in reports):
                self._retired_generation_registrations = [
                    retained
                    for retained in self._retired_generation_registrations
                    if retained is not registrations
                ]
            return reports

    def _emit_runtime_error(
        self,
        extension: LoadedExtension,
        event: str,
        error: Exception,
    ) -> None:
        bindings = self._runtime_state.bindings
        callback = getattr(bindings, "on_error", None) if bindings is not None else None
        if not callable(callback):
            return
        callback(
            {
                "extensionPath": str(extension.source_path),
                "event": event,
                "error": str(error),
            }
        )


def _accepts_registration_collector(callback: Callable[..., object]) -> bool:
    """Preserve the historical one-argument duck-typed API binding seam."""

    try:
        parameters = tuple(inspect.signature(callback).parameters.values())
    except (TypeError, ValueError):
        return False
    positional = tuple(
        parameter
        for parameter in parameters
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    )
    return len(positional) >= 2 or any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in parameters
    )


async def _join_cancellation_atomic(task: asyncio.Task[T]) -> T:
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if caller is None or caller.cancelling() == 0:
                return task.result()
            cancellation = exc
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


def _context_from_session(session: object) -> _RunnerContext:
    session_manager = getattr(session, "session_manager", None)
    get_cwd = getattr(session_manager, "get_cwd", None)
    if callable(get_cwd):
        return _RunnerContext(cwd=str(get_cwd()))
    return _RunnerContext(cwd="")


def _context_from_agent_event(event: object) -> _RunnerContext:
    agent_context = getattr(event, "context", None)
    messages = getattr(agent_context, "messages", None)
    if isinstance(messages, list):
        return _RunnerContext(cwd="")
    return _RunnerContext(cwd="")


def _event_type(event: object) -> str | None:
    if isinstance(event, dict):
        value = event.get("type")
        return value if isinstance(value, str) else None
    value = getattr(event, "type", None)
    return value if isinstance(value, str) else None


def _event_object(event: object) -> object:
    if not isinstance(event, dict):
        return event
    return _ExtensionEvent(**event)


@dataclass
class _ExtensionEvent:
    def __init__(self, **values: object) -> None:
        for key, value in values.items():
            setattr(self, key, value)


def _coerce_before_agent_start_result(result: object) -> BeforeAgentStartResult | None:
    if result is None:
        return None
    if isinstance(result, BeforeAgentStartResult):
        return result
    if isinstance(result, dict):
        system_prompt = result.get("system_prompt")
        system_prompt_append = result.get("system_prompt_append", "")
        extra_messages = result.get("extra_messages", result.get("messages", []))
        diagnostics = result.get("diagnostics", [])
        return BeforeAgentStartResult(
            system_prompt=system_prompt if isinstance(system_prompt, str) else None,
            system_prompt_append=system_prompt_append
            if isinstance(system_prompt_append, str)
            else "",
            extra_messages=extra_messages if isinstance(extra_messages, list) else [],
            diagnostics=diagnostics if isinstance(diagnostics, list) else [],
        )
    return None


__all__ = [
    "ExtensionGenerationRetirement",
    "ExtensionRunner",
    "PreparedExtensionGeneration",
]
