from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, TypeVar, cast

from loushang.foundation.json import JsonValueError, require_json_mapping
from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalCodecError,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginLifecycleCodecError,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.retirement import (
    PluginRetirementIntentV1,
    PluginRetirementRecordCodecError,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import PluginDeclarationCodecError
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

PLUGIN_INSTANCE_LEASE_MEMBER_VERSION = 1
PLUGIN_INSTANCE_LEASE_FAMILY_VERSION = 1
PLUGIN_INSTANCE_ACTIVATION_VERSION = 1
PLUGIN_INSTANCE_FAMILY_RELEASE_VERSION = 1
PLUGIN_INSTANCE_REVOCATION_VERSION = 1
PLUGIN_INSTANCE_RETIREMENT_COMPLETION_VERSION = 1
PLUGIN_INSTANCE_RUNTIME_EVENT_VERSION = 1

PluginInstanceRuntimeState = Literal[
    "ACTIVE",
    "DRAINING",
    "REVOKING",
    "RETIRED",
]
PluginInstanceLeaseKind = Literal[
    "direct_host",
    "independent",
    "owner_generation",
    "session_membership",
    "agent_membership",
]
PluginInstanceRuntimeEventKind = Literal[
    "activated",
    "family_acquired",
    "drain_started",
    "revoke_started",
    "family_released",
    "retired",
]
PluginInstanceRetirementCompletionKind = Literal["graceful", "security"]

_LEASE_KINDS = frozenset(
    {
        "direct_host",
        "independent",
        "owner_generation",
        "session_membership",
        "agent_membership",
    }
)
_RESULT_CODE_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789._-:"
)
_NestedT = TypeVar("_NestedT")


class PluginInstanceRuntimeRecordCodecError(JournalCodecError):
    """Strict Plugin Instance runtime record decoding failure."""


