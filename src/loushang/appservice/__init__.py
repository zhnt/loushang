"""Product-neutral G11 hosted application semantics."""

from .client import InProcessAppClientV1
from .continuity import (
    APPLICATION_CONTINUITY_VERSION,
    MAX_APPLICATION_RECORDS,
    MAX_CONTINUITY_RECORD_BYTES,
    ApplicationContinuityError,
    ApplicationContinuityErrorCodeV1,
    ApplicationContinuityLeaseV1,
    ApplicationContinuityRecordV1,
    ApplicationContinuityStoreV1,
    ApplicationContinuitySummaryV1,
    MuxMemberContinuityV1,
    MuxSpaceContinuityV1,
    continuity_summary,
    decode_application_continuity_record,
    encode_application_continuity_record,
)
from .continuity_file import JsonFileApplicationContinuityStoreV1
from .ports import (
    HostedSessionEventListenerV1,
    HostedSessionPortV1,
    HostedSessionResolverV1,
)
from .runtime import AppServiceV1

__all__ = [
    "APPLICATION_CONTINUITY_VERSION",
    "MAX_APPLICATION_RECORDS",
    "MAX_CONTINUITY_RECORD_BYTES",
    "AppServiceV1",
    "ApplicationContinuityError",
    "ApplicationContinuityErrorCodeV1",
    "ApplicationContinuityLeaseV1",
    "ApplicationContinuityRecordV1",
    "ApplicationContinuityStoreV1",
    "ApplicationContinuitySummaryV1",
    "HostedSessionEventListenerV1",
    "HostedSessionPortV1",
    "HostedSessionResolverV1",
    "InProcessAppClientV1",
    "JsonFileApplicationContinuityStoreV1",
    "MuxMemberContinuityV1",
    "MuxSpaceContinuityV1",
    "continuity_summary",
    "decode_application_continuity_record",
    "encode_application_continuity_record",
]
