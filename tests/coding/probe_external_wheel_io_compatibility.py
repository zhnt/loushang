"""Frozen native publication outcomes; inert records confer no authorization."""

from __future__ import annotations

import errno
import importlib
import json
import os
import stat
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

KINDS = ("data", "dependency", "worker")
PUBLICATION_CASES = (
    "success",
    "existing_same",
    "existing_different",
    "stale_stage",
    "unsafe_directory",
    "short_write",
    "no_progress",
    "write_failure",
    "file_sync_failure",
    "link_failure",
    "directory_sync_failure",
    "cleanup_failure",
    "write_and_cleanup_failure",
    "verification_failure",
)
READ_CASES = (
    "success",
    "digest_mismatch",
    "unsafe_mode",
    "hardlink",
    "oversize",
    "changed_after_read",
    "missing",
    "directory",
    "metadata_failure",
)
FIXTURE = Path(__file__).with_name("fixtures") / "external_wheel_io_v1.json"
pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="original POSIX source IO"
)


def observe(kind, operation, scenario, root, monkeypatch):
    module = importlib.import_module(f"loushang.coding.package_external_{kind}_wheel")
    cls = getattr(module, f"CodingExternal{kind.title()}WheelCatalog")
    owner = cls.__new__(cls)
    root.mkdir(mode=0o700)
    owner.source_root = root
    directory = root / module._DIRECTORY if kind == "dependency" else root
    if directory != root:
        directory.mkdir(mode=0o700)
    name = "sample-1.0-py3-none-any.whl"
    path, stage = directory / name, directory / f".{name}.staging"
    body = "wheel bytes é\n".encode()
    record = SimpleNamespace(
        wheel_filename=name, artifact_digest=sha256(body).hexdigest()
    )
    trace = []
    handles = {}
    reads = 0
    original_open, original_close = os.open, os.close
    original_write, original_sync = os.write, os.fsync
    original_link, original_unlink, original_stat = os.link, os.unlink, os.fstat

    if operation == "read" or scenario.startswith("existing"):
        path.write_bytes(b"different" if scenario == "existing_different" else body)
        path.chmod(0o600)
    if scenario == "stale_stage":
        stage.write_bytes(b"stale")
    if scenario == "unsafe_directory":
        directory.chmod(0o755)
    if scenario == "digest_mismatch":
        record.artifact_digest = "0" * 64
    if scenario == "unsafe_mode":
        path.chmod(0o644)
    if scenario == "hardlink":
        os.link(path, directory / "other")
    if scenario == "oversize":
        with path.open("r+b") as stream:
            stream.truncate(module._MAX_WHEEL_BYTES + 1)
    if scenario == "missing":
        path.unlink()
    if scenario == "directory":
        path.unlink()
        path.mkdir()

    def opened(name, flags, mode=0o777, *, dir_fd=None):
        descriptor = original_open(name, flags, mode, dir_fd=dir_fd)
        label = (
            "parent"
            if Path(name) == directory
            else (
                "stage"
                if Path(name).name == stage.name
                else ("target" if Path(name).name == path.name else "ancestor")
            )
        )
        handles[descriptor] = label
        trace.append(f"open:{label}")
        return descriptor

    def closed(descriptor):
        label = handles.pop(descriptor, "unknown")
        # Old fdopen closes its descriptor in C; the new owner closes explicitly.
        # Compare native closure through the liveness invariant below instead.
        if label != "target":
            trace.append(f"close:{label}")
        return original_close(descriptor)

    def written(descriptor, pending):
        trace.append(f"write:{len(pending)}")
        if scenario == "no_progress":
            return 0
        if scenario in {"write_failure", "write_and_cleanup_failure"}:
            raise OSError(errno.EIO, "injected write failure")
        return original_write(
            descriptor, pending[:3] if scenario == "short_write" else pending
        )

    def synced(descriptor):
        label = handles.get(descriptor, "unknown")
        trace.append(f"sync:{label}")
        if (scenario == "file_sync_failure" and label == "stage") or (
            scenario == "directory_sync_failure" and label == "parent"
        ):
            raise OSError(errno.EIO, "injected sync failure")
        return original_sync(descriptor)

    def linked(*args, **kwargs):
        trace.append("link")
        if scenario == "link_failure":
            raise OSError(errno.EIO, "injected link failure")
        return original_link(*args, **kwargs)

    def unlinked(name, *, dir_fd=None):
        trace.append("unlink")
        if (
            scenario in {"cleanup_failure", "write_and_cleanup_failure"}
            and stage.exists()
        ):
            raise OSError(errno.EIO, "injected cleanup failure")
        return original_unlink(name, dir_fd=dir_fd)

    def metadata(descriptor):
        nonlocal reads
        value = original_stat(descriptor)
        if handles.get(descriptor) == "target":
            reads += 1
            trace.append("target_stat")
            if scenario == "metadata_failure":
                raise OSError(errno.EIO, "injected metadata failure")
            if scenario == "changed_after_read" and reads >= 3:
                return SimpleNamespace(
                    **{
                        field: getattr(value, field)
                        + (1 if field == "st_mtime_ns" else 0)
                        for field in (
                            "st_dev",
                            "st_ino",
                            "st_mode",
                            "st_uid",
                            "st_nlink",
                            "st_size",
                            "st_mtime_ns",
                            "st_ctime_ns",
                        )
                    }
                )
        return value

    def verify(_record):
        trace.append("verify")
        if scenario == "verification_failure":
            raise RuntimeError("injected verification failure")

    def verify_wheel(_name, _body):
        trace.append("verify_wheel_metadata")

    error = None
    with monkeypatch.context() as patch:
        for key, value in (
            ("open", opened),
            ("close", closed),
            ("write", written),
            ("fsync", synced),
            ("link", linked),
            ("unlink", unlinked),
            ("fstat", metadata),
        ):
            patch.setattr(os, key, value)
        if operation == "publish":
            patch.setattr(owner, "_verify_controlled", verify)
        elif kind == "dependency":
            patch.setattr(module, "_verify_wheel_body", verify_wheel)
        try:
            if operation == "publish":
                owner._publish_controlled(record, body)
            else:
                owner._verify_controlled(record)
        except Exception as exc:
            error = [type(exc).__name__, str(exc).replace(str(root), "<root>")]

    live = []
    for descriptor, label in handles.items():
        try:
            original_stat(descriptor)
        except OSError as exc:
            assert exc.errno == errno.EBADF
        else:
            live.append(label)
            original_close(descriptor)
    files = {}
    for target in sorted(directory.iterdir()):
        if target.is_file():
            files[target.name] = {
                "size": target.stat().st_size,
                "mode": stat.S_IMODE(target.stat().st_mode),
                "digest": sha256(target.read_bytes()).hexdigest(),
            }
    return {"error": error, "trace": trace, "files": files, "live_owned_fds": live}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("scenario", PUBLICATION_CASES)
