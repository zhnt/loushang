from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from hashlib import sha256
from typing import Literal, cast

from loushang.foundation.json import JsonValueError, require_json_mapping
from loushang.harness.journal import FunctionalJournalRecordCodec, JournalCodecError
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
    decode_nullable,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import PluginDeclarationCodecError
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

PLUGIN_PACKAGE_REVISION_REF_VERSION = 1
PLUGIN_INSTALLATION_KEY_VERSION = 1
PLUGIN_DESIRED_SELECTION_VERSION = 1
PLUGIN_INSTALLATION_STATE_VERSION = 1
PLUGIN_DESIRED_STATE_MUTATION_VERSION = 1
PLUGIN_DESIRED_STATE_TRANSITION_VERSION = 1

PluginInstallationScope = Literal["process", "tenant", "workspace"]
PluginDesiredState = Literal[
    "absent",
    "installed_disabled",
    "installed_enabled",
]
PluginDesiredTransitionKind = Literal[
    "install",
    "enable",
    "disable",
    "remove",
    "unchanged",
]

_INSTALLATION_SCOPES = frozenset({"process", "tenant", "workspace"})
_DESIRED_STATES = frozenset({"absent", "installed_disabled", "installed_enabled"})
_TRANSITION_KINDS = frozenset({"install", "enable", "disable", "remove", "unchanged"})


class PluginLifecycleCodecError(JournalCodecError):
    """Strict value-record decoding failure with a stable lifecycle code."""


@dataclass(frozen=True, slots=True)
class PluginPackageRevisionRefV1:
    plugin_id: str
    plugin_version: str | None
    package_content_digest: str
    dependency_lock_digest: str
    package_source_identity: str
    schema_version: int = PLUGIN_PACKAGE_REVISION_REF_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.plugin_id, name="Plugin id")
        if self.plugin_version is not None:
            _require_nonempty(self.plugin_version, name="Plugin version")
        _require_sha256(self.package_content_digest, name="package content digest")
        _require_sha256(self.dependency_lock_digest, name="dependency lock digest")
        _require_nonempty(
            self.package_source_identity,
            name="package source identity",
        )
        _require_version(
            self.schema_version,
            expected=PLUGIN_PACKAGE_REVISION_REF_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "dependencyLockDigest": self.dependency_lock_digest,
            "packageContentDigest": self.package_content_digest,
            "packageSourceIdentity": self.package_source_identity,
            "pluginId": self.plugin_id,
            "pluginVersion": self.plugin_version,
            "schemaVersion": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackageRevisionRefV1:
        document = _decode_document(
            value,
            name="Plugin package revision ref",
            schema=_PLUGINPACKAGEREVISIONREF_SCHEMA,
            version=PLUGIN_PACKAGE_REVISION_REF_VERSION,
        )
        try:
            return _PLUGINPACKAGEREVISIONREF_SCHEMA.decode(cls, document)
        except PluginLifecycleCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, order=True, slots=True)
