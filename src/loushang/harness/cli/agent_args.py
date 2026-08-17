"""Typed values for the standard Agent-product CLI profile."""

from __future__ import annotations

import os
from argparse import Namespace
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, TextIO, TypeVar

from loushang.harness.host.prompt_input import PromptInputPlan, resolve_prompt_input

AgentCliMode = Literal["text", "print", "json", "rpc", "channel"]
CommandListFormat = Literal["tsv", "json"]
DiagnosticListFormat = Literal["tsv", "json"]
SourceInfoFormat = Literal["text", "json"]
ModelListFormat = Literal["text", "json"]
SessionListFormat = Literal["tsv", "json"]
SkillListFormat = Literal["tsv", "json"]
PluginListFormat = Literal["tsv", "json"]
PackageListFormat = Literal["text", "tsv", "json"]
ExportFormat = Literal["html", "jsonl"]
ExportResultFormat = Literal["text", "json"]
CommandResultFormat = Literal["raw", "json"]
AgentArgsT = TypeVar("AgentArgsT", bound="AgentCliArgs")


@dataclass(frozen=True)
class AgentCliArgs:
    """Parsed values declared by ``STANDARD_CLI_PROFILE``.

    Products subclass this value object with additive arguments. The standard
    projection stays shared so every Agent product interprets the common
    grammar identically.
    """

    help: bool
    version: bool
    source_info: bool
    source_info_format: SourceInfoFormat
    mode: AgentCliMode
    prompt: str | None
    tui: bool
    no_tui: bool
    continue_: bool
    resume: bool | str
    no_session: bool
    session: str | None
    session_name: str | None
    list_sessions: bool
    all_sessions: bool
    list_sessions_format: SessionListFormat
    session_index: bool
    refresh_session_index: bool
    session_cwd: str | None
    session_name_filter: str | None
    session_parent: str | None
    session_query: str | None
    session_has_diagnostics: bool | None
    session_limit: int | None
    fork: str | None
    session_dir: str | None
    cwd: str | None
    provider: str | None
    model: str | None
    thinking: str | None
    tools: tuple[str, ...]
    no_tools: bool
    no_builtin_tools: bool
    no_context_files: bool
    list_commands: bool
    list_commands_format: CommandListFormat
    list_diagnostics: bool
    list_diagnostics_format: DiagnosticListFormat
    diagnostics_limit: int
    diag_export: bool
    diag_output: str | None
    list_skills: bool
    list_skills_format: SkillListFormat
    enable_skills: tuple[str, ...]
    disable_skills: tuple[str, ...]
    list_plugins: bool
    list_plugins_format: PluginListFormat
    list_packages: bool
    list_packages_format: PackageListFormat
    package_catalog: str | None
    install_packages: tuple[str, ...]
    uninstall_packages: tuple[str, ...]
    package_scope: str
    update_all_packages: bool
    check_package_updates: bool
    materialize_packages: tuple[str, ...]
    update_packages: tuple[str, ...]
    remove_packages: tuple[str, ...]
    add_plugin_sources: tuple[str, ...]
    remove_plugin_sources: tuple[str, ...]
    enable_plugins: tuple[str, ...]
    disable_plugins: tuple[str, ...]
    command: str | None
    command_args: str
    command_result_format: CommandResultFormat
    list_models: str | bool
    list_models_format: ModelListFormat
    models: tuple[str, ...]
    extensions: tuple[str, ...]
    no_extensions: bool
    skills: tuple[str, ...]
    no_skills: bool
    prompt_templates: tuple[str, ...]
    no_prompt_templates: bool
    themes: tuple[str, ...]
    no_themes: bool
    system_prompt: str | None
    append_system_prompt: tuple[str, ...]
    verbose: bool
    debug: str | None
    debug_file: str | None
    trace: str | None
    trace_file: str | None
    offline: bool
    export: str | None
    export_format: ExportFormat
    export_result_format: ExportResultFormat
    render_tool_events: bool
    messages: tuple[str, ...]
    file_args: tuple[str, ...]
    message_prompts: tuple[str, ...]
    unknown_flags: dict[str, bool | str]
    extension_flag_values: dict[str, bool | str]


