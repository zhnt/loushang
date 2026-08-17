from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

import loushang.harness.workspace.process as process_contracts
from loushang.harness.workspace.process import ProcessLaunchRequest


def test_launch_request_freezes_shell_free_process_state(tmp_path: Path) -> None:
    command = ["server", "--stdio"]
    environment = [["TOKEN", "secret"], ["MODE", "test"]]

    request = ProcessLaunchRequest(
        command=command,
        cwd=str(tmp_path),
        effective_environment=environment,
    )
    command.append("--mutated")
    environment[0][1] = "changed"

    assert request.command == ("server", "--stdio")
    assert request.cwd == str(tmp_path.resolve())
    assert request.effective_environment == (("TOKEN", "secret"), ("MODE", "test"))
    assert "secret" not in repr(request)


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        (
            {
                "command": "server --stdio",
                "cwd": "/tmp",
                "effective_environment": (),
            },
            TypeError,
            "shell string",
        ),
        (
            {"command": ("server",), "cwd": "relative", "effective_environment": ()},
            ValueError,
            "absolute path",
        ),
        (
            {
                "command": ("server",),
                "cwd": "/tmp",
                "effective_environment": (("A", "1"), ("A", "2")),
            },
            ValueError,
            "unique",
        ),
    ],
)
def test_launch_request_rejects_ambiguous_process_state(
    kwargs: dict[str, object],
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        ProcessLaunchRequest(**kwargs)  # type: ignore[arg-type]


def test_public_contract_does_not_expose_host_or_caller_controlled_limits() -> None:
    assert "ProcessHost" not in process_contracts.__all__
    assert not hasattr(process_contracts, "ProcessHost")
    assert "ProcessExecutionScope" not in process_contracts.__all__
    assert not hasattr(process_contracts, "ProcessExecutionScope")
    assert {field.name for field in fields(ProcessLaunchRequest)} == {
        "command",
        "cwd",
        "effective_environment",
    }