class PluginInstallationKeyV1:
    product_id: str
    installation_scope: PluginInstallationScope
    scope_id: str
    plugin_id: str
    schema_version: int = PLUGIN_INSTALLATION_KEY_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.product_id, name="Product id")
        if self.installation_scope not in _INSTALLATION_SCOPES:
            raise ValueError("Unsupported Plugin installation scope")
        _require_nonempty(self.scope_id, name="scope id")
        _require_nonempty(self.plugin_id, name="Plugin id")
        _require_version(
            self.schema_version,
            expected=PLUGIN_INSTALLATION_KEY_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "installationScope": self.installation_scope,
            "pluginId": self.plugin_id,
            "productId": self.product_id,
            "schemaVersion": self.schema_version,
            "scopeId": self.scope_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstallationKeyV1:
        document = _decode_document(
            value,
            name="Plugin installation key",
            schema=_PLUGININSTALLATIONKEY_SCHEMA,
            version=PLUGIN_INSTALLATION_KEY_VERSION,
        )
        try:
            scope = _wire_string(
                document["installationScope"],
                name="Plugin installation scope",
            )
            if scope not in _INSTALLATION_SCOPES:
                raise ValueError("Unsupported Plugin installation scope")
            document["installationScope"] = scope
            return _PLUGININSTALLATIONKEY_SCHEMA.decode(cls, document)
        except PluginLifecycleCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginDesiredSelectionV1:
    desired_state: PluginDesiredState
    package_revision: PluginPackageRevisionRefV1 | None
    instance_revision_ref: PluginInstanceRevisionRef | None
    schema_version: int = PLUGIN_DESIRED_SELECTION_VERSION

    def __post_init__(self) -> None:
        if self.desired_state not in _DESIRED_STATES:
            raise ValueError("Unsupported Plugin desired state")
        _require_version(
            self.schema_version,
            expected=PLUGIN_DESIRED_SELECTION_VERSION,
        )
        if self.desired_state == "absent":
            if (
                self.package_revision is not None
                or self.instance_revision_ref is not None
            ):
                raise ValueError("Absent Plugin selection cannot carry references")
            return
        if self.package_revision is None:
            raise ValueError("Installed Plugin selection requires a package revision")
        if self.desired_state == "installed_disabled":
            if self.instance_revision_ref is not None:
                raise ValueError(
                    "Disabled Plugin selection cannot be an active revision"
                )
            return
        if self.instance_revision_ref is None:
            raise ValueError("Enabled Plugin selection requires an instance revision")
        if self.instance_revision_ref.plugin_id != self.package_revision.plugin_id:
            raise ValueError("Plugin selection reference ids do not match")

    @classmethod
    def absent(cls) -> PluginDesiredSelectionV1:
        return cls(
            desired_state="absent",
            package_revision=None,
            instance_revision_ref=None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "desiredState": self.desired_state,
            "instanceRevisionRef": (
                None
                if self.instance_revision_ref is None
                else self.instance_revision_ref.to_dict()
            ),
            "packageRevision": (
                None
                if self.package_revision is None
                else self.package_revision.to_dict()
            ),
            "schemaVersion": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginDesiredSelectionV1:
        document = _decode_document(
            value,
            name="Plugin desired selection",
            schema=_PLUGINDESIREDSELECTION_SCHEMA,
            version=PLUGIN_DESIRED_SELECTION_VERSION,
        )
        try:
            desired_state = _wire_string(
                document["desiredState"],
                name="Plugin desired state",
            )
            if desired_state not in _DESIRED_STATES:
                raise ValueError("Unsupported Plugin desired state")
            package = decode_nullable(
                document["packageRevision"],
                decoder=PluginPackageRevisionRefV1.from_dict,
            )
            instance = _wire_optional_instance_ref(document["instanceRevisionRef"])
            document["desiredState"] = desired_state
            document["packageRevision"] = package
            document["instanceRevisionRef"] = instance
            return _PLUGINDESIREDSELECTION_SCHEMA.decode(cls, document)
        except PluginLifecycleCodecError:
            raise
        except (PluginDeclarationCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginInstallationStateV1:
    installation_key: PluginInstallationKeyV1
    selection: PluginDesiredSelectionV1
    latest_instance_revision_ref: PluginInstanceRevisionRef | None
    schema_version: int = PLUGIN_INSTALLATION_STATE_VERSION

    def __post_init__(self) -> None:
        _require_version(
            self.schema_version,
            expected=PLUGIN_INSTALLATION_STATE_VERSION,
        )
        plugin_id = self.installation_key.plugin_id
        package = self.selection.package_revision
        selected_instance = self.selection.instance_revision_ref
        latest = self.latest_instance_revision_ref
        if package is not None and package.plugin_id != plugin_id:
            raise ValueError("Package revision does not match installation Plugin id")
        if selected_instance is not None and selected_instance.plugin_id != plugin_id:
            raise ValueError("Instance revision does not match installation Plugin id")
        if latest is not None and latest.plugin_id != plugin_id:
            raise ValueError(
                "Latest instance revision does not match installation Plugin id"
            )
        if (
            self.selection.desired_state == "installed_enabled"
            and selected_instance != latest
        ):
            raise ValueError(
                "Enabled selection must reference the latest instance revision"
            )

    @classmethod
    def initial(cls, key: PluginInstallationKeyV1) -> PluginInstallationStateV1:
        return cls(
            installation_key=key,
            selection=PluginDesiredSelectionV1.absent(),
            latest_instance_revision_ref=None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "installationKey": self.installation_key.to_dict(),
            "latestInstanceRevisionRef": (
                None
                if self.latest_instance_revision_ref is None
                else self.latest_instance_revision_ref.to_dict()
            ),
            "schemaVersion": self.schema_version,
            "selection": self.selection.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstallationStateV1:
        document = _decode_document(
            value,
            name="Plugin installation state",
            schema=_PLUGININSTALLATIONSTATE_SCHEMA,
            version=PLUGIN_INSTALLATION_STATE_VERSION,
        )
        try:
            return _PLUGININSTALLATIONSTATE_SCHEMA.decode(cls, document)
        except PluginLifecycleCodecError:
            raise
        except (PluginDeclarationCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginDesiredStateMutationV1:
    operation_id: str
    idempotency_key: str
    expected_inventory_revision: int
    installation_key: PluginInstallationKeyV1
    desired_state: PluginDesiredState
    package_revision: PluginPackageRevisionRefV1 | None
    actor_id: str
    policy_revision: str
    approval_reference: str | None = None
    schema_version: int = PLUGIN_DESIRED_STATE_MUTATION_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.operation_id, name="operation id")
        _require_nonempty(self.idempotency_key, name="idempotency key")
        _require_nonnegative_integer(
            self.expected_inventory_revision,
            name="expected inventory revision",
        )
        if self.desired_state not in _DESIRED_STATES:
            raise ValueError("Unsupported Plugin desired state")
        if (
            self.package_revision is not None
            and self.package_revision.plugin_id != self.installation_key.plugin_id
        ):
            raise ValueError("Package revision does not match installation Plugin id")
        if self.desired_state == "absent" and self.package_revision is not None:
            raise ValueError("Remove mutation cannot carry a package revision")
        _require_nonempty(self.actor_id, name="actor id")
        _require_nonempty(self.policy_revision, name="policy revision")
        if self.approval_reference is not None:
            _require_nonempty(self.approval_reference, name="approval reference")
        _require_version(
            self.schema_version,
            expected=PLUGIN_DESIRED_STATE_MUTATION_VERSION,
        )

    @property
    def digest(self) -> str:
        return sha256(StrictPluginJsonCodec.encode(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "actorId": self.actor_id,
            "approvalReference": self.approval_reference,
            "desiredState": self.desired_state,
            "expectedInventoryRevision": self.expected_inventory_revision,
            "idempotencyKey": self.idempotency_key,
            "installationKey": self.installation_key.to_dict(),
            "operationId": self.operation_id,
            "packageRevision": (
                None
                if self.package_revision is None
                else self.package_revision.to_dict()
            ),
            "policyRevision": self.policy_revision,
            "schemaVersion": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginDesiredStateMutationV1:
        document = _decode_document(
            value,
            name="Plugin desired-state mutation",
            schema=_PLUGINDESIREDSTATEMUTATION_SCHEMA,
            version=PLUGIN_DESIRED_STATE_MUTATION_VERSION,
        )
        try:
            desired_state = _wire_string(
                document["desiredState"],
                name="Plugin desired state",
            )
            if desired_state not in _DESIRED_STATES:
                raise ValueError("Unsupported Plugin desired state")
            document["desiredState"] = desired_state
            return _PLUGINDESIREDSTATEMUTATION_SCHEMA.decode(cls, document)
        except PluginLifecycleCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginDesiredStateTransitionV1:
    inventory_revision: int
    transition_kind: PluginDesiredTransitionKind
    mutation: PluginDesiredStateMutationV1
    previous_state: PluginInstallationStateV1
    committed_state: PluginInstallationStateV1
    record_version: int = PLUGIN_DESIRED_STATE_TRANSITION_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.inventory_revision, name="inventory revision")
        if self.transition_kind not in _TRANSITION_KINDS:
            raise ValueError("Unsupported Plugin desired-state transition kind")
        if self.inventory_revision != self.mutation.expected_inventory_revision + 1:
            raise ValueError(
                "Transition inventory revision does not match mutation CAS"
            )
        key = self.mutation.installation_key
        if (
            self.previous_state.installation_key != key
            or self.committed_state.installation_key != key
        ):
            raise ValueError("Transition installation keys do not match")
        _require_version(
            self.record_version,
            expected=PLUGIN_DESIRED_STATE_TRANSITION_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "committedState": self.committed_state.to_dict(),
            "inventoryRevision": self.inventory_revision,
            "mutation": self.mutation.to_dict(),
            "previousState": self.previous_state.to_dict(),
            "recordVersion": self.record_version,
            "transitionKind": self.transition_kind,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginDesiredStateTransitionV1:
        document = _decode_document(
            value,
            name="Plugin desired-state transition",
            schema=_PLUGINDESIREDSTATETRANSITION_SCHEMA,
            version=PLUGIN_DESIRED_STATE_TRANSITION_VERSION,
            version_field="recordVersion",
        )
        try:
            kind = _wire_string(
                document["transitionKind"],
                name="Plugin desired-state transition kind",
            )
            if kind not in _TRANSITION_KINDS:
                raise ValueError("Unsupported Plugin desired-state transition kind")
            document["transitionKind"] = kind
            return _PLUGINDESIREDSTATETRANSITION_SCHEMA.decode(cls, document)
        except PluginLifecycleCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


PLUGIN_DESIRED_STATE_TRANSITION_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginDesiredStateTransitionV1.to_dict,
    decoder=PluginDesiredStateTransitionV1.from_dict,
)


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid_record(f"{name} must be a non-empty string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_integer(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid_record(f"{name} must be an integer")
    return value


def _wire_optional_instance_ref(value: object) -> PluginInstanceRevisionRef | None:
    if value is None:
        return None
    try:
        return PluginInstanceRevisionRef.from_dict(value)
    except PluginDeclarationCodecError as exc:
        raise _invalid_record(str(exc)) from exc


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_sha256(value: str, *, name: str) -> None:
    _require_nonempty(value, name=name)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_digest(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any((character not in "0123456789abcdef" for character in value))
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_nonnegative_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_positive_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_version(value: int, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise ValueError("Unsupported Plugin lifecycle record version")


def _invalid_record(message: str) -> PluginLifecycleCodecError:
    return PluginLifecycleCodecError(
        message,
        code="invalid_plugin_lifecycle_record",
    )


__all__ = [
    "PLUGIN_DESIRED_SELECTION_VERSION",
    "PLUGIN_DESIRED_STATE_MUTATION_VERSION",
    "PLUGIN_DESIRED_STATE_TRANSITION_CODEC",
    "PLUGIN_DESIRED_STATE_TRANSITION_VERSION",
    "PLUGIN_INSTALLATION_KEY_VERSION",
    "PLUGIN_INSTALLATION_STATE_VERSION",
    "PLUGIN_PACKAGE_REVISION_REF_VERSION",
    "PluginDesiredSelectionV1",
    "PluginDesiredState",
    "PluginDesiredStateMutationV1",
    "PluginDesiredStateTransitionV1",
    "PluginDesiredTransitionKind",
    "PluginInstallationKeyV1",
    "PluginInstallationScope",
    "PluginInstallationStateV1",
    "PluginLifecycleCodecError",
    "PluginPackageRevisionRefV1",
]


_PLUGINPACKAGEREVISIONREF_SCHEMA = RecordSchema.for_dataclass(
    PluginPackageRevisionRefV1,
    _wire_string,
    RecordField("plugin_id", "Plugin id"),
    RecordField("plugin_version", "Plugin version", _wire_optional_string),
    RecordField("schema_version", decoder=int),
    derive_labels=True,
)


_PLUGININSTALLATIONKEY_SCHEMA = RecordSchema.for_dataclass(
    PluginInstallationKeyV1,
    _wire_string,
    RecordField("product_id", "Product id"),
    RecordField("installation_scope", decoder=lambda value: value),
    RecordField("plugin_id", "Plugin id"),
    RecordField("schema_version", decoder=int),
    derive_labels=True,
)


_PLUGINDESIREDSELECTION_SCHEMA = RecordSchema.for_dataclass(
    PluginDesiredSelectionV1,
    _wire_string,
    RecordField("desired_state", decoder=lambda value: value),
    RecordField("package_revision", decoder=lambda value: value),
    RecordField("instance_revision_ref", decoder=lambda value: value),
    RecordField("schema_version", decoder=int),
    derive_labels=True,
)


_PLUGININSTALLATIONSTATE_SCHEMA = RecordSchema.for_dataclass(
    PluginInstallationStateV1,
    _wire_string,
    RecordField("installation_key", decoder=PluginInstallationKeyV1.from_dict),
    RecordField("selection", decoder=PluginDesiredSelectionV1.from_dict),
    RecordField("latest_instance_revision_ref", decoder=_wire_optional_instance_ref),
    RecordField("schema_version", decoder=int),
    derive_labels=True,
)


_PLUGINDESIREDSTATEMUTATION_SCHEMA = RecordSchema.for_dataclass(
    PluginDesiredStateMutationV1,
    _wire_string,
    RecordField(
        "expected_inventory_revision", "expected inventory revision", _wire_integer
    ),
    RecordField("installation_key", decoder=PluginInstallationKeyV1.from_dict),
    RecordField("desired_state", decoder=lambda value: value),
    RecordField(
        "package_revision",
        decoder=lambda value: decode_nullable(
            value, decoder=PluginPackageRevisionRefV1.from_dict
        ),
    ),
    RecordField("approval_reference", "approval reference", _wire_optional_string),
    RecordField("schema_version", decoder=int),
    derive_labels=True,
)


_PLUGINDESIREDSTATETRANSITION_SCHEMA = RecordSchema.for_dataclass(
    PluginDesiredStateTransitionV1,
    _wire_string,
    RecordField("inventory_revision", "inventory revision", _wire_integer),
    RecordField("transition_kind", decoder=lambda value: value),
    RecordField("mutation", decoder=PluginDesiredStateMutationV1.from_dict),
    RecordField("previous_state", decoder=PluginInstallationStateV1.from_dict),
    RecordField("committed_state", decoder=PluginInstallationStateV1.from_dict),
    RecordField("record_version", decoder=int),
    derive_labels=True,
)


def _record_document(
    value: object,
    *,
    name: str,
    schema: RecordSchema,
    version: int,
    version_field: str = "schemaVersion",
    invalid_record: Callable[[str], Exception],
    unsupported_version: Callable[[], Exception],
) -> dict[str, object]:
    """Admit one owned JSON document; each record owner keeps its diagnostics."""
    try:
        document = cast(dict[str, object], require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise invalid_record(str(exc)) from exc
    keys = schema.keys
    actual = set(document)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise invalid_record(
            f"{name} fields do not match; missing={missing!r}, unknown={unknown!r}"
        )
    selected_version = document.get(version_field)
    if (
        not isinstance(selected_version, int)
        or isinstance(selected_version, bool)
        or selected_version != version
    ):
        raise unsupported_version()
    return document


_decode_document = partial(
    _record_document,
    invalid_record=_invalid_record,
    unsupported_version=lambda: PluginLifecycleCodecError(
        "Unsupported Plugin lifecycle record version",
        code="unsupported_plugin_lifecycle_record_version",
    ),
)
