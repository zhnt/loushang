from __future__ import annotations

import asyncio
import json
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

from loushang.coding import create_agent_session_runtime
from loushang.harness.host.rpc import run_rpc_host

RPC_COMMANDS = [
    ("intro", {"type": "get_state"}),
    ("models", {"type": "get_available_models"}),
    ("commands", {"type": "get_commands"}),
    ("set-name", {"type": "set_session_name", "name": "RPC Probe"}),
    ("state-after-set", {"type": "get_state"}),
]


async def _run_rpc(project_root: Path) -> tuple[int, str, str]:
    runtime = create_agent_session_runtime(session_dir=project_root / ".loushang-sessions")
    await runtime.new_session(cwd=project_root)

    payload_lines = [json.dumps({"id": request_id, **payload}) for request_id, payload in RPC_COMMANDS]
    stdin = StringIO("\n".join(payload_lines) + "\n")
    stdout = StringIO()
    stderr = StringIO()

    exit_code = await run_rpc_host(
        runtime=runtime,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )
    return exit_code, stdout.getvalue(), stderr.getvalue()


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-rpc-probe-") as tmpdir:
        project_root = Path(tmpdir)
        print(f"Project root: {project_root}")

        exit_code, raw_output, raw_error = await _run_rpc(project_root)

        print(f"RPC host exit code: {exit_code}")
        print("Responses:")
        for line in raw_output.splitlines():
            payload = json.loads(line)
            command = payload.get("command")
            success = payload.get("success")
            request_id = payload.get("id")
            if command == "get_available_models":
                model_count = len(payload.get("data", {}).get("models", []))
                print(f"[{request_id}] {command}: success={success}, models={model_count}")
            elif command == "get_commands":
                command_count = len(payload.get("data", {}).get("commands", []))
                print(f"[{request_id}] {command}: success={success}, commands={command_count}")
            elif command == "get_state":
                state = payload.get("data", {})
                model = state.get("model", {})
                session_name = state.get("sessionName", "")
                print(
                    f"[{request_id}] {command}: success={success}, "
                    f"session={state.get('sessionId')}, model={model.get('provider')}/{model.get('id')}, "
                    f"name={session_name}"
                )
            else:
                print(f"[{request_id}] {command}: success={success}")

        if raw_error:
            print("stderr:")
            print(raw_error)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
