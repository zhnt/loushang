from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

import loushang.harness.session.bootstrap_construction as bootstrap_construction_module
from loushang.ai.model import ModelSelection
from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
from loushang.harness.bootstrap import BootstrapActivationRuntime
from loushang.harness.config.agent import ControlConfig
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.session.bootstrap import (
    AgentBootstrapRequest,
    AgentBootstrapRuntime,
    AgentProductConstructionBinding,
    AgentProductConstructionPorts,
    AgentProductConstructionRequest,
    AgentProductConstructionRuntime,
    AgentSessionConstructionRequest,
    AgentSessionConstructionRuntime,
    BootstrapServices,
    StandardAgentSessionActivationEffects,
    StandardAgentSessionConfigurationResult,
    activate_standard_agent_session_configuration,
    build_standard_agent_session_result,
    create_standard_agent_bootstrap_services,
    standard_agent_session_activation_plan,
)
from loushang.harness.workspace.exec import ExecService


def test_agent_bootstrap_runtime_builds_agent_and_product_session() -> None:
    calls: list[tuple[str, object]] = []

    class FakeAgent:
        session_id = None

    def agent_factory(**kwargs):
        calls.append(("agent", kwargs))
        return FakeAgent()

    request = AgentBootstrapRequest(
        session_id="session-1",
        system_prompt="prompt",
        thinking_level="off",
        model=None,
        convert_to_llm=lambda value: value,
        steering_mode="one-at-a-time",
        follow_up_mode="one-at-a-time",
        thinking_budgets={"high": 100},
        max_retry_delay_ms=50,
    )

    result = AgentBootstrapRuntime[FakeAgent, str]().construct(
        request,
        agent_factory=agent_factory,
        session_factory=lambda agent: f"session:{agent.session_id}",
    )

    assert result == "session:session-1"
    assert calls[0][1]["initial_state"] == {
        "system_prompt": "prompt",
        "thinking_level": "off",
        "tools": [],
    }
    assert calls[0][1]["max_retry_delay_ms"] == 50


def test_standard_agent_services_bind_research_resources_and_shared_defaults() -> None:
    class ResearchResourceLoader:
        pass

    loader = ResearchResourceLoader()
    diagnostics = DiagnosticsService()
    exec_service = ExecService()
    ai_registry = AiModelRegistry()

    services = create_standard_agent_bootstrap_services(
        resource_loader_factory=lambda: loader,
        ai_model_registry=ai_registry,
        diagnostics_service=diagnostics,
        exec_service=exec_service,
        default_model=ModelSelection(
            provider="research",
            endpoint_id="test-endpoint",
            model_id="primary",
        ),
        thinking_level="medium",
        system_prompt="Use primary sources.",
    )

    assert services.resource_loader is loader
    assert services.model_registry.ai_registry is ai_registry
    assert services.diagnostics_service is diagnostics
    assert services.exec_service is exec_service
    settings = services.settings_manager.get_settings()
    assert settings.default_model == ModelSelection(
        provider="research",
        endpoint_id="test-endpoint",
        model_id="primary",
    )
    assert settings.thinking_level == "medium"
    assert settings.system_prompt == "Use primary sources."


def test_standard_agent_session_result_collects_scoped_diagnostics() -> None:
    diagnostics = DiagnosticsService()
    diagnostics.capture_failure(
        code="research_source_unavailable",
        error="source unavailable",
        phase="runtime",
        source="session",
        session_id="research-session",
    )
    diagnostics.capture_failure(
        code="other_session_failure",
        error="other failure",
        phase="runtime",
        source="session",
        session_id="other-session",
    )
    session = object()
    bundle = {"sources": ["paper"]}

    result = build_standard_agent_session_result(
        session,
        resource_bundle=bundle,
        diagnostics_service=diagnostics,
        session_id="research-session",
        cwd_bound_services_audit="research-audit",
    )

    assert result.session is session
    assert result.resource_bundle is bundle
    assert tuple(record.code for record in result.diagnostics) == (
        "research_source_unavailable",
    )
    assert result.cwd_bound_services_audit == "research-audit"


