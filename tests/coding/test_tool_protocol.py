from __future__ import annotations


def test_tool_details_protocol_projection_adds_pi_aliases_without_mutating_source() -> (
    None
):
    from loushang.harness.tools.workspace.protocol import (
        project_tool_details_for_protocol,
    )

    details = {
        "full_output_path": "/tmp/full.log",
        "first_changed_line": 12,
        "match_limit_reached": True,
        "match_limit": 100,
        "result_limit_reached": True,
        "result_limit": 200,
        "entry_limit_reached": True,
        "entry_limit": 300,
        "lines_truncated": True,
    }

    projected = project_tool_details_for_protocol(details)

    assert projected["fullOutputPath"] == "/tmp/full.log"
    assert projected["firstChangedLine"] == 12
    assert projected["matchLimitReached"] == 100
    assert projected["resultLimitReached"] == 200
    assert projected["entryLimitReached"] == 300
    assert projected["linesTruncated"] is True
    assert "fullOutputPath" not in details
    assert "firstChangedLine" not in details
    assert "matchLimitReached" not in details


def test_tool_details_protocol_projection_preserves_existing_pi_aliases() -> None:
    from loushang.harness.tools.workspace.protocol import (
        project_tool_details_for_protocol,
    )

    projected = project_tool_details_for_protocol(
        {
            "full_output_path": "/tmp/snake.log",
            "fullOutputPath": "/tmp/protocol.log",
            "match_limit_reached": True,
            "match_limit": 100,
            "matchLimitReached": 5,
        }
    )

    assert projected["fullOutputPath"] == "/tmp/protocol.log"
    assert projected["matchLimitReached"] == 5


def test_tool_artifact_paths_for_protocol_dedupes_projected_paths() -> None:
    from loushang.harness.tools.workspace.protocol import (
        tool_artifact_paths_for_protocol,
    )

    paths = tool_artifact_paths_for_protocol(
        {
            "full_output_path": "/tmp/full.log",
            "fullOutputPath": "/tmp/full.log",
            "stdout_artifact_path": "/tmp/stdout.log",
            "stderr_artifact_path": "/tmp/stderr.log",
        }
    )

    assert paths == ["/tmp/full.log", "/tmp/stdout.log", "/tmp/stderr.log"]
