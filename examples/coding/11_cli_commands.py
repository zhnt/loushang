from __future__ import annotations

import asyncio
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loushang.coding.cli.__main__ import run_cli

EXTENSION_SOURCE = """
def register(api):
    async def deploy(args, ctx):
        await ctx.sendMessage(
            {
                "customType": "deploy_result",
                "content": f"args={args}; cwd={ctx.cwd}; tools={','.join(sorted(ctx.get_active_tool_names()))}",
                "display": True,
            },
            {"triggerTurn": False},
        )

    api.register_command(
        name="deploy",
        description="Run a fake deploy operation with args",
        handler=deploy,
    )
"""


async def _run_cli(project_root: Path, argv: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = await run_cli(
        argv,
        cwd=project_root,
        stdout=stdout,
        stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def _write_extension(project_root: Path) -> None:
    extensions_dir = project_root / "extensions"
    extensions_dir.mkdir(parents=True, exist_ok=True)
    (extensions_dir / "commands.py").write_text(EXTENSION_SOURCE.strip() + "\n", encoding="utf-8")


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-coding-cli-") as tmpdir:
        project_root = Path(tmpdir)
        _write_extension(project_root)

        print("=== CLI commands demo ===")
        print(f"Project root: {project_root}")
        print()

        list_code, list_stdout, list_stderr = await _run_cli(project_root, ["--list-commands"])
        print(f"--list-commands -> code {list_code}")
        print(list_stdout or "<no output>")
        if list_stderr:
            print(f"stderr: {list_stderr}", file=sys.stderr)

        print()

        json_list_code, json_list_stdout, json_list_stderr = await _run_cli(
            project_root,
            ["--list-commands", "--list-commands-format", "json"],
        )
        print(f"--list-commands --list-commands-format json -> code {json_list_code}")
        print(json_list_stdout or "<no output>")
        if json_list_stderr:
            print(f"stderr: {json_list_stderr}", file=sys.stderr)

        print()

        exec_code, exec_stdout, exec_stderr = await _run_cli(
            project_root,
            ["--command", "deploy", "--command-args", "prod"],
        )
        print(f'--command deploy "prod" -> code {exec_code}')
        print(exec_stdout.rstrip())
        if exec_stderr:
            print(f"stderr: {exec_stderr}", file=sys.stderr)

        print()

        json_exec_code, json_exec_stdout, json_exec_stderr = await _run_cli(
            project_root,
            [
                "--command",
                "deploy",
                "--command-args",
                "prod",
                "--command-result-format",
                "json",
            ],
        )
        print(f'--command deploy "prod" --command-result-format json -> code {json_exec_code}')
        print(json_exec_stdout.rstrip())
        if json_exec_stderr:
            print(f"stderr: {json_exec_stderr}", file=sys.stderr)

        print()
        print("CLI invocation finished.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