def test_agent_session_construction_runtime_uses_product_callbacks() -> None:
    class FakeAgent:
        session_id = None

    diagnostics: list[object] = []
    request = AgentSessionConstructionRequest(
        session_id="session-2",
        base_prompt="base",
        resolved_prompt="resolved",
        thinking_level="off",
        model=None,
        convert_to_llm=lambda value: value,
        steering_mode="one-at-a-time",
        follow_up_mode="one-at-a-time",
        thinking_budgets={},
        max_retry_delay_ms=None,
        stream_fn=None,
        resource_bundle={"resources": []},
        tools=None,
        tool_registry=None,
        allowed_tool_names=None,
        active_tool_names=None,
        no_tools_mode=None,
    )

    result = AgentSessionConstructionRuntime[
        FakeAgent,
        str,
        dict,
        object,
        object,
    ]().construct(
        request,
        agent_factory=lambda **kwargs: FakeAgent(),
        register_extension_tools=lambda bundle, registry: (
            bundle,
            registry,
            ["extension-diagnostic"],
        ),
        record_extension_diagnostics=diagnostics.extend,
        registry_factory=object,
        register_tool=lambda _registry, _tool: None,
        session_factory=lambda agent, bundle, registry, active, prompt, mode: (
            agent.session_id,
            bundle,
            active,
            prompt,
            mode,
        ),
    )

    assert result == ("session-2", {"resources": []}, None, "base", None)
    assert diagnostics == ["extension-diagnostic"]


def test_agent_product_construction_runtime_composes_existing_owners(
    monkeypatch,
) -> None:
    actions: list[tuple[object, ...]] = []
    settings = SimpleNamespace(
        system_prompt="configured",
        default_model=None,
        steering_mode="one-at-a-time",
        follow_up_mode="all",
        thinking_budgets={},
        retry=SimpleNamespace(provider_max_retry_delay_ms=25),
        enabled_models=("research/*",),
    )
    diagnostics = SimpleNamespace(
        record_drafts=lambda values, **kwargs: actions.append(
            ("diagnostics", tuple(values), kwargs)
        )
    )
    extension_runtime = object()
    configuration = cast(
        Any,
        SimpleNamespace(
            settings=settings,
            session_id="research-session",
            resource_loader=object(),
            model_registry=SimpleNamespace(
                build_model=lambda selection: selection,
                ai_registry=SimpleNamespace(get_endpoint=lambda _selection: None),
                get_model=lambda pattern: f"model:{pattern}",
            ),
            diagnostics_service=diagnostics,
        ),
    )
    monkeypatch.setattr(
        bootstrap_construction_module.StandardAgentSessionConfigurationRuntime,
        "configure",
        lambda _self, _request: StandardAgentSessionConfigurationResult(
            resource_bundle={"resources": []},
            extension_runtime=extension_runtime,
            cwd_bound_services_audit=cast(Any, "audit"),
        ),
    )
    monkeypatch.setattr(
        bootstrap_construction_module,
        "resolve_base_system_prompt",
        lambda **_kwargs: "base prompt",
    )
    monkeypatch.setattr(
        bootstrap_construction_module,
        "assemble_prompt",
        lambda **_kwargs: SimpleNamespace(system_prompt="assembled prompt"),
    )
    monkeypatch.setattr(
        bootstrap_construction_module,
        "resolve_session_model",
        lambda *_args, **_kwargs: "resolved-model",
    )
    monkeypatch.setattr(
        bootstrap_construction_module,
        "register_resource_extension_tools",
        lambda **kwargs: (
            kwargs["resource_bundle"],
            kwargs["tool_registry"],
            ("extension-diagnostic",),
        ),
    )
    monkeypatch.setattr(
        bootstrap_construction_module,
        "scoped_models_from_patterns",
        lambda patterns, **_kwargs: tuple(patterns),
    )

    class FakeAgent:
        session_id = None

    disposed: list[bool] = []
    result = AgentProductConstructionRuntime[
        FakeAgent,
        tuple[object, ...],
        object,
    ]().construct(
        AgentProductConstructionRequest(
            configuration=configuration,
            ports=AgentProductConstructionPorts(
                activate_resources=lambda bundle: bundle,
                prompt_section_composer=object(),
                tool_pack_composer=object(),
                list_tool_definitions=lambda _runtime: (),
                get_tool_source_info=lambda _runtime, _name: None,
                dispose_capabilities=lambda: disposed.append(True),
            ),
            default_system_prompt="research default",
            explicit_system_prompt=None,
            append_system_prompt=(),
            model=None,
            thinking_level="off",
            tools=None,
            tool_registry=None,
            allowed_tool_names=None,
            active_tool_names=None,
            no_tools=None,
            stream_fn=None,
            convert_to_llm=lambda value: value,
            agent_factory=lambda **kwargs: (
                actions.append(("agent", kwargs)) or FakeAgent()
            ),
            session_factory=lambda agent, bundle, extensions, registry, active, prompt, mode: (
                agent.session_id,
                bundle,
                extensions,
                registry,
                active,
                prompt,
                mode,
            ),
            on_default_model_unavailable=lambda *_args: None,
            set_scoped_models=lambda session, models: actions.append(
                ("scoped-models", session, tuple(models))
            ),
        )
    )

    assert result.session == (
        "research-session",
        {"resources": []},
        extension_runtime,
        None,
        None,
        "base prompt",
        None,
    )
    assert result.configuration.cwd_bound_services_audit == "audit"
    assert actions[0][0] == "diagnostics"
    assert actions[1][0] == "agent"
    assert actions[1][1]["initial_state"]["system_prompt"] == "assembled prompt"
    assert actions[1][1]["initial_state"]["model"] == "resolved-model"
    assert actions[2][0] == "scoped-models"
    assert disposed == []


