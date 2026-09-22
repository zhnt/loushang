from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager

import pytest

from loushang.ai.types import ImagePart
from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.transcript import ProductTranscriptSession
from loushang.harness.transcript import product_session as product_module
from loushang.harness.transcript.model_input_blobs import SessionModelInputBlobCodec
from loushang.harness.transcript.writer_lease import TranscriptWriterError

from .test_runtime_profile import _runtime
from .test_writer_images import message, prepare

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned hydration")


def setup(root):
    root.mkdir(mode=0o700)
    runtime = _runtime("coding")
    return prepare(root, runtime, runtime.bind_lifecycle_owned)[0]


def logical_image():
    return {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"}


def invoke(session, codec, action):
    if action == "context":
        return session.build_session_context()
    if action == "new_codec":
        return session._model_input_binary_codec(active_only=True)
    if action == "hydrate":
        return codec.hydrate_mapping({})
    return codec.externalize_mapping({})


@pytest.mark.parametrize("action", ["context", "new_codec", "hydrate", "externalize"])
def test_closed_owned_consumers_reject_even_without_images(tmp_path, monkeypatch, action):
    async def scenario():
        owner = setup(tmp_path / "sessions")
        session = ProductTranscriptSession(lifecycle_session=await owner.create())
        codec = session._model_input_binary_codec(active_only=True)
        await owner.dispose()

        def forbidden(*args, **kwargs):
            raise AssertionError("closed consumer accessed native storage")

        monkeypatch.setattr(product_module, "SessionBlobStore", forbidden)
        monkeypatch.setattr(owner, "_check_writers", forbidden)
        with pytest.raises(TranscriptWriterError, match="closed"):
            invoke(session, codec, action)
        assert owner._active_io == 0 and owner._io_drained.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["context", "codec"])
def test_hydration_uses_original_tree_after_admission(tmp_path, monkeypatch, action):
    async def scenario():
        data = tmp_path / "data"
        data.mkdir(mode=0o700)
        owner = setup(data / "sessions")
        session = ProductTranscriptSession(lifecycle_session=await owner.create())
        try:
            await session.append_message(message())
            codec = session._model_input_binary_codec(active_only=True)
            projected = codec.externalize_mapping(logical_image())
            assert projected.replacement_count == 1
            check = owner._check_writers

            def swap_after_check():
                check()
                data.rename(tmp_path / "original")
                data.mkdir(mode=0o700)
                (data / "sentinel").write_bytes(b"replacement")

            with monkeypatch.context() as patch:
                patch.setattr(owner, "_check_writers", swap_after_check)
                if action == "context":
                    context = session.build_session_context()
                    assert context.messages[-1].content == [
                        ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")
                    ]
                else:
                    assert codec.hydrate_mapping(projected.value) == logical_image()
            assert tuple(path.name for path in data.iterdir()) == ("sentinel",)
            assert (data / "sentinel").read_bytes() == b"replacement"
            assert owner._active_io == 0
        finally:
            await owner.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("where", ["thread", "other_loop", "no_loop"])
def test_owned_sync_consumers_reject_wrong_execution_context(tmp_path, monkeypatch, where):
    owner_loop = asyncio.new_event_loop()
    owner = setup(tmp_path / "sessions")

    async def create():
        session = ProductTranscriptSession(lifecycle_session=await owner.create())
        return session, session._model_input_binary_codec(active_only=True)

    session, codec = owner_loop.run_until_complete(create())

    def reject():
        for action in ("context", "new_codec", "hydrate", "externalize"):
            with pytest.raises(RuntimeError):
                invoke(session, codec, action)
        assert owner._active_io == 0

    async def call():
        reject()

    async def in_thread():
        await asyncio.to_thread(reject)

    def forbidden(*args, **kwargs):
        raise AssertionError("wrong execution context reached storage")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner, "_check_writers", forbidden)
            patch.setattr(product_module, "SessionBlobStore", forbidden)
            if where == "no_loop":
                reject()
            elif where == "other_loop":
                asyncio.run(call())
            else:
                owner_loop.run_until_complete(in_thread())
    finally:
        owner_loop.run_until_complete(owner.dispose())
        owner_loop.close()


def test_sync_scope_checks_and_nested_errors_drain(tmp_path, monkeypatch):
    async def scenario():
        owner = setup(tmp_path / "sessions")
        lifecycle = await owner.create()
        session = ProductTranscriptSession(lifecycle_session=lifecycle)
        codec = session._model_input_binary_codec(active_only=True)
        try:
            async with lifecycle.operation_scope():
                assert owner._active_io == 1

                def unavailable():
                    raise OSError("test writer check failed")

                with monkeypatch.context() as patch:
                    patch.setattr(owner, "_check_writers", unavailable)
                    with pytest.raises(OSError, match="writer check failed"):
                        session.build_session_context()
                assert owner._active_io == 1
                with pytest.raises(ValueError):
                    codec.hydrate_mapping({"$loushang.sessionBlob": {"version": -1}})
                assert owner._active_io == 1
            assert owner._active_io == 0 and owner._io_drained.is_set()
        finally:
            await owner.dispose()

    asyncio.run(scenario())


