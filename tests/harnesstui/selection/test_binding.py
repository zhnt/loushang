from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loushang.harnesstui.selection.binding import (
    SessionModelSelectionViewPort,
    available_session_model_choices,
    current_session_model_choice_value,
    select_session_model,
)


@dataclass(frozen=True)
class _Selection:
    provider: str
    model_id: str
    endpoint_id: str


@dataclass(frozen=True)
class _Detail:
    provider: str
    model_id: str
    endpoint_id: str
    region: str
    name: str


class _Session:
    def __init__(self) -> None:
        self.agent = type(
            "Agent",
            (),
            {"model": _Selection("provider", "current", "primary")},
        )()

    def get_available_model_details(self):
        return [
            _Detail(
                provider="provider",
                model_id="current",
                endpoint_id="primary",
                region="global",
                name="Current",
            )
        ]

    def get_available_models(self):
        return [_Selection("provider", "fallback", "secondary")]


def test_session_binding_merges_details_and_fallback_selections() -> None:
    async def scenario() -> None:
        session = _Session()
        choices = await available_session_model_choices(session)

        assert [choice.value for choice in choices] == [
            "provider:primary:current",
            "provider:secondary:fallback",
        ]
        assert choices[0].region == "global"
        assert (
            await current_session_model_choice_value(session, choices=choices)
            == "provider:primary:current"
        )

    asyncio.run(scenario())


def test_session_binding_reuses_selection_runtime_to_apply_a_choice() -> None:
    async def scenario() -> None:
        selected: list[object] = []
        session = _Session()
        port = SessionModelSelectionViewPort(
            session,
            apply_selection=lambda selection: selected.append(selection),
        )

        assert await port.current_value(await port.available_choices()) == (
            "provider:primary:current"
        )
        message = await select_session_model(
            session,
            query="fallback",
            apply_selection=lambda selection: selected.append(selection),
        )

        assert message == "Model set: provider:secondary:fallback"
        assert [
            (selection.provider, selection.model_id, selection.endpoint_id)
            for selection in selected
        ] == [("provider", "fallback", "secondary")]

    asyncio.run(scenario())
