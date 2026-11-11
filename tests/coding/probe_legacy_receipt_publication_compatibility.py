"""Original publication outcomes; inert codec data never grants Product authority."""
from __future__ import annotations

import errno
import importlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.journal import _rooted_io

FIXTURE = Path(__file__).with_name("fixtures") / "legacy_receipt_publication_v1.json"
KINDS = ("disabled", "builtin", "removed")
SCENARIOS = (
    "success", "exists", "unsafe_parent", "write_failure", "cleanup_failure",
    "post_permission", "post_missing", "post_identity_and_missing", "post_identity",
)
EXTRA_SCENARIOS = (
    "encode_nan", "encode_surrogate", "write_and_cleanup_failure",
    "write_and_close_failure", "cleanup_and_close_failure", "close_failure",
)
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="original Linux receipt IO")


def observe(kind, scenario, root, monkeypatch):
    module = importlib.import_module(f"loushang.coding.package_legacy_{kind}_acceptance")
    root.mkdir(mode=0o700)
    path = root / "acceptance.jsonl"
    # Exercise the original codec projection with inert Unicode/nested values.
    # Full first-B authority/review decisions are covered by original integration tests.
    label = float("nan") if scenario == "encode_nan" else (
        "\ud800" if scenario == "encode_surrogate" else "旧版é"
    )
    record = SimpleNamespace(
        acceptance_id="a" * 64, acceptance_version=1,
        review=SimpleNamespace(to_dict=lambda: {"label": label, "nested": [1, True, None]}),
    )
    trace = []
    outer_fds = []
    cleaned = False
    original_open, original_close, original_fstat = os.open, os.close, os.fstat
    original_lstat = Path.lstat
    original_cleanup = _rooted_io.RootedFileIO.cleanup
    original_write = _rooted_io.RootedFile.atomic_write

    def opened(name, flags, mode=0o777, *, dir_fd=None):
        fd = original_open(name, flags, mode, dir_fd=dir_fd)
        if Path(name) == root:
            outer_fds.append(fd)
            trace.append("parent_open")
        return fd

    def closed(fd):
        if fd in outer_fds:
            trace.append("parent_close")
            if scenario in {"close_failure", "write_and_close_failure", "cleanup_and_close_failure"}:
                original_close(fd)
                raise OSError(errno.EIO, "injected parent close failure")
        return original_close(fd)

    def fstat(fd):
        value = original_fstat(fd)
        if fd in outer_fds:
            trace.append("parent_fstat_after" if cleaned else "parent_fstat")
            if cleaned and scenario in {"post_identity", "post_identity_and_missing"}:
                fields = list(value)
                fields[1] += 1
                return os.stat_result(fields)
        return value

    def lstat(self, *args, **kwargs):
        if self == root:
            trace.append("parent_lstat_after" if cleaned else "parent_lstat")
            if cleaned and scenario in {"post_missing", "post_identity_and_missing"}:
                raise FileNotFoundError(errno.ENOENT, "injected parent disappearance")
        return original_lstat(self, *args, **kwargs)

    def write(self, payload, *, exclusive=False):
        trace.append("atomic_write")
        assert exclusive is True
        if scenario in {"write_failure", "write_and_cleanup_failure", "write_and_close_failure"}:
            raise OSError(errno.EIO, "injected publication failure")
        return original_write(self, payload, exclusive=exclusive)

    def cleanup(self):
        nonlocal cleaned
        trace.append("cleanup")
        original_cleanup(self)
        cleaned = True
        if scenario in {"cleanup_failure", "write_and_cleanup_failure", "cleanup_and_close_failure"}:
            raise OSError(errno.EIO, "injected cleanup failure")
        if scenario == "post_permission":
            root.chmod(0o755)

    if scenario == "exists":
        path.write_bytes(b"prior receipt\n")
        path.chmod(0o600)
    if scenario == "unsafe_parent":
        root.chmod(0o755)
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", opened)
        patch.setattr(os, "close", closed)
        patch.setattr(os, "fstat", fstat)
        patch.setattr(Path, "lstat", lstat)
        patch.setattr(_rooted_io.RootedFile, "atomic_write", write)
        patch.setattr(_rooted_io.RootedFileIO, "cleanup", cleanup)
        try:
            module._write_private_acceptance(path, record)
        except BaseException as error:
            result = {"error": type(error).__name__, "message": str(error).replace(str(root), "$ROOT")}
            if scenario in EXTRA_SCENARIOS:
                contexts = []
                context = error.__context__
                while context is not None:
                    contexts.append([type(context).__name__, str(context)])
                    context = context.__context__
                result["contexts"] = contexts
        else:
            result = {"error": None}
    leaked = []
    for fd in outer_fds:
        try:
            original_fstat(fd)
        except OSError as error:
            assert error.errno == errno.EBADF
        else:
            leaked.append(fd)
            original_close(fd)
    return dict(
        result=result, trace=trace, leaked=bool(leaked),
        payload=path.read_bytes().hex() if path.exists() else None,
        files=sorted(child.name for child in root.iterdir()),
        mode=stat.S_IMODE(root.stat().st_mode),
    )


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_original_receipt_publication(kind, scenario, tmp_path, monkeypatch):
    expected = json.loads(FIXTURE.read_text())
    actual = observe(kind, scenario, tmp_path / "state", monkeypatch)
    prior = expected[f"{kind}:{scenario}"]
    # Native exclusive publication names a random staging file in EEXIST.
    # Keep raw original evidence; normalize only that nondeterministic token.
    for outcome in (actual, prior):
        message = outcome["result"].get("message")
        if message is not None:
            outcome["result"]["message"] = re.sub(
                r"(\.acceptance\.jsonl\.)[0-9a-f]{24}(\.tmp)", r"\1<TOKEN>\2", message
            )
    assert actual == prior


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("scenario", EXTRA_SCENARIOS)
def test_original_receipt_encoding_and_failure_precedence(kind, scenario, tmp_path, monkeypatch):
    expected = json.loads(FIXTURE.with_name("legacy_receipt_failures_v1.json").read_text())
    assert observe(kind, scenario, tmp_path / "state", monkeypatch) == expected[f"{kind}:{scenario}"]


def test_windows_builtin_keeps_original_jsonl_bytes(tmp_path, monkeypatch):
    module = importlib.import_module("loushang.coding.package_legacy_builtin_acceptance")
    record = SimpleNamespace(
        acceptance_id="a" * 64, acceptance_version=1,
        review=SimpleNamespace(to_dict=lambda: {"label": "旧版é", "nested": [1, True, None]}),
    )
    calls = []
    monkeypatch.setattr(module, "write_windows_private_receipt", lambda *args: calls.append(args))
    target = tmp_path / "not-published.jsonl"
    module._write_windows_builtin_acceptance(target, record)
    prior = json.loads(FIXTURE.read_text())["builtin:success"]["payload"]
    assert calls == [(target, bytes.fromhex(prior))]
    assert not target.exists()  # Encoding test; no claim of native Windows validation.
