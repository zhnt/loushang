from __future__ import annotations

import asyncio
import os

import pytest


def test_policy_decision_rejects_invalid_disposition() -> None:
    from loushang.harness.policy import PolicyDecision

    with pytest.raises(ValueError, match="Unsupported policy disposition"):
        PolicyDecision(disposition="ignore")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="reason"):
        PolicyDecision(disposition="deny", reason=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="code"):
        PolicyDecision(disposition="deny", code=object())  # type: ignore[arg-type]


def test_tool_policy_subject_takes_an_immutable_nested_snapshot() -> None:
    from loushang.harness.policy import build_tool_policy_subject

    edits = [{"oldText": "before", "newText": "after"}]
    arguments = {"path": "notes.txt", "edits": edits}

    subject = build_tool_policy_subject(
        tool_name="edit",
        arguments=arguments,
        cwd="/tmp/project",
    )
    arguments["path"] = "changed.txt"
    edits[0]["newText"] = "changed"

    assert subject.arguments["path"] == "notes.txt"
    assert subject.arguments["edits"][0]["newText"] == "after"  # type: ignore[index]
    with pytest.raises(TypeError):
        subject.arguments["path"] = "forbidden"  # type: ignore[index]


def test_tool_policy_subject_rejects_non_json_argument_trees() -> None:
    from loushang.harness.policy import build_tool_policy_subject

    with pytest.raises(TypeError, match="mapping keys must be strings"):
        build_tool_policy_subject(
            tool_name="write",
            arguments={"nested": {1: "numeric", "1": "string"}},
        )
    with pytest.raises(TypeError, match="JSON-compatible"):
        build_tool_policy_subject(
            tool_name="write",
            arguments={"payload": bytearray(b"mutable")},
        )


@pytest.mark.parametrize(
    ("command", "payload", "tokens"),
    [
        (("/bin/sh", "-lc", "git push origin main"), "git push origin main", ()),
        (
            ("/usr/bin/git", "push", "origin", "main"),
            None,
            ("git", "push", "origin", "main"),
        ),
        (("env", "FOO=1", "bash", "-lc", "git push"), "git push", ()),
        (("env", "1FOO=1", "bash", "-lc", "git push"), "git push", ()),
        (("env", "=1", "bash", "-lc", "git push"), "git push", ()),
        (("env", "--", "FOO=1", "bash", "-lc", "git push"), "git push", ()),
        (("env", "--chd", "/tmp", "bash", "-c", "git push"), "git push", ()),
        (("env", "--uns", "FOO", "bash", "-c", "git push"), "git push", ()),
        (("env", "-Sbash -c 'git push'"), "git push", ()),
        (("env", "-iu", "FOO", "bash", "-c", "git push"), "git push", ()),
        (("env", "-iC", "/tmp", "bash", "-c", "git push"), "git push", ()),
        (("env", "-iS", "bash -c 'git push'"), "git push", ()),
        (("env", "-iSbash -c 'git push'"), "git push", ()),
        (("env", "-S", "-i bash -c 'git push'"), "git push", ()),
        (("env", "-S", "FOO=bar bash -c 'git push'"), "git push", ()),
        (("env", "--default-signal", "bash", "-c", "git push"), "git push", ()),
        (("env", "--ignore-signal", "bash", "-c", "git push"), "git push", ()),
        (("env", "--block-signal", "bash", "-c", "git push"), "git push", ()),
        (("sudo", "-u", "root", "/bin/rm", "-rf", "/tmp"), None, ("rm", "-rf", "/tmp")),
        (("sudo", "-nu", "root", "bash", "-c", "rm -rf /tmp"), "rm -rf /tmp", ()),
        (("sudo", "--use", "root", "bash", "-c", "rm -rf /tmp"), "rm -rf /tmp", ()),
        (("sudo", "--chd", "/tmp", "bash", "-c", "rm -rf /tmp"), "rm -rf /tmp", ()),
        (("sudo", "FOO=bar", "bash", "-c", "rm -rf /tmp"), "rm -rf /tmp", ()),
        (
            ("sudo", "-nu", "root", "FOO=bar", "bash", "-c", "rm -rf /tmp"),
            "rm -rf /tmp",
            (),
        ),
        (("sudo", "-s", "rm", "-rf", "/tmp"), "rm -rf /tmp", ()),
        (("sudo", "--login", "rm", "-rf", "/tmp"), "rm -rf /tmp", ()),
        (("ash", "-c", "git push"), "git push", ()),
        (("fish", "-c", "git push"), "git push", ()),
        (("fish", "--command", "git push"), "git push", ()),
        (("fish", "--command=git push"), "git push", ()),
        (
            ("fish", "-C", "printf setup", "-c", "git push"),
            "printf setup\ngit push",
            (),
        ),
        (
            ("fish", "-c", "printf safe", "-c", "git push"),
            "printf safe\ngit push",
            (),
        ),
        (("sh", "-c", "--", "printf shell"), "printf shell", ()),
        (("bash", "--noprofile", "-c", "printf bash"), "printf bash", ()),
        (("bash", "-O", "extglob", "-c", "printf extglob"), "printf extglob", ()),
    ],
)
def test_command_normalization_exposes_shell_payload_or_direct_tokens(
    command: tuple[str, ...],
    payload: str | None,
    tokens: tuple[str, ...],
) -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(command, cwd="/tmp")

    assert subject.command == command
    assert subject.shell_payload == payload
    assert subject.direct_tokens == tokens


