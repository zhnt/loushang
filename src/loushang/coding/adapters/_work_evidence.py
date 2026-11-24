"""Coding compatibility types for Session artifact evidence."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harnesswork.integrations.evidence import (
    EvidenceRecord as _EvidenceRecord,
)
from loushang.harnesswork.integrations.evidence import (
    SupportReference as _SupportReference,
)
from loushang.harnesswork.integrations.evidence import WorkEvidenceCodec


class EvidenceReplayError(ValueError):
    """A supported evidence report violates the private interchange contract."""


class UnsupportedEvidenceVersion(EvidenceReplayError):
    """The caller cannot interpret this evidence version."""


@dataclass(frozen=True)
class EvidenceRecord(_EvidenceRecord):
    pass


@dataclass(frozen=True)
class SupportReference(_SupportReference):
    pass


EVIDENCE_CODEC = WorkEvidenceCodec(
    EvidenceRecord,
    SupportReference,
    invalid=EvidenceReplayError,
    unsupported_version=UnsupportedEvidenceVersion,
    invalid_kind_message="not a Coding evidence report",
)

work_evidence_fact = EVIDENCE_CODEC.work_evidence_fact
validate_evidence_fact = EVIDENCE_CODEC.validate_evidence_fact
project_work_evidence = EVIDENCE_CODEC.project_work_evidence
deviation_support = EVIDENCE_CODEC.deviation_support
