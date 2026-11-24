"""Coding screen and routing for a conversation displayed before bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harness.host.product_host import ProductHostLifecycle
from loushang.harnesstui.conversation.startup_host import (
    PreparedScreenCliRunner,
    StartupOutput,
    run_screen_first_agent_cli,
)

if TYPE_CHECKING:
    from loushang.coding.cli.args import CliArgs
    from loushang.harness.cli.agent_host import (
        AgentCliHostRunners,
        AgentCliSessionHostBinding,
    )
    from loushang.harness.cli.application import (
        AgentCliApplicationBinding,
        AgentCliApplicationState,
    )
    from loushang.harness.cli.launch import CliLaunchPlan


def screen_startup_eligible(
    args: CliArgs, plan: CliLaunchPlan, *, stdin: TextIO, stdout: TextIO
) -> bool:
    from loushang.coding.cli.startup_route import screen_startup_eligible as check

    return check(args, plan, stdin=stdin, stdout=stdout)


async def run_screen_first_cli(
    raw_argv: tuple[str, ...],
    *,
    binding: AgentCliApplicationBinding[CliArgs] | None = None,
    host_binding: AgentCliSessionHostBinding[CliArgs, AgentCliApplicationState[CliArgs]]
    | None = None,
    host_runners: AgentCliHostRunners | None = None,
    project_root: Path,
    cwd: str | Path | None,
) -> int:
    async def prepare(run_prepared: PreparedScreenCliRunner[CliArgs]) -> int:
        if binding is not None:
            assert host_binding is not None and host_runners is not None
            return await run_prepared(binding, host_binding, host_runners)

        from loushang.coding.cli.application import run_cli

        return await run_cli(raw_argv, cwd=cwd, _prepared_screen_runner=run_prepared)

    async def run_tui(**kwargs: Any) -> int:
        from loushang.coding.ui.mode import run_coding_tui

        return await run_coding_tui(**kwargs)

    return await run_screen_first_agent_cli(
        raw_argv,
        app=ScreenCodingTuiApp(
            model_label=None,
            cwd=str(project_root),
            branch=None,
            session_label=None,
        ),
        prepare_cli=prepare,
        run_tui=run_tui,
        lifecycle=binding.host_lifecycle if binding else ProductHostLifecycle.resolve(),
        cwd=cwd,
    )


__all__ = ["StartupOutput", "run_screen_first_cli", "screen_startup_eligible"]
