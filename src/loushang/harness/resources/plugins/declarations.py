from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Literal, NoReturn, cast

from loushang.harness.resources.plugins._strict_json import (
    PluginJsonCodecError,
    StrictPluginJsonCodec,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
    parse_plugin_entrypoint,
)

PLUGIN_DECLARATION_SOURCE_VERSION = 1
PLUGIN_CONTRIBUTION_INDEX_VERSION = 2
PLUGIN_DECLARATION_IR_VERSION = 2
PLUGIN_DECLARATION_DOCUMENT_VERSION = 1
PLUGIN_LOCAL_WORKER_CONFIGURATION_VERSION = 1
PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION = 3
PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION = 3
PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION = 2
PLUGIN_DECLARATION_DOCUMENT_MEDIA_TYPE = (
    "application/vnd.loushang.plugin-declarations+json"
)
PLUGIN_DECLARATION_DOCUMENT_SCHEMA_ID = "loushang.plugin-declaration-document"
MAX_PLUGIN_DECLARATION_DOCUMENT_BYTES = 4_194_304
MAX_PLUGIN_DECLARATIONS_PER_DOCUMENT = 1_024

PluginContributionKind = Literal[
    "capability_provider",
    "command_pack",
    "continuity_provider",
    "resource_item",
    "tool_pack",
]
PluginContributionExecutionModel = Literal["data_only", "in_process", "local_worker"]
PluginDeclarationSourceKind = Literal["document", "in_process"]

_SUPPORTED_CONTRIBUTION_KINDS = frozenset(
    {
        "capability_provider",
        "command_pack",
        "continuity_provider",
        "resource_item",
        "tool_pack",
    }
)
_LEGACY_EXECUTION_MODELS = frozenset({"data_only", "in_process"})
_SUPPORTED_EXECUTION_MODELS = frozenset({*_LEGACY_EXECUTION_MODELS, "local_worker"})
_SUPPORTED_CONTRIBUTION_INDEX_VERSIONS = frozenset(
    {
        PLUGIN_CONTRIBUTION_INDEX_VERSION,
        PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION,
    }
)
_SUPPORTED_DECLARATION_IR_VERSIONS = frozenset(
    {PLUGIN_DECLARATION_IR_VERSION, PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION}
)
_SUPPORTED_DECLARATION_DOCUMENT_VERSIONS = frozenset(
    {
        PLUGIN_DECLARATION_DOCUMENT_VERSION,
        PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION,
    }
)
_IN_PROCESS_CONTRIBUTION_KINDS = frozenset(
    {"capability_provider", "continuity_provider"}
)
_DATA_ONLY_CONTRIBUTION_KINDS = frozenset(
    {"command_pack", "resource_item", "tool_pack"}
)
_LOCAL_WORKER_CONTRIBUTION_KINDS = frozenset({"capability_provider"})
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_MAX_LOCAL_WORKER_IDENTIFIER_LENGTH = 128


class PluginDeclarationCodecError(PluginJsonCodecError):
    """Finite schema diagnostic from a PLC1B declaration codec."""


