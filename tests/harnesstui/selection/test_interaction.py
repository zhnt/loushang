from __future__ import annotations

import asyncio

from loushang.harnesstui.selection.catalog import ModelChoice
from loushang.harnesstui.selection.interaction import (
    ModelInteractionPresentationCopy,
    ModelInteractionSnapshot,
    present_model_interaction,
    resolve_model_interaction,
    run_model_interaction,
)
from loushang.tui import CommandPalette


def _choices() -> tuple[ModelChoice, ...]:
    return (
        ModelChoice(
            label="provider/model",
            value="provider:primary:model",
            selection=object(),
            endpoint_id="primary",
        ),
        ModelChoice(
            label="provider/model",
            value="provider:primary-canary:model",
            selection=object(),
            endpoint_id="primary-canary",
        ),
        ModelChoice(
            label="other/large",
            value="other/large",
            selection=object(),
        ),
    )


def test_model_interaction_resolves_empty_unique_and_ambiguous_queries() -> None:
    choices = _choices()
    snapshot = ModelInteractionSnapshot(choices)

    empty = resolve_model_interaction(ModelInteractionSnapshot(()))
    selected = resolve_model_interaction(snapshot, query="large")
    ambiguous = resolve_model_interaction(snapshot, query="provider/model")

    assert empty.kind == "empty"
    assert empty.matches == ()
    assert selected.kind == "selected"
    assert selected.choice is choices[2]
    assert selected.choice.selection is choices[2].selection
    assert selected.palette is not None
    assert ambiguous.kind == "ambiguous"
    assert ambiguous.matches == choices[:2]
    assert ambiguous.palette is not None


def test_model_interaction_prefers_exact_endpoint_qualified_value() -> None:
    choices = _choices()
    snapshot = ModelInteractionSnapshot(choices)

    by_value = resolve_model_interaction(
        snapshot,
        query="provider:primary-canary:model",
    )

    assert by_value.kind == "selected"
    assert by_value.choice is choices[1]


def test_model_interaction_reports_colon_shorthand_as_ambiguous() -> None:
    choices = _choices()

    result = resolve_model_interaction(
        ModelInteractionSnapshot(choices),
        query="provider:model",
    )

    assert result.kind == "ambiguous"
    assert result.matches == choices[:2]


def test_model_interaction_does_not_prioritize_bare_endpoint_match() -> None:
    choices = _choices()

    result = resolve_model_interaction(
        ModelInteractionSnapshot(choices),
        query="primary",
    )

    assert result.kind == "ambiguous"
    assert result.matches == choices[:2]


def test_model_interaction_lists_current_choice_first_for_chooser() -> None:
    choices = _choices()
    snapshot = ModelInteractionSnapshot(
        choices,
        current_value=choices[2].value,
        title="Available runtime models",
    )
    seen: list[CommandPalette] = []

    async def choose(palette: CommandPalette) -> str:
        seen.append(palette)
        return choices[0].value

    result = asyncio.run(run_model_interaction(snapshot, choose=choose))

    assert result.kind == "selected"
    assert result.choice is choices[0]
    assert seen[0].title == "Available runtime models"
    assert tuple(item.value for item in seen[0].items) == (
        choices[2].value,
        choices[0].value,
        choices[1].value,
    )
    assert seen[0].items[0].description == "current"


def test_model_interaction_reports_cancelled_chooser_without_losing_snapshot() -> None:
    choices = _choices()
    snapshot = ModelInteractionSnapshot(choices, current_value=choices[1].value)

    result = asyncio.run(run_model_interaction(snapshot, choose=lambda _palette: None))

    assert result.kind == "cancelled"
    assert result.choice is None
    assert result.matches == (choices[1], choices[0], choices[2])
    assert result.palette is not None


def test_model_interaction_passes_empty_palette_to_chooser() -> None:
    seen: list[CommandPalette] = []

    def choose(palette: CommandPalette) -> None:
        seen.append(palette)

    result = asyncio.run(
        run_model_interaction(ModelInteractionSnapshot(()), choose=choose)
    )

    assert result.kind == "cancelled"
    assert len(seen) == 1
    assert seen[0].items == ()


def test_model_interaction_does_not_choose_for_explicit_query() -> None:
    chooser_called = False

    def choose(_palette: CommandPalette) -> str:
        nonlocal chooser_called
        chooser_called = True
        return "other/large"

    result = asyncio.run(
        run_model_interaction(
            ModelInteractionSnapshot(_choices()),
            query="missing",
            choose=choose,
        )
    )

    assert result.kind == "empty"
    assert result.palette is not None
    assert not chooser_called


def test_model_interaction_presenter_leaves_selected_choice_for_product_apply() -> None:
    choices = _choices()
    snapshot = ModelInteractionSnapshot(choices, current_value=choices[2].value)
    copy = ModelInteractionPresentationCopy(
        list_items=lambda items, current: (
            f"list:{current}:" + ",".join(choice.value for choice in items)
        ),
        item_text=lambda choice: choice.value,
        cancelled="cancelled-copy",
        empty="empty-copy",
        no_match=lambda query: f"missing-copy:{query}",
        ambiguous_title="ambiguous-copy",
        ambiguous_hint=lambda matches: f"hint-copy:{len(matches)}",
    )

    listed = resolve_model_interaction(snapshot)
    selected = resolve_model_interaction(snapshot, query="large")
    ambiguous = resolve_model_interaction(snapshot, query="provider/model")
    missing = resolve_model_interaction(snapshot, query="missing")
    empty = resolve_model_interaction(ModelInteractionSnapshot(()))
    cancelled = asyncio.run(
        run_model_interaction(snapshot, choose=lambda _palette: None)
    )

    assert present_model_interaction(
        listed,
        current_value=snapshot.current_value,
        copy=copy,
    ).startswith(f"list:{choices[2].value}:")
    assert (
        present_model_interaction(
            selected,
            current_value=snapshot.current_value,
            copy=copy,
        )
        is None
    )
    assert present_model_interaction(
        ambiguous,
        current_value=snapshot.current_value,
        copy=copy,
    ) == (
        "ambiguous-copy\n"
        "  provider:primary:model\n"
        "  provider:primary-canary:model\n"
        "hint-copy:2"
    )
    assert (
        present_model_interaction(
            missing,
            current_value=None,
            copy=copy,
        )
        == "missing-copy:missing"
    )
    assert (
        present_model_interaction(empty, current_value=None, copy=copy) == "empty-copy"
    )
    assert (
        present_model_interaction(
            cancelled,
            current_value=snapshot.current_value,
            copy=copy,
        )
        == "cancelled-copy"
    )
