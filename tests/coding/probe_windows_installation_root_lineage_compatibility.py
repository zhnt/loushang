"""Original complete lineage observations over real files and controlled native ports."""

from __future__ import annotations

import builtins
import json
import os
import stat
from contextlib import contextmanager, suppress
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import package_installation_private_data as code
from loushang.coding import package_legacy_windows_receipt as receipts
from loushang.coding import package_private_data_windows_deletion_journal as deletion
from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1 as Event,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1 as Target,
)
from loushang.harness.plugin_management import _private_data_deletion_windows as history
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1 as Confirmation,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionPlanV1 as Plan,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionReceiptV1 as Receipt,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1 as Key
from loushang.harness.resources.packages import _file_consumption
from loushang.harness.resources.packages import _private_receipts_windows as native
from tests.coding.probe_native_release_readers_compatibility import error_graph

CASES = tuple(
    "current-" + c
    for c in (
        "empty",
        "bound",
        "retired",
        "successor",
        "pending",
        "foreign-pending",
        "allow-pending",
        "staged-event",
        "event-gap",
        "event-json",
        "event-receipt",
        "retirement-identity",
        "retirement-path",
        "future",
        "unexpected-name",
        "initial-intent",
        "receipt-without-intent",
        "intent-changed",
        "receipt-json",
        "identity-bool",
        "identity-negative",
        "identity-shape",
        "receipt-changed",
        "intent-stage",
        "receipt-stage",
        "recover-intent-stage",
        "bound-and-stage",
        "getter-error",
        "directory-enter",
        "constructor-error",
        "events-error",
        "close-error",
        "exit-error",
        "events-close-error",
        "close-exit-error",
    )
)
CASES += tuple(
    "bind-" + c
    for c in (
        "new",
        "repeat",
        "unclaimed",
        "intent-only",
        "dirty",
        "root-changed",
        "receipt-write-error",
        "receipt-after-write",
        "zero-write",
        "rename-error",
        "flush-error",
        "retry-write",
        "retry-rename",
        "retry-flush",
    )
)
CASES += tuple(
    "inspect-" + c
    for c in (
        "empty",
        "bound",
        "unclaimed",
        "incomplete",
        "root-missing",
        "root-changed",
        "state-changed",
        "staged",
    )
)
CASES += tuple(
    "restore-" + c
    for c in (
        "intent",
        "intent-repeat",
        "wrong-predecessor",
        "present",
        "not-retired",
        "already-bound",
        "state-changed",
        "publish",
        "publish-repeat",
        "publish-generation",
        "publish-predecessor",
        "publish-identity",
        "publish-stored-identity",
        "publish-no-intent",
        "publish-state-changed",
    )
)
CASES += tuple(
    "codec-" + c
    for c in (
        "initial",
        "true",
        "float",
        "false",
        "zero",
        "max",
        "future",
        "missing-predecessor",
        "initial-predecessor",
        "negative",
        "name-valid",
        "name-future",
        "name-malformed",
        "name-stage",
    )
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def observe(name, base, patch):
    kind, case = name.split("-", 1)
    trace = []
    descriptors = {}
    armed = False
    fault_used = False
    virtual_base = Path("/unused-a71-lineage")

    def physical(value):
        return base / Path(str(value)).relative_to(virtual_base)

    class VirtualPath(type(Path())):
        def lstat(self):
            trace.append(["lstat", str(self)])
            return physical(self).lstat()

        def iterdir(self):
            trace.append(["iterdir", str(self)])
            return (self / p.name for p in physical(self).iterdir())

    package = VirtualPath(str(virtual_base / "packages"))
    root = package / "installation-private-data" / ("b" * 64)
    state = VirtualPath(str(virtual_base / "product-state"))
    physical(package).mkdir(mode=0o700, parents=True)
    physical(state).mkdir(mode=0o700)
    key = Key("coding", "workspace", "workspace:" + "a" * 64, "coding.arch.default")
    other = Key("coding", "workspace", key.scope_id, "coding.other")
    layout = NS(package_root=package)
    package_id = (1, 2)
    parent_id = (3, 4)
    first_id = (5, 6)
    root_id = (7, 8)
    patch.setattr(code, "coding_arch_installation_private_data_root", lambda *_: root)
    patch.setattr(
        code,
        "resolve_coding_package_epoch_layout",
        lambda _: NS(control_root=VirtualPath(str(virtual_base))),
    )
    if hasattr(code, "_windows_root_lineage"):
        from loushang.harness.plugin_management import (
            _installation_root_windows as effects,
        )
    else:
        effects = code

    def seed(path, body):
        physical(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        physical(path).write_bytes(body)

    def lineage(number, identity, predecessor=None):
        intent, receipt = code._windows_arch_generation_paths(root, state, number)
        seed(
            intent,
            code._windows_arch_generation_intent_payload(
                key, root, package_id, number, predecessor
            ),
        )
        if identity is not None:
            seed(
                receipt,
                code._windows_arch_generation_receipt_payload(
                    key, root, parent_id, identity, number, predecessor
                ),
            )
        return intent, receipt

    def completed(selected_key, identity):
        target = Target(
            sha256(os.fsencode(str(root))).hexdigest(),
            (*identity, stat.S_IFDIR | 0o700, 0, 1),
            (),
        )
        plan = Plan(
            selected_key, "coding.arch.private-data:windows-v1", target.target_id
        )
        confirmation = Confirmation(plan.fingerprint, "lineage-delete:1")
        receipt = Receipt(
            selected_key,
            plan.owner_id,
            target.target_id,
            plan.fingerprint,
            confirmation.confirmation_id,
            deletion.windows_arch_deletion_receipt_id(plan, confirmation),
            "deleted",
        )
        start = Event(1, "started", plan, confirmation, target)
        return (
            start,
            replace(start, revision=2, phase="renamed"),
            replace(start, revision=3, phase="completed", receipt=receipt),
        )

    events = ()
    retired = (
        kind == "restore"
        or kind == "current"
        and case in ("retired", "successor", "retirement-identity", "retirement-path")
    )
    bound = (
        kind == "current"
        and case
        not in (
            "empty",
            "initial-intent",
            "receipt-without-intent",
            "intent-stage",
            "recover-intent-stage",
        )
        or kind == "bind"
        and case in ("repeat", "root-changed")
        or kind == "inspect"
        and case in ("bound", "root-missing", "root-changed", "staged")
    )
    if retired:
        first_intent, first_receipt = lineage(1, first_id)
        events = completed(key, first_id)
        predecessor = events[-1].receipt.receipt_id
        if case == "retirement-identity":
            seed(
                first_receipt,
                code._windows_arch_generation_receipt_payload(
                    key, root, parent_id, (99, 100), 1, None
                ),
            )
        if case == "retirement-path":
            bad_target = Target("f" * 64, (*first_id, stat.S_IFDIR | 0o700, 0, 1), ())
            bad_plan = Plan(
                key, "coding.arch.private-data:windows-v1", bad_target.target_id
            )
            bad_confirmation = Confirmation(bad_plan.fingerprint, "lineage-delete:1")
            bad_receipt = Receipt(
                key,
                bad_plan.owner_id,
                bad_target.target_id,
                bad_plan.fingerprint,
                bad_confirmation.confirmation_id,
                deletion.windows_arch_deletion_receipt_id(bad_plan, bad_confirmation),
                "deleted",
            )
            start = Event(1, "started", bad_plan, bad_confirmation, bad_target)
            events = (
                start,
                replace(start, revision=2, phase="renamed"),
                replace(start, revision=3, phase="completed", receipt=bad_receipt),
            )
        if (
            case == "successor"
            or kind == "restore"
            and (case == "already-bound" or case.startswith("publish"))
        ):
            second_intent, second_receipt = lineage(
                2,
                root_id
                if case in ("successor", "already-bound", "publish-stored-identity")
                else None,
                predecessor,
            )
    elif bound:
        first_intent, first_receipt = lineage(1, root_id)
    elif (
        kind == "bind"
        and case in ("intent-only", "dirty")
        or kind == "inspect"
        and case == "incomplete"
        or kind == "current"
        and case == "initial-intent"
    ):
        first_intent, first_receipt = lineage(1, None)
    if kind == "current" and case in ("pending", "allow-pending", "foreign-pending"):
        events = (completed(other if case == "foreign-pending" else key, root_id)[0],)
    if kind == "current" and case == "receipt-without-intent":
        first_intent, first_receipt = lineage(1, root_id)
        physical(first_intent).unlink()
    if kind == "restore" and case == "not-retired":
        events = ()
        predecessor = "unused"
        for p in physical(state).iterdir():
            p.unlink()
    if (
        kind in ("bind", "inspect")
        and case
        in (
            "repeat",
            "unclaimed",
            "dirty",
            "root-changed",
            "bound",
            "staged",
            "incomplete",
        )
        or kind == "restore"
        and (case in ("present", "already-bound") or case.startswith("publish"))
    ):
        physical(root).mkdir(mode=0o700, parents=True, exist_ok=True)
    if kind == "bind" and case == "dirty":
        seed(root / "data", b"existing")
    if kind == "current" and case == "intent-changed":
        seed(first_intent, b"changed intent")
    if kind == "current" and case in (
        "receipt-json",
        "identity-bool",
        "identity-negative",
        "identity-shape",
        "receipt-changed",
    ):
        document = json.loads(physical(first_receipt).read_bytes())
        if case == "identity-bool":
            document["rootIdentity"] = [True, 8]
        if case == "identity-negative":
            document["rootIdentity"] = [-1, 8]
        if case == "identity-shape":
            document["rootIdentity"] = [7]
        if case == "receipt-changed":
            document["extra"] = True
        seed(
            first_receipt,
            b"invalid json" if case == "receipt-json" else canonical(document),
        )
    if kind == "restore" and case == "publish-no-intent":
        physical(second_intent).unlink()
    for event in events:
        seed(
            state / f"arch-private-deletion-{event.revision:08d}.json",
            canonical(event.to_dict()) + b"\n",
        )
    if case == "event-gap":
        seed(state / "arch-private-deletion-00000002.json", b"{}\n")
    if case == "event-json":
        seed(state / "arch-private-deletion-00000001.json", b"bad json\n")
    if case == "event-receipt":
        bad = completed(key, root_id)
        for event in bad:
            seed(
                state / f"arch-private-deletion-{event.revision:08d}.json",
                canonical(event.to_dict()) + b"\n",
            )
        doc = json.loads(
            physical(state / "arch-private-deletion-00000003.json").read_bytes()
        )
        doc["receipt"]["receiptId"] = "wrong"
        seed(state / "arch-private-deletion-00000003.json", canonical(doc) + b"\n")
    if case == "staged-event":
        seed(state / "arch-private-deletion-00000001.json.stage", b"partial")
    if case in ("future", "unexpected-name"):
        seed(
            state
            / f"arch-private-root-{root.name}.generation-0000000{2 if case == 'future' else 1}.json",
            b"{}",
        )
    if (
        kind == "current"
        and case
        in ("intent-stage", "recover-intent-stage", "receipt-stage", "bound-and-stage")
        or kind == "inspect"
        and case == "staged"
    ):
        first_intent, first_receipt = lineage(
            1,
            root_id if case in ("receipt-stage", "bound-and-stage", "staged") else None,
        )
        selected = first_receipt if case == "receipt-stage" else first_intent
        seed(state / (selected.name + ".stage"), physical(selected).read_bytes())
        if case != "bound-and-stage":
            physical(selected).unlink()

    class OsView:
        name = "nt"

        def __getattr__(self, name):
            return getattr(os, name)

        def fstat(self, fd):
            value = os.fstat(fd)
            trace.append(["stat", descriptors[fd]])
            return NS(
                **{
                    **{k: getattr(value, k) for k in dir(value) if k.startswith("st_")},
                    "st_file_attributes": 0x10 if stat.S_ISDIR(value.st_mode) else 0x20,
                }
            )

        def read(self, fd, n):
            trace.append(["read", descriptors[fd], n])
            return os.read(fd, n)

        def write(self, fd, data):
            nonlocal fault_used
            trace.append(["write", descriptors[fd], len(data)])
            if armed and not fault_used and case in ("zero-write", "retry-write"):
                fault_used = True
                if case == "zero-write":
                    return 0
                raise OSError("injected write")
            return os.write(fd, data)

        def close(self, fd):
            trace.append(["fd-close", descriptors.pop(fd)])
            os.close(fd)

    class Acl:
        security_descriptor = 1

        def __enter__(self):
            trace.append(["acl-enter"])
            return self

        def __exit__(self, *_):
            trace.append(["acl-exit"])

        def validate(self, fd, **_):
            trace.append(["acl", descriptors[fd]])

    def open_directory(path, **_):
        trace.append(["directory-open", str(path)])
        fd = os.open(physical(path), os.O_RDONLY | os.O_DIRECTORY)
        descriptors[fd] = str(path)
        return fd

    def open_file(parent, name, *, create_new, write, **_):
        trace.append(["file-open", name, create_new, write])
        flags = os.O_WRONLY if write else os.O_RDONLY
        if create_new:
            flags |= os.O_CREAT | os.O_EXCL
        fd = os.open(name, flags, 0o600, dir_fd=parent)
        descriptors[fd] = name
        return fd

    def visible(parent, name):
        fd = os.open(name, os.O_RDONLY, dir_fd=parent)
        descriptors[fd] = name
        try:
            return OsView().fstat(fd)
        finally:
            descriptors.pop(fd)
            os.close(fd)

    def rename(parent, old, new):
        nonlocal fault_used
        trace.append(["rename", old, new])
        if armed and not fault_used and case in ("rename-error", "retry-rename"):
            fault_used = True
            raise OSError("injected rename")
        os.rename(old, new, src_dir_fd=parent, dst_dir_fd=parent)

    def flush_file(fd):
        nonlocal fault_used
        trace.append(["flush-file", descriptors[fd]])
        if armed and not fault_used and case in ("flush-error", "retry-flush"):
            fault_used = True
            raise OSError("injected flush")
        os.fsync(fd)

    for field, value in {
        "os": OsView(),
        "WindowsPrivateDirectoryAcl": Acl,
        "open_windows_directory": open_directory,
        "open_windows_regular_file_at": open_file,
        "windows_stat_at": visible,
        "windows_regular_file_stream_names": lambda _: ("::$DATA",),
        "windows_directory_stream_names": lambda _: (),
        "windows_flush_file": flush_file,
        "windows_flush_directory": lambda fd: trace.append(
            ["flush-directory", descriptors[fd]]
        ),
    }.items():
        patch.setattr(native, field, value)
    patch.setattr(_file_consumption, "os", OsView())
    patch.setattr(receipts, "windows_rename_at", rename)

    @contextmanager
    def directory(path, *, revalidate_on_success):
        trace.append(["lineage-enter", str(path), revalidate_on_success])
        if case == "directory-enter":
            raise OSError("injected lineage enter")
        fd = os.open(physical(path), os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)
            trace.append(["lineage-exit"])
            if case in ("exit-error", "close-exit-error"):
                raise OSError("injected lineage exit")

    patch.setattr(effects, "private_windows_directory", directory)

    def names(fd):
        names = tuple(sorted(os.listdir(fd)))
        trace.append(["list", list(names)])
        return names

    patch.setattr(effects, "windows_listdir_at", names)
    patch.setattr(history, "windows_listdir_at", names)

    def identity(path):
        trace.append(["identity", str(path)])
        if path == package:
            return package_id
        if path == root.parent:
            return parent_id
        if case == "root-missing":
            raise FileNotFoundError("injected missing root")
        if case in ("root-changed", "publish-identity"):
            return (99, 100)
        physical(path).stat()
        return root_id

    def prepare(path, *parts, **kwargs):
        trace.append(["prepare", str(path), list(parts), kwargs])
        physical(path.joinpath(*parts)).mkdir(mode=0o700, parents=True, exist_ok=True)

    patch.setattr(
        effects, "inspect_windows_product_private_directory_identity", identity
    )
    patch.setattr(effects, "prepare_windows_product_private_directory_chain", prepare)
    real_init = deletion.CodingWindowsArchPrivateDataDeletionTransaction.__init__
    real_events = deletion.CodingWindowsArchPrivateDataDeletionTransaction.events
    real_close = deletion.CodingWindowsArchPrivateDataDeletionTransaction._close

    def init(self, *args, **kwargs):
        trace.append(["transaction-init"])
        if case == "constructor-error":
            raise OSError("injected constructor")
        real_init(self, *args, **kwargs)

    def load(self):
        trace.append(["transaction-events"])
        if case in ("events-error", "events-close-error"):
            raise OSError("injected events")
        return real_events(self)

    def close(self):
        trace.append(["transaction-close"])
        real_close(self)
        if case in ("close-error", "events-close-error", "close-exit-error"):
            raise OSError("injected transaction close")

    patch.setattr(
        deletion.CodingWindowsArchPrivateDataDeletionTransaction, "__init__", init
    )
    patch.setattr(
        deletion.CodingWindowsArchPrivateDataDeletionTransaction, "events", load
    )
    patch.setattr(
        deletion.CodingWindowsArchPrivateDataDeletionTransaction, "_close", close
    )
    original_import = builtins.__import__

    def resolve(name, *args, **kwargs):
        if name.endswith("package_private_data_windows_deletion_journal"):
            trace.append(["class-resolve"])
            if case == "getter-error":
                raise ImportError("injected class resolution")
        return original_import(name, *args, **kwargs)

    patch.setattr(builtins, "__import__", resolve)
    # Fault the actual common write, while retaining its original byte program.
    original_write = native.WindowsPrivateReceiptIO.write_private_receipt

    def write(io, path, payload, *, maximum_bytes):
        trace.append(["write-bound", maximum_bytes])
        if (
            armed
            and case == "receipt-write-error"
            and not path.name.endswith(".intent.json")
        ):
            raise OSError("injected receipt write")
        result = original_write(io, path, payload, maximum_bytes=maximum_bytes)
        if (
            armed
            and case == "receipt-after-write"
            and not path.name.endswith(".intent.json")
        ):
            raise receipts.CodingWindowsPrivateReceiptError(
                "injected after publication"
            )
        return result

    patch.setattr(native.WindowsPrivateReceiptIO, "write_private_receipt", write)
    armed = True
    trace.clear()

    def operation():
        if kind == "current":
            return code._windows_arch_current_root_generation(
                key,
                root,
                state,
                package_id,
                recover_stage=case == "recover-intent-stage",
                allow_pending=case == "allow-pending",
            )
        if kind == "bind":
            return code._bind_windows_arch_installation_root(
                layout, key, state_root=state
            )
        if kind == "inspect":
            return code.inspect_coding_windows_arch_installation_root(
                layout,
                key,
                state_root=state / "other" if case == "state-changed" else state,
            )
        if kind == "restore":
            selected_predecessor = (
                "wrong"
                if case in ("wrong-predecessor", "publish-predecessor")
                else predecessor
            )
            selected_state = (
                state / "other"
                if case in ("state-changed", "publish-state-changed")
                else state
            )
            if case.startswith("publish"):
                return code._publish_windows_arch_restored_root_receipt(
                    layout,
                    key,
                    state_root=selected_state,
                    generation_number=3 if case == "publish-generation" else 2,
                    deletion_receipt_id=selected_predecessor,
                    expected_identity=(88, 89)
                    if case == "publish-stored-identity"
                    else root_id,
                )
            return code._prepare_windows_arch_restore_generation_intent(
                layout,
                key,
                state_root=selected_state,
                deletion_receipt_id=selected_predecessor,
            )
        if case.startswith("name-"):
            prefix = f"arch-private-root-{root.name}.generation-"
            suffix = {
                "name-valid": "00000002.json",
                "name-future": "00000003.json",
                "name-malformed": "00000002.evil.json",
                "name-stage": "00000002.intent.json.stage",
            }[case]
            return code._validate_windows_root_generation_names(
                (prefix + suffix,), root, 2
            )
        number = {
            "initial": 1,
            "true": True,
            "float": 1.0,
            "false": False,
            "zero": 0,
            "max": 4097,
            "future": 4098,
            "missing-predecessor": 2,
            "initial-predecessor": 1,
            "negative": -1,
        }[case]
        pred = "receipt-id" if number != 1 or case == "initial-predecessor" else None
        if case == "missing-predecessor":
            pred = None
        paths = code._windows_arch_generation_paths(root, state, number)
        return {
            "paths": [str(p) for p in paths],
            "intent": code._windows_arch_generation_intent_payload(
                key, root, package_id, number, pred
            ).hex(),
            "receipt": code._windows_arch_generation_receipt_payload(
                key, root, parent_id, root_id, number, pred
            ).hex(),
        }

    def serial(value):
        if isinstance(value, code._WindowsArchRootGeneration):
            return {
                "type": type(value).__module__ + "." + type(value).__qualname__,
                "number": value.number,
                "predecessor": value.predecessor_receipt_id,
                "intent_path": str(value.intent_path),
                "receipt_path": str(value.receipt_path),
                "intent": None if value.intent is None else value.intent.hex(),
                "receipt": None if value.receipt is None else value.receipt.hex(),
                "identity": None if value.identity is None else list(value.identity),
            }
        return list(value) if isinstance(value, tuple) else value

    def attempt():
        try:
            return {"value": serial(operation()), "error": None}
        except BaseException as exc:
            return {"value": None, "error": error_graph(exc, lambda value: value)}

    try:
        result = attempt()
        if case in ("repeat", "intent-repeat", "publish-repeat") or case.startswith(
            "retry-"
        ):
            armed = False
            trace.append(["retry"])
            result = {"first": result, "second": attempt()}
        return {
            "result": result,
            "trace": trace,
            "outstanding": list(descriptors.values()),
            "tree": {
                str(p.relative_to(base)): {
                    "mode": oct(stat.S_IMODE(p.stat().st_mode)),
                    "bytes": p.read_bytes().hex() if p.is_file() else None,
                }
                for p in sorted(base.rglob("*"))
            },
        }
    finally:
        for fd in tuple(descriptors):
            with suppress(OSError):
                os.close(fd)


def fixed_observation(value):
    # All original ordered trace entries are covered by one exact digest.
    # Raw immutable observations remain in the source-guarded external archive.
    trace = value["trace"]
    return {
        **{key: item for key, item in value.items() if key != "trace"},
        "trace_entries": len(trace),
        "trace_sha256": sha256(canonical(trace)).hexdigest(),
    }


FIXTURE = json.loads(
    (
        Path(__file__).parent / "fixtures" / "windows_installation_root_lineage_v1.json"
    ).read_text()
)


@pytest.mark.parametrize("case", CASES)
def test_original_windows_root_lineage(case, tmp_path, monkeypatch):
    actual = observe(case, tmp_path, monkeypatch)
    assert fixed_observation(actual) == FIXTURE["observations"][case], actual
