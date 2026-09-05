"""Closed failure vocabulary for Product-neutral AppHost contracts."""

from __future__ import annotations

import re
from enum import Enum

_FIELD = re.compile(r"[a-z][a-z0-9._]{0,127}\Z")


class AppHostFailureCategory(str, Enum):
    """Stable AppHost failure categories without Product or transport detail."""

    INVALID_CONTRACT = "invalid_contract"
    PRODUCT_IDENTITY_REQUIRED = "product_identity_required"
    PRODUCT_UNAVAILABLE = "product_unavailable"
    PRODUCT_INCOMPATIBLE = "product_incompatible"
    PROFILE_UNAVAILABLE = "profile_unavailable"
    SESSION_AMBIGUOUS = "session_ambiguous"
    SESSION_CANDIDATE_STALE = "session_candidate_stale"
    GENERATION_RETIRED = "generation_retired"
    GENERATION_CONFLICT = "generation_conflict"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    CLEANUP_INCOMPLETE = "cleanup_incomplete"


class InvalidAppHostContractReason(str, Enum):
    """Closed, payload-free reasons for local A0 contract rejection."""

    CANONICAL_ENVELOPE_REQUIRED = "canonical_envelope_required"
    MIGRATION_ENVELOPE_FORBIDDEN = "migration_envelope_forbidden"
    PROFILE_REFERENCE_MISSING = "profile_reference_missing"
    FAILURE_CATEGORY_REQUIRED = "failure_category_required"
    FAILURE_CATEGORY_UNEXPECTED = "failure_category_unexpected"
    CONTRACT_VERSION_MISMATCH = "contract_version_mismatch"
    ADMISSION_GENERATION_MISMATCH = "admission_generation_mismatch"
    ADMISSION_SUBJECT_MISMATCH = "admission_subject_mismatch"
    STABLE_ID_REQUIRED = "stable_id_required"
    BOUNDED_TEXT_REQUIRED = "bounded_text_required"
    CONTROL_CHARACTER_FORBIDDEN = "control_character_forbidden"
    OPAQUE_TOKEN_REQUIRED = "opaque_token_required"
    ENUM_VALUE_REQUIRED = "enum_value_required"
    INSTANCE_REQUIRED = "instance_required"
    NATIVE_ASYNC_METHOD_REQUIRED = "native_async_method_required"
    IMMUTABLE_TUPLE_REQUIRED = "immutable_tuple_required"
    ITEM_COUNT_INVALID = "item_count_invalid"
    DUPLICATE_ITEM = "duplicate_item"


class AppHostError(Exception):
    """Base typed AppHost failure whose message derives from a closed category."""

    def __init__(self, category: AppHostFailureCategory) -> None:
        if not isinstance(category, AppHostFailureCategory):
            raise TypeError("category must be an AppHostFailureCategory")
        self.category = category
        super().__init__(category.value)


class InvalidAppHostContractError(AppHostError, ValueError):
    """An immutable A0 contract value failed exact local validation."""

    def __init__(self, field: str, reason: InvalidAppHostContractReason) -> None:
        if not isinstance(field, str) or _FIELD.fullmatch(field) is None:
            raise TypeError("field must be a bounded stable field name")
        if not isinstance(reason, InvalidAppHostContractReason):
            raise TypeError("reason must be an InvalidAppHostContractReason")
        self.field = field
        self.reason = reason
        super().__init__(AppHostFailureCategory.INVALID_CONTRACT)
        self.args = (f"invalid AppHost contract field {field!r}; {reason.value}",)
