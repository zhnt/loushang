from __future__ import annotations

import asyncio
from io import StringIO
from types import SimpleNamespace

from loushang.harness.cli import configure_agent_cli_session


class _ExtensionRunner:
    def __init__(self) -> None:
        self.values: list[tuple[str, object]] = []

    def set_flag_value(self, name: str, value: object) -> None:
        self.values.append((name, value))


class _Session:
    def __init__(self) -> None:
        self.extension_runner = _ExtensionRunner()
        self.name: str | None = None
        self.thinking: object | None = None

    def set_session_name(self, name: str) -> None:
        self.name = name

    async def set_thinking_level(self, level: object) -> None:
        self.thinking = level


def test_agent_session_configuration_uses_injected_model_policy() -> None:
    session = _Session()
    stderr = StringIO()
    applied: list[object] = []

    async def apply_model(_session: object, selection: object) -> object:
        applied.append(selection)
        return SimpleNamespace(selection=selection)

    result = asyncio.run(
        configure_agent_cli_session(
            session,
            session_name="Research",
            extension_flag_values={"review": True},
            model_selection=None,
            resolve_model_selection=lambda: "provider/model",
            thinking_level="high",
            apply_model_selection=apply_model,
            model_result_warning=lambda _result: "persistence unavailable",
            stderr=stderr,
        )
    )

    assert result is None
    assert session.name == "Research"
    assert session.extension_runner.values == [("review", True)]
    assert session.thinking == "high"
    assert applied == ["provider/model"]
    assert stderr.getvalue() == "Warning: persistence unavailable\n"


def test_agent_session_configuration_contains_model_parse_errors() -> None:
    stderr = StringIO()

    result = asyncio.run(
        configure_agent_cli_session(
            _Session(),
            session_name=None,
            extension_flag_values={},
            model_selection=None,
            resolve_model_selection=lambda: (_ for _ in ()).throw(
                ValueError("invalid model")
            ),
            thinking_level=None,
            apply_model_selection=None,
            model_result_warning=None,
            stderr=stderr,
        )
    )

    assert result == 1
    assert stderr.getvalue() == "Error: invalid model\n"
