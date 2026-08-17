from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from loushang.ai.model import ModelSelection


class _SettingsManager:
    def __init__(self) -> None:
        self.default_model_calls: list[tuple[ModelSelection | None, str]] = []

    def set_default_model(
        self,
        selection: ModelSelection | None,
        *,
        scope: str = "session",
    ) -> None:
        self.default_model_calls.append((selection, scope))


class _Session:
    def __init__(self) -> None:
        self.settings_manager = _SettingsManager()
        self.set_model_calls: list[object] = []

    async def set_model(self, selection: object) -> None:
        self.set_model_calls.append(selection)


class _FailingSession(_Session):
    async def set_model(self, selection: object) -> None:
        self.set_model_calls.append(selection)
        raise RuntimeError("model unavailable")


class _FailingSettingsManager(_SettingsManager):
    def set_default_model(
        self,
        selection: ModelSelection | None,
        *,
        scope: str = "session",
    ) -> None:
        super().set_default_model(selection, scope=scope)
        raise OSError("disk full")


def test_apply_model_selection_persists_global_default_after_runtime_switch() -> None:
    from loushang.coding.model_selection import apply_model_selection

    session = _Session()
    detail = SimpleNamespace(
        provider_id="dashscope",
        endpoint_id="openai-responses",
        id="qwen3.6-plus",
    )

    result = asyncio.run(apply_model_selection(session, detail))

    expected = ModelSelection(
        provider="dashscope",
        endpoint_id="openai-responses",
        model_id="qwen3.6-plus",
    )
    assert result.selection == expected
    assert result.persistence_error is None
    assert session.set_model_calls == [expected]
    assert session.settings_manager.default_model_calls == [(expected, "global")]


def test_apply_model_selection_writes_global_settings_not_project(tmp_path) -> None:
    from loushang.coding.control import SettingsManager
    from loushang.coding.model_selection import apply_model_selection

    session = _Session()
    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"
    session.settings_manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )
    selection = ModelSelection(
        provider="openai",
        endpoint_id="responses",
        model_id="gpt-5.4",
    )

    result = asyncio.run(apply_model_selection(session, selection))

    assert result.persisted is True
    assert json.loads(global_settings_path.read_text(encoding="utf-8")) == {
        "default_model": {
            "provider": "openai",
            "model_id": "gpt-5.4",
            "endpoint_id": "responses",
        }
    }
    assert not project_settings_path.exists()


def test_apply_model_selection_does_not_persist_when_runtime_switch_fails() -> None:
    from loushang.coding.model_selection import apply_model_selection

    session = _FailingSession()

    with pytest.raises(RuntimeError, match="model unavailable"):
        asyncio.run(
            apply_model_selection(
                session,
                ModelSelection(
                    endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
                ),
            )
        )

    assert session.settings_manager.default_model_calls == []


def test_apply_model_selection_reports_persistence_failure_after_runtime_switch() -> (
    None
):
    from loushang.coding.model_selection import apply_model_selection

    session = _Session()
    session.settings_manager = _FailingSettingsManager()
    selection = ModelSelection(
        provider="openai",
        endpoint_id="responses",
        model_id="gpt-5.4",
    )

    result = asyncio.run(apply_model_selection(session, selection))

    assert session.set_model_calls == [selection]
    assert result.selection == selection
    assert isinstance(result.persistence_error, OSError)
    assert session.settings_manager.default_model_calls == [(selection, "global")]
