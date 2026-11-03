from __future__ import annotations

import asyncio
import os
import sys

import pytest

from loushang.harness.transcript import ProductTranscriptSession
from loushang.harness.transcript import session_factory as module
from loushang.harness.transcript.session_catalog import (
    session_file_authority_fingerprint,
)

from .test_owned_bundle_import import bundle
from .test_owned_session_factory import factory, new
from .test_writer_lease import TranscriptWriterError
from .test_writer_root_binding import tree

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned import")


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("fault", ["stale", "during_read", "after_freeze"])
def test_import_source_fingerprint_binds_actual_frozen_bytes(tmp_path, monkeypatch, archive, fault):
    async def scenario():
        zipped, target = await bundle(tmp_path)
        source = zipped if archive else next((tmp_path / "source/sessions").glob("*.jsonl"))
        fingerprint = session_file_authority_fingerprint(source)
        selected = factory()
        before = tree(target.parent)
        read = module._read_stable_regular_file
        native_read = os.read
        reads = []
        changed = []

        def replace_source():
            source.rename(source.with_suffix(".original"))
            source.symlink_to(tmp_path / "untrusted-missing-source")
            changed.append(True)

        def frozen(*args, **kwargs):
            reads.append(True)
            result = read(*args, **kwargs)
            if fault == "after_freeze":
                replace_source()
            return result

        def changing_read(fd, count):
            result = native_read(fd, count)
            if fault == "during_read" and not changed:
                replace_source()
            return result

        session = None
        try:
            if fault == "stale":
                replace_source()
            with monkeypatch.context() as patch:
                patch.setattr(module, "_read_stable_regular_file", frozen)
                if fault == "during_read":
                    patch.setattr(os, "read", changing_read)
                if fault == "after_freeze":
                    session = await selected.import_transcript(
                        source, session_dir=target, expected_source_fingerprint=fingerprint,
                    )
                else:
                    with pytest.raises(OSError):
                        await selected.import_transcript(
                            source, session_dir=target, expected_source_fingerprint=fingerprint,
                        )
            assert len(reads) == 1
            assert changed
            if session is None:
                assert tree(target.parent) == before
                assert not selected.pending_preparations
            else:
                context = ProductTranscriptSession(lifecycle_session=session).build_session_context()
                assert context.messages[0].content[0].data == "aGVsbG8="
                assert session.session_blob_health[0].state == "available"
        finally:
            if session is not None:
                await session.dispose()
            await selected.close()

    asyncio.run(scenario())


def test_import_cannot_recreate_a_known_missing_store_root(tmp_path):
    async def scenario():
        source, target = await bundle(tmp_path, images=False)
        selected = factory(store_state_root=tmp_path / "state/session-stores")
        seed = await new(selected, target, "existing-store")
        await seed.dispose()
        target.rename(target.with_name("retained-old-store"))
        try:
            with pytest.raises(TranscriptWriterError):
                await selected.import_transcript(source, session_dir=target)
            assert not target.exists()
            assert not selected.pending_preparations
        finally:
            await selected.close()

    asyncio.run(scenario())
