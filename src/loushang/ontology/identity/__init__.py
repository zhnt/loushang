"""Explicit deployment-scoped identity crosswalk contracts."""

from loushang.ontology.identity.model import (
    IDENTITY_CROSSWALK_FORMAT,
    IdentityCrosswalkSnapshot,
    IdentityResolution,
    IdentityResolutionStatus,
    SourceRecordIdentity,
)
from loushang.ontology.identity.ports import (
    IdentityResolutionError,
    IdentityResolver,
    require_confirmed_identity,
)

__all__ = [
    "IDENTITY_CROSSWALK_FORMAT",
    "IdentityCrosswalkSnapshot",
    "IdentityResolution",
    "IdentityResolutionError",
    "IdentityResolutionStatus",
    "IdentityResolver",
    "SourceRecordIdentity",
    "require_confirmed_identity",
]
