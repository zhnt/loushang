"""Explicit G16 management and interactive attach commands.

Development entry: python -m loushang.coding.cli.mux. No command discovers or
starts a background application. Client exit is not application stop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Coroutine, Sequence
from contextlib import redirect_stdout
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from loushang.harnesstui.mux.shell import HostedMuxShellV1

from loushang.appserver.local import LocalAppClientConnectionV1, LocalConnectionModeV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1, LocalRecordError
from loushang.appserver.protocol import (
    AppServiceError,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxSelectorV1,
    MuxSpaceV1,
)


def _emit(value: dict[str, object], stream: TextIO) -> None:
    # ASCII JSON escapes terminal control sequences and never contains a key/path.
    print(json.dumps(value, ensure_ascii=True, sort_keys=True), file=stream, flush=True)


def _mux(value: MuxSpaceV1) -> dict[str, object]:
    return {
        "muxId": value.mux_space_id,
        "name": value.name,
        "revision": value.revision,
        "members": len(value.members),
    }


class _ClientCommand:
    def __init__(
        self, root: Path, endpoint: str, action: str, name: str | None, output: TextIO
    ) -> None:
        self._directory = LocalConnectionDirectoryV1(root)
        self._connection = LocalAppClientConnectionV1(
            self._directory,
            endpoint,
            expected_product_id="coding",
            mode=LocalConnectionModeV1.STOP
            if action == "stop"
            else LocalConnectionModeV1.APP,
        )
        self._action, self._name, self._output = action, name, output
        self._shell: HostedMuxShellV1 | None = None
        self.cleanup_pending = True

    async def run(self) -> None:
        try:
            await self._connection.start()
            if self._action == "stop":
                _emit({"status": "stop_requested"}, self._output)
                return
            client = self._connection.client
            if self._action == "attach":
                from loushang.harnesstui.mux.shell import HostedMuxShellV1
                from loushang.harnesstui.mux.terminal import run_hosted_mux_shell

                self._shell = HostedMuxShellV1(
                    client,
                    selector=MuxSelectorV1(name=self._name),
                    product_id="coding",
                    scopes=tuple(
                        (item.scope, item.fingerprint)
                        for item in self._connection.scopes
                    ),
                )
                status = await run_hosted_mux_shell(
                    self._shell, stdin=sys.stdin, stdout=self._output
                )
                if status:
                    raise RuntimeError("interactive connection ended")
            elif self._action == "list":
                _emit(
                    {
                        "muxes": [
                            _mux(item)
                            for item in (await client.list_muxes()).mux_spaces
                        ]
                    },
                    self._output,
                )
            elif self._action == "create":
                assert self._name is not None
                _emit(
                    _mux(await client.create_mux(MuxCreateV1(self._name))), self._output
                )
            elif self._action == "close":
                selector = MuxSelectorV1(name=self._name)
                await client.attach_mux(MuxAttachV1(selector))
                await client.close_mux(MuxCloseV1(selector))
                _emit({"status": "mux_closed", "name": self._name}, self._output)
            else:
                raise ValueError("unsupported local management action")
        finally:
            try:
                if self._shell is not None:
                    await self._shell.close()
            finally:
                await self._connection.close()
                self._directory.close()
            self.cleanup_pending = False


def _execute(
    operation: Callable[[], Coroutine[object, object, None]],
    pending: Callable[[], bool],
) -> int:
    """Process-only runner: never turn unresolved cleanup into a clean exit."""
    runner = asyncio.Runner()
    status = 0
    with redirect_stdout(sys.stderr):
        try:
            runner.run(operation())
        except KeyboardInterrupt:
            status = 130
            print("local_interrupted", file=sys.stderr)
        except (AppServiceError, LocalRecordError) as error:
            status = 1
            print(error.code.value, file=sys.stderr)
        except Exception:
            status = 1
            print("local_operation_failed", file=sys.stderr)
        finally:
            if pending():
                print("local_cleanup_incomplete", file=sys.stderr, flush=True)
                os._exit(status or 1)
            runner.close()
    return status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loushang-mux",
        description="Explicit local Coding workspace management and interactive attach.",
    )
    parser.add_argument(
        "--connection-root",
        required=True,
        type=Path,
        help="exact private connection-record directory; parent must exist",
    )
    parser.add_argument(
        "--endpoint", required=True, help="explicit application endpoint name"
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    output = sys.stdout
    if args.action == "attach" and (not sys.stdin.isatty() or not output.isatty()):
        parser.error("interactive attach requires terminal input and output")
    try:
        root = args.connection_root.expanduser().resolve()
        if args.action == "serve":
            # Management/help paths do not import the real Product/model bootstrap.
            from ..hosted_bootstrap import CodingHostedLaunchV1
            from ..hosted_local import CodingLocalCommandV1, CodingLocalLaunchV1

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
                _emit(launch.describe(), output)
                return 0
            command = CodingLocalCommandV1(launch)
            return _execute(
                lambda: command.run(
                    ready=lambda: _emit(
                        {"status": "ready", **launch.describe()}, output
                    )
                ),
                lambda: command.cleanup_pending,
            )
        client = _ClientCommand(
            root, args.endpoint, args.action, getattr(args, "name", None), output
        )
    except (ValueError, OSError):
        parser.error("invalid local command configuration")
    except Exception:
        print("local_configuration_unavailable", file=sys.stderr)
        return 1
    return _execute(client.run, lambda: client.cleanup_pending)


if __name__ == "__main__":
    raise SystemExit(main())
