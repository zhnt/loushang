from __future__ import annotations

from loushang.harness.commands import (
    CommandDescriptor,
    CommandEffectKind,
    CommandKind,
)
from loushang.harnesstui.commands.catalog import ConversationCommandCatalog
from loushang.harnesstui.conversation.host import ConversationHostRoute
from loushang.harnesstui.conversation.intents import (
    FollowUpIntent,
    PromptIntent,
    QuitIntent,
    SettingsIntent,
)


def _command(
    name: str,
    *,
    description: str,
    source: str,
    argument_hint: str | None = None,
) -> CommandDescriptor[object]:
    return CommandDescriptor(
        name=name,
        invocation_name=name,
        description=description,
        source=source,
        argument_hint=argument_hint,
    )


def test_classifies_local_and_session_commands() -> None:
    catalog = ConversationCommandCatalog(
        session_commands=lambda: [
            _command(
                "rename",
                description="Rename the current session",
                source="builtin",
                argument_hint="<name>",
            )
        ]
    )

    settings_effect = catalog.effect_for_route("settings", SettingsIntent())
    assert settings_effect is not None
    assert settings_effect.kind is CommandEffectKind.LOCAL_UI
    assert settings_effect.command.kind is CommandKind.LOCAL_UI
    assert settings_effect.command.id == "harness.ui.settings"

    rename_effect = catalog.effect_for_route(
        ConversationHostRoute.DISPATCH,
        PromptIntent("/rename Project Alpha"),
    )
    assert rename_effect is not None
    assert rename_effect.kind is CommandEffectKind.SESSION
    assert rename_effect.command.kind is CommandKind.SESSION
    assert rename_effect.command.name == "rename"
    assert rename_effect.payload == {
        "invocation_name": "rename",
        "args": "Project Alpha",
    }


def test_leaves_plain_prompts_and_queue_routes_unowned() -> None:
    catalog = ConversationCommandCatalog(session_commands=lambda: [])

    assert (
        catalog.effect_for_route(
            ConversationHostRoute.DISPATCH,
            PromptIntent("hello"),
        )
        is None
    )
    assert (
        catalog.effect_for_route(
            ConversationHostRoute.STEER,
            PromptIntent("steer"),
        )
        is None
    )
    assert (
        catalog.effect_for_route(
            ConversationHostRoute.FOLLOW_UP,
            FollowUpIntent("later"),
        )
        is None
    )


def test_preserves_local_command_argument_rules() -> None:
    catalog = ConversationCommandCatalog(session_commands=lambda: [])

    terminal = catalog.lookup("/terminal")
    assert terminal is not None
    assert terminal.kind is CommandKind.LOCAL_UI

    assert catalog.lookup("/model kimi").name == "model"
    assert catalog.lookup("/commands model").name == "commands"
    assert catalog.lookup("/config").name == "config"
    assert catalog.lookup("/terminal extra") is None


def test_quit_and_exit_are_listed_without_owning_dispatch() -> None:
    catalog = ConversationCommandCatalog(session_commands=lambda: [])

    by_name = {command.name: command for command in catalog.commands()}
    assert by_name["quit"].kind is CommandKind.LOCAL_UI
    assert by_name["exit"].kind is CommandKind.LOCAL_UI

    assert catalog.lookup("/quit").name == "quit"
    assert catalog.lookup("/exit").name == "exit"
    assert catalog.lookup("/quit now") is None

    # Dispatch still owns QuitIntent exits; the catalog declares no routes.
    assert catalog.effect_for_route("quit", QuitIntent()) is None
    assert (
        catalog.effect_for_route(ConversationHostRoute.DISPATCH, QuitIntent()) is None
    )


def test_lists_local_and_session_commands_once() -> None:
    catalog = ConversationCommandCatalog(
        session_commands=lambda: [
            _command(
                "report",
                description="Session report",
                source="builtin",
            ),
            _command(
                "deploy",
                description="Deploy app",
                source="extension",
            ),
        ]
    )

    commands = catalog.commands()
    by_name = {command.name: command for command in commands}

    assert len([command for command in commands if command.name == "report"]) == 1
    assert by_name["report"].kind is CommandKind.SESSION
    assert by_name["report"].source == "builtin"
    assert by_name["deploy"].kind is CommandKind.SESSION
    assert by_name["deploy"].source == "extension"
    assert by_name["settings"].kind is CommandKind.LOCAL_UI
    assert by_name["config"].kind is CommandKind.LOCAL_UI
