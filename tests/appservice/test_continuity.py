from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from pathlib import Path

import pytest

from loushang.appserver.protocol import SessionIdentityV1, SessionScopeV1
from loushang.appservice import (
    APPLICATION_CONTINUITY_VERSION,
    MAX_CONTINUITY_RECORD_BYTES,
    ApplicationContinuityError,
    ApplicationContinuityErrorCodeV1,
    ApplicationContinuityRecordV1,
    JsonFileApplicationContinuityStoreV1,
    MuxMemberContinuityV1,
    MuxSpaceContinuityV1,
    decode_application_continuity_record,
    encode_application_continuity_record,
)

_FINGERPRINT = "a" * 64


def _async_test(
    function: Callable[..., Awaitable[None]],
) -> Callable[..., None]:
    @wraps(function)
    def wrapper(*args: object, **kwargs: object) -> None:
        asyncio.run(function(*args, **kwargs))

    return wrapper


def _record(
    *,
    application_id: str = "coding.default",
    product_id: str = "coding",
    revision: int = 1,
    session_id: str = "session-1",
) -> ApplicationContinuityRecordV1:
    identity = SessionIdentityV1(
        product_id,
        "continuity-1",
        session_id,
        SessionScopeV1.CWD,
        _FINGERPRINT,
    )
    return ApplicationContinuityRecordV1(
        application_id=application_id,
        product_id=product_id,
        record_revision=revision,
        mux_spaces=(
            MuxSpaceContinuityV1(
                "mux-1",
                "dev",
                2,
                (MuxMemberContinuityV1("member-1", "Session", 1, identity),),
            ),
        ),
    )


def test_G13_STRICT_RECORD_round_trips_canonical_values() -> None:
    record = _record()

    encoded = encode_application_continuity_record(record)

    assert decode_application_continuity_record(encoded) == record
    assert json.loads(encoded)["contractVersion"] == APPLICATION_CONTINUITY_VERSION
    assert b"generation" not in encoded
    for forbidden in (b"attachment", b"cursor", b"turn", b"approval", b"path"):
        assert forbidden not in encoded.lower()


@pytest.mark.parametrize(
    "payload",
    (
        b"{}",
        b'{"applicationId":"a","applicationId":"b"}',
        b'{"applicationId":"../escape"}',
        b'{"recordRevision":NaN}',
        b"[1]",
        b"\xff",
        b"x" * (MAX_CONTINUITY_RECORD_BYTES + 1),
    ),
    ids=(
        "empty",
        "duplicate-key",
        "unsafe-application-id",
        "non-finite-number",
        "non-object-root",
        "invalid-utf8",
        "oversized",
    ),
)
def test_G13_STRICT_RECORD_rejects_unbounded_unknown_or_duplicate_input(
    payload: bytes,
) -> None:
    with pytest.raises(ApplicationContinuityError) as caught:
        decode_application_continuity_record(payload)

    assert caught.value.code is ApplicationContinuityErrorCodeV1.CORRUPT
    assert str(caught.value) == "continuity_corrupt"


def test_G13_STRICT_RECORD_rejects_cross_mux_session_alias() -> None:
    member = _record().mux_spaces[0].members[0]
    with pytest.raises(ValueError, match="several MuxSpaces"):
        ApplicationContinuityRecordV1(
            "coding.default",
            "coding",
            1,
            (
                MuxSpaceContinuityV1("mux-1", "one", 1, (member,)),
                MuxSpaceContinuityV1(
                    "mux-2",
                    "two",
                    1,
                    (MuxMemberContinuityV1("member-2", "Other", 1, member.session),),
                ),
            ),
        )


@_async_test
async def test_G13_LEASE_FENCE_excludes_a_second_live_owner(tmp_path: Path) -> None:
    root = tmp_path / "continuity"
    first_store = JsonFileApplicationContinuityStoreV1(root)
    second_store = JsonFileApplicationContinuityStoreV1(root)
    first = await first_store.acquire(
        application_id="coding.default",
        owner_epoch="epoch-1",
    )

    with pytest.raises(ApplicationContinuityError) as caught:
        await second_store.acquire(
            application_id="coding.default",
            owner_epoch="epoch-2",
        )
    assert caught.value.code is ApplicationContinuityErrorCodeV1.LOCKED

    await first.close()
    second = await second_store.acquire(
        application_id="coding.default",
        owner_epoch="epoch-2",
    )
    await second.close()


@_async_test
async def test_G13_LEASE_FENCE_commits_by_exact_revision_and_deletes(
    tmp_path: Path,
) -> None:
    store = JsonFileApplicationContinuityStoreV1(tmp_path / "continuity")
    lease = await store.acquire(
        application_id="coding.default",
        owner_epoch="epoch-1",
    )
    first = _record()
    await lease.commit(expected_revision=None, record=first)
    assert await lease.load() == first

    with pytest.raises(ApplicationContinuityError) as caught:
        await lease.commit(expected_revision=None, record=first)
    assert caught.value.code is ApplicationContinuityErrorCodeV1.CONFLICT

    second = _record(revision=2)
    await lease.commit(expected_revision=1, record=second)
    with pytest.raises(ValueError, match="next revision"):
        await lease.commit(expected_revision=2, record=_record(revision=4))
    await lease.delete(expected_revision=2)
    assert await lease.load() is None
    await lease.close()

    with pytest.raises(ApplicationContinuityError) as closed:
        await lease.load()
    assert closed.value.code is ApplicationContinuityErrorCodeV1.CLOSED


