from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    DEFAULT_SYSTEM_PROMPT,
    attach_stream_printer,
    build_kimi_model,
    describe_model,
    resolve_api_key,
)

from loushang.ai import ApiKeyAuth, CallOptions
from loushang.coding import (
    create_agent_session_runtime,
)
from loushang.coding import (
    register_coding_builtin_tools as register_builtin_tools,
)
from loushang.harness.tools.workspace.registry import (
    WorkspaceToolRegistry as ToolRegistry,
)

EXAMPLE_FIRST_REQUEST = (
    "当前目录有哪些文件？"
    "如果有 docs 目录，列出 docs 目录中的文件。"
)
EXAMPLE_RESUME_REQUEST = "继续查看 README.md，并摘要重点。"
ENV_EXAMPLES_SESSION_DIR = "LOUSHANG_EXAMPLES_SESSION_DIR"


def _resolve_session_dir() -> Path:
    raw = os.environ.get(ENV_EXAMPLES_SESSION_DIR, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd() / ".loushang-sessions"


def _tool_enforced_prompt(user_request: str) -> str:
    return (
        "你有一个可用的 bash 工具。\n"
        "如果用户的问题涉及当前目录、文件列表、路径、文件是否存在、文件内容、"
        "或任何可以通过 shell 验证的本地事实，你必须先调用 bash 工具，再回答。"
        "不要猜测，也不要凭记忆回答。\n"
        "例如：\n"
        "- “当前是什么目录” 应先调用 `pwd`\n"
        "- “当前目录有哪些文件” 应先调用 `ls -1`\n"
        "- “README.md 里写了什么” 应先调用 `cat README.md`\n"
        "在调用工具后，基于真实输出给出简短回答。\n\n"
        f"用户请求：{user_request}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or resume an online coding session with the built-in bash tool.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python examples/coding/08_online_resume_repo_session.py '
            f'"{EXAMPLE_FIRST_REQUEST}"\n'
            '  python examples/coding/08_online_resume_repo_session.py '
            '--resume <session-file>.jsonl '
            '(e.g., ./.loushang-sessions/<session-file>.jsonl, or LOUSHANG_EXAMPLES_SESSION_DIR/<session-file>.jsonl)\n'
            f'"{EXAMPLE_RESUME_REQUEST}"'
        ),
    )
    parser.add_argument(
        "--resume",
        type=Path,
        help="Existing session JSONL file to restore and continue.",
    )
    parser.add_argument(
        "request",
        nargs="+",
        help="Natural-language request to send to the session.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Max seconds to wait for the model response (default: 60).",
    )
    return parser


def _configure_session(session) -> None:
    session.agent.call_options = CallOptions(auth=ApiKeyAuth(resolve_api_key()))
    attach_stream_printer(session)


async def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    user_request = " ".join(args.request).strip()
    if not user_request:
        raise SystemExit(2)

    model = build_kimi_model()
    model_info = describe_model(model)
    registry = ToolRegistry()
    register_builtin_tools(registry)

    if args.resume is not None:
        session_file = args.resume.expanduser().resolve()
        if not session_file.is_file():
            raise FileNotFoundError(f"Session file not found: {session_file}")
        session_dir = session_file.parent
    else:
        session_file = None
        session_dir = _resolve_session_dir()

    runtime = create_agent_session_runtime(
        session_dir=session_dir,
        model=model,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        tools=registry.list_enabled_tools(),
        persist=True,
    )

    if session_file is not None:
        session = await runtime.restore_session(session_file)
        mode = "resume"
    else:
        session = await runtime.create_session(cwd=str(Path.cwd()))
        mode = "start"

    _configure_session(session)

    active_file = session.session_manager.get_session_file()
    print("=== Online Resume Repo Session ===", flush=True)
    print(f"Mode: {mode}", flush=True)
    print(f"Provider: {model_info['provider']}", flush=True)
    print(f"Model: {model_info['model']}", flush=True)
    print(f"Endpoint: {model_info['endpoint']}", flush=True)
    print(f"API: {model_info['api']}", flush=True)
    print(f"Base URL: {model_info['base_url']}", flush=True)
    print(f"CWD: {session.session_manager.get_cwd()}", flush=True)
    print("Tools: bash", flush=True)
    if active_file is not None:
        print(f"Session file: {active_file}", flush=True)
    print(f"Request: {user_request}", flush=True)
    print(flush=True)

    try:
        await asyncio.wait_for(
            session.prompt(_tool_enforced_prompt(user_request)),
            timeout=args.timeout,
        )
    except asyncio.TimeoutError:
        raise SystemExit(f"Prompt timeout ({args.timeout}s). Check network/connectivity/API availability.")
    print(flush=True)

    if active_file is not None:
        print("Resume with:", flush=True)
        print(
            "  python examples/coding/08_online_resume_repo_session.py "
            f'--resume "{active_file}" "{EXAMPLE_RESUME_REQUEST}"',
            flush=True,
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
