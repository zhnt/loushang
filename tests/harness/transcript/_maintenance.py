"""Test-scoped retained maintenance for public transcript deletion tests."""

import sys

from loushang.harness.transcript import delete_agent_transcript_jsonl


async def delete_with_maintenance(path, *, current_session_file=None):
    from .test_owned_session_factory import factory

    if sys.platform != "linux":
        return await delete_agent_transcript_jsonl(path, current_session_file=current_session_file)
    owner = factory()
    try:
        return await delete_agent_transcript_jsonl(
            path, current_session_file=current_session_file, maintenance_owner=owner,
        )
    finally:
        await owner.close()
