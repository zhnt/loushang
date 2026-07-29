from __future__ import annotations

import os

from loushang.harness.policy import (
    build_tool_policy_subject,
    executable_search_path_from_env,
    normalize_command_subject,
)
from loushang.harness.policy_engine import PolicyEngine
from loushang.harness.workspace.exec import ExecRequest, materialize_exec_request


def _evaluate_action(
    engine: PolicyEngine, *, tool_name: str, exec_request: ExecRequest
):
    request = materialize_exec_request(exec_request)
    environment = request.effective_environment
    assert environment is not None
    return engine.evaluate(
        build_tool_policy_subject(
            tool_name=tool_name,
            arguments={"command": request.command, "cwd": request.cwd},
            cwd=request.cwd,
            command=normalize_command_subject(
                request.command,
                cwd=request.cwd,
                executable_search_path=executable_search_path_from_env(
                    environment,
                    default=os.defpath,
                ),
                environment_overrides=environment,
                environment_is_complete=True,
            ),
        )
    )


def _evaluate_tool_call(
    engine: PolicyEngine,
    *,
    tool_name: str,
    arguments: dict[str, object],
    cwd: str | None = None,
):
    return engine.evaluate(
        build_tool_policy_subject(
            tool_name=tool_name,
            arguments=arguments,
            cwd=cwd,
        )
    )


def test_policy_engine_is_product_neutral_and_namespaces_rules() -> None:
    engine = PolicyEngine(
        rule_id_prefix="design",
        blocked_substrings=("rm -rf",),
    )

    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=("/bin/sh", "-lc", "rm -rf /tmp/demo"), cwd="/tmp"
        ),
    )

    assert decision.disposition == "deny"
    assert engine._evaluator.rules[0].id == "design.command.block.0"


def test_policy_engine_accepts_product_specific_tool_and_path_values() -> None:
    engine = PolicyEngine(
        rule_id_prefix="ppt",
        blocked_tools=("write",),
        ask_path_substrings=("/secrets",),
    )

    tool_decision = _evaluate_tool_call(
        engine, tool_name="write", arguments={"path": "/tmp/file"}, cwd="/tmp"
    )
    path_decision = _evaluate_tool_call(
        engine, tool_name="read", arguments={"path": "/tmp/secrets/key"}, cwd="/tmp"
    )

    assert tool_decision.disposition == "deny"
    assert path_decision.disposition == "ask"
