"""Short Linux managed-mux entry; parse and terminal checks precede native IO."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lmux", description="Linux named workspace muxes (managed preview).")
    commands = parser.add_subparsers(dest="action")
    new = commands.add_parser("new", help="create a named mux, start/reuse its service, and attach")
    new.add_argument("-s", "--name", required=True)
    new.add_argument("--workspace", help="workspace for the new mux; defaults to cwd")
    creation = commands.add_parser("create", help="query an exact previous creation, or explicitly continue it")
    creation.add_argument("--server", required=True, help="exact original service ID (not an alias)")
    creation.add_argument("--operation", required=True, help="original creation operation ID")
    creation.add_argument("--continue", dest="continue_create", action="store_true",
                          help="confirm and continue the same creation once; never attach automatically")
    creation.add_argument("--yes", action="store_true", help="confirm continuing this exact creation")
    creation_status = commands.add_parser("create-status", help="read-only recorded creation fact; never start or resend")
    creation_status.add_argument("--server", required=True)
    creation_status.add_argument("--operation", required=True)
    attach = commands.add_parser("attach", help="reconnect by global name; never start a service")
    attach.add_argument("-t", "--target")
    listing = commands.add_parser("ls", help="read-only global reservations and recorded state (not liveness)")
    listing.add_argument("--after", help="page after this global name")
    diagnostic = commands.add_parser("status", help="read recorded service state and paths; never start or probe readiness")
    selected = diagnostic.add_mutually_exclusive_group()
    selected.add_argument("-t", "--target", help="global mux name, independent of cwd")
    selected.add_argument("--server", help="service alias or exact service ID, including services without mux names")
    logs = commands.add_parser("logs", help="read bounded lifecycle log tails; never create or repair logs")
    selected_logs = logs.add_mutually_exclusive_group(required=True)
    selected_logs.add_argument("-t", "--target")
    selected_logs.add_argument("--server", help="service alias or exact service ID")
    logs.add_argument("--limit", type=int, default=50, help="maximum visible events, 1..100 (default: 50)")
    start = commands.add_parser("start", help="explicitly start/reuse a named mux's service; never replay mux creation")
    start.add_argument("-t", "--target", required=True)
    server = commands.add_parser("server", help="manage a workspace service independently of mux names")
    server_commands = server.add_subparsers(dest="server_action", required=True)
    server_start = server_commands.add_parser("start", help="start/reuse a workspace service without creating a mux")
    server_start.add_argument("--workspace", help="service workspace; defaults to cwd")
    server_start.add_argument("--name", help="optional stable service alias (separate from mux names)")
    server_start.add_argument("--trace-for", type=int, metavar="SECONDS",
                              help="request bounded trace for this new instance only, 1..3600 seconds")
    stop = commands.add_parser("stop", help="gracefully stop a selected service; never force-kill")
    stopped = stop.add_mutually_exclusive_group(required=True)
    stopped.add_argument("--server", help="service alias or exact service ID")
    stopped.add_argument("--all", action="store_true", help="stop only the confirmed namespace instance snapshot")
    stop.add_argument("--yes", action="store_true", help="confirm stopping this service and all its muxes")
    close = commands.add_parser("close", help="close one mux, or reconcile an exact previous close; keep Session files")
    target = close.add_mutually_exclusive_group(required=True)
    target.add_argument("-t", "--target")
    target.add_argument("--server")
    close.add_argument("--operation", help="exact previous close operation ID; requires --server")
    close.add_argument("--continue", dest="continue_close", action="store_true",
                       help="explicitly resend the same idempotent close; requires --server and --operation")
    close.add_argument("--yes", action="store_true", help="confirm this exact close or reconciliation")
    status = commands.add_parser("close-status", help="read-only close result; never start, renew, close, or reconcile")
    status.add_argument("--server", required=True)
    status.add_argument("--operation", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.action == "logs" and not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    if getattr(args, "trace_for", None) is not None and not 1 <= args.trace_for <= 3600:
        parser.error("--trace-for must be between 1 and 3600 seconds")
    if args.action in (None, "new", "attach") and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        parser.error("interactive lmux requires a terminal on stdin and stdout")
    if args.action in ("stop", "close") and not args.yes and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        parser.error("non-interactive " + args.action + " requires --yes")
    if args.action == "create":
        if args.yes and not args.continue_create:
            parser.error("--yes requires --continue")
        if args.continue_create and not args.yes and (not sys.stdin.isatty() or not sys.stdout.isatty()):
            parser.error("non-interactive create --continue requires --yes")
    if args.action == "close" and (bool(args.server) != bool(args.operation) or args.continue_close and not args.operation):
        parser.error("--operation requires --server; --continue requires both")
    from loushang.apphost.managed.contracts import (
        ManagedContractError,
        require_mux_name,
        require_service_alias,
    )

    for name in (getattr(args, "name", None), getattr(args, "target", None), getattr(args, "after", None)):
        if name is not None:
            try:
                (require_service_alias if args.action == "server" else require_mux_name)(name)
            except ManagedContractError:
                parser.error("invalid service alias" if args.action == "server" else "invalid mux name")
    if args.action in ("stop", "close", "close-status", "create", "create-status", "status", "logs"):
        from loushang.apphost.managed.contracts import _HEX32, _HEX64, _match

        try:
            if args.server is not None:
                if args.action in ("stop", "status", "logs") and _HEX64.fullmatch(args.server) is None:
                    require_service_alias(args.server)
                else:
                    _match(args.server, _HEX64)
            if getattr(args, "operation", None) is not None:
                _match(args.operation, _HEX32)
        except ManagedContractError:
            parser.error("expected service alias or exact service ID" if args.action in ("stop", "status", "logs")
                         else "expected exact service and operation IDs")
    from .lmux_command import execute

    return execute(args, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
