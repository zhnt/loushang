"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable, Sequence
from typing import Literal

from loushang.coding.resume import activation_projection_v2 as _binding
from loushang.harness.transcript.types import AgentTranscriptRecord

from .resume_records import matches_intent
from .selected_ancestry import SelectedAncestry


def project_activation_history_steps(
    records: Iterable[_binding.AgentTranscriptRecord],
    *,
    current_session_id: str,
    input_id: str | None = None,
) -> Generator[
    _binding.AgentTranscriptRecord | None,
    None,
    _binding.CodingActivationAttemptProjectionV2,
]:
    if (
        type(current_session_id) is not str
        or _binding.re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", current_session_id) is None
    ):
        raise ValueError(_binding._RESUME_OPERATION_VALUES["value_001"])
    ancestry = SelectedAncestry(_binding._ANCESTRY_DOMAIN)
    pending: dict[str, _binding.CodingActivationAttemptV1] = {}
    unknown = False
    selected_binding: (
        _binding.CodingRuntimeBindingV1 | _binding.CodingRuntimeBindingV2 | None
    ) = None
    selected_binding_record_id: str | None = None
    for record in records:
        ancestry.require_next(
            record, error=_binding._RESUME_OPERATION_VALUES["value_002"]
        )
        observed_binding: _binding.CodingRuntimeBindingV1 | None = None
        payload = record.payload
        if isinstance(
            payload, _binding.ExtensionData
        ) and payload.extension_type.startswith(
            _binding._RESUME_OPERATION_VALUES["value_003"]
        ):
            attempt: _binding.CodingActivationAttemptV1 | None
            if (
                payload.extension_type
                == _binding.CODING_ACTIVATION_ATTEMPT_EXTENSION_TYPE
            ):
                attempt = _binding.validate_coding_activation_attempt_record(record)
            elif (
                payload.extension_type
                == _binding.CODING_ACTIVATION_ATTEMPT_V2_EXTENSION_TYPE
            ):
                attempt = _binding.validate_coding_activation_attempt_v2_record(record)
            else:
                unknown = True
                attempt = None
            if attempt is not None:
                if attempt.ancestry_digest != ancestry.hexdigest():
                    raise ValueError(_binding._RESUME_OPERATION_VALUES["value_006"])
                if attempt.session_id in pending:
                    raise ValueError(_binding._RESUME_OPERATION_VALUES["value_007"])
                pending[attempt.session_id] = attempt
        reserved = {
            key
            for key in record.metadata
            if key.startswith(_binding._RESUME_OPERATION_VALUES["value_004"])
        }
        if reserved:
            if record.kind != _binding.AGENT_MESSAGE_KIND or not isinstance(
                payload, _binding.UserMessage
            ):
                raise ValueError(_binding._RESUME_OPERATION_VALUES["value_005"])
            if reserved == {_binding.CODING_RUNTIME_BINDING_V2_METADATA_KEY}:
                raw = record.metadata[_binding.CODING_RUNTIME_BINDING_V2_METADATA_KEY]
                version = (
                    raw.get("version") if isinstance(raw, _binding.Mapping) else None
                )
                if type(version) is int and version > 2:
                    unknown = True
                else:
                    binding_v2 = _binding.decode_coding_runtime_binding_v2(
                        record.metadata
                    )
                    matched = pending.get(binding_v2.session_id)
                    if type(matched) is not _binding.CodingActivationAttemptV2:
                        raise ValueError(_binding._RESUME_OPERATION_VALUES["value_008"])
                    _binding._require_decoded_v2_binding(
                        record,
                        binding_v2,
                        payload=_binding._require_v2_user_payload(record),
                        intent=matched,
                    )
                    observed_binding = binding_v2
                    del pending[binding_v2.session_id]
            elif reserved == {_binding.CODING_RUNTIME_BINDING_METADATA_KEY}:
                observation = _binding.inspect_coding_runtime_binding(record.metadata)
                if observation.status == "unknown_version":
                    unknown = True
                elif (binding := observation.binding) is not None:
                    _binding._require_decoded_v1_binding(
                        record,
                        binding,
                        payload=payload,
                        expected_session_id=binding.session_id,
                    )
                    matched = pending.get(binding.session_id)
                    if matched is not None:
                        if type(matched) is not _binding.CodingActivationAttemptV1:
                            raise ValueError(
                                _binding._RESUME_OPERATION_VALUES["value_009"]
                            )
                        if record.parent_id != matched.attempt_id or not matches_intent(
                            binding, matched, check_session=False
                        ):
                            raise ValueError(
                                _binding._RESUME_OPERATION_VALUES["value_010"]
                            )
                        del pending[binding.session_id]
                    observed_binding = binding
            else:
                unknown = True
        match = None
        if (
            observed_binding is not None
            and observed_binding.session_id == current_session_id
            and not unknown
        ):
            selected_binding = observed_binding
            selected_binding_record_id = record.record_id
            if observed_binding.input_id == input_id:
                match = record
        ancestry.advance(record, _binding._encoded)
        yield match
    ancestry_digest = ancestry.hexdigest()
    if unknown:
        return _binding.CodingActivationAttemptProjectionV2(
            "unknown_version",
            ancestry_digest=ancestry_digest,
            binding_status="unknown_version",
            binding_record_id=selected_binding_record_id,
        )
    current = pending.get(current_session_id)
    if current is not None:
        return _binding.CodingActivationAttemptProjectionV2(
            "pending",
            current,
            current.attempt_id,
            ancestry_digest,
            "bound" if selected_binding is not None else "none",
            selected_binding,
            selected_binding_record_id,
        )
    return _binding.CodingActivationAttemptProjectionV2(
        "none",
        ancestry_digest=ancestry_digest,
        binding_status="bound" if selected_binding is not None else "none",
        binding=selected_binding,
        binding_record_id=selected_binding_record_id,
    )