@_async_test
async def test_G13_MULTI_RECORD_keeps_application_keys_isolated(
    tmp_path: Path,
) -> None:
    store = JsonFileApplicationContinuityStoreV1(tmp_path / "continuity")
    first = await store.acquire(application_id="coding.one", owner_epoch="one")
    second = await store.acquire(application_id="slides.one", owner_epoch="two")
    await first.commit(
        expected_revision=None,
        record=_record(application_id="coding.one"),
    )
    await second.commit(
        expected_revision=None,
        record=_record(
            application_id="slides.one",
            product_id="slides",
            session_id="session-2",
        ),
    )

    summaries = await store.list_applications()

    assert tuple(item.application_id for item in summaries) == (
        "coding.one",
        "slides.one",
    )
    assert tuple(item.product_id for item in summaries) == ("coding", "slides")
    await first.close()
    await second.close()


@_async_test
async def test_G13_BOUNDED_PRIVATE_STORAGE_uses_private_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "continuity"
    store = JsonFileApplicationContinuityStoreV1(root)
    lease = await store.acquire(
        application_id="coding.default",
        owner_epoch="epoch-1",
    )
    await lease.commit(expected_revision=None, record=_record())

    if os.name != "nt":
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE((root / "coding.default.json").stat().st_mode) == 0o600
        assert stat.S_IMODE((root / "coding.default.lock").stat().st_mode) == 0o600
    assert not tuple(root.glob("*.tmp"))
    await lease.close()


@_async_test
async def test_G13_BOUNDED_PRIVATE_STORAGE_preserves_corrupt_record(
    tmp_path: Path,
) -> None:
    root = tmp_path / "continuity"
    root.mkdir(mode=0o700)
    record_path = root / "coding.default.json"
    record_path.write_bytes(b"{broken")
    if os.name != "nt":
        record_path.chmod(0o600)
    store = JsonFileApplicationContinuityStoreV1(root)
    lease = await store.acquire(
        application_id="coding.default",
        owner_epoch="epoch-1",
    )

    with pytest.raises(ApplicationContinuityError) as caught:
        await lease.load()

    assert caught.value.code is ApplicationContinuityErrorCodeV1.CORRUPT
    assert record_path.read_bytes() == b"{broken"
    await lease.close()


@_async_test
async def test_G13_BOUNDED_PRIVATE_STORAGE_rejects_symlinked_record(
    tmp_path: Path,
) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    root = tmp_path / "continuity"
    root.mkdir(mode=0o700)
    target = tmp_path / "outside.json"
    target.write_bytes(encode_application_continuity_record(_record()))
    (root / "coding.default.json").symlink_to(target)
    store = JsonFileApplicationContinuityStoreV1(root)
    lease = await store.acquire(
        application_id="coding.default",
        owner_epoch="epoch-1",
    )

    with pytest.raises(ApplicationContinuityError) as caught:
        await lease.load()

    assert caught.value.code is ApplicationContinuityErrorCodeV1.UNAVAILABLE
    await lease.close()


@_async_test
async def test_G13_LEASE_FENCE_process_death_releases_the_os_lock(
    tmp_path: Path,
) -> None:
    root = tmp_path / "continuity"
    ready = tmp_path / "child-ready"
    source = """
import asyncio
import sys
from pathlib import Path
from loushang.appservice import JsonFileApplicationContinuityStoreV1

async def hold():
    store = JsonFileApplicationContinuityStoreV1(Path(sys.argv[1]))
    lease = await store.acquire(application_id="coding.default", owner_epoch="child")
    Path(sys.argv[2]).write_bytes(b"ready")
    await asyncio.Event().wait()
    await lease.close()

asyncio.run(hold())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", source, str(root), str(ready)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.is_file():
            if process.poll() is not None:
                assert process.stderr is not None
                pytest.fail(
                    "continuity lease child exited before readiness: "
                    + process.stderr.read().decode("utf-8", errors="replace")
                )
            if time.monotonic() >= deadline:
                process.kill()
                process.wait(timeout=10)
                assert process.stderr is not None
                pytest.fail(
                    "continuity lease child did not become ready: "
                    + process.stderr.read().decode("utf-8", errors="replace")
                )
            time.sleep(0.02)
        process.kill()
        assert process.wait(timeout=10) != 0

        store = JsonFileApplicationContinuityStoreV1(root)
        release_deadline = time.monotonic() + 5
        while True:
            try:
                lease = await store.acquire(
                    application_id="coding.default",
                    owner_epoch="parent",
                )
                break
            except ApplicationContinuityError as error:
                if (
                    error.code is not ApplicationContinuityErrorCodeV1.LOCKED
                    or time.monotonic() >= release_deadline
                ):
                    raise
                time.sleep(0.02)
        await lease.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


@_async_test
async def test_G13_BOUNDED_PRIVATE_STORAGE_failed_replace_keeps_old_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "continuity"
    store = JsonFileApplicationContinuityStoreV1(root)
    lease = await store.acquire(
        application_id="coding.default",
        owner_epoch="epoch-1",
    )
    first = _record()
    await lease.commit(expected_revision=None, record=first)

    def fail_replace(source: object, target: object) -> None:
        del source, target
        raise OSError("hidden")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(ApplicationContinuityError) as caught:
        await lease.commit(expected_revision=1, record=_record(revision=2))

    assert caught.value.code is ApplicationContinuityErrorCodeV1.UNAVAILABLE
    assert await lease.load() == first
    assert not tuple(root.glob("*.tmp"))
    await lease.close()
