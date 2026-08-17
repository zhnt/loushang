from __future__ import annotations

import asyncio
import json
from io import StringIO
from types import SimpleNamespace

from loushang.harness.cli import (
    CliOperationInsertion,
    CliOperationStage,
    CommandExecutionRequest,
    SessionListingOperationRequest,
    StandardCliOperationRequest,
    agent_session_listing_request,
    agent_standard_cli_operation_request,
    run_agent_cli_session_listing,
    run_command_operation,
    run_session_listing_operation,
    run_standard_cli_operations,
)


class _Runtime:
    def list_session_summaries(self) -> list[object]:
        return [
            "invalid",
            SimpleNamespace(
                session_id="session-1",
                cwd="/workspace",
                session_file=None,
                parent_session=None,
                leaf_id=None,
                metadata=SimpleNamespace(
                    created_at="2026-07-01T00:00:00Z",
                    updated_at="2026-07-02T00:00:00Z",
                    name="Example",
                ),
            ),
        ]


class _Session:
    async def execute_command_async(self, name: str, args: str) -> object:
        return SimpleNamespace(result={"name": name, "args": args})


def test_standard_agent_arguments_project_operation_requests() -> None:
    args = SimpleNamespace(
        list_sessions=True,
        list_sessions_format="json",
        session_cwd="/workspace",
        session_name_filter=None,
        session_parent=None,
        session_query="notes",
        session_has_diagnostics=None,
        session_limit=5,
        all_sessions=True,
        session_index=False,
        refresh_session_index=True,
        install_packages=("example",),
        materialize_packages=(),
        update_packages=(),
        remove_packages=(),
        uninstall_packages=(),
        check_package_updates=False,
        update_all_packages=False,
        package_scope="global",
        list_models="alpha",
        export=None,
        export_format="html",
        export_result_format="text",
        list_commands=False,
        list_commands_format="tsv",
        list_diagnostics=False,
        diagnostics_limit=20,
        list_diagnostics_format="tsv",
        list_skills=False,
        list_skills_format="tsv",
        list_plugins=False,
        list_plugins_format="tsv",
        command=None,
        command_args="",
        command_result_format="raw",
        list_models_format="json",
    )

    listing = agent_session_listing_request(args)
    operations = agent_standard_cli_operation_request(args)

    assert listing == SessionListingOperationRequest(
        output_format="json",
        cwd="/workspace",
        text="notes",
        limit=5,
        all_sessions=True,
        indexed=True,
        refresh_index=True,
    )
    assert operations.package_lifecycle is not None
    assert operations.package_lifecycle.install == ("example",)
    assert operations.model_listing is not None
    assert operations.model_listing.query == "alpha"


def test_session_listing_operation_owns_query_validation_and_projection(
    monkeypatch,
) -> None:
    from loushang.harness.cli import host_operations

    original = host_operations.try_project_session_record
    monkeypatch.setattr(
        host_operations,
        "try_project_session_record",
        lambda record: None if record == "invalid" else original(record),
    )
    stdout = StringIO()
    stderr = StringIO()

    result = run_session_listing_operation(
        _Runtime(),
        SessionListingOperationRequest(output_format="json"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert [item["session_id"] for item in json.loads(stdout.getvalue())] == [
        "session-1"
    ]
    assert stderr.getvalue() == ""


def test_agent_session_listing_runs_the_standard_projected_request(
    monkeypatch,
) -> None:
    from loushang.harness.cli import host_operations

    original = host_operations.try_project_session_record
    monkeypatch.setattr(
        host_operations,
        "try_project_session_record",
        lambda record: None if record == "invalid" else original(record),
    )
    stdout = StringIO()
    stderr = StringIO()

    result = run_agent_cli_session_listing(
        SimpleNamespace(
            list_sessions=True,
            list_sessions_format="json",
            session_cwd=None,
            session_name_filter=None,
            session_parent=None,
            session_query=None,
            session_has_diagnostics=None,
            session_limit=None,
            all_sessions=False,
            session_index=False,
            refresh_session_index=False,
        ),
        _Runtime(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert [item["session_id"] for item in json.loads(stdout.getvalue())] == [
        "session-1"
    ]
    assert stderr.getvalue() == ""


def test_session_listing_operation_projects_invalid_limit_to_cli_error() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_session_listing_operation(
        _Runtime(),
        SessionListingOperationRequest(limit=-1),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Error: Session query limit must be non-negative\n"


def test_command_operation_writes_standard_result_envelope() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = asyncio.run(
        run_command_operation(
            _Session(),
            CommandExecutionRequest(
                command="/deploy",
                args="now",
                result_format="json",
            ),
            stdout=stdout,
            stderr=stderr,
        )
    )

    assert result == 0
    assert json.loads(stdout.getvalue()) == {
        "command": "deploy",
        "args": "now",
        "result": {"name": "deploy", "args": "now"},
    }
    assert stderr.getvalue() == ""


def test_standard_operation_pack_accepts_product_stage_insertions() -> None:
    calls: list[str] = []

    result = asyncio.run(
        run_standard_cli_operations(
            object(),
            None,
            StandardCliOperationRequest(),
            stdout=StringIO(),
            stderr=StringIO(),
            insertions=(
                CliOperationInsertion(
                    CliOperationStage(
                        "product_catalog",
                        lambda: calls.append("product_catalog") or 0,
                    ),
                    target_operation_id="list_skills",
                ),
            ),
        )
    )

    assert result == 0
    assert calls == ["product_catalog"]
