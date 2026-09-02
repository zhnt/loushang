"""Revisioned Product default Tool profiles and scoped contributors."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from threading import RLock
from typing import TypeVar
from weakref import WeakKeyDictionary


class StaleDefaultProfileRevisionError(RuntimeError):
    """Raised when a profile or contribution expectation is stale."""


@dataclass(frozen=True)
class DefaultToolProfileSnapshot:
    """One exact, Product-owned default Tool profile revision."""

    profile_id: str
    profile_revision: int
    static_default_names: tuple[str, ...]
    automatic_selection_policy_fingerprint: str
    automatic_selection_enabled: bool
    automatic_selection_excluded_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.profile_id, "profile_id")
        _require_non_negative(self.profile_revision, "profile_revision")
        object.__setattr__(
            self,
            "static_default_names",
            _unique_tool_names(self.static_default_names),
        )
        _require_non_empty(
            self.automatic_selection_policy_fingerprint,
            "automatic_selection_policy_fingerprint",
        )
        if type(self.automatic_selection_enabled) is not bool:
            raise TypeError("automatic_selection_enabled must be a bool")
        object.__setattr__(
            self,
            "automatic_selection_excluded_names",
            _unique_tool_names(self.automatic_selection_excluded_names),
        )


@dataclass(frozen=True)
class DefaultToolProfileContributionSnapshot:
    namespace: str
    contributor_id: str
    contribution_revision: int
    static_default_names: tuple[str, ...]
    published: bool

    def __post_init__(self) -> None:
        _require_non_empty(self.namespace, "namespace")
        _require_non_empty(self.contributor_id, "contributor_id")
        _require_non_negative(
            self.contribution_revision,
            "contribution_revision",
        )
        object.__setattr__(
            self,
            "static_default_names",
            _unique_tool_names(self.static_default_names),
        )
        if type(self.published) is not bool:
            raise TypeError("published must be a bool")


@dataclass(frozen=True)
class DefaultToolProfileChange:
    previous: DefaultToolProfileSnapshot
    current: DefaultToolProfileSnapshot
    contribution: DefaultToolProfileContributionSnapshot
    _receipt_token: _ProfilePublicationReceipt = field(repr=False, compare=False)


@dataclass(frozen=True)
class DefaultToolProfilePolicyChange:
    """One assembler-issued automatic-selection policy migration."""

    previous: DefaultToolProfileSnapshot
    current: DefaultToolProfileSnapshot
    _receipt_token: _ProfilePublicationReceipt = field(repr=False, compare=False)


ProfilePublicationT = TypeVar(
    "ProfilePublicationT",
    DefaultToolProfileChange,
    DefaultToolProfilePolicyChange,
)


class _ProfilePublicationReceipt:
    """Weakly tracked, per-publication assembler authority."""


class DefaultToolProfileAssembler:
    """Sole complete-truth assembler for namespace-bound Product fragments."""

    def __init__(
        self,
        *,
        profile_id: str,
        namespace_order: Iterable[str],
        automatic_selection_policy_fingerprint: str,
        automatic_selection_enabled: bool,
        automatic_selection_excluded_names: Iterable[str] = (),
    ) -> None:
        _require_non_empty(profile_id, "profile_id")
        namespaces = _unique_identifiers(namespace_order, "namespace")
        if not namespaces:
            raise ValueError("namespace_order must not be empty")
        _require_non_empty(
            automatic_selection_policy_fingerprint,
            "automatic_selection_policy_fingerprint",
        )
        if type(automatic_selection_enabled) is not bool:
            raise TypeError("automatic_selection_enabled must be a bool")
        excluded_names = _unique_tool_names(automatic_selection_excluded_names)
        self._profile_id = profile_id
        self._namespace_order = namespaces
        self._policy_fingerprint = automatic_selection_policy_fingerprint
        self._automatic_selection_enabled = automatic_selection_enabled
        self._automatic_selection_excluded_names = excluded_names
        self._lock = RLock()
        self._profile_revision = 0
        self._contributor_order: dict[tuple[str, str], int] = {}
        self._contributor_tokens: dict[tuple[str, str], object] = {}
        self._contributions: dict[
            tuple[str, str], DefaultToolProfileContributionSnapshot
        ] = {}
        self._issued_publications: WeakKeyDictionary[
            _ProfilePublicationReceipt, tuple[object, ...]
        ] = WeakKeyDictionary()

    def snapshot(self) -> DefaultToolProfileSnapshot:
        with self._lock:
            return self._assembled_snapshot()

    def contributor(
        self,
        *,
        namespace: str,
        contributor_id: str,
    ) -> ToolDefaultProfileContributorHandle:
        _require_non_empty(namespace, "namespace")
        _require_non_empty(contributor_id, "contributor_id")
        if namespace not in self._namespace_order:
            raise ValueError(f"unknown default-profile namespace: {namespace}")
        key = (namespace, contributor_id)
        with self._lock:
            if key not in self._contributor_order:
                self._contributor_order[key] = len(self._contributor_order)
                self._contributor_tokens[key] = object()
            token = self._contributor_tokens[key]
        return ToolDefaultProfileContributorHandle._issued(self, key, token)

    def migrate_automatic_selection_policy(
        self,
        *,
        automatic_selection_policy_fingerprint: str,
        automatic_selection_enabled: bool,
        expected_profile_revision: int,
        automatic_selection_excluded_names: Iterable[str] | None = None,
    ) -> DefaultToolProfilePolicyChange:
        """Atomically migrate Product policy on the assembler revision stream."""

        _require_non_empty(
            automatic_selection_policy_fingerprint,
            "automatic_selection_policy_fingerprint",
        )
        if type(automatic_selection_enabled) is not bool:
            raise TypeError("automatic_selection_enabled must be a bool")
        with self._lock:
            excluded_names = (
                self._automatic_selection_excluded_names
                if automatic_selection_excluded_names is None
                else _unique_tool_names(automatic_selection_excluded_names)
            )
            self._expect_profile_revision(expected_profile_revision)
            previous = self._assembled_snapshot()
            if (
                automatic_selection_policy_fingerprint == self._policy_fingerprint
                and automatic_selection_enabled == self._automatic_selection_enabled
                and excluded_names == self._automatic_selection_excluded_names
            ):
                return self._issue_publication(
                    DefaultToolProfilePolicyChange(
                        previous=previous,
                        current=previous,
                        _receipt_token=_ProfilePublicationReceipt(),
                    )
                )
            next_revision = self._profile_revision + 1
            current = self._assembled_snapshot(
                profile_revision=next_revision,
                policy_fingerprint=automatic_selection_policy_fingerprint,
                automatic_selection_enabled=automatic_selection_enabled,
                automatic_selection_excluded_names=excluded_names,
            )
            self._policy_fingerprint = automatic_selection_policy_fingerprint
            self._automatic_selection_enabled = automatic_selection_enabled
            self._automatic_selection_excluded_names = excluded_names
            self._profile_revision = next_revision
            return self._issue_publication(
                DefaultToolProfilePolicyChange(
                    previous=previous,
                    current=current,
                    _receipt_token=_ProfilePublicationReceipt(),
                )
            )

    def _replace_contribution(
        self,
        key: tuple[str, str],
        token: object,
        names: Iterable[str],
        *,
        expected_revision: int,
    ) -> DefaultToolProfileChange:
        supplied = _unique_tool_names(names)
        with self._lock:
            self._validate_contributor_grant(key, token)
            previous_contribution = self._contributions.get(key)
            current_revision = (
                previous_contribution.contribution_revision
                if previous_contribution is not None
                else 0
            )
            self._expect_contribution_revision(expected_revision, current_revision)
            previous_profile = self._assembled_snapshot()
            if (
                previous_contribution is not None
                and previous_contribution.published
                and previous_contribution.static_default_names == supplied
            ):
                return self._issue_publication(
                    DefaultToolProfileChange(
                        previous=previous_profile,
                        current=previous_profile,
                        contribution=previous_contribution,
                        _receipt_token=_ProfilePublicationReceipt(),
                    )
                )
            contribution = DefaultToolProfileContributionSnapshot(
                namespace=key[0],
                contributor_id=key[1],
                contribution_revision=current_revision + 1,
                static_default_names=supplied,
                published=True,
            )
            candidate = dict(self._contributions)
            candidate[key] = contribution
            self._validate_no_conflicts(candidate)
            next_revision = self._profile_revision + 1
            current_profile = self._assembled_snapshot(
                contributions=candidate,
                profile_revision=next_revision,
            )
            self._contributions = candidate
            self._profile_revision = next_revision
            return self._issue_publication(
                DefaultToolProfileChange(
                    previous=previous_profile,
                    current=current_profile,
                    contribution=contribution,
                    _receipt_token=_ProfilePublicationReceipt(),
                )
            )

    def _withdraw_contribution(
        self,
        key: tuple[str, str],
        token: object,
        *,
        expected_revision: int,
    ) -> DefaultToolProfileChange:
        with self._lock:
            self._validate_contributor_grant(key, token)
            previous_contribution = self._contributions.get(key)
            current_revision = (
                previous_contribution.contribution_revision
                if previous_contribution is not None
                else 0
            )
            self._expect_contribution_revision(expected_revision, current_revision)
            previous_profile = self._assembled_snapshot()
            if previous_contribution is None or not previous_contribution.published:
                contribution = previous_contribution or (
                    DefaultToolProfileContributionSnapshot(
                        namespace=key[0],
                        contributor_id=key[1],
                        contribution_revision=0,
                        static_default_names=(),
                        published=False,
                    )
                )
                return self._issue_publication(
                    DefaultToolProfileChange(
                        previous=previous_profile,
                        current=previous_profile,
                        contribution=contribution,
                        _receipt_token=_ProfilePublicationReceipt(),
                    )
                )
            contribution = DefaultToolProfileContributionSnapshot(
                namespace=key[0],
                contributor_id=key[1],
                contribution_revision=current_revision + 1,
                static_default_names=(),
                published=False,
            )
            candidate = {**self._contributions, key: contribution}
            next_revision = self._profile_revision + 1
            current_profile = self._assembled_snapshot(
                contributions=candidate,
                profile_revision=next_revision,
            )
            self._contributions = candidate
            self._profile_revision = next_revision
            return self._issue_publication(
                DefaultToolProfileChange(
                    previous=previous_profile,
                    current=current_profile,
                    contribution=contribution,
                    _receipt_token=_ProfilePublicationReceipt(),
                )
            )

    def _validate_publication(
        self,
        publication: DefaultToolProfileChange | DefaultToolProfilePolicyChange,
    ) -> None:
        with self._lock:
            issued_payload = self._issued_publications.get(
                publication._receipt_token
            )
            if issued_payload != _publication_payload(publication):
                raise PermissionError(
                    "default-profile publication was not issued by this assembler"
                )

    def _issue_publication(
        self,
        publication: ProfilePublicationT,
    ) -> ProfilePublicationT:
        self._issued_publications[publication._receipt_token] = _publication_payload(
            publication
        )
        return publication

    def _assembled_snapshot(
        self,
        *,
        contributions: dict[
            tuple[str, str], DefaultToolProfileContributionSnapshot
        ]
        | None = None,
        profile_revision: int | None = None,
        policy_fingerprint: str | None = None,
        automatic_selection_enabled: bool | None = None,
        automatic_selection_excluded_names: tuple[str, ...] | None = None,
    ) -> DefaultToolProfileSnapshot:
        source = self._contributions if contributions is None else contributions
        ordered = sorted(
            (
                (key, contribution)
                for key, contribution in source.items()
                if contribution.published
            ),
            key=lambda item: (
                self._namespace_order.index(item[0][0]),
                self._contributor_order[item[0]],
            ),
        )
        return DefaultToolProfileSnapshot(
            profile_id=self._profile_id,
            profile_revision=(
                self._profile_revision
                if profile_revision is None
                else profile_revision
            ),
            static_default_names=tuple(
                name
                for _key, contribution in ordered
                for name in contribution.static_default_names
            ),
            automatic_selection_policy_fingerprint=(
                self._policy_fingerprint
                if policy_fingerprint is None
                else policy_fingerprint
            ),
            automatic_selection_enabled=(
                self._automatic_selection_enabled
                if automatic_selection_enabled is None
                else automatic_selection_enabled
            ),
            automatic_selection_excluded_names=(
                self._automatic_selection_excluded_names
                if automatic_selection_excluded_names is None
                else automatic_selection_excluded_names
            ),
        )

    def _validate_contributor_grant(
        self,
        key: tuple[str, str],
        token: object,
    ) -> None:
        if self._contributor_tokens.get(key) is not token:
            raise PermissionError("invalid default-profile contributor capability")

    def _expect_profile_revision(self, expected: int) -> None:
        if expected != self._profile_revision:
            raise StaleDefaultProfileRevisionError(
                "default profile revision changed: "
                f"expected {expected}, found {self._profile_revision}"
            )

    @staticmethod
    def _expect_contribution_revision(expected: int, current: int) -> None:
        if expected != current:
            raise StaleDefaultProfileRevisionError(
                "default-profile contribution revision changed: "
                f"expected {expected}, found {current}"
            )

    @staticmethod
    def _validate_no_conflicts(
        contributions: dict[
            tuple[str, str], DefaultToolProfileContributionSnapshot
        ],
    ) -> None:
        owners: dict[str, tuple[str, str]] = {}
        for key, contribution in contributions.items():
            if not contribution.published:
                continue
            for name in contribution.static_default_names:
                previous = owners.get(name)
                if previous is not None and previous != key:
                    raise ValueError(
                        f"default Tool Name {name!r} is contributed by both "
                        f"{previous!r} and {key!r}"
                    )
                owners[name] = key


class ToolDefaultProfileContributorHandle:
    """A namespace/contributor-bound profile mutation capability."""

    def __init__(
        self,
        assembler: DefaultToolProfileAssembler,
        key: tuple[str, str],
        token: object,
    ) -> None:
        self._assembler = assembler
        self._key = key
        self._token = token

    @classmethod
    def _issued(
        cls,
        assembler: DefaultToolProfileAssembler,
        key: tuple[str, str],
        token: object,
    ) -> ToolDefaultProfileContributorHandle:
        return cls(assembler, key, token)

    def replace_contribution(
        self,
        names: Iterable[str],
        *,
        expected_revision: int,
    ) -> DefaultToolProfileChange:
        return self._assembler._replace_contribution(
            self._key,
            self._token,
            names,
            expected_revision=expected_revision,
        )

    def withdraw_contribution(
        self,
        *,
        expected_revision: int,
    ) -> DefaultToolProfileChange:
        return self._assembler._withdraw_contribution(
            self._key,
            self._token,
            expected_revision=expected_revision,
        )


def _publication_payload(
    publication: DefaultToolProfileChange | DefaultToolProfilePolicyChange,
) -> tuple[object, ...]:
    if isinstance(publication, DefaultToolProfileChange):
        return (
            DefaultToolProfileChange,
            _profile_payload(publication.previous),
            _profile_payload(publication.current),
            (
                publication.contribution.namespace,
                publication.contribution.contributor_id,
                publication.contribution.contribution_revision,
                publication.contribution.static_default_names,
                publication.contribution.published,
            ),
        )
    return (
        DefaultToolProfilePolicyChange,
        _profile_payload(publication.previous),
        _profile_payload(publication.current),
    )


def _profile_payload(snapshot: DefaultToolProfileSnapshot) -> tuple[object, ...]:
    return (
        snapshot.profile_id,
        snapshot.profile_revision,
        snapshot.static_default_names,
        snapshot.automatic_selection_policy_fingerprint,
        snapshot.automatic_selection_enabled,
        snapshot.automatic_selection_excluded_names,
    )


def _unique_tool_names(names: Iterable[str]) -> tuple[str, ...]:
    return _unique_identifiers(names, "Tool Name")


def _unique_identifiers(values: Iterable[str], label: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{label} values must be an iterable, not one string")
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"{label} values must be strings")
        if not value:
            raise ValueError(f"{label} values must be non-empty strings")
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return tuple(unique)


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_non_negative(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


__all__ = [
    "DefaultToolProfileAssembler",
    "DefaultToolProfileChange",
    "DefaultToolProfileContributionSnapshot",
    "DefaultToolProfilePolicyChange",
    "DefaultToolProfileSnapshot",
    "StaleDefaultProfileRevisionError",
    "ToolDefaultProfileContributorHandle",
]
