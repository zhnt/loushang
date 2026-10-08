"""Portable parsing checks for Windows private-data confirmation authority."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from loushang.coding.package_legacy_windows_receipt import (
    CodingWindowsPrivateReceiptError,
    _require_simple_attributes,
)
from loushang.coding.package_private_data_windows_confirmation import (
    CodingWindowsArchPrivateDataConfirmationOwner,
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


def test_windows_confirmation_requires_one_canonical_immutable_record() -> None:
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "a" * 64,
        plugin_id="coding.arch.default",
    )
    plan = PluginPrivateDataDeletionPlanV1(
        installation_key=key,
        owner_id="coding.arch.private-data:windows-v1",
        target_id="absent:" + "b" * 64,
    )
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint,
        confirmation_id="arch-private-data:portable",
    )
    record = PluginPrivateDataConfirmationRecordV1(
        record_revision=1,
        plan=plan,
        confirmation=confirmation,
        actor_id="local-operator:portable-test",
        policy_revision="windows-private-data-test:1",
    )
    decode = CodingWindowsArchPrivateDataConfirmationOwner._decode
    assert decode(canonical_json_bytes(record.to_dict()) + b"\n") == record
    with pytest.raises(ValueError, match="noncanonical"):
        decode(json.dumps(record.to_dict(), indent=2).encode("utf-8"))
    with pytest.raises(ValueError, match="noncanonical"):
        decode(
            canonical_json_bytes(replace(record, record_revision=2).to_dict()) + b"\n"
        )
    with pytest.raises(ValueError, match="invalid"):
        decode(b'{"recordRevision":1,"recordRevision":1}')


def test_windows_confirmation_receipt_rejects_hidden_or_foreign_attributes() -> None:
    _require_simple_attributes(
        SimpleNamespace(st_file_attributes=0x20), directory=False
    )
    _require_simple_attributes(SimpleNamespace(st_file_attributes=0x10), directory=True)
    for value, directory in ((0x22, False), (0x12, True), (0x10, False), (0, False)):
        with pytest.raises(CodingWindowsPrivateReceiptError, match="attributes"):
            _require_simple_attributes(
                SimpleNamespace(st_file_attributes=value), directory=directory
            )
