"""Small native Extension author journey owned by Coding."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory

from loushang.ai.provider._offline_adapter import OfflineModelAdapter
from loushang.ai.types import ToolCall
from loushang.coding.composition.bootstrap import create_agent_session, create_services
from loushang.coding.package.pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.resources.runtime import CodingResourceLoader
from loushang.coding.session.manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_authoring._offline_smoke import (
    capture_authoring_input,
    hold_authoring_home,
    require_authoring_tool_result,
)
from loushang.harness.session._cleanup import hold_authoring_session

_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_MAX_SOURCE_BYTES = 1024 * 1024


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="loushang-coding-extension",
        description="Create or prove a trusted workspace Python Extension.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create one no-replace Extension file")
    init.add_argument("destination", help="file under .loushang/extensions/")
    smoke = commands.add_parser(
        "smoke", help="run one Extension tool in a disposable offline Coding Session"
    )
    smoke.add_argument("source_file")
    smoke.add_argument("--tool", required=True)
    smoke.add_argument(
        "--arguments", default="{}", help="JSON object of tool arguments"
    )
    smoke.add_argument("--expect", help="text expected in the tool result")
    args = parser.parse_args(argv)
    if args.command == "init":
        try:
            report = create_extension_source(args.destination)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    try:
        arguments = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        parser.error(f"--arguments must be a JSON object: {exc}")
    if not isinstance(arguments, dict) or any(
        not isinstance(key, str) for key in arguments
    ):
        parser.error("--arguments must be a JSON object")
    report = smoke_extension_source(
        args.source_file,
        tool_name=args.tool,
        arguments=arguments,
        expected_text=args.expect,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


def create_extension_source(destination: str | Path) -> dict[str, object]:
    """Create a trusted single-file Extension without replacing existing source."""

    source = Path(destination).expanduser().absolute()
    name = source.stem
    if source.suffix != ".py" or _NAME.fullmatch(name) is None:
        raise ValueError(
            "Extension destination must be a lowercase snake_case .py file"
        )
    if source.exists() or source.is_symlink():
        raise FileExistsError(f"Extension source already exists: {source}")
    source.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tool_name = f"{name}_echo"
    body = (
        "from loushang.harness.tools.authoring import direct_tool\n"
        "from loushang.harness.tools.core import tool\n\n\n"
        f'@tool(label="{name} Echo")\n'
        f"async def {tool_name}(message: str) -> str:\n"
        '    """Return the supplied message."""\n'
        f'    return f"{name}: {{message}}"\n\n\n'
        "def register(api):\n"
        f"    api.register_tool(direct_tool({tool_name}))\n"
    )
    with source.open("x", encoding="utf-8") as output:
        output.write(body)
    return {
        "sourcePath": str(source),
        "profile": "coding-native-extension-v1",
        "sourceLoad": "not_checked",
        "sessionSelection": "not_checked",
        "toolUse": "not_checked",
        "smokeCommand": [
            "loushang-coding-extension",
            "smoke",
            str(source),
            "--tool",
            tool_name,
            "--arguments",
            '{"message":"hello"}',
            "--expect",
            f"{name}: hello",
        ],
    }


def smoke_extension_source(
    source_file: str | Path,
    *,
    tool_name: str,
    arguments: dict[str, object],
    expected_text: str | None = None,
) -> dict[str, object]:
    """Prove a trusted Extension tool through real Coding Session execution.

    The temporary workspace isolates Product files, not Python execution. The
    source runs in this process with the caller's own permissions.
    """

    report: dict[str, object] = {
        "status": "failed",
        "sourceLoad": "not_checked",
        "sessionSelection": "not_checked",
        "toolUse": "not_checked",
        "workspace": "disposable",
        "modelTransport": "offline",
        "executionTrust": "trusted_in_process",
    }
    source = Path(source_file).expanduser().absolute()
    if source.suffix != ".py" or _NAME.fullmatch(source.stem) is None:
        return _failure(report, "source_load", "invalid_extension_source")
    if _NAME.fullmatch(tool_name) is None:
        return _failure(report, "session_selection", "invalid_tool_name")
    try:
        source_bytes = capture_authoring_input(
            source,
            maximum_bytes=_MAX_SOURCE_BYTES,
            invalid_input="source must be a regular Python file of at most 1 MiB",
            changed_before_read="source changed while being captured",
            changed_during_read="source changed while being captured",
            require_visible_source=True,
        )
    except (OSError, ValueError) as exc:
        return _failure(report, "source_load", "source_capture_refused", str(exc))
    with (
        TemporaryDirectory(prefix="loushang-extension-smoke-") as scratch,
        hold_authoring_home(Path(scratch) / "home"),
    ):
        workspace = Path(scratch) / "workspace"
        extensions = workspace / ".loushang" / "extensions"
        extensions.mkdir(mode=0o700, parents=True)
        (extensions / source.name).write_bytes(source_bytes)
        try:
            settings = SettingsManager(
                global_settings_path=Path(scratch) / "global-settings.json",
                project_settings_path=workspace / ".loushang" / "settings.json",
            )
            cutover_and_bootstrap_coding_package_product(
                resolve_coding_plugin_lifecycle_state_layout(workspace),
                settings,
                workspace=workspace,
                namespace_id=sha256(source_bytes).hexdigest(),
                runtime_version="0.1.0",
                runtime_protocol_epoch=2,
            )
            asyncio.run(
                _prove_tool_use(
                    workspace,
                    source.stem,
                    tool_name,
                    arguments,
                    expected_text,
                    report,
                    settings,
                )
            )
        except Exception as exc:
            stage = (
                "tool_use"
                if report["sessionSelection"] == "passed"
                else "session_selection"
                if report["sourceLoad"] == "passed"
                else "source_load"
            )
            return _failure(report, stage, "extension_smoke_failed", str(exc))
    report["status"] = "passed"
    return report


async def _prove_tool_use(
    workspace: Path,
    extension_name: str,
    tool_name: str,
    arguments: dict[str, object],
    expected_text: str | None,
    report: dict[str, object],
    settings: SettingsManager,
) -> None:
    adapter = OfflineModelAdapter(
        f"coding-extension-smoke-{token_hex(8)}",
        response_id="extension-smoke",
        text="Extension smoke complete.",
        tool_call=ToolCall(
            type="toolCall", id="extension-smoke-call", name=tool_name, arguments=arguments
        ),
    )
    async with hold_authoring_session(
        adapter.registered(),
        SessionManager,
        lambda manager: create_agent_session(
            session_manager=manager,
            model=adapter.model(
                model_id="offline-extension-smoke",
                name="Offline Extension Smoke",
                endpoint="extension-smoke-offline",
            ),
            system_prompt="Run the author Extension tool.",
            tools=[],
            services=create_services(
                settings_manager=settings,
                resource_loader=CodingResourceLoader(
                    workspace_root=workspace, project_resource_mode="standard"
                ),
            ),
        ),
        workspace=workspace,
        session_dir=workspace / ".loushang-sessions",
    ) as (_, session):
        extensions_result = await session.execute_command_async("/extensions", "")
        extension_listing = getattr(extensions_result, "result", None)
        if extension_name not in str(extension_listing):
            raise RuntimeError("Extension was not listed by the Coding Session")
        report["sourceLoad"] = "passed"
        if tool_name not in session.get_active_tool_names():
            raise RuntimeError(f"Tool {tool_name} is not active in the Coding Session")
        report["sessionSelection"] = "passed"
        await session.prompt(f"Call {tool_name} with the supplied arguments.")
        require_authoring_tool_result(
            session.get_session_context().messages,
            tool_name=tool_name,
            expected_text=expected_text,
        )
        report["toolUse"] = "passed"


def _failure(
    report: dict[str, object], stage: str, code: str, detail: str | None = None
) -> dict[str, object]:
    report[
        {
            "source_load": "sourceLoad",
            "session_selection": "sessionSelection",
            "tool_use": "toolUse",
        }[stage]
    ] = "failed"
    report["failedStage"] = stage
    report["code"] = code
    if detail:
        report["detail"] = detail
    return report


__all__ = ["create_extension_source", "main", "smoke_extension_source"]
