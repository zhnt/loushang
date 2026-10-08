"""Product-bound Windows confirmation candidate for exact Arch data deletion.

Each acceptance is an immutable native private receipt. This owner issues no
deletion receipt and grants no filesystem deletion authority by itself.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationRecordV1,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_private_data_deletion_preview import CodingArchPrivateDataTargetSnapshotV1
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _capture_windows_target_snapshot,
)

_OWNER_ID = "coding.arch.private-data:windows-v1"
_MAX_CONFIRMATION_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataConfirmationOwner:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        if (
            self.product.state_root
            != resolve_coding_package_epoch_layout(self.layout).control_root
            / "product-state"
        ):
            raise ValueError("Windows Coding Arch confirmation Product state changed")

    def plan_for(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        """Observe the exact current target without creating acceptance."""

        self._require_key(key)
        preview = CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        target = preview.snapshot_for(key)
        return PluginPrivateDataDeletionPlanV1(key, _OWNER_ID, target.target_id)

    def record_confirmation(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> PluginPrivateDataConfirmationRecordV1:
        """Accept one unchanged preview under the offline Product fence."""

        self._require_plan(plan, confirmation)
        preview = CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        with preview._offline():
            state = self.product.desired_state.snapshot().installation(
                plan.installation_key
            )
            if state.latest_instance_revision_ref is None:
                raise ValueError(
                    "Windows Coding Arch Installation has no Product history"
                )
            # Avoid nesting the native quiescence gate through plan_for().
            root = coding_arch_installation_private_data_root(
                self.layout, plan.installation_key
            )
            expected_root = inspect_coding_windows_arch_installation_root(
                self.layout,
                plan.installation_key,
                state_root=self.product.state_root,
            )
            current = (
                CodingArchPrivateDataTargetSnapshotV1(
                    root_path_digest=sha256(os.fsencode(str(root))).hexdigest(),
                    root_identity=None,
                    members=(),
                )
                if expected_root is None
                else _capture_windows_target_snapshot(root, expected_root=expected_root)
            )
            if (
                current.target_id != plan.target_id
                or inspect_coding_windows_arch_installation_root(
                    self.layout,
                    plan.installation_key,
                    state_root=self.product.state_root,
                )
                != expected_root
            ):
                raise ValueError("Windows Coding Arch confirmation plan is stale")
            record = PluginPrivateDataConfirmationRecordV1(
                record_revision=1,
                plan=plan,
                confirmation=confirmation,
                actor_id=actor_id,
                policy_revision=policy_revision,
            )
            payload = canonical_json_bytes(record.to_dict()) + b"\n"
            if len(payload) > _MAX_CONFIRMATION_BYTES:
                raise ValueError("Windows Coding Arch confirmation is too large")
            path = self._record_path(confirmation)
            with self.product.epoch_runtime.borrow_product_state_root_descriptor():
                existing = read_windows_private_receipt(
                    path,
                    maximum_bytes=_MAX_CONFIRMATION_BYTES,
                    allow_unpublished_stage=True,
                )
                if existing is not None:
                    if self._decode(existing) != record:
                        raise ValueError(
                            "Windows Coding Arch confirmation ID was reused"
                        )
                    return record
                write_windows_private_receipt(path, payload)
                if (
                    read_windows_private_receipt(
                        path, maximum_bytes=_MAX_CONFIRMATION_BYTES
                    )
                    != payload
                ):
                    raise ValueError("Windows Coding Arch confirmation changed")
            return record

    def is_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> bool:
        """Read one exact private receipt through the current Product root."""

        self._require_plan(plan, confirmation)
        self.product.assert_private_data_read_authority_current()
        with self.product.epoch_runtime.borrow_product_state_root_descriptor():
            raw = read_windows_private_receipt(
                self._record_path(confirmation),
                maximum_bytes=_MAX_CONFIRMATION_BYTES,
            )
            record = None if raw is None else self._decode(raw)
            result = record is not None and (
                record.plan == plan and record.confirmation == confirmation
            )
        self.product.assert_private_data_read_authority_current()
        return result

    def _record_path(
        self, confirmation: PluginPrivateDataDeletionConfirmationV1
    ) -> Path:
        digest = sha256(
            b"loushang.coding-arch-windows-private-data-confirmation/v1\0"
            + confirmation.confirmation_id.encode("utf-8")
        ).hexdigest()
        return self.product.state_root / f"private-data-confirmation-{digest}.json"

    def _require_key(self, key: PluginInstallationKeyV1) -> None:
        if (
            not isinstance(key, PluginInstallationKeyV1)
            or key.product_id != "coding"
            or key.installation_scope != "workspace"
            or key.scope_id != self.layout.scope_id
            or key.plugin_id != "coding.arch.default"
        ):
            raise ValueError("Windows Coding Arch confirmation Installation is foreign")

    def _require_plan(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> None:
        if (
            not isinstance(plan, PluginPrivateDataDeletionPlanV1)
            or not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1)
            or plan.owner_id != _OWNER_ID
            or len(plan.target_id) > 80
            or len(confirmation.confirmation_id.encode("utf-8")) > 256
            or confirmation.plan_fingerprint != plan.fingerprint
        ):
            raise ValueError("Windows Coding Arch confirmation plan is invalid")
        self._require_key(plan.installation_key)

    @staticmethod
    def _decode(raw: bytes) -> PluginPrivateDataConfirmationRecordV1:
        try:
            document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
            record = PluginPrivateDataConfirmationRecordV1.from_dict(document)
        except (TypeError, UnicodeError, ValueError) as exc:
            raise ValueError("Windows Coding Arch confirmation is invalid") from exc
        if (
            record.record_revision != 1
            or raw != canonical_json_bytes(record.to_dict()) + b"\n"
        ):
            raise ValueError("Windows Coding Arch confirmation is noncanonical")
        return record


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Windows Coding Arch confirmation has duplicate fields")
        result[key] = value
    return result


__all__ = ["CodingWindowsArchPrivateDataConfirmationOwner"]
