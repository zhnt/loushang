"""Portable data contracts for continuity discovery and activation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from loushang.foundation.json import JSONValue, require_json_mapping

ContinuitySort = Literal["updated", "created"]
ContinuityIndexState = Literal["fresh", "stale", "rebuilding", "unavailable", "unknown"]
ContinuityPreviewSectionKind = Literal["text", "key_value", "artifacts"]
ActivationDisposition = Literal["in_place", "relaunch", "new_window", "unsupported"]

MAX_CONTINUITY_PAGE_SIZE = 100
MAX_CONTINUITY_TEXT_LENGTH = 512
CONTINUITY_PROVIDER_PROFILE_VERSION = 1


def _nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_text(
    value: object,
    *,
    name: str,
    maximum: int = MAX_CONTINUITY_TEXT_LENGTH,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string or None")
    if len(value) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters")
    return value


def _unique_nonempty(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    result = tuple(values)
    for value in result:
        _nonempty(value, name=name)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} values must be unique")
    return result


@dataclass(frozen=True)
class ExperienceDescriptor:
    """Stable identity and Domain membership for one composed Product surface."""

    experience_id: str
    label: str
    domain_ids: tuple[str, ...]
    default_domain_id: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.experience_id, name="experience_id")
        _nonempty(self.label, name="experience label")
        domain_ids = _unique_nonempty(self.domain_ids, name="domain_id")
        if not domain_ids:
            raise ValueError("experience domain_ids must not be empty")
        if (
            self.default_domain_id is not None
            and self.default_domain_id not in domain_ids
        ):
            raise ValueError("default_domain_id must belong to domain_ids")
        object.__setattr__(self, "domain_ids", domain_ids)


@dataclass(frozen=True)
class ContinuityProviderDescriptor:
    """Admission-time metadata for one Product- or OEM-owned provider."""

    provider_id: str
    experience_id: str
    domain_ids: tuple[str, ...]
    label: str
    primary_domain_id: str | None = None
    supported_sorts: tuple[ContinuitySort, ...] = ("updated",)
    supports_startup: bool = True
    supports_in_place: bool = True
    implementation_version: int = 1
    profile_version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.provider_id, name="provider_id")
        _nonempty(self.experience_id, name="provider experience_id")
        _nonempty(self.label, name="provider label")
        domain_ids = _unique_nonempty(self.domain_ids, name="provider domain_id")
        if not domain_ids:
            raise ValueError("provider domain_ids must not be empty")
        if (
            self.primary_domain_id is not None
            and self.primary_domain_id not in domain_ids
        ):
            raise ValueError("primary_domain_id must belong to domain_ids")
        sorts = tuple(self.supported_sorts)
        if "updated" not in sorts:
            raise ValueError("providers must support the updated sort")
        if not sorts or len(set(sorts)) != len(sorts):
            raise ValueError("supported_sorts must be non-empty and unique")
        if any(sort not in {"updated", "created"} for sort in sorts):
            raise ValueError("supported_sorts contains an unknown common sort")
        if type(self.supports_startup) is not bool:
            raise TypeError("supports_startup must be a bool")
        if type(self.supports_in_place) is not bool:
            raise TypeError("supports_in_place must be a bool")
        if type(self.implementation_version) is not int:
            raise TypeError("implementation_version must be an integer")
        if type(self.profile_version) is not int:
            raise TypeError("profile_version must be an integer")
        if self.implementation_version < 1 or self.profile_version < 1:
            raise ValueError("provider versions must be at least 1")
        object.__setattr__(self, "domain_ids", domain_ids)
        object.__setattr__(self, "supported_sorts", sorts)


@dataclass(frozen=True)
class ContinuityTarget:
    provider_id: str
    opaque_id: str
    revision: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.provider_id, name="target provider_id")
        _nonempty(self.opaque_id, name="target opaque_id")
        if self.revision is not None:
            _nonempty(self.revision, name="target revision")


@dataclass(frozen=True)
class ContinuitySummary:
    """Fixed, deliberately small cross-product Resume envelope."""

    target: ContinuityTarget
    domain_ids: tuple[str, ...]
    primary_domain_id: str | None
    title: str
    updated_at: str
    created_at: str | None = None
    subtitle: str | None = None
    excerpt: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, ContinuityTarget):
            raise TypeError("summary target must be a ContinuityTarget")
        domain_ids = _unique_nonempty(self.domain_ids, name="summary domain_id")
        if not domain_ids:
            raise ValueError("summary domain_ids must not be empty")
        if (
            self.primary_domain_id is not None
            and self.primary_domain_id not in domain_ids
        ):
            raise ValueError("summary primary_domain_id must belong to domain_ids")
        _nonempty(self.title, name="summary title")
        if len(self.title) > MAX_CONTINUITY_TEXT_LENGTH:
            raise ValueError(
                f"summary title must be at most {MAX_CONTINUITY_TEXT_LENGTH} characters"
            )
        _nonempty(self.updated_at, name="summary updated_at")
        _optional_text(self.created_at, name="summary created_at")
        _optional_text(self.subtitle, name="summary subtitle")
        _optional_text(self.excerpt, name="summary excerpt")
        _optional_text(self.status, name="summary status")
        object.__setattr__(self, "domain_ids", domain_ids)


@dataclass(frozen=True)
class ContinuityQuery:
    text: str = ""
    provider_ids: tuple[str, ...] = ()
    domain_ids: tuple[str, ...] = ()
    sort_id: ContinuitySort = "updated"
    descending: bool = True
    page_size: int = 25
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("query text must be a string")
        if len(self.text) > MAX_CONTINUITY_TEXT_LENGTH:
            raise ValueError(
                f"query text must be at most {MAX_CONTINUITY_TEXT_LENGTH} characters"
            )
        object.__setattr__(
            self,
            "provider_ids",
            _unique_nonempty(self.provider_ids, name="query provider_id"),
        )
        object.__setattr__(
            self,
            "domain_ids",
            _unique_nonempty(self.domain_ids, name="query domain_id"),
        )
        if self.sort_id not in {"updated", "created"}:
            raise ValueError("query sort_id must be updated or created")
        if type(self.descending) is not bool:
            raise TypeError("query descending must be a bool")
        if type(self.page_size) is not int:
            raise TypeError("query page_size must be an integer")
        if not 1 <= self.page_size <= MAX_CONTINUITY_PAGE_SIZE:
            raise ValueError(
                f"query page_size must be between 1 and {MAX_CONTINUITY_PAGE_SIZE}"
            )
        if self.cursor is not None:
            _nonempty(self.cursor, name="query cursor")


@dataclass(frozen=True)
class ProviderQuery:
    text: str
    sort_id: ContinuitySort
    descending: bool
    limit: int
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("provider query text must be a string")
        if self.sort_id not in {"updated", "created"}:
            raise ValueError("provider query sort_id must be updated or created")
        if type(self.descending) is not bool:
            raise TypeError("provider query descending must be a bool")
        if (
            type(self.limit) is not int
            or not 1 <= self.limit <= MAX_CONTINUITY_PAGE_SIZE
        ):
            raise ValueError(
                f"provider query limit must be between 1 and {MAX_CONTINUITY_PAGE_SIZE}"
            )


@dataclass(frozen=True)
class ContinuityDiagnostic:
    code: str
    message: str
    provider_id: str | None = None
    details: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonempty(self.code, name="diagnostic code")
        _nonempty(self.message, name="diagnostic message")
        if self.provider_id is not None:
            _nonempty(self.provider_id, name="diagnostic provider_id")
        object.__setattr__(
            self,
            "details",
            require_json_mapping(dict(self.details), name="diagnostic details"),
        )


@dataclass(frozen=True)
class ProviderPageItem:
    summary: ContinuitySummary
    after_cursor: str

    def __post_init__(self) -> None:
        if not isinstance(self.summary, ContinuitySummary):
            raise TypeError("provider page item summary must be a ContinuitySummary")
        _nonempty(self.after_cursor, name="provider item after_cursor")


@dataclass(frozen=True)
class ProviderPage:
    items: tuple[ProviderPageItem, ...]
    has_more: bool
    index_state: ContinuityIndexState
    index_generation: str
    query_snapshot: str
    diagnostics: tuple[ContinuityDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        items = tuple(self.items)
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, ProviderPageItem) for item in items):
            raise TypeError("provider page items must contain ProviderPageItem values")
        if type(self.has_more) is not bool:
            raise TypeError("provider page has_more must be a bool")
        if self.index_state not in {
            "fresh",
            "stale",
            "rebuilding",
            "unavailable",
            "unknown",
        }:
            raise ValueError("provider page index_state is invalid")
        _nonempty(self.index_generation, name="provider index_generation")
        _nonempty(self.query_snapshot, name="provider query_snapshot")
        if any(
            not isinstance(diagnostic, ContinuityDiagnostic)
            for diagnostic in diagnostics
        ):
            raise TypeError(
                "provider page diagnostics must contain ContinuityDiagnostic values"
            )
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "diagnostics", diagnostics)


@dataclass(frozen=True)
class ProviderPageState:
    index_state: ContinuityIndexState
    index_generation: str
    query_snapshot: str
    diagnostic: ContinuityDiagnostic | None = None


@dataclass(frozen=True)
class ContinuityPage:
    items: tuple[ContinuitySummary, ...]
    next_cursor: str | None
    provider_diagnostics: tuple[ContinuityDiagnostic, ...]
    partial: bool
    ordering_complete: bool
    provider_states: dict[str, ProviderPageState]
    aggregate_index_state: ContinuityIndexState
    restart_required: bool = False


@dataclass(frozen=True)
class ContinuityArtifactReference:
    label: str
    reference: str

    def __post_init__(self) -> None:
        _nonempty(self.label, name="artifact label")
        _nonempty(self.reference, name="artifact reference")


@dataclass(frozen=True)
class ContinuityPreviewSection:
    kind: ContinuityPreviewSectionKind
    title: str | None = None
    text: str | None = None
    rows: tuple[tuple[str, str], ...] = ()
    artifacts: tuple[ContinuityArtifactReference, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"text", "key_value", "artifacts"}:
            raise ValueError("preview section kind is invalid")
        _optional_text(self.title, name="preview section title")
        _optional_text(self.text, name="preview section text", maximum=4096)
        rows = tuple(self.rows)
        artifacts = tuple(self.artifacts)
        if len(rows) > 50 or len(artifacts) > 50:
            raise ValueError("preview sections may contain at most 50 entries")
        for key, value in rows:
            _nonempty(key, name="preview row key")
            if not isinstance(value, str):
                raise TypeError("preview row values must be strings")
        if any(
            not isinstance(artifact, ContinuityArtifactReference)
            for artifact in artifacts
        ):
            raise TypeError(
                "preview artifacts must contain ContinuityArtifactReference values"
            )
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "artifacts", artifacts)


@dataclass(frozen=True)
class ContinuityPreview:
    target: ContinuityTarget
    revision: str | None
    heading: str
    sections: tuple[ContinuityPreviewSection, ...]
    stale: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.target, ContinuityTarget):
            raise TypeError("preview target must be a ContinuityTarget")
        _nonempty(self.heading, name="preview heading")
        sections = tuple(self.sections)
        if len(sections) > 20:
            raise ValueError("preview may contain at most 20 sections")
        if any(
            not isinstance(section, ContinuityPreviewSection) for section in sections
        ):
            raise TypeError(
                "preview sections must contain ContinuityPreviewSection values"
            )
        if type(self.stale) is not bool:
            raise TypeError("preview stale must be a bool")
        object.__setattr__(self, "sections", sections)


__all__ = [
    "ActivationDisposition",
    "ContinuityArtifactReference",
    "ContinuityDiagnostic",
    "ContinuityIndexState",
    "ContinuityPage",
    "ContinuityPreview",
    "ContinuityPreviewSection",
    "ContinuityPreviewSectionKind",
    "ContinuityProviderDescriptor",
    "ContinuityQuery",
    "ContinuitySort",
    "ContinuitySummary",
    "ContinuityTarget",
    "ExperienceDescriptor",
    "MAX_CONTINUITY_PAGE_SIZE",
    "MAX_CONTINUITY_TEXT_LENGTH",
    "ProviderPage",
    "ProviderPageItem",
    "ProviderPageState",
    "ProviderQuery",
]