def test_agent_product_construction_binding_compiles_research_policy(
    monkeypatch,
) -> None:
    captured: list[AgentProductConstructionRequest] = []
    expected_result = SimpleNamespace(session="research-session")
    monkeypatch.setattr(
        bootstrap_construction_module.AgentProductConstructionRuntime,
        "construct",
        lambda _self, request: captured.append(request) or expected_result,
    )
    settings = SimpleNamespace(thinking_level="medium")
    services = BootstrapServices(
        settings_manager=SimpleNamespace(get_settings=lambda: settings),
        model_registry=object(),
        resource_loader=object(),
        diagnostics_service=object(),
    )
    capability_runtime = cast(
        Any,
        SimpleNamespace(
            skill_activation="research-skills",
            activate_resources=lambda bundle: bundle,
            prompt_section_composer="research-prompts",
            tool_pack_composer="research-tools",
            dispose=lambda: None,
        ),
    )
    binding = AgentProductConstructionBinding[
        object,
        object,
        object,
    ](
        default_system_prompt="research default",
        bind_capabilities=lambda: capability_runtime,
        create_extension_runtime=lambda bundle: bundle,
        source_identity_check=lambda _cwd: cast(Any, None),
        list_tool_definitions=lambda _runtime: (),
        get_tool_source_info=lambda _runtime, _name: None,
        product_tool_pack_id="research.registry",
        extension_tool_pack_id="research.extensions",
    )
    session_capabilities: list[object] = []

    def legacy_session_factory(
        capabilities,
        _agent,
        _bundle,
        _extensions,
        _registry,
        _active,
        _prompt,
        _mode,
    ):
        session_capabilities.append(capabilities)
        return object()

    result = binding.construct(
        services=services,
        package_materializer=cast(Any, "materializer"),
        session_id="research-session",
        cwd="/research",
        extension_flag_values={"citations": True},
        explicit_system_prompt=None,
        append_system_prompt=("Use primary sources.",),
        model=None,
        thinking_level=None,
        tools=None,
        tool_registry=None,
        allowed_tool_names=None,
        active_tool_names=None,
        no_tools=None,
        stream_fn=None,
        convert_to_llm=lambda value: value,
        agent_factory=lambda **_kwargs: object(),
        session_factory=legacy_session_factory,
        on_default_model_unavailable=lambda *_args: None,
        set_scoped_models=lambda *_args: None,
    )

    assert result is expected_result
    request = captured[0]
    assert request.configuration.settings is settings
    assert request.configuration.skill_activation_runtime == "research-skills"
    assert request.configuration.session_id == "research-session"
    assert request.configuration.cwd == "/research"
    assert request.default_system_prompt == "research default"
    assert request.thinking_level == "medium"
    assert request.product_tool_pack_id == "research.registry"
    assert request.extension_tool_pack_id == "research.extensions"
    assert request.ports.prompt_section_composer == "research-prompts"
    assert request.ports.tool_pack_composer == "research-tools"
    request.session_factory(
        object(),
        object(),
        object(),
        None,
        None,
        "research prompt",
        None,
    )
    assert session_capabilities == [capability_runtime]


