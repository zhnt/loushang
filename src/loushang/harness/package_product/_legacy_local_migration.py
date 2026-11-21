"""Fixed legacy acceptance and settings-consumption transactions.

Package Product owns receipt/Desired locking, replay, Settings transaction and
rooted IO. Products retain nominal codecs and authenticated legacy admission.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generic, Literal, Protocol, TypeVar

from loushang.foundation.json import _unique_json_object_hook
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.config.agent import SettingsManager
from loushang.harness.config.store import _read_stable_json_patch
from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
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
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _hold_windows_private_cutover_directory,
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    write_legacy_product_projection,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ._plugin_bootstrap import (
    _PluginBootstrapPolicy,
    _product_plugin_runtime,
    _ProductOwner,
)

RecordT = TypeVar("RecordT")
ReviewT = TypeVar("ReviewT")


@dataclass(frozen=True)
class _FirstAcceptanceEnvelope:
    """The common V1 acceptance envelope; review admission stays with its Product."""

    invalid_message: str
    invalid_code: str
    version_error: str
    identity_error: str

    @staticmethod
    def identity(review_id: str) -> str:
        return sha256(
            canonical_json_bytes({"acceptanceVersion": 1, "reviewId": review_id})
        ).hexdigest()

    def decode(
        self,
        value: object,
        review_decoder: Callable[[object], ReviewT],
        create: Callable[[ReviewT], RecordT],
    ) -> RecordT:
        if type(value) is not dict or set(value) != {
            "acceptanceId",
            "acceptanceVersion",
            "review",
        }:
            raise JournalCodecError(self.invalid_message, code=self.invalid_code)
        try:
            if (
                type(value["acceptanceVersion"]) is not int
                or value["acceptanceVersion"] != 1
            ):
                raise ValueError(self.version_error)
            record = create(review_decoder(value["review"]))
            if getattr(record, "acceptance_id") != value["acceptanceId"]:
                raise ValueError(self.identity_error)
            return record
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                self.invalid_message, code=self.invalid_code
            ) from exc


@dataclass(frozen=True)
class _FirstAcceptanceJournal(Generic[RecordT]):
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
    windows_receipts: WindowsPrivateReceiptIO | None = None
    windows_untouched_message: str = ""
    postcheck: Literal["separate", "combined"] = "separate"
    check_replay_epoch: bool = False

    def accept(
        self,
        epoch_runtime: (
            PackageProductPosixFencedRuntimeOwner
            | PackageProductWindowsFencedRuntimeOwner
        ),
        proposed: RecordT,
        *,
        conflict_message: str,
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
                    raise self.error_type(conflict_message)
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


@dataclass(frozen=True)
class _LocalAcceptanceProtocol(Generic[RecordT]):
    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    codec: JournalRecordCodec[RecordT]
    error_type: type[Exception]
    label: str
    max_acceptance_bytes: int
    max_desired_bytes: int

    def accept(
        self,
        proposed: RecordT,
        *,
        plugin_id: str,
        installation_key: Callable[[], PluginInstallationKeyV1],
        require_current_review: Callable[[], None],
    ) -> RecordT:
        epoch_runtime = self.epoch_runtime
        state_root = epoch_runtime.prepare_product_state_root()
        path = self._path(state_root, plugin_id)
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
                            installation_key,
                        )
                        require_current_review()
                        payload = encode_jsonl_record(
                            proposed,
                            record_codec=self.codec,
                            format_profile=SORTED_UNICODE_JSONL_FORMAT,
                        )
                        target.atomic_write(payload, exclusive=True)
                        epoch_runtime.assert_current()
                self._require_private_parent_after(state_root, descriptor, before)
                return proposed
        finally:
            os.close(descriptor)

    def reopen(self, plugin_id: str) -> RecordT | None:
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
        return records[0]

    def _decode(self, raw: bytes, path: Path) -> tuple[RecordT, ...]:
        return decode_jsonl(
            raw.decode("utf-8"),
            target=path,
            record_codec=self.codec,
            load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
        ).records

    def _require_unseen_installation(
        self,
        desired: RootedFile,
        path: Path,
        installation_key: Callable[[], PluginInstallationKeyV1],
    ) -> None:
        try:
            raw = desired.read_bytes(max_bytes=self.max_desired_bytes)
        except FileNotFoundError:
            return
        if raw and not raw.endswith(b"\n"):
            raise self.error_type("Product Desired State is incomplete")
        snapshot = decode_plugin_desired_state_snapshot(raw.decode("utf-8"), path=path)
        key = installation_key()
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
    def plugin_id(self) -> str: ...
    @property
    def review_id(self) -> str: ...
    @property
    def legacy_source_identity(self) -> str: ...
    @property
    def configured_plugin_source_scope(self) -> str | None: ...


class _AcceptedSource(Protocol):
    @property
    def acceptance_id(self) -> str: ...
    @property
    def review(self) -> _AcceptedReview: ...


@dataclass(frozen=True, slots=True)
class _FrozenSources:
    projection_digest: str
    by_plugin: Mapping[str, _ConfiguredSource | None]
    ordered_paths: dict[str, tuple[str, ...]]
    raw_digests: dict[str, str]


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


@dataclass(frozen=True)
class _LegacyLocalInstallation:
    """Replay one approved source through the existing Product Desired owner.

    Admission, trust and historical ID selection stay with the Product. This
    owner executes the exact install/enable history and runtime lifetime.
    """

    product: _ProductOwner
    key: PluginInstallationKeyV1
    source_identity: str
    install_operation_id: str
    enable_operation_id: str
    error_type: type[Exception]
    session_id_prefix: str

    def install(self, *, allow_enabled: bool) -> tuple[str, PluginPackageRevisionRefV1]:
        product, key, operation_id, plugin_id = (
            self.product,
            self.key,
            self.install_operation_id,
            self.key.plugin_id,
        )
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
        command_id = product.settled_install_command_id(
            operation_id=operation_id, plugin_id=plugin_id
        )
        if command_id is None:
            raise self.error_type("Legacy local Product install handoff is not settled")
        selected = product.desired_state.snapshot().installation(key)
        if (
            selected.selection.desired_state
            not in {"installed_disabled", "installed_enabled"}
            or selected.selection.package_revision is None
            or selected.selection.package_revision.package_source_identity
            != self.source_identity
        ):
            raise self.error_type("Legacy local Product Installation selection changed")
        transitions = self._install_history(
            command_id, selected.selection.package_revision
        )
        if selected.selection.desired_state == "installed_disabled":
            if len(transitions) != 1 or transitions[0].committed_state != selected:
                raise self.error_type(
                    "Legacy local Product disablement was independently changed"
                )
        elif (
            not allow_enabled
            or len(transitions) != 2
            or not isinstance(transitions[1], PluginDesiredStateTransitionV1)
            or transitions[1].mutation.operation_id != self.enable_operation_id
            or transitions[1].mutation.actor_id != product.actor_id
            or transitions[1].committed_state != selected
        ):
            raise self.error_type(
                "Legacy local Product enablement was independently changed"
            )
        return command_id, selected.selection.package_revision

    def enable(self) -> tuple[str, PluginPackageRevisionRefV1]:
        product, key, install_id, plugin_id = (
            self.product,
            self.key,
            self.install_operation_id,
            self.key.plugin_id,
        )
        install_command_id = product.settled_install_command_id(
            operation_id=install_id, plugin_id=plugin_id
        )
        if install_command_id is None:
            raise self.error_type("Legacy local Product install handoff is not settled")
        snapshot = product.desired_state.snapshot()
        selected = snapshot.installation(key)
        revision = selected.selection.package_revision
        if (
            revision is None
            or revision.package_source_identity != self.source_identity
            or selected.selection.desired_state
            not in {"installed_disabled", "installed_enabled"}
        ):
            raise self.error_type("Legacy local Product Installation selection changed")
        enable_id = self.enable_operation_id
        transitions = self._install_history(install_command_id, revision)
        if selected.selection.desired_state == "installed_enabled":
            if (
                len(transitions) != 2
                or not isinstance(transitions[1], PluginDesiredStateTransitionV1)
                or transitions[1].mutation.operation_id != enable_id
                or transitions[1].mutation.actor_id != product.actor_id
                or transitions[1].committed_state != selected
            ):
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
            len(final_transitions) != 2
            or not isinstance(final_transitions[1], PluginDesiredStateTransitionV1)
            or final_transitions[1].mutation.operation_id != enable_id
            or final_transitions[1].mutation.actor_id != product.actor_id
            or final_transitions[1].committed_state != selected
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
        if (
            not transitions
            or not isinstance(transitions[0], PluginDesiredStateTransitionV1)
            or transitions[0].mutation.operation_id != command_id
            or transitions[0].mutation.actor_id != self.product.actor_id
            or transitions[0].committed_state.selection.desired_state
            != "installed_disabled"
            or transitions[0].committed_state.selection.package_revision != revision
        ):
            raise self.error_type("Legacy local Product install was superseded")
        return transitions

    def route_install(self) -> None:
        session_id = self.session_id_prefix + secrets.token_hex(16)
        with _product_plugin_runtime(
            self.product, product_id=self.key.product_id, session_id=session_id
        ) as binding:
            outcome = binding.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id=self.install_operation_id,
                    action="install",
                    source=self.source_identity,
                    scope="project",
                ),
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
            if os.name == "nt":
                with _hold_windows_private_cutover_directory(
                    parent,
                    prefix=self.prefix,
                    projection_name=self.projection_name,
                    projection_label=f"{self.label} Source projection",
                    projection_contents=contents,
                ) as source_root:
                    yield source_root
            else:
                with TemporaryDirectory(prefix=self.prefix, dir=parent) as raw:
                    source_root = Path(raw)
                    write_legacy_product_projection(
                        source_root,
                        projection_name=self.projection_name,
                        contents=contents,
                    )
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

    def has_pre_fence_inputs(self, *paths: Path) -> bool:
        """Read settings in order and short-circuit on the first legacy input."""
        for path in paths:
            _, _, patch = self.read_patch(path)
            for key in self.source_keys & patch.keys():
                value = patch[key]
                if not isinstance(value, list) or value:
                    return True
        return False

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


@dataclass(frozen=True)
class _LegacyAdoptionSelection:
    """Read-only adoption provenance over the original handoff and Desired owners.

    Product choices and historical IDs are supplied as data. Later operator
    mutations do not erase initial adoption; partial evidence cannot prove it.
    """

    key: PluginInstallationKeyV1
    source_identity: str
    install_operation_id: str
    enable_operation_id: str | None
    builtin_ids: tuple[str, ...]
    disabled_builtin_ids: frozenset[str]
    removed_builtin_operations: Mapping[str, str]

    def settled(
        self,
        desired: PluginDesiredStateLedger,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
        handoffs: PackageRetentionHandoffJournal,
        bindings: Sequence[PackageProductLocalWheelBindingV1],
        *,
        store_id: str,
        bootstrap_policy: _PluginBootstrapPolicy,
        handoff_error: str,
    ) -> bool:
        before, history = desired.capture_read_only()

        def transitions_for(
            selected_plugin: str,
        ) -> tuple[PluginDesiredStateJournalTransition, ...]:
            key = PluginInstallationKeyV1(
                product_id=self.key.product_id,
                installation_scope="workspace",
                scope_id=self.key.scope_id,
                plugin_id=selected_plugin,
            )
            return tuple(
                item for item in history if item.mutation.installation_key == key
            )

        old_install_id = self.install_operation_id
        command_id = self._settled_command(
            handoffs,
            error_message=handoff_error,
            operation_id=old_install_id,
            plugin_id=self.key.plugin_id,
        )
        old_events = transitions_for(self.key.plugin_id)
        if not self._initial_install_matches(
            old_events, command_id, self.source_identity
        ):
            return False
        if self.enable_operation_id is not None:
            enable_id = self.enable_operation_id
            if (
                len(old_events) < 2
                or not isinstance(old_events[1], PluginDesiredStateTransitionV1)
                or old_events[1].mutation.operation_id != enable_id
                or old_events[1].committed_state.selection.desired_state
                != "installed_enabled"
                or old_events[1].committed_state.selection.package_revision
                != old_events[0].committed_state.selection.package_revision
            ):
                return False

        for builtin_id in self.builtin_ids:
            events = transitions_for(builtin_id)
            if builtin_id in self.removed_builtin_operations:
                if (
                    not events
                    or events[0].mutation.operation_id
                    != self.removed_builtin_operations[builtin_id]
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
            operation_id = bootstrap_policy.operation_id(store_id, builtin_id)
            command_id = self._settled_command(
                handoffs,
                error_message=handoff_error,
                operation_id=operation_id,
                plugin_id=builtin_id,
            )
            builtin_source = tuple(
                item.source_identity
                for item in bindings
                if item.plugin_id == builtin_id
            )
            if len(builtin_source) != 1 or not self._initial_install_matches(
                events, command_id, builtin_source[0]
            ):
                return False
            if builtin_id in self.disabled_builtin_ids:
                if any(
                    event.mutation.operation_id.startswith(
                        bootstrap_policy.enable_id_prefix
                    )
                    for event in events[1:]
                ):
                    return False
            elif (
                len(events) < 2
                or not isinstance(events[1], PluginDesiredStateTransitionV1)
                or events[1].committed_state.selection.desired_state
                != "installed_enabled"
                or events[1].committed_state.selection.package_revision
                != events[0].committed_state.selection.package_revision
            ):
                return False
        after, later_history = desired.capture_read_only()
        epoch_runtime.assert_current()
        return before == after and history == later_history

    @staticmethod
    def _initial_install_matches(
        events: tuple[PluginDesiredStateJournalTransition, ...],
        command_id: str | None,
        source_identity: str,
    ) -> bool:
        return (
            command_id is not None
            and bool(events)
            and isinstance(events[0], PluginDesiredStateTransitionV1)
            and events[0].mutation.operation_id == command_id
            and events[0].committed_state.selection.desired_state
            == "installed_disabled"
            and events[0].committed_state.selection.package_revision is not None
            and events[
                0
            ].committed_state.selection.package_revision.package_source_identity
            == source_identity
        )

    def _settled_command(
        self,
        handoffs: PackageRetentionHandoffJournal,
        *,
        operation_id: str,
        plugin_id: str,
        error_message: str,
    ) -> str | None:
        receipt = handoffs.read_operation(operation_id)
        if receipt is None or receipt.state != "settled":
            return None
        request = receipt.request.desired_request
        if (
            receipt.desired_receipt is None
            or receipt.desired_receipt.request != request
            or request.operation_id != operation_id
            or request.plugin_id != plugin_id
            or request.product_id != self.key.product_id
            or request.scope_id != self.key.scope_id
        ):
            raise ValueError(error_message)
        return request.command_id