def test_original_publication_outcome(kind, scenario, tmp_path, monkeypatch):
    expected = json.loads(FIXTURE.read_text())[f"{kind}:publish:{scenario}"]
    assert normalize(
        observe(kind, "publish", scenario, tmp_path / "source", monkeypatch)
    ) == normalize(expected)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("scenario", READ_CASES)
def test_original_controlled_read_outcome(kind, scenario, tmp_path, monkeypatch):
    expected = json.loads(FIXTURE.read_text())[f"{kind}:read:{scenario}"]
    assert normalize(
        observe(kind, "read", scenario, tmp_path / "source", monkeypatch)
    ) == normalize(expected)


def normalize(observation):
    # The frozen probe used a shallow /tmp root; RunLease uses a deeper disk root.
    # Ignore only ancestor traversal count on both sides, retaining the raw fixture.
    return {
        **observation,
        "trace": [
            event for event in observation["trace"] if not event.endswith(":ancestor")
        ],
    }


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("same_bytes", [False, True])
def test_existing_target_is_verified_after_staging_unlinked(
    kind,
    same_bytes,
    tmp_path,
    monkeypatch,
):
    module = importlib.import_module(f"loushang.coding.package_external_{kind}_wheel")
    cls = getattr(module, f"CodingExternal{kind.title()}WheelCatalog")
    owner = cls.__new__(cls)
    root = tmp_path / "source"
    root.mkdir(mode=0o700)
    owner.source_root = root
    directory = root / module._DIRECTORY if kind == "dependency" else root
    if directory != root:
        directory.mkdir(mode=0o700)
    name, body = "sample-1.0-py3-none-any.whl", b"original bytes"
    target = directory / name
    target.write_bytes(body if same_bytes else b"preexisting different bytes")
    target.chmod(0o600)
    record = SimpleNamespace(
        wheel_filename=name, artifact_digest=sha256(body).hexdigest()
    )
    if kind == "dependency":
        # Wheel metadata is domain policy, tested by the original catalog suite.
        monkeypatch.setattr(module, "_verify_wheel_body", lambda *_: None)
    if same_bytes:
        owner._publish_controlled(record, body)
    else:
        error = getattr(module, f"CodingExternal{kind.title()}WheelError")
        with pytest.raises(error, match="bytes changed"):
            owner._publish_controlled(record, body)
    assert target.read_bytes() == (
        body if same_bytes else b"preexisting different bytes"
    )
    assert target.stat().st_nlink == 1
    assert not (directory / f".{name}.staging").exists()