@dataclass(frozen=True, slots=True)
class PluginLocalWorkerConfiguration:
    """Inert, authority-free local Worker topology descriptor v1."""

    entrypoint: str
    protocol: str
    protocol_version: int
    configuration_version: int = PLUGIN_LOCAL_WORKER_CONFIGURATION_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.configuration_version) is not int
            or self.configuration_version != PLUGIN_LOCAL_WORKER_CONFIGURATION_VERSION
        ):
            raise ValueError("Unsupported Plugin local Worker configuration version")
        path = canonical_plugin_relative_path(self.entrypoint)
        if path.as_posix() in {"", "."}:
            raise ValueError("Plugin local Worker entrypoint must name a file")
        _require_identifier(self.protocol, name="Worker protocol")
        if len(self.protocol) > _MAX_LOCAL_WORKER_IDENTIFIER_LENGTH:
            raise ValueError("Worker protocol must be a bounded identifier")
        if (
            isinstance(self.protocol_version, bool)
            or not isinstance(self.protocol_version, int)
            or self.protocol_version < 1
        ):
            raise ValueError("Plugin local Worker protocol version must be positive")
        object.__setattr__(self, "entrypoint", path.as_posix())

    @property
    def fingerprint(self) -> str:
        return _domain_digest(
            "loushang.plugin-local-worker-configuration/v1",
            configuration=self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "configurationVersion": self.configuration_version,
            "entrypoint": self.entrypoint,
            "protocol": self.protocol,
            "protocolVersion": self.protocol_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginLocalWorkerConfiguration:
        document = _require_object(value, name="Plugin local Worker configuration")
        _require_exact_fields(
            document,
            keys={
                "configurationVersion",
                "entrypoint",
                "protocol",
                "protocolVersion",
            },
            name="Plugin local Worker configuration",
        )
        _require_version(
            document,
            key="configurationVersion",
            supported=PLUGIN_LOCAL_WORKER_CONFIGURATION_VERSION,
            code="unsupported_plugin_local_worker_configuration_version",
        )
        try:
            return cls(
                entrypoint=_require_string(
                    document["entrypoint"], name="Worker entrypoint"
                ),
                protocol=_require_string(document["protocol"], name="Worker protocol"),
                protocol_version=_require_integer(
                    document["protocolVersion"], name="Worker protocolVersion"
                ),
            )
        except PluginDeclarationCodecError:
            raise
        except (TypeError, ValueError) as exc:
            _raise_codec(
                "plugin_local_worker_configuration_invalid",
                f"Invalid Plugin local Worker configuration: {exc}",
                cause=exc,
            )


@dataclass(frozen=True, slots=True)
class PluginDeclarationSource:
    """Exact revision-independent declaration-source union v1."""

    kind: PluginDeclarationSourceKind
    locator: str | None = None
    entrypoint: str | None = None
    media_type: str | None = None
    schema_id: str | None = None
    schema_version: int | None = None
    source_version: int = PLUGIN_DECLARATION_SOURCE_VERSION

    def __post_init__(self) -> None:
        if self.source_version != PLUGIN_DECLARATION_SOURCE_VERSION:
            raise ValueError("Unsupported Plugin declaration source version")
        if self.kind == "document":
            if (
                self.entrypoint is not None
                or self.media_type != PLUGIN_DECLARATION_DOCUMENT_MEDIA_TYPE
                or self.schema_id != PLUGIN_DECLARATION_DOCUMENT_SCHEMA_ID
                or self.schema_version not in _SUPPORTED_DECLARATION_DOCUMENT_VERSIONS
            ):
                raise ValueError("Invalid document Plugin declaration source")
            path = canonical_plugin_relative_path(self.locator)
            if path.suffix != ".json":
                raise ValueError("Plugin declaration document must be a JSON path")
            object.__setattr__(self, "locator", path.as_posix())
            return
        if self.kind == "in_process":
            if any(
                value is not None
                for value in (
                    self.locator,
                    self.media_type,
                    self.schema_id,
                    self.schema_version,
                )
            ):
                raise ValueError("Invalid in-process Plugin declaration source")
            path, symbol = parse_plugin_entrypoint(self.entrypoint)
            object.__setattr__(self, "entrypoint", f"{path.as_posix()}:{symbol}")
            return
        raise ValueError("Unsupported Plugin declaration source kind")

    @classmethod
    def document(
        cls,
        locator: str,
        *,
        schema_version: int = PLUGIN_DECLARATION_DOCUMENT_VERSION,
    ) -> PluginDeclarationSource:
        return cls(
            kind="document",
            locator=locator,
            media_type=PLUGIN_DECLARATION_DOCUMENT_MEDIA_TYPE,
            schema_id=PLUGIN_DECLARATION_DOCUMENT_SCHEMA_ID,
            schema_version=schema_version,
        )

    @classmethod
    def in_process(cls, entrypoint: str) -> PluginDeclarationSource:
        return cls(kind="in_process", entrypoint=entrypoint)

    @property
    def relative_path(self) -> PurePosixPath:
        if self.kind == "document":
            assert self.locator is not None
            return PurePosixPath(self.locator)
        assert self.entrypoint is not None
        path, _ = parse_plugin_entrypoint(self.entrypoint)
        return path

    @property
    def fingerprint(self) -> str:
        return _domain_digest(
            "loushang.plugin-declaration-source-descriptor/v1",
            source=self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        if self.kind == "document":
            assert self.locator is not None
            assert self.media_type is not None
            assert self.schema_id is not None
            assert self.schema_version is not None
            return {
                "kind": self.kind,
                "locator": self.locator,
                "mediaType": self.media_type,
                "schemaId": self.schema_id,
                "schemaVersion": self.schema_version,
                "sourceVersion": self.source_version,
            }
        assert self.entrypoint is not None
        return {
            "entrypoint": self.entrypoint,
            "kind": self.kind,
            "sourceVersion": self.source_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginDeclarationSource:
        document = _require_object(value, name="Plugin declaration source")
        _require_version(
            document,
            key="sourceVersion",
            supported=PLUGIN_DECLARATION_SOURCE_VERSION,
            code="unsupported_plugin_declaration_source_version",
        )
        kind = _require_union_tag(
            document,
            key="kind",
            supported={"document", "in_process"},
            code="unsupported_plugin_declaration_source_kind",
        )
        if kind == "document":
            _require_exact_fields(
                document,
                keys={
                    "kind",
                    "locator",
                    "mediaType",
                    "schemaId",
                    "schemaVersion",
                    "sourceVersion",
                },
                name="document Plugin declaration source",
            )
            locator = _require_string(document["locator"], name="source locator")
            media_type = _require_string(document["mediaType"], name="source mediaType")
            schema_id = _require_string(document["schemaId"], name="source schemaId")
            schema_version = _require_integer(
                document["schemaVersion"], name="source schemaVersion"
            )
            if schema_version not in _SUPPORTED_DECLARATION_DOCUMENT_VERSIONS:
                _raise_codec(
                    "unsupported_plugin_declaration_document_version",
                    "Unsupported Plugin declaration document schema version",
                )
            if (
                media_type != PLUGIN_DECLARATION_DOCUMENT_MEDIA_TYPE
                or schema_id != PLUGIN_DECLARATION_DOCUMENT_SCHEMA_ID
            ):
                _raise_codec(
                    "plugin_declaration_field_value_mismatch",
                    "Plugin declaration document source schema identity is invalid",
                )
            try:
                return cls.document(locator, schema_version=schema_version)
            except (TypeError, ValueError) as exc:
                _raise_codec(
                    "plugin_declaration_field_value_mismatch",
                    f"Invalid Plugin declaration document locator: {exc}",
                    cause=exc,
                )
        _require_exact_fields(
            document,
            keys={"entrypoint", "kind", "sourceVersion"},
            name="in-process Plugin declaration source",
        )
        entrypoint = _require_string(document["entrypoint"], name="source entrypoint")
        try:
            return cls.in_process(entrypoint)
        except (TypeError, ValueError) as exc:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                f"Invalid Plugin declaration entrypoint: {exc}",
                cause=exc,
            )


@dataclass(frozen=True, slots=True)
class PluginContributionReservation:
    """Exact inert ContributionIndex item and reservation identity v2."""

    contribution_id: str
    kind: PluginContributionKind
    owner: str
    declaration_source: PluginDeclarationSource
    contribution_execution_model: PluginContributionExecutionModel
    requested_authorities: tuple[str, ...]
    configuration: Mapping[str, object] = field(default_factory=dict)
    required: bool = True
    worker_configuration: PluginLocalWorkerConfiguration | None = None
    index_version: int = field(
        default=PLUGIN_CONTRIBUTION_INDEX_VERSION,
        repr=False,
    )

    def __post_init__(self) -> None:
        _require_identifier(self.contribution_id, name="contribution id")
        _require_identifier(self.owner, name="contribution owner")
        if self.kind not in _SUPPORTED_CONTRIBUTION_KINDS:
            raise ValueError("Unsupported Plugin contribution kind")
        if not isinstance(self.declaration_source, PluginDeclarationSource):
            raise TypeError("Plugin contribution requires a declaration source")
        if self.index_version not in _SUPPORTED_CONTRIBUTION_INDEX_VERSIONS:
            raise ValueError("Unsupported Plugin contribution index version")
        supported_execution_models = (
            _LEGACY_EXECUTION_MODELS
            if self.index_version == PLUGIN_CONTRIBUTION_INDEX_VERSION
            else _SUPPORTED_EXECUTION_MODELS
        )
        if self.contribution_execution_model not in supported_execution_models:
            raise ValueError("Unsupported Plugin contribution execution model")
        if self.declaration_source.kind == "document":
            expected_document_version = (
                PLUGIN_DECLARATION_DOCUMENT_VERSION
                if self.index_version == PLUGIN_CONTRIBUTION_INDEX_VERSION
                else PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION
            )
            if self.declaration_source.schema_version != expected_document_version:
                raise ValueError(
                    f"Plugin contribution index v{self.index_version} requires "
                    f"declaration document v{expected_document_version}"
                )
        if (
            self.kind in _IN_PROCESS_CONTRIBUTION_KINDS
            and self.contribution_execution_model not in {"in_process", "local_worker"}
        ):
            raise ValueError(
                f"{self.kind} contribution must be in-process or an admitted local Worker"
            )
        if (
            self.kind in _DATA_ONLY_CONTRIBUTION_KINDS
            and self.contribution_execution_model != "data_only"
        ):
            raise ValueError(f"{self.kind} contribution must be data-only")
        if any(not isinstance(item, str) for item in self.requested_authorities):
            raise TypeError("Plugin requested authorities must be strings")
        if tuple(sorted(self.requested_authorities)) != self.requested_authorities:
            raise ValueError("Plugin requested authorities must be sorted")
        if len(self.requested_authorities) != len(set(self.requested_authorities)):
            raise ValueError("Plugin requested authorities must be unique")
        for authority in self.requested_authorities:
            _require_identifier(authority, name="requested authority")
        if (
            self.kind in _DATA_ONLY_CONTRIBUTION_KINDS
            and self.requested_authorities
        ):
            raise ValueError(f"{self.kind} contribution cannot request authorities")
        object.__setattr__(self, "configuration", _freeze_json_mapping(self.configuration))
        if not isinstance(self.required, bool):
            raise TypeError("Plugin contribution required must be a boolean")
        if self.contribution_execution_model == "local_worker":
            if self.index_version != PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION:
                raise ValueError("Plugin local Worker requires contribution index v3")
            if self.kind not in _LOCAL_WORKER_CONTRIBUTION_KINDS:
                raise ValueError(
                    "Plugin local Worker is not supported for this contribution kind"
                )
            if (
                self.declaration_source.kind != "document"
                or self.declaration_source.schema_version
                != PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION
            ):
                raise ValueError(
                    "Plugin local Worker requires a declaration document v2 source"
                )
            if not isinstance(
                self.worker_configuration, PluginLocalWorkerConfiguration
            ):
                raise TypeError(
                    "Plugin local Worker requires a typed Worker configuration"
                )
            if self.requested_authorities:
                raise ValueError(
                    "Plugin local Worker cannot receive ambient requested authorities"
                )
            if self.configuration:
                raise ValueError(
                    "Plugin local Worker configuration must use the versioned Worker field"
                )
        elif self.worker_configuration is not None:
            raise ValueError(
                "Only a Plugin local Worker may carry Worker configuration"
            )

    @property
    def source_descriptor_fingerprint(self) -> str:
        return self.declaration_source.fingerprint

    @property
    def fingerprint(self) -> str:
        return _domain_digest(
            f"loushang.plugin-contribution-reservation/v{self.index_version}",
            reservation=self.to_dict(),
        )

    @property
    def configuration_fingerprint(self) -> str:
        """Temporary process-local v1 selection projection; never a wire peer."""

        return _document_digest(dict(self.configuration))

    def to_dict(self) -> dict[str, object]:
        document: dict[str, object] = {
            "configuration": _thaw_json(self.configuration),
            "contributionExecutionModel": self.contribution_execution_model,
            "declarationSource": self.declaration_source.to_dict(),
            "id": self.contribution_id,
            "kind": self.kind,
            "owner": self.owner,
            "requestedAuthorities": list(self.requested_authorities),
            "required": self.required,
        }
        if self.index_version == PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION:
            document["workerConfiguration"] = (
                None
                if self.worker_configuration is None
                else self.worker_configuration.to_dict()
            )
        return document

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        index_version: int = PLUGIN_CONTRIBUTION_INDEX_VERSION,
    ) -> PluginContributionReservation:
        document = _require_object(value, name="Plugin contribution reservation")
        if index_version not in _SUPPORTED_CONTRIBUTION_INDEX_VERSIONS:
            _raise_codec(
                "unsupported_plugin_contribution_index_version",
                "Unsupported Plugin contribution index version",
            )
        keys = {
            "configuration",
            "contributionExecutionModel",
            "declarationSource",
            "id",
            "kind",
            "owner",
            "requestedAuthorities",
            "required",
        }
        if index_version == PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION:
            keys.add("workerConfiguration")
        _require_exact_fields(
            document,
            keys=keys,
            name="Plugin contribution reservation",
        )
        contribution_id = _require_string(document["id"], name="contribution id")
        kind = _require_union_tag(
            document,
            key="kind",
            supported=_SUPPORTED_CONTRIBUTION_KINDS,
            code="unsupported_plugin_contribution_kind",
        )
        owner = _require_string(document["owner"], name="contribution owner")
        execution_model = _require_union_tag(
            document,
            key="contributionExecutionModel",
            supported=(
                _LEGACY_EXECUTION_MODELS
                if index_version == PLUGIN_CONTRIBUTION_INDEX_VERSION
                else _SUPPORTED_EXECUTION_MODELS
            ),
            code="unsupported_plugin_contribution_execution_model",
        )
        authorities = _require_sorted_unique_strings(
            document["requestedAuthorities"], name="Plugin requestedAuthorities"
        )
        configuration = document["configuration"]
        if not isinstance(configuration, dict):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Plugin contribution configuration must be an object",
            )
        required = document["required"]
        if not isinstance(required, bool):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Plugin contribution required must be a boolean",
            )
        if kind in _IN_PROCESS_CONTRIBUTION_KINDS and execution_model not in {
            "in_process",
            "local_worker",
        }:
            _raise_codec(
                "unsupported_plugin_contribution_execution_model",
                f"{kind} contribution must use in_process or local_worker",
            )
        if kind in _DATA_ONLY_CONTRIBUTION_KINDS and execution_model != "data_only":
            _raise_codec(
                "unsupported_plugin_contribution_execution_model",
                f"{kind} contribution must use data_only",
            )
        if kind in _DATA_ONLY_CONTRIBUTION_KINDS and authorities:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                f"{kind} contribution cannot request authorities",
            )
        source = PluginDeclarationSource.from_dict(document["declarationSource"])
        worker_configuration = None
        if index_version == PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION:
            worker_value = document["workerConfiguration"]
            if worker_value is not None:
                worker_configuration = PluginLocalWorkerConfiguration.from_dict(
                    worker_value
                )
        try:
            return cls(
                contribution_id=contribution_id,
                kind=cast(PluginContributionKind, kind),
                owner=owner,
                declaration_source=source,
                contribution_execution_model=cast(
                    PluginContributionExecutionModel, execution_model
                ),
                requested_authorities=authorities,
                configuration=configuration,
                required=required,
                worker_configuration=worker_configuration,
                index_version=index_version,
            )
        except (TypeError, ValueError) as exc:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                f"Invalid Plugin contribution reservation: {exc}",
                cause=exc,
            )


