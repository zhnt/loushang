"""Frozen native-call order over emulated primitives; not Windows platform proof."""

from __future__ import annotations

import json
import os
import shutil
import stat
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import loushang.coding.package_private_data_windows_backup as backup
import loushang.coding.package_private_data_windows_deletion_owner as deletion
import loushang.coding.package_private_data_windows_preview as preview
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
    _identity,
)
from loushang.harness.resources.packages import _file_consumption

CASES = (
    "write:new",
    "write:complete",
    "write:prefix",
    "write:empty",
    "write:conflict",
    "write:overlong",
    "write:stream",
    "write:attributes",
    "write:identity",
    "write:zero",
    "write:short",
    "write:flush",
    "read:valid",
    "read:content",
    "read:identity",
    "read:stream",
    "read:attributes",
    "read:oversized",
    "child:valid",
    "child:stream",
    "child:attributes",
    "child:identity",
    "child:acl",
    "copy:new",
    "copy:prefix",
    "copy:conflict",
    "copy:zero",
    "copy:identity",
    "remove:valid",
    "remove:content",
    "remove:stream",
    "remove:foreign",
)

CAPTURE_CASES = (
    "valid",
    "empty",
    "empty_sessions",
    "empty_session",
    "unsupported_root",
    "invalid_name",
    "late_bad_name",
    "attributes",
    "file_attributes",
    "stream",
    "file_stream",
    "identity",
    "root_identity",
    "path_identity",
    "links",
    "late_links",
    "oversized",
    "small_observed",
    "read_limit",
    "entry_limit",
    "entry_limit_one",
    "total_limit",
    "both_limits",
    "negative_file_and_cap",
    "negative_directory_and_cap",
    "file_directory",
)