@dataclass(frozen=True, slots=True)
class PluginInstanceLeaseMemberV1:
    lease_id: str
    family_id: str
    installation_key: PluginInstallationKeyV1
    instance_revision_ref: PluginInstanceRevisionRef
    package_revision: PluginPackageRevisionRefV1
    member_version: int = PLUGIN_INSTANCE_LEASE_MEMBER_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.lease_id, name="Plugin Instance lease id")
        _require_sha256(self.family_id, name="Plugin Instance lease family id")
        _require_version(
            self.member_version,
            expected=PLUGIN_INSTANCE_LEASE_MEMBER_VERSION,
        )
        plugin_id = self.installation_key.plugin_id
        if (
            self.instance_revision_ref.plugin_id != plugin_id
            or self.package_revision.plugin_id != plugin_id
        ):
            raise ValueError("Plugin Instance lease member identities do not match")
        if self.lease_id != plugin_instance_lease_id(
            family_id=self.family_id,
            installation_key=self.installation_key,
            instance_revision_ref=self.instance_revision_ref,
            package_revision=self.package_revision,
        ):
            raise ValueError("Plugin Instance lease id does not match its fields")

    @classmethod
    def create(
        cls,
        *,
        family_id: str,
        installation_key: PluginInstallationKeyV1,
        instance_revision_ref: PluginInstanceRevisionRef,
        package_revision: PluginPackageRevisionRefV1,
    ) -> PluginInstanceLeaseMemberV1:
        return cls(
            lease_id=plugin_instance_lease_id(
                family_id=family_id,
                installation_key=installation_key,
                instance_revision_ref=instance_revision_ref,
                package_revision=package_revision,
            ),
            family_id=family_id,
            installation_key=installation_key,
            instance_revision_ref=instance_revision_ref,
            package_revision=package_revision,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "familyId": self.family_id,
            "installationKey": self.installation_key.to_dict(),
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "leaseId": self.lease_id,
            "memberVersion": self.member_version,
            "packageRevision": self.package_revision.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstanceLeaseMemberV1:
        document = _wire_object(value, name="Plugin Instance lease member")
        _wire_exact_fields(
            document,
            keys={
                "familyId",
                "installationKey",
                "instanceRevisionRef",
                "leaseId",
                "memberVersion",
                "packageRevision",
            },
            name="Plugin Instance lease member",
        )
        _wire_version(
            document.get("memberVersion"),
            expected=PLUGIN_INSTANCE_LEASE_MEMBER_VERSION,
        )
        try:
            return cls(
                lease_id=_wire_string(document["leaseId"], name="lease id"),
                family_id=_wire_string(document["familyId"], name="family id"),
                installation_key=PluginInstallationKeyV1.from_dict(
                    document["installationKey"]
                ),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                package_revision=PluginPackageRevisionRefV1.from_dict(
                    document["packageRevision"]
                ),
                member_version=PLUGIN_INSTANCE_LEASE_MEMBER_VERSION,
            )
        except PluginInstanceRuntimeRecordCodecError:
            raise
        except (
            PluginDeclarationCodecError,
            PluginLifecycleCodecError,
            TypeError,
            ValueError,
        ) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginInstanceLeaseFamilyV1:
    family_id: str
    lease_kind: PluginInstanceLeaseKind
    operation_id: str
    idempotency_key: str
    holder_reference: str
    parent_family_id: str | None
    source_inventory_revision: int | None
    members: tuple[PluginInstanceLeaseMemberV1, ...]
    family_version: int = PLUGIN_INSTANCE_LEASE_FAMILY_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.family_id, name="Plugin Instance lease family id")
        if self.lease_kind not in _LEASE_KINDS:
            raise ValueError("Unsupported Plugin Instance lease kind")
        for value, name in (
            (self.operation_id, "Plugin Instance lease operation id"),
            (self.idempotency_key, "Plugin Instance lease idempotency key"),
            (self.holder_reference, "Plugin Instance lease holder reference"),
        ):
            _require_nonempty(value, name=name)
        _require_version(
            self.family_version,
            expected=PLUGIN_INSTANCE_LEASE_FAMILY_VERSION,
        )
        if not self.members:
            raise ValueError("Plugin Instance lease family must not be empty")
        expected_members = tuple(
            sorted(self.members, key=lambda item: item.installation_key)
        )
        if self.members != expected_members:
            raise ValueError("Plugin Instance lease members must be sorted")
        installation_keys = tuple(item.installation_key for item in self.members)
        instance_refs = tuple(item.instance_revision_ref for item in self.members)
        if len(installation_keys) != len(set(installation_keys)):
            raise ValueError("Plugin Instance lease Installations must be unique")
        if len(instance_refs) != len(set(instance_refs)):
            raise ValueError("Plugin Instance lease revisions must be unique")
        if any(member.family_id != self.family_id for member in self.members):
            raise ValueError("Plugin Instance lease member has the wrong family")
        if (
            self.lease_kind in {"direct_host", "independent", "owner_generation"}
            and len(self.members) != 1
        ):
            raise ValueError("Plugin Instance lease kind requires one member")
        if self.lease_kind == "agent_membership":
            if self.parent_family_id is None:
                raise ValueError("Agent membership requires a parent family")
            if self.source_inventory_revision is not None:
                raise ValueError("Derived membership has no desired-state revision")
        else:
            if self.parent_family_id is not None:
                raise ValueError("Root Plugin Instance lease cannot have a parent")
            if self.source_inventory_revision is None:
                raise ValueError(
                    "Root Plugin Instance lease requires a source inventory revision"
                )
            _require_positive_integer(
                self.source_inventory_revision,
                name="source inventory revision",
            )
        if self.family_id != plugin_instance_lease_family_id(
            lease_kind=self.lease_kind,
            operation_id=self.operation_id,
            idempotency_key=self.idempotency_key,
            holder_reference=self.holder_reference,
            parent_family_id=self.parent_family_id,
            source_inventory_revision=self.source_inventory_revision,
            member_subjects=tuple(
                (
                    member.installation_key,
                    member.instance_revision_ref,
                    member.package_revision,
                )
                for member in self.members
            ),
        ):
            raise ValueError("Plugin Instance lease family id does not match its fields")

    @classmethod
    def create(
        cls,
        *,
        lease_kind: PluginInstanceLeaseKind,
        operation_id: str,
        idempotency_key: str,
        holder_reference: str,
        parent_family_id: str | None,
        source_inventory_revision: int | None,
        member_subjects: tuple[
            tuple[
                PluginInstallationKeyV1,
                PluginInstanceRevisionRef,
                PluginPackageRevisionRefV1,
            ],
            ...,
        ],
    ) -> PluginInstanceLeaseFamilyV1:
        family_id = plugin_instance_lease_family_id(
            lease_kind=lease_kind,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            holder_reference=holder_reference,
            parent_family_id=parent_family_id,
            source_inventory_revision=source_inventory_revision,
            member_subjects=member_subjects,
        )
        return cls(
            family_id=family_id,
            lease_kind=lease_kind,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            holder_reference=holder_reference,
            parent_family_id=parent_family_id,
            source_inventory_revision=source_inventory_revision,
            members=tuple(
                PluginInstanceLeaseMemberV1.create(
                    family_id=family_id,
                    installation_key=installation_key,
                    instance_revision_ref=instance_revision_ref,
                    package_revision=package_revision,
                )
                for installation_key, instance_revision_ref, package_revision in member_subjects
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "familyId": self.family_id,
            "familyVersion": self.family_version,
            "holderReference": self.holder_reference,
            "idempotencyKey": self.idempotency_key,
            "leaseKind": self.lease_kind,
            "members": [member.to_dict() for member in self.members],
            "operationId": self.operation_id,
            "parentFamilyId": self.parent_family_id,
            "sourceInventoryRevision": self.source_inventory_revision,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstanceLeaseFamilyV1:
        document = _wire_object(value, name="Plugin Instance lease family")
        _wire_exact_fields(
            document,
            keys={
                "familyId",
                "familyVersion",
                "holderReference",
                "idempotencyKey",
                "leaseKind",
                "members",
                "operationId",
                "parentFamilyId",
                "sourceInventoryRevision",
            },
            name="Plugin Instance lease family",
        )
        _wire_version(
            document.get("familyVersion"),
            expected=PLUGIN_INSTANCE_LEASE_FAMILY_VERSION,
        )
        try:
            lease_kind = _wire_string(document["leaseKind"], name="lease kind")
            if lease_kind not in _LEASE_KINDS:
                raise ValueError("Unsupported Plugin Instance lease kind")
            members = document["members"]
            if not isinstance(members, list):
                raise ValueError("Plugin Instance lease members must be a JSON array")
            return cls(
                family_id=_wire_string(document["familyId"], name="family id"),
                lease_kind=cast(PluginInstanceLeaseKind, lease_kind),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                holder_reference=_wire_string(
                    document["holderReference"], name="holder reference"
                ),
                parent_family_id=_wire_optional_string(
                    document["parentFamilyId"], name="parent family id"
                ),
                source_inventory_revision=_wire_optional_integer(
                    document["sourceInventoryRevision"],
                    name="source inventory revision",
                ),
                members=tuple(
                    PluginInstanceLeaseMemberV1.from_dict(member)
                    for member in members
                ),
                family_version=PLUGIN_INSTANCE_LEASE_FAMILY_VERSION,
            )
        except PluginInstanceRuntimeRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginInstanceActivationV1:
    activation_id: str
    installation_key: PluginInstallationKeyV1
    instance_revision_ref: PluginInstanceRevisionRef
    package_revision: PluginPackageRevisionRefV1
    source_inventory_revision: int
    direct_host_family: PluginInstanceLeaseFamilyV1
    activation_version: int = PLUGIN_INSTANCE_ACTIVATION_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.activation_id, name="Plugin Instance activation id")
        _require_positive_integer(
            self.source_inventory_revision,
            name="activation source inventory revision",
        )
        _require_version(
            self.activation_version,
            expected=PLUGIN_INSTANCE_ACTIVATION_VERSION,
        )
        plugin_id = self.installation_key.plugin_id
        if (
            self.instance_revision_ref.plugin_id != plugin_id
            or self.package_revision.plugin_id != plugin_id
        ):
            raise ValueError("Plugin Instance activation identities do not match")
        family = self.direct_host_family
        if (
            family.lease_kind != "direct_host"
            or family.source_inventory_revision != self.source_inventory_revision
            or len(family.members) != 1
        ):
            raise ValueError("Plugin Instance activation requires its direct host")
        member = family.members[0]
        if (
            member.installation_key != self.installation_key
            or member.instance_revision_ref != self.instance_revision_ref
            or member.package_revision != self.package_revision
        ):
            raise ValueError("Plugin Instance activation direct host does not match")
        if self.activation_id != plugin_instance_activation_id(
            installation_key=self.installation_key,
            instance_revision_ref=self.instance_revision_ref,
            package_revision=self.package_revision,
            source_inventory_revision=self.source_inventory_revision,
            direct_host_family=self.direct_host_family,
        ):
            raise ValueError("Plugin Instance activation id does not match its fields")

    @classmethod
    def create(
        cls,
        *,
        installation_key: PluginInstallationKeyV1,
        instance_revision_ref: PluginInstanceRevisionRef,
        package_revision: PluginPackageRevisionRefV1,
        source_inventory_revision: int,
        operation_id: str,
        idempotency_key: str,
        direct_host_reference: str,
    ) -> PluginInstanceActivationV1:
        family = PluginInstanceLeaseFamilyV1.create(
            lease_kind="direct_host",
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            holder_reference=direct_host_reference,
            parent_family_id=None,
            source_inventory_revision=source_inventory_revision,
            member_subjects=(
                (installation_key, instance_revision_ref, package_revision),
            ),
        )
        return cls(
            activation_id=plugin_instance_activation_id(
                installation_key=installation_key,
                instance_revision_ref=instance_revision_ref,
                package_revision=package_revision,
                source_inventory_revision=source_inventory_revision,
                direct_host_family=family,
            ),
            installation_key=installation_key,
            instance_revision_ref=instance_revision_ref,
            package_revision=package_revision,
            source_inventory_revision=source_inventory_revision,
            direct_host_family=family,
        )

    @property
    def operation_id(self) -> str:
        return self.direct_host_family.operation_id

    @property
    def idempotency_key(self) -> str:
        return self.direct_host_family.idempotency_key

    def to_dict(self) -> dict[str, object]:
        return {
            "activationId": self.activation_id,
            "activationVersion": self.activation_version,
            "directHostFamily": self.direct_host_family.to_dict(),
            "installationKey": self.installation_key.to_dict(),
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "packageRevision": self.package_revision.to_dict(),
            "sourceInventoryRevision": self.source_inventory_revision,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstanceActivationV1:
        document = _wire_object(value, name="Plugin Instance activation")
        _wire_exact_fields(
            document,
            keys={
                "activationId",
                "activationVersion",
                "directHostFamily",
                "installationKey",
                "instanceRevisionRef",
                "packageRevision",
                "sourceInventoryRevision",
            },
            name="Plugin Instance activation",
        )
        _wire_version(
            document.get("activationVersion"),
            expected=PLUGIN_INSTANCE_ACTIVATION_VERSION,
        )
        try:
            return cls(
                activation_id=_wire_string(
                    document["activationId"], name="activation id"
                ),
                installation_key=PluginInstallationKeyV1.from_dict(
                    document["installationKey"]
                ),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                package_revision=PluginPackageRevisionRefV1.from_dict(
                    document["packageRevision"]
                ),
                source_inventory_revision=_wire_integer(
                    document["sourceInventoryRevision"],
                    name="source inventory revision",
                ),
                direct_host_family=PluginInstanceLeaseFamilyV1.from_dict(
                    document["directHostFamily"]
                ),
                activation_version=PLUGIN_INSTANCE_ACTIVATION_VERSION,
            )
        except PluginInstanceRuntimeRecordCodecError:
            raise
        except (
            PluginDeclarationCodecError,
            PluginLifecycleCodecError,
            TypeError,
            ValueError,
        ) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginInstanceLeaseFamilyReleaseV1:
    family_id: str
    operation_id: str
    idempotency_key: str
    release_reference: str
    release_version: int = PLUGIN_INSTANCE_FAMILY_RELEASE_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.family_id, name="Plugin Instance lease family id")
        for value, name in (
            (self.operation_id, "Plugin Instance release operation id"),
            (self.idempotency_key, "Plugin Instance release idempotency key"),
            (self.release_reference, "Plugin Instance release reference"),
        ):
            _require_nonempty(value, name=name)
        _require_version(
            self.release_version,
            expected=PLUGIN_INSTANCE_FAMILY_RELEASE_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "familyId": self.family_id,
            "idempotencyKey": self.idempotency_key,
            "operationId": self.operation_id,
            "releaseReference": self.release_reference,
            "releaseVersion": self.release_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstanceLeaseFamilyReleaseV1:
        document = _wire_object(value, name="Plugin Instance lease family release")
        _wire_exact_fields(
            document,
            keys={
                "familyId",
                "idempotencyKey",
                "operationId",
                "releaseReference",
                "releaseVersion",
            },
            name="Plugin Instance lease family release",
        )
        _wire_version(
            document.get("releaseVersion"),
            expected=PLUGIN_INSTANCE_FAMILY_RELEASE_VERSION,
        )
        try:
            return cls(
                family_id=_wire_string(document["familyId"], name="family id"),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                release_reference=_wire_string(
                    document["releaseReference"], name="release reference"
                ),
                release_version=PLUGIN_INSTANCE_FAMILY_RELEASE_VERSION,
            )
        except PluginInstanceRuntimeRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginInstanceRevocationV1:
    revocation_id: str
    installation_key: PluginInstallationKeyV1
    instance_revision_ref: PluginInstanceRevisionRef
    operation_id: str
    idempotency_key: str
    authority_reference: str
    reason_code: str
    revocation_version: int = PLUGIN_INSTANCE_REVOCATION_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.revocation_id, name="Plugin Instance revocation id")
        if self.instance_revision_ref.plugin_id != self.installation_key.plugin_id:
            raise ValueError("Plugin Instance revocation identities do not match")
        for value, name in (
            (self.operation_id, "Plugin Instance revocation operation id"),
            (self.idempotency_key, "Plugin Instance revocation idempotency key"),
            (self.authority_reference, "Plugin Instance revocation authority"),
        ):
            _require_nonempty(value, name=name)
        _require_result_code(self.reason_code)
        _require_version(
            self.revocation_version,
            expected=PLUGIN_INSTANCE_REVOCATION_VERSION,
        )
        if self.revocation_id != plugin_instance_revocation_id(
            installation_key=self.installation_key,
            instance_revision_ref=self.instance_revision_ref,
            operation_id=self.operation_id,
            idempotency_key=self.idempotency_key,
            authority_reference=self.authority_reference,
            reason_code=self.reason_code,
        ):
            raise ValueError("Plugin Instance revocation id does not match its fields")

    @classmethod
    def create(
        cls,
        *,
        installation_key: PluginInstallationKeyV1,
        instance_revision_ref: PluginInstanceRevisionRef,
        operation_id: str,
        idempotency_key: str,
        authority_reference: str,
        reason_code: str,
    ) -> PluginInstanceRevocationV1:
        return cls(
            revocation_id=plugin_instance_revocation_id(
                installation_key=installation_key,
                instance_revision_ref=instance_revision_ref,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                authority_reference=authority_reference,
                reason_code=reason_code,
            ),
            installation_key=installation_key,
            instance_revision_ref=instance_revision_ref,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            authority_reference=authority_reference,
            reason_code=reason_code,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "authorityReference": self.authority_reference,
            "idempotencyKey": self.idempotency_key,
            "installationKey": self.installation_key.to_dict(),
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "operationId": self.operation_id,
            "reasonCode": self.reason_code,
            "revocationId": self.revocation_id,
            "revocationVersion": self.revocation_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstanceRevocationV1:
        document = _wire_object(value, name="Plugin Instance revocation")
        _wire_exact_fields(
            document,
            keys={
                "authorityReference",
                "idempotencyKey",
                "installationKey",
                "instanceRevisionRef",
                "operationId",
                "reasonCode",
                "revocationId",
                "revocationVersion",
            },
            name="Plugin Instance revocation",
        )
        _wire_version(
            document.get("revocationVersion"),
            expected=PLUGIN_INSTANCE_REVOCATION_VERSION,
        )
        try:
            return cls(
                revocation_id=_wire_string(
                    document["revocationId"], name="revocation id"
                ),
                installation_key=PluginInstallationKeyV1.from_dict(
                    document["installationKey"]
                ),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                authority_reference=_wire_string(
                    document["authorityReference"], name="authority reference"
                ),
                reason_code=_wire_string(
                    document["reasonCode"], name="reason code"
                ),
                revocation_version=PLUGIN_INSTANCE_REVOCATION_VERSION,
            )
        except PluginInstanceRuntimeRecordCodecError:
            raise
        except (
            PluginDeclarationCodecError,
            PluginLifecycleCodecError,
            TypeError,
            ValueError,
        ) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginInstanceRetirementCompletionV1:
    completion_id: str
    completion_kind: PluginInstanceRetirementCompletionKind
    coordination_id: str
    installation_key: PluginInstallationKeyV1
    instance_revision_ref: PluginInstanceRevisionRef
    operation_id: str
    idempotency_key: str
    completion_reference: str
    completion_version: int = PLUGIN_INSTANCE_RETIREMENT_COMPLETION_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.completion_id, name="Plugin Instance completion id")
        _require_sha256(self.coordination_id, name="Plugin Instance coordination id")
        if self.completion_kind not in {"graceful", "security"}:
            raise ValueError("Unsupported Plugin Instance completion kind")
        if self.instance_revision_ref.plugin_id != self.installation_key.plugin_id:
            raise ValueError("Plugin Instance completion identities do not match")
        for value, name in (
            (self.operation_id, "Plugin Instance completion operation id"),
            (self.idempotency_key, "Plugin Instance completion idempotency key"),
            (self.completion_reference, "Plugin Instance completion reference"),
        ):
            _require_nonempty(value, name=name)
        _require_version(
            self.completion_version,
            expected=PLUGIN_INSTANCE_RETIREMENT_COMPLETION_VERSION,
        )
        if self.completion_id != plugin_instance_retirement_completion_id(
            completion_kind=self.completion_kind,
            coordination_id=self.coordination_id,
            installation_key=self.installation_key,
            instance_revision_ref=self.instance_revision_ref,
            operation_id=self.operation_id,
            idempotency_key=self.idempotency_key,
            completion_reference=self.completion_reference,
        ):
            raise ValueError("Plugin Instance completion id does not match its fields")

    @classmethod
    def create(
        cls,
        *,
        completion_kind: PluginInstanceRetirementCompletionKind,
        coordination_id: str,
        installation_key: PluginInstallationKeyV1,
        instance_revision_ref: PluginInstanceRevisionRef,
        operation_id: str,
        idempotency_key: str,
        completion_reference: str,
    ) -> PluginInstanceRetirementCompletionV1:
        return cls(
            completion_id=plugin_instance_retirement_completion_id(
                completion_kind=completion_kind,
                coordination_id=coordination_id,
                installation_key=installation_key,
                instance_revision_ref=instance_revision_ref,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                completion_reference=completion_reference,
            ),
            completion_kind=completion_kind,
            coordination_id=coordination_id,
            installation_key=installation_key,
            instance_revision_ref=instance_revision_ref,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            completion_reference=completion_reference,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "completionId": self.completion_id,
            "completionKind": self.completion_kind,
            "completionReference": self.completion_reference,
            "completionVersion": self.completion_version,
            "coordinationId": self.coordination_id,
            "idempotencyKey": self.idempotency_key,
            "installationKey": self.installation_key.to_dict(),
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "operationId": self.operation_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstanceRetirementCompletionV1:
        document = _wire_object(value, name="Plugin Instance retirement completion")
        _wire_exact_fields(
            document,
            keys={
                "completionId",
                "completionKind",
                "completionReference",
                "completionVersion",
                "coordinationId",
                "idempotencyKey",
                "installationKey",
                "instanceRevisionRef",
                "operationId",
            },
            name="Plugin Instance retirement completion",
        )
        _wire_version(
            document.get("completionVersion"),
            expected=PLUGIN_INSTANCE_RETIREMENT_COMPLETION_VERSION,
        )
        try:
            kind = _wire_string(
                document["completionKind"], name="completion kind"
            )
            if kind not in {"graceful", "security"}:
                raise ValueError("Unsupported Plugin Instance completion kind")
            return cls(
                completion_id=_wire_string(
                    document["completionId"], name="completion id"
                ),
                completion_kind=cast(
                    PluginInstanceRetirementCompletionKind,
                    kind,
                ),
                coordination_id=_wire_string(
                    document["coordinationId"], name="coordination id"
                ),
                installation_key=PluginInstallationKeyV1.from_dict(
                    document["installationKey"]
                ),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                operation_id=_wire_string(
                    document["operationId"], name="operation id"
                ),
                idempotency_key=_wire_string(
                    document["idempotencyKey"], name="idempotency key"
                ),
                completion_reference=_wire_string(
                    document["completionReference"], name="completion reference"
                ),
                completion_version=PLUGIN_INSTANCE_RETIREMENT_COMPLETION_VERSION,
            )
        except PluginInstanceRuntimeRecordCodecError:
            raise
        except (
            PluginDeclarationCodecError,
            PluginLifecycleCodecError,
            TypeError,
            ValueError,
        ) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginInstanceRuntimeEventV1:
    journal_revision: int
    event_kind: PluginInstanceRuntimeEventKind
    activation: PluginInstanceActivationV1 | None
    family: PluginInstanceLeaseFamilyV1 | None
    retirement_intent: PluginRetirementIntentV1 | None
    revocation: PluginInstanceRevocationV1 | None
    release: PluginInstanceLeaseFamilyReleaseV1 | None
    completion: PluginInstanceRetirementCompletionV1 | None
    record_version: int = PLUGIN_INSTANCE_RUNTIME_EVENT_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.journal_revision, name="journal revision")
        if self.event_kind not in {
            "activated",
            "family_acquired",
            "drain_started",
            "revoke_started",
            "family_released",
            "retired",
        }:
            raise ValueError("Unsupported Plugin Instance runtime event kind")
        _require_version(
            self.record_version,
            expected=PLUGIN_INSTANCE_RUNTIME_EVENT_VERSION,
        )
        expected = {
            "activated": (True, False, False, False, False, False),
            "family_acquired": (False, True, False, False, False, False),
            "drain_started": (False, False, True, False, False, False),
            "revoke_started": (False, False, False, True, False, False),
            "family_released": (False, False, False, False, True, False),
            "retired": (False, False, False, False, False, True),
        }[self.event_kind]
        actual = tuple(
            item is not None
            for item in (
                self.activation,
                self.family,
                self.retirement_intent,
                self.revocation,
                self.release,
                self.completion,
            )
        )
        if actual != expected:
            raise ValueError("Plugin Instance runtime event payload is inconsistent")

    @classmethod
    def activated(
        cls,
        *,
        journal_revision: int,
        activation: PluginInstanceActivationV1,
    ) -> PluginInstanceRuntimeEventV1:
        return cls(
            journal_revision=journal_revision,
            event_kind="activated",
            activation=activation,
            family=None,
            retirement_intent=None,
            revocation=None,
            release=None,
            completion=None,
        )

    @classmethod
    def family_acquired(
        cls,
        *,
        journal_revision: int,
        family: PluginInstanceLeaseFamilyV1,
    ) -> PluginInstanceRuntimeEventV1:
        return cls(
            journal_revision=journal_revision,
            event_kind="family_acquired",
            activation=None,
            family=family,
            retirement_intent=None,
            revocation=None,
            release=None,
            completion=None,
        )

    @classmethod
    def drain_started(
        cls,
        *,
        journal_revision: int,
        retirement_intent: PluginRetirementIntentV1,
    ) -> PluginInstanceRuntimeEventV1:
        return cls(
            journal_revision=journal_revision,
            event_kind="drain_started",
            activation=None,
            family=None,
            retirement_intent=retirement_intent,
            revocation=None,
            release=None,
            completion=None,
        )

    @classmethod
    def revoke_started(
        cls,
        *,
        journal_revision: int,
        revocation: PluginInstanceRevocationV1,
    ) -> PluginInstanceRuntimeEventV1:
        return cls(
            journal_revision=journal_revision,
            event_kind="revoke_started",
            activation=None,
            family=None,
            retirement_intent=None,
            revocation=revocation,
            release=None,
            completion=None,
        )

    @classmethod
    def family_released(
        cls,
        *,
        journal_revision: int,
        release: PluginInstanceLeaseFamilyReleaseV1,
    ) -> PluginInstanceRuntimeEventV1:
        return cls(
            journal_revision=journal_revision,
            event_kind="family_released",
            activation=None,
            family=None,
            retirement_intent=None,
            revocation=None,
            release=release,
            completion=None,
        )

    @classmethod
    def retired(
        cls,
        *,
        journal_revision: int,
        completion: PluginInstanceRetirementCompletionV1,
    ) -> PluginInstanceRuntimeEventV1:
        return cls(
            journal_revision=journal_revision,
            event_kind="retired",
            activation=None,
            family=None,
            retirement_intent=None,
            revocation=None,
            release=None,
            completion=completion,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "activation": (
                None if self.activation is None else self.activation.to_dict()
            ),
            "completion": (
                None if self.completion is None else self.completion.to_dict()
            ),
            "eventKind": self.event_kind,
            "family": None if self.family is None else self.family.to_dict(),
            "journalRevision": self.journal_revision,
            "recordVersion": self.record_version,
            "release": None if self.release is None else self.release.to_dict(),
            "retirementIntent": (
                None
                if self.retirement_intent is None
                else self.retirement_intent.to_dict()
            ),
            "revocation": (
                None if self.revocation is None else self.revocation.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstanceRuntimeEventV1:
        document = _wire_object(value, name="Plugin Instance runtime event")
        _wire_exact_fields(
            document,
            keys={
                "activation",
                "completion",
                "eventKind",
                "family",
                "journalRevision",
                "recordVersion",
                "release",
                "retirementIntent",
                "revocation",
            },
            name="Plugin Instance runtime event",
        )
        _wire_version(
            document.get("recordVersion"),
            expected=PLUGIN_INSTANCE_RUNTIME_EVENT_VERSION,
        )
        try:
            event_kind = _wire_string(
                document["eventKind"], name="runtime event kind"
            )
            if event_kind not in {
                "activated",
                "family_acquired",
                "drain_started",
                "revoke_started",
                "family_released",
                "retired",
            }:
                raise ValueError("Unsupported Plugin Instance runtime event kind")
            return cls(
                journal_revision=_wire_integer(
                    document["journalRevision"], name="journal revision"
                ),
                event_kind=cast(PluginInstanceRuntimeEventKind, event_kind),
                activation=_wire_optional_nested(
                    document["activation"], PluginInstanceActivationV1.from_dict
                ),
                family=_wire_optional_nested(
                    document["family"], PluginInstanceLeaseFamilyV1.from_dict
                ),
                retirement_intent=_wire_optional_nested(
                    document["retirementIntent"], PluginRetirementIntentV1.from_dict
                ),
                revocation=_wire_optional_nested(
                    document["revocation"], PluginInstanceRevocationV1.from_dict
                ),
                release=_wire_optional_nested(
                    document["release"],
                    PluginInstanceLeaseFamilyReleaseV1.from_dict,
                ),
                completion=_wire_optional_nested(
                    document["completion"],
                    PluginInstanceRetirementCompletionV1.from_dict,
                ),
                record_version=PLUGIN_INSTANCE_RUNTIME_EVENT_VERSION,
            )
        except PluginInstanceRuntimeRecordCodecError:
            raise
        except (
            PluginRetirementRecordCodecError,
            TypeError,
            ValueError,
        ) as exc:
            raise _invalid_record(str(exc)) from exc


PLUGIN_INSTANCE_RUNTIME_EVENT_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginInstanceRuntimeEventV1.to_dict,
    decoder=PluginInstanceRuntimeEventV1.from_dict,
)


def plugin_instance_lease_family_id(
    *,
    lease_kind: PluginInstanceLeaseKind,
    operation_id: str,
    idempotency_key: str,
    holder_reference: str,
    parent_family_id: str | None,
    source_inventory_revision: int | None,
    member_subjects: tuple[
        tuple[
            PluginInstallationKeyV1,
            PluginInstanceRevisionRef,
            PluginPackageRevisionRefV1,
        ],
        ...,
    ],
) -> str:
    payload = StrictPluginJsonCodec.encode(
        {
            "holderReference": holder_reference,
            "idempotencyKey": idempotency_key,
            "leaseKind": lease_kind,
            "memberSubjects": [
                {
                    "installationKey": installation_key.to_dict(),
                    "instanceRevisionRef": instance_revision_ref.to_dict(),
                    "packageRevision": package_revision.to_dict(),
                }
                for installation_key, instance_revision_ref, package_revision in member_subjects
            ],
            "operationId": operation_id,
            "parentFamilyId": parent_family_id,
            "sourceInventoryRevision": source_inventory_revision,
        }
    )
    return sha256(b"plugin-instance-lease-family-v1\0" + payload).hexdigest()


def plugin_instance_lease_id(
    *,
    family_id: str,
    installation_key: PluginInstallationKeyV1,
    instance_revision_ref: PluginInstanceRevisionRef,
    package_revision: PluginPackageRevisionRefV1,
) -> str:
    payload = StrictPluginJsonCodec.encode(
        {
            "familyId": family_id,
            "installationKey": installation_key.to_dict(),
            "instanceRevisionRef": instance_revision_ref.to_dict(),
            "packageRevision": package_revision.to_dict(),
        }
    )
    return sha256(b"plugin-instance-lease-v1\0" + payload).hexdigest()


def plugin_instance_activation_id(
    *,
    installation_key: PluginInstallationKeyV1,
    instance_revision_ref: PluginInstanceRevisionRef,
    package_revision: PluginPackageRevisionRefV1,
    source_inventory_revision: int,
    direct_host_family: PluginInstanceLeaseFamilyV1,
) -> str:
    payload = StrictPluginJsonCodec.encode(
        {
            "directHostFamily": direct_host_family.to_dict(),
            "installationKey": installation_key.to_dict(),
            "instanceRevisionRef": instance_revision_ref.to_dict(),
            "packageRevision": package_revision.to_dict(),
            "sourceInventoryRevision": source_inventory_revision,
        }
    )
    return sha256(b"plugin-instance-activation-v1\0" + payload).hexdigest()


def plugin_instance_revocation_id(
    *,
    installation_key: PluginInstallationKeyV1,
    instance_revision_ref: PluginInstanceRevisionRef,
    operation_id: str,
    idempotency_key: str,
    authority_reference: str,
    reason_code: str,
) -> str:
    payload = StrictPluginJsonCodec.encode(
        {
            "authorityReference": authority_reference,
            "idempotencyKey": idempotency_key,
            "installationKey": installation_key.to_dict(),
            "instanceRevisionRef": instance_revision_ref.to_dict(),
            "operationId": operation_id,
            "reasonCode": reason_code,
        }
    )
    return sha256(b"plugin-instance-revocation-v1\0" + payload).hexdigest()


def plugin_instance_retirement_completion_id(
    *,
    completion_kind: PluginInstanceRetirementCompletionKind,
    coordination_id: str,
    installation_key: PluginInstallationKeyV1,
    instance_revision_ref: PluginInstanceRevisionRef,
    operation_id: str,
    idempotency_key: str,
    completion_reference: str,
) -> str:
    payload = StrictPluginJsonCodec.encode(
        {
            "completionKind": completion_kind,
            "completionReference": completion_reference,
            "coordinationId": coordination_id,
            "idempotencyKey": idempotency_key,
            "installationKey": installation_key.to_dict(),
            "instanceRevisionRef": instance_revision_ref.to_dict(),
            "operationId": operation_id,
        }
    )
    return sha256(b"plugin-instance-retirement-completion-v1\0" + payload).hexdigest()


def _wire_object(value: object, *, name: str) -> dict[str, object]:
    try:
        return cast(dict[str, object], require_json_mapping(value, name=name))
    except JsonValueError as exc:
        raise _invalid_record(str(exc)) from exc


def _wire_exact_fields(
    value: dict[str, object], *, keys: set[str], name: str
) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise _invalid_record(
            f"{name} fields do not match; missing={missing!r}, unknown={unknown!r}"
        )


def _wire_version(value: object, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise PluginInstanceRuntimeRecordCodecError(
            "Unsupported Plugin Instance runtime record version",
            code="unsupported_plugin_instance_runtime_record_version",
        )


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_integer(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _wire_optional_integer(value: object, *, name: str) -> int | None:
    if value is None:
        return None
    return _wire_integer(value, name=name)


def _wire_optional_nested(
    value: object,
    decoder: Callable[[object], _NestedT],
) -> _NestedT | None:
    if value is None:
        return None
    return decoder(value)


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_positive_integer(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_result_code(value: str) -> None:
    _require_nonempty(value, name="Plugin Instance structural result code")
    if len(value) > 128 or any(
        character not in _RESULT_CODE_CHARACTERS for character in value
    ):
        raise ValueError("Plugin Instance result code is not structural")


def _require_version(value: int, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise ValueError("Unsupported Plugin Instance runtime record version")


def _invalid_record(message: str) -> PluginInstanceRuntimeRecordCodecError:
    return PluginInstanceRuntimeRecordCodecError(
        message,
        code="invalid_plugin_instance_runtime_record",
    )


__all__ = [
    "PLUGIN_INSTANCE_ACTIVATION_VERSION",
    "PLUGIN_INSTANCE_FAMILY_RELEASE_VERSION",
    "PLUGIN_INSTANCE_LEASE_FAMILY_VERSION",
    "PLUGIN_INSTANCE_LEASE_MEMBER_VERSION",
    "PLUGIN_INSTANCE_RETIREMENT_COMPLETION_VERSION",
    "PLUGIN_INSTANCE_REVOCATION_VERSION",
    "PLUGIN_INSTANCE_RUNTIME_EVENT_CODEC",
    "PLUGIN_INSTANCE_RUNTIME_EVENT_VERSION",
    "PluginInstanceActivationV1",
    "PluginInstanceLeaseFamilyReleaseV1",
    "PluginInstanceLeaseFamilyV1",
    "PluginInstanceLeaseKind",
    "PluginInstanceLeaseMemberV1",
    "PluginInstanceRetirementCompletionKind",
    "PluginInstanceRetirementCompletionV1",
    "PluginInstanceRevocationV1",
    "PluginInstanceRuntimeEventKind",
    "PluginInstanceRuntimeEventV1",
    "PluginInstanceRuntimeRecordCodecError",
    "PluginInstanceRuntimeState",
    "plugin_instance_activation_id",
    "plugin_instance_lease_family_id",
    "plugin_instance_lease_id",
    "plugin_instance_retirement_completion_id",
    "plugin_instance_revocation_id",
]
