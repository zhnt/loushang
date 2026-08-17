"""Deterministic resource candidate collision and precedence resolution."""

from __future__ import annotations

from collections.abc import Sequence

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_precedence import (
    _candidate_sort_key,
    _source_precedence_rank,
    _winner_sort_key,
)
from loushang.harness.resources._loader_types import (
    DescriptorT,
)
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    ResourceMergeDecision,
)


def _resolve_candidates(
    candidates: Sequence[DescriptorT],
    *,
    resource_type: str,
) -> tuple[list[DescriptorT], list[DiagnosticDraft], list[ResourceMergeDecision]]:
    grouped: dict[str, list[DescriptorT]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.id or candidate.name, []).append(candidate)

    active: list[DescriptorT] = []
    diagnostics: list[DiagnosticDraft] = []
    decisions: list[ResourceMergeDecision] = []
    for logical_id, group_members in grouped.items():
        group = sorted(group_members, key=_candidate_sort_key)
        enabled_candidates = [candidate for candidate in group if candidate.enabled]
        winner = (
            min(enabled_candidates, key=_winner_sort_key)
            if enabled_candidates
            else None
        )
        if winner is not None:
            active.append(winner)

        for candidate in group:
            if candidate.enabled:
                continue
            diagnostics.append(
                resource_diagnostic(
                    code="resource_disabled",
                    message=f"{resource_type} resource '{logical_id}' is disabled.",
                    source_path=candidate.source_path,
                    resource_id=candidate.id,
                    resource_type=resource_type,
                    source_kind=candidate.source_kind,
                )
            )

        if len(group) > 1:
            candidate_ids = tuple(candidate.id or candidate.name for candidate in group)
            candidate_source_kinds = tuple(candidate.source_kind for candidate in group)
            if winner is None:
                message = f"{resource_type} resource '{logical_id}' has no enabled candidates."
            else:
                message = (
                    f"{resource_type} resource '{logical_id}' selected {winner.source_kind} "
                    f"candidate '{winner.id}' over lower-priority or later-tiebreak candidates."
                )
            diagnostics.append(
                resource_diagnostic(
                    code="resource_collision",
                    message=message,
                    source_path=winner.source_path
                    if winner is not None
                    else group[0].source_path,
                    resource_id=logical_id,
                    resource_type=resource_type,
                    source_kind=winner.source_kind
                    if winner is not None
                    else group[0].source_kind,
                    metadata={
                        "winner_id": winner.id if winner is not None else None,
                        "candidate_ids": candidate_ids,
                        "candidate_source_kinds": candidate_source_kinds,
                        **_collision_path_metadata(winner=winner, candidates=group),
                    },
                )
            )
            decisions.append(
                ResourceMergeDecision(
                    resource_type=resource_type,
                    logical_id=logical_id,
                    winner_id=winner.id if winner is not None else None,
                    winner_source_kind=winner.source_kind
                    if winner is not None
                    else None,
                    candidate_ids=candidate_ids,
                    candidate_source_kinds=candidate_source_kinds,
                    reason="precedence_and_tiebreak",
                )
            )
        elif winner is not None:
            decisions.append(
                ResourceMergeDecision(
                    resource_type=resource_type,
                    logical_id=logical_id,
                    winner_id=winner.id,
                    winner_source_kind=winner.source_kind,
                    candidate_ids=(winner.id or winner.name,),
                    candidate_source_kinds=(winner.source_kind,),
                    reason="single_candidate",
                )
            )

    return active, diagnostics, decisions