def test_agent_product_construction_late_binds_session_capabilities_and_disposes_bootstrap(
    monkeypatch,
) -> None:
    calls: list[str] = []
    bootstrap_capabilities = cast(
        Any,
        SimpleNamespace(
            skill_activation="bootstrap-skills",
            activate_resources=lambda bundle: bundle,
            prompt_section_composer="bootstrap-prompts",
            tool_pack_composer="bootstrap-tools",
            dispose=lambda: calls.append("dispose:bootstrap"),
        ),
    )
    session_capabilities = cast(
        Any,
        SimpleNamespace(dispose=lambda: calls.append("dispose:session")),
    )
    side_question_binding = cast(
        Any,
        SimpleNamespace(dispose=lambda: calls.append("dispose:side-question")),
    )

    def construct(_self, request):
        request.session_factory(
            object(),
            object(),
            "extensions",
            None,
            None,
            "prompt",
            None,
        )
        return SimpleNamespace(session="session")

    monkeypatch.setattr(
        bootstrap_construction_module.AgentProductConstructionRuntime,
        "construct",
        construct,
    )
    services = BootstrapServices(
        settings_manager=SimpleNamespace(
            get_settings=lambda: SimpleNamespace(thinking_level="off")
        ),
        model_registry=object(),
        resource_loader=object(),
        diagnostics_service=object(),
    )
    bound_sessions: list[object] = []
    binding = AgentProductConstructionBinding[
        object,
        object,
        object,
    ](
        default_system_prompt="research",
        bind_capabilities=lambda: bootstrap_capabilities,
        bind_session_capabilities=lambda extensions: (
            calls.append(f"bind:{extensions}") or session_capabilities
        ),
        bind_session_side_question=lambda _extensions: side_question_binding,
        create_extension_runtime=lambda bundle: bundle,
        source_identity_check=lambda _cwd: cast(Any, None),
        list_tool_definitions=lambda _runtime: (),
        get_tool_source_info=lambda _runtime, _name: None,
    )

    binding.construct(
        services=services,
        package_materializer=cast(Any, "materializer"),
        session_id="session",
        cwd="/research",
        extension_flag_values=None,
        explicit_system_prompt=None,
        append_system_prompt=(),
        model=None,
        thinking_level=None,
        tools=None,
        tool_registry=None,
        allowed_tool_names=None,
        active_tool_names=None,
        no_tools=None,
        stream_fn=None,
        convert_to_llm=lambda value: value,
        agent_factory=lambda **_kwargs: object(),
        session_factory=lambda capabilities, *_args: (
            bound_sessions.append(capabilities) or object()
        ),
        on_default_model_unavailable=lambda *_args: None,
        set_scoped_models=lambda *_args: None,
    )

    assert bound_sessions == [session_capabilities]
    assert calls == ["bind:extensions", "dispose:bootstrap"]


def test_agent_product_construction_disposes_late_bound_capabilities_on_failure(
    monkeypatch,
) -> None:
    calls: list[str] = []
    bootstrap_capabilities = cast(
        Any,
        SimpleNamespace(
            skill_activation="bootstrap-skills",
            activate_resources=lambda bundle: bundle,
            prompt_section_composer="bootstrap-prompts",
            tool_pack_composer="bootstrap-tools",
            dispose=lambda: calls.append("dispose:bootstrap"),
        ),
    )
    session_capabilities = cast(
        Any,
        SimpleNamespace(dispose=lambda: calls.append("dispose:session")),
    )
    side_question_binding = cast(
        Any,
        SimpleNamespace(dispose=lambda: calls.append("dispose:side-question")),
    )

    def construct(_self, request):
        request.session_factory(
            object(),
            object(),
            "extensions",
            None,
            None,
            "prompt",
            None,
        )
        raise RuntimeError("construction failed after final binding")

    monkeypatch.setattr(
        bootstrap_construction_module.AgentProductConstructionRuntime,
        "construct",
        construct,
    )
    services = BootstrapServices(
        settings_manager=SimpleNamespace(
            get_settings=lambda: SimpleNamespace(thinking_level="off")
        ),
        model_registry=object(),
        resource_loader=object(),
        diagnostics_service=object(),
    )
    binding = AgentProductConstructionBinding[
        object,
        object,
        object,
    ](
        default_system_prompt="research",
        bind_capabilities=lambda: bootstrap_capabilities,
        bind_session_capabilities=lambda _extensions: session_capabilities,
        bind_session_side_question=lambda _extensions: side_question_binding,
        create_extension_runtime=lambda bundle: bundle,
        source_identity_check=lambda _cwd: cast(Any, None),
        list_tool_definitions=lambda _runtime: (),
        get_tool_source_info=lambda _runtime, _name: None,
    )

    with pytest.raises(
        RuntimeError,
        match="construction failed after final binding",
    ):
        binding.construct(
            services=services,
            package_materializer=cast(Any, "materializer"),
            session_id="session",
            cwd="/research",
            extension_flag_values=None,
            explicit_system_prompt=None,
            append_system_prompt=(),
            model=None,
            thinking_level=None,
            tools=None,
            tool_registry=None,
            allowed_tool_names=None,
            active_tool_names=None,
            no_tools=None,
            stream_fn=None,
            convert_to_llm=lambda value: value,
            agent_factory=lambda **_kwargs: object(),
            session_factory=lambda _capabilities, *_args: object(),
            on_default_model_unavailable=lambda *_args: None,
            set_scoped_models=lambda *_args: None,
        )

    assert calls == [
        "dispose:side-question",
        "dispose:session",
        "dispose:bootstrap",
    ]


