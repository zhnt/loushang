"""Authenticate legacy inventory facts and shared review values."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import fields
from functools import partial
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Literal,
    NamedTuple,
    Protocol,
    Self,
    TypeVar,
)

from loushang.harness.package_product._legacy_binding_evidence import (
    LEGACY_BINDING_CAPTURE_MAX_BYTES,
    LegacyLocalBindingEvidence,
    decode_legacy_local_binding_heads,
)
from loushang.harness.package_product._legacy_management_evidence import (
    LEGACY_DESIRED_CAPTURE_MAX_BYTES,
    SERVICE_LOCK_MARKERS,
    LegacyManagementCapturePaths,
    classify_management_members,
    decode_legacy_desired_evidence,
    read_settled_management_history,
    require_empty_lock_markers,
    require_service_lock_markers,
)
from loushang.harness.package_product._legacy_runtime import (
    _FencedRuntime,
    _LegacyFirstSnapshot,
    require_legacy_snapshot_members,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.plugin_management.retirement import (
    inspect_removed_installation_epoch,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_legacy_source_wheel import (
    _LegacyWheelValues,
    _reacquire_legacy_local_plugin_wheel,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    PackageProductPreBSnapshotOwner,
)
from loushang.harness.resources.packages.product_windows_pre_b_snapshot import (
    PackageProductWindowsPreBSnapshotOwner,
)
from loushang.harness.resources.plugins.dependencies import PluginDependencyClosureLock

_InstalledState = Literal["installed_disabled", "installed_enabled"]
_BINDING_LOCK = "package-lock.json"
_PACKAGE_LOCK_MARKER = "package-lock.json.lock"
_DESIRED_JOURNAL = "desired-state.jsonl"

LEGACY_REVIEW_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
LEGACY_REVIEW_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class _BindingHead(Protocol):
    @property
    def plugin_id(self) -> str: ...
    @property
    def source_identity(self) -> str: ...
    @property
    def lockfile_digest(self) -> str: ...
    @property
    def content_digest(self) -> str: ...

    @property
    def manifest_digest(self) -> str: ...

    @property
    def binding_digest(self) -> str: ...
    @property
    def dependency_lock(self) -> PluginDependencyClosureLock: ...


_BindingT = TypeVar("_BindingT", bound=_BindingHead)
_WheelT = TypeVar("_WheelT")


class LegacyInventoryFacts(NamedTuple, Generic[_BindingT]):
    active_local: tuple[tuple[_BindingT, _InstalledState, str | None], ...]
    builtin_intent: tuple[tuple[str, _InstalledState], ...]
    removed_plugin_ids: tuple[str, ...]
    unselected_source_identities: tuple[str, ...]
    lockfile_digest: str | None


class LegacyRemovedBinding(NamedTuple, Generic[_BindingT]):
    binding: _BindingT
    install_operation_id: str
    remove_operation_id: str
    head_operation_id: str
    head_transition_kind: Literal["install", "update"]


class LegacyInventoryEvidence(NamedTuple):
    first_fence_id: str
    snapshot_receipt_id: str
    inventory: LegacyInventoryFacts[LegacyLocalBindingEvidence]
    desired_journal_digest: str | None


class _LegacyScopedDisable(Protocol):
    def __init__(self, scope: Literal["global", "project"], plugin_id: str) -> None: ...

    @property
    def scope(self) -> str: ...

    @property
    def plugin_id(self) -> str: ...


class _LegacyBuiltinIntent(Protocol):
    def __init__(
        self,
        plugin_id: str,
        desired_state: _InstalledState,
    ) -> None: ...

    @property
    def plugin_id(self) -> str: ...

    @property
    def desired_state(self) -> str: ...


def legacy_review_scalar_schema(record_type: type, *excluded: str) -> RecordSchema:
    names = (member.name for member in fields(record_type) if member.name not in excluded)
    return RecordSchema(lambda value: value, tuple(RecordField(name) for name in names))


def legacy_record_digest(document: dict[str, object]) -> str:
    return sha256(canonical_json_bytes(document)).hexdigest()


class LegacyReviewWireSelections(NamedTuple):
    disabled: list[dict[str, Any]]
    intent: list[dict[str, Any]]
    removed: list[str]

    @classmethod
    def read(
        cls,
        document: dict[str, Any],
        *,
        required: bool,
        disabled_error: ValueError,
        intent_error: ValueError,
        removed_error: ValueError,
    ) -> LegacyReviewWireSelections:
        """Read required builtin lists or local lists omitted when empty."""

        def plugin_id_is_text(value: object) -> bool:
            return type(value) is str if required else isinstance(value, str)

        def desired_state_is_valid(value: object) -> bool:
            if required:
                return value in ("installed_disabled", "installed_enabled")
            return type(value) is str

        disabled = read_legacy_disabled_plugins(
            _review_wire_list(document, "disabledPlugins", required, disabled_error),
            plugin_id_is_text=plugin_id_is_text,
            error=disabled_error,
        )
        intent = _review_wire_list(document, "builtinIntent", required, intent_error)
        if any(
            type(item) is not dict
            or set(item) != {"pluginId", "desiredState"}
            or type(item["pluginId"]) is not str
            or not desired_state_is_valid(item["desiredState"])
            for item in intent
        ):
            raise intent_error
        removed = _review_wire_list(document, "removedBuiltinIds", required, removed_error)
        if any(type(item) is not str for item in removed):
            raise removed_error
        return cls(disabled, intent, removed)

    def decode(
        self,
        disable_type: type[_LegacyScopedDisable],
        intent_type: type[_LegacyBuiltinIntent],
    ) -> dict[str, object]:
        return {
            "disabled_plugins": tuple(
                disable_type(item["scope"], item["pluginId"]) for item in self.disabled
            ),
            "builtin_intent": tuple(
                intent_type(item["pluginId"], item["desiredState"]) for item in self.intent
            ),
            "removed_builtin_ids": tuple(self.removed),
        }


def _review_wire_list(
    document: dict[str, Any], key: str, required: bool, error: ValueError
) -> list[Any]:
    value = document[key] if required else document.get(key, [])
    if not isinstance(value, list) or (not required and key in document and not value):
        raise error
    return value


def read_legacy_disabled_plugins(
    value: object, *, plugin_id_is_text: Callable[[object], bool], error: ValueError,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(
        type(item) is not dict
        or set(item) != {"scope", "pluginId"}
        or item["scope"] not in ("global", "project")
        or not plugin_id_is_text(item["pluginId"])
        for item in value
    ):
        raise error
    return value


def legacy_disabled_plugins_wire(
    disables: Sequence[_LegacyScopedDisable],
) -> list[dict[str, str]]:
    return [{"scope": item.scope, "pluginId": item.plugin_id} for item in disables]


def legacy_review_selection_wire(
    disables: Sequence[_LegacyScopedDisable],
    builtin_intent: Sequence[_LegacyBuiltinIntent],
    removed_builtin_ids: Sequence[str],
    *,
    include_empty: bool,
) -> dict[str, object]:
    document: dict[str, object] = {}
    if include_empty or disables:
        document["disabledPlugins"] = legacy_disabled_plugins_wire(disables)
    if include_empty or builtin_intent:
        document["builtinIntent"] = [
            {"pluginId": item.plugin_id, "desiredState": item.desired_state}
            for item in builtin_intent
        ]
    if include_empty or removed_builtin_ids:
        document["removedBuiltinIds"] = list(removed_builtin_ids)
    return document


def valid_legacy_disable_selections(
    disables: Sequence[_LegacyScopedDisable],
    disable_type: type[_LegacyScopedDisable],
    *,
    supported_id: Callable[[str], object] = LEGACY_REVIEW_ID.fullmatch,
) -> bool:
    return not any(
        not isinstance(item, disable_type)
        or item.scope not in ("global", "project")
        or not supported_id(item.plugin_id)
        for item in disables
    ) and len({(item.scope, item.plugin_id) for item in disables}) == len(disables)


def valid_legacy_builtin_intent(
    intent: Sequence[_LegacyBuiltinIntent],
    builtin_ids: frozenset[str],
    *,
    intent_type: type[_LegacyBuiltinIntent],
) -> bool:
    return not any(
        not isinstance(item, intent_type)
        or item.plugin_id not in builtin_ids
        or item.desired_state not in ("installed_disabled", "installed_enabled")
        for item in intent
    ) and tuple(item.plugin_id for item in intent) == tuple(
        sorted({item.plugin_id for item in intent})
    )


class _LegacyFencedReviewRecord:
    """Share the identity seal for the nominal first-fence review records."""

    __slots__ = ()
    _schema: ClassVar[RecordSchema]
    _disable_type: ClassVar[type[_LegacyScopedDisable]]

    if TYPE_CHECKING:
        store_id: str
        namespace_id: str
        scope_id: str
        first_fence_id: str
        snapshot_receipt_id: str
        disabled_plugins: tuple[_LegacyScopedDisable, ...]
        review_id: str

    def _seal_review(self, identity: dict[str, object]) -> None:
        object.__setattr__(self, "review_id", legacy_record_digest(identity))

    def _selection_identity(
        self,
        builtin_intent: Sequence[_LegacyBuiltinIntent],
        removed_builtin_ids: Sequence[str],
        *,
        include_empty: bool = True,
    ) -> dict[str, object]:
        identity = self._schema.encode(self)
        identity.update(
            legacy_review_selection_wire(
                self.disabled_plugins, builtin_intent, removed_builtin_ids,
                include_empty=include_empty,
            )
        )
        return identity

    def _identity(self) -> dict[str, object]:
        raise NotImplementedError

    def to_dict(self) -> dict[str, object]:
        return {**self._identity(), "reviewId": self.review_id}


class LegacyDisabledReviewRecord(_LegacyFencedReviewRecord):
    """Decode the historical settings-only review and verify its exact identity."""

    __slots__ = ()
    _review_label: ClassVar[str]

    if TYPE_CHECKING:
        review_version: int

    def __post_init__(self) -> None:
        if not self.disabled_plugins:
            raise ValueError("Disabled-only review requires scoped disabled Plugins")
        if self.review_version != 1:
            raise ValueError("Unsupported disabled-only review version")
        self._seal_review(self._identity_dict())

    def _identity_dict(self) -> dict[str, object]:
        return {
            **self._schema.encode(self),
            "disabledPlugins": legacy_disabled_plugins_wire(self.disabled_plugins),
        }

    def to_dict(self) -> dict[str, object]:
        return {"reviewId": self.review_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        label = cls._review_label
        if type(value) is not dict or set(value) != cls._schema.keys | {
            "reviewId", "disabledPlugins",
        }:
            raise ValueError(f"{label} record is invalid")
        disabled = read_legacy_disabled_plugins(
            value["disabledPlugins"],
            plugin_id_is_text=lambda item: isinstance(item, str) and bool(item),
            error=ValueError(f"{label} entries are invalid"),
        )
        for name in (
            "namespaceId", "firstFenceId", "snapshotReceiptId",
            "sourceProjectionDigest", "reviewId",
        ):
            if not isinstance(value[name], str) or LEGACY_REVIEW_DIGEST.fullmatch(value[name]) is None:
                raise ValueError(f"{label} digest is invalid")
        for name in ("storeId", "scopeId"):
            if not isinstance(value[name], str) or not value[name]:
                raise ValueError(f"{label} authority is invalid")
        if type(value["reviewVersion"]) is not int or value["reviewVersion"] != 1:
            raise ValueError(f"{label} version is invalid")
        if len({(item["scope"], item["pluginId"]) for item in disabled}) != len(disabled):
            raise ValueError(f"{label} entries are duplicated")
        scalar_fields: dict[str, object] = cls._schema.decode(dict, value)
        del scalar_fields["review_version"]
        create: Callable[..., Self] = cls
        review = create(
            **scalar_fields,
            disabled_plugins=tuple(
                cls._disable_type(item["scope"], item["pluginId"]) for item in disabled
            ),
        )
        if review.review_id != value["reviewId"]:
            raise ValueError(f"{label} identity changed")
        return review


class LegacyBuiltinReviewRecord(_LegacyFencedReviewRecord):
    """Validate and encode historical builtin intent with Product-supplied IDs."""

    __slots__ = ()
    _error_type: ClassVar[type[ValueError]]
    _builtin_ids: ClassVar[frozenset[str]]
    _removable_builtin_ids: ClassVar[frozenset[str]]
    _builtin_intent_type: ClassVar[type[_LegacyBuiltinIntent]]

    if TYPE_CHECKING:
        desired_journal_digest: str
        source_projection_digest: str
        builtin_intent: tuple[_LegacyBuiltinIntent, ...]
        removed_builtin_ids: tuple[str, ...]
        review_version: int

    def __post_init__(self) -> None:
        if (
            type(self.store_id) is not str
            or not self.store_id
            or type(self.scope_id) is not str
            or not self.scope_id.startswith("workspace:")
            or type(self.review_version) is not int
            or self.review_version != 1
            or type(self.disabled_plugins) is not tuple
            or type(self.builtin_intent) is not tuple
            or type(self.removed_builtin_ids) is not tuple
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in (
                    self.namespace_id,
                    self.first_fence_id,
                    self.snapshot_receipt_id,
                    self.source_projection_digest,
                    self.desired_journal_digest,
                )
            )
            or not valid_legacy_disable_selections(
                self.disabled_plugins, self._disable_type,
                supported_id=self._builtin_ids.__contains__,
            )
            or not valid_legacy_builtin_intent(
                self.builtin_intent, self._builtin_ids, intent_type=self._builtin_intent_type
            )
            or self.removed_builtin_ids != tuple(sorted(set(self.removed_builtin_ids)))
            or any(item not in self._removable_builtin_ids for item in self.removed_builtin_ids)
            or set(self.removed_builtin_ids).intersection(
                item.plugin_id for item in self.builtin_intent
            )
            or not (self.builtin_intent or self.removed_builtin_ids)
        ):
            raise self._error_type("Builtin-only review is invalid")
        self._seal_review(self._identity())

    def _identity(self) -> dict[str, object]:
        identity = self._selection_identity(self.builtin_intent, self.removed_builtin_ids)
        identity["reviewVersion"] = self.review_version
        return identity

    @classmethod
    def from_dict(cls, value: object) -> Self:
        expected = cls._schema.keys | {
            "reviewId", "reviewVersion", "removedBuiltinIds",
            "builtinIntent", "disabledPlugins",
        }
        if type(value) is not dict or set(value) != expected:
            raise cls._error_type("Builtin-only review record is invalid")
        error = cls._error_type("Builtin-only review entries are invalid")
        selections = LegacyReviewWireSelections.read(
            value, required=True, disabled_error=error, intent_error=error, removed_error=error,
        )
        create: Callable[..., Self] = cls
        try:
            review = create(
                **cls._schema.decode(dict, value),
                **selections.decode(cls._disable_type, cls._builtin_intent_type),
                review_version=value["reviewVersion"],
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise cls._error_type("Builtin-only review record is invalid") from exc
        if review.review_id != value["reviewId"]:
            raise cls._error_type("Builtin-only review identity changed")
        return review


def classify_legacy_builtin_snapshot(
    list_members: Callable[..., tuple[str, ...] | None],
    expected: Mapping[str, tuple[str, ...]],
    *,
    shape_error: Exception,
    operation_error: type[ValueError],
    label: str,
) -> bool:
    require_legacy_snapshot_members(list_members, expected, error=shape_error)
    return classify_management_members(
        desired_members=list_members(domain="desired_state") or (),
        instance_members=list_members(domain="instance_state") or (),
        lock_members=(),
        has_binding=False,
        allow_retirement=False,
        allow_retired_runtime=False,
        error_type=operation_error,
        label=f"{label} old",
    )


def read_legacy_builtin_admission(
    owner: PackageProductPreBSnapshotOwner | PackageProductWindowsPreBSnapshotOwner,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
    *,
    expected: Mapping[str, tuple[str, ...]],
    desired_path: Path,
    management_paths: LegacyManagementCapturePaths,
    product_id: str,
    scope_id: str,
    builtin_ids: Set[str],
    review_error: type[ValueError],
    inventory_error: type[ValueError],
    desired_error: type[ValueError],
    operation_error: type[ValueError],
    label: str,
) -> tuple[LegacyInventoryFacts[LegacyLocalBindingEvidence], str]:
    """Check exact builtin Desired and management evidence before the first fence."""
    receipt_id = snapshot.receipt_id
    evidence = owner.snapshot(receipt_id)
    shape_error = review_error(f"{label} old snapshot is not builtin-only")
    if evidence is None or evidence.snapshot != snapshot:
        raise shape_error
    has_operations = classify_legacy_builtin_snapshot(
        partial(owner.list_domain_members, receipt_id),
        expected,
        shape_error=shape_error,
        operation_error=operation_error,
        label=label,
    )
    read = partial(owner.read_regular_member, receipt_id)
    raw = read(domain="desired_state", member_name=_DESIRED_JOURNAL)
    if raw is None:
        raise review_error(f"{label} old Desired State is missing")
    desired, digest, transitions = decode_legacy_desired_evidence(
        raw,
        path=desired_path,
        product_id=product_id,
        scope_id=scope_id,
        maximum_bytes=LEGACY_DESIRED_CAPTURE_MAX_BYTES,
        error_type=desired_error,
        label=f"{label} legacy",
    )
    if has_operations:
        require_empty_lock_markers(
            read,
            SERVICE_LOCK_MARKERS,
            error_type=review_error,
            message=f"{label} old management lock changed",
        )
        read_settled_management_history(
            read,
            paths=management_paths,
            instance_members=(),
            desired_snapshot=desired,
            desired_transitions=transitions,
            error_type=review_error,
            missing_messages=(
                f"{label} old management operations are missing",
                f"{label} old retirement journals are missing",
                f"{label} old Instance runtime evidence is missing",
            ),
            operation_error=operation_error,
            operation_label=f"{label} old",
            instance_error=review_error,
        )
    if not isinstance(scope_id, str) or not scope_id.startswith("workspace:"):
        raise ValueError(f"{label} legacy workspace scope is invalid")
    return classify_legacy_installations(
        (),
        desired,
        product_id=product_id,
        scope_id=scope_id,
        builtin_ids=builtin_ids,
        error_type=inventory_error,
        label=f"{label} legacy",
    ), digest


def read_legacy_installation_inventory(
    reader: _LegacyFirstSnapshot,
    *,
    desired_path: Path,
    management_paths: LegacyManagementCapturePaths,
    product_id: str,
    scope_id: str,
    builtin_ids: Set[str],
    inventory_error: type[ValueError],
    lock_error: type[ValueError],
    desired_error: type[ValueError],
    operation_error: type[ValueError],
    instance_error: type[ValueError],
    label: str,
) -> LegacyInventoryEvidence:
    """Join first-fence facts using only immutable snapshot read authority."""
    binding_members = reader.list_members(domain="binding_history")
    if binding_members not in ((), (_BINDING_LOCK,)):
        raise inventory_error(f"{label} legacy binding members are ambiguous")
    if not binding_members and any(
        reader.list_members(domain=domain)
        for domain in ("store_bytes", "enablement_state")
    ):
        raise inventory_error(
            f"{label} legacy state without a binding lock is unsupported"
        )
    bindings: tuple[LegacyLocalBindingEvidence, ...] = ()
    if binding_members:
        lock_raw = reader.read_member(
            domain="binding_history",
            member_name=_BINDING_LOCK,
            maximum_bytes=LEGACY_BINDING_CAPTURE_MAX_BYTES,
        )
        if lock_raw is None:
            raise lock_error(f"{label} legacy Package binding lock is missing")
        bindings = decode_legacy_local_binding_heads(
            lock_raw,
            maximum_bytes=LEGACY_BINDING_CAPTURE_MAX_BYTES,
            error_type=lock_error,
            label=f"{label} legacy",
        )

    desired_members = reader.list_members(domain="desired_state")
    instance_members = reader.list_members(domain="instance_state")
    lock_members = reader.list_members(domain="lock_history")
    desired_snapshot = None
    desired_digest = None
    if binding_members or desired_members or instance_members or lock_members:
        has_binding = bool(binding_members)
        has_operations = classify_management_members(
            desired_members=desired_members,
            instance_members=instance_members,
            lock_members=lock_members,
            has_binding=has_binding,
            allow_retirement=has_binding,
            allow_retired_runtime=has_binding,
            error_type=operation_error,
            label=f"{label} old",
        )
        desired_raw = reader.read_member(
            domain="desired_state",
            member_name=_DESIRED_JOURNAL,
            maximum_bytes=LEGACY_DESIRED_CAPTURE_MAX_BYTES,
        )
        if desired_raw is None:
            raise inventory_error(f"{label} old Desired state is missing")
        desired_snapshot, desired_digest, transitions = decode_legacy_desired_evidence(
            desired_raw,
            path=desired_path,
            product_id=product_id,
            scope_id=scope_id,
            maximum_bytes=LEGACY_DESIRED_CAPTURE_MAX_BYTES,
            error_type=desired_error,
            label=f"{label} legacy",
        )
        if _PACKAGE_LOCK_MARKER in lock_members:
            require_empty_lock_markers(
                reader.read_member,
                (("lock_history", _PACKAGE_LOCK_MARKER),),
                error_type=inventory_error,
                message=f"{label} old Package lock changed",
            )
        if has_operations:
            require_service_lock_markers(
                reader.read_member,
                instance_members,
                error_type=inventory_error,
                message=f"{label} old management lock changed",
            )
            read_settled_management_history(
                reader.read_member,
                paths=management_paths,
                instance_members=instance_members,
                desired_snapshot=desired_snapshot,
                desired_transitions=transitions,
                error_type=inventory_error,
                missing_messages=(
                    f"{label} old management operation journal is missing",
                    f"{label} old retirement journals are missing",
                    f"{label} old Instance runtime evidence is missing",
                ),
                operation_error=operation_error,
                operation_label=f"{label} old",
                instance_error=instance_error,
            )
    if not isinstance(scope_id, str) or not scope_id.startswith("workspace:"):
        raise ValueError(f"{label} legacy workspace scope is invalid")
    inventory = classify_legacy_installations(
        bindings,
        desired_snapshot,
        product_id=product_id,
        scope_id=scope_id,
        builtin_ids=builtin_ids,
        error_type=inventory_error,
        label=f"{label} legacy",
    )
    reader.runtime.assert_current()
    fence = reader.runtime.cutover_result.fence
    if fence is None:
        raise inventory_error(f"{label} legacy first fence is missing")
    return LegacyInventoryEvidence(
        fence.fence_id, fence.request.snapshot_receipt_id, inventory, desired_digest
    )


def _matches_binding(
    package: PluginPackageRevisionRefV1, binding: _BindingHead
) -> bool:
    return (
        package.plugin_id == binding.plugin_id
        and package.package_source_identity == binding.source_identity
        and package.package_content_digest == binding.content_digest
        and package.dependency_lock_digest == binding.dependency_lock.digest
    )


def reacquire_legacy_bound_wheel(
    binding: _BindingHead,
    *,
    legacy_package_root: Path,
    staging_prefix: str,
    result_factory: Callable[[_LegacyWheelValues], _WheelT],
) -> _WheelT:
    """Use disposable staging while the original Source is recaptured."""
    with TemporaryDirectory(prefix=staging_prefix) as staging:
        return _reacquire_legacy_local_plugin_wheel(
            Path(binding.source_identity.removeprefix("local:")),
            legacy_package_root=legacy_package_root,
            staging_parent=Path(staging),
            plugin_id=binding.plugin_id,
            expected_source_identity=binding.source_identity,
            expected_content_digest=binding.content_digest,
            expected_manifest_digest=binding.manifest_digest,
            expected_dependency_lock=binding.dependency_lock,
            result_factory=result_factory,
        )


def reacquire_legacy_inventory_source(
    read_inventory: Callable[[], LegacyInventoryEvidence],
    epoch_runtime: _FencedRuntime,
    *,
    legacy_package_root: Path,
    plugin_id: str,
    staging_prefix: str,
    error_type: type[ValueError],
    label: str,
    result_factory: Callable[[_LegacyWheelValues], _WheelT],
) -> tuple[LegacyInventoryEvidence, int, _WheelT]:
    """Rebuild a live Source against the same inventory before and after capture."""
    inventory = read_inventory()
    for position, (binding, _, _) in enumerate(inventory.inventory.active_local):
        if binding.plugin_id == plugin_id:
            break
    else:
        raise error_type(f"{label} legacy Plugin is not an installed local candidate")
    if not binding.source_identity.startswith("local:/"):
        raise error_type(f"{label} legacy local Source changed")
    wheel = reacquire_legacy_bound_wheel(
        binding,
        legacy_package_root=legacy_package_root,
        staging_prefix=staging_prefix,
        result_factory=result_factory,
    )
    epoch_runtime.assert_current()
    if read_inventory() != inventory:
        raise error_type(
            f"{label} legacy Installation snapshot changed during Source reacquisition"
        )
    epoch_runtime.assert_current()
    return inventory, position, wheel


def classify_legacy_installations(
    bindings: tuple[_BindingT, ...],
    desired: PluginDesiredStateSnapshotV1 | None,
    *,
    product_id: str,
    scope_id: str,
    builtin_ids: Set[str],
    error_type: type[ValueError],
    label: str,
) -> LegacyInventoryFacts[_BindingT]:
    by_plugin: dict[str, _BindingT] = {}
    source_ids: set[str] = set()
    lock_digests = {item.lockfile_digest for item in bindings}
    for binding in bindings:
        if (
            binding.plugin_id in by_plugin
            or binding.plugin_id in builtin_ids
            or binding.source_identity in source_ids
        ):
            raise error_type(f"{label} binding identity is ambiguous")
        by_plugin[binding.plugin_id] = binding
        source_ids.add(binding.source_identity)
    if len(lock_digests) > 1:
        raise error_type(f"{label} lock snapshot changed")

    active: list[tuple[_BindingT, _InstalledState, str | None]] = []
    builtins: list[tuple[str, _InstalledState]] = []
    removed: list[str] = []
    selected_ids: set[str] = set()
    for state in () if desired is None else desired.installations:
        key = state.installation_key
        selection = state.selection
        if (
            key.product_id != product_id
            or key.installation_scope != "workspace"
            or key.scope_id != scope_id
        ):
            raise error_type(f"{label} Installation scope changed")
        plugin_id = key.plugin_id
        if selection.desired_state == "absent":
            removed.append(plugin_id)
            continue
        package = selection.package_revision
        if package is None or package.plugin_id != plugin_id:
            raise error_type(f"{label} installed revision is missing")
        if plugin_id in builtin_ids:
            if (
                plugin_id in by_plugin
                or package.package_source_identity != f"embedded:{plugin_id}"
            ):
                raise error_type(f"{label} builtin Source is unsupported")
            builtins.append((plugin_id, selection.desired_state))
            continue
        matched = by_plugin.get(plugin_id)
        if matched is None or not _matches_binding(package, matched):
            raise error_type(
                f"{label} installed revision differs from current Source head"
            )
        selected_ids.add(plugin_id)
        active.append((matched, selection.desired_state, package.plugin_version))
    return LegacyInventoryFacts(
        active_local=tuple(sorted(active, key=lambda item: item[0].plugin_id)),
        builtin_intent=tuple(sorted(builtins, key=lambda item: item[0])),
        removed_plugin_ids=tuple(sorted(removed)),
        unselected_source_identities=tuple(
            sorted(
                binding.source_identity
                for plugin_id, binding in by_plugin.items()
                if plugin_id not in selected_ids
            )
        ),
        lockfile_digest=next(iter(lock_digests), None),
    )


def prove_removed_legacy_bindings(
    bindings: tuple[_BindingT, ...],
    transitions: tuple[PluginDesiredStateJournalTransition, ...],
    *,
    unselected_source_identities: tuple[str, ...],
    removed_plugin_ids: tuple[str, ...],
    builtin_ids: Set[str],
    maximum_bindings: int,
    error_type: type[ValueError],
    label: str,
) -> tuple[LegacyRemovedBinding[_BindingT], ...]:
    unselected = set(unselected_source_identities)
    removed_bindings = {
        binding.plugin_id: binding
        for binding in bindings
        if binding.source_identity in unselected
    }
    if (
        not 0 < len(bindings) <= maximum_bindings
        or not removed_bindings
        or unselected
        != {binding.source_identity for binding in removed_bindings.values()}
        or not set(removed_bindings) <= set(removed_plugin_ids)
        or set(removed_plugin_ids) - removed_bindings.keys() - builtin_ids
        or not transitions
    ):
        raise error_type(f"{label} set is unsupported")
    mismatch_message = f"{label} does not match its lock head"
    removed: list[LegacyRemovedBinding[_BindingT]] = []
    for plugin_id, binding in sorted(removed_bindings.items()):
        history = tuple(
            item
            for item in transitions
            if item.mutation.installation_key.plugin_id == plugin_id
        )
        proof = inspect_removed_installation_epoch(
            history,
            error_type=error_type,
            label=label,
            mismatch_message=mismatch_message,
        )
        if not _matches_binding(proof.package_revision, binding):
            raise error_type(mismatch_message)
        removed.append(
            LegacyRemovedBinding(
                binding,
                proof.install.mutation.operation_id,
                proof.removal.mutation.operation_id,
                proof.head.mutation.operation_id,
                proof.head_transition_kind,
            )
        )
    return tuple(removed)