def _resolve_strict_named_candidates(
    candidates: Sequence[DescriptorT],
    *,
    resource_type: str,
) -> tuple[list[DescriptorT], list[DiagnosticDraft], list[ResourceMergeDecision]]:
    grouped: dict[str, list[DescriptorT]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.id or candidate.name, []).append(candidate)

    active: list[DescriptorT] = []
    diagnostics: list[DiagnosticDraft] = []
    decisions: list[ResourceMergeDecision] = []
    for logical_id, group_members in grouped.items():
        group = sorted(group_members, key=_candidate_sort_key)
        enabled_candidates = [candidate for candidate in group if candidate.enabled]

        for candidate in group:
            if candidate.enabled:
                continue
            diagnostics.append(
                resource_diagnostic(
                    code="resource_disabled",
                    message=f"{resource_type} resource '{logical_id}' is disabled.",
                    source_path=candidate.source_path,
                    resource_id=candidate.id,
                    resource_type=resource_type,
                    source_kind=candidate.source_kind,
                )
            )

        if not enabled_candidates:
            if len(group) > 1:
                candidate_ids = tuple(
                    candidate.id or candidate.name for candidate in group
                )
                candidate_source_kinds = tuple(
                    candidate.source_kind for candidate in group
                )
                diagnostics.append(
                    resource_diagnostic(
                        code="resource_collision",
                        message=f"{resource_type} resource '{logical_id}' has no enabled candidates.",
                        source_path=group[0].source_path,
                        resource_id=logical_id,
                        resource_type=resource_type,
                        source_kind=group[0].source_kind,
                        metadata={
                            "winner_id": None,
                            "candidate_ids": candidate_ids,
                            "candidate_source_kinds": candidate_source_kinds,
                            **_collision_path_metadata(winner=None, candidates=group),
                        },
                    )
                )
                decisions.append(
                    ResourceMergeDecision(
                        resource_type=resource_type,
                        logical_id=logical_id,
                        winner_id=None,
                        winner_source_kind=None,
                        candidate_ids=candidate_ids,
                        candidate_source_kinds=candidate_source_kinds,
                        reason="no_enabled_candidates",
                    )
                )
            continue

        winner = enabled_candidates[0]
        candidate_ids = tuple(candidate.id or candidate.name for candidate in group)
        candidate_source_kinds = tuple(candidate.source_kind for candidate in group)
        top_rank = _source_precedence_rank(winner.source_kind)
        top_tier = [
            candidate
            for candidate in enabled_candidates
            if _source_precedence_rank(candidate.source_kind) == top_rank
        ]

        if len(top_tier) > 1:
            diagnostics.append(
                resource_diagnostic(
                    code="resource_collision",
                    message=f"{resource_type} resource '{logical_id}' has conflicting same-precedence candidates.",
                    source_path=top_tier[0].source_path,
                    resource_id=logical_id,
                    resource_type=resource_type,
                    source_kind=top_tier[0].source_kind,
                    metadata={
                        "winner_id": None,
                        "candidate_ids": candidate_ids,
                        "candidate_source_kinds": candidate_source_kinds,
                        **_collision_path_metadata(winner=None, candidates=group),
                    },
                )
            )
            decisions.append(
                ResourceMergeDecision(
                    resource_type=resource_type,
                    logical_id=logical_id,
                    winner_id=None,
                    winner_source_kind=None,
                    candidate_ids=candidate_ids,
                    candidate_source_kinds=candidate_source_kinds,
                    reason="same_precedence_conflict",
                )
            )
            continue

        active.append(winner)
        if len(group) > 1:
            diagnostics.append(
                resource_diagnostic(
                    code="resource_collision",
                    message=(
                        f"{resource_type} resource '{logical_id}' selected {winner.source_kind} "
                        f"candidate '{winner.id}' over lower-precedence candidates."
                    ),
                    source_path=winner.source_path,
                    resource_id=logical_id,
                    resource_type=resource_type,
                    source_kind=winner.source_kind,
                    metadata={
                        "winner_id": winner.id,
                        "candidate_ids": candidate_ids,
                        "candidate_source_kinds": candidate_source_kinds,
                        **_collision_path_metadata(winner=winner, candidates=group),
                    },
                )
            )
            decisions.append(
                ResourceMergeDecision(
                    resource_type=resource_type,
                    logical_id=logical_id,
                    winner_id=winner.id,
                    winner_source_kind=winner.source_kind,
                    candidate_ids=candidate_ids,
                    candidate_source_kinds=candidate_source_kinds,
                    reason="source_precedence",
                )
            )
        else:
            decisions.append(
                ResourceMergeDecision(
                    resource_type=resource_type,
                    logical_id=logical_id,
                    winner_id=winner.id,
                    winner_source_kind=winner.source_kind,
                    candidate_ids=(winner.id or winner.name,),
                    candidate_source_kinds=(winner.source_kind,),
                    reason="single_candidate",
                )
            )

    return active, diagnostics, decisions


def _collision_path_metadata(
    *,
    winner: DescriptorT | None,
    candidates: list[DescriptorT],
) -> dict[str, object]:
    winner_path = str(winner.source_path) if winner is not None else None
    candidate_paths = tuple(str(candidate.source_path) for candidate in candidates)
    loser_paths = tuple(
        str(candidate.source_path)
        for candidate in candidates
        if candidate is not winner
    )
    return {
        "winner_path": winner_path,
        "candidate_paths": candidate_paths,
        "loser_paths": loser_paths,
    }


def _resolve_extension_candidates(
    candidates: Sequence[ExtensionDescriptor],
    *,
    resource_type: str,
) -> tuple[
    list[ExtensionDescriptor], list[DiagnosticDraft], list[ResourceMergeDecision]
]:
    ordered = sorted(candidates, key=_candidate_sort_key)
    active: list[ExtensionDescriptor] = []
    diagnostics: list[DiagnosticDraft] = []
    decisions: list[ResourceMergeDecision] = []

    grouped: dict[str, list[ExtensionDescriptor]] = {}
    for candidate in ordered:
        grouped.setdefault(candidate.id or candidate.name, []).append(candidate)
        if candidate.enabled:
            active.append(candidate)
            continue
        diagnostics.append(
            resource_diagnostic(
                code="resource_disabled",
                message=f"{resource_type} resource '{candidate.id or candidate.name}' is disabled.",
                source_path=candidate.source_path,
                resource_id=candidate.id,
                resource_type=resource_type,
                source_kind=candidate.source_kind,
            )
        )

    for logical_id, group in grouped.items():
        enabled_group = [candidate for candidate in group if candidate.enabled]
        if not enabled_group:
            decisions.append(
                ResourceMergeDecision(
                    resource_type=resource_type,
                    logical_id=logical_id,
                    winner_id=None,
                    winner_source_kind=None,
                    candidate_ids=tuple(
                        candidate.id or candidate.name for candidate in group
                    ),
                    candidate_source_kinds=tuple(
                        candidate.source_kind for candidate in group
                    ),
                    reason="no_enabled_candidates",
                )
            )
            continue
        decisions.append(
            ResourceMergeDecision(
                resource_type=resource_type,
                logical_id=logical_id,
                winner_id=enabled_group[0].id,
                winner_source_kind=enabled_group[0].source_kind,
                candidate_ids=tuple(
                    candidate.id or candidate.name for candidate in group
                ),
                candidate_source_kinds=tuple(
                    candidate.source_kind for candidate in group
                ),
                reason="all_enabled_candidates_active"
                if len(enabled_group) > 1
                else "single_candidate",
            )
        )

    return active, diagnostics, decisions
