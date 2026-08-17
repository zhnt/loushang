from __future__ import annotations

import sys


def _bash_tool(
    *,
    policy_engine=None,
    approval_resolver=None,
    **definition_options,
):
    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    return wrap_tool_definition(
        create_bash_tool_definition(**definition_options),
        policy_evaluator=policy_engine,
        approval_resolver=approval_resolver,
    )


def _evaluate_action(engine, *, tool_name, exec_request):
    import os

    from loushang.harness.policy import (
        build_tool_policy_subject,
        executable_search_path_from_env,
        normalize_command_subject,
    )
    from loushang.harness.workspace.exec import materialize_exec_request

    request = materialize_exec_request(exec_request)
    environment = request.effective_environment
    assert environment is not None
    command = normalize_command_subject(
        request.command,
        cwd=request.cwd,
        stdin=request.stdin,
        executable_search_path=executable_search_path_from_env(
            environment,
            default=os.defpath,
        ),
        environment_overrides=environment,
        environment_is_complete=True,
    )
    arguments = {"command": request.command, "cwd": request.cwd}
    if request.env:
        arguments["env"] = request.env
    if request.stdin is not None:
        arguments["stdin"] = request.stdin
    return engine.evaluate(
        build_tool_policy_subject(
            tool_name=tool_name,
            arguments=arguments,
            cwd=request.cwd,
            command=command,
        )
    )


def _evaluate_tool_call(engine, *, tool_name, arguments, cwd=None):
    from loushang.harness.policy import build_tool_policy_subject
    from loushang.harness.workspace.exec import ExecRequest

    raw_command = arguments.get("command")
    if tool_name == "bash" and isinstance(raw_command, (str, list, tuple)):
        command = (
            ("/bin/sh", "-lc", raw_command)
            if isinstance(raw_command, str)
            else tuple(raw_command)
        )
        raw_env = arguments.get("env", ())
        env = (
            tuple(tuple(pair) for pair in raw_env)
            if isinstance(raw_env, (list, tuple))
            else ()
        )
        return _evaluate_action(
            engine,
            tool_name=tool_name,
            exec_request=ExecRequest(
                command=command,
                cwd=(
                    arguments["cwd"] if isinstance(arguments.get("cwd"), str) else cwd
                ),
                env=env,
                stdin=(
                    arguments["stdin"]
                    if isinstance(arguments.get("stdin"), str)
                    else None
                ),
            ),
        )
    return engine.evaluate(
        build_tool_policy_subject(
            tool_name=tool_name,
            arguments=arguments,
            cwd=cwd,
        )
    )


def test_policy_decision_helpers_cover_allow_deny_and_ask() -> None:
    from loushang.harness.policy import PolicyDecision

    assert PolicyDecision.allow() == PolicyDecision(disposition="allow", reason=None)
    assert PolicyDecision.deny("blocked") == PolicyDecision(
        disposition="deny", reason="blocked"
    )
    assert PolicyDecision.ask("needs approval") == PolicyDecision(
        disposition="ask", reason="needs approval"
    )


def test_policy_engine_denies_blocked_commands() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine(blocked_substrings=["rm -rf", "git reset --hard"])
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["/bin/sh", "-lc", "rm -rf /tmp/demo"], cwd="/tmp"
        ),
    )

    assert decision.disposition == "deny"
    assert "rm -rf" in decision.reason


def test_policy_engine_asks_before_destructive_commands_by_default() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["/bin/sh", "-lc", "git reset --hard HEAD~1"], cwd="/tmp"
        ),
    )

    assert decision.disposition == "ask"
    assert decision.code == "repository_history_rewrite"


def test_policy_engine_asks_before_absolute_path_destructive_executables() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(command=["/bin/rm", "-rf", "/tmp"], cwd="/tmp"),
    )

    assert decision.disposition == "ask"
    assert decision.code == "filesystem_deletion"


def test_policy_engine_allows_safe_readonly_command() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(command=["/bin/sh", "-lc", "pwd"], cwd="/tmp"),
    )

    assert decision.disposition == "allow"


