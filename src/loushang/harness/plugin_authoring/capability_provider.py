"""Strict authoring codecs for one Plugin-contributed Capability Provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import cast

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityRequirement,
    CapabilityRequirementBinding,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.plugin_authoring.reservations import (
    _authoring_reservation_view,
    _PluginAuthoringReservationView,
)
from loushang.harness.resources.plugins.declarations import (
    PluginDeclaration,
    PluginExecutionModel,
    _document_digest,
    _exact_document,
    _freeze_json_mapping,
    _require_sha256,
    _thaw_json,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_python_path,
    canonical_plugin_symbol,
)
from loushang.harness.resources.plugins.selection import (
    PluginDeclarationReservation,
)

CAPABILITY_PROVIDER_PAYLOAD_VERSION = 1
PLUGIN_PROVIDER_SELECTION_RULE = "Plugin declaration candidate"

@dataclass(frozen=True, slots=True)
class PluginSymbolReference:
    """Serializable symbol locator bound to one immutable Plugin revision."""

    path: str
    symbol: str
    package_digest: str
    execution_model: PluginExecutionModel

    def __post_init__(self) -> None:
        path = _contained_python_path(self.path)
        canonical_plugin_symbol(self.symbol)
        _require_sha256(self.package_digest, name="Plugin symbol package digest")
        if self.execution_model != "in_process":
            raise ValueError("Unsupported Plugin symbol execution model")
        object.__setattr__(self, "path", path.as_posix())

    @property
    def relative_path(self) -> PurePosixPath:
        return PurePosixPath(self.path)

    def to_dict(self) -> dict[str, object]:
        return {
            "executionModel": self.execution_model,
            "packageDigest": self.package_digest,
            "path": self.path,
            "symbol": self.symbol,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginSymbolReference:
        document = _exact_document(
            value,
            name="Plugin symbol reference",
            keys={"executionModel", "packageDigest", "path", "symbol"},
        )
        path = document["path"]
        symbol = document["symbol"]
        package_digest = document["packageDigest"]
        execution_model = document["executionModel"]
        if not all(
            isinstance(item, str)
            for item in (path, symbol, package_digest, execution_model)
        ):
            raise ValueError("Plugin symbol reference fields must be strings")
        assert isinstance(path, str)
        assert isinstance(symbol, str)
        assert isinstance(package_digest, str)
        assert isinstance(execution_model, str)
        return cls(
            path=path,
            symbol=symbol,
            package_digest=package_digest,
            execution_model=cast(PluginExecutionModel, execution_model),
        )


@dataclass(frozen=True, slots=True)
class CapabilityProviderDeclarationPayload:
    """Canonical Provider metadata and revision-bound live symbol references."""

    provider: CapabilityBundleProvider
    factory: PluginSymbolReference
    disposer: PluginSymbolReference | None
    binding_inputs: Mapping[str, object] = field(default_factory=dict)
    configuration_fingerprint: str = ""
    payload_version: int = CAPABILITY_PROVIDER_PAYLOAD_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.provider, CapabilityBundleProvider):
            raise TypeError("Capability Provider payload requires Provider metadata")
        if not isinstance(self.factory, PluginSymbolReference):
            raise TypeError("Capability Provider payload requires a factory reference")
        if self.disposer is not None and not isinstance(
            self.disposer, PluginSymbolReference
        ):
            raise TypeError("Capability Provider disposer must be a symbol reference")
        if self.disposer is not None and (
            self.disposer.package_digest != self.factory.package_digest
            or self.disposer.execution_model != self.factory.execution_model
        ):
            raise ValueError(
                "Capability Provider factory and disposer must share revision identity"
            )
        binding_inputs = _freeze_json_mapping(self.binding_inputs)
        _require_sha256(
            self.configuration_fingerprint,
            name="Capability Provider configuration fingerprint",
        )
        if self.payload_version != CAPABILITY_PROVIDER_PAYLOAD_VERSION:
            raise ValueError("Unsupported Capability Provider payload version")
        object.__setattr__(self, "binding_inputs", binding_inputs)

    @property
    def fingerprint(self) -> str:
        return _document_digest(self.to_dict())

    @property
    def binding_input_fingerprint(self) -> str:
        return _document_digest(dict(self.binding_inputs))

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingInputs": _thaw_json(self.binding_inputs),
            "configurationFingerprint": self.configuration_fingerprint,
            "disposer": None if self.disposer is None else self.disposer.to_dict(),
            "factory": self.factory.to_dict(),
            "payloadVersion": self.payload_version,
            "provider": capability_bundle_provider_to_dict(self.provider),
        }

    @classmethod
    def from_dict(cls, value: object) -> CapabilityProviderDeclarationPayload:
        document = _exact_document(
            value,
            name="Capability Provider declaration payload",
            keys={
                "bindingInputs",
                "configurationFingerprint",
                "disposer",
                "factory",
                "payloadVersion",
                "provider",
            },
        )
        binding_inputs = document["bindingInputs"]
        configuration_fingerprint = document["configurationFingerprint"]
        disposer = document["disposer"]
        factory = document["factory"]
        payload_version = document["payloadVersion"]
        provider = document["provider"]
        if not isinstance(binding_inputs, dict):
            raise ValueError("Capability Provider bindingInputs must be an object")
        if not isinstance(configuration_fingerprint, str):
            raise ValueError(
                "Capability Provider configurationFingerprint must be a string"
            )
        if disposer is not None and not isinstance(disposer, dict):
            raise ValueError("Capability Provider disposer must be an object or null")
        if not isinstance(factory, dict):
            raise ValueError("Capability Provider factory must be an object")
        if not isinstance(payload_version, int) or isinstance(payload_version, bool):
            raise ValueError("Capability Provider payload version must be an integer")
        if not isinstance(provider, dict):
            raise ValueError("Capability Provider metadata must be an object")
        return cls(
            provider=capability_bundle_provider_from_dict(provider),
            factory=PluginSymbolReference.from_dict(factory),
            disposer=(
                None if disposer is None else PluginSymbolReference.from_dict(disposer)
            ),
            binding_inputs=binding_inputs,
            configuration_fingerprint=configuration_fingerprint,
            payload_version=payload_version,
        )

    @classmethod
    def from_reserved_declaration(
        cls,
        declaration: PluginDeclaration,
        *,
        reservation: PluginDeclarationReservation,
    ) -> CapabilityProviderDeclarationPayload:
        """Decode one declaration against its complete inert reservation."""

        reservation_view = _authoring_reservation_view(reservation)
        if not isinstance(declaration, PluginDeclaration):
            raise TypeError("Capability Provider codec requires PluginDeclaration")
        if declaration.plugin_id != reservation_view.plugin_id:
            raise ValueError(
                "Capability Provider declaration must match its package identity"
            )
        contribution = reservation_view.contribution
        if (
            declaration.contribution_id != contribution.contribution_id
            or declaration.kind != contribution.kind
            or declaration.owner != contribution.owner
            or declaration.reservation_fingerprint != contribution.fingerprint
        ):
            raise ValueError(
                "Capability Provider declaration must match its reservation envelope"
            )
        payload = _capability_provider_payload_from_declaration(declaration)
        _validate_capability_provider_reservation(
            payload,
            reservation=reservation_view,
        )
        return payload


def _capability_provider_payload_from_declaration(
    declaration: PluginDeclaration,
) -> CapabilityProviderDeclarationPayload:
    if declaration.kind != "capability_provider":
        raise ValueError("Capability Provider declaration kind mismatch")
    payload = CapabilityProviderDeclarationPayload.from_dict(
        declaration.to_dict()["payload"]
    )
    _validate_capability_provider_identity(
        payload,
        plugin_id=declaration.plugin_id,
        owner=declaration.owner,
    )
    return payload


def _validate_capability_provider_identity(
    payload: CapabilityProviderDeclarationPayload,
    *,
    plugin_id: str,
    owner: str,
) -> None:
    provider = payload.provider
    if provider.capability_id != owner:
        raise ValueError(
            "Capability Provider capability id must match its declaration owner"
        )
    if provider.source_id != f"plugin:{plugin_id}":
        raise ValueError("Capability Provider source id must be declaration-derived")
    if provider.selection_rule != PLUGIN_PROVIDER_SELECTION_RULE:
        raise ValueError(
            "Capability Provider selection rule must be declaration-derived"
        )


def _validate_capability_provider_reservation(
    payload: CapabilityProviderDeclarationPayload,
    *,
    reservation: _PluginAuthoringReservationView,
) -> None:
    contribution = reservation.contribution
    _validate_capability_provider_identity(
        payload,
        plugin_id=reservation.plugin_id,
        owner=contribution.owner,
    )
    if contribution.kind != "capability_provider":
        raise ValueError("Capability Provider declaration reservation kind mismatch")
    if payload.provider.required_authorities != frozenset(
        contribution.requested_authorities
    ):
        raise ValueError("Capability Provider authorities must match its reservation")
    if payload.configuration_fingerprint != contribution.configuration_fingerprint:
        raise ValueError(
            "Capability Provider configuration fingerprint must match its reservation"
        )
    for reference in (payload.factory, payload.disposer):
        if reference is None:
            continue
        if reference.package_digest != reservation.package_digest:
            raise ValueError(
                "Capability Provider symbol package digest must match its package"
            )
        if reference.execution_model != contribution.execution_model:
            raise ValueError(
                "Capability Provider symbol execution model must match its reservation"
            )


def capability_contract_range_to_dict(
    value: CapabilityContractRange,
) -> dict[str, object]:
    if not isinstance(value, CapabilityContractRange):
        raise TypeError("Capability contract codec requires CapabilityContractRange")
    return {"maximum": value.maximum, "minimum": value.minimum}


def capability_contract_range_from_dict(value: object) -> CapabilityContractRange:
    document = _exact_document(
        value,
        name="Capability contract range",
        keys={"maximum", "minimum"},
    )
    return CapabilityContractRange(
        minimum=cast(int, document["minimum"]),
        maximum=cast(int, document["maximum"]),
    )


def capability_requirement_to_dict(value: CapabilityRequirement) -> dict[str, object]:
    if not isinstance(value, CapabilityRequirement):
        raise TypeError("Capability requirement codec requires CapabilityRequirement")
    return {
        "binding": value.binding,
        "capability": value.capability,
        "compatibleContract": capability_contract_range_to_dict(
            value.compatible_contract
        ),
        "facets": sorted(value.facets),
        "optional": value.optional,
    }


def capability_requirement_from_dict(value: object) -> CapabilityRequirement:
    document = _exact_document(
        value,
        name="Capability requirement",
        keys={"binding", "capability", "compatibleContract", "facets", "optional"},
    )
    binding = document["binding"]
    capability = document["capability"]
    facets = _canonical_string_list(
        document["facets"],
        name="Capability requirement facets",
    )
    optional = document["optional"]
    if not isinstance(binding, str) or not isinstance(capability, str):
        raise ValueError("Capability requirement identity fields must be strings")
    if not isinstance(optional, bool):
        raise ValueError("Capability requirement optional must be a boolean")
    return CapabilityRequirement(
        capability=capability,
        facets=facets,
        compatible_contract=capability_contract_range_from_dict(
            document["compatibleContract"]
        ),
        optional=optional,
        binding=cast(CapabilityRequirementBinding, binding),
    )


def capability_bundle_provider_to_dict(
    value: CapabilityBundleProvider,
) -> dict[str, object]:
    if not isinstance(value, CapabilityBundleProvider):
        raise TypeError("Capability Provider codec requires Provider metadata")
    return {
        "capabilityId": value.capability_id,
        "compatibleContract": capability_contract_range_to_dict(
            value.compatible_contract
        ),
        "facets": sorted(value.facets),
        "implementationVersion": value.implementation_version,
        "providerId": value.provider_id,
        "requiredAuthorities": sorted(value.required_authorities),
        "requirements": [
            capability_requirement_to_dict(requirement)
            for requirement in sorted(
                value.requirements,
                key=lambda item: item.capability,
            )
        ],
        "selectionRule": value.selection_rule,
        "sourceId": value.source_id,
    }


def capability_bundle_provider_from_dict(value: object) -> CapabilityBundleProvider:
    document = _exact_document(
        value,
        name="Capability Provider metadata",
        keys={
            "capabilityId",
            "compatibleContract",
            "facets",
            "implementationVersion",
            "providerId",
            "requiredAuthorities",
            "requirements",
            "selectionRule",
            "sourceId",
        },
    )
    capability_id = document["capabilityId"]
    implementation_version = document["implementationVersion"]
    provider_id = document["providerId"]
    selection_rule = document["selectionRule"]
    source_id = document["sourceId"]
    if not all(
        isinstance(item, str)
        for item in (capability_id, provider_id, selection_rule, source_id)
    ):
        raise ValueError("Capability Provider identity fields must be strings")
    if not isinstance(implementation_version, int) or isinstance(
        implementation_version, bool
    ):
        raise ValueError("Capability Provider implementation version must be an integer")
    facets = _canonical_string_list(
        document["facets"],
        name="Capability Provider facets",
    )
    required_authorities = _canonical_string_list(
        document["requiredAuthorities"],
        name="Capability Provider required authorities",
    )
    requirements_document = document["requirements"]
    if not isinstance(requirements_document, list):
        raise ValueError("Capability Provider requirements must be a list")
    requirements = tuple(
        capability_requirement_from_dict(requirement)
        for requirement in requirements_document
    )
    capabilities = tuple(requirement.capability for requirement in requirements)
    if capabilities != tuple(sorted(capabilities)):
        raise ValueError(
            "Capability Provider requirements must use canonical sorted order"
        )
    assert isinstance(capability_id, str)
    assert isinstance(provider_id, str)
    assert isinstance(selection_rule, str)
    assert isinstance(source_id, str)
    return CapabilityBundleProvider(
        capability_id=capability_id,
        provider_id=provider_id,
        implementation_version=implementation_version,
        compatible_contract=capability_contract_range_from_dict(
            document["compatibleContract"]
        ),
        facets=facets,
        requirements=requirements,
        required_authorities=frozenset(required_authorities),
        source_id=source_id,
        selection_rule=selection_rule,
    )


def _canonical_string_list(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a string list")
    if value != sorted(set(value)):
        raise ValueError(f"{name} must use canonical sorted order without duplicates")
    return tuple(value)


def _contained_python_path(value: object) -> PurePosixPath:
    try:
        return canonical_plugin_python_path(value)
    except ValueError as exc:
        raise ValueError(
            "Plugin symbol path must be a contained relative Python path"
        ) from exc


__all__ = [
    "CAPABILITY_PROVIDER_PAYLOAD_VERSION",
    "PLUGIN_PROVIDER_SELECTION_RULE",
    "CapabilityProviderDeclarationPayload",
    "PluginSymbolReference",
    "capability_bundle_provider_from_dict",
    "capability_bundle_provider_to_dict",
    "capability_contract_range_from_dict",
    "capability_contract_range_to_dict",
    "capability_requirement_from_dict",
    "capability_requirement_to_dict",
]