@dataclass(frozen=True, slots=True)
class PluginContributionIndex:
    """Exact inert contribution reservation index v2 or local-Worker v3."""

    items: tuple[PluginContributionReservation, ...] = ()
    version: int = PLUGIN_CONTRIBUTION_INDEX_VERSION

    def __post_init__(self) -> None:
        if self.version not in _SUPPORTED_CONTRIBUTION_INDEX_VERSIONS:
            raise ValueError("Unsupported Plugin contribution index version")
        if any(
            not isinstance(item, PluginContributionReservation) for item in self.items
        ):
            raise TypeError("Plugin contribution index items have an invalid type")
        identities = tuple(item.contribution_id for item in self.items)
        if identities != tuple(sorted(identities)):
            raise ValueError("Plugin contribution index items must be sorted")
        if len(identities) != len(set(identities)):
            raise ValueError("Plugin contribution index contains duplicate identities")
        if any(item.index_version != self.version for item in self.items):
            raise ValueError(
                "Plugin contribution reservation version must match its index"
            )
        if self.version == PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION and not any(
            item.contribution_execution_model == "local_worker" for item in self.items
        ):
            raise ValueError(
                "Plugin contribution index v3 requires a local Worker contribution"
            )

    @property
    def fingerprint(self) -> str:
        return _domain_digest(
            f"loushang.plugin-contribution-index/v{self.version}",
            index=self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {"items": [item.to_dict() for item in self.items], "version": self.version}

    @classmethod
    def from_dict(cls, value: object) -> PluginContributionIndex:
        document = _require_object(value, name="Plugin contribution index")
        version = _require_supported_version(
            document,
            key="version",
            supported=_SUPPORTED_CONTRIBUTION_INDEX_VERSIONS,
            code="unsupported_plugin_contribution_index_version",
        )
        _require_exact_fields(
            document, keys={"items", "version"}, name="Plugin contribution index"
        )
        items = document["items"]
        if not isinstance(items, list):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Plugin contribution index items must be a list",
            )
        decoded = tuple(
            PluginContributionReservation.from_dict(item, index_version=version)
            for item in items
        )
        identities = tuple(item.contribution_id for item in decoded)
        if identities != tuple(sorted(identities)):
            _raise_codec(
                "plugin_contribution_index_unsorted",
                "Plugin contribution index items must be contribution-id sorted",
            )
        if len(identities) != len(set(identities)):
            _raise_codec(
                "duplicate_plugin_contribution_identity",
                "Plugin contribution index contains duplicate identities",
            )
        if version == PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION and not any(
            item.contribution_execution_model == "local_worker" for item in decoded
        ):
            _raise_codec(
                "plugin_local_worker_contribution_missing",
                "Plugin contribution index v3 requires a local Worker contribution",
            )
        return cls(items=decoded, version=version)


