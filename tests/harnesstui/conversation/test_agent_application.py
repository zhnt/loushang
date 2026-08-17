from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

from loushang.ai.model import ModelSelection
from loushang.harness.commands import CommandDescriptor
from loushang.harnesstui.conversation.agent_application import (
    AgentPlainConversationApplicationBinding,
    AgentScreenConversationApplicationBinding,
    bind_agent_screen_approval_presenter,
    bind_agent_screen_session_transition,
    build_agent_screen_surface_workflow_ports,
    current_agent_runtime_session,
    handle_agent_screen_approval,
    refresh_agent_screen_session,
)
from loushang.harnesstui.conversation.host import (
    ConversationScreenRunProfile,
)
from loushang.harnesstui.conversation.run_context import RebindableEventSource
from loushang.harnesstui.conversation.startup import ConversationStartupView
from loushang.harnesstui.surface.controller import ApprovalSurfaceDecision


class _Manager:
    def get_branch(self) -> tuple[object, ...]:
        return ()


class _Session:
    session_manager = _Manager()
    settings_manager = None
    session_id = "research-session"

    def get_tool_definition(self, _name: str) -> None:
        return None

    def get_steering_messages(self) -> tuple[str, ...]:
        return ()

    def get_follow_up_messages(self) -> tuple[str, ...]:
        return ()

    def get_thinking_level(self) -> str:
        return "medium"


class _Surface:
    async def handle_text(self, _text: str) -> None:
        return None

    async def handle_surface_intent(self, _intent: object) -> None:
        return None

    def is_local_command(self, _text: str) -> bool:
        return False

    def clear_approval_surfaces(self) -> None:
        return None


def _startup() -> ConversationStartupView:
    return ConversationStartupView(
        model_label="research/model",
        cwd="/research",
        branch="main",
        project_label="research",
        session_label="Research",
        session_observability_id="research-session",
    )


def test_agent_screen_application_binding_prepares_shared_state() -> None:
    session = _Session()

    class App:
        state = SimpleNamespace(running=False)

        def set_statusline_settings(self, settings: object) -> None:
            self.settings = settings

    app = App()
    statuses: list[object] = []
    traces: list[tuple[str, dict[str, object]]] = []
    binding = AgentScreenConversationApplicationBinding(
        session=session,
        app=cast(Any, app),
        action_host=cast(Any, object()),
        build_surface=lambda status: statuses.append(status) or _Surface(),
        startup=_startup(),
        interaction_context=cast(Any, nullcontext()),
        profile=ConversationScreenRunProfile(
            input_router_factory=None,
            interruption_message="Interrupted",
            cancellation_message="Cancelled",
        ),
        trace=lambda name, **data: traces.append((name, data)),
        stdout=cast(Any, SimpleNamespace(write=lambda _value: None)),
        now=lambda: 1.0,
        resume_command_prefix=("research", "--resume"),
    )

    prepared = binding.prepare()

    assert prepared.app is app
    assert prepared.event_source is session
    assert prepared.history_records == ()
    assert prepared.should_exit("/quit") is True
    assert prepared.should_exit("continue") is False
    assert len(statuses) == 1
    prepared.on_start()
    assert traces == [
        (
            "tui.start",
            {
                "interactive": True,
                "model": "research/model",
                "cwd": "/research",
                "branch": "main",
                "session": "Research",
            },
        )
    ]


