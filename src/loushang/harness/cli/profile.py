"""Shared CLI grammar and safe Product augmentation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from loushang.harness.cli.types import (
    UNSET,
    CliArgumentSpec,
    CliCommandSpec,
    CliProfileError,
    _validate_arguments,
)


@dataclass(frozen=True, slots=True)
class CliProfile:
    """Immutable CLI grammar selected by a Product host.

    ``augment`` is intentionally additive.  There is no generic override API:
    changing the meaning of a standard flag requires an explicit profile or
    protocol version instead of silently changing another Product's grammar.
    """

    profile_id: str
    root_arguments: tuple[CliArgumentSpec, ...] = ()
    commands: tuple[CliCommandSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise CliProfileError("CLI profile id must be non-empty")
        _validate_arguments(self.root_arguments)
        command_ids: set[str] = set()
        command_names: set[str] = set()
        root_flags = {flag for spec in self.root_arguments for flag in spec.flags}
        root_ids = {spec.argument_id for spec in self.root_arguments}
        root_dests = {spec.dest for spec in self.root_arguments}
        for command in self.commands:
            if command.command_id in command_ids:
                raise CliProfileError(
                    f"duplicate CLI command id {command.command_id!r}")
            duplicate_names = command_names.intersection(command.names)
            if duplicate_names:
                raise CliProfileError(
                    f"duplicate CLI command name(s) {sorted(duplicate_names)!r}")
            command_argument_ids = {spec.argument_id for spec in command.arguments}
            command_argument_dests = {spec.dest for spec in command.arguments}
            command_argument_flags = {
                flag for spec in command.arguments for flag in spec.flags
            }
            if root_ids.intersection(command_argument_ids):
                raise CliProfileError("command argument ids cannot shadow root arguments")
            if root_dests.intersection(command_argument_dests):
                raise CliProfileError("command destinations cannot shadow root arguments")
            if root_flags.intersection(command_argument_flags):
                raise CliProfileError("command flags cannot shadow root arguments")
            command_ids.add(command.command_id)
            command_names.update(command.names)
        object.__setattr__(self, "root_arguments", tuple(self.root_arguments))
        object.__setattr__(self, "commands", tuple(self.commands))

    def augment(
        self,
        *,
        profile_id: str | None = None,
        root_arguments: Sequence[CliArgumentSpec] = (),
        commands: Sequence[CliCommandSpec] = (),
        command_argument_extensions: Mapping[
            str, Sequence[CliArgumentSpec]
        ] | None = None,
    ) -> CliProfile:
        """Return a Product profile with additional arguments and commands.

        Existing IDs, destinations, flags, command IDs, and aliases may not be
        replaced.  The failure is deliberate: it keeps standard CLI behaviour
        identical across Products and makes additions reviewable.
        """

        combined_arguments = (*self.root_arguments, *root_arguments)
        _validate_arguments(combined_arguments)
        extension_map = command_argument_extensions or {}
        base_commands = (*self.commands, *commands)
        extended_commands: list[CliCommandSpec] = []
        for command in base_commands:
            additions: Sequence[CliArgumentSpec] = ()
            for key, values in extension_map.items():
                if key == command.command_id or key in command.names:
                    additions = (*additions, *values)
            extended_commands.append(
                CliCommandSpec(
                    command_id=command.command_id,
                    names=command.names,
                    arguments=(*command.arguments, *additions),
                    help=command.help,
                )
            )
        known_commands = {
            command.command_id for command in base_commands
        } | {name for command in base_commands for name in command.names}
        unknown_extensions = set(extension_map) - known_commands
        if unknown_extensions:
            raise CliProfileError(
                f"CLI command argument extensions target unknown command(s): "
                f"{sorted(unknown_extensions)!r}"
            )
        return CliProfile(
            profile_id=profile_id or self.profile_id,
            root_arguments=combined_arguments,
            commands=tuple(extended_commands),
        )

    def command(self, command_id_or_name: str) -> CliCommandSpec | None:
        for command in self.commands:
            if command.command_id == command_id_or_name or command_id_or_name in command.names:
                return command
        return None

    @property
    def option_names(self) -> frozenset[str]:
        """Return normalized option names reserved by this profile."""

        arguments = (
            *self.root_arguments,
            *(argument for command in self.commands for argument in command.arguments),
        )
        return frozenset(
            flag.lstrip("-")
            for argument in arguments
            for flag in argument.flags
            if flag.startswith("--")
        )


def _argument(
    argument_id: str,
    *flags: str,
    dest: str,
    action: str = "store",
    type: object = None,
    nargs: object = None,
    choices: tuple[object, ...] | None = None,
    default: object = UNSET,
    const: object = UNSET,
    metavar: str | None = None,
    help: str | None = None,
) -> CliArgumentSpec:
    return CliArgumentSpec(
        argument_id=argument_id,
        flags=tuple(flags),
        dest=dest,
        action=action,  # type: ignore[arg-type]
        type=type,  # type: ignore[arg-type]
        nargs=nargs,  # type: ignore[arg-type]
        choices=choices,
        default=default,
        const=const,
        metavar=metavar,
        help=help,
    )


STANDARD_CLI_PROFILE = CliProfile(
    profile_id="harness.standard",
    root_arguments=(
        _argument("cli.help", "--help", "-h", dest="help", action="store_true"),
        _argument("cli.version", "--version", "-v", dest="version", action="store_true"),
        _argument("host.mode", "--mode", dest="mode", choices=("text", "print", "json", "rpc", "channel"), default="text"),
        _argument("host.tui", "--tui", dest="tui", action="store_true"),
        _argument("host.no_tui", "--no-tui", dest="no_tui", action="store_true"),
        _argument("session.no_session", "--no-session", dest="no_session", action="store_true"),
        _argument("session.name", "--session-name", dest="session_name"),
        _argument("session.select", "--session", dest="session"),
        _argument("session.list", "--list-sessions", dest="list_sessions", action="store_true"),
        _argument("session.resume", "--resume", "-r", dest="resume", nargs="?", const=True, default=False, metavar="SESSION"),
        _argument("session.continue", "--continue", "-c", dest="continue_", action="store_true"),
        _argument("session.cwd", "--cwd", dest="cwd"),
        _argument("ai.provider", "--provider", dest="provider"),
        _argument("ai.model", "--model", dest="model"),
        _argument("ai.thinking", "--thinking", dest="thinking", choices=("off", "minimal", "low", "medium", "high", "xhigh")),
        _argument("tools.select", "--tools", "-t", dest="tools", action="append", default=[]),
        _argument("tools.disable", "--no-tools", "-nt", dest="no_tools", action="store_true"),
        _argument("tools.no_builtin", "--no-builtin-tools", "-nbt", dest="no_builtin_tools", action="store_true"),
        _argument("transcript.export", "--export", dest="export", nargs="?", const=""),
        _argument("transcript.export_format", "--export-format", dest="export_format", choices=("html", "jsonl"), default="html"),
        _argument("transcript.export_result_format", "--export-result-format", dest="export_result_format", choices=("text", "json"), default="text"),
        _argument("command.select", "--command", dest="command"),
        _argument("command.args", "--command-args", dest="command_args", default=""),
        _argument("command.result_format", "--command-result-format", dest="command_result_format", choices=("raw", "json"), default="raw"),
        _argument("session.list_format", "--list-sessions-format", dest="list_sessions_format", choices=("tsv", "json"), default="tsv"),
        _argument("diagnostics.source_info", "--source-info", dest="source_info", action="store_true"),
        _argument("diagnostics.source_info_format", "--source-info-format", dest="source_info_format", choices=("text", "json"), default="text"),
        _argument("session.all", "--all-sessions", dest="all_sessions", action="store_true"),
        _argument("session.index", "--session-index", dest="session_index", action="store_true"),
        _argument("session.refresh_index", "--refresh-session-index", dest="refresh_session_index", action="store_true"),
        _argument("session.directory_cwd", "--session-cwd", dest="session_cwd"),
        _argument("session.name_filter", "--session-name-filter", dest="session_name_filter"),
        _argument("session.parent", "--session-parent", dest="session_parent"),
        _argument("session.query", "--session-query", dest="session_query"),
        _argument("session.has_diagnostics", "--session-has-diagnostics", dest="session_has_diagnostics", action="store_true", default=None),
        _argument("session.no_diagnostics", "--session-no-diagnostics", dest="session_has_diagnostics", action="store_false"),
        _argument("session.limit", "--session-limit", dest="session_limit", type=int),
        _argument("session.fork", "--fork", dest="fork"),
        _argument("session.dir", "--session-dir", dest="session_dir"),
        _argument("ai.list_models", "--list-models", dest="list_models", nargs="?", const="", default=False),
        _argument("ai.list_models_format", "--list-models-format", dest="list_models_format", choices=("text", "json"), default="text"),
        _argument("ai.models", "--models", dest="models"),
        _argument("resources.extension", "--extension", "-e", dest="extension", action="append", default=[]),
        _argument("resources.no_extensions", "--no-extensions", "-ne", dest="no_extensions", action="store_true"),
        _argument("resources.skill", "--skill", dest="skill", action="append", default=[]),
        _argument("resources.no_skills", "--no-skills", "-ns", dest="no_skills", action="store_true"),
        _argument("resources.prompt_template", "--prompt-template", dest="prompt_template", action="append", default=[]),
        _argument("resources.no_prompt_templates", "--no-prompt-templates", "-np", dest="no_prompt_templates", action="store_true"),
        _argument("resources.theme", "--theme", dest="theme", action="append", default=[]),
        _argument("resources.no_themes", "--no-themes", dest="no_themes", action="store_true"),
        _argument("prompt.system", "--system-prompt", dest="system_prompt"),
        _argument("prompt.one_shot", "--prompt", "-p", dest="prompt"),
        _argument("prompt.append_system", "--append-system-prompt", dest="append_system_prompt", action="append", default=[]),
        _argument("host.verbose", "--verbose", dest="verbose", action="store_true"),
        _argument("diagnostics.debug", "--debug", dest="debug"),
        _argument("diagnostics.debug_file", "--debug-file", dest="debug_file"),
        _argument("diagnostics.trace", "--trace", dest="trace"),
        _argument("diagnostics.trace_file", "--trace-file", dest="trace_file"),
        _argument("host.offline", "--offline", dest="offline", action="store_true"),
        _argument("events.render_tool_events", "--render-tool-events", dest="render_tool_events", action="store_true"),
        _argument("prompt.message", "--message", dest="message_prompts", action="append", default=[]),
        _argument("tools.flag", "--tool", dest="tool_flags", action="append", default=[]),
        _argument("context.no_files", "--no-context-files", "-nc", dest="no_context_files", action="store_true"),
        _argument("commands.list", "--list-commands", dest="list_commands", action="store_true"),
        _argument("commands.list_format", "--list-commands-format", dest="list_commands_format", choices=("tsv", "json"), default="tsv"),
        _argument("diagnostics.list", "--list-diagnostics", dest="list_diagnostics", action="store_true"),
        _argument("diagnostics.list_format", "--list-diagnostics-format", dest="list_diagnostics_format", choices=("tsv", "json"), default="tsv"),
        _argument("diagnostics.limit", "--diagnostics-limit", dest="diagnostics_limit", type=int, default=50),
        _argument("diagnostics.export", "--diag-export", dest="diag_export", action="store_true"),
        _argument("diagnostics.output", "--diag-output", dest="diag_output"),
        _argument("resources.list_skills", "--list-skills", dest="list_skills", action="store_true"),
        _argument("resources.list_skills_format", "--list-skills-format", dest="list_skills_format", choices=("tsv", "json"), default="tsv"),
        _argument("resources.enable_skill", "--enable-skill", dest="enable_skill", action="append", default=[]),
        _argument("resources.disable_skill", "--disable-skill", dest="disable_skill", action="append", default=[]),
        _argument("resources.list_plugins", "--list-plugins", dest="list_plugins", action="store_true"),
        _argument("resources.list_plugins_format", "--list-plugins-format", dest="list_plugins_format", choices=("tsv", "json"), default="tsv"),
        _argument("resources.list_packages", "--list-packages", dest="list_packages", action="store_true"),
        _argument("resources.list_packages_format", "--list-packages-format", dest="list_packages_format", choices=("text", "tsv", "json"), default="text"),
        _argument("resources.package_catalog", "--package-catalog", dest="package_catalog"),
        _argument("resources.install_package", "--install-package", dest="install_package", action="append", default=[]),
        _argument("resources.uninstall_package", "--uninstall-package", dest="uninstall_package", action="append", default=[]),
        _argument("resources.package_scope", "--package-scope", dest="package_scope", choices=("global", "project"), default="global"),
        _argument("resources.update_packages", "--update-packages", dest="update_packages", action="store_true"),
        _argument("resources.check_package_updates", "--check-package-updates", dest="check_package_updates", action="store_true"),
        _argument("resources.materialize_package", "--materialize-package", dest="materialize_package", action="append", default=[]),
        _argument("resources.update_package", "--update-package", dest="update_package", action="append", default=[]),
        _argument("resources.remove_package", "--remove-package", dest="remove_package", action="append", default=[]),
        _argument("resources.add_plugin_source", "--add-plugin-source", "--add-plugin", dest="add_plugin_source", action="append", default=[]),
        _argument("resources.remove_plugin_source", "--remove-plugin-source", "--remove-plugin", dest="remove_plugin_source", action="append", default=[]),
        _argument("resources.enable_plugin", "--enable-plugin", dest="enable_plugin", action="append", default=[]),
        _argument("resources.disable_plugin", "--disable-plugin", dest="disable_plugin", action="append", default=[]),
    ),
)

__all__ = ["CliProfile", "STANDARD_CLI_PROFILE"]
