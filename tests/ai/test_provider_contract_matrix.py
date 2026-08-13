from __future__ import annotations

import inspect
from pathlib import Path
from typing import NamedTuple

from loushang.ai.api_registry import APIRegistry
from loushang.ai.bootstrap import register_builtin_api_adapters
from loushang.ai.protocols.anthropic_messages import AnthropicMessagesAdapter
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter
from loushang.ai.provider.protocol import APIAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_SOURCE_ROOT = REPO_ROOT / "src/loushang/ai"
NON_CANONICAL_API_ADAPTER_TERMS = (
    "ApiProvider",
    "RegisteredApiProvider",
    "RegisteredAPIAdapter",
    "register_api_provider",
    "get_api_provider",
    "list_api_providers",
    "clear_api_providers",
    "reset_api_providers",
    "register_builtin_ai_providers",
    "get_default_api_provider_registry",
)


class CoreAdapterCase(NamedTuple):
    api: str
    module: str
    class_name: str
    adapter_type: type[object]


CORE_ADAPTER_MATRIX = (
    CoreAdapterCase(
        "anthropic-messages",
        "loushang.ai.protocols.anthropic_messages",
        "AnthropicMessagesAdapter",
        AnthropicMessagesAdapter,
    ),
    CoreAdapterCase(
        "openai-completions",
        "loushang.ai.protocols.openai_chat_completions",
        "OpenAIChatCompletionsAdapter",
        OpenAIChatCompletionsAdapter,
    ),
    CoreAdapterCase(
        "openai-responses",
        "loushang.ai.protocols.openai_responses",
        "OpenAIResponsesAdapter",
        OpenAIResponsesAdapter,
    ),
)


def test_core_production_adapters_implement_api_adapter_contract() -> None:
    for case in CORE_ADAPTER_MATRIX:
        adapter = case.adapter_type()

        assert adapter.api == case.api
        assert isinstance(adapter, APIAdapter)
        assert callable(adapter.invoke_raw)
        assert list(inspect.signature(adapter.invoke_raw).parameters) == ["request"]
        assert not hasattr(adapter, "stream_simple")


def test_builtin_registration_is_frozen_to_core_adapter_matrix() -> None:
    registry = APIRegistry()

    register_builtin_api_adapters(registry)

    assert sorted(adapter.api for adapter in registry.list_api_adapters()) == [
        case.api for case in CORE_ADAPTER_MATRIX
    ]


def test_contract_matrix_document_matches_core_adapters() -> None:
    docs = (
        REPO_ROOT
        / "docs/internals/architecture/ai/core-provider-adapter-contract-matrix.md"
    ).read_text(encoding="utf-8")

    for case in CORE_ADAPTER_MATRIX:
        assert f"`{case.api}`" in docs
        assert f"`{case.module}`" in docs
        assert f"`{case.class_name}`" in docs
    assert "`loushang.ai.protocols.faux.FauxAdapter`" in docs


def test_ai_source_uses_api_adapter_as_the_only_formal_term() -> None:
    occurrences = {
        term: str(path.relative_to(REPO_ROOT))
        for path in AI_SOURCE_ROOT.rglob("*.py")
        for term in NON_CANONICAL_API_ADAPTER_TERMS
        if term in path.read_text(encoding="utf-8")
    }

    assert occurrences == {}