def test_command_normalization_preserves_malformed_env_split_string_as_payload() -> (
    None
):
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(("env", "-S", "'"))

    assert subject.shell_payload == "'"
    assert subject.normalization_complete is False


@pytest.mark.parametrize(
    "command",
    [
        ("env", "-S", "bash -c 'printf ok'"),
        ("env", "-S", r'bash\_-c\_"rm -rf /tmp"'),
        ("env", "-S", "${RUNNER} -c 'rm -rf /tmp'"),
        ("env", "--platform-specific", "bash", "-c", "printf ok"),
        ("sudo", "--platform-specific", "bash", "-c", "printf ok"),
        ("env", "-C", "/tmp", "bash", "stdin-script"),
        ("env", "--chdir=/tmp", "bash", "stdin-script"),
        ("sudo", "-D", "/tmp", "bash", "stdin-script"),
        ("sudo", "--chroot=/tmp", "bash", "stdin-script"),
        ("sudo", "-s", "printf", "ok"),
        ("env", "PATH=/tmp", "cat", "+x"),
        ("env", "--", "PATH=/tmp", "cat", "+x"),
        ("env", "-u", "PATH", "cat", "+x"),
        ("env", "-uPATH", "cat", "+x"),
        ("env", "--unset=PATH", "cat", "+x"),
        ("env", "-i", "cat", "+x"),
        ("env", "--ignore-environment", "cat", "+x"),
        ("env", "-", "cat", "+x"),
        ("env", "-a", "sh", "busybox"),
        ("env", "-ash", "busybox"),
        ("env", "--argv0", "sh", "busybox"),
        ("env", "--argv0=sh", "busybox"),
        ("env", "BASH_ENV=/dev/stdin", "bash", "-c", "printf safe"),
        ("env", "ENV=/dev/stdin", "sh", "-c", "printf safe"),
        ("env", "-u", "BASH_ENV", "bash", "-c", "printf safe"),
        ("env", "--unset=ENV", "sh", "-c", "printf safe"),
        ("sudo", "PATH=/tmp", "cat", "+x"),
    ],
)
def test_command_normalization_marks_platform_specific_wrappers_incomplete(
    command: tuple[str, ...],
) -> None:
    from loushang.harness.policy import (
        IncompleteCommandMatcher,
        normalize_command_subject,
    )

    subject = normalize_command_subject(command)

    assert subject.normalization_complete is False
    assert IncompleteCommandMatcher().matches(subject)


def test_command_normalization_can_trust_an_injected_shell_entrypoint() -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(
        ("/opt/product-shell", "-lc", "rm -rf /tmp"),
        assume_shell=True,
    )

    assert subject.shell_payload == "rm -rf /tmp"
    assert subject.normalization_complete is True


@pytest.mark.parametrize(
    "command",
    [
        ("bash",),
        ("bash", "-s"),
        ("bash", "-s", "argument"),
        ("bash", "-"),
        ("bash", "/dev/stdin"),
        ("bash", "/dev/fd/0"),
        ("bash", "/proc/self/fd/0"),
        ("rbash",),
        ("rzsh",),
        ("rksh",),
        ("env", "SAFE=1", "sh"),
        ("fish",),
        ("fish", "-"),
        ("fish", "-C", "printf setup"),
    ],
)
def test_command_normalization_exposes_shell_stdin_payload(
    command: tuple[str, ...],
) -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(command, stdin="rm -rf /tmp/demo")

    assert subject.shell_payload is not None
    assert "rm -rf /tmp/demo" in subject.shell_payload
    assert subject.direct_tokens == ()


