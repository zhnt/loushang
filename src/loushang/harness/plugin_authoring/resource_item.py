"""Strict inert authoring codec for one Plugin-contributed Resource Item."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, NoReturn, cast

from loushang.harness.plugin_authoring.reservations import (
    _authoring_reservation_view,
    _PluginAuthoringReservationView,
)
from loushang.harness.resources.plugins.declarations import (
    PluginDeclaration,
    PluginDeclarationCodecError,
    _document_digest,
    _require_identifier,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionError,
    VerifiedRevisionHandle,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionCandidate,
    PluginDeclarationSourceGroup,
)

RESOURCE_ITEM_DECLARATION_PAYLOAD_VERSION = 1

ResourceItemKind = Literal[
    "asset",
    "method",
    "prompt",
    "skill",
    "source",
    "theme",
]
ResourceItemLocatorKind = Literal["directory", "file"]

_RESOURCE_ITEM_KINDS = frozenset(
    {"asset", "method", "prompt", "skill", "source", "theme"}
)
_RESOURCE_ITEM_LOCATOR_KINDS = frozenset({"directory", "file"})
_MEDIA_TYPE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*"
)


@dataclass(frozen=True, slots=True)
class ResourceItemDeclarationPayload:
    """Owner-versioned Resource subtype over one immutable package locator."""

    locator: str
    locator_kind: ResourceItemLocatorKind
    media_type: str
    owner_namespace: str
    resource_kind: ResourceItemKind
    schema_id: str
    schema_version: int
    payload_version: int = RESOURCE_ITEM_DECLARATION_PAYLOAD_VERSION

    def __post_init__(self) -> None:
        if self.payload_version != RESOURCE_ITEM_DECLARATION_PAYLOAD_VERSION:
            raise ValueError("Unsupported Resource Item declaration payload version")
        if self.resource_kind not in _RESOURCE_ITEM_KINDS:
            raise ValueError("Unsupported Resource Item kind")
        if self.locator_kind not in _RESOURCE_ITEM_LOCATOR_KINDS:
            raise ValueError("Unsupported Resource Item locator kind")
        locator = canonical_plugin_relative_path(self.locator)
        _require_identifier(self.owner_namespace, name="Resource owner namespace")
        if not isinstance(self.media_type, str) or not _MEDIA_TYPE.fullmatch(
            self.media_type
        ):
            raise ValueError("Resource Item media type must be canonical")
        _require_identifier(self.schema_id, name="Resource Item schema id")
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version <= 0
        ):
            raise ValueError("Resource Item schema version must be positive")
        _validate_locator_shape(
            self.resource_kind,
            locator=locator,
            locator_kind=self.locator_kind,
        )
        object.__setattr__(self, "locator", locator.as_posix())

    @property
    def relative_path(self) -> PurePosixPath:
        return PurePosixPath(self.locator)

    @property
    def fingerprint(self) -> str:
        return _document_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "locator": self.locator,
            "locatorKind": self.locator_kind,
            "mediaType": self.media_type,
            "ownerNamespace": self.owner_namespace,
            "payloadVersion": self.payload_version,
            "resourceKind": self.resource_kind,
            "schemaId": self.schema_id,
            "schemaVersion": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> ResourceItemDeclarationPayload:
        if not isinstance(value, dict):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Resource Item declaration payload must be an object",
            )
        version = value.get("payloadVersion")
        if version is None:
            _raise_codec(
                "unsupported_resource_item_declaration_payload_version",
                "Resource Item declaration payload version is missing",
            )
        if not isinstance(version, int) or isinstance(version, bool):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Resource Item declaration payload version must be an integer",
            )
        if version != RESOURCE_ITEM_DECLARATION_PAYLOAD_VERSION:
            _raise_codec(
                "unsupported_resource_item_declaration_payload_version",
                "Unsupported Resource Item declaration payload version",
            )
        resource_kind = value.get("resourceKind")
        if resource_kind is not None and not isinstance(resource_kind, str):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Resource Item kind must be a string",
            )
        if isinstance(resource_kind, str) and resource_kind not in _RESOURCE_ITEM_KINDS:
            _raise_codec(
                "unsupported_resource_item_kind",
                "Unsupported Resource Item kind",
            )
        locator_kind = value.get("locatorKind")
        if locator_kind is not None and not isinstance(locator_kind, str):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Resource Item locator kind must be a string",
            )
        if isinstance(locator_kind, str) and (
            locator_kind not in _RESOURCE_ITEM_LOCATOR_KINDS
        ):
            _raise_codec(
                "unsupported_resource_item_locator_kind",
                "Unsupported Resource Item locator kind",
            )
        expected_fields = {
            "locator",
            "locatorKind",
            "mediaType",
            "ownerNamespace",
            "payloadVersion",
            "resourceKind",
            "schemaId",
            "schemaVersion",
        }
        if set(value) != expected_fields:
            _raise_codec(
                "plugin_declaration_exact_field_mismatch",
                "Resource Item declaration payload fields do not match",
            )
        locator = value["locator"]
        media_type = value["mediaType"]
        owner_namespace = value["ownerNamespace"]
        schema_id = value["schemaId"]
        schema_version = value["schemaVersion"]
        if not all(
            isinstance(item, str)
            for item in (locator, media_type, owner_namespace, schema_id)
        ):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Resource Item string fields have an invalid type",
            )
        if not isinstance(resource_kind, str) or not isinstance(locator_kind, str):
            _raise_codec(
                "plugin_declaration_exact_field_mismatch",
                "Resource Item union tags are required",
            )
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Resource Item schema version must be an integer",
            )
        try:
            return cls(
                locator=cast(str, locator),
                locator_kind=cast(ResourceItemLocatorKind, locator_kind),
                media_type=cast(str, media_type),
                owner_namespace=cast(str, owner_namespace),
                resource_kind=cast(ResourceItemKind, resource_kind),
                schema_id=cast(str, schema_id),
                schema_version=schema_version,
                payload_version=version,
            )
        except (TypeError, ValueError) as exc:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                f"Invalid Resource Item declaration payload: {exc}",
                cause=exc,
            )

    @classmethod
    def from_candidate(
        cls,
        candidate: PluginContributionCandidate,
    ) -> ResourceItemDeclarationPayload:
        """Resolve payload against one evidenced package-bound Candidate."""

        if not isinstance(candidate, PluginContributionCandidate):
            raise TypeError("Resource Item codec requires a Plugin Candidate")
        declaration = candidate.declaration
        contributions = {
            item.contribution_id: item
            for item in candidate.package.contribution_index.items
        }
        contribution = contributions.get(declaration.contribution_id)
        if contribution is None:
            _raise_cross_field("Resource Item Candidate has no package reservation")
        if (
            declaration.plugin_id != candidate.package.manifest.name
            or declaration.kind != contribution.kind
            or declaration.owner != contribution.owner
            or declaration.reservation_fingerprint != contribution.fingerprint
            or declaration.source_descriptor_fingerprint
            != contribution.source_descriptor_fingerprint
            or declaration.source_kind != contribution.declaration_source.kind
        ):
            _raise_cross_field(
                "Resource Item Candidate does not match its package reservation"
            )
        payload = _payload_from_declaration(declaration)
        _validate_resource_item_contribution(
            payload,
            owner=contribution.owner,
            contribution_kind=contribution.kind,
            execution_model=contribution.contribution_execution_model,
            requested_authorities=contribution.requested_authorities,
        )
        _validate_published_locator(
            payload,
            entry_kind=_verified_entry_kind(
                candidate.package.revision_handle,
                payload=payload,
            ),
        )
        return payload

    @classmethod
    def from_reserved_declaration(
        cls,
        declaration: PluginDeclaration,
        *,
        source_group: PluginDeclarationSourceGroup,
    ) -> ResourceItemDeclarationPayload:
        """Resolve Builder output against its accepted executable reservation."""

        if not isinstance(declaration, PluginDeclaration):
            raise TypeError("Resource Item codec requires PluginDeclaration")
        if not isinstance(source_group, PluginDeclarationSourceGroup):
            raise TypeError("Resource Item codec requires one SourceGroup")
        reservations = {
            item.contribution.contribution_id: item
            for item in source_group.reservations
        }
        reservation = reservations.get(declaration.contribution_id)
        if reservation is None:
            _raise_cross_field("Resource Item declaration has no SourceGroup reservation")
        reservation_view = _authoring_reservation_view(source_group, reservation)
        contribution = reservation_view.contribution
        if (
            declaration.plugin_id != reservation_view.plugin_id
            or declaration.kind != contribution.kind
            or declaration.owner != contribution.owner
            or declaration.reservation_fingerprint != contribution.fingerprint
            or declaration.source_descriptor_fingerprint
            != contribution.source_descriptor_fingerprint
            or declaration.source_kind != contribution.declaration_source.kind
        ):
            _raise_cross_field(
                "Resource Item declaration does not match its SourceGroup reservation"
            )
        payload = _payload_from_declaration(declaration)
        _validate_resource_item_reservation(payload, reservation=reservation_view)
        _validate_published_locator(
            payload,
            entry_kind=_verified_entry_kind(
                source_group.package.revision_handle,
                payload=payload,
            ),
        )
        return payload


def _validate_resource_item_reservation(
    payload: ResourceItemDeclarationPayload,
    *,
    reservation: _PluginAuthoringReservationView,
) -> None:
    if not isinstance(payload, ResourceItemDeclarationPayload):
        raise TypeError("Resource Item declaration requires a typed payload")
    contribution = reservation.contribution
    _validate_resource_item_contribution(
        payload,
        owner=contribution.owner,
        contribution_kind=contribution.kind,
        execution_model=contribution.contribution_execution_model,
        requested_authorities=contribution.requested_authorities,
    )


def _payload_from_declaration(
    declaration: PluginDeclaration,
) -> ResourceItemDeclarationPayload:
    if declaration.kind != "resource_item":
        _raise_cross_field("Resource Item declaration kind does not match")
    payload = ResourceItemDeclarationPayload.from_dict(
        declaration.to_dict()["payload"]
    )
    if payload.owner_namespace != declaration.owner:
        _raise_cross_field(
            "Resource Item owner namespace does not match its Declaration owner"
        )
    return payload


def _validate_resource_item_contribution(
    payload: ResourceItemDeclarationPayload,
    *,
    owner: str,
    contribution_kind: str,
    execution_model: str,
    requested_authorities: tuple[str, ...],
) -> None:
    if (
        contribution_kind != "resource_item"
        or payload.owner_namespace != owner
        or execution_model != "data_only"
        or requested_authorities
    ):
        _raise_cross_field(
            "Resource Item payload does not match its inert reservation envelope"
        )


def _validate_published_locator(
    payload: ResourceItemDeclarationPayload,
    *,
    entry_kind: str,
) -> None:
    if entry_kind != payload.locator_kind:
        _raise_cross_field(
            "Resource Item locator kind does not match the verified package entry"
        )


def _verified_entry_kind(
    handle: VerifiedRevisionHandle,
    *,
    payload: ResourceItemDeclarationPayload,
) -> str:
    try:
        return handle.entry_kind(payload.locator)
    except PluginRevisionError as exc:
        if exc.code != "invalid_plugin_revision_path":
            raise
        _raise_codec(
            "plugin_declaration_cross_field_mismatch",
            "Resource Item locator does not exist in the verified package",
            cause=exc,
        )


def _validate_locator_shape(
    resource_kind: ResourceItemKind,
    *,
    locator: PurePosixPath,
    locator_kind: ResourceItemLocatorKind,
) -> None:
    if resource_kind == "skill":
        if locator_kind == "file" and locator.name != "SKILL.md":
            raise ValueError("Skill file locator must identify SKILL.md")
        return
    if resource_kind in {"prompt", "method"}:
        if locator_kind != "file" or locator.suffix != ".md":
            raise ValueError(f"{resource_kind.title()} locator must be a Markdown file")
        return
    if resource_kind == "theme" and (
        locator_kind != "file" or locator.suffix != ".json"
    ):
        raise ValueError("Theme locator must be a JSON file")


def _raise_cross_field(message: str) -> NoReturn:
    _raise_codec("plugin_declaration_cross_field_mismatch", message)


def _raise_codec(
    code: str,
    message: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    error = PluginDeclarationCodecError(message, code=code)
    if cause is None:
        raise error
    raise error from cause


__all__ = [
    "RESOURCE_ITEM_DECLARATION_PAYLOAD_VERSION",
    "ResourceItemDeclarationPayload",
    "ResourceItemKind",
    "ResourceItemLocatorKind",
]
