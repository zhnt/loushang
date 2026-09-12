"""Console/module entrypoint; application policy lives in its own module."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loushang.coding.cli.application import run_cli as run_cli


def __getattr__(name: str) -> Any:
    # Historical helper reads remain available; application owns their injection.
    if name.startswith("__"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from loushang.coding.cli import application

    value = getattr(application, name)
    if name == "run_cli":
        globals()[name] = value
    return value


async def _run_entry(argv: list[str] | tuple[str, ...]) -> int:
    # Only this exact invocation has no grammar/extension/dispatch decisions.
    # Explicitly materialized or replaced run_cli bindings retain their behavior.
    if tuple(argv) == ("--version",) and "run_cli" not in globals():
        from importlib.metadata import PackageNotFoundError, version

        try:
            installed_version = version("loushang")
        except PackageNotFoundError:
            installed_version = "0.1.0"
        sys.stdout.write(f"{installed_version}\n")
        return 0
    if (
        "run_cli" not in globals()
        and "loushang.coding.cli.application" not in sys.modules
    ):
        from loushang.coding.cli.startup_route import early_screen_project_root

        project_root = early_screen_project_root(
            tuple(argv), stdin=sys.stdin, stdout=sys.stdout
        )
        if project_root is not None:
            from loushang.coding.cli.screen_startup import run_screen_first_cli

            return await run_screen_first_cli(
                tuple(argv), project_root=project_root, cwd=None
            )
    runner = globals()["run_cli"] if "run_cli" in globals() else __getattr__("run_cli")
    return await runner(argv)


def main(argv: list[str] | tuple[str, ...] | None = None) -> int:
    import asyncio

    try:
        return asyncio.run(_run_entry(sys.argv[1:] if argv is None else argv))
    except KeyboardInterrupt:
        sys.stderr.write("Interrupted.\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
