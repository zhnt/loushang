from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path

from loushang.harness.runtime import SessionOperationResult


class FakeExtensionRunner:
    def __init__(self, flags) -> None:
        self._flags = list(flags)
        self._values: dict[str, bool | str] = {}

    def get_flags(self):
        return list(self._flags)

    def set_flag_value(self, name: str, value: bool | str) -> None:
        self._values[name] = value

    def get_flag_values(self) -> dict[str, bool | str]:
        return dict(self._values)


class FakeSession:
    def __init__(self, session_id: str, extension_runner: FakeExtensionRunner) -> None:
        self.session_id = session_id
        self.session_name = session_id
        self.session_file = Path(f"/tmp/{session_id}.jsonl")
        self.extension_runner = extension_runner
        self.set_model_calls = []

    async def set_model(self, selection) -> None:
        self.set_model_calls.append(selection)


class FakeRuntime:
    def __init__(self, session: FakeSession) -> None:
        self._current_session = session
        self.new_session_calls: list[str] = []

    def get_current_session(self) -> FakeSession:
        return self._current_session

    async def new_session(self, *, cwd: str) -> FakeSession:
        self.new_session_calls.append(cwd)
        return self._current_session

    async def new_session_operation(
        self,
        *,
        cwd: str | None = None,
        parent_session: str | None = None,
    ) -> SessionOperationResult[FakeSession, None]:
        del parent_session
        if cwd is None:
            raise ValueError("Fake runtime requires cwd")
        session = await self.new_session(cwd=cwd)
        return SessionOperationResult(
            previous=session,
            current=session,
            payload=None,
            cancelled=False,
        )


class FakeRunner:
    def __init__(self, *, exit_code: int = 0) -> None:
        self.calls: list[dict[str, object]] = []
        self.exit_code = exit_code

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.exit_code


def _fake_services():
    from types import SimpleNamespace

    settings = SimpleNamespace(session_dir=None)
    settings_manager = SimpleNamespace(get_settings=lambda: settings)
    return SimpleNamespace(
        settings_manager=settings_manager, diagnostics_service=object()
    )


def test_parse_args_preserves_unknown_extension_flags_for_second_pass() -> None:
    from loushang.coding.cli.args import parse_args

    args = parse_args(
        ["--mode", "rpc", "--plan", "--request-id", "abc"], allow_unknown=True
    )

    assert args.extension_flag_values == {}
    assert args.unknown_flags == {"plan": True, "request-id": "abc"}


def test_parse_args_applies_extension_flags_on_second_pass() -> None:
    from loushang.coding.cli.args import parse_args
    from loushang.harness.extensions.agent import ResolvedFlag, SourceInfo

    args = parse_args(
        ["--mode", "rpc", "--plan", "--request-id", "abc"],
        extension_flags={
            "plan": ResolvedFlag(
                name="plan",
                type="boolean",
                source_info=SourceInfo(path=Path("/tmp/extensions/demo.py")),
                extension_name="demo",
            ),
            "request-id": ResolvedFlag(
                name="request-id",
                type="string",
                source_info=SourceInfo(path=Path("/tmp/extensions/demo.py")),
                extension_name="demo",
            ),
        },
    )

    assert args.unknown_flags == {}
    assert args.extension_flag_values == {"plan": True, "request-id": "abc"}


def test_run_cli_applies_extension_flag_values_after_extension_discovery(
    tmp_path,
) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.harness.extensions.agent import ResolvedFlag, SourceInfo

    extension_runner = FakeExtensionRunner(
        [
            ResolvedFlag(
                name="plan",
                type="boolean",
                source_info=SourceInfo(path=tmp_path / "extensions" / "demo.py"),
                extension_name="demo",
            )
        ]
    )
    runtime = FakeRuntime(FakeSession("session-1", extension_runner))
    rpc_runner = FakeRunner()

    async def scenario() -> None:
        exit_code = await run_cli(
            ["--mode", "rpc", "--plan"],
            stdin=StringIO(""),
            stdout=StringIO(),
            stderr=StringIO(),
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: runtime,
            rpc_runner=rpc_runner,
        )
        assert exit_code == 0

    asyncio.run(scenario())

    assert runtime.new_session_calls == [str(tmp_path.resolve())]
    assert (
        runtime.get_current_session().extension_runner.get_flag_values()["plan"] is True
    )
    assert rpc_runner.calls[0]["runtime"] is runtime


def test_run_cli_prints_discovered_extension_flags_in_help(tmp_path) -> None:
    from loushang.coding.cli.__main__ import run_cli
    from loushang.harness.extensions.agent import ResolvedFlag, SourceInfo

    extension_runner = FakeExtensionRunner(
        [
            ResolvedFlag(
                name="plan",
                type="boolean",
                description="Enable planning mode",
                default=False,
                source_info=SourceInfo(path=tmp_path / "extensions" / "demo.py"),
                extension_name="demo",
            ),
            ResolvedFlag(
                name="request-id",
                type="string",
                description="Attach request id",
                source_info=SourceInfo(path=tmp_path / "extensions" / "demo.py"),
                extension_name="demo",
            ),
        ]
    )
    runtime = FakeRuntime(FakeSession("session-1", extension_runner))
    runtime_args = []

    async def scenario() -> None:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = await run_cli(
            ["--help"],
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=tmp_path,
            services=_fake_services(),
            runtime_builder=lambda **kwargs: (
                runtime_args.append(kwargs["args"]) or runtime
            ),
        )
        assert exit_code == 0
        value = stdout.getvalue()
        assert "Extension flags:" in value
        assert "--plan [boolean]" in value
        assert "--request-id [string]" in value
        assert "Enable planning mode" in value
        assert stderr.getvalue() == ""

    asyncio.run(scenario())

    assert runtime_args[0].no_session is True