def test_agent_screen_surface_ports_bind_structural_research_session() -> None:
    labels: list[str] = []
    approvals: list[dict[str, object]] = []

    class ResearchSession:
        def get_model_selection(self) -> ModelSelection:
            return ModelSelection(
                endpoint_id="test-endpoint", provider="research", model_id="analyst"
            )

        def get_available_models(self) -> tuple[ModelSelection, ...]:
            return (
                ModelSelection(
                    endpoint_id="test-endpoint", provider="research", model_id="analyst"
                ),
                ModelSelection(
                    endpoint_id="test-endpoint",
                    provider="research",
                    model_id="reviewer",
                ),
            )

        async def list_commands(self) -> tuple[CommandDescriptor[object], ...]:
            return (
                CommandDescriptor(
                    name="report",
                    description="Build a research report",
                    source="research",
                ),
            )

    async def select_model(value: str) -> str:
        return f"Selected {value}"

    async def build_settings_content() -> object:
        return {"product": "research"}

    async def on_approval(event: dict[str, object]) -> bool:
        approvals.append(event)
        return True

    ports = build_agent_screen_surface_workflow_ports(
        ResearchSession(),
        select_model=select_model,
        set_model_label=labels.append,
        build_settings_content=build_settings_content,
        terminal_diagnostics=lambda: "research terminal",
        hotkeys=lambda: "research hotkeys",
        on_approval=on_approval,
    )

    assert asyncio.run(ports.format_commands("report")) == (
        "Commands:\n/report - Build a research report (research)"
    )
    assert "research:test-endpoint:analyst" in asyncio.run(ports.format_models(""))
    assert asyncio.run(ports.build_model_selector()).purpose == "model"
    assert asyncio.run(ports.build_command_selector()).purpose == "command"
    assert asyncio.run(ports.build_settings_content()) == {"product": "research"}
    asyncio.run(ports.refresh_model_label())
    assert labels == ["research:test-endpoint:analyst"]

    assert ports.decide_approval is not None
    assert asyncio.run(
        ports.decide_approval(
            ApprovalSurfaceDecision(
                action_id="research-approval",
                action="Publish report",
                outcome="allow_once",
                raw_note="approved",
            )
        )
    )
    assert approvals == [
        {
            "action_id": "research-approval",
            "action": "Publish report",
            "approved": True,
            "outcome": "allow_once",
            "scope": "once",
            "raw_note": "approved",
        }
    ]


def test_agent_screen_approval_binding_uses_structural_product_ports() -> None:
    presented: list[dict[str, object]] = []
    cleared: list[str] = []
    subscriptions: list[object] = []

    class Lease:
        def __init__(self, close) -> None:
            self._close = close

        def close(self, reason: str = "closed") -> None:
            del reason
            self._close()

    class Interaction:
        presenter: object | None = None

        def bind_presenter(
            self,
            presenter: object,
            *,
            dismisser: object | None = None,
        ) -> Lease:
            self.presenter = presenter
            self.dismisser = dismisser
            return Lease(lambda: setattr(self, "presenter", None))

        async def respond(
            self,
            action_id: str,
            *,
            outcome: str,
            reason: str | None = None,
        ) -> bool:
            del action_id, reason
            return outcome == "allow_once"

    class Surface:
        def open_approval(self, **payload: object) -> None:
            presented.append(payload)

        def dismiss_approval(self, action_id: str) -> None:
            presented.append({"dismissed": action_id})

        def clear_approval_surfaces(self) -> None:
            cleared.append("cleared")

    class Runtime:
        current_session: object | None

        def __init__(self, session: object) -> None:
            self.current_session = session

        def subscribe_after_session_invalidate(self, callback: object):
            subscriptions.append(callback)
            return lambda: subscriptions.append("unsubscribed")

        def set_rebind_session(self, callback: object | None) -> None:
            self.rebind = callback

    interaction = Interaction()
    session = object()
    surface = Surface()
    runtime = Runtime(session)
    unbind_presenter = bind_agent_screen_approval_presenter(
        interaction,
        surface,
        default_action="Approve operation",
    )

    def on_rebind(_session: object) -> None:
        return None

    unbind_transition = bind_agent_screen_session_transition(
        runtime,
        surface,
        on_rebind=on_rebind,
    )

    assert callable(interaction.presenter)
    interaction.presenter({"action_id": "approval-1"})  # type: ignore[operator]
    assert presented == [
        {
            "action": "Approve operation",
            "risk": "",
            "requester": "",
            "cwd": "",
            "environment": "",
            "grant_summary": "",
            "action_id": "approval-1",
            "allow_session": False,
            "options": (),
        }
    ]
    interaction.presenter(  # type: ignore[operator]
        {
            "action_id": "approval-2",
            "actor_id": "/root/reviewer#1",
            "cwd": "/repo",
            "environment": "local",
            "grant_summary": "Publish non-force refs to origin",
            "approval_options": ("allow_once", "allow_session", "deny"),
        }
    )
    assert presented[-1]["allow_session"] is True
    assert presented[-1]["requester"] == "/root/reviewer#1"
    assert presented[-1]["cwd"] == "/repo"
    assert presented[-1]["environment"] == "local"
    assert presented[-1]["grant_summary"] == "Publish non-force refs to origin"
    assert asyncio.run(
        handle_agent_screen_approval(
            interaction,
            {"action_id": "approval-2", "approved": True},
        )
    )
    assert current_agent_runtime_session(runtime, object()) is session
    assert callable(subscriptions[0])
    assert runtime.rebind is on_rebind
    subscriptions[0]()  # type: ignore[operator]
    assert cleared == ["cleared"]

    unbind_transition()
    unbind_presenter()
    assert subscriptions[-1] == "unsubscribed"
    assert runtime.rebind is None
    assert interaction.presenter is None


