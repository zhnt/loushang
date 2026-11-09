"""Frozen per-record and publication results from all four existing dialects."""

from __future__ import annotations

import importlib
import inspect
import json
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

KINDS = ("deletion", "restore", "expiry", "confirmation")
READ_CASES = (
    "valid",
    "noncanonical",
    "wrong_revision",
    "wrong_revision_noncanonical",
    "invalid_json",
    "invalid_utf8",
    "wrong_shape",
    "duplicate",
    "duplicate_invalid_schema",
    "duplicate_before_invalid",
    "noncanonical_before_invalid",
    "wrong_revision_before_invalid",
    "trailing_bytes",
    "duplicate_identity",
)
APPEND_CASES = (
    "append",
    "staged_retry",
    "wrong_stage",
    "full",
    "oversized",
    "closed",
    "write_failure",
    "no_publication",
    "corrupt_publication",
    "changed_publication",
    "next_stage_debt",
    "wrong_revision",
)


def _module(kind):
    stem = (
        "backup_expiry"
        if kind == "expiry"
        else "restore"
        if kind == "confirmation"
        else kind
    )
    return importlib.import_module(
        "loushang.coding.package_private_data_windows_" + stem + "_journal"
    )


def _record_type(kind, module):
    return (
        module.CodingArchPrivateDataDeletionEventV1
        if kind == "deletion"
        else module.CodingWindowsArchBackupExpiryEventV1
        if kind == "expiry"
        else module.CodingArchPrivateDataRestoreConfirmationV1
        if kind == "confirmation"
        else module.CodingArchPrivateDataRestoreEventV1
    )


