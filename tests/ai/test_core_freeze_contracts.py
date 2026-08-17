from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import tomllib
from pathlib import Path

import pytest

import loushang.ai as ai
from loushang.ai.api_registry import (
    APIRegistry,
    get_default_api_registry,
)
from loushang.ai.auth import ApiKeyAuth
from loushang.ai.model import (
    clear_default_model_registry,
    get_default_model_registry,
    load_model_registry_from_file,
    reload_default_model_registry,
)
from loushang.ai.options import CallOptions
from loushang.ai.provider.resolution import resolve_request_for_model

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_SRC = REPO_ROOT / "src/loushang/ai"
MODEL_DIR = AI_SRC / "model"


def _custom_registry_raw(
    provider_id: str = "company-aif002",
    *,
    stream: bool = False,
) -> dict[str, object]:
    return {
        "providers": {
            provider_id: {
                "displayName": "Company AI",
                "auth": {"apiKeyEnv": "COMPANY_AI_API_KEY"},
                "endpoints": {
                    "anthropic-messages": {
                        "api": "anthropic-messages",
                        "baseUrl": "https://ai.company.example/v1",
                        "models": {
                            "company-chat": {
                                "displayName": "Company Chat",
                                "capabilities": {
                                    "input": ["text"],
                                    "output": ["text"],
                                    "contextWindow": 1024,
                                    "maxTokens": 128,
                                    "stream": stream,
                                },
                            }
                        },
                    }
                },
            }
        }
    }


def _write_custom_registry(
    path: Path,
    provider_id: str = "company-aif002",
    *,
    stream: bool = False,
) -> None:
    path.write_text(
        json.dumps(_custom_registry_raw(provider_id, stream=stream), indent=2),
        encoding="utf-8",
    )