def run_probe(
    case: str, root: Path, native_modules: tuple, native_io
) -> dict[str, object]:
    """Keep the frozen pre-move scenarios; call the actual current read owner."""
    operation, fault = case.split(":")
    source = root / "source"
    session = source / "sessions" / ("a" * 64)
    session.mkdir(parents=True)
    content = b"private cache"
    file = session / "cache.json"
    file.write_bytes(content)
    members = tuple(
        CodingArchPrivateDataMemberV1(
            item.relative_to(source).as_posix(),
            "directory" if item.is_dir() else "file",
            _identity(item.stat()),
            None if item.is_dir() else sha256(content).hexdigest(),
        )
        for item in (source / "sessions", session, file)
    )
    snapshot = CodingArchPrivateDataTargetSnapshotV1(
        sha256(os.fsencode(str(source))).hexdigest(), _identity(source.stat()), members
    )
    destination = root / "destination"
    destination.mkdir()
    if operation == "write" and fault != "new":
        existing = {
            "empty": b"",
            "prefix": content[:3],
            "conflict": b"incorrect",
            "overlong": content + b"extra",
            "zero": content[:3],
            "short": content[:3],
            "flush": content[:3],
        }.get(fault, content)
        (destination / "cache.json").write_bytes(existing)
    if operation == "copy" and fault in {"prefix", "conflict"}:
        output = destination / "sessions" / ("a" * 64)
        output.mkdir(parents=True)
        (output / "cache.json").write_bytes(
            content[:3] if fault == "prefix" else b"bad"
        )
    if operation in {"read", "remove"} and fault == "content":
        file.write_bytes(b"changed cache")
        os.utime(file, ns=(file.stat().st_atime_ns, members[-1].identity[4]))
    if operation == "remove" and fault == "foreign":
        (source / "unobserved").write_bytes(b"foreign")
    if operation == "capture":
        if fault == "empty":
            shutil.rmtree(source / "sessions")
        elif fault in {"empty_sessions", "empty_session"}:
            file.unlink()
            if fault == "empty_sessions":
                session.rmdir()
        elif fault == "unsupported_root":
            (source / "unobserved").write_bytes(b"foreign")
        elif fault == "invalid_name":
            session.rename(session.with_name("invalid"))
        elif fault == "late_bad_name":
            session.with_name("z-invalid").mkdir()
        elif fault == "file_directory":
            file.unlink()
            file.mkdir()

    trace: list[str] = []
    descriptors: dict[int, Path] = {}
    stat_counts: dict[Path, int] = {}

    def short(path):
        return Path(path).relative_to(root).as_posix()

    def metadata(value, path):
        fields = {
            name: getattr(value, name) for name in dir(value) if name.startswith("st_")
        }
        is_directory = stat.S_ISDIR(value.st_mode)
        fields["st_file_attributes"] = (
            0x02 if fault == "attributes" else 0x10 if is_directory else 0x20
        )
        if fault == "oversized" and not is_directory:
            fields["st_size"] = 16 * 1024 * 1024 + 1
        if fault in {"small_observed", "read_limit"} and not is_directory:
            fields["st_size"] = 1
        if fault == "file_attributes" and not is_directory:
            fields["st_file_attributes"] = 0x02
        if fault == "links" and not is_directory:
            fields["st_nlink"] = 2
        if (fault == "negative_file_and_cap" and not is_directory) or (
            fault == "negative_directory_and_cap" and path == source / "sessions"
        ):
            fields["st_mtime_ns"] = -1
        return SimpleNamespace(**fields)

    class OsView:
        def __getattr__(self, name):
            return getattr(os, name)

        def fstat(self, descriptor):
            path = descriptors[descriptor]
            trace.append("stat:" + short(path))
            stat_counts[path] = stat_counts.get(path, 0) + 1
            value = metadata(os.fstat(descriptor), path)
            if fault == "identity" and (
                operation in {"child", "copy"} or stat_counts[path] > 1
            ):
                value.st_ino += 1
            if fault == "late_links" and path == file and stat_counts[path] > 1:
                value.st_nlink = 2
            return value

        def read(self, descriptor, maximum):
            trace.append(f"read:{short(descriptors[descriptor])}:{maximum}")
            return os.read(descriptor, maximum)

        def write(self, descriptor, data):
            trace.append(f"write:{short(descriptors[descriptor])}:{len(data)}")
            if fault == "zero":
                return 0
            return os.write(descriptor, data[:2] if fault == "short" else data)

        def lseek(self, descriptor, offset, whence):
            trace.append(f"seek:{short(descriptors[descriptor])}:{offset}:{whence}")
            return os.lseek(descriptor, offset, whence)

        def dup(self, descriptor):
            trace.append("dup:" + short(descriptors[descriptor]))
            duplicate = os.dup(descriptor)
            descriptors[duplicate] = descriptors[descriptor]
            return duplicate

        def close(self, descriptor):
            trace.append("close:" + short(descriptors.pop(descriptor)))
            os.close(descriptor)

    class Acl:
        def __init__(self, *, inherit_children=False):
            self.security_descriptor = "inherited" if inherit_children else "exact"

        def __enter__(self):
            trace.append("acl-enter:" + self.security_descriptor)
            return self

        def __exit__(self, *_):
            trace.append("acl-exit:" + self.security_descriptor)

        def validate(self, descriptor, **kwargs):
            trace.append(
                f"acl:{short(descriptors[descriptor])}:{self.security_descriptor}:{kwargs}"
            )
            if fault == "acl":
                raise PermissionError("probe ACL denied")
            if (
                fault == "destination_acl"
                and descriptors[descriptor].is_relative_to(destination)
                and session in descriptors.values()
            ):
                raise PermissionError("probe destination ACL denied")

    def path_for(value, directory_fd=None):
        return (
            Path(value) if directory_fd is None else descriptors[directory_fd] / value
        )

    def open_directory(value, *, dir_fd=None, create_new=False, **_):
        path = path_for(value, dir_fd)
        trace.append(f"open-directory:{short(path)}:{create_new}")
        if create_new:
            path.mkdir()
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        descriptors[fd] = path
        return fd

    def open_file(parent, name, *, create_new, write, **_):
        path = descriptors[parent] / name
        trace.append(f"open-file:{short(path)}:{create_new}:{write}")
        flags = os.O_RDWR if write else os.O_RDONLY
        fd = os.open(path, flags | (os.O_CREAT | os.O_EXCL if create_new else 0), 0o600)
        descriptors[fd] = path
        return fd

    def open_delete(parent, name, *, directory):
        path = descriptors[parent] / name
        trace.append(f"open-delete:{short(path)}:{directory}")
        fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if directory else 0))
        descriptors[fd] = path
        return fd

    def visible(parent, name):
        path = descriptors[parent] / name
        trace.append("visible:" + short(path))
        return metadata(path.stat(), path)

    def streams(fd):
        path = descriptors[fd]
        trace.append("streams:" + short(path))
        return (
            ("::$DATA", "extra:$DATA")
            if fault == "stream" or (fault == "file_stream" and path == file)
            else ("::$DATA",)
        )

    def flush(fd):
        trace.append("flush:" + short(descriptors[fd]))
        if fault == "flush":
            raise OSError("probe flush interrupted")

    def listdir(fd):
        trace.append("list:" + short(descriptors[fd]))
        return tuple(sorted(os.listdir(fd)))

    def delete(fd, *, expected_identity, directory):
        path = descriptors[fd]
        trace.append(f"delete:{short(path)}:{directory}")
        path.rmdir() if directory else path.unlink()

    primitives = {
        "os": OsView(),
        "WindowsPrivateDirectoryAcl": Acl,
        "open_windows_directory": open_directory,
        "open_windows_regular_file_at": open_file,
        "open_windows_deletion_entry_at": open_delete,
        "windows_stat_at": visible,
        "windows_regular_file_stream_names": streams,
        "windows_directory_stream_names": streams,
        "windows_listdir_at": listdir,
        "windows_flush_file": flush,
        "windows_flush_directory": flush,
        "windows_delete_open_entry": delete,
    }
    input_fd = None
    if operation not in {"remove", "capture"}:
        input_path = (
            destination
            if operation in {"write", "copy"}
            else source
            if operation == "child"
            else session
        )
        input_fd = os.open(input_path, os.O_RDONLY | os.O_DIRECTORY)
        descriptors[input_fd] = input_path
    with ExitStack() as stack:
        if operation == "capture":
            original_lstat = Path.lstat

            def lstat(path, *args, **kwargs):
                value = original_lstat(path, *args, **kwargs)
                if path != source:
                    return value
                trace.append("lstat:" + short(path))
                result = metadata(value, path)
                if fault == "path_identity":
                    result.st_ino += 1
                return result

            stack.enter_context(patch.object(Path, "lstat", lstat))
            for name, limit in (
                (
                    "_MAX_ENTRIES",
                    0
                    if fault == "negative_directory_and_cap"
                    else 1
                    if fault == "entry_limit_one"
                    else 2,
                ),
                ("_MAX_TOTAL_BYTES", 8),
                ("_MAX_FILE_BYTES", 8),
            ):
                if (
                    (
                        name == "_MAX_ENTRIES"
                        and fault
                        in {
                            "entry_limit",
                            "entry_limit_one",
                            "both_limits",
                            "negative_file_and_cap",
                            "negative_directory_and_cap",
                        }
                    )
                    or (
                        name == "_MAX_TOTAL_BYTES"
                        and fault in {"total_limit", "both_limits"}
                    )
                    or (name == "_MAX_FILE_BYTES" and fault == "read_limit")
                ):
                    stack.enter_context(patch.object(preview, name, limit))
        for module in (*native_modules, _file_consumption):
            for name, value in primitives.items():
                if module is _file_consumption and name != "os":
                    continue
                stack.enter_context(patch.object(module, name, value, create=True))
        try:
            if operation == "write":
                value = native_io.write_or_verify_archive_file(
                    input_fd,
                    "cache.json",
                    content,
                    Acl(inherit_children=True),
                    inherited_file=True,
                )
            elif operation == "read":
                value = native_io.read_source_file(
                    input_fd, "cache.json", members[-1], Acl(inherit_children=True)
                )
            elif operation == "child":
                child_fd, _ = native_io.open_directory_child(
                    input_fd, "sessions", Acl()
                )
                OsView().close(child_fd)
                value = None
            elif operation == "copy":
                value = backup._copy_members(
                    source, snapshot, input_fd, Acl(), Acl(inherit_children=True)
                )
            elif operation == "capture":
                expected_root = (source.stat().st_dev, source.stat().st_ino)
                value = preview._capture_windows_target_snapshot(
                    source,
                    expected_root=(0, 0) if fault == "root_identity" else expected_root,
                )
                value = {
                    "root_path_matches": value.root_path_digest
                    == sha256(os.fsencode(str(source))).hexdigest(),
                    "root_identity_matches": value.root_identity
                    == _identity(source.stat()),
                    "members": [
                        [
                            member.relative_path,
                            member.kind,
                            member.identity
                            == _identity((source / member.relative_path).stat()),
                            member.identity[3] if member.kind == "file" else None,
                            member.content_sha256,
                        ]
                        for member in value.members
                    ],
                }
            else:
                value = deletion._remove_members(source, snapshot.members, snapshot)
            result = {"value": value.hex() if isinstance(value, bytes) else value}
        except Exception as error:
            result = {
                "error_type": type(error).__module__ + "." + type(error).__qualname__,
                "message": str(error),
            }
        finally:
            if input_fd is not None:
                OsView().close(input_fd)
    outstanding = [short(path) for path in descriptors.values()]
    for fd in descriptors:
        os.close(fd)
    return {
        **result,
        "trace": trace,
        "open_descriptors": outstanding,
        "files": {
            item.relative_to(root).as_posix(): item.read_bytes().hex()
            for item in sorted(root.rglob("*"))
            if item.is_file()
        },
    }