def run_probe(kind: str, case: str, documents: dict) -> dict:
    append = case.startswith("append/")
    if append:
        case = case.split("/", 1)[1]
    module = _module(kind)
    restore_module = _module("restore")
    record_type = _record_type(kind, module)
    root = Path("/unused-record-state")
    product = SimpleNamespace(state_root=root)
    owner = (
        module.CodingWindowsArchPrivateDataDeletionTransaction(root, 7)
        if kind == "deletion"
        else restore_module.CodingWindowsArchPrivateDataRestoreTransaction(
            SimpleNamespace(), product, 7
        )
    )
    transaction = (
        module.CodingWindowsArchBackupExpiryTransaction(
            SimpleNamespace(), product, owner
        )
        if kind == "expiry"
        else owner
    )
    prefix = module._CONFIRM_PREFIX if kind == "confirmation" else module._EVENT_PREFIX

    def name(revision):
        return f"{prefix}{revision:08d}.json"

    def canonical(document):
        from loushang.harness.resources.packages.plugin_lifecycle.records import (
            canonical_json_bytes,
        )

        return canonical_json_bytes(document) + b"\n"

    first = canonical(documents["first"])
    second = canonical(documents["second"])
    wrong_revision = canonical(documents["wrong_revision"])
    noncanonical = json.dumps(documents["first"], indent=2).encode()
    duplicate = b'{"revision":1,' + first[1:]
    saved = {}
    trace = []
    raw_cases = {
        "valid": (first,),
        "noncanonical": (noncanonical,),
        "wrong_revision": (wrong_revision,),
        "wrong_revision_noncanonical": (
            json.dumps(documents["wrong_revision"], indent=2).encode(),
        ),
        "invalid_json": (b"{invalid-json}\n",),
        "invalid_utf8": (b"\xff",),
        "wrong_shape": (b"[]\n",),
        "duplicate": (duplicate,),
        "duplicate_invalid_schema": (b'{"revision":1,"revision":0}\n',),
        "duplicate_before_invalid": (duplicate, b"{invalid}\n"),
        "noncanonical_before_invalid": (noncanonical, b"{invalid}\n"),
        "wrong_revision_before_invalid": (wrong_revision, b"{invalid}\n"),
        "trailing_bytes": (first + b" ",),
        "duplicate_identity": (first, second),
    }
    if not append:
        saved.update({name(index): raw for index, raw in enumerate(raw_cases[case], 1)})
    elif case == "staged_retry":
        saved[name(1) + ".stage"] = first
    elif case == "wrong_stage" and kind == "confirmation":
        saved[name(2) + ".stage"] = b"pending"
    event = record_type.from_dict(
        documents["wrong_revision"]
        if case == "wrong_revision" and append
        else documents["first"]
    )

    def list_names(_fd):
        trace.append("list")
        return tuple(saved)

    def read(path, *, maximum_bytes):
        trace.append(f"read:{path.name}:{maximum_bytes}")
        return saved.get(path.name)

    def write(path, payload, **kwargs):
        trace.append(
            {
                "write": path.name,
                "maximum_bytes": kwargs.get("maximum_bytes", "default"),
                "size": len(payload),
                "sha256": sha256(payload).hexdigest(),
            }
        )
        if case == "write_failure":
            raise OSError("probe publication interrupted")
        if case == "no_publication":
            return
        saved.pop(path.name + ".stage", None)
        saved[path.name] = (
            b"{invalid}\n"
            if case == "corrupt_publication"
            else canonical(documents["alternative"])
            if case == "changed_publication"
            else payload
        )
        if case == "next_stage_debt":
            saved[name(2) + ".stage"] = b"pending"

    if case == "closed":
        owner._close()
    with ExitStack() as stack:
        native_io = getattr(type(transaction), "_receipt_io", None)
        if native_io is None:
            stack.enter_context(patch.object(module, "windows_listdir_at", list_names))
            stack.enter_context(
                patch.object(module, "read_windows_private_receipt", read)
            )
            stack.enter_context(
                patch.object(module, "write_windows_private_receipt", write)
            )
        else:
            native = importlib.import_module(
                "loushang.harness.plugin_management._private_data_deletion_windows"
                if kind == "deletion"
                else "loushang.harness.plugin_management._private_data_expiry_windows"
                if kind == "expiry"
                else "loushang.harness.plugin_management._private_data_restore_windows"
            )
            from loushang.coding.package_legacy_windows_receipt import (
                write_windows_private_receipt,
            )

            original_write_cap = (
                inspect.signature(write_windows_private_receipt)
                .parameters["maximum_bytes"]
                .default
            )

            def read_native(_io, path, *, maximum_bytes, allow_unpublished_stage=False):
                assert allow_unpublished_stage is False
                return read(path, maximum_bytes=maximum_bytes)

            def write_native(_io, path, payload, *, maximum_bytes):
                # Old trace says default; assert the *same* original effective
                # bound before normalizing only this nonpersistent call spelling.
                if kind == "expiry":
                    # Expiry explicitly passed its own bound before migration.
                    assert maximum_bytes == type(transaction)._max_event_bytes
                    return write(path, payload, maximum_bytes=maximum_bytes)
                assert maximum_bytes == original_write_cap
                return write(path, payload)

            stack.enter_context(patch.object(native, "windows_listdir_at", list_names))
            stack.enter_context(
                patch.object(type(native_io), "read_private_receipt", read_native)
            )
            stack.enter_context(
                patch.object(type(native_io), "write_private_receipt", write_native)
            )
        if case == "full":
            stack.enter_context(
                patch.object(
                    type(transaction) if native_io is not None else module,
                    "_max_events" if native_io is not None else "_MAX_EVENTS",
                    0,
                )
            )
        if case == "oversized":
            stack.enter_context(
                patch.object(
                    type(transaction) if native_io is not None else module,
                    (
                        "_confirmation_max_bytes"
                        if kind == "confirmation"
                        else "_max_event_bytes"
                    )
                    if native_io is not None
                    else (
                        "_CONFIRM_MAX_BYTES"
                        if kind == "confirmation"
                        else "_MAX_EVENT_BYTES"
                    ),
                    1,
                )
            )
        if kind == "confirmation":
            from loushang.coding.package_private_data_deletion_preview import (
                CodingArchPrivateDataTargetSnapshotV1,
            )

            completion = restore_module.CodingArchPrivateDataRestoreEventV1.from_dict(
                documents["completion"]
            )
            source = CodingArchPrivateDataTargetSnapshotV1.from_dict(
                documents["source"]
            )
            stack.enter_context(
                patch.object(
                    type(owner),
                    "_completed_restore",
                    lambda _self, _plan: (completion, source),
                )
            )
        try:
            if append:
                value = (
                    transaction.confirm_restore(object())
                    if kind == "confirmation"
                    else transaction._append(
                        (),
                        2
                        if case == "wrong_stage"
                        else 1
                        if case == "staged_retry"
                        else None,
                        event,
                    )
                )
                result = {"returned": value.to_dict()}
            else:
                rows, staged = (
                    transaction._scan_confirmations()
                    if kind == "confirmation"
                    else transaction._scan()
                )
                result = {"records": [row.to_dict() for row in rows], "staged": staged}
        except Exception as error:
            cause = error.__cause__
            result = {
                "error_type": type(error).__module__ + "." + type(error).__qualname__,
                "message": str(error),
                "cause_type": None
                if cause is None
                else type(cause).__module__ + "." + type(cause).__qualname__,
                "cause_message": None if cause is None else str(cause),
            }
    return {
        **result,
        "trace": trace,
        "files": {name: raw.hex() for name, raw in saved.items()},
    }


@pytest.mark.parametrize("kind", KINDS)
def test_original_per_record_and_append_contracts(kind: str) -> None:
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "windows_record_files_v1.json"
        ).read_text()
    )
    for case, expected in fixture["kinds"][kind]["cases"].items():
        assert run_probe(kind, case, fixture["kinds"][kind]["documents"]) == expected, (
            case
        )


def decode_authority_probe(owner_type, raw: bytes) -> dict:
    try:
        return {"record": owner_type._decode(raw).to_dict()}
    except Exception as error:
        cause = error.__cause__
        return {
            "error_type": type(error).__module__ + "." + type(error).__qualname__,
            "message": str(error),
            "cause_type": None
            if cause is None
            else type(cause).__module__ + "." + type(cause).__qualname__,
            "cause_message": None if cause is None else str(cause),
            "cause_code": getattr(cause, "code", None),
        }


def test_confirmation_authority_retains_decoder_and_error_cause_contract() -> None:
    from loushang.coding.package_private_data_windows_confirmation import (
        CodingWindowsArchPrivateDataConfirmationOwner,
    )

    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "windows_confirmation_decode_v1.json"
        ).read_text()
    )
    for case in fixture["cases"]:
        assert (
            decode_authority_probe(
                CodingWindowsArchPrivateDataConfirmationOwner,
                bytes.fromhex(case["raw"]),
            )
            == case["expected"]
        ), case["name"]
