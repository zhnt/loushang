from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.approval.proposals import (
    propose_policy_amendments,
    propose_session_approval_grant,
)
from loushang.harness.policy import (
    build_tool_policy_subject,
    normalize_command_subject,
    shell_command_policy_subject,
)


def test_git_push_session_grant_ignores_cosmetic_flags_but_keeps_security_scope(
    tmp_path: Path,
) -> None:
    baseline = _proposal("git push origin main", cwd=tmp_path)
    decorated = _proposal(
        "git push --porcelain --progress origin main",
        cwd=tmp_path,
    )

    assert baseline is not None
    assert decorated == baseline
    assert replace(baseline, summary="Localized presentation copy") == baseline
    assert baseline.capability == "git.publish_refs"
    assert dict(baseline.constraints) == {
        "force": "false",
        "remote": "origin",
        "repository": str(tmp_path.resolve()),
    }


@pytest.mark.parametrize(
    "command",
    (
        "git push --force origin main",
        "git push -uf origin main",
        "git push --force-with-lease origin main",
        "git push --force-if-includes origin main",
        "git push --delete origin old",
        "git push origin :old",
        "git push origin +main:main",
        "git push --follow-tags origin main",
        "git push --tags origin main",
        "git push --dry-run origin main",
        "git push origin",
        "git push",
        "git push https://token@example.com/acme/repo main",
        "git -c remote.origin.url=https://example.com/acme/repo push origin main",
        "git push origin main && echo done",
    ),
)
def test_git_push_session_grant_is_not_offered_for_unbounded_or_unsafe_forms(
    command: str,
    tmp_path: Path,
) -> None:
    assert _proposal(command, cwd=tmp_path) is None


def test_git_push_session_grant_reuses_non_force_refs_for_same_remote(
    tmp_path: Path,
) -> None:
    main = _proposal("git push origin main", cwd=tmp_path)
    release = _proposal("git push origin release", cwd=tmp_path)
    upstream = _proposal("git push upstream main", cwd=tmp_path)
    other_repo = _proposal("git -C other push origin main", cwd=tmp_path)

    assert main is not None
    assert release is not None
    assert upstream is not None
    assert other_repo is not None
    assert main == release
    assert len({main, upstream, other_repo}) == 3


def test_session_grant_requires_the_policy_effect_that_admitted_it(
    tmp_path: Path,
) -> None:
    subject = _subject("git push origin main", cwd=tmp_path)

    assert (
        propose_session_approval_grant(subject, policy_code="external_api_mutation")
        is None
    )


def test_policy_offers_project_amendment_only_for_safe_typed_publish_scope(
    tmp_path: Path,
) -> None:
    safe = _subject("git push origin main", cwd=tmp_path)
    destructive = _subject("rm -rf build", cwd=tmp_path)

    amendments = propose_policy_amendments(
        safe,
        policy_code="external_publication",
    )

    assert len(amendments) == 1
    assert amendments[0].scope == "project"
    assert amendments[0].grant.capability == "git.publish_refs"
    assert (
        propose_policy_amendments(
            destructive,
            policy_code="filesystem_deletion",
        )
        == ()
    )


def test_git_push_grant_uses_stable_workspace_command_capability_for_shell(
    tmp_path: Path,
) -> None:
    command = "git push origin main"
    subject = build_tool_policy_subject(
        tool_name="shell",
        capability_id="workspace.command",
        arguments={"command": command},
        cwd=str(tmp_path),
        command=shell_command_policy_subject(
            (
                r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                "-EncodedCommand",
                "transport-blob",
            ),
            script=command,
            dialect="powershell",
            shell_flavor="windows-powershell",
            cwd=str(tmp_path),
        ),
    )

    proposal = propose_session_approval_grant(
        subject,
        policy_code="external_publication",
    )

    assert proposal is not None
    assert proposal.capability == "git.publish_refs"
    assert dict(proposal.constraints) == {
        "force": "false",
        "remote": "origin",
        "repository": str(tmp_path.resolve()),
    }


def test_shell_name_without_workspace_command_capability_cannot_gain_git_grant(
    tmp_path: Path,
) -> None:
    legacy_shape = _subject("git push origin main", cwd=tmp_path)
    subject = replace(legacy_shape, tool_name="shell")

    assert (
        propose_session_approval_grant(
            subject,
            policy_code="external_publication",
        )
        is None
    )


def _proposal(command: str, *, cwd: Path):
    return propose_session_approval_grant(
        _subject(command, cwd=cwd),
        policy_code="external_publication",
    )


def _subject(command: str, *, cwd: Path):
    normalized = normalize_command_subject(
        ("/bin/sh", "-lc", command),
        cwd=str(cwd),
    )
    return build_tool_policy_subject(
        tool_name="bash",
        arguments={"command": command},
        cwd=str(cwd),
        command=normalized,
    )
