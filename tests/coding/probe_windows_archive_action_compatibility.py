"""Original action ordering over inert native ports, not Windows authority proof."""

from __future__ import annotations

import json
import os
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import loushang.coding.package_private_data_windows_backup as coding
from loushang.coding.package_private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.harness.plugin_management import _private_data_backup_windows as action
from loushang.harness.resources.packages import _file_consumption
from loushang.harness.resources.packages import _private_tree_windows as native

CASES = (
    "fresh",
    "reuse",
    "stage",
    "foreign_stage",
    "stage_and_final",
    "stage_members",
    "copy_failure",
    "write_failure",
    "stage_flush",
    "source_changed",
    "root_changed",
    "stage_verify",
    "rename_before",
    "rename_after",
    "parent_flush",
    "final_verify",
    "parent_acl",
    "parent_open",
    "parent_post",
    "parent_close",
    "stage_close",
    "copy_and_post",
    "copy_and_close",
)
FIXTURE = Path(__file__).with_name("fixtures") / "windows_archive_action_v1.json"
READ_CASES = (
    "verify:fresh",
    "verify:stage",
    "verify:foreign_key",
    "verify:source_absent",
    "verify:source_changed",
    "verify:noncanonical",
    "verify:duplicate",
    "verify:bad_utf8",
    "verify:oversized",
    "verify:grow",
    "verify:grow_and_attributes",
    "verify:late_links",
    "verify:parent_close",
    "verify:parent_post",
)
READ_FIXTURE = FIXTURE.with_name("windows_archive_read_v1.json")
FD_CASES = (
    "valid",
    "before_attributes",
    "after_attributes",
    "read_failure",
    "bad_utf8",
)
FD_FIXTURE = FIXTURE.with_name("windows_archive_fds_v1.json")


