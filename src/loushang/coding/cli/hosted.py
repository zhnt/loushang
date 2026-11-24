"""Explicit foreground stdio Coding application, separate from default routes."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from loushang.agent.types import StreamFn
from loushang.ai.model import Model, ModelSelection
from loushang.apphost.integrations._foreground_process import run_foreground_process
from loushang.apphost.integrations._foreground_stdio import _InheritedStdioForeground
from loushang.appserver.framing import require_timeout
from loushang.appserver.protocol import AppServiceError
from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.coding.hosted.bootstrap import (
    CodingHostedLaunchV1,
    create_coding_hosted_attempt,
    prepare_coding_hosted_session_roots,
)
from loushang.coding.hosted.session import CodingHostedProductRuntimeFactoryForSession
from loushang.harness.tools.core import ToolDefinition


class CodingHostedCommandV1(_InheritedStdioForeground):
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
        session_execution: bool = False,
        package_product_runtime_factory_for_session: (
            CodingHostedProductRuntimeFactoryForSession | None
        ) = None,
    ) -> None:
        if type(session_discovery) is not bool:
            raise TypeError("invalid discovery activation")
        if type(session_execution) is not bool:
            raise TypeError("invalid execution activation")
        require_timeout(connection_timeout)
        require_timeout(settlement_timeout)
        self._launch = launch
        attempt = create_coding_hosted_attempt(
            launch,
            model=model,
            stream_fn=stream_fn,
            tools=tools,
            session_discovery=session_discovery,
            owned_transcripts=session_execution,
            package_product_runtime_factory_for_session=(
                package_product_runtime_factory_for_session
            ),
        )
        super().__init__(
            attempt,
            connection_timeout=connection_timeout,
            settlement_timeout=settlement_timeout,
            session_discovery=session_discovery,
            session_execution=session_execution,
            prepare_session_roots=(
                (lambda: prepare_coding_hosted_session_roots(self._launch))
                if session_execution
                else None
            ),
        )


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
        parser.add_argument(
            "--session-execution",
            action="store_true",
            help="explicitly select stable session-execution submission",
        )
    return parser


def parse_launch(
    argv: Sequence[str] | None = None,
) -> tuple[CodingHostedLaunchV1, bool]:
    """Legacy library parser: never accept a selection this pair cannot carry."""
    launch, describe, _, _ = _parse_options(argv, allow_discovery=False)
    return launch, describe


def _parse_options(
    argv: Sequence[str] | None,
    *,
    allow_discovery: bool,
) -> tuple[CodingHostedLaunchV1, bool, bool, bool]:
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
    return (
        launch,
        args.describe,
        args.session_discovery if allow_discovery else False,
        args.session_execution if allow_discovery else False,
    )


def execute_hosted_command(command: CodingHostedCommandV1) -> int:
    """Run the explicit foreground stdio command and report its exit status."""
    input_fd, output_fd = sys.stdin.fileno(), sys.stdout.fileno()
    return run_foreground_process(
        lambda: command.run(input_fd=input_fd, output_fd=output_fd),
        lambda: command.cleanup_pending,
        reportable_errors=(AppServiceError,),
        interrupted="hosted_interrupted",
        failed="hosted_application_failed",
        cleanup_incomplete="hosted_cleanup_incomplete",
    )


def main(argv: Sequence[str] | None = None) -> int:
    launch, describe, discovery, execution = _parse_options(
        argv, allow_discovery=True
    )
    if describe:
        profile = (
            AppConnectionProfileV1.STDIO_DISCOVERY_EXECUTION
            if discovery and execution
            else AppConnectionProfileV1.STDIO_EXECUTION
            if execution
            else AppConnectionProfileV1.STDIO_DISCOVERY
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
        command = CodingHostedCommandV1(
            launch,
            session_discovery=discovery,
            session_execution=execution,
        )
    except Exception:
        print("hosted_configuration_unavailable", file=sys.stderr)
        return 1
    return execute_hosted_command(command)


if __name__ == "__main__":
    raise SystemExit(main())
