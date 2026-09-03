"""Internal PLC9B Package lifecycle owner boundary.

This package is intentionally not re-exported from the public Package facade.
PLC9B1 contains only inert records, classification, durable status, and CAS
mechanics. Later dark submodules add explicitly injected acquisition,
quarantine, wheel, and pure closure-verification capabilities, but this package
still has no production route, publication, process, or desired-state authority.
"""

from __future__ import annotations

from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PACKAGE_LIFECYCLE_JOURNAL_CODEC,
    PackageLifecycleJournal,
    PackageLifecycleJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageClassificationAuthorityPort,
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleCancelRequestV1,
    PackageLifecycleFailureV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleIngressRequestV2,
    PackageLifecycleJournalRecordV1,
    PackageLifecycleRequestV1,
    PackageLifecycleRequestV2,
    PackageLifecycleRetryRequestV1,
    PackageLifecycleStatusV1,
    PluginBoundPackageClassificationV1,
    canonical_json_bytes,
    canonicalize_source_identity,
    classify_package_request,
)

__all__ = [
    "PACKAGE_LIFECYCLE_JOURNAL_CODEC",
    "PackageClassificationAuthorityPort",
    "PackageClassificationBasisFactV1",
    "PackageClassificationFactsV1",
    "PackageLifecycleCancelRequestV1",
    "PackageLifecycleFailureV1",
    "PackageLifecycleIngressRequestV1",
    "PackageLifecycleIngressRequestV2",
    "PackageLifecycleJournal",
    "PackageLifecycleJournalError",
    "PackageLifecycleJournalRecordV1",
    "PackageLifecycleOwner",
    "PackageLifecycleRequestV1",
    "PackageLifecycleRequestV2",
    "PackageLifecycleRetryRequestV1",
    "PackageLifecycleStatusV1",
    "PluginBoundPackageClassificationV1",
    "canonical_json_bytes",
    "canonicalize_source_identity",
    "classify_package_request",
]
