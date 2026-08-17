from __future__ import annotations


def test_model_selection_is_owned_by_ai() -> None:
    import loushang.ai.model as ai_model

    assert (
        ai_model.ModelSelection(
            endpoint_id="test-endpoint", provider="faux", model_id="alpha"
        ).endpoint_id
        == "test-endpoint"
    )
    assert not hasattr(ai_model, "ControlConfig")