def test_agent_product_construction_disposes_session_if_bootstrap_cleanup_fails(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def dispose_bootstrap() -> None:
        calls.append("dispose:bootstrap")
        raise RuntimeError("bootstrap cleanup failed")

    bootstrap_capabilities = cast(
        Any,
        SimpleNamespace(
            skill_activation="bootstrap-skills",
            activate_resources=lambda bundle: bundle,
            prompt_section_composer="bootstrap-prompts",
            tool_pack_composer="bootstrap-tools",
            dispose=dispose_bootstrap,
        ),
    )
    session_capabilities = cast(
        Any,
        SimpleNamespace(dispose=lambda: calls.append("dispose:session")),
    )
    side_question_binding = cast(
        Any,
        SimpleNamespace(dispose=lambda: calls.append("dispose:side-question")),
    )

    def construct(_self, request):
        request.session_factory(
            object(),
            object(),
            "extensions",
            None,
            None,
            "prompt",
            None,
        )
        return SimpleNamespace(session="session")

    monkeypatch.setattr(
        bootstrap_construction_module.AgentProductConstructionRuntime,
        "construct",
        construct,
    )
    services = BootstrapServices(
        settings_manager=SimpleNamespace(
            get_settings=lambda: SimpleNamespace(thinking_level="off")
        ),
        model_registry=object(),
        resource_loader=object(),
        diagnostics_service=object(),
    )
    binding = AgentProductConstructionBinding[
        object,
        object,
        object,
    ](
        default_system_prompt="research",
        bind_capabilities=lambda: bootstrap_capabilities,
        bind_session_capabilities=lambda _extensions: session_capabilities,
        bind_session_side_question=lambda _extensions: side_question_binding,
        create_extension_runtime=lambda bundle: bundle,
        source_identity_check=lambda _cwd: cast(Any, None),
        list_tool_definitions=lambda _runtime: (),
        get_tool_source_info=lambda _runtime, _name: None,
    )

    with pytest.raises(RuntimeError, match="bootstrap cleanup failed"):
        binding.construct(
            services=services,
            package_materializer=cast(Any, "materializer"),
            session_id="session",
            cwd="/research",
            extension_flag_values=None,
            explicit_system_prompt=None,
            append_system_prompt=(),
            model=None,
            thinking_level=None,
            tools=None,
            tool_registry=None,
            allowed_tool_names=None,
            active_tool_names=None,
            no_tools=None,
            stream_fn=None,
            convert_to_llm=lambda value: value,
            agent_factory=lambda **_kwargs: object(),
            session_factory=lambda _capabilities, *_args: object(),
            on_default_model_unavailable=lambda *_args: None,
            set_scoped_models=lambda *_args: None,
        )

    assert calls == [
        "dispose:bootstrap",
        "dispose:side-question",
        "dispose:session",
    ]


def test_standard_agent_session_activation_plan_preserves_capability_order() -> None:
    calls: list[str] = []

    def effect(name: str):
        return lambda _selection, _context: calls.append(name)

    runtime = BootstrapActivationRuntime(
        standard_agent_session_activation_plan(
            StandardAgentSessionActivationEffects(
                startup_checks=effect("startup_checks"),
                package_sources=effect("package_sources"),
                resource_roots=effect("resource_roots"),
                resources=effect("resources"),
                extensions=effect("extensions"),
                cwd_audit=effect("cwd_audit"),
                model_registry=effect("model_registry"),
            )
        )
    )

    result = runtime.activate(ControlConfig(), object())

    assert result.report.ok
    assert calls == [
        "startup_checks",
        "package_sources",
        "resource_roots",
        "resources",
        "extensions",
        "cwd_audit",
        "model_registry",
    ]


def test_standard_agent_session_activation_propagates_first_failure() -> None:
    def effect(name: str):
        def apply(_selection, _context):
            if name == "resources":
                raise RuntimeError("resource failure")

        return apply

    effects = StandardAgentSessionActivationEffects(
        startup_checks=effect("startup_checks"),
        package_sources=effect("package_sources"),
        resource_roots=effect("resource_roots"),
        resources=effect("resources"),
        extensions=effect("extensions"),
        cwd_audit=effect("cwd_audit"),
        model_registry=effect("model_registry"),
    )

    try:
        activate_standard_agent_session_configuration(
            ControlConfig(),
            object(),
            effects=effects,
        )
    except RuntimeError as error:
        assert str(error) == "resource failure"
    else:
        raise AssertionError("activation failure was not propagated")