@dataclass(frozen=True, slots=True)
class PluginDeclaration:
    """Exact serializable declaration IR v2 or local-Worker IR v3."""

    plugin_id: str
    contribution_id: str
    kind: PluginContributionKind
    owner: str
    reservation_fingerprint: str
    source_descriptor_fingerprint: str
    source_kind: PluginDeclarationSourceKind
    payload: Mapping[str, object]
    ir_version: int = PLUGIN_DECLARATION_IR_VERSION
    contribution_execution_model: PluginContributionExecutionModel | None = None
    worker_configuration: PluginLocalWorkerConfiguration | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.plugin_id, name="Plugin id")
        _require_identifier(self.contribution_id, name="contribution id")
        _require_identifier(self.owner, name="contribution owner")
        if self.kind not in _SUPPORTED_CONTRIBUTION_KINDS:
            raise ValueError("Unsupported Plugin declaration kind")
        if self.ir_version not in _SUPPORTED_DECLARATION_IR_VERSIONS:
            raise ValueError("Unsupported Plugin declaration IR version")
        if self.source_kind not in {"document", "in_process"}:
            raise ValueError("Unsupported Plugin declaration source kind")
        _require_sha256(self.reservation_fingerprint, name="reservation fingerprint")
        _require_sha256(
            self.source_descriptor_fingerprint, name="source descriptor fingerprint"
        )
        object.__setattr__(self, "payload", _freeze_json_mapping(self.payload))
        if self.ir_version == PLUGIN_DECLARATION_IR_VERSION:
            if (
                self.contribution_execution_model is not None
                or self.worker_configuration is not None
            ):
                raise ValueError(
                    "Plugin declaration IR v2 cannot carry execution topology"
                )
            return
        if self.contribution_execution_model not in _SUPPORTED_EXECUTION_MODELS:
            raise ValueError(
                "Plugin declaration IR v3 requires a supported execution model"
            )
        if (
            self.kind in _IN_PROCESS_CONTRIBUTION_KINDS
            and self.contribution_execution_model not in {"in_process", "local_worker"}
        ):
            raise ValueError(
                f"{self.kind} declaration must be in-process or an admitted local Worker"
            )
        if (
            self.kind in _DATA_ONLY_CONTRIBUTION_KINDS
            and self.contribution_execution_model != "data_only"
        ):
            raise ValueError(f"{self.kind} declaration must be data-only")
        if self.contribution_execution_model == "local_worker":
            if not isinstance(
                self.worker_configuration, PluginLocalWorkerConfiguration
            ):
                raise TypeError(
                    "Plugin local Worker declaration requires Worker configuration"
                )
            if self.source_kind != "document":
                raise ValueError(
                    "Plugin local Worker declaration must be document sourced"
                )
            if self.kind not in _LOCAL_WORKER_CONTRIBUTION_KINDS:
                raise ValueError(
                    "Plugin local Worker declaration kind is not supported"
                )
        elif self.worker_configuration is not None:
            raise ValueError(
                "Only a Plugin local Worker declaration may carry Worker configuration"
            )

    @property
    def fingerprint(self) -> str:
        return _domain_digest(
            f"loushang.plugin-declaration/v{self.ir_version}",
            declaration=self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        document: dict[str, object] = {
            "contributionId": self.contribution_id,
            "irVersion": self.ir_version,
            "kind": self.kind,
            "owner": self.owner,
            "payload": _thaw_json(self.payload),
            "pluginId": self.plugin_id,
            "reservationFingerprint": self.reservation_fingerprint,
            "sourceDescriptorFingerprint": self.source_descriptor_fingerprint,
            "sourceKind": self.source_kind,
        }
        if self.ir_version == PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION:
            document["contributionExecutionModel"] = self.contribution_execution_model
            document["workerConfiguration"] = (
                None
                if self.worker_configuration is None
                else self.worker_configuration.to_dict()
            )
        return document

    @classmethod
    def from_dict(cls, value: object) -> PluginDeclaration:
        document = _require_object(value, name="Plugin declaration")
        ir_version = _require_supported_version(
            document,
            key="irVersion",
            supported=_SUPPORTED_DECLARATION_IR_VERSIONS,
            code="unsupported_plugin_declaration_ir_version",
        )
        keys = {
            "contributionId",
            "irVersion",
            "kind",
            "owner",
            "payload",
            "pluginId",
            "reservationFingerprint",
            "sourceDescriptorFingerprint",
            "sourceKind",
        }
        if ir_version == PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION:
            keys.update({"contributionExecutionModel", "workerConfiguration"})
        _require_exact_fields(
            document,
            keys=keys,
            name="Plugin declaration",
        )
        kind = _require_union_tag(
            document,
            key="kind",
            supported=_SUPPORTED_CONTRIBUTION_KINDS,
            code="unsupported_plugin_contribution_kind",
        )
        source_kind = _require_union_tag(
            document,
            key="sourceKind",
            supported={"document", "in_process"},
            code="unsupported_plugin_declaration_source_kind",
        )
        payload = document["payload"]
        if not isinstance(payload, dict):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Plugin declaration payload must be an object",
            )
        execution_model = None
        worker_configuration = None
        if ir_version == PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION:
            execution_model = _require_union_tag(
                document,
                key="contributionExecutionModel",
                supported=_SUPPORTED_EXECUTION_MODELS,
                code="unsupported_plugin_contribution_execution_model",
            )
            worker_value = document["workerConfiguration"]
            if worker_value is not None:
                worker_configuration = PluginLocalWorkerConfiguration.from_dict(
                    worker_value
                )
        try:
            return cls(
                plugin_id=_require_string(document["pluginId"], name="Plugin id"),
                contribution_id=_require_string(
                    document["contributionId"], name="contribution id"
                ),
                kind=cast(PluginContributionKind, kind),
                owner=_require_string(document["owner"], name="contribution owner"),
                reservation_fingerprint=_require_string(
                    document["reservationFingerprint"], name="reservation fingerprint"
                ),
                source_descriptor_fingerprint=_require_string(
                    document["sourceDescriptorFingerprint"],
                    name="source descriptor fingerprint",
                ),
                source_kind=cast(PluginDeclarationSourceKind, source_kind),
                payload=payload,
                ir_version=ir_version,
                contribution_execution_model=cast(
                    PluginContributionExecutionModel | None,
                    execution_model,
                ),
                worker_configuration=worker_configuration,
            )
        except PluginDeclarationCodecError:
            raise
        except (TypeError, ValueError) as exc:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                f"Invalid Plugin declaration: {exc}",
                cause=exc,
            )


