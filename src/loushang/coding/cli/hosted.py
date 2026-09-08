"""Explicit foreground stdio Coding application, separate from default routes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from contextlib import redirect_stdout
from pathlib import Path

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.apphost.continuity import HostedApplicationContinuityRuntimeV1
from loushang.apphost.foreground import HostedForegroundRuntimeV1
from loushang.appserver.framing import require_timeout
from loushang.appserver.protocol import AppServiceError
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.appserver.stdio import InheritedStdioTransportV1
from loushang.harness.tools.core import ToolDefinition

from ..hosted_bootstrap import CodingHostedLaunchV1, create_coding_hosted_attempt


class CodingHostedCommandV1:
    """Publish startup and shutdown ownership before acquiring the G13 lease.

    Model/transport and safe-tool overrides are trusted library test seams;
    the installed command never accepts remote factory/module selection.
    """

    def __init__(
        self,
        launch: CodingHostedLaunchV1,
        *,
        model: Model | ModelSelection | None = None,
        stream_fn: StreamFn | None = None,
        tools: list[ToolDefinition] | None = None,
        connection_timeout: float = 10.0,
        settlement_timeout: float = 60.0,
        session_discovery: bool = False,
    ) -> None:
        if type(session_discovery) is not bool:
            raise TypeError("invalid discovery activation")
        require_timeout(connection_timeout)
        require_timeout(settlement_timeout)
        self._launch = launch
        self._connection_timeout = connection_timeout
        self._settlement_timeout = settlement_timeout
        self._session_discovery = session_discovery
        self._attempt = create_coding_hosted_attempt(
            launch,
            model=model,
            stream_fn=stream_fn,
            tools=tools,
            session_discovery=session_discovery,
        )
        self._application: HostedApplicationContinuityRuntimeV1 | None = None
        self._transport: InheritedStdioTransportV1 | None = None
        self._foreground: HostedForegroundRuntimeV1 | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._started = False
        self._closing = False
        self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    async def run(self, *, input_fd: int, output_fd: int) -> None:
        if self._started or self._closing:
            raise RuntimeError("hosted_command_closed")
        self._started = True
        try:
            self._application = await self._attempt.open()
            self._transport = InheritedStdioTransportV1(
                input_fd=input_fd, output_fd=output_fd
            )
            self._foreground = HostedForegroundRuntimeV1(
                self._application,
                self._transport,
                connection_timeout=self._connection_timeout,
                settlement_timeout=self._settlement_timeout,
                session_discovery=self._session_discovery,
            )
            await self._foreground.run()
        finally:
            await self.close()

    async def close(self) -> None:
        self._closing = True
        if self._settled:
            return
        task = self._close_task
        if task is None or (
            task.done() and (task.cancelled() or task.exception() is not None)
        ):
            task = asyncio.create_task(self._close_once())
            task.add_done_callback(_observe)
            self._close_task = task
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        if self._foreground is not None:
            await self._foreground.close()
        else:
            if self._application is not None:
                await self._application.close()
            else:
                await self._attempt.close()
            if self._transport is not None:
                await self._transport.close()
        self._settled = True


def _observe(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


def _parser(*, allow_discovery: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loushang-hosted",
        description="Explicit foreground Coding application over inherited stdio; EOF shuts it down.",
    )
    parser.add_argument(
        "--workspace", type=Path, required=True, help="trusted execution workspace"
    )
    parser.add_argument(
        "--application-root",
        type=Path,
        required=True,
        help="private continuity directory (parent must exist)",
    )
    parser.add_argument(
        "--application-id",
        default="coding.default",
        help="stable application key to recover",
    )
    parser.add_argument(
        "--cwd-sessions",
        type=Path,
        required=True,
        help="exact cwd canonical Session directory",
    )
    parser.add_argument(
        "--home-sessions",
        type=Path,
        required=True,
        help="exact user-global canonical Session directory",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="print path-free scope selectors without starting or writing state",
    )
    if allow_discovery:
        parser.add_argument(
            "--session-discovery",
            action="store_true",
            help="explicitly select the bounded session-discovery wire profile",
        )
    return parser


def parse_launch(
    argv: Sequence[str] | None = None,
) -> tuple[CodingHostedLaunchV1, bool]:
    """Legacy library parser: never accept a selection this pair cannot carry."""
    launch, describe, _ = _parse_options(argv, allow_discovery=False)
    return launch, describe


def _parse_options(
    argv: Sequence[str] | None,
    *,
    allow_discovery: bool,
) -> tuple[CodingHostedLaunchV1, bool, bool]:
    parser = _parser(allow_discovery=allow_discovery)
    args = parser.parse_args(argv)
    try:
        launch = CodingHostedLaunchV1(
            workspace=args.workspace.expanduser().resolve(),
            application_root=args.application_root.expanduser().resolve(),
            application_id=args.application_id,
            cwd_sessions=args.cwd_sessions.expanduser().resolve(),
            home_sessions=args.home_sessions.expanduser().resolve(),
        )
    except (ValueError, OSError):
        parser.error("invalid hosted launch configuration")
    return launch, args.describe, args.session_discovery if allow_discovery else False


def execute_hosted_command(command: CodingHostedCommandV1) -> int:
    """Process-only runner; an incomplete cleanup is a fatal nonzero exit.

    The outer parent retains terminate/reap authority. Avoid Runner.close's
    unbounded cancellation join only when our retained cleanup is incomplete;
    do not claim that an abrupt process exit completed application settlement.
    """
    input_fd, output_fd = sys.stdin.fileno(), sys.stdout.fileno()
    runner = asyncio.Runner()
    status = 0
    with redirect_stdout(sys.stderr):
        try:
            runner.run(command.run(input_fd=input_fd, output_fd=output_fd))
        except KeyboardInterrupt:
            status = 130
            print("hosted_interrupted", file=sys.stderr)
        except AppServiceError as error:
            status = 1
            print(error.code.value, file=sys.stderr)
        except Exception:
            status = 1
            print("hosted_application_failed", file=sys.stderr)
        finally:
            if command.cleanup_pending:
                print("hosted_cleanup_incomplete", file=sys.stderr, flush=True)
                os._exit(status or 1)
            runner.close()
    return status


def main(argv: Sequence[str] | None = None) -> int:
    launch, describe, discovery = _parse_options(argv, allow_discovery=True)
    if describe:
        profile = (
            AppConnectionProfileV1.STDIO_DISCOVERY
            if discovery
            else AppConnectionProfileV1.STDIO
        )
        print(
            json.dumps(
                launch.describe(profile=profile), ensure_ascii=False, sort_keys=True
            )
        )
        return 0
    try:
        command = CodingHostedCommandV1(launch, session_discovery=discovery)
    except Exception:
        print("hosted_configuration_unavailable", file=sys.stderr)
        return 1
    return execute_hosted_command(command)


if __name__ == "__main__":
    raise SystemExit(main())
