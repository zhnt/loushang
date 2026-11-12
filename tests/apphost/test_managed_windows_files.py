"""Run managed file admission and publication against native Windows handles."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows rooted file operations")


def test_windows_managed_directory_publishes_and_reopens(tmp_path):
    root = tmp_path / "apphost" / "records"
    owner = PrivateManagedDirectory(root, create=True, create_parents=True)
    try:
        with owner.lock("control.lock", create=True):
            owner.write("service.json", b"first", expected=None)
            previous = owner.read("service.json")
            assert previous is not None
            owner.write("service.json", b"second", expected=previous)
            with pytest.raises(ManagedStorageError, match="conflict"):
                owner.write("service.json", b"stale", expected=previous)
        assert set(owner.names(limit=2)) == {"control.lock", "service.json"}
    finally:
        owner.close()

    reopened = PrivateManagedDirectory(root)
    try:
        record = reopened.read("service.json")
        assert record is not None
        assert record.content == b"second"
        assert record.identity != previous.identity
    finally:
        reopened.close()


def test_windows_managed_directory_rejects_public_leaf(tmp_path):
    root = tmp_path / "records"
    root.mkdir()
    with pytest.raises(ManagedStorageError, match="unavailable"):
        PrivateManagedDirectory(root)


def test_windows_managed_directory_uses_one_stable_lock(tmp_path):
    root = tmp_path / "records"
    owner = PrivateManagedDirectory(root, create=True)
    other = PrivateManagedDirectory(root)
    try:
        with owner.lock("control.lock", create=True):
            with pytest.raises(ManagedStorageError, match="busy"), other.lock("control.lock"):
                pytest.fail("Second owner acquired the live lock")
        with other.lock("control.lock"):
            assert os.stat(root / "control.lock").st_size == 0
    finally:
        other.close()
        owner.close()


def test_windows_managed_data_append_isolate_and_remove(tmp_path):
    owner = PrivateManagedDirectory(tmp_path / "records", create=True)
    try:
        with owner.lock("control.lock", create=True):
            first = owner.append_data("output.log", b"alpha", expected=None, capacity=32)
            after = owner.append_data("output.log", b" beta", expected=first, capacity=32)
            assert after.tail == b"alpha beta"
            isolated = owner.isolate_data("output.log", "removed-output", expected=after, capacity=32)
            assert isolated.identity == after.identity
            assert owner.data_snapshot("output.log", capacity=32) is None
            removal = owner.prepare_data_removal(
                "removed-output", "removed-expired", expected=isolated, capacity=32,
            )
            owner.remove_data(removal)
            assert owner.data_snapshot("removed-expired", capacity=32) is None
    finally:
        owner.close()


def test_windows_managed_file_rejects_extra_stream_and_hardlink(tmp_path):
    root = tmp_path / "records"
    owner = PrivateManagedDirectory(root, create=True)
    try:
        with owner.lock("control.lock", create=True):
            owner.write("service.json", b"record", expected=None)
        record = root / "service.json"
        extra_stream = root / "service.json:extra"
        extra_stream.write_bytes(b"unexpected")
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.read(record.name)
        extra_stream.unlink()
        link = root / "alias.json"
        os.link(record, link)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner.read(record.name)
    finally:
        owner.close()


def test_windows_managed_directory_rejects_junction_ancestors(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = tmp_path / "junction"
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/j", str(junction), str(outside)],
        check=True, capture_output=True,
    )
    try:
        with pytest.raises(ManagedStorageError, match="unavailable"):
            PrivateManagedDirectory(junction / "records", create=True, create_parents=True)
        assert not (outside / "records").exists()
    finally:
        junction.rmdir()
