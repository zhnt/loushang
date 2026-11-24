"""Coding bindings for the hosted user choice and its historical result tag."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from loushang.apphost.integrations.user_choice import ASK_USER as ASK_USER
from loushang.apphost.integrations.user_choice import HostedUserChoiceRuntime
from loushang.appserver.protocol import UserChoicePromptV1
from loushang.harness.transcript import AgentTranscriptRecord


class _UnverifiableChoice(ValueError):
    """A redacted diagnostic for ambiguous or invalid transcript evidence."""


class HostedUserChoice(HostedUserChoiceRuntime):
    """Keep the result tag used by existing Coding transcripts."""

    _result_kind = "coding.user_choice/v1"
    _logger = logging.getLogger(__name__)
    _evidence_error = _UnverifiableChoice


def recover_pending_choice(
    selected_records: Sequence[AgentTranscriptRecord], session_id: str
) -> UserChoicePromptV1 | None:
    """Project the latest committed question in a validated active branch."""
    return HostedUserChoice.recover_pending_choice(selected_records, session_id)


def pending_choice_from_transcript(
    selected_records: Sequence[AgentTranscriptRecord], session_id: str
) -> UserChoicePromptV1 | None:
    return HostedUserChoice.pending_choice_from_transcript(selected_records, session_id)
