"""Explicit local Mux commands and Linux user service control."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Coroutine, Sequence
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from loushang.apphost.integrations._foreground_client_control import _MuxScopes
    from loushang.apphost.managed.connection import ManagedConnectionLeaseV1
    from loushang.appserver.local import LocalAppClientConnectionV1
    from loushang.appserver.protocol import MuxSelectorV1
    from loushang.harnesstui.mux.shell import HostedMuxShellV1

from loushang.apphost.integrations._foreground_client_control import (
    _LocalMuxClientCommand,
    _LocalMuxPresentation,
    emit_local_mux_value,
)
from loushang.apphost.integrations._foreground_process import run_foreground_process
from loushang.appserver.local_record import LocalRecordError
from loushang.appserver.protocol import AppServiceError

from . import mux_service


def _bind_coding_mux_shell() -> Callable[
    [LocalAppClientConnectionV1 | ManagedConnectionLeaseV1, MuxSelectorV1, _MuxScopes],
    HostedMuxShellV1,
]:
    from loushang.harnesstui.conversation.theme import terminal_transcript_theme
    from loushang.harnesstui.mux.shell import HostedMuxShellV1

    def bind(
        connection: LocalAppClientConnectionV1 | ManagedConnectionLeaseV1,
        selector: MuxSelectorV1,
        scopes: _MuxScopes,
    ) -> HostedMuxShellV1:
        return HostedMuxShellV1(
            connection.client,
            selector=selector,
            product_id="coding",
            scopes=scopes,
            discovery_client=connection.discovery_client,
            execution_client=connection.execution_client,
            transcript_theme=terminal_transcript_theme(),
        )

    return bind


def _load_mux_presentation() -> _LocalMuxPresentation[HostedMuxShellV1]:
    bind = _bind_coding_mux_shell()
    from loushang.harnesstui.mux.terminal import run_hosted_mux_shell

    async def run(shell: HostedMuxShellV1, output: TextIO) -> int:
        return await run_hosted_mux_shell(shell, stdin=sys.stdin, stdout=output)

    return bind, run


def _execute(
    operation: Callable[[], Coroutine[object, object, None]],
    pending: Callable[[], bool],
) -> int:
    return run_foreground_process(
        operation,
        pending,
        reportable_errors=(AppServiceError, LocalRecordError),
        interrupted="local_interrupted",
        failed="local_operation_failed",
        cleanup_incomplete="local_cleanup_incomplete",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loushang-mux",
        description="Explicit local Coding workspace management and interactive attach.",
    )
    parser.add_argument(
        "--connection-root",
        type=Path,
        help="exact private connection-record directory; parent must exist",
    )
    parser.add_argument(
        "--endpoint", help="explicit application endpoint name"
    )
    commands = parser.add_subparsers(dest="action", required=True)
    serve = commands.add_parser(
        "serve", help="run the application in this foreground process"
    )
    serve.add_argument("--workspace", required=True, type=Path)
    serve.add_argument("--application-root", required=True, type=Path)
    serve.add_argument("--application-id", default="coding.default")
    serve.add_argument("--cwd-sessions", required=True, type=Path)
    serve.add_argument("--home-sessions", required=True, type=Path)
    serve.add_argument(
        "--session-discovery", action="store_true",
        help="explicitly advertise bounded discovery in the authenticated record",
    )
    serve.add_argument(
        "--describe", action="store_true", help="print path-free selectors without IO"
    )
    commands.add_parser("list", help="list named muxes without attaching")
    create = commands.add_parser("create", help="create an empty named mux")
    create.add_argument("name")
    attach = commands.add_parser(
        "attach", help="control one mux in this terminal; exit only detaches"
    )
    attach.add_argument("name")
    close = commands.add_parser(
        "close", help="close a mux and its execution; not detach"
    )
    close.add_argument("name")
    close.add_argument(
        "--yes",
        action="store_true",
        required=True,
        help="confirm the destructive intent",
    )
    commands.add_parser(
        "stop",
        help="request application stop; acknowledgement is not completed cleanup",
    )
    mux_service.register_arguments(commands, serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.action == "service":
        return mux_service.run_command(parser, args)
    if args.connection_root is None or args.endpoint is None:
        parser.error("--connection-root and --endpoint are required for this command")
    output = sys.stdout
    if args.action == "attach" and (not sys.stdin.isatty() or not output.isatty()):
        parser.error("interactive attach requires terminal input and output")
    try:
        root = args.connection_root.expanduser().resolve()
        if args.action == "serve":
            from loushang.apphost.managed.systemd import (
                run_systemd_foreground_application,
            )

            notify_socket = mux_service.foreground_notification_socket(parser, args)
            # Management/help paths do not import the real Product/model bootstrap.
            from ..hosted.bootstrap import CodingHostedLaunchV1
            from ..hosted.local import CodingLocalCommandV1, CodingLocalLaunchV1

            launch = CodingLocalLaunchV1(
                CodingHostedLaunchV1(
                    args.workspace.expanduser().resolve(),
                    args.application_root.expanduser().resolve(),
                    args.application_id,
                    args.cwd_sessions.expanduser().resolve(),
                    args.home_sessions.expanduser().resolve(),
                ),
                root,
                args.endpoint,
                session_discovery=args.session_discovery,
            )
            if args.describe:
                emit_local_mux_value(launch.describe(), output)
                return 0
            command = CodingLocalCommandV1(launch)

            def ready() -> None:
                emit_local_mux_value({"status": "ready", **launch.describe()}, output)

            return _execute(
                partial(run_systemd_foreground_application, command, notify_socket, ready),
                lambda: command.cleanup_pending,
            )
        client: _LocalMuxClientCommand[HostedMuxShellV1] = _LocalMuxClientCommand(
            root,
            args.endpoint,
            args.action,
            getattr(args, "name", None),
            output,
            product_id="coding",
        )
    except (ValueError, OSError):
        parser.error("invalid local command configuration")
    except Exception:
        print("local_configuration_unavailable", file=sys.stderr)
        return 1
    return _execute(
        partial(client.run, _load_mux_presentation),
        lambda: client.cleanup_pending,
    )


if __name__ == "__main__":
    raise SystemExit(main())
