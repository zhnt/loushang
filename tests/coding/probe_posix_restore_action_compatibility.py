"""Old POSIX restore control flow, with inert admission/native ports.

This checks resource scope and error order, not archive authority or real I/O.
The existing Product integration suite supplies the separate native evidence.
"""

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

import loushang.coding.package_private_data_restore as code
import loushang.harness.plugin_management.private_data_backup as archive
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

CASES = (
    "success",
    "replay",
    "existing_without_start",
    "expected_same_absent",
    "preflight",
    "journal_open",
    "begin",
    "transfer",
    "post_verify",
    "archive_changed",
    "complete",
    "result",
    "files_close",
    "archive_close",
    "parent_close",
    "result_archive_close",
    "complete_parent_close",
    "archive_open",
    "files_open",
    "replay_verify",
    "replay_close",
    "dynamic_hooks",
    "writer_snapshot",
)


def observe(case, patch):
    trace = []
    opened = set()
    key = PluginInstallationKeyV1("coding", "workspace", "test", "coding.arch.default")
    name = "b" * 64
    source = NS(target_id="present:test", members=())
    receipt = NS(
        installation_key=key, backup_id=name, source_target_id=source.target_id
    )
    deletion = NS(receipt_id="deleted:test")
    base, target = Path("/inert/private"), Path("/inert/private/data/install")
    meta = NS(
        st_dev=1, st_ino=2, st_mode=16832, st_size=0, st_mtime_ns=3, st_ctime_ns=4
    )
    stat_count = 0
    verify_count = 0
    existing = case in {
        "replay",
        "existing_without_start",
        "replay_verify",
        "replay_close",
    }
    replay = case in {"replay", "replay_verify", "replay_close"}

    def effect(label):
        trace.append(label)
        if (
            case == label
            or (case == "result_archive_close" and label == "result")
            or (case == "complete_parent_close" and label == "complete")
        ):
            raise RuntimeError(label)

    def close(fd):
        trace.append(f"close:{fd}")
        failure = {
            "files_close": 30,
            "archive_close": 20,
            "parent_close": 10,
            "result_archive_close": 20,
            "complete_parent_close": 10,
            "replay_close": 40,
        }.get(case)
        if failure == fd:
            raise OSError(f"close:{fd}")
        opened.remove(fd)

    @contextmanager
    def closing(fd):
        try:
            yield fd
        finally:
            close(fd)

    @contextmanager
    def offline():
        trace.append("offline:enter")
        try:
            yield
        finally:
            trace.append("offline:exit")

    def stat(*args, **kwargs):
        nonlocal stat_count
        stat_count += 1
        trace.append("stat")
        if case == "archive_changed" and stat_count == 2:
            return NS(**{**vars(meta), "st_ino": 5})
        return meta

    def fstat(fd):
        trace.append(f"fstat:{fd}")
        assert fd in opened
        return meta

    class IO:
        label = "Coding Arch"

        def open_path(self, private_base, path):
            assert private_base == base
            fd = 10 if path == base / "backups" else 40
            trace.append(f"open:{fd}")
            opened.add(fd)
            return fd

        def open_directory(self, parent, child):
            fd = 20 if parent == 10 else 30
            assert (parent, child) in {(10, name), (20, "files")}
            effect("archive_open" if fd == 20 else "files_open")
            opened.add(fd)
            return fd

        def preflight_restore_target(self, private_base, path, members, **kwargs):
            assert (private_base, path, members) == (base, target, ())
            assert kwargs == dict(
                stage_name=".arch-restore-" + name + ".staging",
                stage_prefix=".arch-restore-",
                stage_suffix=".staging",
            )
            effect("preflight")
            return existing

        def restore_verified_tree(self, private_base, path, members, fd, **kwargs):
            assert fd == 30 and fd in opened
            effect("transfer")
            kwargs["write_file"](30, "member", b"content")
            if case == "writer_snapshot":
                kwargs["write_file"](30, "member2", b"content")
            return "restored"

    class Journal:
        def __init__(self, root):
            assert opened == {10, 20, 30}
            effect("journal_open")

        def events(self):
            trace.append("events")
            return (
                ()
                if case == "existing_without_start"
                else (NS(restore_id="restore:test"),)
            )

        def begin(self, **kwargs):
            assert kwargs == dict(
                key=key, backup_id=name, deletion_receipt_id="deleted:test"
            )
            effect("begin")
            return NS(
                phase="completed" if replay else "started", restore_id="restore:test"
            )

        def complete(self, event):
            assert opened == {10, 20}
            effect("complete")
            return NS(restore_id=event.restore_id)

    def result(*args):
        assert opened == {10, 20}
        effect("result")
        return list(args)

    def verify_files(fd, actual_source):
        nonlocal verify_count
        assert fd in opened and actual_source is source
        verify_count += 1
        trace.append(f"verify:{fd}")
        if case == "dynamic_hooks" and verify_count == 1:

            def changed_verify(fd, source):
                trace.append("changed_verify")
                verify_files(fd, source)

            def changed_write(*args):
                trace.append("changed_write")
                write(*args)

            patch.setattr(code, "_verify_files", changed_verify)
            patch.setattr(code, "_write_or_verify_file", changed_write)
        if (case == "post_verify" and verify_count == 2) or (
            case == "replay_verify" and fd == 40
        ):
            raise RuntimeError("verify")

    def verify_archive(*args, **kwargs):
        assert args == (10, name, key, source, receipt)
        trace.append("verify_archive")

    def prepare(path, **kwargs):
        assert path == target.parent
        assert kwargs == dict(private_base=base, label="data")
        trace.append("prepare")

    def identity(*args):
        assert args == (key, name, "deleted:test")
        trace.append("identity")
        return "restore:test"

    def write(*args):
        trace.append("write")
        if case == "writer_snapshot":
            patch.setattr(
                code,
                "_write_or_verify_file",
                lambda *args: trace.append("changed_write"),
            )

    io = IO()
    patch.setattr(
        code, "CodingArchPrivateDataDeletionPreview", lambda *a: NS(_offline=offline)
    )
    patch.setattr(code, "coding_arch_installation_private_data_root", lambda *a: target)
    patch.setattr(
        code,
        "CodingArchPrivateDataDeletionJournal",
        lambda *a: NS(current_start=lambda: None, events=lambda: ()),
    )
    patch.setattr(code, "latest_deleted_target_receipt", lambda *a: deletion)
    patch.setattr(code, "_backup_parent", lambda *a: base / "backups")
    patch.setattr(code, "_read_manifest", lambda *a: (receipt, source))
    patch.setattr(code, "_private_io", io)
    patch.setattr(code, "_open_private_path", io.open_path)
    if hasattr(code, "_open_private_dir"):
        patch.setattr(code, "_open_private_dir", io.open_directory)
    patch.setattr(archive, "verify_private_archive", verify_archive)
    patch.setattr(code, "_verify_files", verify_files)
    patch.setattr(code, "_write_or_verify_file", write)
    patch.setattr(code, "_prepare_private_tree", prepare)
    patch.setattr(code, "CodingArchPrivateDataRestoreJournal", Journal)
    patch.setattr(code, "restore_id_for", identity)
    patch.setattr(code, "CodingArchPrivateDataRestoreResultV1", result)
    native = NS(stat=stat, fstat=fstat)
    if hasattr(code, "os"):
        patch.setattr(code, "os", native)
    patch.setattr(archive, "os", native)
    patch.setattr(code, "closing_descriptor", closing)
    patch.setattr(archive, "closing_descriptor", closing)
    owner = object.__new__(code.CodingArchPrivateDataRestoreOwner)
    object.__setattr__(owner, "layout", NS(private_data_base=base))
    object.__setattr__(
        owner,
        "product",
        NS(
            state_root=Path("/inert/state"),
            desired_state=NS(
                snapshot=lambda: NS(
                    inventory_revision=3,
                    installation=lambda k: NS(selection=NS(desired_state="absent")),
                )
            ),
        ),
    )
    expected = (
        None
        if case != "expected_same_absent"
        else code.CodingArchPrivateDataRestorePlanV1(
            key, name, deletion.receipt_id, source.target_id, 3, "same_bytes"
        )
    )
    value = None
    error = None
    try:
        value = owner.restore(key, name, expected_plan=expected)
    except Exception as exc:
        error = [type(exc).__name__, str(exc)]
        chain = exc.__context__
        while chain is not None:
            error.append([type(chain).__name__, str(chain)])
            chain = chain.__context__
    return dict(trace=trace, value=value, error=error, unclosed=sorted(opened))


@pytest.mark.parametrize("case", CASES)
def test_posix_restore_original_control_flow(case, monkeypatch):
    expected = json.loads(
        (
            Path(__file__).parent / "fixtures" / "posix_restore_action_v2.json"
        ).read_text()
    )
    assert observe(case, monkeypatch) == expected[case]
