from __future__ import annotations

import asyncio
import json
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from loushang.ai.model import Capabilities, Model
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.cli.__main__ import _run_coding_pre_runtime_operation, run_cli
from loushang.coding.cli.args import parse_args
from loushang.coding.cli.lsp import run_coding_lsp_command
from loushang.coding.control import ControlConfig, SettingsManager
from loushang.coding.lsp import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.cli import AgentCliStatePreparationContext


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128_000,
            max_tokens=4_096,
        ),
    )


def _configure_python_server(config_dir: Path) -> None:
    config = config_dir / "lsp.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "id": "configured-python",
                        "command": [sys.executable, "-m", "configured_lsp"],
                        "language_extensions": {"python": [".py"]},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_status_and_doctor_inspect_catalog_without_starting_process(
    tmp_path: Path,
) -> None:
    user_config_dir = tmp_path / "user-config"
    _configure_python_server(user_config_dir)
    services = create_services(
        settings_manager=SettingsManager(
            ControlConfig(capabilities={"coding.lsp": "always"}),
            global_settings_path=user_config_dir / "settings.json",
        )
    )
    stdout = StringIO()

    exit_code = asyncio.run(
        run_coding_lsp_command(
            ("status", "--format", "json"),
            stdin=StringIO(),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
            services=services,
            build_services=lambda _root: (_ for _ in ()).throw(
                AssertionError("provided services must be reused")
            ),
        )
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["scope"] == "catalog"
    assert payload["mount_mode"] == "always"
    assert payload["admitted_count"] >= 1
    assert payload["process_start_attempted"] is False
    configured = next(
        item
        for item in payload["servers"]
        if item["definition_id"] == "configured-python"
    )
    assert configured["state"] == "admitted"


def test_doctor_reports_missing_servers_without_attempting_install(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    services = create_services(
        settings_manager=SettingsManager(
            ControlConfig(capabilities={"coding.lsp": "always"})
        )
    )
    stdout = StringIO()

    exit_code = asyncio.run(
        run_coding_lsp_command(
            ("doctor",),
            stdin=StringIO(),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
            services=services,
            build_services=lambda _root: services,
        )
    )

    assert exit_code == 1
    assert "Scope: catalog (offline)" in stdout.getvalue()
    assert "Process start attempted: no" in stdout.getvalue()
    assert "no language server is available" in stdout.getvalue()


def test_doctor_fails_for_rejected_config_even_when_another_server_is_admitted(
    tmp_path: Path,
) -> None:
    user_config_dir = tmp_path / "user-config"
    _configure_python_server(user_config_dir)
    config = user_config_dir / "lsp.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["servers"].append(
        {
            "id": "broken",
            "command": "not-an-array",
            "language_extensions": {"python": [".py"]},
        }
    )
    config.write_text(json.dumps(payload), encoding="utf-8")
    services = create_services(
        settings_manager=SettingsManager(
            ControlConfig(capabilities={"coding.lsp": "always"}),
            global_settings_path=user_config_dir / "settings.json",
        )
    )
    stdout = StringIO()

    exit_code = asyncio.run(
        run_coding_lsp_command(
            ("doctor",),
            stdin=StringIO(),
            stdout=stdout,
            stderr=StringIO(),
            cwd=tmp_path,
            services=services,
            build_services=lambda _root: services,
        )
    )

    assert exit_code == 1
    assert "configuration errors require attention" in stdout.getvalue()


def test_top_level_lsp_command_short_circuits_session_runtime(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    async def lsp_runner(argv, **kwargs):
        del kwargs
        calls.append(tuple(argv))
        return 7

    exit_code = asyncio.run(
        run_cli(
            ("lsp", "status"),
            cwd=tmp_path,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=StringIO(),
            lsp_runner=lsp_runner,
            runtime_builder=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("status must not construct a session runtime")
            ),
        )
    )

    assert exit_code == 7
    assert calls == [("status",)]


def test_generic_cli_capability_override_activates_coding_lsp() -> None:
    manager = SettingsManager()
    services = create_services(settings_manager=manager)
    context = AgentCliStatePreparationContext(
        args=parse_args(["--capability", "coding.lsp=always"]),
        project_root=Path.cwd(),
        session_dir=Path.cwd() / ".loushang" / "sessions",
        services=services,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    result = asyncio.run(
        _run_coding_pre_runtime_operation(
            context,
            workflow_runner=SimpleNamespace(),
        )
    )

    assert result is None
    assert manager.get_settings().capabilities["coding.lsp"] == "always"


def test_configured_lsp_is_available_to_ordinary_session_and_remains_lazy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from loushang.coding.sandbox import SandboxExecutionRuntime

    user_config_dir = tmp_path / "user-config"
    _configure_python_server(user_config_dir)
    starts: list[object] = []

    class _NeverLauncher:
        async def start(self, *args: object, **kwargs: object) -> object:
            starts.append((args, kwargs))
            raise AssertionError("session construction must not start an LSP server")

    monkeypatch.setattr(
        SandboxExecutionRuntime,
        "bind_process_launcher",
        lambda _runtime, _scope: _NeverLauncher(),
    )
    services = create_services(
        settings_manager=SettingsManager(
            ControlConfig(capabilities={"coding.lsp": "always"}),
            global_settings_path=user_config_dir / "settings.json",
        )
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            persist=False,
        )
    )

    session = create_agent_session(
        session_manager=manager,
        services=services,
        model=_model(),
    )

    assert {INSPECT_SYMBOL_TOOL_NAME, DOCUMENT_OUTLINE_TOOL_NAME}.issubset(
        session.get_active_tool_names()
    )
    assert "lsp" in {command.name for command in session.list_commands()}
    command_result = asyncio.run(session.execute_command_async("lsp", "status"))
    assert command_result is not None
    assert command_result.result["scope"] == "session"
    assert command_result.result["servers"] == []
    assert "No language server has been started" in command_result.result["display"]
    assert starts == []
    asyncio.run(session.dispose())