def agent_cli_argument_values(
    namespace: Namespace,
    *,
    unknown_flags: dict[str, bool | str],
    extension_flag_values: dict[str, bool | str],
) -> dict[str, object]:
    """Project an argparse namespace into standard Agent CLI constructor values."""

    file_args, messages = split_file_args(namespace.messages)
    return {
        "help": namespace.help,
        "version": namespace.version,
        "source_info": namespace.source_info,
        "source_info_format": namespace.source_info_format,
        "mode": namespace.mode,
        "prompt": namespace.prompt,
        "tui": namespace.tui,
        "no_tui": namespace.no_tui,
        "continue_": namespace.continue_,
        "resume": namespace.resume,
        "no_session": namespace.no_session,
        "session": namespace.session,
        "session_name": namespace.session_name,
        "list_sessions": namespace.list_sessions,
        "all_sessions": namespace.all_sessions,
        "list_sessions_format": namespace.list_sessions_format,
        "session_index": namespace.session_index,
        "refresh_session_index": namespace.refresh_session_index,
        "session_cwd": namespace.session_cwd,
        "session_name_filter": namespace.session_name_filter,
        "session_parent": namespace.session_parent,
        "session_query": namespace.session_query,
        "session_has_diagnostics": namespace.session_has_diagnostics,
        "session_limit": namespace.session_limit,
        "fork": namespace.fork,
        "session_dir": namespace.session_dir,
        "cwd": namespace.cwd,
        "provider": namespace.provider,
        "model": namespace.model,
        "thinking": namespace.thinking,
        "tools": parse_tool_flags(namespace.tool_flags, namespace.tools),
        "no_tools": namespace.no_tools,
        "no_builtin_tools": namespace.no_builtin_tools,
        "no_context_files": namespace.no_context_files,
        "list_commands": namespace.list_commands,
        "list_commands_format": namespace.list_commands_format,
        "list_diagnostics": namespace.list_diagnostics,
        "list_diagnostics_format": namespace.list_diagnostics_format,
        "diagnostics_limit": namespace.diagnostics_limit,
        "diag_export": namespace.diag_export,
        "diag_output": namespace.diag_output,
        "list_skills": namespace.list_skills,
        "list_skills_format": namespace.list_skills_format,
        "enable_skills": tuple(namespace.enable_skill),
        "disable_skills": tuple(namespace.disable_skill),
        "list_plugins": namespace.list_plugins,
        "list_plugins_format": namespace.list_plugins_format,
        "list_packages": namespace.list_packages,
        "list_packages_format": namespace.list_packages_format,
        "package_catalog": namespace.package_catalog,
        "install_packages": tuple(namespace.install_package),
        "uninstall_packages": tuple(namespace.uninstall_package),
        "package_scope": namespace.package_scope,
        "update_all_packages": namespace.update_packages,
        "check_package_updates": namespace.check_package_updates,
        "materialize_packages": tuple(namespace.materialize_package),
        "update_packages": tuple(namespace.update_package),
        "remove_packages": tuple(namespace.remove_package),
        "add_plugin_sources": tuple(namespace.add_plugin_source),
        "remove_plugin_sources": tuple(namespace.remove_plugin_source),
        "enable_plugins": tuple(namespace.enable_plugin),
        "disable_plugins": tuple(namespace.disable_plugin),
        "command": namespace.command,
        "command_args": namespace.command_args,
        "command_result_format": namespace.command_result_format,
        "list_models": namespace.list_models,
        "list_models_format": namespace.list_models_format,
        "models": parse_csv_items(namespace.models),
        "extensions": tuple(namespace.extension),
        "no_extensions": namespace.no_extensions,
        "skills": tuple(namespace.skill),
        "no_skills": namespace.no_skills,
        "prompt_templates": tuple(namespace.prompt_template),
        "no_prompt_templates": namespace.no_prompt_templates,
        "themes": tuple(namespace.theme),
        "no_themes": namespace.no_themes,
        "system_prompt": namespace.system_prompt,
        "append_system_prompt": parse_csv_item_groups(namespace.append_system_prompt),
        "verbose": namespace.verbose,
        "debug": namespace.debug,
        "debug_file": namespace.debug_file,
        "trace": namespace.trace,
        "trace_file": namespace.trace_file,
        "offline": namespace.offline,
        "export": namespace.export,
        "export_format": namespace.export_format,
        "export_result_format": namespace.export_result_format,
        "render_tool_events": namespace.render_tool_events,
        "messages": messages,
        "file_args": file_args,
        "message_prompts": tuple(namespace.message_prompts),
        "unknown_flags": unknown_flags,
        "extension_flag_values": extension_flag_values,
    }


