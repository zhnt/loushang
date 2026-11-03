from __future__ import annotations

import asyncio
import sys

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.bootstrap import create_agent_session_runtime

from .test_agent_session_runtime import _model

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux default owned bootstrap")


def test_default_bootstrap_fresh_sibling_projects_share_family_without_layout_change(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "platform"))

    async def scenario():
        a_root, b_root = tmp_path / "sessions/project-a", tmp_path / "sessions/project-b"
        a = create_agent_session_runtime(session_dir=a_root, model=_model(), no_tools=True)
        b = create_agent_session_runtime(session_dir=b_root, model=_model(), no_tools=True)
        try:
            first = await a.create_session(cwd=str(tmp_path))
            await first.session_manager.append_message(UserMessage(role="user", content="A", timestamp=1.0))
            second = await b.create_session(cwd=str(tmp_path))
            await second.session_manager.append_message(UserMessage(role="user", content="B", timestamp=2.0))
            assert first.session_manager.session_file.parent == a_root
            assert second.session_manager.session_file.parent == b_root
            assert (a_root.parent / "session-assets/.locks").is_dir()
            first_owner = first.session_manager._lifecycle_session._writer_owner
            second_owner = second.session_manager._lifecycle_session._writer_owner
            assert first_owner._store_admission._binding.family_id == second_owner._store_admission._binding.family_id
            assert first.session_manager._lifecycle_session.ownership_state == "graph_owned"
        finally:
            await b.dispose_session_runtime()
            await a.dispose_session_runtime()

    asyncio.run(scenario())
