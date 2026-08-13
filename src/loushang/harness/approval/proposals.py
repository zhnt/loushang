"""Grant and policy-amendment proposals for approved actions.

Implements grant proposals (§9.1) of
docs/internals/architecture/harness/policy-approval-redesign.md: generalizes
an approved tool action into a session-scoped approval grant or a
project/user policy amendment when the action is safely generalizable
(simple commands, conservative git push forms). Consumed by
`loushang.harness.tools.workspace.policy`; Products retain wording,
risk presentation, and amendment destinations.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from loushang.harness.approval.requests import (
    ApprovalGrantProposal,
    PolicyAmendmentProposal,
)
from loushang.harness.policy._powershell import parse_simple_powershell_command
from loushang.harness.policy.subjects import CommandPolicySubject, ToolPolicySubject

_SHELL_CONTROL = frozenset({";", "&&", "||", "|", "&", "(", ")"})
_GIT_GLOBAL_VALUE_OPTIONS = frozenset(
    {"-C", "-c", "--exec-path", "--git-dir", "--namespace", "--work-tree"}
)
_GIT_PUSH_VALUE_OPTIONS = frozenset(
    {
        "--exec",
        "--push-option",
        "--receive-pack",
        "--repo",
    }
)
_GIT_PUSH_IGNORED_SESSION_OPTIONS = frozenset(
    {
        "-q",
        "-u",
        "-v",
        "--atomic",
        "--ipv4",
        "--ipv6",
        "--porcelain",
        "--progress",
        "--quiet",
        "--set-upstream",
        "--verbose",
    }
)
_GIT_PUSH_DRY_RUN_OPTIONS = frozenset({"-n", "--dry-run"})
_GIT_PUSH_UNSAFE_SESSION_OPTIONS = frozenset(
    {
        "-d",
        "-f",
        "--all",
        "--delete",
        "--force",
        "--force-if-includes",
        "--force-with-lease",
        "--follow-tags",
        "--mirror",
        "--no-verify",
        "--prune",
        "--signed",
        "--tags",
    }
)


def propose_session_approval_grant(
    subject: ToolPolicySubject,
    *,
    policy_code: str | None,
) -> ApprovalGrantProposal | None:
    """Generalize only actions whose security-relevant scope is understood."""

    if policy_code != "external_publication":
        return None
    if subject.capability_id != "workspace.command" and not (
        subject.capability_id is None and subject.tool_name == "bash"
    ):
        return None
    command = subject.command
    if command is None or not command.normalization_complete:
        return None
    tokens = _simple_command_tokens(command)
    if not tokens:
        return None
    return _git_push_proposal(tokens, cwd=subject.cwd)


def propose_policy_amendments(
    subject: ToolPolicySubject,
    *,
    policy_code: str | None,
) -> tuple[PolicyAmendmentProposal, ...]:
    """Offer persistent rules only for understood, repository-bound effects."""

    grant = propose_session_approval_grant(subject, policy_code=policy_code)
    if grant is None:
        return ()
    return (PolicyAmendmentProposal(scope="project", grant=grant),)


def _simple_command_tokens(
    command: CommandPolicySubject,
) -> tuple[str, ...]:
    if command.shell_payload is None:
        return command.direct_tokens
    if command.dialect == "powershell":
        return parse_simple_powershell_command(command.shell_payload) or ()
    if command.dialect != "posix":
        return ()
    try:
        tokens = tuple(shlex.split(command.shell_payload, posix=True))
    except ValueError:
        return ()
    if any(token in _SHELL_CONTROL for token in tokens):
        return ()
    return tokens


def _git_push_proposal(
    tokens: tuple[str, ...],
    *,
    cwd: str | None,
) -> ApprovalGrantProposal | None:
    values = list(tokens)
    while values and os.path.basename(values[0]) in {"command", "exec", "nohup"}:
        values.pop(0)
    if not values or os.path.basename(values.pop(0)).casefold() not in {
        "git",
        "git.exe",
    }:
        return None

    repository = Path(cwd or ".").expanduser()
    while values:
        value = values.pop(0)
        option = value.partition("=")[0]
        if option in _GIT_GLOBAL_VALUE_OPTIONS:
            option_value = value.partition("=")[2]
            if not option_value:
                if not values:
                    return None
                option_value = values.pop(0)
            if option != "-C":
                return None
            candidate = Path(option_value).expanduser()
            repository = (
                candidate
                if candidate.is_absolute()
                else repository / candidate
            )
            continue
        if value.startswith("-"):
            if value in {
                "--bare",
                "--literal-pathspecs",
                "--no-optional-locks",
                "--no-pager",
            }:
                continue
            return None
        if value != "push":
            return None
        break
    else:
        return None

    operands: list[str] = []
    unsafe = False
    index = 0
    while index < len(values):
        value = values[index]
        option = value.partition("=")[0]
        if _unsafe_push_option(value):
            unsafe = True
        if option in _GIT_PUSH_DRY_RUN_OPTIONS:
            return None
        if option in _GIT_PUSH_VALUE_OPTIONS:
            return None
        if value == "--":
            operands.extend(values[index + 1 :])
            break
        if value.startswith("-"):
            if option not in _GIT_PUSH_IGNORED_SESSION_OPTIONS:
                return None
        else:
            operands.append(value)
        index += 1
    if unsafe or len(operands) < 2:
        return None

    remote, *refspecs = operands
    if not remote or not refspecs or any(not refspec for refspec in refspecs):
        return None
    if any(_unsafe_refspec(refspec) for refspec in refspecs):
        return None
    if "://" in remote and "@" in remote.partition("://")[2].partition("/")[0]:
        return None
    repository_ref = str(repository.resolve())
    return ApprovalGrantProposal(
        capability="git.publish_refs",
        constraints=(
            ("repository", repository_ref),
            ("remote", remote),
            ("force", "false"),
        ),
        summary=f"Publish non-force refs to {remote} from this repository",
    )


def _unsafe_push_option(value: str) -> bool:
    option = value.partition("=")[0]
    if option in _GIT_PUSH_UNSAFE_SESSION_OPTIONS:
        return True
    if value.startswith("-") and not value.startswith("--"):
        return "d" in value[1:] or "f" in value[1:]
    return False


def _unsafe_refspec(refspec: str) -> bool:
    if refspec.startswith("+"):
        return True
    source, separator, _destination = refspec.partition(":")
    return bool(separator) and not source


__all__ = [
    "propose_policy_amendments",
    "propose_session_approval_grant",
]