def test_refresh_agent_screen_session_replaces_history_and_event_source(
    tmp_path,
) -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp

    class Manager:
        def get_branch(self) -> tuple[object, ...]:
            return ()

        def get_cwd(self) -> str:
            return str(tmp_path)

    class Session:
        session_id = "resumed-session"
        session_name = "Resumed"
        session_manager = Manager()

        def get_model_selection(self) -> ModelSelection:
            return ModelSelection(
                endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
            )

    class Runtime:
        def get_cwd(self) -> str:
            return str(tmp_path)

    old_source = SimpleNamespace(subscribe=lambda _listener: lambda: None)
    event_source = RebindableEventSource(old_source)
    app = ScreenCodingTuiApp(
        model_label="old/model",
        cwd="/old",
        branch=None,
        session_label="old",
    )
    render_requests: list[str] = []
    app.render_requester = render_requests.append
    session = Session()

    asyncio.run(
        refresh_agent_screen_session(
            runtime=Runtime(),
            app=app,
            session=session,
            approval_interaction=None,
            event_source=event_source,
        )
    )

    assert event_source.source is session
    assert app.state.cwd == str(tmp_path)
    assert app.state.model_label == "openai:test-endpoint:gpt-5.4"
    assert app.state.session_label == "Resumed"
    assert app.state.records == []
    assert render_requests == ["product"]


