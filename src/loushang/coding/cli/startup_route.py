"""Shared side-effect-free routing for ordinary embedded CLI conversations."""

from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from typing import Any, TextIO

from loushang.coding.cli.args import CliArgs, parse_args, removed_legacy_resource_option
from loushang.harness.cli.launch import (
    AgentCliLaunchOverlay,
    CliLaunchPlan,
    agent_cli_launch_plan,
    cli_static_error,
    resolve_effective_tui,
)
from loushang.harness.host.product_host import stream_is_tty


def _cli_launch_plan(args: CliArgs) -> CliLaunchPlan:
    product_command_operation = any(
        (
            args.list_methods,
            args.show_method is not None,
            args.show_method_plan is not None,
            args.work_log_inspect is not None,
        )
    )
    product_structured_operation = any(
        (
            args.list_methods and args.list_methods_format == "json",
            args.show_method is not None and args.show_method_format == "json",
            args.show_method_plan is not None
            and args.show_method_plan_format == "json",
        )
    )
    return agent_cli_launch_plan(
        args,
        overlay=AgentCliLaunchOverlay(
            workflow_requested=args.prompt_steps is not None,
            work_log_requested=args.work_log is not None,
            method_requested=args.method is not None,
            method_disabled=args.no_method,
            command_operation=product_command_operation,
            structured_operation_output=product_structured_operation,
        ),
    )


def screen_startup_eligible(
    args: Any, plan: Any, *, stdin: TextIO, stdout: TextIO
) -> bool:
    """Only ordinary embedded conversations may acquire the early screen."""

    return bool(
        stream_is_tty(stdin)
        and stream_is_tty(stdout)
        and not args.help
        and not args.version
        and args.resume is not True
        and not plan.command_operation
        and not plan.prompt_requested
        and not plan.workflow_requested
        and not plan.message_input
        and not plan.file_input
        and not plan.follow_up_input
        and not plan.work_log_requested
        and not plan.method_requested
        and plan.mode == "text"
        and cli_static_error(plan) is None
        and resolve_effective_tui(plan, stdin_is_tty=True, stdout_is_tty=True)
    )


def early_screen_project_root(
    argv: tuple[str, ...], *, stdin: TextIO, stdout: TextIO
) -> Path | None:
    """Use the canonical grammar without consuming input or reporting errors.

    Positional command-family tokens remain message input in this grammar and
    therefore cannot claim an early conversation screen. Real dispatch and
    extension validation still run through the application after this preflight.
    """
    if not stream_is_tty(stdin) or not stream_is_tty(stdout):
        return None
    if removed_legacy_resource_option(argv) is not None:
        return None
    try:
        with redirect_stderr(StringIO()):
            args = parse_args(argv, allow_unknown=True)
    except SystemExit:
        return None
    if not screen_startup_eligible(
        args, _cli_launch_plan(args), stdin=stdin, stdout=stdout
    ):
        return None
    return Path(args.cwd or Path.cwd()).resolve()
