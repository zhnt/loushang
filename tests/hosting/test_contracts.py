from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from loushang.hosting import (
    HOSTING_CONTRACT_VERSION,
    ChildSessionRequest,
    HostingComponent,
    HostingFailureCategory,
    HostingLifecycleTransition,
    HostingObservation,
    InvalidHostingRequestError,
    ProcessExit,
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStderrTail,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)


def _streams() -> ProcessStreamSpec:
    return ProcessStreamSpec(
        stdin=ProcessStdinMode.PIPE,
        stdout=ProcessStdoutMode.PIPE,
        stderr=ProcessStderrMode.CAPTURE_TAIL,
    )


def _request(**overrides: object) -> ProcessLaunchRequest:
    values: dict[str, object] = {
        "argv": (sys.executable, "-c", "print('ok')"),
        "cwd": str(Path.cwd().resolve()),
        "effective_environment": (("PATH", "/admitted/bin"), ("TOKEN", "secret")),
        "streams": _streams(),
    }
    values.update(overrides)
    return ProcessLaunchRequest(**values)  # type: ignore[arg-type]


def test_h0_contract_is_versioned_immutable_and_normalizes_sequences() -> None:
    request = _request(
        argv=[sys.executable, ""],
        effective_environment=[["PATH", "/bin"]],
    )

    assert HOSTING_CONTRACT_VERSION == "loushang.hosting/v1"
    assert request.argv == (sys.executable, "")
    assert request.effective_environment == (("PATH", "/bin"),)
    assert dataclasses.is_dataclass(request)
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.cwd = "/replacement"  # type: ignore[misc]


def test_request_repr_never_discloses_effective_environment_values() -> None:
    request = _request()

    assert "secret" not in repr(request)
    assert "TOKEN" not in repr(request)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("argv", "echo unsafe", "not a shell string"),
        ("argv", (), "must not be empty"),
        ("argv", ("python",), "absolute executable path"),
        ("argv", (sys.executable, b"bytes"), "only strings"),
        ("argv", (sys.executable, "bad\0arg"), "must not contain NUL"),
        ("cwd", "relative", "absolute path"),
        ("cwd", "/tmp/bad\0cwd", "must not contain NUL"),
        ("effective_environment", {"PATH": "/bin"}, "string pairs"),
        ("effective_environment", (("BAD=NAME", "x"),), "invalid variable name"),
        ("effective_environment", (("A", "x\0y"),), "NUL variable value"),
        (
            "effective_environment",
            (("Path", "one"), ("PATH", "two")),
            "duplicate variable names",
        ),
    ],
)
def test_materialized_request_rejects_ambient_or_ambiguous_shapes(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(InvalidHostingRequestError, match=message) as caught:
        _request(**{field: value})

    assert caught.value.category is HostingFailureCategory.INVALID_REQUEST
    assert caught.value.field == field or field == "argv"


def test_stream_intent_rejects_strings_instead_of_coercing_them() -> None:
    with pytest.raises(TypeError, match="ProcessStdinMode"):
        ProcessStreamSpec(  # type: ignore[arg-type]
            stdin="pipe",
            stdout=ProcessStdoutMode.PIPE,
            stderr=ProcessStderrMode.PIPE,
        )


def test_child_session_request_accepts_only_the_hosting_process_contract() -> None:
    request = _request()

    assert ChildSessionRequest(process=request).process is request
    with pytest.raises(InvalidHostingRequestError, match="ProcessLaunchRequest"):
        ChildSessionRequest(process=object())  # type: ignore[arg-type]

def test_exit_and_stderr_tail_are_raw_immutable_mechanism_facts() -> None:
    exit_result = ProcessExit(return_code=-9)
    tail = ProcessStderrTail(content=b"bounded", truncated=True)

    assert exit_result.return_code == -9
    assert tail == ProcessStderrTail(content=b"bounded", truncated=True)
    assert "bounded" not in repr(tail)
    with pytest.raises(TypeError, match="integer"):
        ProcessExit(return_code=True)  # type: ignore[arg-type]


def test_observations_have_a_closed_schema_and_typed_failure_boundary() -> None:
    failed = HostingObservation(
        component=HostingComponent.PROCESS,
        transition=HostingLifecycleTransition.FAILED,
        owner_id="lease-1",
        backend_id="posix",
        failure=HostingFailureCategory.SPAWN_FAILED,
    )

    assert failed.failure is HostingFailureCategory.SPAWN_FAILED
    assert {field.name for field in dataclasses.fields(failed)} == {
        "component",
        "transition",
        "owner_id",
        "session_id",
        "backend_id",
        "failure",
    }
    with pytest.raises(ValueError, match="require a failure category"):
        HostingObservation(
            component=HostingComponent.PROCESS,
            transition=HostingLifecycleTransition.FAILED,
            owner_id="lease-1",
        )
    with pytest.raises(ValueError, match="only failed observations"):
        HostingObservation(
            component=HostingComponent.PROCESS,
            transition=HostingLifecycleTransition.CLOSED,
            owner_id="lease-1",
            failure=HostingFailureCategory.CLEANUP_FAILED,
        )


def test_observation_identifiers_are_bounded_and_nul_free() -> None:
    with pytest.raises(ValueError, match="1-128"):
        HostingObservation(
            component=HostingComponent.PROCESS,
            transition=HostingLifecycleTransition.PUBLISHED,
            owner_id="x" * 129,
        )
    with pytest.raises(ValueError, match="NUL-free"):
        HostingObservation(
            component=HostingComponent.SESSION,
            transition=HostingLifecycleTransition.PUBLISHED,
            owner_id="owner",
            session_id="bad\0id",
        )
