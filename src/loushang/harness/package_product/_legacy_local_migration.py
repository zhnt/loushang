"""Fixed legacy acceptance and settings-consumption transactions.

Package Product owns receipt/Desired locking, replay, Settings transaction and
rooted IO. Products retain nominal codecs and authenticated legacy admission.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, closing, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    NamedTuple,
    Protocol,
    Self,
    TypeVar,
    cast,
)

from loushang.foundation.json import _unique_json_object_hook
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.config.agent import SettingsManager
from loushang.harness.config.store import _read_stable_json_patch
from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    JournalRecordCodec,
    decode_jsonl,
    encode_jsonl_record,
    journal_file_lock,
    journal_file_read_lock,
)
from loushang.harness.journal._rooted_io import (
    RootedFile,
    RootedFileIO,
    _private_parent_matches,
    publish_private_bytes,
    read_private_text,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateLedger,
    decode_plugin_desired_state_snapshot,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_legacy_source_wheel import (
    LEGACY_SOURCE_WHEEL_FILENAME,
    _LegacyLocalWheelFields,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    hold_legacy_product_projection_root,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ._application_runtime import (
    FencedOrdinaryProductApplication,
    handoff_product_open,
    hold_accepted_product_adoption,
)
from ._legacy_inventory import (
    LEGACY_REVIEW_DIGEST,
    LEGACY_REVIEW_ID,
    LegacyInventoryEvidence,
    _BindingHead,
    legacy_record_digest,
)
from ._legacy_runtime import (
    FencedRuntimeOpenKwargs,
    _FencedRuntime,
    _LegacyEpoch,
    matches_epoch_layout,
)
from ._local_source_catalog import wheel_source_binding_digest
from ._plugin_bootstrap import (
    ReviewedPluginChoices,
    _PluginBootstrapPolicy,
    _ProductOwner,
    replay_reviewed_product_plugins,
    route_project_package,
)
from .product_runtime import hold_local_wheel_product_runtime

RecordT = TypeVar("RecordT")
ReviewT = TypeVar("ReviewT")
_ACCEPTANCE_FIELDS = {"acceptanceId", "acceptanceVersion", "review"}


@dataclass(frozen=True)
class _FirstAcceptanceEnvelope:
    """The common V1 acceptance envelope; review admission stays with its Product."""

    invalid_message: str
    invalid_code: str
    version_error: str
    identity_error: str

    @staticmethod
    def identity(review_id: str) -> str:
        return legacy_record_digest({"acceptanceVersion": 1, "reviewId": review_id})

    def _document(
        self, value: object, *, optional: frozenset[str] = frozenset()
    ) -> dict[str, Any]:
        allowed = _ACCEPTANCE_FIELDS | optional
        if type(value) is not dict or not _ACCEPTANCE_FIELDS <= value.keys() <= allowed:
            raise JournalCodecError(self.invalid_message, code=self.invalid_code)
        return value

    def decode(
        self,
        value: object,
        review_decoder: Callable[[object], ReviewT],
        create: Callable[[ReviewT], RecordT],
    ) -> RecordT:
        document = self._document(value)

        def propose() -> RecordT:
            if type(document["acceptanceVersion"]) is not int or document["acceptanceVersion"] != 1:
                raise ValueError(self.version_error)
            return create(review_decoder(document["review"]))

        return self._decode_proposal(document, propose)

    def _decode_proposal(
        self, document: dict[str, Any], propose: Callable[[], RecordT]
    ) -> RecordT:
        try:
            record = propose()
            if getattr(record, "acceptance_id") != document["acceptanceId"]:
                raise ValueError(self.identity_error)
            return record
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                self.invalid_message, code=self.invalid_code
            ) from exc


class _FirstAcceptanceReview(Protocol):
    @property
    def review_id(self) -> str: ...

    def to_dict(self) -> dict[str, object]: ...

    @classmethod
    def from_dict(cls, value: object) -> Self: ...


_FirstReviewT = TypeVar("_FirstReviewT", bound=_FirstAcceptanceReview)
_ReviewResultT = TypeVar("_ReviewResultT", bound=_FirstAcceptanceReview, covariant=True)
_ReviewLayoutT = TypeVar("_ReviewLayoutT", contravariant=True)
_ReviewRuntimeT = TypeVar("_ReviewRuntimeT", bound=_FencedRuntime, contravariant=True)


class _ReadFirstReview(Protocol[_ReviewLayoutT, _ReviewRuntimeT, _ReviewResultT]):
    def __call__(
        self, layout: _ReviewLayoutT, runtime: _ReviewRuntimeT, /, *,
        settings_manager: SettingsManager,
    ) -> _ReviewResultT: ...


_AcceptanceLayoutT = TypeVar("_AcceptanceLayoutT")
_AcceptanceRuntimeT = TypeVar("_AcceptanceRuntimeT", bound=_FencedRuntime)


class _FirstAcceptanceRecord(Generic[_FirstReviewT]):
    """Keep the V1 receipt codec with the journal that publishes it."""

    __slots__ = ()
    review: _FirstReviewT
    acceptance_id: str
    acceptance_version: int
    _envelope: ClassVar[_FirstAcceptanceEnvelope]
    _review_type: ClassVar[type[_FirstAcceptanceReview]]
    _review_required: ClassVar[str]

    @classmethod
    def create(cls, review: _FirstReviewT) -> Self:
        if not isinstance(review, cls._review_type):
            raise TypeError(cls._review_required)
        cls._check_review(review)
        create: Callable[..., Self] = cls
        return create(
            review=review, acceptance_id=cls._envelope.identity(review.review_id)
        )

    @classmethod
    def _check_review(cls, review: _FirstReviewT) -> None:
        """Apply any Product-specific eligibility rule after the nominal check."""

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptanceId": self.acceptance_id,
            "acceptanceVersion": self.acceptance_version,
            "review": self.review.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        review_type = cast(type[_FirstReviewT], cls._review_type)
        return cls._envelope.decode(value, review_type.from_dict, cls.create)

    @classmethod
    def _record_codec(cls) -> FunctionalJournalRecordCodec[Self]:
        return FunctionalJournalRecordCodec(encoder=cls.to_dict, decoder=cls.from_dict)


class _LocalAcceptanceReview(_FirstAcceptanceReview, Protocol):
    @property
    def plugin_id(self) -> str: ...

    @property
    def scope_id(self) -> str: ...


_LocalReviewT = TypeVar("_LocalReviewT", bound=_LocalAcceptanceReview)
_LegacyResourceKind = Literal["skill", "prompt", "theme"]
_RESOURCE_KIND_VERSION = {"skill": 1, "prompt": 2, "theme": 3}


def _legacy_resource_kind(
    document: Mapping[str, object],
    version: object,
    *,
    invalid_version: str,
    invalid_kind: str,
) -> _LegacyResourceKind:
    if type(version) is not int:
        raise ValueError(invalid_version)
    if version == 1 and "resourceKind" not in document:
        return "skill"
    wire_kind = document.get("resourceKind")
    if version == 2 and wire_kind == "prompt":
        return "prompt"
    if version == 3 and wire_kind == "theme":
        return "theme"
    raise ValueError(invalid_kind)


class LegacyLocalAcceptanceRecord(_FirstAcceptanceRecord[_LocalReviewT]):
    """Keep the three local receipt versions with the shared first-fence codec."""

    __slots__ = ()
    resource_kind: _LegacyResourceKind
    _label: ClassVar[str]

    def __post_init__(self) -> None:
        review_type = cast(type[_LocalReviewT], self._review_type)
        if (
            not isinstance(self.review, review_type)
            or type(self.acceptance_version) is not int
            or _RESOURCE_KIND_VERSION.get(self.resource_kind) != self.acceptance_version
        ):
            raise ValueError(f"{self._label} acceptance record is invalid")
        if self.acceptance_id != self._identity(
            self.review, self.acceptance_version, self.resource_kind
        ):
            raise ValueError(self._envelope.identity_error)

    @staticmethod
    def _identity(review: _LocalAcceptanceReview, version: int, kind: _LegacyResourceKind) -> str:
        identity: dict[str, object] = {
            "acceptanceVersion": version,
            "reviewId": review.review_id,
            "pluginId": review.plugin_id,
        }
        if version >= 2:
            identity["resourceKind"] = kind
        return legacy_record_digest(identity)

    @classmethod
    def create(cls, review: _LocalReviewT, *, resource_kind: _LegacyResourceKind = "skill") -> Self:
        review_type = cast(type[_LocalReviewT], cls._review_type)
        if not isinstance(review, review_type):
            raise TypeError(cls._review_required)
        cls._check_review(review)
        version = _RESOURCE_KIND_VERSION.get(resource_kind)
        if version is None:
            raise ValueError("Unsupported legacy local Resource type")
        create: Callable[..., Self] = cls
        return create(
            review, cls._identity(review, version, resource_kind),
            acceptance_version=version, resource_kind=resource_kind,
        )

    def to_dict(self) -> dict[str, object]:
        document = super().to_dict()
        if self.acceptance_version >= 2:
            document["resourceKind"] = self.resource_kind
        return document

    @classmethod
    def from_dict(cls, value: object) -> Self:
        document = cls._envelope._document(value, optional=frozenset({"resourceKind"}))

        def propose(record_type: type[Self] = cls) -> Self:
            kind = _legacy_resource_kind(
                document, document["acceptanceVersion"],
                invalid_version=cls._envelope.version_error,
                invalid_kind=f"Unsupported {cls._label} acceptance type",
            )
            review_type = cast(type[_LocalReviewT], cls._review_type)
            return record_type.create(review_type.from_dict(document["review"]), resource_kind=kind)

        return cls._envelope._decode_proposal(document, propose)


@dataclass(frozen=True)
class _FirstAcceptanceJournal(
    Generic[_AcceptanceLayoutT, _AcceptanceRuntimeT, _FirstReviewT, RecordT]
):
    """One frozen first-adoption receipt, committed before any Desired mutation.

    Products supply the authenticated record and original diagnostic profile.
    This owner retains receipt-before-Desired lock order and native publication;
    it neither selects a review nor authorizes the later adoption.
    """

    filename: str
    codec: JournalRecordCodec[RecordT]
    error_type: type[Exception]
    directory_label: str
    posix_read_error_type: type[Exception]
    posix_read_label: str
    untouched_message: str
    create: Callable[[_FirstReviewT], RecordT]
    changed_review: str
    accept_conflict: str
    read_conflict: str
    review: _ReadFirstReview[_AcceptanceLayoutT, _AcceptanceRuntimeT, _FirstReviewT]
    resolve_epoch: Callable[[_AcceptanceLayoutT], _LegacyEpoch]
    windows_receipts: WindowsPrivateReceiptIO | None = None
    windows_untouched_message: str = ""
    postcheck: Literal["separate", "combined"] = "separate"
    check_replay_epoch: bool = False
    check_epoch_before_read: bool = False
    empty_is_missing: bool = True

    def accept_review(
        self,
        layout: _AcceptanceLayoutT,
        runtime: _AcceptanceRuntimeT,
        *,
        settings_manager: SettingsManager,
        accepted_review_id: str,
    ) -> RecordT:
        authenticated = self.review(layout, runtime, settings_manager=settings_manager)
        if accepted_review_id != authenticated.review_id:
            raise self.error_type(self.changed_review)
        proposed = self.create(authenticated)
        self._require_store(runtime, self.resolve_epoch(layout).store_id)
        return self.accept(runtime, proposed)

    def read_acceptance(
        self,
        layout: _AcceptanceLayoutT,
        runtime: _AcceptanceRuntimeT,
        *,
        settings_manager: SettingsManager,
    ) -> RecordT | None:
        self._require_store(runtime, self.resolve_epoch(layout).store_id)
        if self.check_epoch_before_read:
            runtime.assert_current()
        path = runtime.control_root / "product-state" / self.filename
        if self.check_epoch_before_read:
            records = self.records(
                path,
                windows=isinstance(runtime, PackageProductWindowsFencedRuntimeOwner),
            )
        else:
            records = self.records(path)
        if records is None or (self.empty_is_missing and not records):
            if self.check_epoch_before_read:
                runtime.assert_current()
            return None
        current_review = self.review(layout, runtime, settings_manager=settings_manager)
        if len(records) != 1 or records[0] != self.create(current_review):
            raise self.error_type(self.read_conflict)
        runtime.assert_current()
        return records[0]

    def _require_store(self, runtime: _FencedRuntime, expected_store_id: str) -> None:
        if runtime.registry.store_id != expected_store_id:
            raise self.error_type("Product Store changed")

    def accept(
        self,
        epoch_runtime: (
            PackageProductPosixFencedRuntimeOwner
            | PackageProductWindowsFencedRuntimeOwner
        ),
        proposed: RecordT,
    ) -> RecordT:
        path = epoch_runtime.prepare_product_state_root() / self.filename
        windows = isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
        with journal_file_lock(path, "exclusive"):
            epoch_runtime.assert_current()
            records = self.decode(
                self.read_private(path, windows=windows, allow_windows_stage=True), path
            )
            if records:
                if len(records) != 1 or records[0] != proposed:
                    raise self.error_type(self.accept_conflict)
                if self.check_replay_epoch:
                    epoch_runtime.assert_current()
                return records[0]
            desired_path = path.parent / "desired-state.jsonl"
            with journal_file_lock(desired_path, "exclusive"):
                self.require_empty_desired(desired_path, windows=windows)
                self.publish(path, proposed, windows=windows)
            epoch_runtime.assert_current()
            return proposed

    def records(
        self, path: Path, *, windows: bool = False
    ) -> tuple[RecordT, ...] | None:
        with journal_file_read_lock(path, "shared", create_lock=False):
            raw = self.read_private(path, windows=windows)
            return None if raw is None else self.decode(raw, path)

    def decode(self, raw: str | None, path: Path) -> tuple[RecordT, ...]:
        if raw is None:
            return ()
        return decode_jsonl(
            raw,
            target=path,
            record_codec=self.codec,
            load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
        ).records

    def encode(self, record: RecordT) -> bytes:
        return encode_jsonl_record(
            record, record_codec=self.codec, format_profile=SORTED_UNICODE_JSONL_FORMAT
        )

    def read_private(
        self,
        path: Path,
        *,
        windows: bool = False,
        allow_windows_stage: bool = False,
    ) -> str | None:
        if windows:
            assert self.windows_receipts is not None
            raw = self.windows_receipts.read_private_receipt(
                path,
                maximum_bytes=1024 * 1024,
                allow_unpublished_stage=allow_windows_stage,
            )
            return None if raw is None else raw.decode("utf-8")
        return read_private_text(
            path,
            max_bytes=16 * 1024 * 1024,
            error_type=self.posix_read_error_type,
            directory_label=f"{self.posix_read_label} state directory",
            file_label=f"{self.posix_read_label} acceptance",
        )

    def publish(self, path: Path, record: RecordT, *, windows: bool = False) -> None:
        payload = self.encode(record)
        if windows:
            assert self.windows_receipts is not None
            self.windows_receipts.write_private_receipt(
                path, payload, maximum_bytes=4 * 1024 * 1024
            )
        else:
            publish_private_bytes(
                path,
                payload,
                error_type=self.error_type,
                directory_label=self.directory_label,
                postcheck=self.postcheck,
            )

    def require_empty_desired(self, path: Path, *, windows: bool = False) -> None:
        if windows:
            assert self.windows_receipts is not None
            raw = self.windows_receipts.read_ledger_bytes(
                path, maximum_bytes=32 * 1024 * 1024
            )
            if raw is None:
                return
            if raw and not raw.endswith(b"\n"):
                raise self.error_type(
                    "Windows Product Desired State journal is incomplete"
                )
            snapshot = decode_plugin_desired_state_snapshot(
                raw.decode("utf-8"), path=path
            )
            if snapshot.inventory_revision != 0:
                raise self.error_type(self.windows_untouched_message)
            return
        try:
            descriptor = os.open(
                path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            )
        except FileNotFoundError:
            return
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) & 0o077
                or metadata.st_size > 32 * 1024 * 1024
            ):
                raise self.posix_read_error_type(
                    "Product Desired State journal is unsafe"
                )
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024 or (raw and not raw.endswith(b"\n")):
                raise self.posix_read_error_type(
                    "Product Desired State journal is incomplete"
                )
            snapshot = decode_plugin_desired_state_snapshot(
                raw.decode("utf-8"), path=path
            )
            if snapshot.inventory_revision != 0:
                raise self.posix_read_error_type(self.untouched_message)
        finally:
            os.close(descriptor)


_LocalReceiptT = TypeVar("_LocalReceiptT", bound=LegacyLocalAcceptanceRecord[Any])


@dataclass(frozen=True)
class _LocalAcceptanceProtocol(Generic[_LocalReviewT, _LocalReceiptT]):
    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    error_type: type[Exception]
    label: str
    max_acceptance_bytes: int
    max_desired_bytes: int
    product_id: str
    record_type: type[_LocalReceiptT]
    resolve_epoch: Callable[[], _LegacyEpoch]
    review_live: Callable[[], _LocalReviewT]
    require_frozen_review: Callable[[_LocalReviewT], None]

    def accept_review(
        self,
        accepted_review_id: str,
        resource_kind: _LegacyResourceKind,
        *,
        require_live_resource_kind: Callable[[], None],
    ) -> _LocalReceiptT:
        review = self.review_live()
        if accepted_review_id != review.review_id:
            raise self.error_type(f"{self.label} review ID changed")
        self._require_epoch()
        proposed = self.record_type.create(review, resource_kind=resource_kind)

        epoch_runtime = self.epoch_runtime
        state_root = epoch_runtime.prepare_product_state_root()
        path = self._path(state_root, review.plugin_id)
        descriptor = os.open(
            state_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            before = os.fstat(descriptor)
            self._require_private_parent(state_root, before)
            with RootedFileIO(state_root, descriptor) as file_io:
                with file_io.bind(path) as target:
                    target.acquire_lock(exclusive=True, suffix=".lock")
                    epoch_runtime.assert_current()
                    try:
                        raw = target.read_bytes(max_bytes=self.max_acceptance_bytes)
                    except FileNotFoundError:
                        raw = None
                    if raw is not None:
                        records = self._decode(raw, path)
                        if len(records) != 1 or records[0] != proposed:
                            raise self.error_type(
                                f"{self.label} acceptance conflicts with prior review"
                            )
                    else:
                        desired = target.sibling("desired-state.jsonl")
                        desired.acquire_lock(exclusive=True, suffix=".lock")
                        self._require_unseen_installation(
                            desired,
                            state_root / "desired-state.jsonl",
                            review,
                        )
                        require_live_resource_kind()
                        if self.review_live() != review:
                            raise self.error_type(
                                f"{self.label} review changed before acceptance"
                            )
                        payload = encode_jsonl_record(
                            proposed,
                            record_codec=self.record_type._record_codec(),
                            format_profile=SORTED_UNICODE_JSONL_FORMAT,
                        )
                        target.atomic_write(payload, exclusive=True)
                        epoch_runtime.assert_current()
                self._require_private_parent_after(state_root, descriptor, before)
                return proposed
        finally:
            os.close(descriptor)

    def read_acceptance(
        self, plugin_id: str, *, check_live: bool = False
    ) -> _LocalReceiptT | None:
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError(f"{self.label} Plugin identity is required")
        self._require_epoch()
        epoch_runtime = self.epoch_runtime
        state_root = epoch_runtime.control_root / "product-state"
        path = self._path(state_root, plugin_id)
        try:
            descriptor = os.open(
                state_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
        except FileNotFoundError:
            epoch_runtime.assert_current()
            return None
        try:
            before = os.fstat(descriptor)
            self._require_private_parent(state_root, before)
            with RootedFileIO(state_root, descriptor) as file_io:
                with file_io.bind(path) as target:
                    try:
                        raw = target.read_bytes(max_bytes=self.max_acceptance_bytes)
                    except FileNotFoundError:
                        raw = None
                self._require_private_parent_after(state_root, descriptor, before)
        finally:
            os.close(descriptor)
        if raw is None:
            epoch_runtime.assert_current()
            return None
        records = self._decode(raw, path)
        if len(records) != 1:
            raise self.error_type(f"{self.label} acceptance has multiple records")
        record = records[0]
        self.require_frozen_review(record.review)
        epoch_runtime.assert_current()
        if check_live:
            if record != self.record_type.create(
                self.review_live(), resource_kind=record.resource_kind
            ):
                raise self.error_type(
                    f"{self.label} acceptance conflicts with current review"
                )
            epoch_runtime.assert_current()
        return record

    def _require_epoch(self) -> None:
        if not matches_epoch_layout(self.epoch_runtime, self.resolve_epoch()):
            raise self.error_type(f"{self.label} Product epoch changed")

    def _decode(self, raw: bytes, path: Path) -> tuple[_LocalReceiptT, ...]:
        return decode_jsonl(
            raw.decode("utf-8"),
            target=path,
            record_codec=self.record_type._record_codec(),
            load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
        ).records

    def _require_unseen_installation(
        self,
        desired: RootedFile,
        path: Path,
        review: _LocalReviewT,
    ) -> None:
        try:
            raw = desired.read_bytes(max_bytes=self.max_desired_bytes)
        except FileNotFoundError:
            return
        if raw and not raw.endswith(b"\n"):
            raise self.error_type("Product Desired State is incomplete")
        snapshot = decode_plugin_desired_state_snapshot(raw.decode("utf-8"), path=path)
        key = PluginInstallationKeyV1.workspace(self.product_id, review.scope_id, review.plugin_id)
        if any(item.installation_key == key for item in snapshot.installations):
            raise self.error_type(
                f"{self.label} Installation already has Product Desired history"
            )

    def _require_private_parent(self, path: Path, opened: os.stat_result) -> None:
        if not _private_parent_matches(path, opened):
            raise self.error_type(f"{self.label} Product state directory is unsafe")

    def _require_private_parent_after(
        self,
        path: Path,
        descriptor: int,
        before: os.stat_result,
    ) -> None:
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise self.error_type(f"{self.label} Product state directory changed")
        self._require_private_parent(path, after)

    @staticmethod
    def _path(state_root: Path, plugin_id: str) -> Path:
        name_digest = sha256(plugin_id.encode()).hexdigest()[:24]
        return state_root / f"legacy-local-acceptance-{name_digest}.jsonl"


class _ConfiguredSource(Protocol):
    @property
    def scope(self) -> Literal["global", "project"]: ...
    @property
    def path(self) -> str: ...


class _AcceptedReview(Protocol):
    @property
    def namespace_id(self) -> str: ...

    @property
    def scope_id(self) -> str: ...

    @property
    def policy_revision(self) -> str: ...

    @property
    def store_id(self) -> str: ...

    @property
    def plugin_id(self) -> str: ...
    @property
    def review_id(self) -> str: ...
    @property
    def legacy_source_identity(self) -> str: ...
    @property
    def configured_plugin_source_scope(self) -> str | None: ...

    @property
    def desired_state(self) -> str: ...

    @property
    def legacy_binding_digest(self) -> str: ...

    @property
    def source_content_digest(self) -> str: ...

    @property
    def manifest_digest(self) -> str: ...

    @property
    def dependency_lock_digest(self) -> str: ...

    @property
    def wheel_filename(self) -> str: ...

    @property
    def wheel_artifact_digest(self) -> str: ...


class _AcceptedSource(Protocol):
    @property
    def acceptance_id(self) -> str: ...
    @property
    def review(self) -> _AcceptedReview: ...

    @property
    def resource_kind(self) -> str: ...


class LegacyLocalBindingRecord:
    """Validate and encode the exact binding produced by an accepted legacy review."""

    __slots__ = ()
    record_revision: int
    store_id: str
    namespace_id: str
    scope_id: str
    plugin_id: str
    legacy_source_identity: str
    legacy_binding_digest: str
    source_content_digest: str
    manifest_digest: str
    dependency_lock_digest: str
    wheel_filename: str
    artifact_digest: str
    requested_package: str
    plugin_manifest_path: str
    policy_revision: str
    approval_id: str
    record_id: str
    record_version: int
    resource_kind: _LegacyResourceKind
    _binding_schema: ClassVar[RecordSchema]
    _candidate_type: ClassVar[type[_LegacyLocalWheelFields]]
    _reserved_plugin_ids: ClassVar[frozenset[str]]
    _invalid_record: ClassVar[str]
    _invalid_code: ClassVar[str]

    @staticmethod
    def _trust_class_for(resource_kind: _LegacyResourceKind) -> str:
        raise NotImplementedError

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Legacy Product binding revision is invalid")
        for value, name in (
            (self.store_id, "Store"),
            (self.scope_id, "scope"),
            (self.plugin_id, "Plugin"),
            (self.policy_revision, "policy"),
            (self.approval_id, "approval"),
        ):
            if not isinstance(value, str) or LEGACY_REVIEW_ID.fullmatch(value) is None:
                raise ValueError(f"Legacy Product {name} identity is invalid")
        if self.plugin_id in self._reserved_plugin_ids:
            raise ValueError("Legacy Product binding cannot replace a builtin Plugin")
        for value, name in (
            (self.namespace_id, "namespace"),
            (self.legacy_binding_digest, "old binding"),
            (self.source_content_digest, "Source content"),
            (self.manifest_digest, "manifest"),
            (self.dependency_lock_digest, "dependency lock"),
            (self.artifact_digest, "Wheel artifact"),
            (self.record_id, "record"),
        ):
            if (
                not isinstance(value, str)
                or LEGACY_REVIEW_DIGEST.fullmatch(value) is None
            ):
                raise ValueError(f"Legacy Product {name} digest is invalid")
        if (
            not isinstance(self.legacy_source_identity, str)
            or not self.legacy_source_identity.startswith("local:")
            or len(self.legacy_source_identity) > 4096
            or LEGACY_SOURCE_WHEEL_FILENAME.fullmatch(self.wheel_filename) is None
            or type(self.record_version) is not int
            or _RESOURCE_KIND_VERSION.get(self.resource_kind) != self.record_version
        ):
            raise ValueError("Legacy Product binding Source shape is invalid")
        if not self._wheel_names_match():
            raise ValueError("Legacy Product binding Wheel identity is inconsistent")
        binding = self.to_policy_binding(Path("/"))
        if binding.requested_package != self.requested_package:
            raise ValueError("Legacy Product binding package is invalid")
        if self.record_id != wheel_source_binding_digest(self.to_dict()):
            raise ValueError("Legacy Product binding record identity is invalid")

    @classmethod
    def create(
        cls,
        *,
        record_revision: int,
        store_id: str,
        namespace_id: str,
        scope_id: str,
        legacy_source_identity: str,
        legacy_binding_digest: str,
        dependency_lock_digest: str,
        policy_revision: str,
        approval_id: str,
        candidate: _LegacyLocalWheelFields,
        resource_kind: _LegacyResourceKind = "skill",
    ) -> Self:
        if not isinstance(candidate, cls._candidate_type):
            raise TypeError("Reacquired legacy Wheel candidate is required")
        if legacy_source_identity != candidate.original_source_identity:
            raise ValueError("Legacy Product original Source identity changed")
        record_version = _RESOURCE_KIND_VERSION.get(resource_kind)
        if record_version is None:
            raise ValueError("Unsupported legacy Product Resource type")
        values: dict[str, object] = {
            "recordRevision": record_revision,
            "storeId": store_id,
            "namespaceId": namespace_id,
            "scopeId": scope_id,
            "pluginId": candidate.plugin_id,
            "legacySourceIdentity": legacy_source_identity,
            "legacyBindingDigest": legacy_binding_digest,
            "sourceContentDigest": candidate.source_content_digest,
            "manifestDigest": candidate.manifest_digest,
            "dependencyLockDigest": dependency_lock_digest,
            "wheelFilename": candidate.filename,
            "artifactDigest": candidate.artifact_digest,
            "requestedPackage": candidate.requested_package,
            "pluginManifestPath": candidate.plugin_manifest_path,
            "policyRevision": policy_revision,
            "approvalId": approval_id,
            "recordVersion": record_version,
        }
        if record_version >= 2:
            values["resourceKind"] = resource_kind
        values["recordId"] = wheel_source_binding_digest(values)
        construct: Callable[..., Self] = cls
        return construct(
            **cls._binding_schema.decode(dict, values), resource_kind=resource_kind
        )

    def to_dict(self) -> dict[str, object]:
        record = self._binding_schema.encode(self)
        if self.record_version >= 2:
            record["resourceKind"] = self.resource_kind
        return record

    @classmethod
    def from_dict(cls, value: object) -> Self:
        expected = cls._binding_schema.keys
        if type(value) is not dict or set(value) not in (
            expected,
            expected | {"resourceKind"},
        ):
            raise JournalCodecError(cls._invalid_record, code=cls._invalid_code)
        try:
            kind = _legacy_resource_kind(
                value,
                value["recordVersion"],
                invalid_version="Unsupported legacy Product binding version",
                invalid_kind="Unsupported legacy Product binding type",
            )
            construct: Callable[..., Self] = cls
            return construct(
                **cls._binding_schema.decode(dict, value), resource_kind=kind
            )
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                cls._invalid_record, code=cls._invalid_code
            ) from exc

    def to_policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return PackageProductLocalWheelBindingV1(
            source_identity=str(source_root / self.wheel_filename),
            requested_package=self.requested_package,
            plugin_id=self.plugin_id,
            artifact_digest=self.artifact_digest,
            plugin_manifest_path=self.plugin_manifest_path,
            source_trust_class=self._trust_class_for(self.resource_kind),
        )

    @classmethod
    def _record_codec(cls) -> FunctionalJournalRecordCodec[Self]:
        return FunctionalJournalRecordCodec(encoder=cls.to_dict, decoder=cls.from_dict)

    def _wheel_names_match(self) -> bool:
        prefix = self.wheel_filename.removesuffix("-1-py3-none-any.whl")
        return (
            self.requested_package == f"{prefix.replace('_', '-')}==1"
            and self.plugin_manifest_path == f"{prefix}/plugin.json"
        )

    def _matches_approval(self, accepted: _AcceptedSource) -> bool:
        review = accepted.review
        return (
            self.approval_id == accepted.acceptance_id
            and self.resource_kind == accepted.resource_kind
            and self.store_id == review.store_id
            and self.namespace_id == review.namespace_id
            and self.scope_id == review.scope_id
            and self.plugin_id == review.plugin_id
            and self.legacy_source_identity == review.legacy_source_identity
            and self.legacy_binding_digest == review.legacy_binding_digest
            and self.source_content_digest == review.source_content_digest
            and self.manifest_digest == review.manifest_digest
            and self.dependency_lock_digest == review.dependency_lock_digest
            and self.wheel_filename == review.wheel_filename
            and self.artifact_digest == review.wheel_artifact_digest
            and self._wheel_names_match()
            and self.policy_revision == review.policy_revision
        )


def verify_accepted_legacy_wheel(
    accepted: _AcceptedSource,
    binding: _BindingHead,
    wheel: _LegacyLocalWheelFields,
    *,
    desired_state: str,
    inspected_kind: str,
    error_type: Callable[[str], Exception],
) -> None:
    """Prove that the live artifact still matches the approved selection."""
    review = accepted.review
    if (
        inspected_kind != accepted.resource_kind
        or desired_state != review.desired_state
        or binding.plugin_id != review.plugin_id
        or binding.source_identity != review.legacy_source_identity
        or binding.binding_digest != review.legacy_binding_digest
        or binding.content_digest != review.source_content_digest
        or binding.manifest_digest != review.manifest_digest
        or binding.dependency_lock.digest != review.dependency_lock_digest
        or wheel.plugin_id != review.plugin_id
        or wheel.original_source_identity != review.legacy_source_identity
        or wheel.source_content_digest != review.source_content_digest
        or wheel.manifest_digest != review.manifest_digest
        or wheel.filename != review.wheel_filename
        or wheel.artifact_digest != review.wheel_artifact_digest
    ):
        raise error_type("Legacy local Source differs from accepted review")


@dataclass(frozen=True, slots=True)
class _FrozenSources:
    projection_digest: str
    by_plugin: Mapping[str, _ConfiguredSource | None]
    ordered_paths: dict[str, tuple[str, ...]]
    raw_digests: dict[str, str]


def project_frozen_legacy_sources(
    acceptance: _AcceptedSource,
    projection: dict[str, object],
    *,
    projection_digest: str,
    by_plugin: Mapping[str, _ConfiguredSource | None],
    error_type: type[Exception],
) -> _FrozenSources:
    """Join the accepted source, original ordering and locked settings digests."""
    review = acceptance.review
    if review.plugin_id not in by_plugin:
        raise error_type("Accepted Plugin differs from first-fence Installation")
    configured = by_plugin[review.plugin_id]
    if (
        None if configured is None else configured.scope
    ) != review.configured_plugin_source_scope:
        raise error_type("Accepted configured Source differs from first fence")
    scopes = projection["scopes"]
    assert isinstance(scopes, dict)
    ordered_paths: dict[str, tuple[str, ...]] = {}
    raw_digests: dict[str, str] = {}
    for scope in ("global", "project"):
        layer = scopes[scope]
        paths = tuple(layer["sourcePatch"].get("plugin_sources", ()))
        ordered_paths[scope] = paths
        if paths:
            raw_digest = layer["rawSha256"]
            if not isinstance(raw_digest, str):
                raise error_type(
                    "Configured Source settings snapshot has no raw digest"
                )
            raw_digests[scope] = raw_digest
    matched = {item.path for item in by_plugin.values() if item is not None}
    if matched != set(ordered_paths["global"] + ordered_paths["project"]):
        raise error_type("Installed Source set differs from configured Sources")
    return _FrozenSources(projection_digest, by_plugin, ordered_paths, raw_digests)


class _SourceConsumptionSettings(Protocol):
    @property
    def global_settings_path(self) -> Path | None: ...

    @property
    def project_settings_path(self) -> Path | None: ...

    def transaction(self) -> AbstractContextManager[object]: ...

    def get_session_settings(self) -> Mapping[str, object]: ...

    def get_global_settings(self) -> Mapping[str, object]: ...

    def get_project_settings(self) -> Mapping[str, object]: ...

    def update_settings(
        self,
        *,
        scope: Literal["global", "project"],
        plugin_sources: tuple[str, ...],
    ) -> None: ...


@dataclass(frozen=True)
class _SourceConsumptionProtocol:
    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    acceptance: _AcceptedSource
    settings: _SourceConsumptionSettings
    frozen: _FrozenSources
    reopen_acceptance: Callable[[str], _AcceptedSource | None]
    projection: _LegacySourceProjection
    other_source_keys: frozenset[str]
    receipt_bytes: Callable[[dict[str, object], str], bytes]
    error_type: type[Exception]
    max_receipt_bytes: int

    def consume(self) -> None:
        epoch_runtime, acceptance, settings, frozen = (
            self.epoch_runtime,
            self.acceptance,
            self.settings,
            self.frozen,
        )
        configured = frozen.by_plugin[acceptance.review.plugin_id]
        if configured is None:
            with settings.transaction():
                settled_others = self._settled_other_paths(
                    epoch_runtime, acceptance, frozen
                )
                self._live_state(settings, None, frozen, settled_others)
            epoch_runtime.assert_current()
            return
        state_root = epoch_runtime.prepare_product_state_root()
        path = self._receipt_path(state_root, acceptance.review.plugin_id)
        expected = self._identity(acceptance, configured, frozen.projection_digest)
        with self._rooted_file(state_root, path) as target:
            target.acquire_lock(exclusive=True, suffix=".lock")
            phase = self._read_phase(target, expected)
            with settings.transaction():
                settled_others = self._settled_other_paths(
                    epoch_runtime, acceptance, frozen
                )
                state = self._live_state(settings, configured, frozen, settled_others)
                if phase is None:
                    if state != "original":
                        raise self.error_type(
                            "Accepted configured Source changed before consumption"
                        )
                    epoch_runtime.assert_current()
                    target.atomic_write(
                        self.receipt_bytes(expected, "prepared"), exclusive=True
                    )
                    phase = "prepared"
                if phase == "settled":
                    if state != "cleared":
                        raise self.error_type("Consumed configured Source was restored")
                    epoch_runtime.assert_current()
                    return
                if state == "original":
                    remaining = tuple(
                        path
                        for path in frozen.ordered_paths[configured.scope]
                        if path not in settled_others and path != configured.path
                    )
                    settings.update_settings(
                        scope=configured.scope, plugin_sources=remaining
                    )
                    if (
                        self._live_state(settings, configured, frozen, settled_others)
                        != "cleared"
                    ):
                        raise self.error_type(
                            "Configured Source setting was not consumed"
                        )
                epoch_runtime.assert_current()
                target.atomic_write(self.receipt_bytes(expected, "settled"))
                epoch_runtime.assert_current()

    def consumed(self) -> bool:
        epoch_runtime, acceptance, settings, frozen = (
            self.epoch_runtime,
            self.acceptance,
            self.settings,
            self.frozen,
        )
        configured = frozen.by_plugin[acceptance.review.plugin_id]
        state_root = epoch_runtime.control_root / "product-state"
        if configured is not None:
            phase = self._source_phase(state_root, acceptance, configured, frozen)
            if phase != "settled":
                return False
        with settings.transaction():
            settled_others = self._settled_other_paths(
                epoch_runtime, acceptance, frozen
            )
            result = (
                self._live_state(settings, configured, frozen, settled_others)
                == "cleared"
            )
        epoch_runtime.assert_current()
        return result

    def _source_phase(
        self,
        state_root: Path,
        acceptance: _AcceptedSource,
        configured: _ConfiguredSource,
        frozen: _FrozenSources,
    ) -> Literal["prepared", "settled"] | None:
        path = self._receipt_path(state_root, acceptance.review.plugin_id)
        try:
            with self._rooted_file(state_root, path) as target:
                return self._read_phase(
                    target,
                    self._identity(acceptance, configured, frozen.projection_digest),
                )
        except FileNotFoundError:
            return None

    def _settled_other_paths(
        self,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
        acceptance: _AcceptedSource,
        frozen: _FrozenSources,
    ) -> frozenset[str]:
        state_root = epoch_runtime.control_root / "product-state"
        settled: set[str] = set()
        for plugin_id, configured in frozen.by_plugin.items():
            if configured is None or plugin_id == acceptance.review.plugin_id:
                continue
            other = self.reopen_acceptance(plugin_id)
            if other is None:
                continue
            if (
                other.review.legacy_source_identity != f"local:{configured.path}"
                or other.review.configured_plugin_source_scope != configured.scope
            ):
                raise self.error_type("Other configured Source acceptance changed")
            if self._source_phase(state_root, other, configured, frozen) == "settled":
                settled.add(configured.path)
        return frozenset(settled)

    def _live_state(
        self,
        settings: _SourceConsumptionSettings,
        configured: _ConfiguredSource | None,
        frozen: _FrozenSources,
        settled_others: frozenset[str],
    ) -> Literal["original", "cleared"]:
        if settings.get_session_settings():
            raise self.error_type(
                "Session settings cannot enter configured Source consumption"
            )
        scoped = {
            "global": settings.get_global_settings(),
            "project": settings.get_project_settings(),
        }
        state: Literal["original", "cleared"] = "cleared"
        for scope, patch in scoped.items():
            if any(patch.get(key) for key in self.other_source_keys):
                raise self.error_type(
                    "Another configured Source appeared during consumption"
                )
            selected = patch.get("plugin_sources", [])
            if not isinstance(selected, list):
                raise self.error_type(
                    "Configured Source setting changed during consumption"
                )
            original = frozen.ordered_paths[scope]
            pending = [path for path in original if path not in settled_others]
            if configured is not None and configured.scope == scope:
                without_current = [path for path in pending if path != configured.path]
                if selected == pending:
                    state = "original"
                elif selected == without_current:
                    state = "cleared"
                else:
                    raise self.error_type(
                        "Configured Source setting changed during consumption"
                    )
            elif selected != pending:
                raise self.error_type(
                    "Other configured Source changed during consumption"
                )
            if original and selected == list(original):
                path = (
                    self._settings_paths(settings, self.error_type)[0]
                    if scope == "global"
                    else self._settings_paths(settings, self.error_type)[1]
                )
                _present, observed = self.projection.verify_loaded_settings(path, patch)
                if observed != frozen.raw_digests[scope]:
                    raise self.error_type(
                        "Configured Source settings changed since first fence"
                    )
        return state

    def _identity(
        self,
        acceptance: _AcceptedSource,
        configured: _ConfiguredSource,
        projection_digest: str,
    ) -> dict[str, object]:
        return {
            "receiptVersion": 1,
            "acceptanceId": acceptance.acceptance_id,
            "reviewId": acceptance.review.review_id,
            "projectionDigest": projection_digest,
            "scope": configured.scope,
            "sourcePath": configured.path,
        }

    @staticmethod
    def _receipt_path(state_root: Path, plugin_id: str) -> Path:
        return state_root / (
            "legacy-local-source-consumption-"
            + sha256(plugin_id.encode()).hexdigest()[:24]
            + ".json"
        )

    def _read_phase(
        self, target: RootedFile, identity: dict[str, object]
    ) -> Literal["prepared", "settled"] | None:
        try:
            raw = target.read_bytes(max_bytes=self.max_receipt_bytes)
        except FileNotFoundError:
            return None
        if raw == self.receipt_bytes(identity, "prepared"):
            return "prepared"
        if raw == self.receipt_bytes(identity, "settled"):
            return "settled"
        raise self.error_type(
            "Configured Source consumption receipt conflicts with accepted review"
        )

    @staticmethod
    def _settings_paths(
        settings: _SourceConsumptionSettings, error_type: type[Exception]
    ) -> tuple[Path, Path]:
        global_path = settings.global_settings_path
        project_path = settings.project_settings_path
        if not isinstance(global_path, Path) or not isinstance(project_path, Path):
            raise error_type("Configured Source settings paths are required")
        return global_path, project_path

    @contextmanager
    def _rooted_file(self, root: Path, path: Path) -> Iterator[RootedFile]:
        descriptor = os.open(
            root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            before = os.fstat(descriptor)
            if not _private_parent_matches(root, before):
                raise self.error_type(
                    "Configured Source Product state directory is unsafe"
                )
            with RootedFileIO(root, descriptor) as file_io:
                with file_io.bind(path) as target:
                    yield target
        finally:
            os.close(descriptor)


def match_legacy_replay_source(
    bindings: Sequence[PackageProductLocalWheelBindingV1],
    accepted: _AcceptedSource,
    *,
    plugin_id: str,
    trust_classes: Collection[str],
    expected_trust: str,
) -> tuple[bool, PackageProductLocalWheelBindingV1 | None]:
    """Report whether the selected legacy binding is absent or exactly approved."""
    matches = tuple(
        item
        for item in bindings
        if item.plugin_id == plugin_id and item.source_trust_class in trust_classes
    )
    if not matches:
        return True, None
    candidate = matches[0]
    if (
        len(matches) != 1
        or candidate.source_trust_class != expected_trust
        or candidate.artifact_digest != accepted.review.wheel_artifact_digest
        or Path(candidate.source_identity).name != accepted.review.wheel_filename
    ):
        return False, None
    return True, candidate


_AcceptedT = TypeVar("_AcceptedT", bound=_AcceptedSource)
_InstallationReceiptT = TypeVar("_InstallationReceiptT")
_EnablementReceiptT = TypeVar("_EnablementReceiptT")


_ReplayRoute = tuple[
    Callable[..., _FirstAcceptanceRecord[Any] | None], Callable[..., object]
]
_ReplayLayoutT = TypeVar("_ReplayLayoutT")


def replay_posix_legacy_product_cutover(
    layout: _ReplayLayoutT,
    open_settings: Callable[[], SettingsManager],
    *,
    roots: FencedRuntimeOpenKwargs,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    inventory_query: Callable[
        [_ReplayLayoutT, PackageProductPosixFencedRuntimeOwner],
        Callable[[], LegacyInventoryEvidence],
    ],
    read_local_acceptance: Callable[..., LegacyLocalAcceptanceRecord[Any] | None],
    local_adoption_settled: Callable[..., bool],
    policy_revision: str,
    disabled: _ReplayRoute,
    builtin: _ReplayRoute,
    removed: _ReplayRoute,
    bootstrap: Callable[..., object],
    default_local_kind: _LegacyResourceKind,
    removals_pending: str,
    sources_pending: str,
    before_local_adoption: bool = False,
) -> None:
    """Close the read-only inventory before replaying any accepted changes."""
    read_disabled, replay_disabled = disabled
    read_builtin, replay_builtin = builtin
    read_removed, replay_removed = removed
    owner = PackageProductPosixFencedRuntimeOwner.open(**roots, read_only=True)
    with handoff_product_open(owner, cleanup_note="Legacy Product replay epoch cleanup also failed"):
        settings = open_settings()
    with owner:
        inventory = inventory_query(layout, owner)().inventory
        pending_removals = bool(inventory.unselected_source_identities)
        if before_local_adoption and not pending_removals:
            return
        # A local adoption only settles the removals that precede its own receipt.
        local_ids = () if before_local_adoption else tuple(
            binding.plugin_id for binding, _, _ in inventory.active_local
        )
        accepted_kinds = {
            plugin_id: accepted.resource_kind
            for plugin_id in local_ids
            if (
                accepted := read_local_acceptance(
                    layout, owner, plugin_id=plugin_id, policy_revision=policy_revision
                )
            )
            is not None
        }
        disabled_acceptance = builtin_acceptance = None
        if not local_ids and not before_local_adoption:
            disabled_acceptance = read_disabled(layout, owner, settings_manager=settings)
            builtin_acceptance = read_builtin(layout, owner, settings_manager=settings)
        removed_acceptance = read_removed(layout, owner, settings_manager=settings)
        if before_local_adoption and removed_acceptance is None:
            raise ValueError(removals_pending)

    replay_options = dict(
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    if pending_removals and removed_acceptance is None:
        raise RuntimeError(removals_pending)
    if removed_acceptance is not None and (pending_removals or not local_ids):
        replay_removed(
            layout,
            settings,
            accepted_review_id=removed_acceptance.review.review_id,
            **replay_options,
        )
    if local_ids:
        if not all(
            local_adoption_settled(
                layout,
                plugin_id=plugin_id,
                workspace=workspace,
                resource_kind=accepted_kinds.get(plugin_id, default_local_kind),
            )
            for plugin_id in local_ids
        ):
            raise RuntimeError(sources_pending)
        return
    if removed_acceptance is not None:
        return
    for acceptance, replay in (
        (builtin_acceptance, replay_builtin),
        (disabled_acceptance, replay_disabled),
    ):
        if acceptance is not None:
            replay(
                layout,
                settings,
                accepted_review_id=acceptance.review.review_id,
                **replay_options,
            )
            return
    bootstrap(layout, settings, **replay_options)


def adopt_legacy_local_data(
    *,
    open_epoch: Callable[[], PackageProductPosixFencedRuntimeOwner],
    open_application: Callable[[], FencedOrdinaryProductApplication],
    accept_and_consume: Callable[
        [PackageProductPosixFencedRuntimeOwner], tuple[_AcceptedT, bool]
    ],
    bind_source: Callable[[PackageProductPosixFencedRuntimeOwner, bool], None],
    plugin_id: str,
    trust_classes: Collection[str],
    expected_trust: Callable[[], str],
    changed_message: str,
    install: Callable[[], _InstallationReceiptT],
    enable: Callable[[], _EnablementReceiptT],
    reviewed_choices: Callable[[_AcceptedT], ReviewedPluginChoices],
    builtin_plugin_ids: tuple[str, ...],
    bootstrap_policy: _PluginBootstrapPolicy,
    removal_label: str,
) -> tuple[_AcceptedT, _InstallationReceiptT, _EnablementReceiptT | None]:
    """Complete the replayable Source, installation and builtin adoption chain."""
    with hold_accepted_product_adoption(
        open_epoch=open_epoch,
        accept_review=accept_and_consume,
        open_application=open_application,
    ) as ((acceptance, admission_checked), application):
        matches, bound = match_legacy_replay_source(
            application.runtime_owner.product_owner.policy.bindings,
            acceptance,
            plugin_id=plugin_id,
            trust_classes=trust_classes,
            expected_trust=expected_trust(),
        )
        if not matches:
            raise RuntimeError(changed_message)
    if bound is None:
        with closing(open_epoch()) as epoch:
            bind_source(epoch, admission_checked)
    installation = install()
    enablement = enable() if acceptance.review.desired_state == "installed_enabled" else None
    with closing(open_application()) as application:
        choices = reviewed_choices(acceptance)
        replay_reviewed_product_plugins(
            application.runtime_owner.product_owner,
            builtin_plugin_ids,
            choices=choices,
            removal_label=removal_label,
            policy=bootstrap_policy,
            strict_history=False,
        )
    return acceptance, installation, enablement


class _LegacyLocalInstallationResult(NamedTuple):
    acceptance_id: str
    install_operation_id: str
    install_command_id: str
    enable_operation_id: str
    package_revision: PluginPackageRevisionRefV1


@dataclass(frozen=True, slots=True)
class _LegacyLocalInstallPolicy:
    product_id: str
    install_prefix: str
    enable_prefix: str
    session_prefix: str
    error_type: type[Exception]

    def operation_identity(
        self, accepted: _AcceptedSource, *, scope_id: str, plugin_id: str
    ) -> tuple[PluginInstallationKeyV1, str, str]:
        key = PluginInstallationKeyV1.workspace(self.product_id, scope_id, plugin_id)
        store_id = accepted.review.store_id
        acceptance_id = accepted.acceptance_id
        digest = sha256(f"{store_id}\0{acceptance_id}".encode()).hexdigest()
        return key, self.install_prefix + digest, self.enable_prefix + digest

    def replay(
        self,
        application: FencedOrdinaryProductApplication,
        *,
        reopen_acceptance: Callable[
            [PackageProductPosixFencedRuntimeOwner], _AcceptedT | None
        ],
        scope_id: str,
        plugin_id: str,
        trust_class_for: Callable[[_AcceptedT], str],
        enable: bool,
        resource_kind: str | None,
    ) -> _LegacyLocalInstallationResult:
        """Hold the original epoch through acceptance, Desired replay and receipt."""
        with closing(application):
            epoch = application.epoch_runtime
            if not isinstance(epoch, PackageProductPosixFencedRuntimeOwner):
                raise self.error_type(
                    "Legacy local migration requires a POSIX Product epoch"
                )
            accepted = reopen_acceptance(epoch)
            if accepted is None or (
                enable
                and (
                    accepted.resource_kind != resource_kind
                    or accepted.review.desired_state != "installed_enabled"
                )
            ):
                raise self.error_type(
                    "Legacy local data Resource has no accepted enabled selection"
                    if enable
                    else "Legacy local Installation has no accepted review"
                )
            installation = _LegacyLocalInstallation.from_accepted_source(
                application.runtime_owner.product_owner,
                accepted,
                scope_id=scope_id,
                plugin_id=plugin_id,
                source_trust_class=trust_class_for(accepted),
                policy=self,
            )
            command_id, revision = (
                installation.enable()
                if enable
                else installation.install(
                    allow_enabled=accepted.review.desired_state == "installed_enabled"
                )
            )
            epoch.assert_current()
            return _LegacyLocalInstallationResult(
                accepted.acceptance_id,
                installation.install_operation_id,
                command_id,
                installation.enable_operation_id,
                revision,
            )


@dataclass(frozen=True)
class _LegacyLocalInstallation:
    """Replay one approved source through the existing Product Desired owner.

    Products supply admission, trust and operation prefixes. This owner
    executes the exact install/enable history and holds the runtime lifetime.
    """

    product: _ProductOwner
    key: PluginInstallationKeyV1
    source_identity: str
    install_operation_id: str
    enable_operation_id: str
    error_type: type[Exception]
    session_id_prefix: str

    @classmethod
    def from_accepted_source(
        cls,
        product: _ProductOwner,
        accepted: _AcceptedSource,
        *,
        scope_id: str,
        plugin_id: str,
        source_trust_class: str,
        policy: _LegacyLocalInstallPolicy,
    ) -> _LegacyLocalInstallation:
        review = accepted.review
        sources = tuple(
            binding
            for binding in product.policy.bindings
            if binding.plugin_id == plugin_id
            and binding.source_trust_class == source_trust_class
            and binding.artifact_digest == review.wheel_artifact_digest
            and Path(binding.source_identity).name == review.wheel_filename
        )
        if len(sources) != 1:
            raise policy.error_type(
                "Legacy local Installation has no exact Product Source binding"
            )
        key, install_id, enable_id = policy.operation_identity(
            accepted, scope_id=scope_id, plugin_id=plugin_id
        )
        return cls(
            product=product,
            key=key,
            source_identity=sources[0].source_identity,
            install_operation_id=install_id,
            enable_operation_id=enable_id,
            error_type=policy.error_type,
            session_id_prefix=policy.session_prefix,
        )

    def _settled_install_command(self) -> str:
        command_id = self.product.settled_install_command_id(
            operation_id=self.install_operation_id, plugin_id=self.key.plugin_id
        )
        if command_id is None:
            raise self.error_type("Legacy local Product install handoff is not settled")
        return command_id

    def _require_selected_revision(
        self, selected: PluginInstallationStateV1
    ) -> PluginPackageRevisionRefV1:
        revision = selected.selection.package_revision
        if (
            selected.selection.desired_state in {"installed_disabled", "installed_enabled"}
            and revision is not None
            and revision.package_source_identity == self.source_identity
        ):
            return revision
        raise self.error_type("Legacy local Product Installation selection changed")

    def _matches_enablement(
        self,
        transitions: tuple[PluginDesiredStateJournalTransition, ...],
        selected: PluginInstallationStateV1,
    ) -> bool:
        return (
            len(transitions) == 2
            and isinstance(transitions[1], PluginDesiredStateTransitionV1)
            and transitions[1].mutation.operation_id == self.enable_operation_id
            and transitions[1].mutation.actor_id == self.product.actor_id
            and transitions[1].committed_state == selected
        )

    def install(self, *, allow_enabled: bool) -> tuple[str, PluginPackageRevisionRefV1]:
        product, key = self.product, self.key
        initial = product.desired_state.snapshot()
        prior_state = next(
            (item for item in initial.installations if item.installation_key == key),
            None,
        )
        if prior_state is not None and prior_state.selection.desired_state not in {
            "installed_disabled",
            "installed_enabled",
        }:
            raise self.error_type(
                "Legacy local Product Desired State was independently changed"
            )
        if prior_state is None:
            self.route_install()
        command_id = self._settled_install_command()
        selected = product.desired_state.snapshot().installation(key)
        revision = self._require_selected_revision(selected)
        transitions = self._install_history(command_id, revision)
        if selected.selection.desired_state == "installed_disabled":
            if len(transitions) != 1 or transitions[0].committed_state != selected:
                raise self.error_type(
                    "Legacy local Product disablement was independently changed"
                )
        elif not allow_enabled or not self._matches_enablement(transitions, selected):
            raise self.error_type(
                "Legacy local Product enablement was independently changed"
            )
        return command_id, revision

    def enable(self) -> tuple[str, PluginPackageRevisionRefV1]:
        product, key = self.product, self.key
        install_command_id = self._settled_install_command()
        snapshot = product.desired_state.snapshot()
        selected = snapshot.installation(key)
        revision = self._require_selected_revision(selected)
        enable_id = self.enable_operation_id
        transitions = self._install_history(install_command_id, revision)
        if selected.selection.desired_state == "installed_enabled":
            if not self._matches_enablement(transitions, selected):
                raise self.error_type(
                    "Legacy local Product enablement was independently changed"
                )
        else:
            if len(transitions) != 1 or transitions[0].committed_state != selected:
                raise self.error_type(
                    "Legacy local Product disablement was independently changed"
                )
            enabled = product.management.submit(
                PluginManagementCommandV1(
                    action="enable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id=enable_id,
                        idempotency_key=enable_id,
                        expected_inventory_revision=snapshot.inventory_revision,
                        installation_key=key,
                        desired_state="installed_enabled",
                        package_revision=None,
                        actor_id=product.actor_id,
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            if enabled.result is None or enabled.result.disposition != "succeeded":
                raise self.error_type("Legacy local Product enablement refused")
            selected = product.desired_state.snapshot().installation(key)
            if (
                selected.selection.desired_state != "installed_enabled"
                or selected.selection.package_revision != revision
            ):
                raise self.error_type("Legacy local Product enablement handoff changed")
        final_transitions = tuple(
            transition
            for transition in product.desired_state.transitions()
            if transition.mutation.installation_key == key
        )
        if (
            not self._matches_enablement(final_transitions, selected)
            or product.desired_state.snapshot().installation(key) != selected
        ):
            raise self.error_type("Legacy local Product enablement was superseded")
        return install_command_id, revision

    def _install_history(
        self, command_id: str, revision: PluginPackageRevisionRefV1 | None
    ) -> tuple[PluginDesiredStateJournalTransition, ...]:
        transitions = tuple(
            transition
            for transition in self.product.desired_state.transitions()
            if transition.mutation.installation_key == self.key
        )
        event = _initial_legacy_install_event(transitions, command_id)
        if (
            event is None
            or event.mutation.actor_id != self.product.actor_id
            or event.committed_state.selection.package_revision != revision
        ):
            raise self.error_type("Legacy local Product install was superseded")
        return transitions

    def route_install(self) -> None:
        session_id = self.session_id_prefix + secrets.token_hex(16)
        with hold_local_wheel_product_runtime(
            self.product, product_id=self.key.product_id, session_id=session_id
        ) as binding:
            outcome = route_project_package(
                binding,
                operation_id=self.install_operation_id,
                action="install",
                source=self.source_identity,
                entrypoint="operations",
            )
            if (
                not outcome.handled
                or outcome.record is None
                or outcome.record.lifecycle != "installed"
                or outcome.evidence is None
                or outcome.evidence.operation_id != self.install_operation_id
            ):
                raise self.error_type("Legacy local Product Package install refused")


_LegacySourceScope = Literal["global", "project"]
_LEGACY_SOURCE_SCOPES: tuple[_LegacySourceScope, ...] = ("global", "project")
_LEGACY_PACKAGE_FILTER_KEYS = frozenset({"extensions", "skills", "prompts", "themes"})
_SOURCE_PROJECTION_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _valid_snapshot_package_source(value: object) -> bool:
    if isinstance(value, str):
        return bool(value)
    if not isinstance(value, dict) or not set(value) <= {
        "source",
        *_LEGACY_PACKAGE_FILTER_KEYS,
    }:
        return False
    source = value.get("source")
    if not isinstance(source, str) or not source:
        return False
    return all(
        isinstance(items, list)
        and all(isinstance(item, str) and item for item in items)
        for key, items in value.items()
        if key in _LEGACY_PACKAGE_FILTER_KEYS
    )


@dataclass(frozen=True)
class _LegacySourceProjection:
    """Keep the original Settings transaction and native projection alive together.

    Policy is data: recognized keys, scope markers and historical wire names.
    Config owns stable reads; native Resources owners create and settle roots.
    """

    product_id: str
    label: str
    source_keys: frozenset[str]
    key_markers: tuple[str, ...]
    projection_name: str
    prefix: str
    maximum_bytes: int
    loaded_fields: tuple[str, ...] = ()

    @contextmanager
    def hold(
        self,
        settings_manager: SettingsManager,
        *,
        global_settings_path: Path,
        project_settings_path: Path,
        projection_parent: Path,
    ) -> Iterator[Path]:
        if os.name not in {"posix", "nt"} or (
            os.name == "posix"
            and not all(
                hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
            )
        ):
            raise RuntimeError("Rooted Source projection is unavailable")
        if not isinstance(settings_manager, SettingsManager):
            raise TypeError(f"{self.label} settings manager is required")
        expected_paths = (
            self.require_path(global_settings_path, name="global settings"),
            self.require_path(project_settings_path, name="project settings"),
        )
        if expected_paths[0] == expected_paths[1]:
            raise ValueError(f"{self.label} Source settings scopes overlap")
        parent = self.require_private_parent(projection_parent)
        with settings_manager.transaction():
            observed_paths = (
                settings_manager.global_settings_path,
                settings_manager.project_settings_path,
            )
            if observed_paths != expected_paths:
                raise ValueError(f"{self.label} Source settings paths changed")
            session = settings_manager.get_session_settings()
            if any(self.looks_like_source_key(key) for key in session):
                raise ValueError(
                    f"{self.label} session Source overrides cannot be backed up"
                )
            layers = {}
            for scope, path, patch in (
                ("global", expected_paths[0], settings_manager.get_global_settings()),
                ("project", expected_paths[1], settings_manager.get_project_settings()),
            ):
                present, raw_digest = self.verify_loaded_settings(path, patch)
                if any(
                    self.looks_like_source_key(key) and key not in self.source_keys
                    for key in patch
                ):
                    raise ValueError(
                        f"{self.label} Source settings include an unmapped key"
                    )
                layers[scope] = {
                    "present": present,
                    "rawSha256": raw_digest,
                    "settingsPath": str(path),
                    "sourcePatch": {
                        key: patch[key]
                        for key in sorted(self.source_keys & patch.keys())
                    },
                }
            contents = self.projection_bytes(
                {"productId": self.product_id, "projectionVersion": 1, "scopes": layers}
            )
            with hold_legacy_product_projection_root(
                parent,
                prefix=self.prefix,
                projection_name=self.projection_name,
                projection_label=f"{self.label} Source projection",
                projection_contents=contents,
            ) as source_root:
                yield source_root

    def require_path(self, path: Path, *, name: str) -> Path:
        if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{self.label} {name} path is invalid")
        return path

    def require_private_parent(self, path: Path) -> Path:
        parent = self.require_path(path, name="Source projection parent")
        if os.name == "nt":
            with WindowsPrivateDirectoryAcl() as acl:
                root = _PinnedWindowsAuthority.open(parent, read_control=True)
                try:
                    acl.validate(root.descriptor)
                    root.assert_visible()
                finally:
                    root.close()
            return parent
        metadata = parent.lstat()
        getuid = getattr(os, "getuid", None)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or (callable(getuid) and metadata.st_uid != getuid())
        ):
            raise ValueError(f"{self.label} Source projection parent is not private")
        return parent

    def verify_loaded_settings(
        self, path: Path, loaded_patch: Mapping[str, object]
    ) -> tuple[bool, str | None]:
        present, digest, decoded = self.read_patch(path)
        if decoded != loaded_patch:
            raise ValueError(f"{self.label} Source settings changed after reload")
        return present, digest

    def read_patch(self, path: Path) -> tuple[bool, str | None, dict[str, object]]:
        """Read a settings patch before a Product owner creates its first lock."""

        self.require_path(path, name="settings")
        return _read_stable_json_patch(
            path,
            maximum_bytes=lambda: self.maximum_bytes,
            label=f"{self.label} Source settings",
        )

    def workspace_has_pre_fence_inputs(
        self, paths: tuple[Path, ...], settings_manager: SettingsManager | None
    ) -> bool:
        """Check effective settings before the ordered on-disk source patches."""
        if settings_manager is not None:
            if not isinstance(settings_manager, SettingsManager):
                raise TypeError(f"{self.label} Product settings manager is invalid")
            if self.has_loaded_pre_fence_inputs(settings_manager):
                return True
            paths = (*paths, *(
                path
                for path in (
                    settings_manager.global_settings_path, settings_manager.project_settings_path
                )
                if path is not None
            ))
        return self.has_pre_fence_inputs(*dict.fromkeys(paths))

    def has_loaded_pre_fence_inputs(self, settings_manager: SettingsManager) -> bool:
        settings = settings_manager.get_settings()
        return any(getattr(settings, field) for field in self.loaded_fields)

    def require_fresh_inputs(self, has_legacy_inputs: bool) -> None:
        if has_legacy_inputs:
            raise RuntimeError(
                f"{self.label} pre-B workspace is unsupported; use a fresh workspace"
            )

    def has_pre_fence_inputs(self, *paths: Path) -> bool:
        """Read settings in order and short-circuit on the first legacy input."""
        for path in paths:
            _, _, patch = self.read_patch(path)
            for key in self.source_keys & patch.keys():
                value = patch[key]
                if not isinstance(value, list) or value:
                    return True
        return False

    def classify(
        self,
        projection: object,
        *,
        disabled_setting: str,
        configured_source_keys: frozenset[str],
    ) -> tuple[tuple[tuple[_LegacySourceScope, str], ...], tuple[str, ...]]:
        """Check the frozen settings wire and report its scoped source choices."""
        if not isinstance(projection, dict) or set(projection) != {
            "productId",
            "projectionVersion",
            "scopes",
        }:
            raise ValueError(f"{self.label} Source projection is invalid")
        if (
            projection["productId"] != self.product_id
            or type(projection["projectionVersion"]) is not int
            or projection["projectionVersion"] != 1
        ):
            raise ValueError(f"{self.label} Source projection version is unsupported")
        scopes = projection["scopes"]
        if not isinstance(scopes, dict) or set(scopes) != set(_LEGACY_SOURCE_SCOPES):
            raise ValueError(f"{self.label} Source projection scopes are invalid")

        disabled: list[tuple[_LegacySourceScope, str]] = []
        sources: list[str] = []
        for scope in _LEGACY_SOURCE_SCOPES:
            layer = scopes[scope]
            if not isinstance(layer, dict) or set(layer) != {
                "present",
                "rawSha256",
                "settingsPath",
                "sourcePatch",
            }:
                raise ValueError(f"{self.label} Source projection layer is invalid")
            present, digest, path, patch = (
                layer["present"],
                layer["rawSha256"],
                layer["settingsPath"],
                layer["sourcePatch"],
            )
            if (
                type(present) is not bool
                or (
                    present
                    and (
                        not isinstance(digest, str)
                        or not _SOURCE_PROJECTION_DIGEST.fullmatch(digest)
                    )
                )
                or (not present and digest is not None)
                or not isinstance(path, str)
                or not Path(path).is_absolute()
                or ".." in Path(path).parts
                or not isinstance(patch, dict)
                or not set(patch) <= self.source_keys
                or (not present and patch)
                or ("packages" in patch and "package_sources" in patch)
            ):
                raise ValueError(f"{self.label} Source projection layer is invalid")
            for key, value in patch.items():
                if not isinstance(value, list):
                    raise ValueError(f"{self.label} legacy Source setting is invalid")
                if key == disabled_setting:
                    if any(not isinstance(item, str) or not item for item in value):
                        raise ValueError(f"{self.label} legacy disabled Plugin is invalid")
                    if len(value) != len(set(value)):
                        raise ValueError(f"{self.label} legacy disabled Plugin is duplicated")
                    disabled.extend((scope, item) for item in value)
                elif key in {"packages", "package_sources"}:
                    if any(not _valid_snapshot_package_source(item) for item in value):
                        raise ValueError(f"{self.label} legacy Package Source is invalid")
                elif any(not isinstance(item, str) or not item for item in value):
                    raise ValueError(f"{self.label} legacy Source setting is invalid")
                if key in configured_source_keys and value:
                    sources.append(f"{scope}:{key}")

        return tuple(disabled), tuple(sources)

    def index_configured_local_sources(
        self,
        projection: object,
        identities: tuple[str, ...],
        *,
        required_identity: str | None,
        max_sources: int,
        builtin_ids: frozenset[str],
        disabled_setting: str,
        configured_source_keys: frozenset[str],
    ) -> dict[str, _LegacySourceScope]:
        """Match each approved configured Source against the frozen installed set."""
        if (
            type(identities) is not tuple
            or not 0 < len(identities) <= max_sources
            or any(
                type(identity) is not str or not identity.startswith("local:/")
                for identity in identities
            )
            or len(identities) != len(set(identities))
            or (required_identity is not None and required_identity not in identities)
        ):
            raise ValueError("Legacy local data Source set is invalid")
        disabled, configured_keys = self.classify(
            projection,
            disabled_setting=disabled_setting,
            configured_source_keys=configured_source_keys,
        )
        if any(plugin_id not in builtin_ids for _, plugin_id in disabled):
            raise ValueError("Legacy local data settings need a separate migration")
        assert isinstance(projection, dict)
        scopes = projection["scopes"]
        configured: dict[str, _LegacySourceScope] = {}
        configured_scopes = 0
        for scope in _LEGACY_SOURCE_SCOPES:
            patch = scopes[scope]["sourcePatch"]
            if set(patch) - {disabled_setting, "plugin_sources"}:
                raise ValueError("Legacy local data settings need a separate migration")
            if "plugin_sources" not in patch:
                continue
            values = patch["plugin_sources"]
            if values:
                configured_scopes += 1
            for path in values:
                if (
                    not isinstance(path, str)
                    or not Path(path).is_absolute()
                    or any(part in {".", ".."} for part in path.split("/"))
                    or f"local:{path}" not in identities
                ):
                    raise ValueError(
                        "Configured Source must be the same installed local Source"
                    )
                if path in configured:
                    raise ValueError("Legacy Skill configured Sources are duplicated")
                configured[path] = scope
        if (
            len(configured) > len(identities)
            or len(configured_keys) != configured_scopes
        ):
            raise ValueError("Legacy local data settings need a separate migration")
        return configured

    def verify_snapshot(
        self,
        raw: bytes,
        *,
        global_settings_path: Path,
        project_settings_path: Path,
        classify: Callable[[object], RecordT],
        maximum_bytes: int,
        error_type: type[ValueError],
    ) -> tuple[RecordT, str]:
        """Verify the captured projection using the same encoder as its writer."""
        label = f"{self.label} Source projection"
        legacy_label = f"{self.label} legacy Source settings"
        if not isinstance(raw, bytes) or not raw or len(raw) > maximum_bytes:
            raise error_type(f"{legacy_label} projection exceeds budget")
        for path in (global_settings_path, project_settings_path):
            if (
                not isinstance(path, Path)
                or not path.is_absolute()
                or ".." in path.parts
            ):
                raise error_type(f"{legacy_label} path is invalid")
        if global_settings_path == project_settings_path:
            raise error_type(f"{legacy_label} scopes overlap")

        def reject_constant(value: str) -> object:
            raise ValueError(f"{label} has invalid constant: {value}")

        try:
            projection = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_json_object_hook(
                    lambda: f"{label} has duplicate JSON keys"
                ),
                parse_constant=reject_constant,
            )
            classification = classify(projection)
            if type(projection) is not dict:
                raise ValueError(f"{label} is not an object")
            scopes = projection["scopes"]
            if scopes["global"]["settingsPath"] != str(global_settings_path) or scopes[
                "project"
            ]["settingsPath"] != str(project_settings_path):
                raise ValueError(f"{self.label} Source settings path changed")
            if raw != self.projection_bytes(projection):
                raise ValueError(f"{label} bytes changed")
        except (UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise error_type(f"{legacy_label} projection is invalid") from exc
        return classification, sha256(raw).hexdigest()

    def looks_like_source_key(self, key: str) -> bool:
        return key in self.source_keys or any(
            marker in key for marker in self.key_markers
        )

    @staticmethod
    def projection_bytes(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")


def read_settled_legacy_local_adoption(
    accepted: _AcceptedSource,
    *,
    desired: PluginDesiredStateLedger,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    bindings: Sequence[PackageProductLocalWheelBindingV1],
    scope_id: str,
    plugin_id: str,
    source_trust_class: str,
    install_policy: _LegacyLocalInstallPolicy,
    builtin_ids: tuple[str, ...],
    choices: ReviewedPluginChoices,
    bootstrap_policy: _PluginBootstrapPolicy,
    handoff_error: str,
) -> bool:
    """Verify initial adoption on the original read-only Product owners."""
    matches, bound = match_legacy_replay_source(
        bindings,
        accepted,
        plugin_id=plugin_id,
        trust_classes=(source_trust_class,),
        expected_trust=source_trust_class,
    )
    if not matches or bound is None:
        return False
    handoffs = PackageRetentionHandoffJournal(
        epoch_runtime.control_root / "product-state" / "handoff.jsonl"
    )
    key, install_id, enable_id = install_policy.operation_identity(
        accepted,
        scope_id=scope_id,
        plugin_id=plugin_id,
    )
    require_enablement = accepted.review.desired_state == "installed_enabled"
    disabled_ids = frozenset(choices.disabled_ids)
    removed_operations = {
        name: choices.operation_id_for(name)
        for name in builtin_ids
        if name in choices.removed_ids
    }
    before, history = desired.capture_read_only()
    store_id = epoch_runtime.registry.store_id

    def transitions_for(
        selected: PluginInstallationKeyV1,
    ) -> tuple[PluginDesiredStateJournalTransition, ...]:
        return tuple(
            item for item in history if item.mutation.installation_key == selected
        )

    def command_for(operation_id: str, selected_plugin: str) -> str | None:
        receipt = handoffs.read_operation(operation_id)
        if receipt is None or receipt.state != "settled":
            return None
        request = receipt.request.desired_request
        if (
            receipt.desired_receipt is None
            or receipt.desired_receipt.request != request
            or request.operation_id != operation_id
            or request.plugin_id != selected_plugin
            or request.product_id != key.product_id
            or request.scope_id != key.scope_id
        ):
            raise ValueError(handoff_error)
        return request.command_id

    command_id = command_for(install_id, plugin_id)
    old_events = transitions_for(key)
    if not _initial_legacy_install_matches(
        old_events, command_id, bound.source_identity
    ):
        return False
    if require_enablement and not (
        _initial_legacy_enablement_matches(old_events, operation_id=enable_id)
    ):
        return False

    for builtin_id in builtin_ids:
        events = transitions_for(
            PluginInstallationKeyV1.workspace(key.product_id, key.scope_id, builtin_id)
        )
        if builtin_id in removed_operations:
            if (
                not events
                or events[0].mutation.operation_id != removed_operations[builtin_id]
                or events[0].committed_state.selection.desired_state != "absent"
                or any(
                    event.mutation.operation_id.startswith(
                        bootstrap_policy.operation_id_prefix
                    )
                    for event in events[1:]
                )
            ):
                return False
            continue
        command_id = command_for(
            bootstrap_policy.operation_id(store_id, builtin_id), builtin_id
        )
        builtin_sources = tuple(
            item.source_identity for item in bindings if item.plugin_id == builtin_id
        )
        if len(builtin_sources) != 1 or not _initial_legacy_install_matches(
            events, command_id, builtin_sources[0]
        ):
            return False
        if builtin_id in disabled_ids:
            if any(
                event.mutation.operation_id.startswith(
                    bootstrap_policy.enable_id_prefix
                )
                for event in events[1:]
            ):
                return False
        elif not _initial_legacy_enablement_matches(events):
            return False
    after, later_history = desired.capture_read_only()
    epoch_runtime.assert_current()
    return before == after and history == later_history


def _initial_legacy_install_event(
    events: tuple[PluginDesiredStateJournalTransition, ...], command_id: str | None
) -> PluginDesiredStateTransitionV1 | None:
    if (
        command_id is None
        or not events
        or not isinstance(events[0], PluginDesiredStateTransitionV1)
        or events[0].mutation.operation_id != command_id
        or events[0].committed_state.selection.desired_state != "installed_disabled"
    ):
        return None
    return events[0]


def _initial_legacy_install_matches(
    events: tuple[PluginDesiredStateJournalTransition, ...],
    command_id: str | None,
    source_identity: str,
) -> bool:
    event = _initial_legacy_install_event(events, command_id)
    if event is None:
        return False
    revision = event.committed_state.selection.package_revision
    return revision is not None and revision.package_source_identity == source_identity


def _initial_legacy_enablement_matches(
    events: tuple[PluginDesiredStateJournalTransition, ...],
    *,
    operation_id: str | None = None,
) -> bool:
    return (
        len(events) >= 2
        and isinstance(events[1], PluginDesiredStateTransitionV1)
        and (operation_id is None or events[1].mutation.operation_id == operation_id)
        and events[1].committed_state.selection.desired_state == "installed_enabled"
        and events[1].committed_state.selection.package_revision
        == events[0].committed_state.selection.package_revision
    )