@pytest.mark.parametrize(
    ("command", "cwd"),
    [
        (("bash", "stdin"), "/dev"),
        (("bash", "fd/0"), "/dev"),
        (("bash", "dev/./stdin"), "/"),
        (("bash", "../dev/stdin"), "/tmp"),
        (("bash", "//dev/stdin"), "/tmp"),
        (("bash", "--", "../dev/fd/0"), "/tmp"),
        (("bash", "../proc/thread-self/fd/0"), "/tmp"),
        (("bash", "/proc/self/root/dev/stdin"), "/tmp"),
        (("bash", "/proc/thread-self/root/dev/stdin"), "/tmp"),
        (("bash", "/proc/self/root/../dev/stdin"), "/tmp"),
        (("bash", "/proc/thread-self/root/../dev/stdin"), "/tmp"),
        (("bash", "/proc/self/root/../../dev/stdin"), "/tmp"),
        (("fish", "stdin"), "/dev"),
        (("fish", "--", "../proc/self/fd/0"), "/tmp"),
    ],
)
def test_command_normalization_exposes_lexically_equivalent_stdin_paths(
    command: tuple[str, ...],
    cwd: str,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(
        command,
        cwd=cwd,
        stdin="rm -rf /tmp/demo",
    )

    assert subject.shell_payload == "rm -rf /tmp/demo"
    assert subject.direct_tokens == ()


def test_command_normalization_detects_symlink_to_stdin(
    tmp_path,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    (tmp_path / "stdin-script").symlink_to("/dev/stdin")

    subject = normalize_command_subject(
        ("bash", "stdin-script"),
        cwd=str(tmp_path),
        stdin="rm -rf /tmp/demo",
    )

    assert subject.shell_payload == "rm -rf /tmp/demo"
    assert subject.normalization_complete is True


def test_command_normalization_detects_relative_stdin_symlink_without_cwd(
    tmp_path,
    monkeypatch,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    (tmp_path / "stdin-script").symlink_to("/dev/stdin")
    monkeypatch.chdir(tmp_path)

    subject = normalize_command_subject(
        ("bash", "stdin-script"),
        stdin="rm -rf /tmp/demo",
    )

    assert subject.shell_payload == "rm -rf /tmp/demo"
    assert subject.normalization_complete is True


def test_command_normalization_preserves_symlink_component_before_parent(
    tmp_path,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    (tmp_path / "root").symlink_to("/")
    operand = str(tmp_path / "root" / ".." / "dev" / "stdin")

    subject = normalize_command_subject(
        ("bash", operand),
        stdin="rm -rf /tmp/demo",
    )

    assert subject.shell_payload == "rm -rf /tmp/demo"
    assert subject.normalization_complete is True


def test_command_normalization_uses_shell_executable_identity_for_aliases(
    tmp_path,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    shell_alias = tmp_path / "shell-alias"
    shell_alias.symlink_to("/bin/bash")
    commands = (
        ((str(shell_alias),), {}),
        (("./shell-alias",), {"cwd": str(tmp_path)}),
        (("shell-alias",), {"executable_search_path": str(tmp_path)}),
    )

    for command, options in commands:
        subject = normalize_command_subject(
            command,
            stdin="rm -rf /tmp/demo",
            **options,
        )

        assert subject.shell_payload == "rm -rf /tmp/demo"
        assert subject.normalization_complete is True


def test_command_normalization_uses_identity_over_deceptive_shell_basename(
    tmp_path,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    deceptive_fish = tmp_path / "fish"
    deceptive_fish.symlink_to("/bin/bash")

    subject = normalize_command_subject(
        (str(deceptive_fish), "+x"),
        stdin="rm -rf /tmp/demo",
    )

    assert subject.shell_payload == "rm -rf /tmp/demo"
    assert subject.normalization_complete is True


@pytest.mark.parametrize(
    "command",
    [
        ("bash", "--rcfile", "/dev/stdin", "-i", "-c", "printf safe"),
        (
            "bash",
            "-i",
            "--init-file=/proc/self/fd/0",
            "-c",
            "printf safe",
        ),
    ],
)
def test_command_normalization_exposes_shell_startup_file_stdin(
    command: tuple[str, ...],
) -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(
        command,
        stdin="rm -rf /tmp/startup",
    )

    assert subject.shell_payload == "rm -rf /tmp/startup\nprintf safe"
    assert subject.normalization_complete is False


def test_command_normalization_exposes_relative_startup_file_stdin_alias(
    tmp_path,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    (tmp_path / "bashrc").symlink_to("/dev/stdin")
    subject = normalize_command_subject(
        ("bash", "--rcfile", "bashrc", "-i", "-c", "printf safe"),
        cwd=str(tmp_path),
        stdin="rm -rf /tmp/startup",
    )

    assert subject.shell_payload == "rm -rf /tmp/startup\nprintf safe"
    assert subject.normalization_complete is False


def test_command_normalization_marks_shell_startup_environment_incomplete() -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(
        ("bash", "-c", "printf safe"),
        stdin="rm -rf /tmp/startup",
        environment_overrides=(("BASH_ENV", "/dev/stdin"),),
    )

    assert subject.shell_payload == "printf safe"
    assert subject.normalization_complete is False


@pytest.mark.parametrize("wrapper_name", ["env", "sudo"])
def test_command_normalization_does_not_unwrap_shells_with_wrapper_basenames(
    tmp_path,
    wrapper_name: str,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    deceptive_wrapper = tmp_path / wrapper_name
    deceptive_wrapper.symlink_to("/bin/bash")
    commands = (
        ((str(deceptive_wrapper),), {}),
        ((f"./{wrapper_name}",), {"cwd": str(tmp_path)}),
        ((wrapper_name,), {"executable_search_path": str(tmp_path)}),
    )

    for command, options in commands:
        subject = normalize_command_subject(
            command,
            stdin="rm -rf /tmp/demo",
            **options,
        )

        assert subject.shell_payload == "rm -rf /tmp/demo"
        assert subject.normalization_complete is True


def test_command_normalization_marks_wrapper_with_arbitrary_basename_incomplete(
    tmp_path,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    wrapper_alias = tmp_path / "runner"
    wrapper_alias.symlink_to("/usr/bin/env")

    subject = normalize_command_subject(
        (str(wrapper_alias), "bash", "-c", "rm -rf /tmp/demo"),
    )

    assert subject.shell_payload is None
    assert subject.normalization_complete is False


def test_command_normalization_fails_safe_for_independent_shell_copies(
    tmp_path,
) -> None:
    from shutil import copy2

    from loushang.harness.policy import normalize_command_subject

    copied_shell = tmp_path / "bash"
    copy2("/bin/bash", copied_shell)
    commands = (
        ((str(copied_shell), "+x"), {}),
        (("./bash", "+x"), {"cwd": str(tmp_path)}),
        (
            ("bash", "+x"),
            {"executable_search_path": str(tmp_path)},
        ),
    )

    for command, options in commands:
        subject = normalize_command_subject(
            command,
            stdin="rm -rf /tmp/demo",
            **options,
        )

        assert subject.shell_payload == "rm -rf /tmp/demo"
        assert subject.normalization_complete is False


@pytest.mark.parametrize(
    ("search_path", "relative_directory"),
    [
        (".", "."),
        ("bin", "bin"),
        (f"{os.pathsep}/definitely/missing", "."),
        (f"/definitely/missing{os.pathsep}", "."),
    ],
)
def test_command_normalization_resolves_relative_path_entries_from_execution_cwd(
    tmp_path,
    monkeypatch,
    search_path: str,
    relative_directory: str,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    process_cwd = tmp_path / "process"
    execution_cwd = tmp_path / "execution"
    process_bin = process_cwd / relative_directory
    execution_bin = execution_cwd / relative_directory
    process_bin.mkdir(parents=True)
    execution_bin.mkdir(parents=True)
    (process_bin / "cat").symlink_to("/bin/cat")
    (execution_bin / "cat").symlink_to("/bin/bash")
    monkeypatch.chdir(process_cwd)

    subject = normalize_command_subject(
        ("cat", "+x"),
        cwd=str(execution_cwd),
        stdin="rm -rf /tmp/demo",
        executable_search_path=search_path,
    )

    assert subject.shell_payload == "rm -rf /tmp/demo"
    assert subject.normalization_complete is True


def test_command_normalization_marks_unresolvable_stdin_entrypoint_incomplete(
    tmp_path,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(
        (str(tmp_path / "missing-shell"),),
        stdin="rm -rf /tmp/demo",
    )

    assert subject.shell_payload is None
    assert subject.normalization_complete is False


@pytest.mark.parametrize(
    ("command", "stdin", "expected_payload"),
    [
        (("/bin/busybox", "sh"), "rm -rf /tmp/demo", "rm -rf /tmp/demo"),
        (("busybox", "ash", "-c", "rm -rf /tmp/demo"), None, "rm -rf /tmp/demo"),
        (
            ("busybox", "env", "bash", "-c", "rm -rf /tmp/demo"),
            None,
            "rm -rf /tmp/demo",
        ),
        (("toybox", "sh", "-c", "rm -rf /tmp/demo"), None, "rm -rf /tmp/demo"),
    ],
)
def test_command_normalization_exposes_multicall_shell_applets(
    command: tuple[str, ...],
    stdin: str | None,
    expected_payload: str,
) -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(command, stdin=stdin)

    assert subject.shell_payload == expected_payload
    assert subject.direct_tokens == ()


def test_command_normalization_classifies_busybox_inode_by_invocation_name(
    tmp_path,
    monkeypatch,
) -> None:
    import loushang.harness.policy as policy_module
    from loushang.harness.policy import normalize_command_subject

    multicall = tmp_path / "busybox"
    multicall.write_text("test executable", encoding="utf-8")
    multicall.chmod(0o755)
    cat_applet = tmp_path / "cat"
    env_applet = tmp_path / "env"
    sh_applet = tmp_path / "sh"
    cat_applet.symlink_to(multicall)
    env_applet.symlink_to(multicall)
    sh_applet.symlink_to(multicall)
    monkeypatch.setattr(
        policy_module,
        "_known_multicall_paths",
        lambda: (str(multicall),),
    )

    cat_subject = normalize_command_subject(
        (str(cat_applet),),
        stdin="ordinary data",
    )
    env_subject = normalize_command_subject(
        (str(env_applet), str(sh_applet), "-c", "printf safe"),
    )

    assert cat_subject.shell_payload is None
    assert cat_subject.direct_tokens == ("cat",)
    assert cat_subject.normalization_complete is True
    assert env_subject.shell_payload == "printf safe"
    assert env_subject.normalization_complete is True


@pytest.mark.parametrize("command", [("bash", "+x"), ("sh", "+eu")])
def test_command_normalization_exposes_stdin_after_plus_options(
    command: tuple[str, ...],
) -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(
        command,
        stdin="rm -rf /tmp/demo",
    )

    assert subject.shell_payload == "rm -rf /tmp/demo"
    assert subject.normalization_complete is True


@pytest.mark.parametrize(
    "command",
    [
        ("bash", "-c", "cat"),
        ("bash", "/tmp/script.sh"),
        ("bash", "--", "-"),
        ("python", "-c", "print('ok')"),
    ],
)
def test_command_normalization_keeps_non_script_stdin_out_of_shell_payload(
    command: tuple[str, ...],
) -> None:
    from loushang.harness.policy import normalize_command_subject

    subject = normalize_command_subject(command, stdin="rm -rf /tmp/data")

    assert subject.shell_payload != "rm -rf /tmp/data"


def test_incomplete_command_matching_scans_raw_argv_conservatively() -> None:
    from loushang.harness.policy import (
        CommandSubstringMatcher,
        normalize_command_subject,
    )

    subject = normalize_command_subject(
        ("env", "-S", r'bash\_-c\_"rm -rf /tmp"'),
    )

    assert subject.normalization_complete is False
    assert CommandSubstringMatcher("rm -rf").matches(subject)


def test_rule_evaluator_returns_first_match_and_abstains_without_one() -> None:
    from loushang.harness.policy import (
        ExactToolNameMatcher,
        PolicyDecision,
        PolicyRule,
        RulePolicyEvaluator,
        build_tool_policy_subject,
    )

    evaluator = RulePolicyEvaluator(
        (
            PolicyRule(
                id="deny-write",
                matcher=ExactToolNameMatcher("write"),
                decision=PolicyDecision.deny("write disabled"),
            ),
            PolicyRule(
                id="ask-write",
                matcher=ExactToolNameMatcher("write"),
                decision=PolicyDecision.ask("confirm write"),
            ),
        )
    )

    write = build_tool_policy_subject(tool_name="write", arguments={})
    read = build_tool_policy_subject(tool_name="read", arguments={})

    assert evaluator.evaluate(write) == PolicyDecision.deny("write disabled")
    assert evaluator.evaluate(read) is None


def test_rule_evaluator_rejects_duplicate_rule_ids() -> None:
    from loushang.harness.policy import (
        ExactToolNameMatcher,
        PolicyDecision,
        PolicyRule,
        RulePolicyEvaluator,
    )

    rules = tuple(
        PolicyRule(
            id="same",
            matcher=ExactToolNameMatcher(name),
            decision=PolicyDecision.allow(),
        )
        for name in ("read", "write")
    )

    with pytest.raises(ValueError, match="ids must be unique"):
        RulePolicyEvaluator(rules)


def test_command_and_path_matchers_use_normalized_subjects(tmp_path) -> None:
    from loushang.harness.policy import (
        CommandSubstringMatcher,
        PathSubstringMatcher,
        build_tool_policy_subject,
        normalize_command_subject,
    )

    command = normalize_command_subject(("/usr/bin/git", "push", "origin", "main"))
    bash = build_tool_policy_subject(
        tool_name="bash",
        arguments={"command": "git push origin main"},
        command=command,
    )
    read = build_tool_policy_subject(
        tool_name="read",
        arguments={"path": "secrets/token.txt"},
        cwd=str(tmp_path),
    )

    assert CommandSubstringMatcher("git push").matches(bash)
    assert PathSubstringMatcher(str(tmp_path / "secrets")).matches(read)


def test_direct_command_matching_does_not_scan_unrelated_argument_text() -> None:
    from loushang.harness.policy import (
        CommandSubstringMatcher,
        normalize_command_subject,
    )

    subject = normalize_command_subject(("python", "-c", 'print("rm -rf")'))

    assert not CommandSubstringMatcher("rm -rf").matches(subject)


def test_policy_evaluator_chain_most_restrictive_runs_all_in_stable_order() -> None:
    from loushang.harness.policy import (
        CustomPolicySubject,
        PolicyDecision,
        PolicyEvaluatorChain,
        evaluate_policy,
    )

    calls: list[str] = []

    class Evaluator:
        def __init__(self, name: str, decision: PolicyDecision | None) -> None:
            self.name = name
            self.decision = decision

        async def evaluate(self, subject):
            del subject
            calls.append(self.name)
            return self.decision

    chain = PolicyEvaluatorChain(
        (
            Evaluator("allow", PolicyDecision.allow()),
            Evaluator("first-deny", PolicyDecision.deny("first", code="one")),
            Evaluator("second-deny", PolicyDecision.deny("second", code="two")),
        ),
        strategy="most_restrictive",
    )

    decision = asyncio.run(evaluate_policy(chain, CustomPolicySubject("demo")))

    assert calls == ["allow", "first-deny", "second-deny"]
    assert decision == PolicyDecision.deny("first", code="one")


def test_policy_evaluator_chain_strategies_preserve_abstention() -> None:
    from loushang.harness.policy import (
        CustomPolicySubject,
        PolicyDecision,
        PolicyEvaluatorChain,
        evaluate_policy,
    )

    class ConstantEvaluator:
        def __init__(self, decision: PolicyDecision | None) -> None:
            self.decision = decision

        def evaluate(self, subject):
            del subject
            return self.decision

    subject = CustomPolicySubject("demo")
    abstaining = PolicyEvaluatorChain(
        (ConstantEvaluator(None), ConstantEvaluator(None)),
        strategy="first_non_allow",
    )
    first = PolicyEvaluatorChain(
        (
            ConstantEvaluator(None),
            ConstantEvaluator(PolicyDecision.allow()),
            ConstantEvaluator(PolicyDecision.deny("later")),
        ),
        strategy="first_decision",
    )

    assert asyncio.run(evaluate_policy(abstaining, subject)) is None
    assert asyncio.run(evaluate_policy(first, subject)) == PolicyDecision.allow()


def test_policy_evaluator_wraps_evaluate_property_failures() -> None:
    from loushang.harness.policy import (
        CustomPolicySubject,
        PolicyEvaluationError,
        evaluate_policy,
    )

    class ExplosiveEvaluator:
        @property
        def evaluate(self):
            raise RuntimeError("shape exploded")

    with pytest.raises(PolicyEvaluationError, match="shape exploded"):
        asyncio.run(
            evaluate_policy(ExplosiveEvaluator(), CustomPolicySubject("test"))  # type: ignore[arg-type]
        )


def test_workspace_policy_wraps_protocol_and_decision_property_failures() -> None:
    from loushang.harness.policy import PolicyDecision, PolicyEvaluationError
    from loushang.harness.tools.workspace.policy import enforce_tool_policy

    class ExplosiveProtocol:
        @property
        def evaluate(self):
            raise RuntimeError("protocol exploded")

    with pytest.raises(PolicyEvaluationError, match="protocol exploded"):
        asyncio.run(
            enforce_tool_policy(
                ExplosiveProtocol(),
                tool_name="read",
                arguments={},
            )
        )

    class ExplosiveDecision:
        @property
        def disposition(self):
            raise RuntimeError("decision exploded")

    class InvalidEvaluator:
        def evaluate(self, subject):
            del subject
            return ExplosiveDecision()

    with pytest.raises(PolicyEvaluationError, match="expected PolicyDecision"):
        asyncio.run(
            enforce_tool_policy(
                InvalidEvaluator(),
                tool_name="read",
                arguments={},
            )
        )

    class ExplicitNewEvaluator:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    asyncio.run(
        enforce_tool_policy(
            ExplicitNewEvaluator(),
            tool_name="read",
            arguments={},
        )
    )


def test_evaluate_policy_wraps_failures_and_invalid_results() -> None:
    from loushang.harness.policy import (
        CustomPolicySubject,
        PolicyDecision,
        PolicyEvaluationError,
        evaluate_policy,
    )

    class FailingEvaluator:
        def evaluate(self, subject):
            del subject
            raise RuntimeError("broken")

    class InvalidEvaluator:
        def evaluate(self, subject):
            del subject
            return "allow"

    malformed = PolicyDecision.allow()
    object.__setattr__(malformed, "code", object())

    class MalformedDecisionEvaluator:
        def evaluate(self, subject):
            del subject
            return malformed

    with pytest.raises(PolicyEvaluationError, match="broken"):
        asyncio.run(evaluate_policy(FailingEvaluator(), CustomPolicySubject("demo")))
    with pytest.raises(PolicyEvaluationError, match="expected PolicyDecision or None"):
        asyncio.run(evaluate_policy(InvalidEvaluator(), CustomPolicySubject("demo")))
    with pytest.raises(PolicyEvaluationError, match="invalid PolicyDecision"):
        asyncio.run(
            evaluate_policy(
                MalformedDecisionEvaluator(),
                CustomPolicySubject("demo"),
            )
        )


def test_evaluate_policy_propagates_cancellation() -> None:
    from loushang.harness.policy import CustomPolicySubject, evaluate_policy

    class CancelledEvaluator:
        async def evaluate(self, subject):
            del subject
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(evaluate_policy(CancelledEvaluator(), CustomPolicySubject("demo")))


def test_workspace_policy_adapter_accepts_async_subject_evaluator() -> None:
    from loushang.harness.policy import PolicyDecision, ToolPolicySubject
    from loushang.harness.tools.workspace.policy import (
        PolicyEnforcementError,
        enforce_tool_policy,
    )

    seen: list[ToolPolicySubject] = []

    class DenyWrites:
        async def evaluate(self, subject):
            assert isinstance(subject, ToolPolicySubject)
            seen.append(subject)
            return PolicyDecision.deny("writes disabled", code="disabled")

    with pytest.raises(PolicyEnforcementError, match="writes disabled"):
        asyncio.run(
            enforce_tool_policy(
                DenyWrites(),
                tool_name="write",
                arguments={"path": "notes.txt", "content": "text"},
                cwd="/tmp/project",
            )
        )

    assert seen[0].tool_name == "write"
    assert seen[0].paths[0].resolved_path == "/tmp/project/notes.txt"


def test_workspace_policy_uses_one_snapshot_across_async_evaluation() -> None:
    from loushang.harness.approval import ApprovalDecision, ApprovalRequest
    from loushang.harness.policy import PolicyDecision, ToolPolicySubject
    from loushang.harness.tools.workspace.policy import (
        PolicyEnforcementError,
        enforce_tool_policy,
    )

    evaluation_started = asyncio.Event()
    release_evaluation = asyncio.Event()
    subjects: list[ToolPolicySubject] = []
    requests: list[ApprovalRequest] = []
    audit_events: list[dict[str, object]] = []

    class BlockingEvaluator:
        async def evaluate(self, subject: ToolPolicySubject) -> PolicyDecision:
            subjects.append(subject)
            evaluation_started.set()
            await release_evaluation.wait()
            return PolicyDecision.ask("review")

    class DenyingResolver:
        def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
            requests.append(request)
            return ApprovalDecision.deny("denied")

    arguments = {
        "path": "before.txt",
        "nested": {"value": "before"},
    }

    async def run() -> PolicyEnforcementError:
        enforced = asyncio.create_task(
            enforce_tool_policy(
                BlockingEvaluator(),
                tool_name="write",
                arguments=arguments,
                cwd="/tmp/project",
                approval_resolver=DenyingResolver(),
                audit_sink=audit_events.append,
            )
        )
        await evaluation_started.wait()
        arguments["path"] = "after.txt"
        arguments["nested"]["value"] = "after"  # type: ignore[index]
        release_evaluation.set()
        with pytest.raises(PolicyEnforcementError) as caught:
            await enforced
        return caught.value

    error = asyncio.run(run())

    assert subjects[0].arguments["path"] == "before.txt"
    assert subjects[0].arguments["nested"]["value"] == "before"  # type: ignore[index]
    assert requests[0].arguments["path"] == "before.txt"
    assert requests[0].arguments["nested"]["value"] == "before"  # type: ignore[index]
    assert error.tool_result_details["path"] == "before.txt"
    assert all("path" not in event for event in audit_events)
    assert all("before.txt" not in repr(event) for event in audit_events)


def test_workspace_policy_adapter_rejects_unknown_evaluator() -> None:
    from loushang.harness.policy import PolicyEvaluationError
    from loushang.harness.tools.workspace.policy import enforce_tool_policy

    with pytest.raises(PolicyEvaluationError, match="no callable evaluate method"):
        asyncio.run(
            enforce_tool_policy(
                object(),
                tool_name="read",
                arguments={"path": "notes.txt"},
            )
        )


def test_workspace_policy_rejects_subject_execution_mismatch() -> None:
    from loushang.harness.policy import (
        CommandPolicySubject,
        PolicyEvaluationError,
        ToolPolicySubject,
        build_tool_policy_subject,
    )
    from loushang.harness.tools.workspace.policy import enforce_tool_policy

    class UnexpectedEvaluator:
        def evaluate(self, subject):
            del subject
            raise AssertionError("mismatched subject must not be evaluated")

    benign = build_tool_policy_subject(
        tool_name="read",
        arguments={},
        cwd="/tmp/project",
    )
    with pytest.raises(PolicyEvaluationError, match="tool_name, arguments, paths"):
        asyncio.run(
            enforce_tool_policy(
                UnexpectedEvaluator(),
                tool_name="write",
                arguments={"path": "danger.txt", "content": "danger"},
                cwd="/tmp/project",
                policy_subject=benign,
            )
        )

    command_arguments = {"command": ["git", "push"]}
    forged = ToolPolicySubject(
        tool_name="bash",
        arguments=command_arguments,
        cwd="/tmp/project",
        command=CommandPolicySubject(
            command=("git", "push"),
            cwd="/tmp/project",
            direct_tokens=(),
        ),
    )
    with pytest.raises(PolicyEvaluationError, match="command"):
        asyncio.run(
            enforce_tool_policy(
                UnexpectedEvaluator(),
                tool_name="bash",
                arguments=command_arguments,
                cwd="/tmp/project",
                policy_subject=forged,
            )
        )


@pytest.mark.parametrize(
    ("actual_command", "forged_command"),
    [
        ("rm -rf /tmp/danger", "printf safe"),
        ("printf safe", "rm -rf /tmp/danger"),
    ],
)
def test_workspace_policy_binds_string_subject_payload_to_execution_argument(
    actual_command: str,
    forged_command: str,
) -> None:
    from loushang.harness.policy import (
        PolicyEvaluationError,
        build_tool_policy_subject,
        normalize_command_subject,
    )
    from loushang.harness.tools.workspace.policy import enforce_tool_policy

    class UnexpectedEvaluator:
        def evaluate(self, subject):
            del subject
            raise AssertionError("forged string subject must not be evaluated")

    arguments = {"command": actual_command}
    forged = build_tool_policy_subject(
        tool_name="bash",
        arguments=arguments,
        cwd="/tmp/project",
        command=normalize_command_subject(
            ("/bin/bash", "-lc", forged_command),
            cwd="/tmp/project",
            assume_shell=True,
        ),
    )

    with pytest.raises(PolicyEvaluationError, match="command"):
        asyncio.run(
            enforce_tool_policy(
                UnexpectedEvaluator(),
                tool_name="bash",
                arguments=arguments,
                cwd="/tmp/project",
                policy_subject=forged,
            )
        )


def test_workspace_policy_rejects_bash_argument_cwd_mismatch() -> None:
    from loushang.harness.policy import (
        PolicyEvaluationError,
        build_tool_policy_subject,
        normalize_command_subject,
    )
    from loushang.harness.tools.workspace.policy import enforce_tool_policy

    class UnexpectedEvaluator:
        def evaluate(self, subject):
            del subject
            raise AssertionError("cwd-mismatched subject must not be evaluated")

    arguments = {
        "command": ["bash", "stdin"],
        "cwd": "/dev",
        "stdin": "rm -rf /tmp/danger",
    }
    subject = build_tool_policy_subject(
        tool_name="bash",
        arguments=arguments,
        cwd="/tmp",
        command=normalize_command_subject(
            ("bash", "stdin"),
            cwd="/tmp",
            stdin="rm -rf /tmp/danger",
        ),
    )

    with pytest.raises(PolicyEvaluationError, match="cwd"):
        asyncio.run(
            enforce_tool_policy(
                UnexpectedEvaluator(),
                tool_name="bash",
                arguments=arguments,
                cwd="/tmp",
                policy_subject=subject,
            )
        )


def test_workspace_policy_does_not_fall_back_after_canonical_abstention() -> None:
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.policy import enforce_tool_policy

    class TransitionalEvaluator:
        def evaluate(self, subject):
            del subject
            return None

        def evaluate_tool_call(self, *, tool_name, arguments, cwd=None):
            del arguments, cwd
            return PolicyDecision.deny(f"legacy denied {tool_name}")

    asyncio.run(
        enforce_tool_policy(
            TransitionalEvaluator(),
            tool_name="write",
            arguments={"path": "notes.txt", "content": "text"},
        )
    )


def test_workspace_policy_revalidates_policy_decision_instances() -> None:
    from loushang.harness.policy import PolicyDecision, PolicyEvaluationError
    from loushang.harness.tools.workspace.policy import enforce_tool_policy

    malformed = PolicyDecision.allow()
    object.__setattr__(malformed, "disposition", "prompt")

    class MalformedEvaluator:
        def evaluate(self, subject):
            del subject
            return malformed

    with pytest.raises(PolicyEvaluationError, match="invalid PolicyDecision"):
        asyncio.run(
            enforce_tool_policy(
                MalformedEvaluator(),
                tool_name="write",
                arguments={"path": "notes.txt", "content": "text"},
            )
        )


def test_dual_protocol_policy_uses_explicit_new_decision_before_legacy() -> None:
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.policy import enforce_tool_policy

    class TransitionalEvaluator:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

        def evaluate_tool_call(self, *, tool_name, arguments, cwd=None):
            del tool_name, arguments, cwd
            raise AssertionError("explicit new decision must be authoritative")

    asyncio.run(
        enforce_tool_policy(
            TransitionalEvaluator(),
            tool_name="write",
            arguments={"path": "notes.txt", "content": "text"},
        )
    )


def test_new_only_workspace_policy_uses_product_default_after_abstention() -> None:
    from loushang.harness.tools.workspace.policy import enforce_tool_policy

    class AbstainingEvaluator:
        def evaluate(self, subject):
            del subject
            return None

    asyncio.run(
        enforce_tool_policy(
            AbstainingEvaluator(),
            tool_name="write",
            arguments={"path": "notes.txt", "content": "text"},
        )
    )
