"""Fixed legacy-local acceptance and settings-consumption transactions.

Package Product owns receipt/Desired locking, replay, Settings transaction and
rooted IO. Products retain nominal codecs and authenticated legacy admission.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Generic, Literal, Protocol, TypeVar

from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
    JournalLoadPolicy,
    JournalRecordCodec,
    decode_jsonl,
    encode_jsonl_record,
)
from loushang.harness.journal._rooted_io import (
    RootedFile,
    RootedFileIO,
    _private_parent_matches,
)
from loushang.harness.plugin_management.ledger import (
    decode_plugin_desired_state_snapshot,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

if TYPE_CHECKING:
    from loushang.harness.config.agent import SettingsManager


RecordT = TypeVar("RecordT")


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


_SOURCE_KEYS = frozenset(
    {"package_roots", "package_sources", "packages", "plugin_sources", "resource_roots"}
)


@dataclass(frozen=True)
class _SourceConsumptionProtocol:
    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    acceptance: _AcceptedSource
    settings: SettingsManager
    frozen: _FrozenSources
    reopen_acceptance: Callable[[str], _AcceptedSource | None]
    verify_loaded_settings: Callable[
        [Path, Mapping[str, object]], tuple[bool, str | None]
    ]
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
        settings: SettingsManager,
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
            if any(patch.get(key) for key in _SOURCE_KEYS - {"plugin_sources"}):
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
                _present, observed = self.verify_loaded_settings(path, patch)
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
        settings: SettingsManager, error_type: type[Exception]
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