def normalize_agent_cli_argv(argv: list[str]) -> list[str]:
    """Normalize standard command aliases before argparse projection."""

    return _normalize_observability_flags(
        _normalize_package_command(_normalize_diagnostics_command(argv))
    )


def agent_cli_bootstrap_args(
    args: AgentArgsT,
    *,
    product_catalog_operation: bool = False,
) -> AgentArgsT:
    """Use an ephemeral session for catalog and resource-setting operations."""

    if product_catalog_operation or any(
        (
            args.list_commands,
            args.list_diagnostics,
            args.list_skills,
            args.list_plugins,
            args.list_packages,
            args.list_models is not False,
            args.enable_skills,
            args.disable_skills,
            args.add_plugin_sources,
            args.remove_plugin_sources,
            args.enable_plugins,
            args.disable_plugins,
        )
    ):
        return replace(args, no_session=True)
    return args


def agent_resource_loader_options(args: AgentCliArgs) -> dict[str, object]:
    """Project standard resource flags into the shared loader option contract."""

    options: dict[str, object] = {
        "additional_extension_paths": list(getattr(args, "extensions", ())),
        "additional_skill_paths": list(getattr(args, "skills", ())),
        "additional_prompt_template_paths": list(
            getattr(args, "prompt_templates", ())
        ),
        "additional_theme_paths": list(getattr(args, "themes", ())),
        "no_extensions": bool(getattr(args, "no_extensions", False)),
        "no_skills": bool(getattr(args, "no_skills", False)),
        "no_prompt_templates": bool(
            getattr(args, "no_prompt_templates", False)
        ),
        "no_themes": bool(getattr(args, "no_themes", False)),
        "no_context_files": bool(getattr(args, "no_context_files", False)),
    }
    if hasattr(args, "system_prompt"):
        options["system_prompt"] = getattr(args, "system_prompt")
    if hasattr(args, "append_system_prompt"):
        options["append_system_prompt"] = list(
            getattr(args, "append_system_prompt")
        )
    return options


def configure_agent_resource_loader(
    resource_loader: object,
    args: AgentCliArgs,
) -> dict[str, object]:
    """Apply standard resource flags when the injected loader supports them."""

    options = agent_resource_loader_options(args)
    setter = getattr(resource_loader, "set_runtime_options", None)
    if callable(setter):
        setter(**options)
    return options


def apply_agent_offline_mode(
    args: AgentCliArgs,
    *,
    environment: dict[str, str] | None = None,
    variable: str = "LOUSHANG_OFFLINE",
) -> None:
    if args.offline:
        (os.environ if environment is None else environment)[variable] = "1"


def resolve_agent_session_dir(
    args: AgentCliArgs,
    *,
    project_root: str | Path,
    settings_manager: object,
) -> Path:
    if args.session_dir:
        return Path(args.session_dir).expanduser().resolve()
    get_settings = getattr(settings_manager, "get_settings", None)
    if not callable(get_settings):
        raise TypeError("settings manager does not expose get_settings()")
    settings = get_settings()
    configured = getattr(settings, "session_dir", None)
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(project_root) / ".loushang" / "sessions"


def agent_image_auto_resize(settings_manager: object | None) -> bool:
    getter = getattr(settings_manager, "get_image_auto_resize", None)
    if callable(getter):
        return bool(getter())
    get_settings = getattr(settings_manager, "get_settings", None)
    if not callable(get_settings):
        return True
    images = getattr(get_settings(), "images", None)
    if images is None:
        return True
    return bool(getattr(images, "auto_resize", True))


def agent_tool_selection(
    args: AgentCliArgs,
) -> tuple[list[str] | None, list[str] | None]:
    """Project CLI tool selection into runtime allow/active lists."""

    if args.no_tools:
        return [], []
    if args.tools:
        selected = list(args.tools)
        return selected, list(selected)
    return None, None


def agent_cli_output_mode(args: AgentCliArgs) -> str:
    """Project structured JSON mode while keeping other hosts text-oriented."""

    return "json" if args.mode == "json" else "text"


