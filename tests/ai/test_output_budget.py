from __future__ import annotations

from types import SimpleNamespace

from loushang.ai import CallOptions
from loushang.ai.model.domain import Capabilities, Model
from loushang.ai.provider.output_budget import resolve_output_token_budget


def _model(max_tokens: int | None) -> Model:
    return Model(
        id="test-model",
        provider="test-provider",
        endpoint="test-endpoint",
        capabilities=Capabilities(max_tokens=max_tokens),
    )


def test_output_budget_uses_uncapped_resolved_request_budget() -> None:
    budget = resolve_output_token_budget(
        _model(32768),
        SimpleNamespace(max_output_tokens=32000),
    )

    assert budget.value == 32000
    assert budget.source == "request"
    assert budget.explicit is True


def test_output_budget_uses_resolved_request_before_options_argument() -> None:
    budget = resolve_output_token_budget(
        _model(32768),
        SimpleNamespace(max_output_tokens=32000),
        CallOptions(max_output_tokens=64),
    )

    assert budget.value == 32000
    assert budget.source == "request"
    assert budget.explicit is True


def test_output_budget_accepts_options_argument_without_request_budget() -> None:
    budget = resolve_output_token_budget(
        _model(32768),
        SimpleNamespace(max_tokens=None),
        CallOptions(max_output_tokens=64),
    )

    assert budget.value == 64
    assert budget.source == "options"
    assert budget.explicit is True


def test_output_budget_caps_model_capability_default() -> None:
    budget = resolve_output_token_budget(
        _model(32768),
        SimpleNamespace(max_tokens=None),
    )

    assert budget.value == 32000
    assert budget.source == "model"
    assert budget.explicit is False


def test_output_budget_uses_resolved_request_capability_before_model() -> None:
    budget = resolve_output_token_budget(
        _model(1024),
        SimpleNamespace(
            max_tokens=None,
            capabilities=Capabilities(max_tokens=65536),
        ),
    )

    assert budget.value == 32000
    assert budget.source == "capabilities"
    assert budget.explicit is False


def test_output_budget_falls_back_when_model_has_no_capability() -> None:
    budget = resolve_output_token_budget(
        _model(None),
        SimpleNamespace(max_tokens=None),
    )

    assert budget.value == 8192
    assert budget.source == "fallback"
    assert budget.explicit is False
