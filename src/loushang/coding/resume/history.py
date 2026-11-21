"""Read-only Coding Resume Header projection, without execution admission."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.coding.composition.plan import (
    CODING_CAPABILITY_PROFILE_METADATA_KEY,
    CODING_PRODUCT_ID,
    CODING_TRANSCRIPT_RUNTIME,
)
from loushang.coding.composition.provenance import (
    CodingCompositionProvenanceV1,
    historical_composition_provenance,
)
from loushang.coding.composition.provenance import (
    historical_startup_composition_record as historical_startup_composition_record,
)
from loushang.coding.harness.session import history_snapshot as _programs
from loushang.coding.resume.activation_attempt import CodingActivationAttemptV1
from loushang.coding.resume.activation_projection_v2 import (
    project_coding_activation_attempt_path_v2 as project_coding_activation_attempt_path_v2,
)
from loushang.coding.resume.binding import CodingRuntimeBindingV1
from loushang.coding.resume.binding_v2 import CodingRuntimeBindingV2
from loushang.harness.conversation import ConversationHeader
from loushang.harness.conversation import (
    ConversationRepository as ConversationRepository,
)
from loushang.harness.runtime import RuntimeProfileSnapshot
from loushang.harness.transcript.jsonl_file import (
    load_agent_transcript_file_with_content_digest as load_agent_transcript_file_with_content_digest,
)
from loushang.harness.transcript.jsonl_file import (
    load_agent_transcript_header,
)
from loushang.harness.transcript.session_catalog import (
    read_agent_transcript_bounded_preview as read_agent_transcript_bounded_preview,
)
from loushang.harness.transcript.session_catalog import (
    session_file_authority_fingerprint as session_file_authority_fingerprint,
)
from loushang.harness.transcript.types import AgentTranscriptRecord

MAX_CODING_RESUME_HISTORY_BYTES = 64 * 1024 * 1024


_RESUME_PLAN_PROGRAM_VALUES = {
    "value_001": "Coding Resume snapshot budget must be within 1 to 64 MiB",
    "value_002": "Coding Resume source changed before snapshot",
    "value_003": "Coding Resume source changed during snapshot",
}


@dataclass(frozen=True, slots=True)
class CodingResumeHeaderPreview:
    """A bounded Header observation, never proof of a writable Session."""

    header: ConversationHeader
    product_identity: Literal["coding", "unknown"]
    composition: CodingCompositionProvenanceV1 | None


@dataclass(frozen=True, slots=True)
class CodingResumeHistoryPreview:
    """A bounded read-only transcript snapshot, never an execution snapshot."""

    header_preview: CodingResumeHeaderPreview
    records: tuple[AgentTranscriptRecord, ...]
    selected_records: tuple[AgentTranscriptRecord, ...]
    selected_leaf_id: str | None
    startup: dict[str, object] | None
    provenance_conflict: bool
    binding_status: Literal["none", "bound", "unknown_version", "invalid"]
    binding: CodingRuntimeBindingV1 | CodingRuntimeBindingV2 | None
    selected_ancestry_digest: str | None
    source_fingerprint: str
    source_content_digest: str
    activation_status: Literal["none", "pending", "unknown_version", "invalid"] = "none"
    pending_activation_attempt: CodingActivationAttemptV1 | None = None
    pending_activation_record_id: str | None = None
    status: Literal["preview"] = "preview"


@dataclass(frozen=True, slots=True)
class CodingResumeRecentPage:
    """A bounded tail display; its records are not a selected ancestry."""

    header_preview: CodingResumeHeaderPreview
    records: tuple[AgentTranscriptRecord, ...]
    source_fingerprint: str
    bytes_read: int
    status: Literal["unverified_tail_preview"] = "unverified_tail_preview"


def inspect_coding_resume_header(
    header: ConversationHeader,
) -> CodingResumeHeaderPreview:
    """Classify historical evidence without resolving the installed composition."""

    runtime = CODING_TRANSCRIPT_RUNTIME.read_snapshot(header.metadata)
    raw_capability = header.metadata.get(CODING_CAPABILITY_PROFILE_METADATA_KEY)
    capability = (
        None
        if raw_capability is None
        else RuntimeProfileSnapshot.from_json(raw_capability)
    )
    if capability is not None and capability.product_id != CODING_PRODUCT_ID:
        raise ValueError(
            "Coding cannot view a session with a capability profile for Product "
            f"{capability.product_id!r}"
        )
    return CodingResumeHeaderPreview(
        header=header,
        product_identity=(
            "coding" if runtime is not None or capability is not None else "unknown"
        ),
        composition=historical_composition_provenance(header.metadata),
    )


def read_coding_resume_header(path: str | Path) -> CodingResumeHeaderPreview:
    """Read an admitted Session path without a Writer, repair, or lock file."""

    return inspect_coding_resume_header(
        load_agent_transcript_header(Path(path), read_only=True)
    )


def read_coding_resume_snapshot(
    path: str | Path,
    *,
    max_bytes: int,
    selected_leaf_id: str | None = None,
    expected_source_fingerprint: str | None = None,
) -> CodingResumeHistoryPreview:
    """Read a bounded historical snapshot without acquiring transcript authority."""

    return _programs.read_resume_snapshot(
        path,
        max_bytes=max_bytes,
        selected_leaf_id=selected_leaf_id,
        expected_source_fingerprint=expected_source_fingerprint,
    )


def read_coding_resume_recent_page(
    path: str | Path,
    *,
    segment_bytes: int = 64 * 1024,
) -> CodingResumeRecentPage:
    """Show recent decoded tail records without proving their selected branch."""

    return _programs.read_resume_recent_page(path, segment_bytes=segment_bytes)


__all__ = [
    "CodingResumeHeaderPreview",
    "CodingResumeHistoryPreview",
    "CodingResumeRecentPage",
    "MAX_CODING_RESUME_HISTORY_BYTES",
    "inspect_coding_resume_header",
    "read_coding_resume_header",
    "read_coding_resume_recent_page",
    "read_coding_resume_snapshot",
]