def test_policy_engine_asks_for_risky_default_heuristics() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["/bin/sh", "-lc", "git push origin main"], cwd="/tmp"
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_asks_for_env_wrapped_shell_payload() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["/usr/bin/env", "bash", "-lc", "git push origin main"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_asks_for_env_wrapped_shell_payload_with_assignments() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["env", "FOO=1", "bash", "-lc", "git push origin main"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_asks_for_env_wrapped_shell_payload_with_option_flags() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["env", "-i", "bash", "-lc", "git push origin main"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_asks_for_env_wrapped_shell_payload_with_split_string_flag() -> (
    None
):
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["env", "-S", "bash -lc 'git push origin main'"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_asks_for_env_wrapped_shell_payload_with_unset_option() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["env", "-u", "DEBUG", "bash", "-lc", "git push origin main"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_allows_incomplete_env_split_without_a_gated_effect() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["env", "-S", "'"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "allow"
    assert decision.code is None


def test_policy_engine_asks_for_malformed_split_string_with_destructive_payload() -> (
    None
):
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["env", "-S", "bash -lc 'rm -rf /tmp"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"
    assert decision.code == "filesystem_deletion"


def test_policy_engine_asks_for_destructive_payloads_after_wrapper_options() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    commands = (
        ["sudo", "-nu", "root", "FOO=bar", "bash", "-c", "rm -rf /tmp"],
        ["sudo", "--use", "root", "bash", "-c", "rm -rf /tmp"],
        ["sudo", "--chd", "/tmp", "bash", "-c", "rm -rf /tmp"],
        ["sudo", "-s", "rm", "-rf", "/tmp"],
        ["sudo", "--login", "rm", "-rf", "/tmp"],
        ["env", "1FOO=bar", "bash", "-c", "rm -rf /tmp"],
        ["env", "=bar", "bash", "-c", "rm -rf /tmp"],
        ["env", "--", "FOO=bar", "bash", "-c", "rm -rf /tmp"],
        ["env", "--chd", "/tmp", "bash", "-c", "rm -rf /tmp"],
        ["env", "--uns", "FOO", "bash", "-c", "rm -rf /tmp"],
        ["env", "-iu", "FOO", "bash", "-c", "rm -rf /tmp"],
        ["env", "-iS", "bash -c 'rm -rf /tmp'"],
        ["env", "-S", "-i bash -c 'rm -rf /tmp'"],
        ["env", "-S", "FOO=bar bash -c 'rm -rf /tmp'"],
        ["env", "--default-signal", "bash", "-c", "rm -rf /tmp"],
        ["env", "--ignore-signal", "bash", "-c", "rm -rf /tmp"],
        ["env", "--block-signal", "bash", "-c", "rm -rf /tmp"],
        ["fish", "--command", "rm -rf /tmp"],
        ["fish", "--command=rm -rf /tmp"],
        ["fish", "-C", "printf setup", "-c", "rm -rf /tmp"],
        ["fish", "-c", "printf safe", "-c", "rm -rf /tmp"],
    )
    engine = PolicyEngine()

    for command in commands:
        decision = _evaluate_action(
            engine,
            tool_name="bash",
            exec_request=ExecRequest(command=command, cwd="/tmp"),
        )
        assert decision.disposition == "ask", command


def test_policy_engine_asks_for_literal_effect_in_nonportable_env_split_syntax() -> (
    None
):
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["env", "-S", r'bash\_-c\_"rm -rf /tmp"'],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"
    assert decision.code == "filesystem_deletion"


def test_policy_engine_allows_dynamic_env_split_without_a_gated_effect() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    decision = _evaluate_action(
        PolicyEngine(),
        tool_name="bash",
        exec_request=ExecRequest(
            command=["env", "-S", "${RUNNER} -c 'printf ok'"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "allow"
    assert decision.code is None


def test_policy_engine_compatibility_method_normalizes_list_commands() -> None:
    from loushang.harness.policy_engine import PolicyEngine

    engine = PolicyEngine()

    direct = _evaluate_tool_call(
        engine,
        tool_name="bash",
        arguments={"command": ["rm", "-rf", "/tmp"]},
    )
    shell = _evaluate_tool_call(
        engine,
        tool_name="bash",
        arguments={"command": ["bash", "-c", "rm -rf /tmp"]},
    )
    literal = _evaluate_tool_call(
        engine,
        tool_name="bash",
        arguments={"command": ["python", "-c", 'print("rm -rf")']},
    )

    assert direct.disposition == "ask"
    assert shell.disposition == "ask"
    assert literal.disposition == "allow"


def test_policy_engine_evaluates_shell_stdin_without_treating_data_as_script() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()

    destructive_script = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["bash", "-s"],
            stdin="rm -rf /tmp/policy-stdin\n",
        ),
    )
    command_data = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["bash", "-c", "cat"],
            stdin="rm -rf /tmp/policy-data\n",
        ),
    )

    assert destructive_script.disposition == "ask"
    assert destructive_script.code == "filesystem_deletion"
    assert command_data.disposition == "allow"


def test_policy_engine_compatibility_paths_use_last_execution_path(tmp_path) -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    (tmp_path / "cat").symlink_to("/bin/bash")
    engine = PolicyEngine()
    dangerous_env = (("PATH", "/usr/bin"), ("PATH", str(tmp_path)))
    # /usr/bin/cat does not exist on macOS (cat lives in /bin); include /bin so
    # the "safe" PATH resolves a real cat on every platform.
    safe_env = (("PATH", str(tmp_path)), ("PATH", "/usr/bin:/bin"))

    action = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=("cat", "+x"),
            cwd=str(tmp_path),
            env=dangerous_env,
            stdin="rm -rf /tmp/policy-stdin\n",
        ),
    )
    tool_call = _evaluate_tool_call(
        engine,
        tool_name="bash",
        arguments={
            "command": ["cat", "+x"],
            "cwd": str(tmp_path),
            "env": dangerous_env,
            "stdin": "rm -rf /tmp/policy-stdin\n",
        },
    )
    safe_action = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=("cat", "+x"),
            cwd=str(tmp_path),
            env=safe_env,
            stdin="rm -rf /tmp/policy-stdin\n",
        ),
    )

    assert action.disposition == "ask"
    assert tool_call.disposition == "ask"
    assert safe_action.disposition == "allow"


def test_policy_engine_asks_for_absolute_path_git_push() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["/usr/bin/git", "push", "origin", "main"], cwd="/tmp"
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_asks_for_sudo_wrapped_destructive_command() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["sudo", "/bin/rm", "-rf", "/tmp"], cwd="/tmp"
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_asks_for_sudo_wrapped_destructive_command_with_options() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["sudo", "-u", "root", "/bin/rm", "-rf", "/tmp"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_asks_for_sudo_wrapped_destructive_command_with_prompt_option() -> (
    None
):
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["sudo", "-p", "prompt", "/bin/rm", "-rf", "/tmp"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_asks_for_sudo_wrapped_destructive_command_with_chroot_option() -> (
    None
):
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["sudo", "-R", "/chroot", "/bin/rm", "-rf", "/tmp"],
            cwd="/tmp",
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_preserves_default_ask_rules_when_customized() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine(ask_substrings=["curl | sh"])
    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["/bin/sh", "-lc", "git push origin main"], cwd="/tmp"
        ),
    )

    assert decision.disposition == "ask"


def test_policy_engine_uses_shell_payload_with_trailing_args() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()

    destructive_decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=["/bin/sh", "-lc", "rm -rf /tmp/demo", "ignored", "still-ignored"],
            cwd="/tmp",
        ),
    )
    ask_decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=[
                "/bin/sh",
                "-lc",
                "git push origin main",
                "ignored",
                "still-ignored",
            ],
            cwd="/tmp",
        ),
    )

    assert destructive_decision.disposition == "ask"
    assert ask_decision.disposition == "ask"


