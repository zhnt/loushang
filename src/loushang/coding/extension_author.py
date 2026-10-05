"""Small native Extension author journey owned by Coding."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import stat
from collections.abc import AsyncIterator, Sequence
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.event_stream.raw_parts import RawPart
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.provider.protocol import ProviderRequest
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.resource_runtime import CodingResourceLoader
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager

_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_MAX_SOURCE_BYTES = 1024 * 1024


class _OfflineToolAdapter:
    def __init__(self, tool_name: str, arguments: dict[str, object]) -> None:
        self.api = f"coding-extension-smoke-{token_hex(8)}"
        self.tool_name = tool_name
        self.arguments = arguments

    def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
        return PreparedModelRequest.from_provider_request(
            request,
            payload={
                "system": request.context.system_prompt,
                "messages": [
                    serialize_message(item) for item in request.context.messages
                ],
                "model": request.model.id,
            },
        )

    async def invoke_prepared_raw(
        self, request: ProviderRequest, prepared: PreparedModelRequest
    ) -> AsyncIterator[RawPart]:
        prepared.payload_for_transport()
        yield {"type": "response_start", "response_id": "extension-smoke"}
        if any(
            getattr(item, "role", None) == "toolResult"
            for item in request.context.messages
        ):
            yield {"type": "text_delta", "text": "Extension smoke complete."}
            yield {"type": "stop_reason", "stop_reason": "stop"}
        else:
            yield {
                "type": "tool_call_start",
                "id": "extension-smoke-call",
                "name": self.tool_name,
            }
            yield {
                "type": "tool_call_args_delta",
                "tool_call_id": "extension-smoke-call",
                "delta": json.dumps(self.arguments),
            }
            yield {"type": "tool_call_done", "tool_call_id": "extension-smoke-call"}
            yield {"type": "stop_reason", "stop_reason": "toolUse"}
        yield {"type": "response_done"}

    async def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]:
        prepared = self.prepare_request(request)
        async for part in self.invoke_prepared_raw(request, prepared):
            yield part


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
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_SOURCE_BYTES:
            raise ValueError("source must be a regular Python file of at most 1 MiB")
        source_bytes = source.read_bytes()
        if len(source_bytes) != info.st_size or source.stat().st_ino != info.st_ino:
            raise ValueError("source changed while being captured")
    except (OSError, ValueError) as exc:
        return _failure(report, "source_load", "source_capture_refused", str(exc))
    with TemporaryDirectory(prefix="loushang-extension-smoke-") as scratch:
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
    adapter = _OfflineToolAdapter(tool_name, arguments)
    registry = get_default_api_registry()
    registry.register_api_adapter(adapter, source_id=adapter.api)
    manager = await SessionManager.new(
        session_dir=workspace / ".loushang-sessions", cwd=str(workspace), persist=True
    )
    session = None
    try:
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="offline-extension-smoke",
                name="Offline Extension Smoke",
                provider="test",
                endpoint="extension-smoke-offline",
                api=adapter.api,
                base_url="https://provider.invalid/v1",
                auth=Auth(kind="none"),
                capabilities=Capabilities(
                    input=("text",),
                    output=("text",),
                    context_window=128000,
                    stream=True,
                    tool_use=True,
                ),
            ),
            system_prompt="Run the author Extension tool.",
            tools=[],
            services=create_services(
                settings_manager=settings,
                resource_loader=CodingResourceLoader(
                    workspace_root=workspace, project_resource_mode="standard"
                ),
            ),
        )
        extensions_result = await session.execute_command_async("/extensions", "")
        extension_listing = getattr(extensions_result, "result", None)
        if extension_name not in str(extension_listing):
            raise RuntimeError("Extension was not listed by the Coding Session")
        report["sourceLoad"] = "passed"
        if tool_name not in session.get_active_tool_names():
            raise RuntimeError(f"Tool {tool_name} is not active in the Coding Session")
        report["sessionSelection"] = "passed"
        await session.prompt(f"Call {tool_name} with the supplied arguments.")
        results = [
            message
            for message in session.get_session_context().messages
            if getattr(message, "role", None) == "toolResult"
            and getattr(message, "tool_name", None) == tool_name
        ]
        if len(results) != 1 or results[0].is_error:
            raise RuntimeError(
                "The requested tool did not return one successful result"
            )
        result_text = "\n".join(
            part.text
            for part in results[0].content
            if getattr(part, "type", None) == "text"
        )
        if expected_text is not None and expected_text not in result_text:
            raise RuntimeError("Tool result did not contain the expected text")
        report["toolUse"] = "passed"
    finally:
        if session is not None:
            await session.dispose()
        registry.unregister_api_adapters(adapter.api)


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