def test_graph_transfer_preserves_consumers_until_graph_close(tmp_path):
    async def scenario():
        owner = setup(tmp_path / "sessions")
        lifecycle = await owner.create()
        session = ProductTranscriptSession(lifecycle_session=lifecycle)
        try:
            await session.append_message(message())
            codec = session._model_input_binary_codec(active_only=True)
            projected = codec.externalize_mapping(logical_image())
            lifecycle._begin_graph_construction()
            lifecycle._commit_graph_ownership()
            await owner.dispose()
            assert not owner.closing
            assert session.build_session_context().messages
            assert codec.hydrate_mapping(projected.value) == logical_image()
        finally:
            await lifecycle._dispose_graph_owned()
        with pytest.raises(TranscriptWriterError, match="closed"):
            codec.hydrate_mapping(projected.value)

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["context", "codec"])
def test_owned_blob_contention_is_not_missing_image(tmp_path, monkeypatch, action):
    async def scenario():
        owner = setup(tmp_path / "sessions")
        session = ProductTranscriptSession(lifecycle_session=await owner.create())
        try:
            await session.append_message(message())
            codec = session._model_input_binary_codec(active_only=True)
            projected = codec.externalize_mapping(logical_image())

            def busy(*args, **kwargs):
                raise BlockingIOError("test retained blob authority busy")

            with monkeypatch.context() as patch:
                patch.setattr(SessionBlobStore, "read_bytes", busy)
                with pytest.raises(BlockingIOError, match="retained blob authority busy"):
                    if action == "context":
                        session.build_session_context()
                    else:
                        codec.hydrate_mapping(projected.value)
            assert owner._active_io == 0 and owner._io_drained.is_set()
        finally:
            await owner.dispose()

    asyncio.run(scenario())


def test_root_replaced_before_admission_rejects_before_blob_store(tmp_path, monkeypatch):
    async def scenario():
        root = tmp_path / "sessions"
        owner = setup(root)
        session = ProductTranscriptSession(lifecycle_session=await owner.create())
        try:
            root.rename(tmp_path / "original")
            root.mkdir(mode=0o700)

            def forbidden(*args, **kwargs):
                raise AssertionError("changed root reached blob storage")

            with monkeypatch.context() as patch:
                patch.setattr(product_module, "SessionBlobStore", forbidden)
                with pytest.raises(TranscriptWriterError):
                    session.build_session_context()
            assert owner._active_io == 0 and not tuple(root.iterdir())
        finally:
            await owner.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["externalize_mapping", "hydrate_mapping"])
def test_falsey_scope_factory_is_not_discarded(tmp_path, method):
    class Scope:
        def __bool__(self):
            return False

        @contextmanager
        def __call__(self):
            raise RuntimeError("test scope admission refused")
            yield  # pragma: no cover

    codec = SessionModelInputBlobCodec(SessionBlobStore(tmp_path, "session"), operation_scope=Scope())
    with pytest.raises(RuntimeError, match="scope admission refused"):
        getattr(codec, method)({})


def test_sync_consumers_reject_while_disposal_is_pending(tmp_path, monkeypatch):
    async def scenario():
        owner = setup(tmp_path / "sessions")
        lifecycle = await owner.create()
        session = ProductTranscriptSession(lifecycle_session=lifecycle)
        codec = session._model_input_binary_codec(active_only=True)
        started, release = asyncio.Event(), asyncio.Event()
        dispose = owner._dispose_runtime

        async def waiting_dispose():
            started.set()
            await release.wait()
            await dispose()

        monkeypatch.setattr(owner, "_dispose_runtime", waiting_dispose)
        closing = asyncio.create_task(owner.dispose())
        try:
            await asyncio.wait_for(started.wait(), 5)
            assert not closing.done()
            for action in ("context", "new_codec", "hydrate", "externalize"):
                with pytest.raises(TranscriptWriterError, match="closed"):
                    invoke(session, codec, action)
            assert owner._active_io == 0
        finally:
            release.set()
            await closing

    asyncio.run(scenario())


def test_corrupt_image_still_degrades_without_leaking_admission(tmp_path):
    async def scenario():
        owner = setup(tmp_path / "sessions")
        session = ProductTranscriptSession(lifecycle_session=await owner.create())
        try:
            await session.append_message(message())
            with session._lifecycle_session.sync_operation_scope():
                store = session._session_blob_store(file_io=owner.blob_file_io)
                reference = store.records[0]
            (store.objects_root / reference.blob_id).write_bytes(b"corrupt")
            context = session.build_session_context()
            assert "Image unavailable" in context.messages[-1].content[0].text
            assert owner._active_io == 0 and owner._io_drained.is_set()
        finally:
            await owner.dispose()

    asyncio.run(scenario())
