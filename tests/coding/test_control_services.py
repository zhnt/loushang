from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from loushang.ai.model import Capabilities, Model


def _runtime_footer(cwd: str) -> str:
    return f"Current date: {date.today().isoformat()}\nCurrent working directory: {cwd}"


def _model(
    model_id: str,
    *,
    provider: str = "faux",
    endpoint: str = "anthropic-messages",
    name: str | None = None,
) -> Model:
    return Model(
        id=model_id,
        name=name,
        provider=provider,
        endpoint=endpoint,
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def test_control_config_exposes_stable_slice_objects() -> None:
    from loushang.coding.control import (
        BranchSummarySettings,
        CompactionSettings,
        ControlConfig,
        ImageSettings,
        RetrySettings,
    )

    config = ControlConfig()

    assert config.compaction == CompactionSettings()
    assert config.branch_summary == BranchSummarySettings()
    assert config.retry == RetrySettings()
    assert config.images == ImageSettings()


def test_settings_manager_updates_slice_objects_and_notifies_subscribers() -> None:
    from loushang.coding.control import (
        BranchSummarySettings,
        CompactionSettings,
        ImageSettings,
        RetrySettings,
        SettingsManager,
    )

    manager = SettingsManager()
    seen = []
    manager.subscribe(seen.append)

    manager.update_settings(
        compaction=CompactionSettings(
            enabled=False, reserve_tokens=2048, keep_recent_tokens=8192
        ),
        branch_summary=BranchSummarySettings(enabled=False, reserve_tokens=1024),
        retry=RetrySettings(enabled=False, max_retries=1, base_delay_ms=50),
        images=ImageSettings(auto_resize=False, block_images=True),
    )

    settings = manager.get_settings()
    assert settings.compaction == CompactionSettings(
        enabled=False, reserve_tokens=2048, keep_recent_tokens=8192
    )
    assert settings.branch_summary == BranchSummarySettings(
        enabled=False, reserve_tokens=1024
    )
    assert settings.retry == RetrySettings(
        enabled=False, max_retries=1, base_delay_ms=50
    )
    assert settings.images == ImageSettings(auto_resize=False, block_images=True)
    assert seen[-1] == settings


def test_settings_manager_apply_overrides_is_session_only_and_flush_is_awaitable(
    tmp_path,
) -> None:
    import asyncio
    import json

    from loushang.coding.control import SettingsManager

    global_settings_path = tmp_path / "global-settings.json"
    global_settings_path.write_text(
        json.dumps(
            {
                "thinking_level": "low",
                "compaction": {"enabled": True, "reserve_tokens": 2048},
            }
        ),
        encoding="utf-8",
    )
    manager = SettingsManager(global_settings_path=global_settings_path)
    seen = []
    manager.subscribe(seen.append)

    manager.apply_overrides(
        {
            "thinking_level": "high",
            "compaction": {"enabled": False},
        }
    )
    asyncio.run(manager.flush())

    assert manager.get_settings().thinking_level == "high"
    assert manager.get_compaction_settings().enabled is False
    assert manager.get_compaction_settings().reserve_tokens == 2048
    assert json.loads(global_settings_path.read_text(encoding="utf-8")) == {
        "thinking_level": "low",
        "compaction": {"enabled": True, "reserve_tokens": 2048},
    }
    assert seen[-1] == manager.get_settings()


def test_create_services_provides_settings_and_model_resolution_for_sessions(
    tmp_path,
) -> None:
    from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.session import ModelSelection
    from loushang.coding.session_manager import SessionManager

    services = create_services(ai_model_registry=AiModelRegistry())
    services.model_registry.register_model(_model("alpha", name="Alpha"))
    services.settings_manager.set_default_model(
        ModelSelection(
            endpoint_id="anthropic-messages", provider="faux", model_id="alpha"
        )
    )
    services.settings_manager.update_settings(
        system_prompt="Be precise.", thinking_level="high"
    )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    session = create_agent_session(session_manager=manager, services=services)

    assert session.get_model_selection() == ModelSelection(
        endpoint_id="anthropic-messages", provider="faux", model_id="alpha"
    )
    assert (
        session.agent.system_prompt
        == f"Be precise.\n\n{_runtime_footer(str(Path('/tmp/project').resolve()))}"
    )
    assert session.agent.thinking_level == "high"


def test_model_registry_resolves_each_complete_endpoint_selection() -> None:
    from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
    from loushang.coding.session import ModelSelection
    from loushang.foundation.observability._router import (
        get_problem_store,
        reset_observability,
    )
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    registry = ModelRegistry(ai_registry=AiModelRegistry())
    registry.register_model(
        _model("alpha", provider="faux", endpoint="anthropic-messages")
    )
    registry.register_model(
        _model("alpha", provider="faux", endpoint="openai-responses")
    )

    reset_observability()
    try:
        messages = registry.build_model(
            ModelSelection(
                endpoint_id="anthropic-messages",
                provider="faux",
                model_id="alpha",
            )
        )
        responses = registry.build_model(
            ModelSelection(
                endpoint_id="openai-responses",
                provider="faux",
                model_id="alpha",
            )
        )

        assert messages.endpoint_id == "anthropic-messages"
        assert responses.endpoint_id == "openai-responses"
        assert get_problem_store().all() == []
    finally:
        reset_observability()


def test_model_registry_records_problem_for_missing_model_selection() -> None:
    import pytest

    from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
    from loushang.coding.session import ModelSelection
    from loushang.foundation.observability._router import (
        get_problem_store,
        reset_observability,
    )
    from loushang.harness.model_catalog import ModelCatalog as ModelRegistry

    registry = ModelRegistry(ai_registry=AiModelRegistry())

    reset_observability()
    try:
        with pytest.raises(KeyError):
            registry.build_model(
                ModelSelection(
                    endpoint_id="test-endpoint", provider="faux", model_id="missing"
                )
            )

        records = get_problem_store().all()
        assert len(records) == 1
        assert records[0].code == "model_selection_not_found"
        assert records[0].source == "config"
        assert records[0].recoverable is True
        assert (
            records[0].message
            == "Model selection not found: faux:test-endpoint:missing"
        )
        assert records[0].details == {
            "endpoint_id": "test-endpoint",
            "model_id": "missing",
            "provider_id": "faux",
        }
    finally:
        reset_observability()


def test_runtime_uses_latest_settings_for_new_sessions(tmp_path) -> None:
    from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
    from loushang.coding.bootstrap import create_agent_session_runtime, create_services
    from loushang.coding.session import ModelSelection

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()

    services = create_services(ai_model_registry=AiModelRegistry())
    services.model_registry.register_model(_model("alpha", name="Alpha"))
    services.model_registry.register_model(
        _model("beta", endpoint="responses", name="Beta")
    )
    services.settings_manager.set_default_model(
        ModelSelection(
            endpoint_id="anthropic-messages", provider="faux", model_id="alpha"
        )
    )

    runtime = create_agent_session_runtime(
        session_dir=tmp_path, services=services, persist=False
    )
    first = asyncio.run(runtime.create_session(cwd=str(project_a)))

    services.settings_manager.set_default_model(
        ModelSelection(endpoint_id="responses", provider="faux", model_id="beta")
    )
    services.settings_manager.update_settings(thinking_level="minimal")
    second = asyncio.run(runtime.create_session(cwd=str(project_b)))

    assert first.get_model_selection() == ModelSelection(
        endpoint_id="anthropic-messages", provider="faux", model_id="alpha"
    )
    assert second.get_model_selection() == ModelSelection(
        endpoint_id="responses", provider="faux", model_id="beta"
    )
    assert second.agent.thinking_level == "minimal"


def test_create_services_can_use_preloaded_persistent_settings_manager(
    tmp_path,
) -> None:
    import json

    from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import SettingsManager
    from loushang.coding.session import ModelSelection
    from loushang.coding.session_manager import SessionManager

    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"
    project_root = tmp_path / "project"
    project_root.mkdir()

    global_settings_path.write_text(
        json.dumps(
            {
                "default_model": {
                    "provider": "faux",
                    "endpoint_id": "anthropic-messages",
                    "model_id": "alpha",
                },
                "thinking_level": "minimal",
            }
        ),
        encoding="utf-8",
    )
    project_settings_path.write_text(
        json.dumps(
            {
                "system_prompt": "Use project policy.",
            }
        ),
        encoding="utf-8",
    )

    settings_manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )
    services = create_services(
        ai_model_registry=AiModelRegistry(),
        settings_manager=settings_manager,
    )
    services.model_registry.register_model(_model("alpha", name="Alpha"))

    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(project_root), persist=False
        )
    )
    session = create_agent_session(session_manager=manager, services=services)

    assert session.get_model_selection() == ModelSelection(
        endpoint_id="anthropic-messages", provider="faux", model_id="alpha"
    )
    assert session.agent.thinking_level == "minimal"
    assert (
        session.agent.system_prompt
        == f"Use project policy.\n\n{_runtime_footer(str(project_root))}"
    )


def test_session_restores_persisted_model_and_accepts_model_selection_updates(
    tmp_path,
) -> None:
    from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.session import ModelSelection
    from loushang.coding.session_manager import SessionManager

    services = create_services(ai_model_registry=AiModelRegistry())
    services.model_registry.register_model(_model("alpha", name="Alpha"))
    services.model_registry.register_model(
        _model("beta", endpoint="responses", name="Beta")
    )
    services.settings_manager.set_default_model(
        ModelSelection(
            endpoint_id="anthropic-messages", provider="faux", model_id="alpha"
        )
    )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(manager.append_model_change("faux", "beta", endpoint_id="responses"))

    session = create_agent_session(session_manager=manager, services=services)

    assert session.get_model_selection() == ModelSelection(
        endpoint_id="responses", provider="faux", model_id="beta"
    )

    asyncio.run(
        session.set_model(
            ModelSelection(
                endpoint_id="anthropic-messages",
                provider="faux",
                model_id="alpha",
            )
        )
    )

    assert session.get_model_selection() == ModelSelection(
        endpoint_id="anthropic-messages", provider="faux", model_id="alpha"
    )
    assert [entry.kind for entry in manager.get_entries()] == [
        "agent.model_selection",
        "agent.model_selection",
    ]
