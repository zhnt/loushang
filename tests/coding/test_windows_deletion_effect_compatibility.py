"""Old Windows deletion effects over real POSIX FDs and inert Windows boundaries.

This covers the physical-action glue and its checkpoint calls. It does not
mint Product authorization, validate DACLs, or prove Windows kernel semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from contextlib import ExitStack, suppress
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import package_private_data_windows_deletion_journal as journal
from loushang.coding import package_private_data_windows_deletion_owner as owner
from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
    _identity,
)
from loushang.harness.plugin_management import private_data_deletion as action
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages import _file_consumption, _private_tree_windows

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Real POSIX FD proof; not native Windows evidence"
)
CASES = (
    "absent",
    "absent_changed",
    "fresh",
    "resume",
    "partial_resume",
    "rename_after",
    "renamed_after",
    "remove_partial",
    "delete_after",
    "coexist",
    "ambiguous",
    "missing_renamed",
    "root_reappeared",
    "stale_target",
    "wrong_renamed",
    "recreated",
    "nonempty",
    "parent_changed",
    "source_changed",
    "bad_remaining",
    "parent_acl",
    "source_acl",
)
PROOF_CASES = (
    "proof_present",
    "proof_absent",
    "proof_wrong_receipt",
    "proof_wrong_generation",
    "proof_root_visible",
    "proof_bad_members",
    "proof_foreign_member",
    "proof_parent_after",
    "proof_acl",
)
FIXTURE = Path(__file__).with_name("fixtures") / "windows_deletion_effects_v1.json"


def observe(case, directory, monkeypatch):
    directory.mkdir(mode=0o700)
    root = directory / "arch"
    trace, descriptors, owned, phases, attempts = [], {}, [], ["started"], []
    fired = set()
    metadata_calls = {}

    def tag(path):
        parts = Path(path).relative_to(directory).parts
        return (
            "/".join("<tombstone>" if p.startswith(".deleting-") else p for p in parts)
            or "."
        )

    def snapshot(path):
        if not path.exists():
            return CodingArchPrivateDataTargetSnapshotV1("a" * 64, None, ())
        members = tuple(
            CodingArchPrivateDataMemberV1(
                str(p.relative_to(path)),
                "directory" if p.is_dir() else "file",
                _identity(p.lstat()),
                None if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest(),
            )
            for p in sorted(path.rglob("*"))
        )
        return CodingArchPrivateDataTargetSnapshotV1(
            "a" * 64, _identity(path.lstat()), members
        )

    if case != "absent":
        root.mkdir(mode=0o700)
        (root / "one").write_bytes(b"first")
        (root / "two").write_bytes(b"second")
    target = snapshot(root)
    if case == "absent_changed":
        target = CodingArchPrivateDataTargetSnapshotV1("a" * 64, None, ())
    key = PluginInstallationKeyV1(
        "coding", "workspace", "workspace:" + "b" * 64, "coding.arch.default"
    )
    plan = PluginPrivateDataDeletionPlanV1(
        key, "coding.arch.private-data:windows-v1", target.target_id
    )
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan.fingerprint, "arch-delete:effect-probe"
    )
    started = CodingArchPrivateDataDeletionEventV1(
        1, "started", plan, confirmation, target
    )
    renamed = (
        replace(started, revision=2, phase="renamed")
        if target.root_identity is not None
        else None
    )
    tombstone = directory / owner._tombstone_name(started)
    if case in {"resume", "partial_resume"} or (
        case in PROOF_CASES and case not in {"proof_absent", "proof_root_visible"}
    ):
        root.rename(tombstone)
    if case == "partial_resume":
        (tombstone / "one").unlink()
        phases.append("renamed")
    if case == "coexist":
        tombstone.mkdir(mode=0o700)
    if case in {"ambiguous", "missing_renamed", "proof_absent"}:
        for p in root.iterdir():
            p.unlink()
        root.rmdir()
    if case in {"missing_renamed", "root_reappeared"}:
        phases.append("renamed")

    if case == "proof_bad_members":
        (tombstone / "two").write_bytes(b"changed")
    if case == "proof_foreign_member":
        (tombstone / "foreign").write_bytes(b"foreign")

    def generation(observed_key, observed_root, _state, _package, *, allow_pending):
        assert observed_key == key and observed_root == root and allow_pending
        trace.append(["generation"])
        identity = target.root_identity[:2]
        if case == "proof_wrong_generation":
            identity = (identity[0], identity[1] + 1)
        return SimpleNamespace(
            receipt=None if case == "proof_wrong_receipt" else object(),
            identity=identity,
        )

    def fault(stage):
        if case == stage and stage not in fired:
            fired.add(stage)
            raise OSError("injected:" + stage)

    class Transaction:
        def current_start(self):
            trace.append(["current_start", phases[-1]])
            return renamed if phases[-1] == "renamed" else started

        def record_renamed(self, value):
            assert value == started
            trace.append(["record_renamed", phases[-1]])
            if case == "wrong_renamed":
                return started
            if phases[-1] != "renamed":
                phases.append("renamed")
            fault("renamed_after")
            return renamed

    def capture_current(_confirmation_owner, observed_key, *, allow_pending):
        assert observed_key == key and allow_pending is True
        trace.append(["capture_current"])
        current = snapshot(root)
        if case == "stale_target":
            current = replace(current, root_path_digest="c" * 64)
        return current

    def capture(path, *, expected_root):
        assert path == tombstone and expected_root == target.root_identity[:2]
        trace.append(["capture", tag(path)])
        if case == "bad_remaining" and "tamper" not in fired:
            fired.add("tamper")
            (path / "two").write_bytes(b"changed")
        return snapshot(path)

    def inspect_parent(path):
        assert path == directory
        trace.append(["inspect_parent"])
        m = path.lstat()
        return (m.st_dev + (case == "parent_changed"), m.st_ino)

    def metadata(descriptor):
        m = os.fstat(descriptor)
        path = descriptors[descriptor]
        trace.append(["fstat", tag(path)])
        metadata_calls[path] = metadata_calls.get(path, 0) + 1
        inode = m.st_ino + (
            (case == "source_changed" and path == root)
            or (
                case == "proof_parent_after"
                and path == directory
                and metadata_calls[path] == 2
            )
        )
        return SimpleNamespace(
            st_dev=m.st_dev,
            st_ino=inode,
            st_mode=m.st_mode,
            st_size=m.st_size,
            st_mtime_ns=m.st_mtime_ns,
            st_nlink=m.st_nlink,
            st_file_attributes=0x10 if stat.S_ISDIR(m.st_mode) else 0x20,
        )

    class ACL:
        def __enter__(self):
            trace.append(["acl_enter"])
            return self

        def __exit__(self, *_args):
            trace.append(["acl_exit"])

        def validate(self, descriptor):
            os.fstat(descriptor)
            path = descriptors[descriptor]
            trace.append(["acl", tag(path)])
            if (case in {"parent_acl", "proof_acl"} and path == directory) or (
                case == "source_acl" and path == root
            ):
                raise PermissionError("injected:" + case)

    def open_directory(path, *, share_delete, read_control):
        assert path == directory and share_delete is False and read_control is True
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        descriptors[descriptor] = path
        owned.append(descriptor)
        trace.append(["open", tag(path)])
        return descriptor

    def open_entry(parent, name, *, directory):
        assert directory is True
        path = descriptors[parent] / name
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        descriptors[descriptor] = path
        owned.append(descriptor)
        trace.append(["open", tag(path)])
        return descriptor

    def close(descriptor):
        trace.append(["close", tag(descriptors.pop(descriptor))])
        os.close(descriptor)

    def listdir(descriptor):
        trace.append(["list", tag(descriptors[descriptor])])
        return os.listdir(descriptor)

    def streams(descriptor):
        trace.append(["streams", tag(descriptors[descriptor])])
        return ("::$DATA",)

    def rename(parent, source, name, *, expected_identity):
        assert _identity(os.fstat(source))[:3] == expected_identity[:3]
        assert descriptors[parent] == directory
        trace.append(["rename"])
        os.rename(descriptors[source], directory / name)
        descriptors[source] = directory / name
        fault("rename_after")

    def flush(descriptor):
        os.fstat(descriptor)
        trace.append(["flush", tag(descriptors[descriptor])])

    def remove_members(path, members, original):
        assert path == tombstone and original == target
        trace.append(["remove", [m.relative_path for m in members]])
        for member in members:
            if case == "nonempty":
                continue
            (path / member.relative_path).unlink()
            fault("remove_partial")
        if case == "recreated":
            root.mkdir()

    def delete(descriptor, *, expected_identity, directory):
        assert directory is True
        assert _identity(os.fstat(descriptor))[:3] == expected_identity[:3]
        trace.append(["delete", tag(descriptors[descriptor])])
        os.rmdir(descriptors[descriptor])
        fault("delete_after")

    namespace = SimpleNamespace(**vars(os))
    namespace.close, namespace.fstat = close, metadata
    try:
        with ExitStack() as stack:
            replacements = {
                "WindowsPrivateDirectoryAcl": ACL,
                "inspect_windows_product_private_directory_identity": inspect_parent,
                "open_windows_directory": open_directory,
                "open_windows_deletion_entry_at": open_entry,
                "windows_listdir_at": listdir,
                "windows_directory_stream_names": streams,
                "windows_flush_directory": flush,
                "windows_rename_open_directory_at": rename,
                "windows_delete_open_entry": delete,
            }
            for module in (
                owner,
                journal,
                action,
                _private_tree_windows,
                _file_consumption,
            ):
                patch = stack.enter_context(monkeypatch.context())
                if hasattr(module, "os"):
                    patch.setattr(module, "os", namespace)
                for name, value in replacements.items():
                    if hasattr(module, name):
                        patch.setattr(module, name, value)
            patch = stack.enter_context(monkeypatch.context())
            patch.setattr(
                journal,
                "coding_arch_installation_private_data_root",
                lambda _layout, _key: root,
            )
            patch.setattr(journal, "_windows_arch_current_root_generation", generation)
            patch.setattr(journal, "_capture_windows_target_snapshot", capture)
            patch.setattr(owner, "_capture_current_target", capture_current)
            patch.setattr(owner, "_capture_windows_target_snapshot", capture)
            patch.setattr(owner, "_remove_members", remove_members)
            patch.setattr(
                _private_tree_windows.PrivateWindowsTreeIO,
                "remove_members",
                lambda _self, *args: remove_members(*args),
            )
            for attempt in range(
                2
                if case
                in {"rename_after", "renamed_after", "remove_partial", "delete_after"}
                else 1
            ):
                trace.append(["attempt", attempt])
                try:
                    if case in PROOF_CASES:
                        proof_owner = SimpleNamespace(
                            layout=SimpleNamespace(package_root=directory),
                            product=SimpleNamespace(state_root=directory / "state"),
                        )
                        disposition = journal._require_windows_tombstone(
                            proof_owner, started, present=case != "proof_absent"
                        )
                    else:
                        disposition = owner._delete_started(
                            root, started, Transaction(), object()
                        )
                except Exception as error:
                    assert not isinstance(
                        error, (AssertionError, KeyError, AttributeError, TypeError)
                    ), error
                    attempts.append([type(error).__name__, str(error)])
                else:
                    attempts.append(["returned", disposition])
                assert not descriptors, "physical-action scope leaked an FD"
        remaining = [tag(p) for p in sorted(directory.rglob("*"))]
        return {
            "attempts": attempts,
            "phases": phases,
            "remaining": remaining,
            "trace": trace,
            "all_owned_fds_closed": True,
        }
    finally:
        for descriptor in tuple(descriptors):
            with suppress(OSError):
                os.close(descriptor)
        for descriptor in owned:
            with pytest.raises(OSError):
                os.fstat(descriptor)


@pytest.mark.parametrize("case", CASES)
def test_original_windows_deletion_effects(case, tmp_path, monkeypatch):
    expected = json.loads(FIXTURE.read_text())[case]
    assert observe(case, tmp_path / case, monkeypatch) == expected


@pytest.mark.parametrize("case", PROOF_CASES)
def test_original_windows_deletion_tombstone_proof(case, tmp_path, monkeypatch):
    expected = json.loads(
        FIXTURE.with_name("windows_tombstone_proofs_v1.json").read_text()
    )[case]
    assert observe(case, tmp_path / case, monkeypatch) == expected
