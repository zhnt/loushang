"""Strict inert Tool/Command Catalog Consumer declaration codecs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, NoReturn, Self, cast

from loushang.harness.capabilities.contracts import CapabilityRequirement
from loushang.harness.plugin_authoring.capability_requirement import (
    capability_requirement_from_dict,
    capability_requirement_to_dict,
)
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
from loushang.harness.resources.plugins.selection import (
    PluginContributionCandidate,
    PluginDeclarationSourceGroup,
)

CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION = 1
TOOL_PACK_DECLARATION_PAYLOAD_VERSION = (
    CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION
)
COMMAND_PACK_DECLARATION_PAYLOAD_VERSION = (
    CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION
)

CatalogConsumerKind = Literal["command_pack", "tool_pack"]
CatalogConsumerItemField = Literal["commands", "tools"]

_REQUIREMENT_FIELDS = {
    "binding",
    "capability",
    "compatibleContract",
    "facets",
    "optional",
}
_CONTRACT_RANGE_FIELDS = {"maximum", "minimum"}


@dataclass(frozen=True, slots=True)
class _CatalogConsumerDeclarationPayload:
    """One shared payload core specialized only by the outer contribution kind."""

    catalog_id: str
    catalog_revision: int
    item_ids: tuple[str, ...]
    owner_namespace: str
    requirements: tuple[CapabilityRequirement, ...] = ()
    payload_version: int = CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION

    _CONTRIBUTION_KIND: ClassVar[CatalogConsumerKind]
    _ITEM_FIELD: ClassVar[CatalogConsumerItemField]
    _LABEL: ClassVar[str]
    _VERSION_DIAGNOSTIC: ClassVar[str]

    def __post_init__(self) -> None:
        if self.payload_version != CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION:
            raise ValueError(f"Unsupported {self._LABEL} declaration payload version")
        if isinstance(self.item_ids, str) or not isinstance(
            self.item_ids, tuple | list
        ):
            raise TypeError(f"{self._LABEL} item identities must be a sequence")
        item_ids = tuple(self.item_ids)
        _validate_catalog_and_items(
            label=self._LABEL,
            catalog_id=self.catalog_id,
            catalog_revision=self.catalog_revision,
            owner_namespace=self.owner_namespace,
            item_ids=item_ids,
        )
        if isinstance(self.requirements, CapabilityRequirement) or not isinstance(
            self.requirements, tuple | list
        ):
            raise TypeError(f"{self._LABEL} requirements must be a sequence")
        supplied_requirements = tuple(self.requirements)
        if any(
            not isinstance(requirement, CapabilityRequirement)
            for requirement in supplied_requirements
        ):
            raise TypeError(
                f"{self._LABEL} requirements must contain CapabilityRequirement values"
            )
        requirements = tuple(
            _decode_capability_requirement(
                capability_requirement_to_dict(requirement)
            )
            for requirement in supplied_requirements
        )
        capabilities = tuple(item.capability for item in requirements)
        if capabilities != tuple(sorted(capabilities)) or len(capabilities) != len(
            set(capabilities)
        ):
            raise ValueError(
                f"{self._LABEL} requirements must be Capability-sorted and unique"
            )
        object.__setattr__(self, "item_ids", item_ids)
        object.__setattr__(self, "requirements", requirements)

    @property
    def fingerprint(self) -> str:
        return _document_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "catalogId": self.catalog_id,
            "catalogRevision": self.catalog_revision,
            self._ITEM_FIELD: list(self.item_ids),
            "ownerNamespace": self.owner_namespace,
            "payloadVersion": self.payload_version,
            "requirements": [
                capability_requirement_to_dict(item) for item in self.requirements
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, dict):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                f"{cls._LABEL} declaration payload must be an object",
            )
        version = value.get("payloadVersion")
        if version is None:
            _raise_codec(
                cls._VERSION_DIAGNOSTIC,
                f"{cls._LABEL} declaration payload version is missing",
            )
        if not isinstance(version, int) or isinstance(version, bool):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                f"{cls._LABEL} declaration payload version must be an integer",
            )
        if version != CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION:
            _raise_codec(
                cls._VERSION_DIAGNOSTIC,
                f"Unsupported {cls._LABEL} declaration payload version",
            )
        expected_fields = {
            "catalogId",
            "catalogRevision",
            cls._ITEM_FIELD,
            "ownerNamespace",
            "payloadVersion",
            "requirements",
        }
        if set(value) != expected_fields:
            _raise_codec(
                "plugin_declaration_exact_field_mismatch",
                f"{cls._LABEL} declaration payload fields do not match",
            )
        catalog_id = value["catalogId"]
        catalog_revision = value["catalogRevision"]
        item_ids = value[cls._ITEM_FIELD]
        owner_namespace = value["ownerNamespace"]
        requirements_document = value["requirements"]
        if not isinstance(catalog_id, str) or not isinstance(owner_namespace, str):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                f"{cls._LABEL} identity fields must be strings",
            )
        if not isinstance(catalog_revision, int) or isinstance(
            catalog_revision, bool
        ):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                f"{cls._LABEL} catalog revision must be an integer",
            )
        if not isinstance(item_ids, list) or not all(
            isinstance(item, str) for item in item_ids
        ):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                f"{cls._LABEL} item identities must be a string list",
            )
        if not isinstance(requirements_document, list):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                f"{cls._LABEL} requirements must be a list",
            )
        try:
            _validate_catalog_and_items(
                label=cls._LABEL,
                catalog_id=catalog_id,
                catalog_revision=catalog_revision,
                owner_namespace=owner_namespace,
                item_ids=tuple(item_ids),
            )
        except TypeError as exc:
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                f"Invalid {cls._LABEL} declaration payload: {exc}",
                cause=exc,
            )
        except ValueError as exc:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                f"Invalid {cls._LABEL} declaration payload: {exc}",
                cause=exc,
            )
        requirements = tuple(
            _decode_capability_requirement(item) for item in requirements_document
        )
        try:
            return cls(
                catalog_id=catalog_id,
                catalog_revision=catalog_revision,
                item_ids=tuple(item_ids),
                owner_namespace=owner_namespace,
                requirements=requirements,
                payload_version=version,
            )
        except TypeError as exc:
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                f"Invalid {cls._LABEL} declaration payload: {exc}",
                cause=exc,
            )
        except ValueError as exc:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                f"Invalid {cls._LABEL} declaration payload: {exc}",
                cause=exc,
            )

    @classmethod
    def from_candidate(cls, candidate: PluginContributionCandidate) -> Self:
        """Resolve one inert payload against a Host-evidenced Candidate."""

        if not isinstance(candidate, PluginContributionCandidate):
            raise TypeError(f"{cls._LABEL} codec requires a Plugin Candidate")
        declaration = candidate.declaration
        contributions = {
            item.contribution_id: item
            for item in candidate.package.contribution_index.items
        }
        contribution = contributions.get(declaration.contribution_id)
        if contribution is None:
            _raise_cross_field(f"{cls._LABEL} Candidate has no package reservation")
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
                f"{cls._LABEL} Candidate does not match its package reservation"
            )
        payload = cls._from_declaration(declaration)
        _validate_catalog_consumer_contribution(
            payload,
            owner=contribution.owner,
            contribution_kind=contribution.kind,
            execution_model=contribution.contribution_execution_model,
            requested_authorities=contribution.requested_authorities,
        )
        return payload

    @classmethod
    def from_reserved_declaration(
        cls,
        declaration: PluginDeclaration,
        *,
        source_group: PluginDeclarationSourceGroup,
    ) -> Self:
        """Resolve Builder output against its accepted inert reservation."""

        if not isinstance(declaration, PluginDeclaration):
            raise TypeError(f"{cls._LABEL} codec requires PluginDeclaration")
        if not isinstance(source_group, PluginDeclarationSourceGroup):
            raise TypeError(f"{cls._LABEL} codec requires one SourceGroup")
        reservations = {
            item.contribution.contribution_id: item
            for item in source_group.reservations
        }
        reservation = reservations.get(declaration.contribution_id)
        if reservation is None:
            _raise_cross_field(
                f"{cls._LABEL} declaration has no SourceGroup reservation"
            )
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
                f"{cls._LABEL} declaration does not match its SourceGroup reservation"
            )
        payload = cls._from_declaration(declaration)
        _validate_catalog_consumer_reservation(
            payload,
            reservation=reservation_view,
        )
        return payload

    @classmethod
    def _from_declaration(cls, declaration: PluginDeclaration) -> Self:
        if declaration.kind != cls._CONTRIBUTION_KIND:
            _raise_cross_field(f"{cls._LABEL} declaration kind does not match")
        payload = cls.from_dict(declaration.to_dict()["payload"])
        if payload.owner_namespace != declaration.owner:
            _raise_cross_field(
                f"{cls._LABEL} owner namespace does not match Declaration owner"
            )
        return payload


@dataclass(frozen=True, slots=True)
class ToolPackDeclarationPayload(_CatalogConsumerDeclarationPayload):
    """Catalog-backed Tool Consumer declaration payload v1."""

    _CONTRIBUTION_KIND: ClassVar[CatalogConsumerKind] = "tool_pack"
    _ITEM_FIELD: ClassVar[CatalogConsumerItemField] = "tools"
    _LABEL: ClassVar[str] = "Tool Pack"
    _VERSION_DIAGNOSTIC: ClassVar[str] = (
        "unsupported_tool_pack_declaration_payload_version"
    )


@dataclass(frozen=True, slots=True)
class CommandPackDeclarationPayload(_CatalogConsumerDeclarationPayload):
    """Catalog-backed Command Consumer declaration payload v1."""

    _CONTRIBUTION_KIND: ClassVar[CatalogConsumerKind] = "command_pack"
    _ITEM_FIELD: ClassVar[CatalogConsumerItemField] = "commands"
    _LABEL: ClassVar[str] = "Command Pack"
    _VERSION_DIAGNOSTIC: ClassVar[str] = (
        "unsupported_command_pack_declaration_payload_version"
    )


def _validate_catalog_consumer_reservation(
    payload: _CatalogConsumerDeclarationPayload,
    *,
    reservation: _PluginAuthoringReservationView,
) -> None:
    if not isinstance(payload, _CatalogConsumerDeclarationPayload):
        raise TypeError("Catalog Consumer declaration requires a typed payload")
    contribution = reservation.contribution
    _validate_catalog_consumer_contribution(
        payload,
        owner=contribution.owner,
        contribution_kind=contribution.kind,
        execution_model=contribution.contribution_execution_model,
        requested_authorities=contribution.requested_authorities,
    )


def _validate_catalog_consumer_contribution(
    payload: _CatalogConsumerDeclarationPayload,
    *,
    owner: str,
    contribution_kind: str,
    execution_model: str,
    requested_authorities: tuple[str, ...],
) -> None:
    if (
        contribution_kind != payload._CONTRIBUTION_KIND
        or payload.owner_namespace != owner
        or execution_model != "data_only"
        or requested_authorities
    ):
        _raise_cross_field(
            f"{payload._LABEL} payload does not match its inert reservation envelope"
        )


def _validate_catalog_and_items(
    *,
    label: str,
    catalog_id: object,
    catalog_revision: object,
    owner_namespace: object,
    item_ids: tuple[object, ...],
) -> None:
    _require_identifier(catalog_id, name=f"{label} catalog id")
    _require_identifier(owner_namespace, name=f"{label} owner namespace")
    if (
        not isinstance(catalog_revision, int)
        or isinstance(catalog_revision, bool)
        or catalog_revision <= 0
    ):
        raise ValueError(f"{label} catalog revision must be positive")
    if not item_ids:
        raise ValueError(f"{label} item identities must not be empty")
    if any(not isinstance(item, str) for item in item_ids):
        raise TypeError(f"{label} item identities must be strings")
    canonical_items = cast(tuple[str, ...], item_ids)
    for item in canonical_items:
        _require_identifier(item, name=f"{label} item identity")
    if canonical_items != tuple(sorted(canonical_items)) or len(
        canonical_items
    ) != len(set(canonical_items)):
        raise ValueError(f"{label} item identities must be sorted and unique")


def _decode_capability_requirement(value: object) -> CapabilityRequirement:
    if not isinstance(value, dict):
        _raise_codec(
            "plugin_declaration_field_type_mismatch",
            "Catalog Consumer Capability requirement must be an object",
        )
    if set(value) != _REQUIREMENT_FIELDS:
        _raise_codec(
            "plugin_declaration_exact_field_mismatch",
            "Catalog Consumer Capability requirement fields do not match",
        )
    binding = value["binding"]
    capability = value["capability"]
    contract = value["compatibleContract"]
    facets = value["facets"]
    optional = value["optional"]
    if not isinstance(binding, str) or not isinstance(capability, str):
        _raise_codec(
            "plugin_declaration_field_type_mismatch",
            "Catalog Consumer Capability requirement identities must be strings",
        )
    if not isinstance(contract, dict):
        _raise_codec(
            "plugin_declaration_field_type_mismatch",
            "Catalog Consumer compatible contract must be an object",
        )
    if set(contract) != _CONTRACT_RANGE_FIELDS:
        _raise_codec(
            "plugin_declaration_exact_field_mismatch",
            "Catalog Consumer compatible contract fields do not match",
        )
    if any(
        not isinstance(contract[field], int) or isinstance(contract[field], bool)
        for field in _CONTRACT_RANGE_FIELDS
    ):
        _raise_codec(
            "plugin_declaration_field_type_mismatch",
            "Catalog Consumer contract versions must be integers",
        )
    if not isinstance(facets, list) or not all(
        isinstance(facet, str) for facet in facets
    ):
        _raise_codec(
            "plugin_declaration_field_type_mismatch",
            "Catalog Consumer Capability facets must be a string list",
        )
    if not isinstance(optional, bool):
        _raise_codec(
            "plugin_declaration_field_type_mismatch",
            "Catalog Consumer Capability optional must be a boolean",
        )
    try:
        _require_identifier(
            capability,
            name="Catalog Consumer Capability identity",
        )
        for facet in facets:
            _require_identifier(
                facet,
                name="Catalog Consumer Capability facet",
            )
    except (TypeError, ValueError) as exc:
        _raise_codec(
            "plugin_declaration_field_value_mismatch",
            f"Invalid Catalog Consumer Capability requirement: {exc}",
            cause=exc,
        )
    try:
        requirement = capability_requirement_from_dict(value)
    except PluginDeclarationCodecError:
        raise
    except TypeError as exc:
        _raise_codec(
            "plugin_declaration_field_type_mismatch",
            f"Invalid Catalog Consumer Capability requirement: {exc}",
            cause=exc,
        )
    except ValueError as exc:
        _raise_codec(
            "plugin_declaration_field_value_mismatch",
            f"Invalid Catalog Consumer Capability requirement: {exc}",
            cause=exc,
        )
    if capability_requirement_to_dict(requirement) != value:
        _raise_codec(
            "plugin_declaration_field_value_mismatch",
            "Catalog Consumer Capability requirement is not canonical",
        )
    return requirement


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
    "CATALOG_CONSUMER_DECLARATION_PAYLOAD_VERSION",
    "COMMAND_PACK_DECLARATION_PAYLOAD_VERSION",
    "TOOL_PACK_DECLARATION_PAYLOAD_VERSION",
    "CatalogConsumerKind",
    "CommandPackDeclarationPayload",
    "ToolPackDeclarationPayload",
]
