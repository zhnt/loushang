from __future__ import annotations

import importlib

import pytest

from loushang.harness.commands import (
    EMPTY_LOCAL_COMMAND_CATALOG_PROFILE,
    CommandCatalog,
    CommandDef,
    CommandDescriptor,
    CommandKind,
    LocalCommandCatalogProfile,
    MixedCommandCatalog,
    MixedCommandCatalogPorts,
)


def _command(name: str, *, kind: CommandKind = CommandKind.LOCAL_UI) -> CommandDef:
    return CommandDef(
        id=f"test.{kind.value}.{name}",
        name=name,
        kind=kind,
    )


def _session_command(descriptor: CommandDescriptor[object]) -> CommandDef:
    return CommandDef(
        id=f"test.session.{descriptor.effective_invocation_name}",
        name=descriptor.effective_invocation_name,
        kind=CommandKind.SESSION,
        description=descriptor.description,
        source=descriptor.source,
        aliases=descriptor.aliases,
    )


def _profile() -> LocalCommandCatalogProfile:
    settings = _command("settings")
    model = _command("model")
    return LocalCommandCatalogProfile(
        local_commands_by_name={
            settings.name: settings,
            model.name: model,
        },
        local_command_names_by_route={"settings_route": settings.name},
        local_commands_accepting_args=frozenset({"model"}),
    )


def test_default_local_command_profile_is_empty() -> None:
    assert not EMPTY_LOCAL_COMMAND_CATALOG_PROFILE.local_commands_by_name
    assert not EMPTY_LOCAL_COMMAND_CATALOG_PROFILE.local_command_names_by_route
    assert not EMPTY_LOCAL_COMMAND_CATALOG_PROFILE.local_commands_accepting_args


def test_legacy_command_composition_module_is_absent() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loushang.harness.command_composition")


def test_mixed_catalog_routes_and_validates_product_local_commands() -> None:
    catalog: MixedCommandCatalog[object] = MixedCommandCatalog(profile=_profile())

    assert catalog.local_for_route("settings_route") == _command("settings")
    assert catalog.local_for_route("unknown") is None
    assert catalog.lookup("/settings") == _command("settings")
    assert catalog.lookup("/settings extra") is None
    assert catalog.lookup("/model provider/model") == _command("model")
    assert catalog.lookup("plain text") is None


def test_local_command_profile_composes_immutable_product_selection() -> None:
    profile = _profile()
    help_command = _command("help")

    selected = profile.select({"settings"})
    added = selected.with_additions(
        {"help": help_command},
        routes={"help_route": "help"},
    )
    replaced = added.with_replacements(
        {
            "settings": CommandDef(
                id="test.local.settings.override",
                name="settings",
                kind=CommandKind.LOCAL_UI,
                description="Override settings",
            )
        }
    )

    assert tuple(profile.local_commands_by_name) == ("settings", "model")
    assert tuple(selected.local_commands_by_name) == ("settings",)
    assert selected.local_command_names_by_route == {"settings_route": "settings"}
    assert added.command_for_route("help_route") == help_command
    assert (
        replaced.local_commands_by_name["settings"].description == "Override settings"
    )
    assert replaced.without({"settings"}).command_for_route("settings_route") is None


def test_local_command_profile_rejects_implicit_overrides_and_invalid_routes() -> None:
    profile = _profile()

    with pytest.raises(ValueError, match="must not replace existing commands"):
        profile.with_additions({"settings": _command("settings")})

    with pytest.raises(ValueError, match="must target existing commands"):
        profile.with_replacements({"help": _command("help")})

    with pytest.raises(ValueError, match="must reference a declared command name"):
        LocalCommandCatalogProfile(
            local_commands_by_name={"settings": _command("settings")},
            local_command_names_by_route={"settings_route": "missing"},
        )


def test_mixed_catalog_preserves_session_resolution_and_invocation_payload() -> None:
    descriptors: CommandCatalog[object] = CommandCatalog(
        (
            CommandDescriptor(
                name="deploy",
                invocation_name="deploy",
                description="old",
                source="builtin",
                aliases=("ship",),
                precedence=1,
            ),
            CommandDescriptor(
                name="deploy",
                invocation_name="deploy",
                description="new",
                source="extension",
                aliases=("release",),
                precedence=2,
            ),
        )
    )
    catalog = MixedCommandCatalog(
        profile=_profile(),
        ports=MixedCommandCatalogPorts(
            session_catalog=lambda: descriptors,
            session_command=_session_command,
        ),
    )

    match = catalog.session_match("/release production")

    assert match is not None
    assert match.command.description == "new"
    assert match.command.source == "extension"
    assert match.invocation_name == "release"
    assert match.args == "production"


def test_mixed_catalog_lists_session_commands_then_unshadowed_locals() -> None:
    descriptors: CommandCatalog[object] = CommandCatalog(
        (
            CommandDescriptor(
                name="settings",
                description="session settings",
                source="session",
            ),
            CommandDescriptor(
                name="report",
                description="report",
                source="session",
            ),
        )
    )
    catalog = MixedCommandCatalog(
        profile=_profile(),
        ports=MixedCommandCatalogPorts(
            session_catalog=lambda: descriptors,
            session_command=_session_command,
        ),
    )

    assert [command.name for command in catalog.commands()] == [
        "settings",
        "report",
        "model",
    ]
    assert catalog.lookup("/settings") == _command("settings")