class _RecordingProvider:
    api = "anthropic-messages"

    def __init__(self) -> None:
        self.modes: list[str | None] = []

    def invoke_raw(self, request):
        return self._raw_parts(request)

    async def _raw_parts(self, request):
        self.modes.append(getattr(request, "mode", None))
        yield {"type": "response_start", "response_id": "aif002"}
        yield {"type": "text_delta", "text": "ok"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


class _InvokeRawOnlyProvider:
    api = "anthropic-messages"

    def __init__(self) -> None:
        self.modes: list[str | None] = []

    def invoke_raw(self, request):
        return self._raw_parts(request)

    async def _raw_parts(self, request):
        self.modes.append(getattr(request, "mode", None))
        yield {"type": "response_start", "response_id": "aif002"}
        yield {"type": "text_delta", "text": "ok"}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


class _StreamRawOnlyProvider:
    api = "anthropic-messages"

    def stream_raw(self, request):
        raise AssertionError("not used by this contract test")


def test_builtin_model_file_is_models_json_without_schema_version() -> None:
    models_json = MODEL_DIR / "models.json"
    legacy_catalog = MODEL_DIR / "models.curated.v2.json"
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert models_json.is_file()
    assert not legacy_catalog.exists()
    assert '"loushang.ai.model" = ["models.json"]' in pyproject
    assert "models.curated.v2.json" not in pyproject

    raw = json.loads(models_json.read_text(encoding="utf-8"))
    assert "schemaVersion" not in raw


def test_cryptography_compatibility_constraint_is_scoped_to_intel_macos() -> None:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = pyproject["project"]["dependencies"]

    assert [
        dependency
        for dependency in dependencies
        if dependency.lower().startswith("cryptography")
    ] == ["cryptography<49; sys_platform == 'darwin' and platform_machine == 'x86_64'"]


def test_simple_api_is_not_part_of_root_or_api_contract() -> None:
    forbidden = {
        "SimpleCallOptions",
        "SimpleStreamOptions",
        "ThinkingBudgets",
        "complete_simple",
        "stream_simple",
        "simple_options_to_call_options",
    }
    for name in forbidden:
        assert name not in ai.__all__
        assert not hasattr(ai, name)

    import loushang.ai.api as api_module
    import loushang.ai.options as options_module

    for name in forbidden:
        assert not hasattr(api_module, name)
        assert not hasattr(options_module, name)


def test_model_instances_do_not_expose_call_facades() -> None:
    model = get_default_model_registry().get_model(
        "moonshot",
        "openai-completions",
        "kimi-k2.6",
    )

    for name in ("complete", "stream", "complete_simple", "stream_simple"):
        assert not hasattr(model, name)


def test_auth_is_owned_by_ai_package_without_top_level_auth_package() -> None:
    auth_files = {
        path.name
        for path in (AI_SRC / "auth").glob("*.py")
        if path.name != "__pycache__"
    }

    assert auth_files == {
        "__init__.py",
        "core.py",
        "credentials.py",
        "errors.py",
        "registry.py",
        "resolver.py",
        "store.py",
        "support.py",
    }

    import loushang.ai.auth as auth_module

    assert not (REPO_ROOT / "src/loushang/auth").exists()
    assert (AI_SRC / "auth" / "sources" / "openai_codex.py").is_file()
    assert not (AI_SRC / "auth" / "oauth" / "providers" / "openai_codex.py").exists()

    for name in (
        "OAuthCredential",
        "CredentialSource",
        "FileCredentialStore",
        "OpenAICodexCredentialSource",
        "resolve_auth",
        "login",
        "logout",
        "credential_status",
    ):
        assert hasattr(auth_module, name)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loushang.auth")


@pytest.mark.parametrize(
    "module_name",
    ("loushang.ai.cli", "loushang.ai." + "contrib.openai_codex"),
)
def test_removed_ai_package_surfaces_are_not_importable(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


def test_default_registry_loads_builtin_and_user_model_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_model_dir = tmp_path / ".loushang" / "models"
    user_model_dir.mkdir(parents=True)
    _write_custom_registry(user_model_dir / "company.json")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    clear_default_model_registry()

    try:
        registry = get_default_model_registry()
        assert registry.get_provider("openai") is not None
        model = registry.get_model(
            "company-aif002",
            "anthropic-messages",
            "company-chat",
        )
        assert model.api == "anthropic-messages"
        assert model.base_url == "https://ai.company.example/v1"
    finally:
        clear_default_model_registry()


def test_default_registry_fails_on_bad_user_model_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_model_dir = tmp_path / ".loushang" / "models"
    user_model_dir.mkdir(parents=True)
    (user_model_dir / "bad.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    clear_default_model_registry()

    try:
        with pytest.raises(ValueError) as exc_info:
            get_default_model_registry()
        assert str(user_model_dir / "bad.json") in str(exc_info.value)
    finally:
        clear_default_model_registry()


def test_reload_default_registry_keeps_existing_registry_when_user_file_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_model_dir = tmp_path / ".loushang" / "models"
    user_model_dir.mkdir(parents=True)
    _write_custom_registry(user_model_dir / "company.json")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    clear_default_model_registry()

    try:
        initial_registry = get_default_model_registry()
        (user_model_dir / "bad.json").write_text("{", encoding="utf-8")

        with pytest.raises(ValueError) as exc_info:
            reload_default_model_registry()

        assert str(user_model_dir / "bad.json") in str(exc_info.value)
        assert get_default_model_registry() is initial_registry
    finally:
        clear_default_model_registry()


def test_provider_registry_accepts_invoke_raw_and_rejects_stream_raw() -> None:
    registry = APIRegistry()

    registry.register_api_adapter(_InvokeRawOnlyProvider())
    with pytest.raises(TypeError):
        registry.register_api_adapter(_StreamRawOnlyProvider())


def test_public_invocation_does_not_expose_registry_injection() -> None:
    for function in (ai.complete, ai.stream, ai.complete_structured):
        parameters = inspect.signature(function).parameters
        assert "provider_registry" not in parameters
        assert "registry" not in parameters


def test_complete_dispatches_to_invoke_raw_provider(tmp_path: Path) -> None:
    async def run() -> None:
        path = tmp_path / "company.json"
        _write_custom_registry(path, stream=True)
        model = load_model_registry_from_file(path).get_model(
            "company-aif002",
            "anthropic-messages",
            "company-chat",
        )
        provider = _InvokeRawOnlyProvider()
        provider_registry = get_default_api_registry()
        provider_registry.clear_api_adapters()
        provider_registry.register_api_adapter(provider)

        message = await ai.complete(
            model,
            {"messages": [{"role": "user", "content": "hello"}]},
            CallOptions(auth=ApiKeyAuth("test-key")),
        )

        assert message.content[0].text == "ok"
        assert provider.modes == ["complete"]

    asyncio.run(run())


def test_stream_dispatches_to_invoke_raw_provider(tmp_path: Path) -> None:
    async def run() -> None:
        path = tmp_path / "company.json"
        _write_custom_registry(path, stream=True)
        model = load_model_registry_from_file(path).get_model(
            "company-aif002",
            "anthropic-messages",
            "company-chat",
        )
        provider = _InvokeRawOnlyProvider()
        provider_registry = get_default_api_registry()
        provider_registry.clear_api_adapters()
        provider_registry.register_api_adapter(provider)

        event_stream = await ai.stream(
            model,
            {"messages": [{"role": "user", "content": "hello"}]},
            CallOptions(auth=ApiKeyAuth("test-key")),
        )
        async for _event in event_stream:
            pass

        assert provider.modes == ["stream"]

    asyncio.run(run())


def test_complete_and_stream_pass_distinct_provider_modes(tmp_path: Path) -> None:
    async def run() -> None:
        path = tmp_path / "company.json"
        _write_custom_registry(path, stream=True)
        model = load_model_registry_from_file(path).get_model(
            "company-aif002",
            "anthropic-messages",
            "company-chat",
        )
        provider = _RecordingProvider()
        provider_registry = get_default_api_registry()
        provider_registry.clear_api_adapters()
        provider_registry.register_api_adapter(provider)
        context = {"messages": [{"role": "user", "content": "hello"}]}

        await ai.complete(
            model,
            context,
            CallOptions(auth=ApiKeyAuth("test-key")),
        )
        event_stream = await ai.stream(
            model,
            context,
            CallOptions(auth=ApiKeyAuth("test-key")),
        )
        async for _event in event_stream:
            pass

        assert provider.modes == ["complete", "stream"]

    asyncio.run(run())


def test_model_carries_call_information_without_registry_lookup_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "company.json"
    _write_custom_registry(path)
    model = load_model_registry_from_file(path).get_model(
        "company-aif002",
        "anthropic-messages",
        "company-chat",
    )

    assert model.api == "anthropic-messages"
    assert model.base_url == "https://ai.company.example/v1"
    assert model.auth is not None
    assert model.auth.api_key_env == "COMPANY_AI_API_KEY"
    assert model.upstream_id is None
    for name in (
        "_endpoint_ref",
        "_auth_inherited",
        "_compat_overrides",
        "_transport_legacy_raw",
        "_routing_legacy_raw",
        "_raw_source",
    ):
        assert not hasattr(model, name)
    assert not hasattr(type(model), "with_endpoint")
    assert not hasattr(type(model), "with_contract_overrides")


def test_bound_model_resolves_without_default_registry_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "company.json"
    _write_custom_registry(path)
    model = load_model_registry_from_file(path).get_model(
        "company-aif002",
        "anthropic-messages",
        "company-chat",
    )

    def fail_default_registry_lookup():
        raise AssertionError("default registry lookup should not be needed")

    monkeypatch.setattr(
        "loushang.ai.model.registry.get_default_model_registry",
        fail_default_registry_lookup,
    )

    request = resolve_request_for_model(
        model,
        options=CallOptions(auth=ApiKeyAuth("test-key")),
        env={},
    )

    assert request.model.provider_id == "company-aif002"
    assert request.model.endpoint_id == "anthropic-messages"
    assert request.model.api == "anthropic-messages"
    assert request.base_url == "https://ai.company.example/v1"
