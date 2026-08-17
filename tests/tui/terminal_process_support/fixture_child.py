from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="scenario", required=True)

    metadata = subparsers.add_parser("metadata")
    metadata.add_argument("--argument", required=True)
    metadata.add_argument("--env-name", required=True)

    subparsers.add_parser("resize")
    subparsers.add_parser("query")

    large = subparsers.add_parser("large")
    large.add_argument("--size", type=int, default=200_000)
    large.add_argument("--code", type=int, default=7)

    tree = subparsers.add_parser("tree")
    tree.add_argument("--pid-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.scenario == "metadata":
        payload = {
            "argument": args.argument,
            "cwd": os.getcwd(),
            "env": os.environ[args.env_name],
            "size": list(os.get_terminal_size(sys.stdout.fileno())),
        }
        sys.stdout.write("META:" + json.dumps(payload, ensure_ascii=False) + "\r\n")
        sys.stdout.write("UNICODE:中文🙂\r\n")
        sys.stdout.write("VT:\x1b[31mred\x1b[0m:NO_NEWLINE")
        sys.stdout.flush()
        return 0
    if args.scenario == "resize":
        initial = os.get_terminal_size(sys.stdout.fileno())
        print(f"INITIAL_SIZE:{initial.columns}x{initial.lines}", flush=True)
        sys.stdin.readline()
        resized = os.get_terminal_size(sys.stdout.fileno())
        print(f"RESIZED_SIZE:{resized.columns}x{resized.lines}", flush=True)
        return 0
    if args.scenario == "query":
        _enable_immediate_input()
        sys.stdout.write("\x1b[")
        sys.stdout.flush()
        time.sleep(0.01)
        sys.stdout.write("5n")
        sys.stdout.flush()
        status = _read_characters(4)
        print(f"STATUS_GOT:{status.encode().hex()}", flush=True)
        sys.stdout.write("\x1b[6")
        sys.stdout.flush()
        time.sleep(0.01)
        sys.stdout.write("n")
        sys.stdout.flush()
        cursor = _read_characters(6)
        print(f"CURSOR_GOT:{cursor.encode().hex()}", flush=True)
        print(f"QUERY_OK:{status.encode().hex()}:{cursor.encode().hex()}", flush=True)
        cursor_is_valid = re.fullmatch(r"\x1b\[[1-9]\d*;[1-9]\d*R", cursor)
        return 0 if status == "\x1b[0n" and cursor_is_valid else 9
    if args.scenario == "large":
        _enable_immediate_input()
        sys.stdout.write("LARGE_BEGIN")
        for index, offset in enumerate(range(0, args.size, 1000)):
            chunk_size = min(1000, args.size - offset)
            sys.stdout.write(("界" * chunk_size) + f"LARGE_CHUNK:{index}:")
            sys.stdout.flush()
            if _read_characters(1) != "c":
                return 10
        sys.stdout.write("LARGE_END")
        sys.stdout.flush()
        if _read_characters(1) != "c":
            return 10
        return args.code
    if args.scenario == "tree":
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        args.pid_file.write_text(
            json.dumps({"root": os.getpid(), "child": child.pid}),
            encoding="utf-8",
        )
        print(f"TREE_READY:{os.getpid()}:{child.pid}", flush=True)
        time.sleep(60)
        return 0
    raise AssertionError(args.scenario)


def _enable_immediate_input() -> None:
    if os.name == "nt":
        import ctypes
        import msvcrt

        # ConPTY delivers terminal responses as VT input only when the child
        # console requests that mode. Disable cooked line/echo handling so a
        # split DSR response is observable character-for-character.
        handle = ctypes.c_void_p(msvcrt.get_osfhandle(sys.stdin.fileno()))
        mode = ctypes.c_uint32()
        if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            raise ctypes.WinError()
        requested = (mode.value | 0x0080 | 0x0200) & ~(0x0002 | 0x0004 | 0x0040)
        if not ctypes.windll.kernel32.SetConsoleMode(
            handle, ctypes.c_uint32(requested)
        ):
            raise ctypes.WinError()
        return
    import termios
    import tty

    fd = sys.stdin.fileno()
    tty.setcbreak(fd)
    attrs = termios.tcgetattr(fd)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def _read_characters(count: int) -> str:
    if os.name == "nt":
        import msvcrt

        return "".join(msvcrt.getwch() for _ in range(count))
    return sys.stdin.read(count)


if __name__ == "__main__":
    raise SystemExit(main())
