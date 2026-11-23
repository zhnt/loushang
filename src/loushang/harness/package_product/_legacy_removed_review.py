"""Read the old removal proof before cutover or from the authenticated fence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, ClassVar, NamedTuple, Self, cast

from loushang.harness.package_product._legacy_binding_evidence import (
    LEGACY_BINDING_CAPTURE_MAX_BYTES,
    LegacyLocalBindingEvidence,
)
from loushang.harness.package_product._legacy_inventory import (
    LEGACY_REVIEW_DIGEST,
    LEGACY_REVIEW_ID,
    LegacyInventoryFacts,
    LegacyInventoryReader,
    LegacyRemovedBinding,
    LegacyReviewWireSelections,
    _LegacyBuiltinIntent,
    _LegacyFencedReviewRecord,
    prove_removed_legacy_bindings,
    valid_legacy_disable_selections,
)
from loushang.harness.package_product._legacy_management_evidence import (
    LEGACY_DESIRED_CAPTURE_MAX_BYTES,
    LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES,
    classify_management_members,
    read_settled_management_history,
    require_empty_lock_markers,
)
from loushang.harness.package_product._legacy_runtime import _LegacyFirstSnapshot
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackageProductPreBSnapshotOwner,
)
from loushang.harness.resources.packages.product_windows_pre_b_snapshot import (
    PackageProductWindowsPreBSnapshotOwner,
)

_DOMAINS = (
    "binding_history",
    "desired_state",
    "source_configuration",
    "enablement_state",
    "instance_state",
    "lock_history",
    "store_bytes",
)
_JOURNAL_DOMAINS = ("desired_state", "instance_state", "lock_history")
_SHAPE_CHANGED = "Old removal snapshot shape changed"
LEGACY_REMOVAL_STORE_ROOTS = frozenset({"installed", "plugin-revisions"})


def _scalar_review_schema(*names: str) -> RecordSchema:
    return RecordSchema(lambda value: value, tuple(RecordField(name) for name in names))


_ENTRY_SCHEMA = _scalar_review_schema(
    "plugin_id",
    "source_identity",
    "content_digest",
    "manifest_digest",
    "dependency_lock_digest",
    "binding_digest",
    "install_operation_id",
    "remove_operation_id",
)
_REVIEW_SCHEMA = _scalar_review_schema(
    "store_id",
    "namespace_id",
    "scope_id",
    "first_fence_id",
    "snapshot_receipt_id",
    "source_projection_digest",
    "lockfile_digest",
    "desired_journal_digest",
)


class LegacyRemovalEntryRecord:
    """Versioned install/update/remove identity over one nominal entry."""

    __slots__ = ()
    _error_type: ClassVar[type[ValueError]]

    if TYPE_CHECKING:
        plugin_id: str
        source_identity: str
        content_digest: str
        manifest_digest: str
        dependency_lock_digest: str
        binding_digest: str
        install_operation_id: str
        remove_operation_id: str
        head_operation_id: str | None
        head_transition_kind: str | None

    def __post_init__(self) -> None:
        if (
            type(self.plugin_id) is not str
            or LEGACY_REVIEW_ID.fullmatch(self.plugin_id) is None
            or type(self.source_identity) is not str
            or not self.source_identity.startswith("local:/")
            or any(
                type(value) is not str or LEGACY_REVIEW_DIGEST.fullmatch(value) is None
                for value in (
                    self.content_digest,
                    self.manifest_digest,
                    self.dependency_lock_digest,
                    self.binding_digest,
                )
            )
            or any(
                type(value) is not str or not value or len(value) > 1024
                for value in (self.install_operation_id, self.remove_operation_id)
            )
            or ((self.head_operation_id is None) != (self.head_transition_kind is None))
            or (
                self.head_operation_id is not None
                and (
                    type(self.head_operation_id) is not str
                    or not self.head_operation_id
                    or len(self.head_operation_id) > 1024
                    or self.head_transition_kind not in {"install", "update"}
                    or (
                        self.head_transition_kind == "install"
                        and self.head_operation_id != self.install_operation_id
                    )
                )
            )
        ):
            raise self._error_type("Old local removal entry is invalid")

    def to_dict(self) -> dict[str, str]:
        result = cast(dict[str, str], _ENTRY_SCHEMA.encode(self))
        if self.head_operation_id is not None:
            assert self.head_transition_kind is not None
            result["headOperationId"] = self.head_operation_id
            result["headTransitionKind"] = self.head_transition_kind
        return result

    @classmethod
    def from_dict(cls, value: object) -> Self:
        keys = _ENTRY_SCHEMA.keys
        if type(value) is not dict or set(value) not in (
            keys,
            keys | {"headOperationId", "headTransitionKind"},
        ):
            raise cls._error_type("Old local removal entry is invalid")
        if "headOperationId" in value and (
            type(value["headOperationId"]) is not str
            or type(value["headTransitionKind"]) is not str
        ):
            raise cls._error_type("Old local removal entry is invalid")
        create: Callable[..., Self] = cls
        return create(
            **_ENTRY_SCHEMA.decode(dict, value),
            head_operation_id=value.get("headOperationId"),
            head_transition_kind=value.get("headTransitionKind"),
        )


class LegacyRemovalReviewRecord(_LegacyFencedReviewRecord):
    """Validate and encode an inert review of the authenticated removal facts."""

    __slots__ = ()
    _error_type: ClassVar[type[ValueError]]
    _entry_type: ClassVar[type[LegacyRemovalEntryRecord]]
    _builtin_intent_type: ClassVar[type[_LegacyBuiltinIntent]]
    _builtin_ids: ClassVar[frozenset[str]]
    _removable_builtin_ids: ClassVar[frozenset[str]]
    _maximum_entries: ClassVar[int]
    _schema = _REVIEW_SCHEMA

    if TYPE_CHECKING:
        source_projection_digest: str
        lockfile_digest: str
        desired_journal_digest: str
        builtin_intent: tuple[_LegacyBuiltinIntent, ...]
        removed_builtin_ids: tuple[str, ...]
        removed_local: tuple[LegacyRemovalEntryRecord, ...]
        review_version: int
        operation_journal_digest: str | None
        retained_store_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        digests = (
            self.namespace_id,
            self.first_fence_id,
            self.snapshot_receipt_id,
            self.source_projection_digest,
            self.lockfile_digest,
            self.desired_journal_digest,
        )
        if (
            type(self.store_id) is not str
            or LEGACY_REVIEW_ID.fullmatch(self.store_id) is None
            or type(self.scope_id) is not str
            or not self.scope_id.startswith("workspace:")
            or type(self.review_version) is not int
            or self.review_version not in {1, 2}
            or type(self.retained_store_roots) is not tuple
            or any(
                type(root) is not str or root not in LEGACY_REMOVAL_STORE_ROOTS
                for root in self.retained_store_roots
            )
            or self.retained_store_roots
            != tuple(sorted(set(self.retained_store_roots)))
            or (
                self.operation_journal_digest is not None
                and (
                    self.review_version != 2
                    or type(self.operation_journal_digest) is not str
                    or LEGACY_REVIEW_DIGEST.fullmatch(self.operation_journal_digest)
                    is None
                )
            )
            or any(
                type(value) is not str or LEGACY_REVIEW_DIGEST.fullmatch(value) is None
                for value in digests
            )
            or not 0 < len(self.removed_local) <= self._maximum_entries
            or any(
                not isinstance(item, self._entry_type) for item in self.removed_local
            )
            or tuple(item.plugin_id for item in self.removed_local)
            != tuple(sorted({item.plugin_id for item in self.removed_local}))
            or any(
                item.plugin_id in self._builtin_ids
                or not item.source_identity.startswith("local:/")
                for item in self.removed_local
            )
            or (
                self.review_version == 1
                and any(
                    item.head_operation_id is not None for item in self.removed_local
                )
            )
            or (
                self.review_version == 2
                and (
                    any(item.head_operation_id is None for item in self.removed_local)
                    or (
                        not any(
                            item.head_transition_kind == "update"
                            for item in self.removed_local
                        )
                        and self.operation_journal_digest is None
                    )
                )
            )
            or any(
                item not in self._removable_builtin_ids
                for item in self.removed_builtin_ids
            )
            or tuple(sorted(set(self.removed_builtin_ids))) != self.removed_builtin_ids
            or any(
                item.plugin_id not in self._builtin_ids for item in self.builtin_intent
            )
            or any(
                item.desired_state not in ("installed_disabled", "installed_enabled")
                for item in self.builtin_intent
            )
            or tuple(item.plugin_id for item in self.builtin_intent)
            != tuple(sorted({item.plugin_id for item in self.builtin_intent}))
            or set(self.removed_builtin_ids).intersection(
                item.plugin_id for item in self.builtin_intent
            )
            or not valid_legacy_disable_selections(
                self.disabled_plugins, self._disable_type
            )
            or any(
                item.plugin_id
                not in self._builtin_ids
                | {local.plugin_id for local in self.removed_local}
                for item in self.disabled_plugins
            )
        ):
            raise self._error_type("Old local removal review is invalid")
        self._seal_review(self._identity())

    def _identity(self) -> dict[str, object]:
        identity = self._selection_identity(self.builtin_intent, self.removed_builtin_ids)
        identity["removedLocal"] = [item.to_dict() for item in self.removed_local]
        identity["reviewVersion"] = self.review_version
        if self.operation_journal_digest is not None:
            identity["operationJournalDigest"] = self.operation_journal_digest
        if self.retained_store_roots:
            identity["retainedStoreRoots"] = list(self.retained_store_roots)
        return identity

    @classmethod
    def from_dict(cls, value: object) -> Self:
        expected = cls._schema.keys | {
            "reviewId",
            "removedLocal",
            "reviewVersion",
            "removedBuiltinIds",
            "builtinIntent",
            "disabledPlugins",
        }
        optional = {"operationJournalDigest", "retainedStoreRoots"}
        if (
            type(value) is not dict
            or not expected <= value.keys() <= expected | optional
        ):
            raise cls._error_type("Old local removal review is invalid")
        if (
            "operationJournalDigest" in value
            and type(value["operationJournalDigest"]) is not str
        ):
            raise cls._error_type("Old local removal review is invalid")
        disabled = value["disabledPlugins"]
        builtins = value["builtinIntent"]
        removed_builtin = value["removedBuiltinIds"]
        removed_local = value["removedLocal"]
        retained_store = value.get("retainedStoreRoots", [])
        if (
            type(disabled) is not list
            or any(
                type(item) is not dict or set(item) != {"scope", "pluginId"}
                for item in disabled
            )
            or type(builtins) is not list
            or any(
                type(item) is not dict or set(item) != {"pluginId", "desiredState"}
                for item in builtins
            )
            or type(removed_builtin) is not list
            or type(removed_local) is not list
            or type(retained_store) is not list
            or ("retainedStoreRoots" in value and not retained_store)
        ):
            raise cls._error_type("Old local removal entries are invalid")
        selections = LegacyReviewWireSelections(disabled, builtins, removed_builtin)
        create: Callable[..., Self] = cls
        try:
            review = create(
                **cls._schema.decode(dict, value),
                **selections.decode(cls._disable_type, cls._builtin_intent_type),
                removed_local=tuple(
                    cls._entry_type.from_dict(item) for item in removed_local
                ),
                review_version=value["reviewVersion"],
                operation_journal_digest=value.get("operationJournalDigest"),
                retained_store_roots=tuple(retained_store),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise cls._error_type("Old local removal review is invalid") from exc
        if review.review_id != value["reviewId"]:
            raise cls._error_type("Old local removal review ID changed")
        return review


class LegacyRemovalFacts(NamedTuple):
    inventory: LegacyInventoryFacts[LegacyLocalBindingEvidence]
    removed: tuple[LegacyRemovedBinding[LegacyLocalBindingEvidence], ...]
    desired_digest: str
    operation_digest: str | None


@dataclass(frozen=True, slots=True)
class LegacyRemovalSnapshot:
    _read_member: Callable[..., bytes | None]
    _instance_members: tuple[str, ...]
    retained_store_roots: tuple[str, ...]
    has_operations: bool
    _before_fence: bool
    _review_error: type[ValueError]
    _operation_error: type[ValueError]
    _label: str

    @classmethod
    def before_fence(
        cls,
        owner: PackageProductPreBSnapshotOwner | PackageProductWindowsPreBSnapshotOwner,
        snapshot: PackageEpochCutoverSnapshotReceiptV1,
        *,
        eligible: bool,
        source_member: str,
        review_error: type[ValueError],
        operation_error: type[ValueError],
        label: str,
    ) -> LegacyRemovalSnapshot:
        evidence = owner.snapshot(snapshot.receipt_id)
        members = {
            domain: owner.list_domain_members(snapshot.receipt_id, domain=domain) or ()
            for domain in _DOMAINS
        }
        if not eligible or evidence is None or evidence.snapshot != snapshot:
            raise review_error(_SHAPE_CHANGED)
        return cls._verify_members(
            members,
            partial(owner.read_regular_member, snapshot.receipt_id),
            source_member=source_member,
            review_error=review_error,
            operation_error=operation_error,
            label=label,
            before_fence=True,
        )

    @classmethod
    def after_fence(
        cls,
        reader: _LegacyFirstSnapshot,
        *,
        source_member: str,
        review_error: type[ValueError],
        operation_error: type[ValueError],
        label: str,
    ) -> LegacyRemovalSnapshot:
        return cls._verify_members(
            {domain: reader.list_members(domain=domain) for domain in _DOMAINS},
            reader.read_member,
            source_member=source_member,
            review_error=review_error,
            operation_error=operation_error,
            label=label,
            before_fence=False,
        )

    @classmethod
    def _verify_members(
        cls,
        members: Mapping[str, tuple[str, ...]],
        read_member: Callable[..., bytes | None],
        *,
        source_member: str,
        review_error: type[ValueError],
        operation_error: type[ValueError],
        label: str,
        before_fence: bool,
    ) -> LegacyRemovalSnapshot:
        store_roots = members["store_bytes"]
        if (
            members["binding_history"] != ("package-lock.json",)
            or members["source_configuration"] != (source_member,)
            or members["enablement_state"]
            or store_roots
            != tuple(sorted(set(store_roots) & LEGACY_REMOVAL_STORE_ROOTS))
        ):
            raise review_error(_SHAPE_CHANGED)
        instance_members = members["instance_state"]
        try:
            has_operations = classify_management_members(
                desired_members=members["desired_state"],
                instance_members=instance_members,
                lock_members=members["lock_history"],
                has_binding=True,
                allow_retirement=True,
                allow_retired_runtime=True,
                error_type=operation_error,
                label=f"{label} old",
            )
        except operation_error as exc:
            raise review_error(_SHAPE_CHANGED) from exc
        require_empty_lock_markers(
            read_member,
            (
                (domain, name)
                for domain in _JOURNAL_DOMAINS
                for name in members[domain]
                if name.endswith(".lock")
            ),
            error_type=review_error,
            message="Old removal journal lock changed",
        )
        return cls(
            read_member,
            instance_members,
            store_roots,
            has_operations,
            before_fence,
            review_error,
            operation_error,
            label,
        )

    def prove(
        self,
        *,
        inventory_reader: LegacyInventoryReader,
        maximum_bindings: int,
    ) -> LegacyRemovalFacts:
        read = self._read_member
        lock_max = LEGACY_BINDING_CAPTURE_MAX_BYTES
        desired_max = LEGACY_DESIRED_CAPTURE_MAX_BYTES
        defaults = self._before_fence
        lock_raw = read(
            domain="binding_history",
            member_name="package-lock.json",
            **({} if defaults else {"maximum_bytes": lock_max}),
        )
        desired_raw = read(
            domain="desired_state",
            member_name="desired-state.jsonl",
            **({} if defaults else {"maximum_bytes": desired_max}),
        )
        if lock_raw is None or desired_raw is None:
            raise self._review_error("Old removal evidence is missing")
        bindings = inventory_reader.decode_binding_heads(lock_raw)
        desired, desired_digest, transitions = inventory_reader.decode_desired(desired_raw)

        def check_management_history() -> str | None:
            return read_settled_management_history(
                read,
                paths=inventory_reader.management_paths,
                instance_members=self._instance_members,
                desired_snapshot=desired,
                desired_transitions=transitions,
                error_type=self._review_error,
                missing_messages=(
                    "Old management operation evidence is missing",
                    "Old retirement evidence is missing",
                    "Old Instance evidence is missing",
                ),
                operation_error=self._operation_error,
                operation_label=f"{self._label} old",
                instance_error=inventory_reader.instance_error,
                operation_maximum_bytes=None
                if defaults
                else LEGACY_MANAGEMENT_CAPTURE_MAX_BYTES,
                retain_operation_digest=not defaults,
            )

        operation_digest = (
            check_management_history() if self.has_operations and not defaults else None
        )
        inventory = inventory_reader.classify(bindings, desired)
        removed = prove_removed_legacy_bindings(
            bindings,
            transitions,
            unselected_source_identities=inventory.unselected_source_identities,
            removed_plugin_ids=inventory.removed_plugin_ids,
            builtin_ids=inventory_reader.builtin_ids,
            maximum_bindings=maximum_bindings,
            error_type=inventory_reader.inventory_error,
            label=f"{self._label} old local removal",
        )
        if self.has_operations and defaults:
            check_management_history()
        return LegacyRemovalFacts(inventory, removed, desired_digest, operation_digest)