@dataclass(frozen=True, slots=True)
class PluginDeclarationDocument:
    """Canonical non-empty declaration document envelope v1 or Worker v2."""

    declarations: tuple[PluginDeclaration, ...]
    document_version: int = PLUGIN_DECLARATION_DOCUMENT_VERSION

    def __post_init__(self) -> None:
        if self.document_version not in _SUPPORTED_DECLARATION_DOCUMENT_VERSIONS:
            raise ValueError("Unsupported Plugin declaration document version")
        if not self.declarations:
            raise ValueError("Plugin declaration document must not be empty")
        if len(self.declarations) > MAX_PLUGIN_DECLARATIONS_PER_DOCUMENT:
            raise ValueError("Plugin declaration document has too many declarations")
        if any(not isinstance(item, PluginDeclaration) for item in self.declarations):
            raise TypeError("Plugin declaration document contains an invalid declaration")
        identities = tuple(
            (item.plugin_id, item.contribution_id) for item in self.declarations
        )
        if identities != tuple(sorted(identities)):
            raise ValueError("Plugin declaration document must be sorted")
        if len(identities) != len(set(identities)):
            raise ValueError("Plugin declaration document contains duplicate identities")
        expected_ir_version = (
            PLUGIN_DECLARATION_IR_VERSION
            if self.document_version == PLUGIN_DECLARATION_DOCUMENT_VERSION
            else PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION
        )
        if any(item.ir_version != expected_ir_version for item in self.declarations):
            raise ValueError(
                "Plugin declaration IR version must match its document version"
            )
        if (
            self.document_version == PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION
            and not any(
                item.contribution_execution_model == "local_worker"
                for item in self.declarations
            )
        ):
            raise ValueError(
                "Plugin declaration document v2 requires a local Worker declaration"
            )

    @property
    def bytes_digest(self) -> str:
        return sha256(PluginDeclarationDocumentCodec.encode_bytes(self)).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "declarations": [item.to_dict() for item in self.declarations],
            "documentVersion": self.document_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginDeclarationDocument:
        document = _require_object(value, name="Plugin declaration document")
        document_version = _require_supported_version(
            document,
            key="documentVersion",
            supported=_SUPPORTED_DECLARATION_DOCUMENT_VERSIONS,
            code="unsupported_plugin_declaration_document_version",
        )
        _require_exact_fields(
            document,
            keys={"declarations", "documentVersion"},
            name="Plugin declaration document",
        )
        declarations = document["declarations"]
        if not isinstance(declarations, list):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Plugin declaration document declarations must be a list",
            )
        if not declarations:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                "Plugin declaration document must not be empty",
            )
        if len(declarations) > MAX_PLUGIN_DECLARATIONS_PER_DOCUMENT:
            _raise_codec(
                "plugin_declaration_document_too_many_declarations",
                "Plugin declaration document has too many declarations",
            )
        decoded = tuple(PluginDeclaration.from_dict(item) for item in declarations)
        identities = tuple((item.plugin_id, item.contribution_id) for item in decoded)
        if identities != tuple(sorted(identities)):
            _raise_codec(
                "plugin_declaration_document_unsorted",
                "Plugin declaration document declarations must be sorted",
            )
        if len(identities) != len(set(identities)):
            _raise_codec(
                "duplicate_plugin_declaration_identity",
                "Plugin declaration document contains duplicate identities",
            )
        if (
            document_version == PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION
            and not any(
                item.contribution_execution_model == "local_worker" for item in decoded
            )
        ):
            _raise_codec(
                "plugin_local_worker_declaration_missing",
                "Plugin declaration document v2 requires a local Worker declaration",
            )
        try:
            return cls(
                declarations=decoded,
                document_version=document_version,
            )
        except (TypeError, ValueError) as exc:
            _raise_codec(
                "plugin_declaration_document_version_mismatch",
                f"Invalid Plugin declaration document: {exc}",
                cause=exc,
            )


