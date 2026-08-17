from __future__ import annotations

from loushang.ai.model import Model, ModelSelection
from loushang.harness.session.model_resolution import (
    classify_model_resolution_failure,
    resolve_default_model,
    resolve_session_model,
    scoped_models_from_patterns,
    split_model_thinking_pattern,
)


def _model() -> Model:
    return Model(
        id="chat",
        provider="provider",
        endpoint="primary",
    )


def test_resolve_default_model_reports_failure_through_product_callback() -> None:
    selection = ModelSelection(
        endpoint_id="test-endpoint", provider="provider", model_id="missing"
    )
    failures: list[tuple[ModelSelection, str]] = []

    result = resolve_default_model(
        selection,
        build_model=lambda _: (_ for _ in ()).throw(KeyError("missing")),
        on_unavailable=lambda selected, _error, reason: failures.append(
            (selected, reason)
        ),
    )

    assert result.model is None
    assert result.reason == "missing"
    assert failures == [(selection, "missing")]


def test_resolve_default_model_keeps_successful_model() -> None:
    model = _model()
    result = resolve_default_model(
        ModelSelection(
            endpoint_id="test-endpoint", provider="provider", model_id="chat"
        ),
        build_model=lambda _: model,
    )

    assert result.model is model
    assert result.error is None


def test_resolve_session_model_keeps_explicit_model() -> None:
    model = _model()

    assert (
        resolve_session_model(
            model,
            default_selection=None,
            build_model=lambda _selection: (_ for _ in ()).throw(AssertionError()),
        )
        is model
    )


def test_resolve_session_model_builds_explicit_selection() -> None:
    model = _model()
    selection = ModelSelection(
        endpoint_id="test-endpoint", provider="provider", model_id="chat"
    )

    assert (
        resolve_session_model(
            selection,
            default_selection=None,
            build_model=lambda selected: model if selected == selection else None,
        )
        is model
    )


def test_classify_explicit_endpoint_failure_is_stable() -> None:
    selection = ModelSelection(
        provider="provider", endpoint_id="missing", model_id="chat"
    )

    assert (
        classify_model_resolution_failure(
            selection,
            error=KeyError("missing"),
            endpoint_lookup=lambda _provider, _endpoint: None,
        )
        == "endpoint_unavailable"
    )


def test_scoped_models_from_patterns_is_product_neutral() -> None:
    selections = {
        "provider/chat": ModelSelection(
            provider="provider", endpoint_id="primary", model_id="chat"
        )
    }

    assert scoped_models_from_patterns(
        ("provider/chat:high", "missing"),
        resolve_model=selections.get,
    ) == [
        {
            "model": {
                "provider": "provider",
                "endpoint_id": "primary",
                "model_id": "chat",
            },
            "thinkingLevel": "high",
        }
    ]


def test_thinking_pattern_parsing_is_owned_by_model_resolution() -> None:
    from loushang.harness.session.bootstrap_utils import (
        split_model_thinking_pattern as compatibility_split,
    )

    assert split_model_thinking_pattern("provider/chat:high") == (
        "provider/chat",
        "high",
    )
    assert compatibility_split is split_model_thinking_pattern