@pytest.mark.parametrize("case", CASES)
def test_original_windows_tree_io_contract(case: str, tmp_path: Path) -> None:
    from loushang.harness.resources.packages import _private_tree_windows as native

    reference = json.loads(
        (
            Path(__file__).parent / "fixtures" / "private_windows_tree_io_v1.json"
        ).read_text()
    )
    assert (
        run_probe(
            case,
            tmp_path,
            (preview, backup, deletion, native),
            preview._native_io,
        )
        == reference[case]
    )


def test_copy_releases_source_parent_when_destination_admission_fails(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.packages import _private_tree_windows as native

    result = run_probe(
        "copy:destination_acl",
        tmp_path,
        (preview, backup, deletion, native),
        preview._native_io,
    )
    assert result["error_type"] == "builtins.PermissionError"
    assert result["message"] == "probe destination ACL denied"
    assert result["open_descriptors"] == []
    assert result["files"] == {
        "source/sessions/" + "a" * 64 + "/cache.json": b"private cache".hex()
    }


@pytest.mark.parametrize("case", CAPTURE_CASES)
def test_original_windows_tree_capture_contract(case: str, tmp_path: Path) -> None:
    from loushang.harness.resources.packages import _private_tree_windows as native
    from loushang.harness.resources.packages import (
        _private_tree_windows_observation as observation,
    )

    reference = json.loads(
        (
            Path(__file__).parent / "fixtures" / "private_windows_tree_capture_v1.json"
        ).read_text()
    )
    assert (
        run_probe(
            "capture:" + case,
            tmp_path,
            (preview, backup, deletion, native, observation),
            preview._native_io,
        )
        == reference[case]
    )