class PluginDeclarationDocumentCodec:
    """Stateless strict byte codec for one declaration document."""

    @staticmethod
    def decode_bytes(encoded: bytes) -> PluginDeclarationDocument:
        if len(encoded) > MAX_PLUGIN_DECLARATION_DOCUMENT_BYTES:
            _raise_codec(
                "plugin_declaration_document_too_large",
                "Plugin declaration document exceeds the byte limit",
            )
        try:
            value = StrictPluginJsonCodec.decode_bytes(encoded)
        except PluginJsonCodecError as exc:
            raise PluginDeclarationCodecError(str(exc), code=exc.code) from exc
        document = PluginDeclarationDocument.from_dict(value)
        try:
            StrictPluginJsonCodec.require_canonical_bytes(encoded, document.to_dict())
        except PluginJsonCodecError as exc:
            raise PluginDeclarationCodecError(str(exc), code=exc.code) from exc
        return document

    @staticmethod
    def encode_bytes(document: PluginDeclarationDocument) -> bytes:
        if not isinstance(document, PluginDeclarationDocument):
            raise TypeError("Plugin declaration codec requires a declaration document")
        encoded = StrictPluginJsonCodec.encode(document.to_dict())
        if len(encoded) > MAX_PLUGIN_DECLARATION_DOCUMENT_BYTES:
            _raise_codec(
                "plugin_declaration_document_too_large",
                "Plugin declaration document exceeds the byte limit",
            )
        return encoded


