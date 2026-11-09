"""Windows Installation root lineage over existing deletion and receipt owners.

The Product retains key/path/epoch admission and offline authority. This private
custody adds no deletion permission, root registry or restore transaction.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages._private_tree_windows import (
    private_windows_directory,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
    prepare_windows_product_private_directory_chain,
)

from .private_data_deletion import (
    PluginPrivateDataDeletionEventV1,
    PrivateDataDeletionTarget,
)
from .records import PluginInstallationKeyV1

_WINDOWS_GENERATION_SUFFIX = re.compile(r"([0-9]{8})\.(?:intent\.)?json(?:\.stage)?\Z")


class _Generation(Protocol):
    def __init__(
        self,
        number: int,
        predecessor_receipt_id: str | None,
        intent_path: Path,
        receipt_path: Path,
        intent: bytes | None,
        receipt: bytes | None,
        identity: tuple[int, int] | None,
    ) -> None: ...
    @property
    def number(self) -> int: ...
    @property
    def predecessor_receipt_id(self) -> str | None: ...
    @property
    def intent_path(self) -> Path: ...
    @property
    def receipt_path(self) -> Path: ...
    @property
    def intent(self) -> bytes | None: ...
    @property
    def receipt(self) -> bytes | None: ...
    @property
    def identity(self) -> tuple[int, int] | None: ...


class _RootDeletionTarget(PrivateDataDeletionTarget, Protocol):
    @property
    def root_path_digest(self) -> str: ...


class _DeletionRecords(Protocol):
    def __init__(self, state_root: Path, state_fd: int) -> None: ...
    def events(
        self,
    ) -> tuple[PluginPrivateDataDeletionEventV1[_RootDeletionTarget], ...]: ...
    def _close(self) -> None: ...


G = TypeVar("G", bound=_Generation)


@dataclass(frozen=True, slots=True)
class _WindowsInstallationRootLineage(Generic[G]):
    """Complete original lineage custody with pure Product data/type bindings."""

    label: str
    receipt_prefix: str
    maximum_receipt_bytes: int
    maximum_write_bytes: int
    receipt_io: Callable[[], WindowsPrivateReceiptIO]
    receipt_error_type: Callable[[], type[RuntimeError]]
    deletion_type: Callable[[], type[_DeletionRecords]]
    generation_type: Callable[[], type[G]]

    def bind(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        *,
        state_root: Path,
        package_root: Path,
    ) -> tuple[int, int]:
        """Bind the current Installation root generation to Product state."""
        package_root_identity = inspect_windows_product_private_directory_identity(
            package_root
        )
        generation = self.current_generation(
            key,
            installation_root,
            state_root,
            package_root_identity,
            recover_stage=True,
        )
        intent = self.generation_intent_payload(
            key,
            installation_root,
            package_root_identity,
            generation.number,
            generation.predecessor_receipt_id,
        )
        if generation.intent is None:
            try:
                installation_root.lstat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError(f"{self.label} private-data root is unclaimed")
            self._write_or_match_receipt(generation.intent_path, intent)
        if generation.receipt is None:
            prepare_windows_product_private_directory_chain(
                package_root, "installation-private-data", installation_root.name
            )
            if any(installation_root.iterdir()):
                raise ValueError(f"Unbound {self.label} private-data root is not empty")
        parent_identity = inspect_windows_product_private_directory_identity(
            installation_root.parent
        )
        identity = inspect_windows_product_private_directory_identity(installation_root)
        receipt = self.generation_receipt_payload(
            key,
            installation_root,
            parent_identity,
            identity,
            generation.number,
            generation.predecessor_receipt_id,
        )
        if generation.receipt is not None and generation.receipt != receipt:
            raise ValueError(f"{self.label} private-data Installation root changed")
        if generation.receipt is None:
            self._write_or_match_receipt(generation.receipt_path, receipt)
        return identity

    def inspect(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        *,
        state_root: Path,
        package_root: Path,
    ) -> tuple[int, int] | None:
        """Read one bound Windows Installation root without creating or repairing it."""
        package_root_identity = inspect_windows_product_private_directory_identity(
            package_root
        )
        generation = self.current_generation(
            key, installation_root, state_root, package_root_identity
        )
        if generation.intent is None and generation.receipt is None:
            try:
                installation_root.lstat()
            except FileNotFoundError:
                return None
            raise ValueError(f"{self.label} private-data root is unclaimed")
        if generation.receipt is None:
            raise ValueError(f"{self.label} private-data root receipt is incomplete")
        parent_identity = inspect_windows_product_private_directory_identity(
            installation_root.parent
        )
        try:
            identity = inspect_windows_product_private_directory_identity(
                installation_root
            )
        except FileNotFoundError as exc:
            raise ValueError(
                f"{self.label} private-data Installation root changed"
            ) from exc
        if generation.receipt != self.generation_receipt_payload(
            key,
            installation_root,
            parent_identity,
            identity,
            generation.number,
            generation.predecessor_receipt_id,
        ):
            raise ValueError(f"{self.label} private-data Installation root changed")
        return identity

    def prepare_restore_intent(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        *,
        state_root: Path,
        deletion_receipt_id: str,
        package_root: Path,
    ) -> int:
        """Claim only the successor root retired by an exact deletion receipt.

        The restore owner calls this while holding offline Product authority, after
        its start event and before publishing any restored directory bytes.
        """
        package_identity = inspect_windows_product_private_directory_identity(
            package_root
        )
        generation = self.current_generation(
            key, installation_root, state_root, package_identity, recover_stage=True
        )
        if (
            generation.number < 2
            or generation.predecessor_receipt_id != deletion_receipt_id
            or generation.receipt is not None
        ):
            raise ValueError(f"{self.label} restore root generation changed")
        try:
            installation_root.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError(f"{self.label} restore root is already present")
        payload = self.generation_intent_payload(
            key,
            installation_root,
            package_identity,
            generation.number,
            deletion_receipt_id,
        )
        self._write_or_match_receipt(generation.intent_path, payload)
        return generation.number

    def publish_restored_receipt(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        *,
        state_root: Path,
        generation_number: int,
        deletion_receipt_id: str,
        expected_identity: tuple[int, int],
        package_root: Path,
    ) -> tuple[int, int]:
        """Bind a separately verified restored tree to the retired generation."""
        package_identity = inspect_windows_product_private_directory_identity(
            package_root
        )
        generation = self.current_generation(
            key, installation_root, state_root, package_identity, recover_stage=True
        )
        if (
            generation.number != generation_number
            or generation.predecessor_receipt_id != deletion_receipt_id
            or generation.intent is None
            or (
                generation.identity is not None
                and generation.identity != expected_identity
            )
        ):
            raise ValueError(f"{self.label} restore root generation changed")
        parent_identity = inspect_windows_product_private_directory_identity(
            installation_root.parent
        )
        identity = inspect_windows_product_private_directory_identity(installation_root)
        if identity != expected_identity:
            raise ValueError(f"{self.label} restored root identity changed")
        payload = self.generation_receipt_payload(
            key,
            installation_root,
            parent_identity,
            identity,
            generation_number,
            deletion_receipt_id,
        )
        self._write_or_match_receipt(generation.receipt_path, payload)
        return identity

    def root_receipt_paths(
        self, installation_root: Path, state_root: Path
    ) -> tuple[Path, Path]:
        basename = self.receipt_prefix + installation_root.name
        return (
            state_root / (basename + ".intent.json"),
            state_root / (basename + ".json"),
        )

    def generation_paths(
        self, installation_root: Path, state_root: Path, number: int
    ) -> tuple[Path, Path]:
        if number == 1:
            return self.root_receipt_paths(installation_root, state_root)
        if number < 2 or number > 4097:
            raise ValueError(f"{self.label} private-data root generation is invalid")
        basename = (
            f"{self.receipt_prefix}{installation_root.name}.generation-{number:08d}"
        )
        return (
            state_root / (basename + ".intent.json"),
            state_root / (basename + ".json"),
        )

    def current_generation(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        state_root: Path,
        package_root_identity: tuple[int, int],
        *,
        recover_stage: bool = False,
        allow_pending: bool = False,
    ) -> G:
        events = self._deletion_events(state_root)
        if (
            not allow_pending
            and events
            and (events[-1].phase != "completed")
            and (events[-1].plan.installation_key == key)
        ):
            raise ValueError(f"{self.label} private-data deletion is unfinished")
        completed = tuple(
            (
                event
                for event in events
                if event.phase == "completed"
                and event.plan.installation_key == key
                and (event.target.root_identity is not None)
            )
        )
        predecessor: str | None = None
        path_digest = sha256(os.fsencode(str(installation_root))).hexdigest()
        for number, event in enumerate(completed, start=1):
            target_identity = event.target.root_identity
            generation = self._read_generation(
                key,
                installation_root,
                state_root,
                package_root_identity,
                number,
                predecessor,
                recover_stage=False,
            )
            if (
                generation.identity is None
                or target_identity is None
                or generation.identity != target_identity[:2]
                or (event.target.root_path_digest != path_digest)
                or (event.receipt is None)
                or (event.receipt.disposition != "deleted")
            ):
                raise ValueError(f"{self.label} private-data root retirement changed")
            predecessor = event.receipt.receipt_id
        self._require_no_future_generations(
            state_root, installation_root, len(completed) + 1
        )
        return self._read_generation(
            key,
            installation_root,
            state_root,
            package_root_identity,
            len(completed) + 1,
            predecessor,
            recover_stage=recover_stage,
        )

    def _deletion_events(
        self, state_root: Path
    ) -> tuple[PluginPrivateDataDeletionEventV1[_RootDeletionTarget], ...]:
        transaction_type = self.deletion_type()
        with private_windows_directory(
            state_root, revalidate_on_success=True
        ) as descriptor:
            transaction = transaction_type(state_root, descriptor)
            try:
                return transaction.events()
            finally:
                transaction._close()

    def _require_no_future_generations(
        self, state_root: Path, installation_root: Path, current_number: int
    ) -> None:
        with private_windows_directory(
            state_root, revalidate_on_success=True
        ) as descriptor:
            self.validate_generation_names(
                windows_listdir_at(descriptor), installation_root, current_number
            )

    def validate_generation_names(
        self, names: tuple[str, ...], installation_root: Path, current_number: int
    ) -> None:
        prefix = f"{self.receipt_prefix}{installation_root.name}.generation-"
        for name in names:
            if not name.startswith(prefix):
                continue
            match = _WINDOWS_GENERATION_SUFFIX.fullmatch(name[len(prefix) :])
            if match is None or not 2 <= int(match.group(1)) <= current_number:
                raise ValueError(
                    f"{self.label} private-data root generation is unexpected"
                )

    def _read_generation(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        state_root: Path,
        package_root_identity: tuple[int, int],
        number: int,
        predecessor_receipt_id: str | None,
        *,
        recover_stage: bool,
    ) -> G:
        intent_path, receipt_path = self.generation_paths(
            installation_root, state_root, number
        )
        intent = self.receipt_io().read_private_receipt(
            intent_path,
            maximum_bytes=self.maximum_receipt_bytes,
            allow_unpublished_stage=recover_stage,
        )
        receipt = self.receipt_io().read_private_receipt(
            receipt_path,
            maximum_bytes=self.maximum_receipt_bytes,
            allow_unpublished_stage=recover_stage,
        )
        if intent is not None and intent != self.generation_intent_payload(
            key,
            installation_root,
            package_root_identity,
            number,
            predecessor_receipt_id,
        ):
            raise ValueError(f"{self.label} private-data root intent changed")
        if intent is None and receipt is not None:
            raise ValueError(f"{self.label} private-data root receipt has no intent")
        identity: tuple[int, int] | None = None
        if receipt is not None:
            try:
                document = json.loads(receipt.decode("utf-8"))
                raw_identity = document["rootIdentity"]
            except (KeyError, TypeError, UnicodeError, ValueError) as exc:
                raise ValueError(
                    f"{self.label} private-data root receipt is invalid"
                ) from exc
            if (
                type(raw_identity) is not list
                or len(raw_identity) != 2
                or any((type(value) is not int or value < 0 for value in raw_identity))
            ):
                raise ValueError(f"{self.label} private-data root identity is invalid")
            identity = (raw_identity[0], raw_identity[1])
            parent_identity = inspect_windows_product_private_directory_identity(
                installation_root.parent
            )
            if receipt != self.generation_receipt_payload(
                key,
                installation_root,
                parent_identity,
                identity,
                number,
                predecessor_receipt_id,
            ):
                raise ValueError(f"{self.label} private-data root receipt changed")
        return self.generation_type()(
            number,
            predecessor_receipt_id,
            intent_path,
            receipt_path,
            intent,
            receipt,
            identity,
        )

    def generation_intent_payload(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        package_root_identity: tuple[int, int],
        number: int,
        predecessor_receipt_id: str | None,
    ) -> bytes:
        if number == 1:
            if predecessor_receipt_id is not None:
                raise ValueError(f"Initial {self.label} root has a predecessor")
            return self._root_intent_payload(
                key, installation_root, package_root_identity
            )
        if predecessor_receipt_id is None:
            raise ValueError(f"Successor {self.label} root has no deletion receipt")
        return canonical_json_bytes(
            {
                "bindingVersion": 3,
                "generation": number,
                "installationKey": key.to_dict(),
                "packageRootIdentity": list(package_root_identity),
                "predecessorReceiptId": predecessor_receipt_id,
                "rootName": installation_root.name,
            }
        )

    def generation_receipt_payload(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        parent_identity: tuple[int, int],
        identity: tuple[int, int],
        number: int,
        predecessor_receipt_id: str | None,
    ) -> bytes:
        if number == 1:
            if predecessor_receipt_id is not None:
                raise ValueError(f"Initial {self.label} root has a predecessor")
            return self._root_receipt_payload(
                key, installation_root, parent_identity, identity
            )
        if predecessor_receipt_id is None:
            raise ValueError(f"Successor {self.label} root has no deletion receipt")
        return canonical_json_bytes(
            {
                "bindingVersion": 3,
                "generation": number,
                "installationKey": key.to_dict(),
                "parentIdentity": list(parent_identity),
                "predecessorReceiptId": predecessor_receipt_id,
                "rootIdentity": list(identity),
                "rootName": installation_root.name,
            }
        )

    def _root_intent_payload(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        package_root_identity: tuple[int, int],
    ) -> bytes:
        return canonical_json_bytes(
            {
                "bindingVersion": 1,
                "installationKey": key.to_dict(),
                "packageRootIdentity": list(package_root_identity),
                "rootName": installation_root.name,
            }
        )

    def _root_receipt_payload(
        self,
        key: PluginInstallationKeyV1,
        installation_root: Path,
        parent_identity: tuple[int, int],
        identity: tuple[int, int],
    ) -> bytes:
        return canonical_json_bytes(
            {
                "bindingVersion": 2,
                "installationKey": key.to_dict(),
                "parentIdentity": list(parent_identity),
                "rootIdentity": list(identity),
                "rootName": installation_root.name,
            }
        )

    def _write_or_match_receipt(self, path: Path, payload: bytes) -> None:
        try:
            self.receipt_io().write_private_receipt(
                path, payload, maximum_bytes=self.maximum_write_bytes
            )
        except (self.receipt_error_type(), FileExistsError):
            if (
                self.receipt_io().read_private_receipt(
                    path, maximum_bytes=self.maximum_receipt_bytes
                )
                != payload
            ):
                raise
        if (
            self.receipt_io().read_private_receipt(
                path, maximum_bytes=self.maximum_receipt_bytes
            )
            != payload
        ):
            raise ValueError(f"{self.label} private-data root receipt changed")
