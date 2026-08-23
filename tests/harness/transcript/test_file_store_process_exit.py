from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_host_runtime


def test_file_store_async_create_allows_python_process_to_exit(tmp_path: Path) -> None:
    script = """
import asyncio
import sys
from pathlib import Path

from loushang.harness.conversation import ConversationHeader
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    create_agent_transcript_file_store,
)


async def main() -> None:
    layout = AgentTranscriptFileLayout(Path(sys.argv[1]))
    key = layout.key("process-exit")
    store = create_agent_transcript_file_store(layout)
    await store.create(
        key,
        ConversationHeader(
            conversation_id=key.conversation_id,
            version=1,
            created_at="2026-08-21T00:00:00Z",
            metadata={},
        ),
        operation_id="create:process-exit",
    )


asyncio.run(main())
"""

    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
