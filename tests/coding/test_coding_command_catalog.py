from __future__ import annotations

from types import SimpleNamespace


def test_coding_command_catalog_classifies_local_and_session_commands() -> None:
    from loushang.coding.commands.catalog import CodingCommandCatalog
    from loushang.coding.ui.intent import PromptIntent, StatusIntent
    from loushang.coding.ui.prompt_routing import PromptRoute
    from loushang.runtime.commands import CommandEffectKind, CommandKind

    catalog = CodingCommandCatalog(
        session_commands=lambda: [
            SimpleNamespace(
                name="name",
                invocation_name="name",
                description="Set session display name",
                source="builtin",
                argument_hint="<name>",
            )
        ]
    )

    status_effect = catalog.effect_for_route(PromptRoute.STATUS, StatusIntent())
    assert status_effect is not None
    assert status_effect.kind is CommandEffectKind.LOCAL_UI
    assert status_effect.command.kind is CommandKind.LOCAL_UI
    assert status_effect.command.id == "coding.ui.status"

    name_effect = catalog.effect_for_route(PromptRoute.DISPATCH, PromptIntent("/name Project Alpha"))
    assert name_effect is not None
    assert name_effect.kind is CommandEffectKind.SESSION
    assert name_effect.command.kind is CommandKind.SESSION
    assert name_effect.command.name == "name"
    assert name_effect.payload == {"invocation_name": "name", "args": "Project Alpha"}


def test_coding_command_catalog_leaves_plain_prompts_and_queue_routes_unowned() -> None:
    from loushang.coding.commands.catalog import CodingCommandCatalog
    from loushang.coding.ui.intent import FollowUpIntent, PromptIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    catalog = CodingCommandCatalog(session_commands=lambda: [])

    assert catalog.effect_for_route(PromptRoute.DISPATCH, PromptIntent("hello")) is None
    assert catalog.effect_for_route(PromptRoute.STEER, PromptIntent("steer")) is None
    assert catalog.effect_for_route(PromptRoute.FOLLOW_UP, FollowUpIntent("later")) is None