def test_policy_engine_ignores_literal_substrings_in_direct_argv_commands() -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest

    engine = PolicyEngine()
    decision = _evaluate_action(
        engine,
        tool_name="python",
        exec_request=ExecRequest(
            command=["python", "-c", 'print("rm -rf")'], cwd="/tmp"
        ),
    )

    assert decision.disposition == "allow"


def test_policy_engine_rejects_bare_string_constructor_inputs() -> None:
    from loushang.harness.policy_engine import PolicyEngine

    try:
        PolicyEngine(blocked_substrings="rm -rf")  # type: ignore[arg-type]
    except TypeError as exc:
        assert "blocked_substrings" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected TypeError")


def test_policy_engine_evaluates_generic_tool_name_rules() -> None:
    from loushang.harness.policy_engine import PolicyEngine

    engine = PolicyEngine(blocked_tools=["write"], ask_tools=["edit"])

    deny_decision = _evaluate_tool_call(
        engine,
        tool_name="write",
        arguments={"path": "notes.txt", "content": "hello"},
        cwd="/tmp/project",
    )
    ask_decision = _evaluate_tool_call(
        engine,
        tool_name="edit",
        arguments={"path": "notes.txt", "edits": [{"oldText": "a", "newText": "b"}]},
        cwd="/tmp/project",
    )
    allow_decision = _evaluate_tool_call(
        engine,
        tool_name="read",
        arguments={"path": "notes.txt"},
        cwd="/tmp/project",
    )

    assert deny_decision.disposition == "deny"
    assert deny_decision.code == "tool_blocked"
    assert "write" in (deny_decision.reason or "")
    assert ask_decision.disposition == "ask"
    assert ask_decision.code == "tool_requires_approval"
    assert "edit" in (ask_decision.reason or "")
    assert allow_decision.disposition == "allow"


