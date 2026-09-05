"""Closed failure vocabulary for Product-neutral AppHost contracts."""

from __future__ import annotations

import re
from collections.abc import Callable
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
    BOOLEAN_REQUIRED = "boolean_required"
    TIMEOUT_INVALID = "timeout_invalid"
    COMPLETION_MISMATCH = "completion_mismatch"


class AppHostError(Exception):
    """Base typed AppHost failure whose message derives from a closed category."""

    def __init__(self, category: AppHostFailureCategory) -> None:
        if not isinstance(category, AppHostFailureCategory):
            raise TypeError("category must be an AppHostFailureCategory")
        self.category = category
        super().__init__(category.value)


class ProductIdentityRequiredError(AppHostError):
    """A route omitted its explicit Product identity."""

    def __init__(self) -> None:
        super().__init__(AppHostFailureCategory.PRODUCT_IDENTITY_REQUIRED)


class ProductUnavailableError(AppHostError):
    """The explicitly selected Product is absent from the active generation."""

    def __init__(self) -> None:
        super().__init__(AppHostFailureCategory.PRODUCT_UNAVAILABLE)


class ProductIncompatibleError(AppHostError):
    """The selected Product cannot open the persisted compatibility identity."""

    def __init__(self) -> None:
        super().__init__(AppHostFailureCategory.PRODUCT_INCOMPATIBLE)


class SessionAmbiguousError(AppHostError):
    """More than one non-equivalent Session candidate claims one identity."""

    def __init__(self) -> None:
        super().__init__(AppHostFailureCategory.SESSION_AMBIGUOUS)


class SessionCandidateStaleError(AppHostError):
    """A request-bound Session candidate changed before its final fence."""

    def __init__(self) -> None:
        super().__init__(AppHostFailureCategory.SESSION_CANDIDATE_STALE)


class GenerationRetiredError(AppHostError):
    """The selected immutable catalog generation no longer admits routes."""

    def __init__(self) -> None:
        super().__init__(AppHostFailureCategory.GENERATION_RETIRED)


class GenerationConflictError(AppHostError):
    """A catalog replacement or returned admission identity failed its CAS."""

    def __init__(self) -> None:
        super().__init__(AppHostFailureCategory.GENERATION_CONFLICT)


class CleanupIncompleteError(AppHostError):
    """An AppHost-owned resource could not be settled deterministically."""

    def __init__(
        self,
        *,
        primary_category: AppHostFailureCategory | None = None,
        cleanup_debt_count: int = 1,
    ) -> None:
        if primary_category is not None and not isinstance(
            primary_category, AppHostFailureCategory
        ):
            raise TypeError("primary_category must be an AppHostFailureCategory")
        if type(cleanup_debt_count) is not int or cleanup_debt_count < 1:
            raise ValueError("cleanup_debt_count must be positive")
        self.primary_category = primary_category
        self.cleanup_debt_count = cleanup_debt_count
        super().__init__(AppHostFailureCategory.CLEANUP_INCOMPLETE)


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


def redacted_apphost_error(category: AppHostFailureCategory) -> AppHostError:
    """Construct the canonical payload-free error for one closed category."""

    constructors: dict[AppHostFailureCategory, Callable[[], AppHostError]] = {
        AppHostFailureCategory.PRODUCT_IDENTITY_REQUIRED: ProductIdentityRequiredError,
        AppHostFailureCategory.PRODUCT_UNAVAILABLE: ProductUnavailableError,
        AppHostFailureCategory.PRODUCT_INCOMPATIBLE: ProductIncompatibleError,
        AppHostFailureCategory.SESSION_AMBIGUOUS: SessionAmbiguousError,
        AppHostFailureCategory.SESSION_CANDIDATE_STALE: SessionCandidateStaleError,
        AppHostFailureCategory.GENERATION_RETIRED: GenerationRetiredError,
        AppHostFailureCategory.GENERATION_CONFLICT: GenerationConflictError,
        AppHostFailureCategory.CLEANUP_INCOMPLETE: CleanupIncompleteError,
    }
    constructor = constructors.get(category)
    return AppHostError(category) if constructor is None else constructor()


__all__ = [
    "AppHostError",
    "AppHostFailureCategory",
    "CleanupIncompleteError",
    "GenerationConflictError",
    "GenerationRetiredError",
    "InvalidAppHostContractError",
    "InvalidAppHostContractReason",
    "ProductIdentityRequiredError",
    "ProductIncompatibleError",
    "ProductUnavailableError",
    "SessionAmbiguousError",
    "SessionCandidateStaleError",
]