def _require_identifier(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {name}")


def _require_sha256(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _freeze_json_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("Plugin declaration data must be a mapping")
    frozen = {
        key: _freeze_json_value(item)
        for key, item in value.items()
        if isinstance(key, str)
    }
    if len(frozen) != len(value):
        raise ValueError("Plugin declaration object keys must be strings")
    StrictPluginJsonCodec.encode(frozen)
    return MappingProxyType(frozen)


def _freeze_json_value(value: object) -> object:
    if value is None or isinstance(value, str | bool | int | float):
        StrictPluginJsonCodec.encode(value)
        return value
    if isinstance(value, Mapping):
        return _freeze_json_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_json_value(item) for item in value)
    raise ValueError("Plugin declaration data must contain only JSON values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_json(value: object) -> bytes:
    return StrictPluginJsonCodec.encode(_thaw_json(value))


def _document_digest(value: object) -> str:
    return sha256(_canonical_json(value)).hexdigest()


def _domain_digest(domain: str, **fields: object) -> str:
    return _document_digest({"domain": domain, **fields})


def _exact_document(
    value: object, *, name: str, keys: set[str]
) -> dict[str, object]:
    """Internal typed-object helper; wire records use the coded validators."""

    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name} fields do not match the supported format")
    return value


def _require_object(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        _raise_codec(
            "plugin_declaration_field_type_mismatch", f"{name} must be an object"
        )
    return value


def _require_exact_fields(
    document: Mapping[str, object], *, keys: set[str], name: str
) -> None:
    if set(document) != keys:
        _raise_codec(
            "plugin_declaration_exact_field_mismatch",
            f"{name} fields do not match the supported format",
        )


def _require_version(
    document: Mapping[str, object], *, key: str, supported: int, code: str
) -> None:
    if key not in document:
        _raise_codec(code, f"{key} is missing or unsupported")
    version = document[key]
    if not isinstance(version, int) or isinstance(version, bool):
        _raise_codec(
            "plugin_declaration_field_type_mismatch", f"{key} must be an integer"
        )
    if version != supported:
        _raise_codec(code, f"Unsupported {key}: {version}")


def _require_supported_version(
    document: Mapping[str, object],
    *,
    key: str,
    supported: frozenset[int],
    code: str,
) -> int:
    if key not in document:
        _raise_codec(code, f"{key} is missing or unsupported")
    version = document[key]
    if not isinstance(version, int) or isinstance(version, bool):
        _raise_codec(
            "plugin_declaration_field_type_mismatch", f"{key} must be an integer"
        )
    if version not in supported:
        _raise_codec(code, f"Unsupported {key}: {version}")
    return version


def _require_union_tag(
    document: Mapping[str, object],
    *,
    key: str,
    supported: set[str] | frozenset[str],
    code: str,
) -> str:
    if key not in document:
        _raise_codec("plugin_declaration_exact_field_mismatch", f"{key} is required")
    value = document[key]
    if not isinstance(value, str):
        _raise_codec(
            "plugin_declaration_field_type_mismatch", f"{key} must be a string"
        )
    if value not in supported:
        _raise_codec(code, f"Unsupported {key}: {value}")
    return value


def _require_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        _raise_codec(
            "plugin_declaration_field_type_mismatch", f"{name} must be a string"
        )
    return value


def _require_integer(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _raise_codec(
            "plugin_declaration_field_type_mismatch", f"{name} must be an integer"
        )
    return value


def _require_sorted_unique_strings(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _raise_codec(
            "plugin_declaration_field_type_mismatch",
            f"{name} must be a string list",
        )
    result = tuple(value)
    if result != tuple(sorted(result)) or len(result) != len(set(result)):
        _raise_codec(
            "plugin_declaration_field_value_mismatch",
            f"{name} must be sorted and unique",
        )
    try:
        for item in result:
            _require_identifier(item, name=name)
    except ValueError as exc:
        _raise_codec(
            "plugin_declaration_field_value_mismatch",
            f"Invalid {name}: {exc}",
            cause=exc,
        )
    return result


def _raise_codec(
    code: str, message: str, *, cause: BaseException | None = None
) -> NoReturn:
    error = PluginDeclarationCodecError(message, code=code)
    if cause is None:
        raise error
    raise error from cause


__all__ = [
    "MAX_PLUGIN_DECLARATIONS_PER_DOCUMENT",
    "MAX_PLUGIN_DECLARATION_DOCUMENT_BYTES",
    "PLUGIN_CONTRIBUTION_INDEX_VERSION",
    "PLUGIN_DECLARATION_DOCUMENT_MEDIA_TYPE",
    "PLUGIN_DECLARATION_DOCUMENT_SCHEMA_ID",
    "PLUGIN_DECLARATION_DOCUMENT_VERSION",
    "PLUGIN_DECLARATION_IR_VERSION",
    "PLUGIN_DECLARATION_SOURCE_VERSION",
    "PLUGIN_LOCAL_WORKER_CONFIGURATION_VERSION",
    "PLUGIN_LOCAL_WORKER_CONTRIBUTION_INDEX_VERSION",
    "PLUGIN_LOCAL_WORKER_DECLARATION_DOCUMENT_VERSION",
    "PLUGIN_LOCAL_WORKER_DECLARATION_IR_VERSION",
    "PluginContributionExecutionModel",
    "PluginContributionIndex",
    "PluginContributionKind",
    "PluginContributionReservation",
    "PluginDeclaration",
    "PluginDeclarationCodecError",
    "PluginDeclarationDocument",
    "PluginDeclarationDocumentCodec",
    "PluginDeclarationSource",
    "PluginDeclarationSourceKind",
    "PluginLocalWorkerConfiguration",
]
