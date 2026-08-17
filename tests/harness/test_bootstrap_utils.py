from __future__ import annotations

import pytest

from loushang.harness.session.bootstrap_utils import (
    append_system_prompt_fragments,
    normalize_no_tools,
    resolve_base_system_prompt,
    split_model_thinking_pattern,
)


def test_bootstrap_utils_append_non_empty_prompt_fragments() -> None:
    assert append_system_prompt_fragments(" base ", ["", " extra "]) == (
        "base\n\nextra"
    )


class _PromptLoader:
    def get_system_prompt_override(self) -> str:
        return "resource prompt"

    def get_append_system_prompt_overrides(self) -> list[str]:
        return ["resource suffix"]


def test_resolve_base_system_prompt_preserves_product_precedence() -> None:
    assert resolve_base_system_prompt(
        explicit_prompt=None,
        resource_loader=_PromptLoader(),
        configured_prompt="configured prompt",
        default_prompt="default prompt",
        append_fragments=("product suffix",),
    ) == "resource prompt\n\nresource suffix\n\nproduct suffix"


def test_resolve_base_system_prompt_uses_default_for_empty_resolution() -> None:
    assert resolve_base_system_prompt(
        explicit_prompt=None,
        resource_loader=object(),
        configured_prompt="",
        default_prompt="default prompt",
    ) == "default prompt"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, "all"), (False, None), (None, None), ("builtin", "builtin")],
)
def test_bootstrap_utils_normalize_no_tools(value, expected) -> None:
    assert normalize_no_tools(value) == expected


def test_bootstrap_utils_rejects_unknown_no_tools_mode() -> None:
    with pytest.raises(ValueError, match="no_tools"):
        normalize_no_tools("custom")


def test_bootstrap_utils_splits_scoped_model_thinking_pattern() -> None:
    assert split_model_thinking_pattern("provider/model:high") == (
        "provider/model",
        "high",
    )
    assert split_model_thinking_pattern("provider/model") == ("provider/model", None)
