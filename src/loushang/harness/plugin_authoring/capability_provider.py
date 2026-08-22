"""Strict authoring codecs for one Plugin-contributed Capability Provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import cast

from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.plugin_authoring.capability_requirement import (
    _canonical_string_list,
    capability_contract_range_from_dict,
    capability_contract_range_to_dict,
    capability_requirement_from_dict,
    capability_requirement_to_dict,
)
from loushang.harness.plugin_authoring.reservations import (
    _authoring_reservation_view,
    _PluginAuthoringReservationView,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionExecutionModel,
    PluginDeclaration,
    PluginDeclarationCodecError,
    _document_digest,
    _exact_document,
    _freeze_json_mapping,
    _thaw_json,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_python_path,
    canonical_plugin_symbol,
)
from loushang.harness.resources.plugins.selection import (
    PluginDeclarationSourceGroup,
)

CAPABILITY_PROVIDER_PAYLOAD_VERSION = 2
PLUGIN_SYMBOL_REFERENCE_VERSION = 2
PLUGIN_PROVIDER_SELECTION_RULE = "Plugin declaration candidate"

@dataclass(frozen=True, slots=True)
class PluginSymbolReference:
    """Package-internal symbol locator; the Host attaches revision identity."""

    path: str
    symbol: str
    execution_model: PluginContributionExecutionModel
    symbol_reference_version: int = PLUGIN_SYMBOL_REFERENCE_VERSION

    def __post_init__(self) -> None:
        path = _contained_python_path(self.path)
        canonical_plugin_symbol(self.symbol)
        if self.execution_model != "in_process":
            raise ValueError("Unsupported Plugin symbol execution model")
        if self.symbol_reference_version != PLUGIN_SYMBOL_REFERENCE_VERSION:
            raise ValueError("Unsupported Plugin symbol reference version")
        object.__setattr__(self, "path", path.as_posix())

    @property
    def relative_path(self) -> PurePosixPath:
        return PurePosixPath(self.path)

    def to_dict(self) -> dict[str, object]:
        return {
            "executionModel": self.execution_model,
            "path": self.path,
            "symbol": self.symbol,
            "symbolReferenceVersion": self.symbol_reference_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginSymbolReference:
        if not isinstance(value, dict):
            raise PluginDeclarationCodecError(
                "Plugin symbol reference must be an object",
                code="plugin_declaration_field_type_mismatch",
            )
        version = value.get("symbolReferenceVersion")
        if version is None:
            raise PluginDeclarationCodecError(
                "Plugin symbol reference version is missing",
                code="unsupported_plugin_symbol_reference_version",
            )
        if not isinstance(version, int) or isinstance(version, bool):
            raise PluginDeclarationCodecError(
                "Plugin symbol reference version must be an integer",
                code="plugin_declaration_field_type_mismatch",
            )
        if version != PLUGIN_SYMBOL_REFERENCE_VERSION:
            raise PluginDeclarationCodecError(
                "Unsupported Plugin symbol reference version",
                code="unsupported_plugin_symbol_reference_version",
            )
        document = _wire_exact_document(
            value,
            name="Plugin symbol reference",
            keys={
                "executionModel",
                "path",
                "symbol",
                "symbolReferenceVersion",
            },
        )
        path = document["path"]
        symbol = document["symbol"]
        execution_model = document["executionModel"]
        if not all(isinstance(item, str) for item in (path, symbol, execution_model)):
            raise PluginDeclarationCodecError(
                "Plugin symbol reference fields must be strings",
                code="plugin_declaration_field_type_mismatch",
            )
        assert isinstance(path, str)
        assert isinstance(symbol, str)
        assert isinstance(execution_model, str)
        if execution_model != "in_process":
            raise PluginDeclarationCodecError(
                "Unsupported Plugin symbol execution model",
                code="unsupported_plugin_contribution_execution_model",
            )
        try:
            return cls(
                path=path,
                symbol=symbol,
                execution_model=cast(
                    PluginContributionExecutionModel, execution_model
                ),
                symbol_reference_version=version,
            )
        except (TypeError, ValueError) as exc:
            raise PluginDeclarationCodecError(
                f"Invalid Plugin symbol reference: {exc}",
                code="plugin_declaration_field_value_mismatch",
            ) from exc


@dataclass(frozen=True, slots=True)
class CapabilityProviderDeclarationPayload:
    """Canonical Provider metadata and package-internal symbol references v2."""

    provider: CapabilityBundleProvider
    factory: PluginSymbolReference
    disposer: PluginSymbolReference | None
    binding_inputs: Mapping[str, object] = field(default_factory=dict)
    payload_version: int = CAPABILITY_PROVIDER_PAYLOAD_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.provider, CapabilityBundleProvider):
            raise TypeError("Capability Provider payload requires Provider metadata")
        if any(
            requirement.capability == self.provider.capability_id
            for requirement in self.provider.requirements
        ):
            raise ValueError(
                "Capability Provider cannot require its own Capability"
            )
        if not isinstance(self.factory, PluginSymbolReference):
            raise TypeError("Capability Provider payload requires a factory reference")
        if self.disposer is not None and not isinstance(
            self.disposer, PluginSymbolReference
        ):
            raise TypeError("Capability Provider disposer must be a symbol reference")
        if self.disposer is not None and (
            self.disposer.execution_model != self.factory.execution_model
        ):
            raise ValueError(
                "Capability Provider factory and disposer must share execution model"
            )
        binding_inputs = _freeze_json_mapping(self.binding_inputs)
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
            "disposer": None if self.disposer is None else self.disposer.to_dict(),
            "factory": self.factory.to_dict(),
            "payloadVersion": self.payload_version,
            "provider": capability_bundle_provider_to_dict(self.provider),
        }

    @classmethod
    def from_dict(cls, value: object) -> CapabilityProviderDeclarationPayload:
        if not isinstance(value, dict):
            raise PluginDeclarationCodecError(
                "Capability Provider payload must be an object",
                code="plugin_declaration_field_type_mismatch",
            )
        version = value.get("payloadVersion")
        if version is None:
            raise PluginDeclarationCodecError(
                "Capability Provider payload version is missing",
                code="unsupported_capability_provider_declaration_payload_version",
            )
        if not isinstance(version, int) or isinstance(version, bool):
            raise PluginDeclarationCodecError(
                "Capability Provider payload version must be an integer",
                code="plugin_declaration_field_type_mismatch",
            )
        if version != CAPABILITY_PROVIDER_PAYLOAD_VERSION:
            raise PluginDeclarationCodecError(
                "Unsupported Capability Provider payload version",
                code="unsupported_capability_provider_declaration_payload_version",
            )
        document = _wire_exact_document(
            value,
            name="Capability Provider declaration payload",
            keys={
                "bindingInputs",
                "disposer",
                "factory",
                "payloadVersion",
                "provider",
            },
        )
        binding_inputs = document["bindingInputs"]
        disposer = document["disposer"]
        factory = document["factory"]
        provider = document["provider"]
        if not isinstance(binding_inputs, dict):
            raise PluginDeclarationCodecError(
                "Capability Provider bindingInputs must be an object",
                code="plugin_declaration_field_type_mismatch",
            )
        if disposer is not None and not isinstance(disposer, dict):
            raise PluginDeclarationCodecError(
                "Capability Provider disposer must be an object or null",
                code="plugin_declaration_field_type_mismatch",
            )
        if not isinstance(factory, dict):
            raise PluginDeclarationCodecError(
                "Capability Provider factory must be an object",
                code="plugin_declaration_field_type_mismatch",
            )
        if not isinstance(provider, dict):
            raise PluginDeclarationCodecError(
                "Capability Provider metadata must be an object",
                code="plugin_declaration_field_type_mismatch",
            )
        provider_metadata = capability_bundle_provider_from_dict(provider)
        if any(
            requirement.capability == provider_metadata.capability_id
            for requirement in provider_metadata.requirements
        ):
            raise PluginDeclarationCodecError(
                "Capability Provider cannot require its own Capability",
                code="plugin_declaration_cross_field_mismatch",
            )
        return cls(
            provider=provider_metadata,
            factory=PluginSymbolReference.from_dict(factory),
            disposer=(
                None if disposer is None else PluginSymbolReference.from_dict(disposer)
            ),
            binding_inputs=binding_inputs,
            payload_version=version,
        )

    @classmethod
    def from_reserved_declaration(
        cls,
        declaration: PluginDeclaration,
        *,
        source_group: PluginDeclarationSourceGroup,
    ) -> CapabilityProviderDeclarationPayload:
        """Decode one declaration against its complete inert reservation."""

        if not isinstance(declaration, PluginDeclaration):
            raise TypeError("Capability Provider codec requires PluginDeclaration")
        if not isinstance(source_group, PluginDeclarationSourceGroup):
            raise TypeError("Capability Provider codec requires one SourceGroup")
        reservations_by_id = {
            item.contribution.contribution_id: item
            for item in source_group.reservations
        }
        reservation = reservations_by_id.get(declaration.contribution_id)
        if reservation is None:
            raise ValueError(
                "Capability Provider declaration must match a SourceGroup reservation"
            )
        reservation_view = _authoring_reservation_view(source_group, reservation)
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
            or declaration.source_descriptor_fingerprint
            != contribution.source_descriptor_fingerprint
            or declaration.source_kind != contribution.declaration_source.kind
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
    if payload.to_dict()["bindingInputs"] != _thaw_json(
        reservation.effective_configuration
    ):
        raise ValueError(
            "Capability Provider binding inputs must match its reservation configuration"
        )
    for reference in (payload.factory, payload.disposer):
        if reference is None:
            continue
        if reference.execution_model != contribution.contribution_execution_model:
            raise ValueError(
                "Capability Provider symbol execution model must match its reservation"
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


def _wire_exact_document(
    value: object,
    *,
    name: str,
    keys: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PluginDeclarationCodecError(
            f"{name} must be an object",
            code="plugin_declaration_field_type_mismatch",
        )
    if set(value) != keys:
        raise PluginDeclarationCodecError(
            f"{name} fields do not match the supported format",
            code="plugin_declaration_exact_field_mismatch",
        )
    return value


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
    "PLUGIN_SYMBOL_REFERENCE_VERSION",
    "CapabilityProviderDeclarationPayload",
    "PluginSymbolReference",
    "capability_bundle_provider_from_dict",
    "capability_bundle_provider_to_dict",
]
