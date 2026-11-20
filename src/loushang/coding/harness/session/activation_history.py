"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable

from loushang.coding.resume import activation_projection_v2 as _binding

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
                    _binding.validate_coding_resume_v2_user_record(
                        record, intent=matched
                    )
                    observed_binding = binding_v2
                    del pending[binding_v2.session_id]
            elif reserved == {_binding.CODING_RUNTIME_BINDING_METADATA_KEY}:
                observation = _binding.inspect_coding_runtime_binding(record.metadata)
                if observation.status == "unknown_version":
                    unknown = True
                elif observation.binding is not None:
                    binding = _binding.validate_coding_runtime_binding_record(
                        record,
                        expected_session_id=observation.binding.session_id,
                    )
                    matched = pending.get(binding.session_id)
                    if matched is not None:
                        if type(matched) is not _binding.CodingActivationAttemptV1:
                            raise ValueError(
                                _binding._RESUME_OPERATION_VALUES["value_009"]
                            )
                        if (
                            record.parent_id != matched.attempt_id
                            or binding.attempt_id != matched.attempt_id
                            or binding.input_id != matched.request_id
                            or binding.original_leaf_id != matched.original_leaf_id
                            or binding.ancestry_digest != matched.ancestry_digest
                            or binding.planned_fingerprint != matched.plan_fingerprint
                            or binding.actual_fingerprint != matched.epoch_fingerprint
                            or binding.subject_digest != matched.subject_digest
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