def resolve_agent_prompt_input(
    args: AgentCliArgs,
    *,
    stdin: TextIO,
    cwd: str | Path,
    auto_resize_images: bool = True,
) -> PromptInputPlan:
    """Resolve standard prompt, message, file, and stdin inputs."""

    return resolve_prompt_input(
        prompt=args.prompt,
        messages=tuple(args.messages),
        message_prompts=tuple(args.message_prompts),
        file_args=tuple(args.file_args),
        stdin=stdin,
        cwd=Path(cwd),
        auto_resize_images=auto_resize_images,
    )


def cwd_bound_services_factory(
    services: object,
    resource_loader_options: dict[str, object],
    *,
    create_services: Callable[..., object],
) -> Callable[[str], object] | None:
    """Build cwd-specific services when project-scoped settings are active."""

    project_base_dir = getattr(
        getattr(services, "settings_manager", None),
        "project_base_dir",
        None,
    )
    if project_base_dir is None:
        return None

    def build_for_cwd(cwd: str) -> object:
        result = create_services(
            cwd=cwd,
            resource_loader_options=resource_loader_options,
        )
        return getattr(result, "services", result)

    return build_for_cwd


def _normalize_package_command(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    command = argv[0]
    if command == "list" and len(argv) == 1:
        return ["--list-packages"]
    if command not in {"install", "remove", "uninstall"}:
        return argv
    source: str | None = None
    trailing: list[str] = []
    scope = "global"
    for token in argv[1:]:
        if token in {"-l", "--local"}:
            scope = "project"
        elif source is None:
            source = token
        else:
            trailing.append(token)
    if source is None or trailing:
        return argv
    flag = "--install-package" if command == "install" else "--uninstall-package"
    return [flag, source, "--package-scope", scope]


def _normalize_diagnostics_command(argv: list[str]) -> list[str]:
    if len(argv) < 2 or argv[0] != "diag" or argv[1] != "export":
        return argv
    rewritten = ["--diag-export"]
    index = 2
    while index < len(argv):
        token = argv[index]
        if token == "--output":
            rewritten.append("--diag-output")
            if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
                rewritten.append(argv[index + 1])
                index += 2
                continue
        elif token.startswith("--output="):
            rewritten.append(f"--diag-output={token.split('=', 1)[1]}")
        else:
            rewritten.append(token)
        index += 1
    return rewritten


def _normalize_observability_flags(argv: list[str]) -> list[str]:
    return [
        "--debug=" if token == "--debug" else "--trace=all"
        if token == "--trace"
        else token
        for token in argv
    ]


def split_file_args(messages: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    file_args: list[str] = []
    plain_messages: list[str] = []
    for message in messages:
        if message.startswith("@") and len(message) > 1:
            file_args.append(message[1:])
        else:
            plain_messages.append(message)
    return tuple(file_args), tuple(plain_messages)


def parse_tool_flags(tool_flags: list[str], tools_arg: list[str]) -> tuple[str, ...]:
    parsed: list[str] = []
    for value in (*tool_flags, *tools_arg):
        parsed.extend(parse_csv_items(value))
    return tuple(parsed)


def parse_csv_items(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(name.strip() for name in raw.split(",") if name.strip())


def parse_csv_item_groups(raw: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in raw:
        normalized.extend(parse_csv_items(value))
    return tuple(normalized)


__all__ = [
    "AgentCliArgs",
    "AgentCliMode",
    "CommandListFormat",
    "CommandResultFormat",
    "DiagnosticListFormat",
    "ExportFormat",
    "ExportResultFormat",
    "ModelListFormat",
    "PackageListFormat",
    "PluginListFormat",
    "SessionListFormat",
    "SkillListFormat",
    "SourceInfoFormat",
    "agent_image_auto_resize",
    "agent_cli_output_mode",
    "agent_cli_bootstrap_args",
    "agent_cli_argument_values",
    "agent_resource_loader_options",
    "agent_tool_selection",
    "apply_agent_offline_mode",
    "configure_agent_resource_loader",
    "cwd_bound_services_factory",
    "normalize_agent_cli_argv",
    "parse_csv_item_groups",
    "parse_csv_items",
    "parse_tool_flags",
    "resolve_agent_session_dir",
    "resolve_agent_prompt_input",
    "split_file_args",
]
