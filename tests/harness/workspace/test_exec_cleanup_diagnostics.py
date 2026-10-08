from __future__ import annotations

import inspect
from dataclasses import fields

import pytest

from loushang.agent.types import AgentToolResult
from loushang.harness.artifacts import SessionBlobRef
from loushang.harness.session.bash import command_result_from_tool_result
from loushang.harness.tools.workspace.bash import _exec_result_to_tool_result
from loushang.harness.tools.workspace.protocol import (
    normalize_bash_result_from_protocol,
    project_tool_details_for_protocol,
)
from loushang.harness.workspace.exec import ExecResult


def test_cleanup_diagnostic_is_keyword_only_and_absent_from_default_tool_details():
    parameter = inspect.signature(ExecResult).parameters["artifact_cleanup_error"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None
    assert fields(ExecResult)[-1].kw_only
    result = ExecResult(7, "out", "err")
    details = _exec_result_to_tool_result(result).details
    assert result.artifact_cleanup_error is None
    assert "artifact_cleanup_error" not in details
    assert "artifactCleanupError" not in project_tool_details_for_protocol(details)


@pytest.mark.parametrize("retention", [None, "publication outcome unknown"])
def test_cleanup_diagnostic_preserves_exit_refs_and_independent_retention_error(retention):
    reference = SessionBlobRef(
        session_id="session", blob_id="a" * 64, logical_name="command.log",
        kind="command-stdout", media_type="text/plain", disclosure="private",
        size_bytes=3, sha256="a" * 64, created_at=1.0,
    )
    result = ExecResult(7, "out", stdout_artifact_ref=reference,
                        artifact_retention_error=retention,
                        artifact_cleanup_error="temporary_cleanup_pending")
    tool = _exec_result_to_tool_result(result)
    projected = project_tool_details_for_protocol(tool.details)
    normalized = normalize_bash_result_from_protocol(projected)
    command = command_result_from_tool_result(tool)
    for value in (normalized, command):
        assert value["exit_code"] == 7
        assert value["stdout_blob"] == reference.manifest_entry()
        assert value["artifact_cleanup_error"] == "temporary_cleanup_pending"
        assert value.get("artifact_retention_error") == retention
    assert projected["artifactCleanupError"] == "temporary_cleanup_pending"


@pytest.mark.parametrize("value", ["/private/path", "secret-token", "", True, 1])
def test_cleanup_diagnostic_never_projects_raw_error_text(value):
    with pytest.raises(ValueError, match="invalid artifact cleanup diagnostic"):
        ExecResult(0, artifact_cleanup_error=value)
    for key in ("artifact_cleanup_error", "artifactCleanupError"):
        with pytest.raises(ValueError, match="invalid artifact cleanup diagnostic"):
            project_tool_details_for_protocol({key: value})
        with pytest.raises(ValueError, match="invalid artifact cleanup diagnostic"):
            normalize_bash_result_from_protocol({key: value})
        with pytest.raises(ValueError, match="invalid artifact cleanup diagnostic"):
            command_result_from_tool_result(AgentToolResult(content=[], details={key: value}))


@pytest.mark.parametrize("values", [(None, "temporary_cleanup_pending"), ("temporary_cleanup_pending", None),
                                    (None, "raw secret"), ("raw secret", None)])
def test_every_projection_rejects_conflicting_or_hidden_invalid_alias(values):
    details = dict(zip(("artifact_cleanup_error", "artifactCleanupError"), values, strict=True))
    for projection in (project_tool_details_for_protocol, normalize_bash_result_from_protocol):
        with pytest.raises(ValueError):
            projection(details)
    with pytest.raises(ValueError):
        command_result_from_tool_result(AgentToolResult(content=[], details=details))
