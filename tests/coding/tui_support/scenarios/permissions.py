from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.tui.playback_suite import PlaybackScenarioSpec
from tests.coding.tui_support.permission_behavior import (
    PermissionBehaviorEvidence,
    run_permission_behavior_matrix,
)


@dataclass(frozen=True, slots=True)
class PermissionBehaviorPlaybackArtifacts:
    events: Path
    summary: Path


@dataclass(frozen=True, slots=True)
class PermissionBehaviorPlaybackResult:
    """Gateway behavior and sanitized audit evidence for all permission modes."""

    evidence: PermissionBehaviorEvidence

    def write_artifacts(
        self,
        directory: str | Path,
        *,
        basename: str = "permission-behavior",
        include_frames: bool = False,
    ) -> PermissionBehaviorPlaybackArtifacts:
        del include_frames
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        events_path = output_dir / f"{basename}-events.jsonl"
        summary_path = output_dir / f"{basename}-summary.txt"
        rows = _event_rows(self.evidence)
        with events_path.open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False))
                stream.write("\n")
        summary_path.write_text(_summary(self.evidence), encoding="utf-8")
        return PermissionBehaviorPlaybackArtifacts(
            events=events_path,
            summary=summary_path,
        )


def _run_permission_behavior_playback() -> PermissionBehaviorPlaybackResult:
    with TemporaryDirectory(prefix="loushang-permission-playback-") as directory:
        evidence = asyncio.run(
            run_permission_behavior_matrix(Path(directory) / "workspace")
        )
    cases = {case.name: case for case in evidence.cases}
    assert cases["standard-write"].outcome == "allowed"
    assert cases["standard-delete"].outcome == "asked"
    assert cases["cautious-write"].outcome == "asked"
    assert cases["full-access-delete"].outcome == "allowed"
    assert cases["full-access-delete"].policy_code == "filesystem_deletion"
    assert cases["managed-deny"].outcome == "denied"
    assert cases["managed-profile-ceiling"].effective_profile == "standard"
    assert cases["child-delegated-ceiling"].outcome == "contained"
    assert cases["child-delegated-ceiling"].actor_id == "/root/reviewer@2"
    assert any(
        event["type"] == "tool_execution_failed"
        and event.get("phase") == "pre_execution"
        and event.get("outcome") == "denied"
        for event in evidence.audit_events
    )
    return PermissionBehaviorPlaybackResult(evidence)


def _event_rows(
    evidence: PermissionBehaviorEvidence,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for case in evidence.cases:
        rows.append(
            {
                "sequence": len(rows) + 1,
                "layer": "behavior",
                "event": "permission.case.completed",
                "data": asdict(case),
            }
        )
    for audit_event in evidence.audit_events:
        rows.append(
            {
                "sequence": len(rows) + 1,
                "layer": "gateway",
                "event": audit_event["type"],
                "data": audit_event,
            }
        )
    return tuple(rows)


def _summary(evidence: PermissionBehaviorEvidence) -> str:
    headings = (
        "Permission behavior acceptance",
        "",
        "case | requested | effective | outcome | policy | approvals | actor",
        "--- | --- | --- | --- | --- | --- | ---",
    )
    lines = tuple(
        " | ".join(
            (
                case.name,
                case.requested_profile,
                case.effective_profile,
                case.outcome,
                case.policy_code or "-",
                str(case.approval_count),
                case.actor_id,
            )
        )
        for case in evidence.cases
    )
    return "\n".join((*headings, *lines, ""))


PERMISSION_SCENARIOS = (
    PlaybackScenarioSpec(
        name="permission-behavior-matrix",
        description=(
            "Exercise Standard, Cautious, and Full Access through real Coding "
            "tools, managed ceilings, child containment, and Gateway audit."
        ),
        run=_run_permission_behavior_playback,
        tags=("permissions", "policy", "approval", "gateway"),
    ),
)


__all__ = [
    "PERMISSION_SCENARIOS",
    "PermissionBehaviorPlaybackArtifacts",
    "PermissionBehaviorPlaybackResult",
]
