from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
while not (REPO_ROOT / "src").exists() and REPO_ROOT.parent != REPO_ROOT:
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loushang.coding import create_coding_tools


def _result_text(result) -> str:
    return "\n".join(
        part.text for part in result.content if getattr(part, "type", None) == "text"
    )


async def _run_tool_command(tool, tool_call_id: str, params: dict[str, object]) -> str:
    try:
        result = await tool.execute(tool_call_id, params)
    except PermissionError as error:
        return f"Blocked by policy: {error}"
    return _result_text(result)


async def main() -> None:
    bash_tool = next(tool for tool in create_coding_tools() if tool.name == "bash")

    allowed_result = await bash_tool.execute(
        "call-allow",
        {
            "command": ["/bin/sh", "-lc", "printf hello-from-bash-tool"],
            "cwd": str(Path.cwd()),
        },
    )
    gated_result_text = await _run_tool_command(
        bash_tool,
        "call-ask",
        {
            "command": ["/bin/sh", "-lc", "git push origin main"],
            "cwd": str(Path.cwd()),
        },
    )

    print("=== Built-In Bash Tool ===")
    print("Allowed command result:")
    print(_result_text(allowed_result))
    print()
    print("Policy-gated command result:")
    print(gated_result_text)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