def test_policy_engine_reuses_bash_heuristics_for_tool_call_arguments() -> None:
    from loushang.harness.policy_engine import PolicyEngine

    engine = PolicyEngine()
    ask_decision = _evaluate_tool_call(
        engine,
        tool_name="bash",
        arguments={"command": "git push origin main"},
        cwd="/tmp/project",
    )
    destructive_decision = _evaluate_tool_call(
        engine,
        tool_name="bash",
        arguments={"command": "rm -rf /tmp/demo"},
        cwd="/tmp/project",
    )

    assert ask_decision.disposition == "ask"
    assert ask_decision.code == "external_publication"
    assert destructive_decision.disposition == "ask"
    assert destructive_decision.code == "filesystem_deletion"


def test_policy_engine_evaluates_resolved_path_substring_rules() -> None:
    from loushang.harness.policy_engine import PolicyEngine

    engine = PolicyEngine(blocked_path_substrings=["/tmp/project/secrets"])

    decision = _evaluate_tool_call(
        engine,
        tool_name="read",
        arguments={"path": "secrets/token.txt"},
        cwd="/tmp/project",
    )

    assert decision.disposition == "deny"
    assert decision.code == "path_blocked"
    assert "/tmp/project/secrets" in (decision.reason or "")


def test_bash_policy_evaluates_effective_command_after_prefix(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy_engine import PolicyEngine

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("blocked effective command must not execute")

    bash = _bash_tool(
        policy_engine=PolicyEngine(),
        exec_service=UnexpectedExecService(),
        command_prefix="rm -rf /tmp/policy-prefix",
    )

    with pytest.raises(PermissionError, match="Filesystem content"):
        asyncio.run(
            bash.execute(
                "call-effective-prefix",
                {"command": "pwd", "cwd": str(tmp_path)},
            )
        )


def test_bash_policy_evaluates_configured_shell_path(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy_engine import PolicyEngine

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("blocked configured shell command must not execute")

    bash = _bash_tool(
        policy_engine=PolicyEngine(),
        exec_service=UnexpectedExecService(),
        shell_path="/opt/product-shell",
    )

    with pytest.raises(PermissionError, match="Filesystem content"):
        asyncio.run(
            bash.execute(
                "call-configured-shell",
                {"command": "rm -rf /tmp/policy-shell", "cwd": str(tmp_path)},
            )
        )


def test_bash_policy_blocks_destructive_shell_stdin_before_execution(tmp_path) -> None:
    import asyncio
    from shutil import copyfile

    import pytest

    from loushang.harness.policy_engine import PolicyEngine

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("blocked stdin script must not execute")

    bash = _bash_tool(
        policy_engine=PolicyEngine(),
        exec_service=UnexpectedExecService(),
    )
    (tmp_path / "stdin-script").symlink_to("/dev/stdin")
    (tmp_path / "root").symlink_to("/")
    (tmp_path / "shell-alias").symlink_to("/bin/bash")
    (tmp_path / "fish").symlink_to("/bin/bash")
    (tmp_path / "env").symlink_to("/bin/bash")
    (tmp_path / "sudo").symlink_to("/bin/bash")
    (tmp_path / "runner").symlink_to("/usr/bin/env")
    copied_shell_dir = tmp_path / "copied-shell"
    copied_shell_dir.mkdir()
    # copyfile (not copy2) avoids copying platform file flags; on macOS copy2
    # triggers chflags PermissionError when reproducing /bin/bash attributes.
    copyfile("/bin/bash", copied_shell_dir / "bash")

    for index, (command, cwd) in enumerate(
        (
            (["bash", "-s"], str(tmp_path)),
            (["bash", "-"], str(tmp_path)),
            (["bash", "/dev/stdin"], str(tmp_path)),
            (["bash", "/dev/fd/0"], str(tmp_path)),
            (["bash", "/proc/self/fd/0"], str(tmp_path)),
            (["bash", "/proc/thread-self/fd/0"], str(tmp_path)),
            (["bash", "/proc/self/root/dev/stdin"], str(tmp_path)),
            (["bash", "/proc/thread-self/root/dev/stdin"], str(tmp_path)),
            (["bash", "../dev/stdin"], "/tmp"),
            (["bash", "../dev/fd/0"], "/tmp"),
            (["bash", "../proc/self/fd/0"], "/tmp"),
            (["bash", "../proc/thread-self/fd/0"], "/tmp"),
            (["bash", "--", "../dev/stdin"], "/tmp"),
            (["bash", "stdin-script"], str(tmp_path)),
            (
                [
                    "bash",
                    str(tmp_path / "root" / ".." / "dev" / "stdin"),
                ],
                str(tmp_path),
            ),
            (["bash", "+x"], str(tmp_path)),
            (["sh", "+eu"], str(tmp_path)),
            (["rbash"], str(tmp_path)),
            (["rzsh"], str(tmp_path)),
            (["rksh"], str(tmp_path)),
            ([str(tmp_path / "shell-alias")], str(tmp_path)),
            (["./shell-alias"], str(tmp_path)),
            ([str(tmp_path / "fish"), "+x"], str(tmp_path)),
            ([str(tmp_path / "env")], str(tmp_path)),
            (["./sudo"], str(tmp_path)),
            (
                [str(tmp_path / "runner"), "bash", "-c", "rm -rf /tmp/demo"],
                str(tmp_path),
            ),
            ([str(copied_shell_dir / "bash"), "+x"], str(tmp_path)),
            (["./copied-shell/bash", "+x"], str(tmp_path)),
            (["/bin/busybox", "sh"], str(tmp_path)),
            (
                ["/bin/busybox", "ash", "-c", "rm -rf /tmp/demo"],
                str(tmp_path),
            ),
        )
        + (
            # /proc/self/root/.. paths only exist on Linux; on macOS /proc does
            # not exist, so these resolve to a missing path and are not stdin.
            (
                (["bash", "/proc/self/root/../dev/stdin"], str(tmp_path)),
                (["bash", "/proc/thread-self/root/../dev/stdin"], str(tmp_path)),
                (["bash", "/proc/self/root/../../dev/stdin"], str(tmp_path)),
            )
            if sys.platform.startswith("linux")
            else ()
        )
    ):
        with pytest.raises(PermissionError):
            asyncio.run(
                bash.execute(
                    f"call-stdin-policy-{index}",
                    {
                        "command": command,
                        "stdin": "rm -rf /tmp/policy-stdin\n",
                        "cwd": cwd,
                    },
                )
            )

    path_commands = (
        ("shell-alias", str(tmp_path)),
        ("env", str(tmp_path)),
        ("bash", str(copied_shell_dir)),
    )
    for executable, search_path in path_commands:
        with pytest.raises(PermissionError):
            asyncio.run(
                bash.execute(
                    f"call-path-{executable}",
                    {
                        "command": [executable],
                        "stdin": "rm -rf /tmp/policy-stdin\n",
                        "cwd": str(tmp_path),
                        "env": [("PATH", search_path)],
                    },
                )
            )


def test_bash_policy_resolves_relative_path_from_execution_cwd(
    tmp_path,
    monkeypatch,
) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy_engine import PolicyEngine

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("blocked relative PATH shell must not execute")

    process_cwd = tmp_path / "process"
    execution_cwd = tmp_path / "execution"
    process_cwd.mkdir()
    execution_cwd.mkdir()
    (process_cwd / "cat").symlink_to("/bin/cat")
    (execution_cwd / "cat").symlink_to("/bin/bash")
    monkeypatch.chdir(process_cwd)
    bash = _bash_tool(
        policy_engine=PolicyEngine(),
        exec_service=UnexpectedExecService(),
    )

    with pytest.raises(PermissionError, match="Filesystem content"):
        asyncio.run(
            bash.execute(
                "call-relative-path-shell",
                {
                    "command": ["cat", "+x"],
                    "stdin": "rm -rf /tmp/policy-stdin\n",
                    "cwd": str(execution_cwd),
                    "env": [("PATH", ".")],
                },
            )
        )


def test_bash_policy_blocks_relative_stdin_symlink_without_explicit_cwd(
    tmp_path,
    monkeypatch,
) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy_engine import PolicyEngine

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("blocked stdin script must not execute")

    (tmp_path / "stdin-script").symlink_to("/dev/stdin")
    monkeypatch.chdir(tmp_path)
    bash = _bash_tool(
        policy_engine=PolicyEngine(),
        exec_service=UnexpectedExecService(),
    )

    with pytest.raises(PermissionError, match="Filesystem content"):
        asyncio.run(
            bash.execute(
                "call-relative-stdin-policy",
                {
                    "command": ["bash", "stdin-script"],
                    "stdin": "rm -rf /tmp/policy-stdin\n",
                },
            )
        )


def test_bash_policy_fails_safe_when_env_wrapper_changes_cwd(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy_engine import PolicyEngine

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("incomplete wrapper command must not execute")

    (tmp_path / "stdin-script").symlink_to("/dev/stdin")
    bash = _bash_tool(
        policy_engine=PolicyEngine(),
        exec_service=UnexpectedExecService(),
    )

    with pytest.raises(PermissionError, match="Filesystem content"):
        asyncio.run(
            bash.execute(
                "call-env-chdir-stdin-policy",
                {
                    "command": [
                        "env",
                        "-C",
                        str(tmp_path),
                        "bash",
                        "stdin-script",
                    ],
                    "stdin": "rm -rf /tmp/policy-stdin\n",
                    "cwd": "/",
                },
            )
        )


def test_bash_policy_fails_safe_when_env_wrapper_changes_executable_path(
    tmp_path,
) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy_engine import PolicyEngine

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("incomplete PATH wrapper command must not execute")

    (tmp_path / "cat").symlink_to("/bin/bash")
    bash = _bash_tool(
        policy_engine=PolicyEngine(),
        exec_service=UnexpectedExecService(),
    )

    commands = (
        ["env", f"PATH={tmp_path}", "cat", "+x"],
        ["env", "--argv0=sh", "/bin/busybox"],
    )
    for index, command in enumerate(commands):
        with pytest.raises(PermissionError, match="Filesystem content"):
            asyncio.run(
                bash.execute(
                    f"call-env-mutation-stdin-policy-{index}",
                    {
                        "command": command,
                        "stdin": "rm -rf /tmp/policy-stdin\n",
                    },
                )
            )


def test_bash_policy_blocks_shell_startup_stdin_before_execution(tmp_path) -> None:
    import asyncio

    import pytest

    from loushang.harness.policy_engine import PolicyEngine

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("shell startup stdin must not execute")

    bash = _bash_tool(
        policy_engine=PolicyEngine(),
        exec_service=UnexpectedExecService(),
    )
    cases = (
        {
            "command": [
                "bash",
                "--rcfile",
                "/dev/stdin",
                "-i",
                "-c",
                "printf safe",
            ],
            "stdin": "rm -rf /tmp/policy-startup\n",
        },
        {
            "command": ["env", "BASH_ENV=/dev/stdin", "bash", "-c", "printf safe"],
            "stdin": "rm -rf /tmp/policy-startup\n",
        },
        {
            "command": ["bash", "-c", "printf safe"],
            "env": [("BASH_ENV", "/dev/stdin")],
            "stdin": "rm -rf /tmp/policy-startup\n",
        },
    )

    for index, arguments in enumerate(cases):
        with pytest.raises(PermissionError):
            asyncio.run(
                bash.execute(
                    f"call-shell-startup-policy-{index}",
                    arguments,
                )
            )


def test_bash_policy_keeps_direct_argv_out_of_shell_payload_matching(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecResult

    requests = []

    class CapturingExecService:
        async def execute(self, request, **kwargs):
            del kwargs
            requests.append(request)
            return ExecResult(exit_code=0, stdout="ok", stderr="")

    bash = _bash_tool(
        policy_engine=PolicyEngine(),
        exec_service=CapturingExecService(),
    )

    asyncio.run(
        bash.execute(
            "call-direct-argv",
            {
                "command": ["python", "-c", 'print("rm -rf")'],
                "cwd": str(tmp_path),
            },
        )
    )

    assert requests[0].command == ("python", "-c", 'print("rm -rf")')


def test_bash_policy_wraps_getter_failure_and_invalid_decision(
    tmp_path,
) -> None:
    import asyncio
    from types import SimpleNamespace

    import pytest

    from loushang.harness.policy import PolicyEvaluationError

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("invalid policy must not execute")

    class ExplosivePolicy:
        @property
        def evaluate(self):
            raise RuntimeError("evaluate getter exploded")

    explosive = _bash_tool(
        policy_engine=ExplosivePolicy(),
        exec_service=UnexpectedExecService(),
    )
    with pytest.raises(PolicyEvaluationError, match="getter exploded"):
        asyncio.run(
            explosive.execute(
                "call-explosive-policy",
                {"command": "pwd", "cwd": str(tmp_path)},
            )
        )

    class InvalidPolicy:
        def evaluate(self, subject):
            del subject
            return SimpleNamespace(
                disposition="allow",
                reason=123,
                code=object(),
            )

    invalid = _bash_tool(
        policy_engine=InvalidPolicy(),
        exec_service=UnexpectedExecService(),
    )
    with pytest.raises(PolicyEvaluationError, match="expected PolicyDecision"):
        asyncio.run(
            invalid.execute(
                "call-invalid-policy",
                {"command": "pwd", "cwd": str(tmp_path)},
            )
        )

    from loushang.harness.policy import PolicyDecision

    malformed_decision = PolicyDecision.allow()
    object.__setattr__(malformed_decision, "disposition", "prompt")

    class MalformedPolicy:
        def evaluate(self, subject):
            del subject
            return malformed_decision

    malformed = _bash_tool(
        policy_engine=MalformedPolicy(),
        exec_service=UnexpectedExecService(),
    )
    with pytest.raises(PolicyEvaluationError, match="invalid PolicyDecision"):
        asyncio.run(
            malformed.execute(
                "call-malformed-policy-decision",
                {"command": "pwd", "cwd": str(tmp_path)},
            )
        )


def test_bash_approval_and_audit_use_effective_spawned_command(tmp_path) -> None:
    import asyncio

    from loushang.harness.approval import ApprovalDecision
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace import (
        BashSpawnContext,
        ToolContext,
        create_bash_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    approval_requests = []
    exec_requests = []
    events: list[dict[str, object]] = []
    effective_cwd = tmp_path / "effective"
    effective_cwd.mkdir()

    class CapturingApprovalResolver:
        def resolve(self, request):
            approval_requests.append(request)
            return ApprovalDecision.allow()

    class CapturingExecService:
        async def execute(self, request, **kwargs):
            del kwargs
            exec_requests.append(request)
            return ExecResult(exit_code=0, stdout="ok", stderr="")

    def rewrite_spawn(context: BashSpawnContext) -> BashSpawnContext:
        return BashSpawnContext(
            command=f"{context.command}\ngit push origin review",
            cwd=str(effective_cwd),
            env=(("LD_PRELOAD", "/tmp/injected.so"),),
        )

    async def emit_event(event: dict[str, object]) -> None:
        events.append(event)

    def provide_context(*, tool_call_id: str) -> ToolContext:
        return ToolContext(
            tool_call_id=tool_call_id,
            cwd=str(tmp_path),
            event_sink=emit_event,
        )

    bash = wrap_tool_definition(
        create_bash_tool_definition(
            exec_service=CapturingExecService(),
            command_prefix="echo prefixed",
            spawn_hook=rewrite_spawn,
        ),
        context_provider=provide_context,
        policy_evaluator=PolicyEngine(),
        approval_resolver=CapturingApprovalResolver(),
    )

    asyncio.run(
        bash.execute(
            "call-effective-approval",
            {
                "command": "pwd",
                "timeout": 3,
                "env": (("SAFE", "1"),),
            },
        )
    )

    effective_command = "echo prefixed\npwd\ngit push origin review"
    assert exec_requests[0].command[2] == effective_command
    assert exec_requests[0].cwd == str(effective_cwd)
    assert approval_requests[0].arguments["command"] == effective_command
    assert approval_requests[0].arguments["cwd"] == str(effective_cwd)
    assert approval_requests[0].arguments["env"] == (
        ("LD_PRELOAD", "/tmp/injected.so"),
    )
    assert approval_requests[0].arguments["timeout"] == 3
    assert [event["type"] for event in events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_requested",
        "tool_approval_resolved",
        "tool_execution_started",
        "tool_execution_completed",
    ]
    assert all("command" not in event for event in events)
    assert all("cwd" not in event for event in events)
    assert all(effective_command not in repr(event) for event in events)
    assert all(str(effective_cwd) not in repr(event) for event in events)
    assert all("/tmp/injected.so" not in repr(event) for event in events)
    assert all(event["capability"] == "git.remote_write" for event in events)


def test_bash_approval_and_audit_preserve_direct_wrapper_argv(tmp_path) -> None:
    import asyncio

    from loushang.harness.approval import ApprovalDecision
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace import (
        ToolContext,
        create_bash_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    approval_requests = []
    exec_requests = []
    events: list[dict[str, object]] = []

    class CapturingApprovalResolver:
        def resolve(self, request):
            approval_requests.append(request)
            return ApprovalDecision.allow()

    class CapturingExecService:
        async def execute(self, request, **kwargs):
            del kwargs
            exec_requests.append(request)
            return ExecResult(exit_code=0, stdout="ok", stderr="")

    async def emit_event(event: dict[str, object]) -> None:
        events.append(event)

    def provide_context(*, tool_call_id: str) -> ToolContext:
        return ToolContext(
            tool_call_id=tool_call_id,
            cwd=str(tmp_path),
            event_sink=emit_event,
        )

    bash = wrap_tool_definition(
        create_bash_tool_definition(
            exec_service=CapturingExecService(),
        ),
        context_provider=provide_context,
        policy_evaluator=PolicyEngine(),
        approval_resolver=CapturingApprovalResolver(),
    )
    command = (
        "env",
        "LD_PRELOAD=/tmp/injected.so",
        "bash",
        "-c",
        "git push origin review",
    )

    asyncio.run(
        bash.execute(
            "call-wrapper-approval",
            {"command": list(command), "cwd": str(tmp_path)},
        )
    )

    assert exec_requests[0].command == command
    assert approval_requests[0].arguments["command"] == command
    assert approval_requests[0].arguments["shell_payload"] == "git push origin review"
    assert all("command" not in event for event in events)
    assert all("LD_PRELOAD" not in repr(event) for event in events)
    assert all("/tmp/injected.so" not in repr(event) for event in events)
    assert all(event["capability"] == "git.remote_write" for event in events)


def test_bash_policy_and_execution_share_frozen_path_and_cwd(
    tmp_path, monkeypatch
) -> None:
    import asyncio

    from loushang.harness.policy import PolicyDecision

    original_cwd = tmp_path / "original"
    changed_cwd = tmp_path / "changed"
    original_cwd.mkdir()
    changed_cwd.mkdir()
    (original_cwd / "cat").symlink_to("/bin/cat")
    (changed_cwd / "cat").symlink_to("/bin/bash")
    marker = tmp_path / "policy-race"
    monkeypatch.chdir(original_cwd)
    monkeypatch.setenv("PATH", ".")

    class MutatingEvaluator:
        async def evaluate(self, subject):
            del subject
            monkeypatch.chdir(changed_cwd)
            monkeypatch.setenv("PATH", ".")
            await asyncio.sleep(0)
            return PolicyDecision.allow()

    bash = _bash_tool(policy_engine=MutatingEvaluator())
    asyncio.run(
        bash.execute(
            "call-frozen-execution",
            {
                "command": ["cat"],
                "stdin": f"printf raced > {marker}\n",
            },
        )
    )

    assert not marker.exists()


def test_bash_without_policy_freezes_path_and_cwd_before_async_update(
    tmp_path, monkeypatch
) -> None:
    import asyncio


    original_cwd = tmp_path / "original"
    changed_cwd = tmp_path / "changed"
    original_cwd.mkdir()
    changed_cwd.mkdir()
    (original_cwd / "cat").symlink_to("/bin/cat")
    (changed_cwd / "cat").symlink_to("/bin/bash")
    marker = tmp_path / "update-race"
    monkeypatch.chdir(original_cwd)
    monkeypatch.setenv("PATH", ".")

    async def mutate_process_state(update) -> None:
        del update
        monkeypatch.chdir(changed_cwd)
        monkeypatch.setenv("PATH", ".")
        await asyncio.sleep(0)

    bash = _bash_tool()
    asyncio.run(
        bash.execute(
            "call-frozen-no-policy",
            {
                "command": ["cat"],
                "stdin": f"printf raced > {marker}\n",
            },
            on_update=mutate_process_state,
        )
    )

    assert not marker.exists()


def test_bash_approval_wait_cannot_change_startup_environment_or_leak_secrets(
    tmp_path, monkeypatch
) -> None:
    import asyncio

    from loushang.harness.approval import ApprovalDecision
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import (
        ToolContext,
        create_bash_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    marker = tmp_path / "approval-race"
    inherited_secret = "must-not-appear-in-control-plane-projections"
    approval_requests = []
    events: list[dict[str, object]] = []
    monkeypatch.delenv("BASH_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("LOUSHANG_INHERITED_SECRET", inherited_secret)

    class AskingEvaluator:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.ask("review execution")

    class MutatingApprovalResolver:
        async def resolve(self, request):
            approval_requests.append(request)
            monkeypatch.setenv("BASH_ENV", "/dev/stdin")
            await asyncio.sleep(0)
            return ApprovalDecision.allow()

    async def emit_event(event: dict[str, object]) -> None:
        events.append(event)

    def provide_context(*, tool_call_id: str) -> ToolContext:
        return ToolContext(tool_call_id=tool_call_id, event_sink=emit_event)

    bash = wrap_tool_definition(
        create_bash_tool_definition(),
        context_provider=provide_context,
        policy_evaluator=AskingEvaluator(),
        approval_resolver=MutatingApprovalResolver(),
    )
    asyncio.run(
        bash.execute(
            "call-frozen-approval",
            {
                "command": ["/bin/bash", "-c", "printf safe"],
                "stdin": f"printf raced > {marker}\n",
            },
        )
    )

    assert not marker.exists()
    assert "env" not in approval_requests[0].arguments
    assert inherited_secret not in repr(approval_requests)
    assert inherited_secret not in repr(events)


def test_policy_engine_evaluate_action_uses_materialized_environment(
    tmp_path, monkeypatch
) -> None:
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.workspace.exec import ExecRequest, materialize_exec_request

    original_cwd = tmp_path / "original"
    changed_cwd = tmp_path / "changed"
    original_cwd.mkdir()
    changed_cwd.mkdir()
    (original_cwd / "cat").symlink_to("/bin/cat")
    (changed_cwd / "cat").symlink_to("/bin/bash")
    monkeypatch.chdir(original_cwd)
    monkeypatch.setenv("PATH", ".")
    request = materialize_exec_request(
        ExecRequest(
            command=["cat"],
            stdin="rm -rf /tmp/materialized-policy-sentinel\n",
        )
    )

    monkeypatch.chdir(changed_cwd)
    decision = _evaluate_action(
        PolicyEngine(),
        tool_name="bash",
        exec_request=request,
    )

    assert decision.disposition == "allow"
