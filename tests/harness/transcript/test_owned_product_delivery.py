from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.transcript import (
    AgentTranscriptSessionFactory,
    ProductTranscriptSession,
)

from .test_owned_bundle_import import bundle
from .test_owned_session_factory import factory
from .test_runtime_profile import _runtime
from .test_writer_lease import busy, lease

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned Product delivery")


def product(selected, calls, *, action=None):
    class Bound(ProductTranscriptSession):
        @classmethod
        def _session_factory(cls):
            return selected

        def _fork_binding_input(self):
            return selected._resolve_binding_input(True)

        def __init__(self, *, lifecycle_session):
            calls.append(lifecycle_session)
            assert lifecycle_session._writer_owner in selected.pending_preparations
            super().__init__(lifecycle_session=lifecycle_session)
            if action:
                action(self)

    return Bound


@pytest.mark.parametrize("method", ["new", "open", "load", "continue_recent", "import_bundle", "fork_from", "fork"])
def test_each_product_construction_projects_once_before_delivery(tmp_path, method):
    async def scenario():
        root = tmp_path / "sessions"
        root.mkdir(mode=0o700)
        selected, calls = factory(), []
        Bound = product(selected, calls)
        source = await Bound.new(root, "/workspace", session_id="conversation-1")
        await source.append_message(UserMessage(role="user", content="hello", timestamp=1.0))
        path, leaf = source.session_file, source.leaf_id
        if method != "fork":
            await source.dispose_runtime_profile()
        calls.clear()
        result = None
        try:
            if method == "new":
                result = await Bound.new(root, "/workspace", session_id="new")
            elif method in {"open", "load"}:
                result = await getattr(Bound, method)(path)
            elif method == "continue_recent":
                result = await Bound.continue_recent(root, "/workspace")
            elif method == "import_bundle":
                archive, target = await bundle(tmp_path, images=False)
                result = await Bound.import_bundle(archive, session_dir=target)
            elif method == "fork_from":
                result = await Bound.fork_from(path, "/workspace", root)
            else:
                result = await source.fork(leaf)
            assert calls == [result._lifecycle_session]
            assert result._creation_factory is selected and not selected.pending_preparations
            await selected.close()  # Delivered runtime remains Session-owned.
            busy(result.session_dir, conversation=result.header.conversation_id)
        finally:
            if result:
                await result.dispose_runtime_profile()
            await source.dispose_runtime_profile()
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["constructor", "factory_binding", "fence"])
def test_failed_wrapper_retains_original_preparation_until_cleanup(tmp_path, monkeypatch, failure):
    async def scenario():
        runtime = _runtime("coding")
        selected, calls = factory(runtime=runtime), []

        def action(value):
            if failure == "constructor":
                raise ValueError("wrapper failed")
            if failure == "fence":
                selected.fence()

        Bound = product(selected, calls, action=action)
        if failure == "factory_binding":
            original = Bound.__setattr__

            def fail_setattr(self, name, value):
                if name == "_creation_factory" and value is selected:
                    raise ValueError("factory binding failed")
                original(self, name, value)

            monkeypatch.setattr(Bound, "__setattr__", fail_setattr)

        async def fail_dispose(binding):
            raise OSError("cleanup temporarily unavailable")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(runtime._binder, "dispose", fail_dispose)
                with pytest.raises((ValueError, RuntimeError)) as result:
                    await Bound.new(tmp_path, "/workspace", session_id="conversation-1")
                assert "cleanup retained" in result.value.__notes__[0]
                retained, = selected.pending_preparations
                assert calls == [retained._session] and retained.cleanup_pending
                busy(tmp_path, conversation="conversation-1")
                with pytest.raises(OSError, match="cleanup temporarily unavailable"):
                    await selected.close()
                assert selected.pending_preparations == (retained,)
            await selected.close()
            assert not selected.pending_preparations
            fresh = lease(tmp_path, conversation="conversation-1")
            try:
                fresh.acquire()
            finally:
                fresh.close()
        finally:
            await selected.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("falsey", [False, True])
def test_instance_fork_uses_creating_factory_not_later_class_selection(tmp_path, monkeypatch, falsey):
    async def scenario():
        class FalseyFactory(AgentTranscriptSessionFactory):
            def __bool__(self):
                return False

        selected = factory(factory_type=FalseyFactory if falsey else AgentTranscriptSessionFactory)
        calls = []
        Bound = product(selected, calls)
        source = await Bound.new(tmp_path, "/workspace", session_id="conversation-1")
        await source.append_message(UserMessage(role="user", content="hello", timestamp=1.0))

        def forbidden(cls):
            raise AssertionError("instance fork looked up a replacement factory")

        monkeypatch.setattr(Bound, "_session_factory", classmethod(forbidden))
        target = None
        try:
            target = await source.fork(source.leaf_id)
            assert target._creation_factory is selected
            assert len(calls) == 2 and not selected.pending_preparations
        finally:
            if target:
                await target.dispose_runtime_profile()
            await source.dispose_runtime_profile()
            await selected.close()

    asyncio.run(scenario())


def test_delivered_graph_state_remains_owned_after_factory_close(tmp_path):
    async def scenario():
        selected, calls = factory(), []
        Bound = product(selected, calls)
        value = await Bound.new(tmp_path, "/workspace", session_id="conversation-1")
        session = value._lifecycle_session
        session._begin_graph_construction()
        session._commit_graph_ownership()
        try:
            await selected.close()
            assert session.ownership_state == "graph_owned"
            assert not session._writer_owner.closing
            assert not selected.pending_preparations
            busy(tmp_path, conversation="conversation-1")
            await value.append_message(UserMessage(role="user", content="after delivery", timestamp=1.0))
            await value.dispose_runtime_profile()  # Compatibility close cannot retire the Graph owner.
            busy(tmp_path, conversation="conversation-1")
        finally:
            await session._dispose_graph_owned()
            await selected.close()
        assert session.ownership_state == "disposed"

    asyncio.run(scenario())


def test_legacy_factory_operation_does_not_receive_projection_keyword(tmp_path):
    from .test_product_session import _ExampleProductSession

    async def scenario():
        selected = factory()
        session = await selected.new(session_dir=tmp_path, cwd="/workspace", session_id="conversation-1")
        calls = []

        async def strict_operation():
            calls.append("operation")
            return session

        class LegacyFactory:
            owns_persistent_sessions = False

        try:
            value = await _ExampleProductSession._construct_product(LegacyFactory(), strict_operation)
            assert calls == ["operation"] and value._creation_factory is None
            assert value._lifecycle_session is session
        finally:
            await session.dispose()
            await selected.close()

    asyncio.run(scenario())