def observe(case):
    # Domain fixtures and gates are inert; this checks the actual original action
    # and native call boundaries. Native copy and Windows authority have separate evidence.
    operation, case = case.split(":", 1) if ":" in case else ("retain", case)
    fixture = json.loads((FIXTURE.parent / "private_data_v1.json").read_text())
    source = CodingArchPrivateDataTargetSnapshotV1.from_dict(fixture["source"])
    key = CodingArchPrivateDataBackupReceiptV1.from_dict(
        fixture["receipt"]
    ).installation_key
    base = Path("/archive-probe")
    source_path, parent = base / "source", base / "backups" / "owner"
    backup_id = coding.backup_id(key, source)
    stage, final = parent / (backup_id + ".staging"), parent / backup_id
    nodes, handles, offsets, trace = {}, {}, {}, []
    counter = 100
    source_captures, root_checks, parent_checks = 0, 0, 0
    manifest_reads = 0

    def short(path):
        return str(path.relative_to(base)).replace(backup_id, "<backup>")

    def make(path, directory=True, content=b""):
        nodes[path] = SimpleNamespace(
            directory=directory, content=content, inode=len(nodes) + 1
        )

    def metadata(path):
        node = nodes[path]
        value = SimpleNamespace(
            st_dev=1,
            st_ino=node.inode,
            st_mode=(stat.S_IFDIR | 0o700)
            if node.directory
            else (stat.S_IFREG | 0o600),
            st_size=0 if node.directory else len(node.content),
            st_mtime_ns=1,
            st_nlink=1,
            st_file_attributes=0x10 if node.directory else 0x20,
        )
        if path.name == "manifest.json":
            if case == "oversized":
                value.st_size = 4 * 1024 * 1024 + 1
            if manifest_reads and case == "grow_and_attributes":
                value.st_file_attributes = 0x2
            if manifest_reads and case == "late_links":
                value.st_nlink = 2
        return value

    def opened(path):
        nonlocal counter
        if path not in nodes:
            raise FileNotFoundError(str(path))
        counter += 1
        handles[counter] = path
        offsets[counter] = 0
        return counter

    class OS:
        def __getattr__(self, name):
            return getattr(os, name)

        def fstat(self, descriptor):
            trace.append("stat:" + short(handles[descriptor]))
            return metadata(handles[descriptor])

        def read(self, descriptor, maximum):
            nonlocal manifest_reads
            trace.append(f"read:{short(handles[descriptor])}:{maximum}")
            if handles[descriptor].name == "manifest.json":
                manifest_reads += 1
                if manifest_reads == 1 and case in {"grow", "grow_and_attributes"}:
                    nodes[handles[descriptor]].content += b"x"
            content = nodes[handles[descriptor]].content[
                offsets[descriptor] : offsets[descriptor] + maximum
            ]
            offsets[descriptor] += len(content)
            return content

        def write(self, descriptor, data):
            path = handles[descriptor]
            trace.append(f"write:{short(path)}:{len(data)}")
            if case == "write_failure":
                raise OSError("injected manifest write failure")
            node = nodes[path]
            offset = offsets[descriptor]
            node.content = (
                node.content[:offset] + bytes(data) + node.content[offset + len(data) :]
            )
            offsets[descriptor] += len(data)
            return len(data)

        def lseek(self, descriptor, offset, whence):
            trace.append(f"seek:{short(handles[descriptor])}:{offset}:{whence}")
            offsets[descriptor] = (
                offset
                if whence == os.SEEK_SET
                else len(nodes[handles[descriptor]].content) + offset
            )
            return offsets[descriptor]

        def close(self, descriptor):
            path = handles.pop(descriptor)
            offsets.pop(descriptor)
            trace.append("close:" + short(path))
            if (path == parent and case in {"parent_close", "copy_and_close"}) or (
                path == stage and case == "stage_close"
            ):
                raise OSError("injected native close failure")

    class ACL:
        def __init__(self, *, inherit_children=False):
            self.security_descriptor = "inherited" if inherit_children else "exact"

        def __enter__(self):
            trace.append("acl-enter:" + self.security_descriptor)
            return self

        def __exit__(self, *_):
            trace.append("acl-exit:" + self.security_descriptor)

        def validate(self, descriptor, **kwargs):
            path = handles[descriptor]
            trace.append(f"acl:{short(path)}:{self.security_descriptor}:{kwargs}")
            if path == parent and case == "parent_acl":
                raise PermissionError("injected parent ACL failure")

    def directory(name, *, dir_fd=None, create_new=False, **_):
        path = Path(name) if dir_fd is None else handles[dir_fd] / name
        trace.append(f"open-directory:{short(path)}:{create_new}")
        if path == parent and case == "parent_open":
            raise OSError("injected parent open failure")
        if create_new:
            if path in nodes:
                raise FileExistsError(str(path))
            make(path)
        return opened(path)

    def regular(parent_fd, name, *, create_new, write, **_):
        path = handles[parent_fd] / name
        trace.append(f"open-file:{short(path)}:{create_new}:{write}")
        if create_new:
            if path in nodes:
                raise FileExistsError(str(path))
            make(path, False)
        return opened(path)

    def names(descriptor):
        path = handles[descriptor]
        trace.append("list:" + short(path))
        return tuple(sorted(item.name for item in nodes if item.parent == path))

    def visible(descriptor, name):
        path = handles[descriptor] / name
        trace.append("visible:" + short(path))
        return metadata(path)

    def streams(descriptor):
        trace.append("streams:" + short(handles[descriptor]))
        return ("::$DATA",)

    def flush(descriptor):
        path = handles[descriptor]
        trace.append("flush:" + short(path))
        if (path == stage and case == "stage_flush") or (
            path == parent and case == "parent_flush"
        ):
            raise OSError("injected flush failure")

    def inspect(path):
        nonlocal parent_checks
        trace.append("inspect:" + short(path))
        parent_checks += 1
        value = metadata(path)
        return value.st_dev, value.st_ino + (
            1 if parent_checks > 1 and case in {"parent_post", "copy_and_post"} else 0
        )

    def capture(path, *, expected_root):
        nonlocal source_captures
        trace.append("capture:" + short(path))
        if path == source_path:
            source_captures += 1
            if source_captures > 1 and case == "source_changed":
                return replace(source, members=())
        return source

    def inspect_source(*_, **__):
        nonlocal root_checks
        root_checks += 1
        trace.append("source-authority")
        return (1, 1) if root_checks == 1 or case != "root_changed" else (1, 2)

    def copy(*_):
        trace.append("copy")
        if case in {"copy_failure", "copy_and_post", "copy_and_close"}:
            raise OSError("injected copy failure")

    def rename(parent_fd, old, new):
        trace.append("rename")
        if case == "rename_before":
            raise OSError("injected rename failure")
        old_path, new_path = handles[parent_fd] / old, handles[parent_fd] / new
        for path in tuple(nodes):
            if path == old_path or path.is_relative_to(old_path):
                nodes[new_path / path.relative_to(old_path)] = nodes.pop(path)
        if case == "rename_after":
            raise OSError("injected rename failure")

    class Preview:
        def __init__(self, *_):
            pass

        @contextmanager
        def _offline(self):
            trace.append("offline-enter")
            try:
                yield
            finally:
                trace.append("offline-exit")

    for path in (source_path, parent):
        make(path)
    receipt = CodingArchPrivateDataBackupReceiptV1(
        key,
        source.target_id,
        backup_id,
        sum(item.kind == "file" for item in source.members),
        sum(item.identity[3] for item in source.members if item.kind == "file"),
        "arch-backup:" + backup_id,
    )
    for path in (
        (final,)
        if case == "reuse" or operation == "verify"
        else (stage,)
        if case in {"stage", "stage_and_final", "stage_members"}
        else ()
    ):
        make(path)
        make(path / "files")
        make(
            path / "manifest.json",
            False,
            coding.canonical_json_bytes(
                {"receipt": receipt.to_dict(), "source": source.to_dict()}
            )
            + b"\n",
        )
    if case == "stage_and_final":
        make(final)
    if operation == "verify":
        if case == "stage":
            make(stage)
        if case == "source_absent":
            del nodes[source_path]
        if case == "noncanonical":
            nodes[final / "manifest.json"].content = (
                b" " + nodes[final / "manifest.json"].content
            )
        if case == "duplicate":
            nodes[final / "manifest.json"].content = (
                b'{"source":0,' + nodes[final / "manifest.json"].content[1:]
            )
        if case == "bad_utf8":
            nodes[final / "manifest.json"].content = b"\xff"
    if case == "stage_members":
        make(stage / "unexpected", False)
    if case == "foreign_stage":
        make(parent / "foreign.staging")
    product = SimpleNamespace(
        desired_state=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                installation=lambda _: SimpleNamespace(
                    latest_instance_revision_ref="old"
                )
            )
        )
    )
    owner = object.__new__(coding.CodingWindowsArchPrivateDataBackupOwner)
    object.__setattr__(owner, "layout", SimpleNamespace(package_root=base))
    object.__setattr__(owner, "product", product)
    old_verify, new_verify = (
        coding._verify_archive,
        action.WindowsPrivateArchiveIO.verify_archive,
    )

    def verification(delegate, args, name):
        trace.append("verify:" + name.replace(backup_id, "<backup>"))
        if (name.endswith(".staging") and case == "stage_verify") or (
            name == backup_id and case == "final_verify"
        ):
            raise ValueError("injected archive validation failure")
        return delegate(*args)

    primitives = dict(
        os=OS(),
        WindowsPrivateDirectoryAcl=ACL,
        open_windows_directory=directory,
        open_windows_regular_file_at=regular,
        windows_listdir_at=names,
        windows_stat_at=visible,
        windows_regular_file_stream_names=streams,
        windows_directory_stream_names=streams,
        windows_flush_directory=flush,
        windows_flush_file=flush,
        windows_rename_at=rename,
        inspect_windows_product_private_directory_identity=inspect,
    )
    with ExitStack() as stack:
        for module in (coding, action, native, _file_consumption):
            for name, value in primitives.items():
                if module is _file_consumption and name != "os":
                    continue
                stack.enter_context(patch.object(module, name, value, create=True))
        stack.enter_context(
            patch.object(coding, "CodingWindowsArchPrivateDataReadPreview", Preview)
        )
        stack.enter_context(
            patch.object(
                coding,
                "coding_arch_installation_private_data_root",
                lambda *_: source_path,
            )
        )
        stack.enter_context(
            patch.object(
                coding,
                "resolve_coding_package_epoch_layout",
                lambda _: SimpleNamespace(control_root=base),
            )
        )
        stack.enter_context(
            patch.object(
                coding, "inspect_coding_windows_arch_installation_root", inspect_source
            )
        )
        stack.enter_context(
            patch.object(coding, "_capture_windows_target_snapshot", capture)
        )
        stack.enter_context(patch.object(coding, "backup_parent", lambda *_: parent))
        stack.enter_context(
            patch.object(
                coding,
                "prepare_windows_product_private_directory_chain",
                lambda *_: trace.append("prepare"),
            )
        )
        stack.enter_context(patch.object(coding, "_copy_members", copy))
        stack.enter_context(
            patch.object(type(coding._native_io), "copy_members", lambda *_: copy())
        )
        stack.enter_context(
            patch.object(
                coding,
                "_verify_archive",
                lambda *args: verification(old_verify, args, args[2]),
            )
        )
        stack.enter_context(
            patch.object(
                action.WindowsPrivateArchiveIO,
                "verify_archive",
                lambda self, *args: verification(
                    lambda *values: new_verify(self, *values), args, args[2]
                ),
            )
        )
        try:
            if operation == "verify":
                requested = (
                    replace(key, scope_id="foreign") if case == "foreign_key" else key
                )
                result = owner.verify(requested, backup_id)
            else:
                result = owner.retain(key)
            outcome = {"same_receipt": result == receipt}
        except Exception as error:
            outcome = {
                "error": type(error).__name__,
                "message": str(error),
                "cause": None
                if error.__cause__ is None
                else [type(error.__cause__).__name__, str(error.__cause__)],
            }
    return {
        **outcome,
        "trace": trace,
        "open_descriptors": [short(path) for path in handles.values()],
        "files": {
            short(path): node.content.hex()
            for path, node in nodes.items()
            if not node.directory
        },
    }


