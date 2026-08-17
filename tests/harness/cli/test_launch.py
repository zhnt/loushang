from __future__ import annotations

import pytest

from loushang.harness.cli import (
    CliLaunchPlan,
    cli_help_belongs_on_stderr,
    cli_observability_mode,
    cli_output_guard_enabled,
    cli_runtime_error,
    cli_static_error,
    resolve_effective_tui,
)


@pytest.mark.parametrize(
    ("plan", "message"),
    (
        (
            CliLaunchPlan(force_tui=True, disable_tui=True),
            "--tui and --no-tui cannot be used together",
        ),
        (
            CliLaunchPlan(fork_requested=True),
            "--fork requires --session or --continue / --resume",
        ),
        (
            CliLaunchPlan(method_requested=True, method_disabled=True),
            "--method cannot be used with --no-method",
        ),
        (
            CliLaunchPlan(mode="channel", file_input=True),
            "@file arguments are not supported in Channel mode",
        ),
    ),
)
def test_cli_static_error_preserves_standard_launch_conflicts(
    plan: CliLaunchPlan,
    message: str,
) -> None:
    assert cli_static_error(plan) == message


def test_effective_tui_requires_interactive_bare_text_launch() -> None:
    assert resolve_effective_tui(
        CliLaunchPlan(), stdin_is_tty=True, stdout_is_tty=True
    )
    assert not resolve_effective_tui(
        CliLaunchPlan(command_operation=True),
        stdin_is_tty=True,
        stdout_is_tty=True,
    )
    assert not resolve_effective_tui(
        CliLaunchPlan(), stdin_is_tty=False, stdout_is_tty=True
    )


def test_cli_launch_output_and_observability_decisions_are_normalized() -> None:
    structured = CliLaunchPlan(structured_operation_output=True)
    prompt = CliLaunchPlan(prompt_requested=True)

    assert cli_output_guard_enabled(structured)
    assert cli_help_belongs_on_stderr(prompt)
    assert cli_observability_mode(prompt, effective_tui=False) == "prompt"
    assert cli_observability_mode(structured, effective_tui=True) == "tui"


def test_cli_runtime_error_applies_effective_tui_after_auto_detection() -> None:
    assert cli_runtime_error(
        CliLaunchPlan(work_log_requested=True),
        effective_tui=True,
    ) == "--work-log is not supported in TUI mode"
