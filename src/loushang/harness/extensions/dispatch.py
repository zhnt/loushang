from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.routing import (
    ExtensionContextFactory,
    ExtensionRoutePlan,
    ExtensionRouter,
    ExtensionRuntimeErrorHandler,
    ResolvedExtensionRoute,
    RouteStep,
)
from loushang.harness.extensions.types import (
    InputEvent,
    InputEventResult,
    InputSource,
    LoadedExtension,
)


class ExtensionDispatcher:
    """Ordered, failure-contained dispatch for product-neutral extension hooks."""

    def __init__(
        self,
        extensions: Sequence[LoadedExtension],
        *,
        context_factory: ExtensionContextFactory,
        diagnostics: list[DiagnosticDraft],
        runtime_error_handler: ExtensionRuntimeErrorHandler | None = None,
        route_plan: ExtensionRoutePlan | None = None,
    ) -> None:
        self._context_factory = context_factory
        self._diagnostics = diagnostics
        plan = route_plan or ExtensionRoutePlan.from_extensions(
            extensions, diagnostics=diagnostics
        )
        self._router = ExtensionRouter(
            plan,
            diagnostics=diagnostics,
            runtime_error_handler=runtime_error_handler,
            include_route_id_in_error_metadata=False,
        )

    def has_handlers(self, event_name: str) -> bool:
        return self._router.has_handlers(event_name)

    async def dispatch(self, event_name: str, event: object) -> tuple[object, ...]:
        return await self._router.observe(
            event_name,
            event,
            context_factory=self._context_factory,
        )

    async def dispatch_first_truthy(
        self, event_name: str, event: object
    ) -> object | None:
        return await self._router.first(
            event_name,
            event,
            predicate=bool,
            context_factory=self._context_factory,
        )

    async def dispatch_input(
        self,
        text: str,
        images: list[object] | None = None,
        *,
        source: str = "interactive",
    ) -> InputEventResult:
        initial = _InputDispatchState(text=text, images=images)

        def event_factory(
            state: _InputDispatchState,
            route: ResolvedExtensionRoute,
        ) -> InputEvent:
            del route
            return InputEvent(
                text=state.text,
                images=state.images,
                source=_normalize_input_source(source),
            )

        def reducer(
            state: _InputDispatchState,
            result: object,
            route: ResolvedExtensionRoute,
        ) -> RouteStep[_InputDispatchState]:
            action, result_text, result_images = _coerce_input_result(result)
            if action in {None, "continue"}:
                return RouteStep(state)
            if action == "handled":
                return RouteStep(
                    _InputDispatchState(
                        text=state.text,
                        images=state.images,
                        action="handled",
                        transformed=state.transformed,
                    ),
                    stop=True,
                )
            if action == "transform":
                if result_text is None:
                    self._diagnostics.append(
                        _invalid_input_diagnostic(
                            route.extension,
                            "input transform results must include string text.",
                        )
                    )
                    return RouteStep(state)
                return RouteStep(
                    _InputDispatchState(
                        text=result_text,
                        images=(
                            result_images if result_images is not None else state.images
                        ),
                        transformed=True,
                    )
                )
            self._diagnostics.append(
                _invalid_input_diagnostic(
                    route.extension,
                    (
                        "input hooks must return action 'continue', 'transform', "
                        "'handled', or None."
                    ),
                )
            )
            return RouteStep(state)

        outcome = await self._router.intercept(
            "input",
            initial,
            event_factory=event_factory,
            reducer=reducer,
            context_factory=self._context_factory,
        )
        state = outcome.state
        if state.action == "handled":
            return InputEventResult(
                action="handled",
                text=state.text,
                images=state.images,
            )
        if state.transformed or state.text != text or state.images is not images:
            return InputEventResult(
                action="transform",
                text=state.text,
                images=state.images,
            )
        return InputEventResult(
            action="continue",
            text=state.text,
            images=state.images,
        )


@dataclass(frozen=True)
class _InputDispatchState:
    text: str
    images: list[object] | None
    action: str = "continue"
    transformed: bool = False


def _normalize_input_source(source: str) -> InputSource:
    if source == "rpc":
        return "rpc"
    if source == "extension":
        return "extension"
    return "interactive"


def _coerce_input_result(
    result: object,
) -> tuple[str | None, str | None, list[object] | None]:
    if result is None:
        return None, None, None
    if isinstance(result, InputEventResult):
        return result.action, result.text, result.images
    if isinstance(result, dict):
        action = result.get("action")
        text = result.get("text")
        images = result.get("images")
        return (
            action if isinstance(action, str) else None,
            text if isinstance(text, str) else None,
            images if isinstance(images, list) else None,
        )
    return None, None, None


def _invalid_input_diagnostic(
    extension: LoadedExtension,
    message: str,
) -> DiagnosticDraft:
    return DiagnosticDraft(
        code="invalid_extension_input_result",
        message=message,
        source_path=extension.source_path,
    )


__all__ = [
    "ExtensionContextFactory",
    "ExtensionDispatcher",
    "ExtensionRuntimeErrorHandler",
]