@pytest.mark.parametrize("case", CASES)
def test_original_windows_archive_action(case):
    assert observe(case) == json.loads(FIXTURE.read_text())[case]


@pytest.mark.parametrize("case", READ_CASES)
def test_original_windows_archive_read(case):
    assert observe(case) == json.loads(READ_FIXTURE.read_text())[case]


def observe_read_fds(root, case, reader_module=None):
    """Use real POSIX descriptors/bytes; emulate only Windows metadata and opens."""
    module = reader_module or coding
    archive = root / "archive"
    archive.mkdir()
    manifest = json.loads((FIXTURE.parent / "private_data_v1.json").read_text())[
        "manifest_utf8"
    ].encode()
    (archive / "manifest.json").write_bytes(b"\xff" if case == "bad_utf8" else manifest)
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    children = set()
    read_started = False
    closed = []

    class OS:
        def __getattr__(self, name):
            return getattr(os, name)

        def fstat(self, descriptor):
            value = os.fstat(descriptor)
            fields = {
                name: getattr(value, name)
                for name in dir(value)
                if name.startswith("st_")
            }
            fields["st_file_attributes"] = (
                0x10
                if stat.S_ISDIR(value.st_mode)
                else (
                    0x2
                    if case == "before_attributes"
                    or (case == "after_attributes" and read_started)
                    else 0x20
                )
            )
            return SimpleNamespace(**fields)

        def read(self, descriptor, maximum):
            nonlocal read_started
            read_started = True
            if case == "read_failure":
                raise OSError("injected manifest read failure")
            return os.read(descriptor, maximum)

        def close(self, descriptor):
            closed.append(
                "directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
            )
            os.close(descriptor)
            children.remove(descriptor)

    class ACL:
        def validate(self, *_args, **_kwargs):
            pass

    def directory(name, *, dir_fd=None, **_):
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=dir_fd)
        children.add(descriptor)
        return descriptor

    def regular(parent_fd, name, **_):
        descriptor = os.open(name, os.O_RDONLY, dir_fd=parent_fd)
        children.add(descriptor)
        return descriptor

    try:
        with ExitStack() as stack:
            for target in (module, action, native, _file_consumption):
                # The current Code reader delegates OS work; archived readers
                # and the actual native owners still receive the same port.
                if target is not module or hasattr(target, "os"):
                    stack.enter_context(patch.object(target, "os", OS()))
                if target is _file_consumption:
                    continue
                stack.enter_context(
                    patch.object(
                        target, "open_windows_directory", directory, create=True
                    )
                )
                stack.enter_context(
                    patch.object(
                        target, "open_windows_regular_file_at", regular, create=True
                    )
                )
                stack.enter_context(
                    patch.object(
                        target,
                        "windows_regular_file_stream_names",
                        lambda _: ("::$DATA",),
                        create=True,
                    )
                )
            try:
                receipt, source = module._read_archive_manifest(
                    parent, "archive", ACL()
                )
                result = {
                    "source_matches": receipt.source_target_id == source.target_id
                }
            except Exception as error:
                result = {"error": type(error).__name__, "message": str(error)}
        return {
            **result,
            "parent_alive": stat.S_ISDIR(os.fstat(parent).st_mode),
            "open_children": len(children),
            "closed": closed,
        }
    finally:
        for descriptor in children:
            os.close(descriptor)
        os.close(parent)


@pytest.mark.parametrize("case", FD_CASES)
def test_manifest_releases_real_children_and_borrows_parent(case, tmp_path):
    assert observe_read_fds(tmp_path, case) == json.loads(FD_FIXTURE.read_text())[case]
