"""Frozen complete expiry Journal observations; inert native IO/preview ports.

Records, encoding, stage/replay decisions and append verification are real.
This does not establish native Windows or Product admission acceptance.
"""

from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

CASES = (
    "complete_replays",
    "other_actor",
    "confirmed_stage",
    "completed_stage",
    "begin_stage",
    "renamed_stage",
    "confirm_write_before",
    "confirm_write_after",
    "begin_bool_version",
    "advance_float_version",
    "closed_before_bad_names",
    "invalid_before_preview",
    "preview_before_history",
)
FIXTURES = Path(__file__).with_name("fixtures")


def observe(case, monkeypatch):
    journal = importlib.import_module(
        "loushang.coding.package_private_data_windows_backup_expiry_journal"
    )
    from loushang.harness.resources.packages.plugin_lifecycle.records import (
        canonical_json_bytes,
    )

    cls = journal.CodingWindowsArchBackupExpiryTransaction
    event_type = journal.CodingWindowsArchBackupExpiryEventV1
    document = json.loads((FIXTURES / "windows_record_files_v1.json").read_text())
    started = event_type.from_dict(document["kinds"]["expiry"]["documents"]["second"])
    plan, confirmation, archive = started.plan, started.confirmation, started.archive
    confirmed = event_type(1, "confirmed", plan, confirmation)
    renamed = replace(started, revision=3, phase="renamed")
    completed = replace(
        renamed,
        revision=4,
        phase="completed",
        receipt=journal.CodingArchPrivateDataBackupExpiryReceiptV1.create(
            plan, confirmation
        ),
    )
    trace, saved = [], {}

    def wire(item):
        return canonical_json_bytes(item.to_dict()) + b"\n"

    def seed(items):
        saved.update(
            {f"arch-backup-expiry-{e.revision:08d}.json": wire(e) for e in items}
        )

    if case in {"other_actor", "confirmed_stage", "begin_bool_version"}:
        seed(
            (
                replace(confirmed, record_version=True)
                if case == "begin_bool_version"
                else confirmed,
            )
        )
    elif case == "begin_stage":
        seed((confirmed, started))
    elif case in {"renamed_stage", "advance_float_version"}:
        seed((confirmed, started, renamed))
    elif case == "completed_stage":
        seed((confirmed, started, renamed, completed))
    if case.endswith("_stage"):
        saved[f"arch-backup-expiry-{len(saved) + 1:08d}.json.stage"] = b"pending"
    if case in {"closed_before_bad_names", "preview_before_history"}:
        saved["arch-backup-expiry-invalid"] = b"bad"

    def active():
        trace.append("active")
        if case == "closed_before_bad_names":
            raise RuntimeError("closed original scope")

    def preview(*args):
        trace.append("preview")
        return (
            replace(
                plan, desired_inventory_revision=plan.desired_inventory_revision + 1
            )
            if case == "preview_before_history"
            else plan
        )

    def names(fd):
        trace.append(["list", fd])
        return tuple(saved)

    def read(path, *, maximum_bytes):
        trace.append(["read", path.as_posix(), maximum_bytes])
        return saved.get(path.name)

    def write(path, payload, *, maximum_bytes):
        trace.append(["write", path.as_posix(), maximum_bytes, payload.hex()])
        if case == "confirm_write_before":
            raise OSError("publication interrupted before")
        saved[path.name] = payload
        if case == "confirm_write_after":
            raise OSError("publication interrupted after")

    monkeypatch.setattr(
        journal.CodingWindowsArchPrivateDataBackupExpiryPreview,
        "__post_init__",
        lambda self: None,
    )
    monkeypatch.setattr(
        journal.CodingWindowsArchPrivateDataBackupExpiryPreview,
        "_preview_locked",
        preview,
    )
    profile = getattr(cls, "_receipt_io", None)
    if profile is None:
        monkeypatch.setattr(journal, "windows_listdir_at", names)
        monkeypatch.setattr(journal, "read_windows_private_receipt", read)
        monkeypatch.setattr(journal, "write_windows_private_receipt", write)
    else:
        core = importlib.import_module(
            "loushang.harness.plugin_management._private_data_expiry_windows"
        )
        monkeypatch.setattr(core, "windows_listdir_at", names)
        monkeypatch.setattr(
            type(profile),
            "read_private_receipt",
            lambda self, path, **kw: read(path, **kw),
        )
        monkeypatch.setattr(
            type(profile),
            "write_private_receipt",
            lambda self, path, payload, **kw: write(path, payload, **kw),
        )
    txn = cls(
        SimpleNamespace(),
        SimpleNamespace(state_root=Path("/unused-product")),
        SimpleNamespace(
            state_fd=7, _state_root=Path("/unused-restore"), _require_active=active
        ),
    )

    def confirm(actor=None):
        return txn.confirm(
            plan,
            actor_id=actor or confirmation.actor_id,
            policy_revision=confirmation.policy_revision,
        )

    result = []
    try:
        if case == "complete_replays":
            result.extend((confirm().to_dict(), confirm().to_dict()))
            current = txn.begin(plan, confirmation, archive)
            result.extend(
                (current.to_dict(), txn.begin(plan, confirmation, archive).to_dict())
            )
            for phase in ("renamed", "completed"):
                current = txn.advance(current, phase)
                result.extend(
                    (current.to_dict(), txn.advance(current, phase).to_dict())
                )
            result.append(confirm().to_dict())
        elif case in {
            "other_actor",
            "confirmed_stage",
            "completed_stage",
            "confirm_write_before",
            "confirm_write_after",
            "preview_before_history",
        }:
            result.append(
                confirm("operator:other" if case == "other_actor" else None).to_dict()
            )
        elif case in {"begin_stage", "begin_bool_version"}:
            result.append(txn.begin(plan, confirmation, archive).to_dict())
        elif case in {"renamed_stage", "advance_float_version"}:
            prior = event_type.from_dict(
                json.loads(saved["arch-backup-expiry-00000003.json"])
            )
            if case == "advance_float_version":
                prior = replace(prior, record_version=1.0)
            result.append(
                txn.advance(
                    prior, "renamed" if case == "renamed_stage" else "completed"
                ).to_dict()
            )
        elif case == "closed_before_bad_names":
            txn.events()
        else:
            txn.confirm(object(), actor_id="operator:test", policy_revision="test:1")
    except Exception as error:
        result.append({"type": type(error).__name__, "message": str(error)})
    return {
        "result": result,
        "trace": trace,
        "saved": {k: v.hex() for k, v in sorted(saved.items())},
    }


def api_shape():
    from loushang.coding.package_private_data_windows_backup_expiry_journal import (
        CodingWindowsArchBackupExpiryTransaction as T,
    )

    return {
        "fields": [f.name for f in fields(T)],
        "slots": list(T.__slots__),
        "signature": str(inspect.signature(T)),
    }


@pytest.mark.parametrize("case", CASES)
def test_original_expiry_journal(case, monkeypatch):
    frozen = json.loads((FIXTURES / "windows_expiry_journal_v1.json").read_text())
    assert observe(case, monkeypatch) == frozen["cases"][case]


def test_original_expiry_transaction_shape():
    frozen = json.loads((FIXTURES / "windows_expiry_journal_v1.json").read_text())
    assert api_shape() == frozen["api"]
