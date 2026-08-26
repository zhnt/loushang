"""Replay durable provider-attempt usage without inferring missing observations."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.ai.types import Usage
from loushang.harness.transcript.kinds import MODEL_CALL_ATTEMPT_USAGE_KIND
from loushang.harness.transcript.model_input_types import (
    ModelInputIntegrityError,
    ModelInputSnapshot,
)
from loushang.harness.transcript.model_input_v2_types import ModelInputSnapshotV2
from loushang.harness.transcript.model_usage_types import ModelCallAttemptUsage
from loushang.harness.transcript.types import AgentTranscriptRecord


@dataclass(frozen=True)
class ModelCallAttemptUsageProjection:
    invocation_id: str
    attempt: int
    model_input_snapshot_id: str
    usage: Usage
    terminal: bool
    components_complete: bool


@dataclass(frozen=True)
class ModelCallUsageLedger:
    attempts: tuple[ModelCallAttemptUsageProjection, ...]
    usage: Usage
    complete: bool


def project_model_call_usage(
    records: list[AgentTranscriptRecord] | tuple[AgentTranscriptRecord, ...],
) -> ModelCallUsageLedger:
    """Apply partial-snapshot replacement within attempts and sum across attempts."""

    prepared: dict[tuple[str, int, str], int] = {}
    order: list[tuple[str, int, str]] = []
    observations: dict[tuple[str, int, str], list[ModelCallAttemptUsage]] = {}
    for index, record in enumerate(records):
        payload = record.payload
        if isinstance(payload, ModelInputSnapshot | ModelInputSnapshotV2):
            key = (payload.invocation_id, payload.attempt, payload.snapshot_id)
            prepared[key] = index
            continue
        if record.kind != MODEL_CALL_ATTEMPT_USAGE_KIND or not isinstance(
            payload, ModelCallAttemptUsage
        ):
            continue
        key = (payload.invocation_id, payload.attempt, payload.model_input_snapshot_id)
        snapshot_index = prepared.get(key)
        if snapshot_index is None or snapshot_index >= index:
            raise ModelInputIntegrityError(
                "model call attempt usage has no matching prior Model Input snapshot"
            )
        if key not in observations:
            order.append(key)
            observations[key] = []
        if payload not in observations[key]:
            observations[key].append(payload)

    attempts = tuple(
        _project_attempt(key, observations[key]) for key in order
    )
    aggregate = Usage(
        input=sum(item.usage.input for item in attempts),
        output=sum(item.usage.output for item in attempts),
        cache_read=sum(item.usage.cache_read for item in attempts),
        cache_write=sum(item.usage.cache_write for item in attempts),
        total_tokens=sum(item.usage.total_tokens for item in attempts),
        cost=None,
    )
    return ModelCallUsageLedger(
        attempts=attempts,
        usage=aggregate,
        complete=(
            bool(prepared)
            and set(observations) == set(prepared)
            and all(item.terminal and item.components_complete for item in attempts)
        ),
    )


def _project_attempt(
    key: tuple[str, int, str],
    observations: list[ModelCallAttemptUsage],
) -> ModelCallAttemptUsageProjection:
    components = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    provider_total: int | None = None
    terminal = False
    observed_components: set[str] = set()
    for observation in observations:
        if terminal:
            raise ModelInputIntegrityError(
                "model call attempt usage changed after its terminal observation"
            )
        component_changed = False
        for name in components:
            value = getattr(observation, name)
            if value is not None:
                components[name] = value
                observed_components.add(name)
                component_changed = True
        if observation.total_tokens is not None:
            provider_total = observation.total_tokens
        elif component_changed:
            provider_total = None
        terminal = observation.terminal
    component_total = sum(components.values())
    usage = Usage(
        **components,
        total_tokens=max(provider_total or 0, component_total),
        cost=None,
    )
    return ModelCallAttemptUsageProjection(
        invocation_id=key[0],
        attempt=key[1],
        model_input_snapshot_id=key[2],
        usage=usage,
        terminal=terminal,
        components_complete=observed_components == set(components),
    )


__all__ = [
    "ModelCallAttemptUsageProjection",
    "ModelCallUsageLedger",
    "project_model_call_usage",
]
