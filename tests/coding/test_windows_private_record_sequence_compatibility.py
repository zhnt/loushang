"""Original four native filename scans, including first-error and active-view order."""

from __future__ import annotations

import importlib
import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

KINDS = ("deletion", "restore", "confirmation", "expiry")
CASES = (
    "empty",
    "unrelated",
    "stage",
    "unexpected",
    "zero",
    "gap",
    "stage_gap",
    "two_stages",
    "published_missing",
    "with_next_stage",
    "too_many",
    "overflow_then_unexpected",
    "zero_then_unexpected",
    "closed",
)


def run_probe(kind: str, case: str) -> dict[str, object]:
    stem = (
        "backup_expiry"
        if kind == "expiry"
        else "restore"
        if kind == "confirmation"
        else kind
    )
    module = importlib.import_module(
        "loushang.coding.package_private_data_windows_" + stem + "_journal"
    )
    root = Path("/unused-state")
    product = SimpleNamespace(state_root=root)
    if kind == "deletion":
        transaction = module.CodingWindowsArchPrivateDataDeletionTransaction(root, 7)
        owner = transaction
    else:
        restore_module = importlib.import_module(
            "loushang.coding.package_private_data_windows_restore_journal"
        )
        owner = restore_module.CodingWindowsArchPrivateDataRestoreTransaction(
            SimpleNamespace(), product, 7
        )
        transaction = (
            module.CodingWindowsArchBackupExpiryTransaction(
                SimpleNamespace(), product, owner
            )
            if kind == "expiry"
            else owner
        )
    prefix = module._CONFIRM_PREFIX if kind == "confirmation" else module._EVENT_PREFIX

    def name(number):
        return f"{prefix}{number:08d}.json"

    scenarios = {
        "empty": [],
        "unrelated": ["other.json"],
        "stage": [name(1) + ".stage"],
        "unexpected": [prefix + "foreign"],
        "zero": [name(0)],
        "gap": [name(2)],
        "stage_gap": [name(2) + ".stage"],
        "two_stages": [name(1) + ".stage", name(2) + ".stage"],
        "published_missing": [name(1)],
        "with_next_stage": [name(1), name(2) + ".stage"],
        "too_many": [name(1), name(2), name(3)],
        "overflow_then_unexpected": [name(1), name(2), name(3), prefix + "foreign"],
        "zero_then_unexpected": [name(0), prefix + "foreign"],
        "closed": [prefix + "foreign"],
    }
    trace: list[str] = []

    def names(_descriptor):
        trace.append("list")
        return scenarios[case]

    def read(path, *, maximum_bytes):
        trace.append(f"read:{path.name}:{maximum_bytes}")
        return None

    if case == "closed":
        owner._close()
    with ExitStack() as stack:
        profile = getattr(type(transaction), "_receipt_io", None)
        if profile is None:
            stack.enter_context(patch.object(module, "windows_listdir_at", names))
            stack.enter_context(
                patch.object(module, "read_windows_private_receipt", read)
            )
            stack.enter_context(patch.object(module, "_MAX_EVENTS", 2))
        else:
            native = importlib.import_module(
                "loushang.harness.plugin_management._private_data_deletion_windows"
                if kind == "deletion"
                else "loushang.harness.plugin_management._private_data_expiry_windows"
                if kind == "expiry"
                else "loushang.harness.plugin_management._private_data_restore_windows"
            )

            def read_native(_io, path, *, maximum_bytes, allow_unpublished_stage=False):
                assert allow_unpublished_stage is False
                return read(path, maximum_bytes=maximum_bytes)

            stack.enter_context(patch.object(native, "windows_listdir_at", names))
            stack.enter_context(
                patch.object(type(profile), "read_private_receipt", read_native)
            )
            stack.enter_context(patch.object(type(transaction), "_max_events", 2))
        try:
            rows, staged = (
                transaction._scan_confirmations()
                if kind == "confirmation"
                else transaction._scan()
            )
            result = {"records": len(rows), "staged": staged}
        except Exception as error:
            result = {
                "error_type": type(error).__module__ + "." + type(error).__qualname__,
                "message": str(error),
            }
    return {**result, "trace": trace}


@pytest.mark.parametrize("kind", KINDS)
def test_original_windows_record_sequence_contract(kind: str) -> None:
    reference = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "private_windows_record_sequence_v1.json"
        ).read_text()
    )
    for case in CASES:
        assert run_probe(kind, case) == reference["scans"][kind][case], case
