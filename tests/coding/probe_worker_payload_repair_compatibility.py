"""Original fixed repair profiles: named staging debt, exact bytes, and read failures."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

import loushang.coding.package_product_worker_payload as payload
import loushang.coding.package_product_worker_registered_payload_repair as registered

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux Worker repair profiles"
)
KINDS = ("empty", "complete", "unmarked", "registered")
CASES = (
    "fresh",
    "repeat",
    "before-link",
    "after-link",
    "after-root-sync",
    "bad-mode",
    "changed-body",
    "single-link-staging",
    "short-read",
    "zero-write",
)
ATTEMPT = "a" * 32


def sample(kind):
    plan = payload.CodingWorkerPayloadDebtPlanV1(
        attempt_id=ATTEMPT,
        entrypoint="bin/worker",
        payload_digest="b" * 64,
        payload_size=4,
        receipt_fingerprint="c" * 64,
        stage_device=3,
        stage_inode=7,
    )
    if kind == "empty":
        return payload.CodingWorkerEmptyPayloadDebtPlanV1(ATTEMPT, 3, 7)
    if kind == "complete":
        return plan, "d" * 64
    if kind == "unmarked":
        return payload.CodingWorkerUnmarkedPayloadDebtReviewV1(
            ATTEMPT,
            3,
            7,
            (
                payload.CodingWorkerUnmarkedPayloadMemberV1(
                    "worker",
                    "file",
                    3,
                    8,
                    0o600,
                    4,
                    "b" * 64,
                ),
            ),
        )
    return registered.CodingWorkerRegisteredPayloadRepairIntentV1(
        plan,
        "d" * 64,
        "e" * 64,
        "f" * 64,
        "1" * 64,
        "host",
        "boot",
        0,
    )


def profile(kind):
    if kind == "registered":
        return registered._names, registered._read_intent, registered._publish_intent
    return (
        getattr(payload, f"_{kind}_repair_names"),
        getattr(payload, f"_read_{kind}_repair_intent"),
        getattr(payload, f"_publish_{kind}_repair_intent"),
    )


def observe_repair(kind, case, root, patch):
    root.chmod(0o700)
    names, read, publish = profile(kind)
    expected = sample(kind)
    name, staged = names(ATTEMPT)
    fd = os.open(root, payload._DIR_FLAGS)
    trace = []
    fired = False
    original_link, original_sync, original_unlink = os.link, os.fsync, os.unlink
    original_read = os.read
    args = expected if kind == "complete" else (expected,)
    try:
        if case in {
            "repeat",
            "bad-mode",
            "changed-body",
            "single-link-staging",
            "short-read",
        }:
            publish(fd, *args)
        if case == "bad-mode":
            (root / name).chmod(0o644)
        elif case == "changed-body":
            with (root / name).open("ab") as out:
                out.write(b" ")
        elif case == "single-link-staging":
            (root / staged).write_bytes(b"foreign")
            (root / staged).chmod(0o600)

        def link(source, target, **kwargs):
            nonlocal fired
            trace.append(["link", source, target])
            if case == "before-link":
                fired = True
                raise OSError("pause before link")
            result = original_link(source, target, **kwargs)
            if case == "after-link":
                fired = True
                raise OSError("link happened; acknowledgement lost")
            return result

        def sync(descriptor):
            nonlocal fired
            trace.append(
                [
                    "sync",
                    "directory"
                    if stat.S_ISDIR(os.fstat(descriptor).st_mode)
                    else "file",
                ]
            )
            result = original_sync(descriptor)
            if case == "after-root-sync" and descriptor == fd:
                fired = True
                raise OSError("root sync happened; acknowledgement lost")
            return result

        def unlink(name, **kwargs):
            trace.append(["unlink", name])
            return original_unlink(name, **kwargs)

        def short(descriptor, size):
            nonlocal fired
            fired = True
            return original_read(descriptor, min(size, 1))

        def zero(descriptor, view):
            nonlocal fired
            fired = True
            return 0

        result = None
        error = None
        with patch.context() as faults:
            faults.setattr(os, "link", link)
            faults.setattr(os, "fsync", sync)
            faults.setattr(os, "unlink", unlink)
            if case == "short-read":
                faults.setattr(os, "read", short)
            if case == "zero-write":
                faults.setattr(os, "write", zero)
            try:
                if case in {
                    "bad-mode",
                    "changed-body",
                    "single-link-staging",
                    "short-read",
                }:
                    result = read(fd, ATTEMPT) == expected
                else:
                    publish(fd, *args)
                    result = read(fd, ATTEMPT) == expected
            except Exception as exc:
                error = []
                while exc is not None:
                    error.append(
                        [
                            type(exc).__name__,
                            str(exc),
                            getattr(exc, "code", None),
                            exc.__suppress_context__,
                        ]
                    )
                    exc = exc.__cause__
        pending = {
            p.name: dict(
                mode=stat.S_IMODE(p.stat().st_mode),
                links=p.stat().st_nlink,
                bytes=p.read_bytes().hex(),
            )
            for p in sorted(root.iterdir())
        }
        retry = None
        if case in {"before-link", "after-link", "after-root-sync"}:
            publish(fd, *args)
            retry = read(fd, ATTEMPT) == expected
        if case in {
            "before-link",
            "after-link",
            "after-root-sync",
            "short-read",
            "zero-write",
        }:
            assert fired, "the named fault must have fired"
        final = {
            p.name: dict(
                mode=stat.S_IMODE(p.stat().st_mode),
                links=p.stat().st_nlink,
                digest=hashlib.sha256(p.read_bytes()).hexdigest(),
            )
            for p in sorted(root.iterdir())
        }
        return dict(
            trace=trace,
            result=result,
            error=error,
            pending=pending,
            retry=retry,
            final=final,
        )
    finally:
        os.close(fd)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", CASES)
def test_original_payload_repair(kind, case, tmp_path, monkeypatch):
    expected = json.loads(
        (Path(__file__).parent / "fixtures/worker_payload_repair_v1.json").read_text()
    )
    assert (
        observe_repair(kind, case, tmp_path, monkeypatch) == expected[kind + ":" + case]
    )
