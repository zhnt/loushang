"""Coding's compatibility names for the shared Resume cleanup owner."""

from loushang.harness.session._resume_continuation import (
    ResumeContinuationCleanupFailure,
)


class CodingResumeContinuationCleanupFailure(ResumeContinuationCleanupFailure):
    _cleanup_label = "Coding Resume"


retain_resume_cleanup_failure = (
    CodingResumeContinuationCleanupFailure.retain_resume_cleanup_failure
)
discard_candidate = CodingResumeContinuationCleanupFailure.discard_candidate
