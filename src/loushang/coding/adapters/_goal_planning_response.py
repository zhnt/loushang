"""Coding profile compatibility over shared committed-response verification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from loushang.harness.events import RuntimeEvent
from loushang.harness.session import response_proof as _proof

from ._goal_proposal import LIMITS, ProposalRejected

ResponseBoundary = _proof.ResponseBoundary


def _profile_error(error: _proof.ResponseProofError) -> ProposalRejected:
    return ProposalRejected(str(error).replace("response", "planning", 1))


def capture_response(
    manager,
    boundary: ResponseBoundary,
    *,
    session_id: str,
    prompt: str,
    events: Sequence[RuntimeEvent],
) -> tuple[bytes, dict[str, object]]:
    try:
        return _proof.capture_response(
            manager, boundary, session_id=session_id, prompt=prompt, events=events,
            max_attempts=LIMITS["provider_attempts"],
        )
    except _proof.ResponseProofError as error:
        raise _profile_error(error) from error


def verify_response(
    manager, proof: Mapping[str, object], *, session_id: str, prompt: str, raw: bytes
) -> None:
    try:
        _proof.verify_response(
            manager, proof, session_id=session_id, prompt=prompt, raw=raw,
            max_attempts=LIMITS["provider_attempts"],
        )
    except _proof.ResponseProofError as error:
        raise _profile_error(error) from error