def test_agent_screen_application_binding_owns_live_session_rebinding(
    tmp_path,
) -> None:
    class Manager:
        def get_branch(self) -> tuple[object, ...]:
            return ()

        def get_cwd(self) -> str:
            return str(tmp_path)

    class Interaction:
        def __init__(self, profile_id: str) -> None:
            self.profile_id = profile_id
            self.presenter: object | None = None

        def permission_profile_snapshot(self) -> object:
            return SimpleNamespace(
                effective_profile=SimpleNamespace(profile_id=self.profile_id)
            )

        def bind_presenter(
            self,
            presenter: object,
            *,
            dismisser: object | None = None,
        ) -> object:
            del dismisser
            self.presenter = presenter

            def close() -> None:
                self.presenter = None

            return SimpleNamespace(close=close)

    class Session:
        settings_manager = None

        def __init__(self, session_id: str, model: str, profile: str) -> None:
            self.session_id = session_id
            self.session_name = session_id.title()
            self.session_manager = Manager()
            self.model = model
            self.approval_interaction = Interaction(profile)

        def get_model_selection(self) -> ModelSelection:
            return ModelSelection(
                endpoint_id="test-endpoint", provider="research", model_id=self.model
            )

        def get_tool_definition(self, _name: str) -> None:
            return None

    class Runtime:
        def __init__(self, current_session: object) -> None:
            self.current_session = current_session
            self.rebind: object | None = None

        def get_cwd(self) -> str:
            return str(tmp_path)

        def set_rebind_session(self, callback: object | None) -> None:
            self.rebind = callback

        def subscribe_after_session_invalidate(self, _callback: object):
            return lambda: None

    class Composer:
        completion_provider: object | None = None

        def set_completion_provider(self, provider: object | None) -> None:
            self.completion_provider = provider

    class App:
        def __init__(self) -> None:
            self.state = SimpleNamespace(
                running=False,
                model_label="research/old",
                cwd=str(tmp_path),
                branch=None,
                session_label="Old",
                permission_profile="standard",
                records=[],
            )
            self.composer = Composer()
            self.errors: list[tuple[str, str]] = []

        def set_statusline_settings(self, settings: object) -> None:
            self.settings = settings

        def replace_transcript_window(
            self,
            records: tuple[object, ...],
            *,
            reason: str,
        ) -> None:
            del reason
            self.state.records = list(records)

        def trim_active_transcript_window(self) -> None:
            return None

        def request_render(self, _kind: str) -> None:
            return None

        def add_error(self, summary: str, diagnostics: str = "") -> None:
            self.errors.append((summary, diagnostics))

    class Surface(_Surface):
        def open_approval(self, **_payload: object) -> None:
            return None

        def dismiss_approval(self, _action_id: str) -> None:
            return None

    initial = Session("old", "analyst", "standard")
    resumed = Session("resumed", "reviewer", "review")
    runtime = Runtime(initial)
    app = App()
    event_source = RebindableEventSource(initial)
    statuses: list[object] = []
    loaded: list[tuple[object, str]] = []

    async def load_completion(session: object, cwd: str) -> object:
        loaded.append((session, cwd))
        return "resumed-completions"

    prepared = AgentScreenConversationApplicationBinding(
        session=initial,
        app=cast(Any, app),
        action_host=cast(Any, object()),
        build_surface=lambda status: statuses.append(status) or Surface(),
        startup=_startup(),
        interaction_context=cast(Any, nullcontext()),
        profile=ConversationScreenRunProfile(
            input_router_factory=None,
            interruption_message="Interrupted",
            cancellation_message="Cancelled",
        ),
        trace=lambda _name, **_data: None,
        stdout=cast(Any, SimpleNamespace(write=lambda _value: None)),
        now=lambda: 1.0,
        session_provider=lambda: runtime.current_session,
        approval_interaction_provider=lambda: getattr(
            runtime.current_session,
            "approval_interaction",
            None,
        ),
        event_source=event_source,
        runtime=runtime,
        completion_provider_loader=load_completion,
    ).prepare()

    unbind_presenter = prepared.bind_presenter()
    unbind_transition = prepared.bind_transition()
    assert initial.approval_interaction.presenter is not None
    assert callable(runtime.rebind)

    runtime.current_session = resumed
    asyncio.run(runtime.rebind(resumed))  # type: ignore[operator]

    assert event_source.source is resumed
    assert app.state.model_label == "research:test-endpoint:reviewer"
    assert app.state.session_label == "Resumed"
    assert app.state.permission_profile == "review"
    assert app.composer.completion_provider == "resumed-completions"
    assert loaded == [(resumed, str(tmp_path))]
    assert initial.approval_interaction.presenter is None
    assert resumed.approval_interaction.presenter is not None
    assert statuses[0].snapshot().model_label == "research:test-endpoint:reviewer"
    assert app.errors == []

    unbind_transition()
    unbind_presenter()
    assert runtime.rebind is None
    assert resumed.approval_interaction.presenter is None


def test_agent_plain_application_binding_prepares_projection_and_header() -> None:
    session = _Session()
    headers: list[dict[str, object]] = []
    app = object()
    renderer = SimpleNamespace(
        render_header=lambda **kwargs: headers.append(kwargs),
    )
    binding = AgentPlainConversationApplicationBinding(
        session=session,
        renderer=cast(Any, renderer),
        startup=_startup(),
        interaction_context=cast(Any, nullcontext()),
        build_app=lambda _event_renderer, _emit: cast(Any, app),
        trace=lambda _name, **_data: None,
    )

    prepared = binding.prepare()
    prepared.render_header()

    assert prepared.event_source is session
    assert prepared.build_app(cast(Any, lambda *_args, **_kwargs: None)) is app
    assert headers == [
        {
            "project_label": "research",
            "cwd": "/research",
            "branch": "main",
            "session_label": "Research",
            "model_label": "research/model",
        }
    ]
