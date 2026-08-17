"""Selectable compaction mechanisms for the standard Agent transcript.

The mechanism in this module owns transcript cut-point planning and the
configuration that selects it. Products provide only summary execution.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.context import ConversationCompactionPlanner
from loushang.harness.transcript.context_usage import estimate_context_tokens
from loushang.harness.transcript.maintenance import (
    CompactionPlan,
    CompactionPreparation,
    TranscriptCompactionPolicy,
)
from loushang.harness.transcript.profile import AgentTranscriptProfile
from loushang.harness.transcript.types import (
    AgentTranscriptRecord,
    ContextCompactionCheckpoint,
)

TURN_AWARE_SUMMARY_IMPLEMENTATION = "agent_transcript.turn_aware_summary"
TURN_AWARE_SUMMARY_VERSION = 1


def _require_boolean(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def _require_non_negative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_percentage(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not 0.0 <= normalized <= 100.0:
        raise ValueError(f"{name} must be between 0 and 100")
    return normalized


@dataclass(frozen=True)
class TranscriptCompactionConfiguration:
    """Strict JSON configuration for turn-aware transcript compaction."""

    enabled: bool
    compact_percent: float
    reserve_tokens: int
    keep_recent_tokens: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "enabled", _require_boolean(self.enabled, name="enabled")
        )
        object.__setattr__(
            self,
            "compact_percent",
            _require_percentage(self.compact_percent, name="compact_percent"),
        )
        object.__setattr__(
            self,
            "reserve_tokens",
            _require_non_negative_int(self.reserve_tokens, name="reserve_tokens"),
        )
        object.__setattr__(
            self,
            "keep_recent_tokens",
            _require_non_negative_int(
                self.keep_recent_tokens, name="keep_recent_tokens"
            ),
        )

    @classmethod
    def from_json(
        cls, value: Mapping[str, object]
    ) -> TranscriptCompactionConfiguration:
        if not isinstance(value, Mapping):
            raise TypeError("compaction config must be a mapping")
        config = require_json_mapping(dict(value), name="compaction config")
        expected = {
            "enabled",
            "compactPercent",
            "reserveTokens",
            "keepRecentTokens",
        }
        unknown = sorted(set(config) - expected)
        missing = sorted(expected - set(config))
        if unknown:
            raise ValueError(
                "compaction config contains unsupported fields: " + ", ".join(unknown)
            )
        if missing:
            raise ValueError(
                "compaction config is missing required fields: " + ", ".join(missing)
            )
        return cls(
            enabled=_require_boolean(config["enabled"], name="enabled"),
            compact_percent=_require_percentage(
                config["compactPercent"], name="compactPercent"
            ),
            reserve_tokens=_require_non_negative_int(
                config["reserveTokens"], name="reserveTokens"
            ),
            keep_recent_tokens=_require_non_negative_int(
                config["keepRecentTokens"], name="keepRecentTokens"
            ),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "enabled": self.enabled,
            "compactPercent": self.compact_percent,
            "reserveTokens": self.reserve_tokens,
            "keepRecentTokens": self.keep_recent_tokens,
        }

    def to_policy(self) -> TranscriptCompactionPolicy:
        return TranscriptCompactionPolicy(
            enabled=self.enabled,
            compact_percent=self.compact_percent,
            reserve_tokens=self.reserve_tokens,
            keep_recent_tokens=self.keep_recent_tokens,
        )


@dataclass(frozen=True)
class AgentTranscriptCompactionCapability:
    """A selected Harness mechanism for one Agent transcript session."""

    implementation: str
    implementation_version: int
    configuration: TranscriptCompactionConfiguration

    def __post_init__(self) -> None:
        if not isinstance(self.implementation, str) or not self.implementation:
            raise ValueError("transcript compaction implementation must be non-empty")
        if type(self.implementation_version) is not int:
            raise TypeError(
                "transcript compaction implementation version must be an integer"
            )
        if self.implementation != TURN_AWARE_SUMMARY_IMPLEMENTATION:
            raise ValueError(
                "unsupported transcript compaction implementation: "
                f"{self.implementation}"
            )
        if self.implementation_version != TURN_AWARE_SUMMARY_VERSION:
            raise ValueError(
                "unsupported transcript compaction implementation version: "
                f"{self.implementation_version}"
            )
        if not isinstance(self.configuration, TranscriptCompactionConfiguration):
            raise TypeError("configuration must be TranscriptCompactionConfiguration")

    @property
    def policy(self) -> TranscriptCompactionPolicy:
        return self.configuration.to_policy()

    def prepare(
        self,
        entries: list[AgentTranscriptRecord],
        keep_recent_tokens: int | None = None,
    ) -> CompactionPreparation:
        return prepare_turn_aware_compaction(
            entries,
            keep_recent_tokens=(
                self.configuration.keep_recent_tokens
                if keep_recent_tokens is None
                else keep_recent_tokens
            ),
        )


def create_agent_transcript_compaction_capability(
    *,
    implementation: str,
    implementation_version: int,
    config: Mapping[str, object],
) -> AgentTranscriptCompactionCapability:
    """Create a supported capability from a resolved profile selection."""

    if not isinstance(implementation, str) or not implementation:
        raise ValueError("transcript compaction implementation must be non-empty")
    if type(implementation_version) is not int:
        raise TypeError(
            "transcript compaction implementation version must be an integer"
        )
    if implementation != TURN_AWARE_SUMMARY_IMPLEMENTATION:
        raise ValueError(
            f"unsupported transcript compaction implementation: {implementation}"
        )
    if implementation_version != TURN_AWARE_SUMMARY_VERSION:
        raise ValueError(
            "unsupported transcript compaction implementation version: "
            f"{implementation_version}"
        )
    return AgentTranscriptCompactionCapability(
        implementation=implementation,
        implementation_version=implementation_version,
        configuration=TranscriptCompactionConfiguration.from_json(config),
    )


def prepare_turn_aware_compaction(
    entries: list[AgentTranscriptRecord], keep_recent_tokens: int
) -> CompactionPreparation:
    """Prepare the deterministic transcript portion of one summary operation."""

    plan = plan_turn_aware_compaction(entries, keep_recent_tokens)
    profile = _turn_aware_profile()
    messages_to_summarize = [
        message
        for entry_id in plan.summarized_entry_ids
        for entry in entries
        if entry.record_id == entry_id
        if (message := profile.record_to_context_item(entry)) is not None
    ]
    turn_prefix_messages = [
        message
        for entry_id in plan.turn_prefix_entry_ids
        for entry in entries
        if entry.record_id == entry_id
        if (message := profile.record_to_context_item(entry)) is not None
    ]
    return CompactionPreparation(
        first_kept_entry_id=plan.first_kept_entry_id,
        messages_to_summarize=messages_to_summarize,
        turn_prefix_messages=turn_prefix_messages,
        is_split_turn=plan.is_split_turn,
        tokens_before=plan.tokens_before,
        previous_summary=_previous_summary(entries, plan.previous_compaction_id),
        details={"compactionPlan": compaction_plan_to_json(plan)},
        plan=plan,
    )


def plan_turn_aware_compaction(
    entries: Sequence[AgentTranscriptRecord], keep_recent_tokens: int
) -> CompactionPlan:
    """Plan a summary boundary without executing a model or mutating a transcript."""

    retained_tokens = _require_non_negative_int(
        keep_recent_tokens, name="keep_recent_tokens"
    )
    profile = _turn_aware_profile()
    records = list(entries)
    if not any(profile.record_to_context_item(entry) is not None for entry in records):
        raise ValueError("Compaction requires at least one visible message entry.")
    shared_plan = _turn_aware_planner(profile).plan(
        records,
        keep_recent_tokens=retained_tokens,
    )
    previous_compaction_id = (
        shared_plan.previous_summary.record_id
        if shared_plan.previous_summary is not None
        else None
    )
    return CompactionPlan(
        previous_compaction_id=previous_compaction_id,
        previous_first_kept_entry_id=_previous_first_kept_entry_id(
            records, previous_compaction_id
        ),
        first_kept_entry_id=shared_plan.first_kept_record_id,
        summarized_entry_ids=shared_plan.summarized_record_ids,
        turn_prefix_entry_ids=shared_plan.turn_prefix_record_ids,
        kept_entry_ids=shared_plan.kept_record_ids,
        is_split_turn=shared_plan.is_split_turn,
        tokens_before=shared_plan.tokens_before,
        keep_recent_tokens=shared_plan.keep_recent_tokens,
    )


def compaction_plan_to_json(plan: CompactionPlan) -> dict[str, JSONValue]:
    """Return stable, product-neutral checkpoint diagnostics for a plan."""

    return {
        "previousCompactionId": plan.previous_compaction_id,
        "previousFirstKeptEntryId": plan.previous_first_kept_entry_id,
        "firstKeptEntryId": plan.first_kept_entry_id,
        "summarizedEntryIds": list(plan.summarized_entry_ids),
        "turnPrefixEntryIds": list(plan.turn_prefix_entry_ids),
        "keptEntryIds": list(plan.kept_entry_ids),
        "isSplitTurn": plan.is_split_turn,
        "tokensBefore": plan.tokens_before,
        "keepRecentTokens": plan.keep_recent_tokens,
    }


def _turn_aware_profile() -> AgentTranscriptProfile:
    return AgentTranscriptProfile(
        context_token_estimator=lambda messages: (
            estimate_context_tokens(list(messages)).tokens
        )
    )


def _turn_aware_planner(
    profile: AgentTranscriptProfile,
) -> ConversationCompactionPlanner[AgentTranscriptRecord, str]:
    return ConversationCompactionPlanner(
        profile.record_ports(),
        turn_start_roles=frozenset({"user"}),
        non_cut_roles=frozenset({"toolResult"}),
        missing_previous_summary="error",
    )


def _previous_first_kept_entry_id(
    entries: Sequence[AgentTranscriptRecord], previous_compaction_id: str | None
) -> str | None:
    if previous_compaction_id is None:
        return None
    for entry in entries:
        if entry.record_id == previous_compaction_id and isinstance(
            entry.payload, ContextCompactionCheckpoint
        ):
            return entry.payload.first_kept_record_id
    return None


def _previous_summary(
    entries: Sequence[AgentTranscriptRecord], previous_compaction_id: str | None
) -> str | None:
    if previous_compaction_id is None:
        return None
    for entry in entries:
        if entry.record_id == previous_compaction_id and isinstance(
            entry.payload, ContextCompactionCheckpoint
        ):
            return entry.payload.summary
    return None


__all__ = [
    "AgentTranscriptCompactionCapability",
    "TURN_AWARE_SUMMARY_IMPLEMENTATION",
    "TURN_AWARE_SUMMARY_VERSION",
    "TranscriptCompactionConfiguration",
    "compaction_plan_to_json",
    "create_agent_transcript_compaction_capability",
    "plan_turn_aware_compaction",
    "prepare_turn_aware_compaction",
]
