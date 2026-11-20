"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from typing import Literal

from loushang.coding.resume import history as _binding

from .composition_receipt import composition_receipt_matches


def read_resume_snapshot(
    path: str | _binding.Path,
    *,
    max_bytes: int,
    selected_leaf_id: str | None,
    expected_source_fingerprint: str | None,
) -> _binding.CodingResumeHistoryPreview:
    """Read a bounded historical snapshot without acquiring transcript authority."""

    if (
        type(max_bytes) is not int
        or not 1 <= max_bytes <= _binding.MAX_CODING_RESUME_HISTORY_BYTES
    ):
        raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_001"])
    source_path = _binding.Path(path)
    source_fingerprint = _binding.session_file_authority_fingerprint(source_path)
    if (
        expected_source_fingerprint is not None
        and source_fingerprint != expected_source_fingerprint
    ):
        raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_002"])
    (
        header,
        records,
        source_content_digest,
    ) = _binding.load_agent_transcript_file_with_content_digest(
        source_path,
        max_bytes=max_bytes,
        read_only=True,
    )
    if _binding.session_file_authority_fingerprint(source_path) != source_fingerprint:
        raise ValueError(_binding._RESUME_PLAN_PROGRAM_VALUES["value_003"])
    header_preview = _binding.inspect_coding_resume_header(header)
    repository = _binding.ConversationRepository.create(
        header=header,
        records=records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        leaf_id=selected_leaf_id,
    )
    startup = _binding.historical_startup_composition_record(records)
    composition = header_preview.composition
    selected_records = repository.active_records()
    try:
        projection = _binding.project_coding_activation_attempt_path_v2(
            selected_records,
            current_session_id=header.conversation_id,
        )
        binding_status: Literal["none", "bound", "unknown_version", "invalid"] = (
            projection.binding_status
        )
        binding = projection.binding
        ancestry_digest = projection.ancestry_digest
        activation_status: Literal["none", "pending", "unknown_version", "invalid"] = (
            projection.status
        )
        pending_attempt = projection.attempt
        pending_record_id = projection.record_id
    except ValueError:
        # Historical viewing remains possible when persisted Resume facts are unusable.
        binding_status = "invalid"
        binding = None
        ancestry_digest = None
        activation_status = "invalid"
        pending_attempt = None
        pending_record_id = None
    return _binding.CodingResumeHistoryPreview(
        header_preview=header_preview,
        records=tuple(records),
        selected_records=selected_records,
        selected_leaf_id=repository.leaf_id,
        startup=startup,
        provenance_conflict=(
            startup is not None
            and composition is not None
            and not composition_receipt_matches(
                startup, composition.set_id, composition.plan_fingerprint
            )
        ),
        binding_status=binding_status,
        binding=binding,
        selected_ancestry_digest=ancestry_digest,
        source_fingerprint=source_fingerprint,
        source_content_digest=source_content_digest,
        activation_status=activation_status,
        pending_activation_attempt=pending_attempt,
        pending_activation_record_id=pending_record_id,
    )


def read_resume_recent_page(
    path: str | _binding.Path, *, segment_bytes: int
) -> _binding.CodingResumeRecentPage:
    """Show recent decoded tail records without proving their selected branch."""

    bounded = _binding.read_agent_transcript_bounded_preview(
        path,
        segment_bytes=segment_bytes,
    )
    return _binding.CodingResumeRecentPage(
        header_preview=_binding.inspect_coding_resume_header(bounded.header),
        records=bounded.tail_records,
        source_fingerprint=bounded.source_fingerprint,
        bytes_read=bounded.bytes_read,
    )