def find_input_records(
    records: Iterable[_binding.AgentTranscriptRecord],
    *,
    current_session_id: str,
    input_id: str,
) -> list[_binding.AgentTranscriptRecord] | None:
    """Find exact-session inputs while verifying the whole selected path."""
    steps = project_activation_history_steps(
        records, current_session_id=current_session_id, input_id=input_id
    )
    matches: list[_binding.AgentTranscriptRecord] = []
    while True:
        try:
            record = next(steps)
        except StopIteration as complete:
            # A later unknown version invalidates even an earlier known input.
            return None if complete.value.status == "unknown_version" else matches
        if record is not None:
            matches.append(record)


def select_input_record(
    candidates: Sequence[AgentTranscriptRecord],
    *,
    expected_digest: str,
    digest: Callable[[AgentTranscriptRecord], str],
    duplicate: Literal["unknown", "conflict"] = "conflict",
) -> AgentTranscriptRecord | Literal["unknown", "conflict"]:
    """Require one candidate and the exact bytes fixed for that input."""
    if not candidates:
        return "unknown"
    if len(candidates) != 1:
        return duplicate
    record = candidates[0]
    return record if digest(record) == expected_digest else "conflict"


def observe_latest_bound_input(
    records: Sequence[AgentTranscriptRecord],
    *,
    current_session_id: str,
    input_id: str,
    expected_digest: str,
    digest: Callable[[AgentTranscriptRecord], str],
) -> AgentTranscriptRecord | Literal["unknown", "conflict"] | None:
    """Observe the latest bound input before a live owner is attached.

    None allows the caller to consult its retained request when the projected
    Binding does not identify this input.
    """
    projection = _binding.project_coding_activation_attempt_path_v2(
        records, current_session_id=current_session_id
    )
    binding = projection.binding
    if (
        projection.binding_status != "bound"
        or binding is None
        or binding.input_id != input_id
        or projection.binding_record_id is None
    ):
        return None
    return select_input_record(
        [record for record in records if record.record_id == projection.binding_record_id],
        expected_digest=expected_digest, digest=digest, duplicate="unknown",
    )


def find_legacy_model_input(
    records: Iterable[AgentTranscriptRecord],
    *,
    current_session_id: str,
    input_id: str,
    expected_digest: str,
    digest: Callable[[AgentTranscriptRecord], str],
) -> tuple[int, AgentTranscriptRecord] | Literal["unknown", "conflict"]:
    """Find the exact V1-bound input and its position for model observation."""
    matches: list[AgentTranscriptRecord] = []
    first_index = 0
    try:
        for index, record in enumerate(records):
            binding = _binding.inspect_coding_runtime_binding(record.metadata).binding
            if binding is None or binding.session_id != current_session_id or binding.input_id != input_id:
                continue
            _binding._require_decoded_v1_binding(
                record, binding, payload=_binding._require_v1_user_payload(record),
                expected_session_id=current_session_id,
            )
            if not matches:
                first_index = index
            matches.append(record)
    except ValueError:
        return "unknown"
    selected = select_input_record(matches, expected_digest=expected_digest, digest=digest)
    return selected if isinstance(selected, str) else (first_index, selected)
