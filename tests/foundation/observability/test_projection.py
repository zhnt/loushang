from __future__ import annotations

from collections import UserDict
from enum import IntEnum, StrEnum
from pathlib import Path

import pytest

from loushang.foundation.observability import get_log, log_context
from loushang.foundation.observability._router import (
    get_problem_store,
    reset_observability,
)
from loushang.foundation.observability.projection import (
    project_diagnostic_mapping,
    project_diagnostic_value,
)


def setup_function() -> None:
    reset_observability()


def test_problem_records_context_module_component_and_details() -> None:
    log = get_log("loushang.tests.module").bind(component="Worker")

    with log_context(session_id="session-1", run_id=8, cwd="/repo", mode="tui"):
        record = log.problem(
            "tool_validation_failed",
            source="tool",
            recoverable=True,
            details={"tool": "write", "attempt": 2},
        )

    assert record.code == "tool_validation_failed"
    assert record.severity == "error"
    assert record.source == "tool"
    assert record.recoverable is True
    assert record.module == "loushang.tests.module"
    assert record.component == "Worker"
    assert record.session_id == "session-1"
    assert record.run_id == 8
    assert record.cwd == "/repo"
    assert record.mode == "tui"
    assert record.details == {"tool": "write", "attempt": 2}
    assert get_problem_store().all() == [record]


def test_problem_from_exception_extracts_type_and_message() -> None:
    log = get_log("loushang.tests.provider")

    try:
        raise RuntimeError("request cancelled")
    except RuntimeError as exc:
        record = log.problem_from_exception(
            exc,
            code="provider_request_cancelled",
            source="provider",
            recoverable=True,
        )

    assert record.code == "provider_request_cancelled"
    assert record.message == "request cancelled"
    assert record.exception_type == "RuntimeError"
    assert record.exception_message == "request cancelled"
    assert record.recoverable is True
    assert get_problem_store().all() == [record]


def test_problem_rejects_non_json_safe_details() -> None:
    log = get_log("loushang.tests.module")

    with pytest.raises(TypeError, match="JSON-safe"):
        log.problem("bad_details", details={"path": Path("tmp/file.txt")})


def test_diagnostic_projection_converts_tuples_and_mapping_implementations() -> None:
    source = UserDict(
        {
            "items": (1, UserDict({"ok": True})),
            "nested": [UserDict({"name": "alpha"})],
        }
    )

    projected = project_diagnostic_mapping(source, name="details")

    assert projected == {
        "items": [1, {"ok": True}],
        "nested": [{"name": "alpha"}],
    }
    assert type(projected) is dict
    assert type(projected["items"]) is list
    assert projected is not source
    assert projected["nested"] is not source["nested"]


def test_diagnostic_projection_preserves_current_scalar_subclass_policy() -> None:
    class Count(IntEnum):
        ONE = 1

    class Label(StrEnum):
        ONE = "one"

    assert project_diagnostic_value(Count.ONE) is Count.ONE
    assert project_diagnostic_value(Label.ONE) is Label.ONE
    assert project_diagnostic_value("\ud800") == "\ud800"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (Path("tmp/file.txt"), "value must be JSON-safe: got PosixPath"),
        (float("nan"), "value must be JSON-safe: non-finite float"),
        (float("inf"), "value must be JSON-safe: non-finite float"),
    ],
)
def test_diagnostic_projection_rejects_unknown_and_non_finite_values(
    value: object,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        project_diagnostic_value(value)


def test_diagnostic_projection_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(
        TypeError,
        match="details must be JSON-safe: keys must be strings",
    ):
        project_diagnostic_mapping({1: "value"})  # type: ignore[arg-type]
