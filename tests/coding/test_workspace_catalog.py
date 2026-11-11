import asyncio
from pathlib import Path

from loushang.apphost.workspaces import WorkspaceRegistry
from loushang.coding.workspace_catalog import CodingWorkspaceCatalog
from loushang.harness.transcript.jsonl_file import load_agent_transcript_file

from .test_hosted_catalog import _intent


def test_two_workspaces_route_real_transcripts_without_runtime_or_cwd_switch(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    registry = WorkspaceRegistry(tmp_path / 'registry')
    registry.open()
    original_cwd = Path.cwd()

    async def scenario():
        catalog = CodingWorkspaceCatalog(registry, tmp_path / 'sessions', tmp_path / 'stores')
        try:
            await catalog.load()
            assert catalog.scopes == ()
            await catalog.register(str(a))
            await catalog.register(str(b))
            sa, sb = await catalog.select(str(a)), await catalog.select(str(b))
            assert sa.source_id != sb.source_id
            assert sa.fingerprint != sb.fingerprint
            assert not (tmp_path / 'sessions').exists()
            for scope in (sa, sb):
                intent = _intent(scope)
                candidate = await catalog.create_candidate(intent)
                await candidate.close()
            headers = [load_agent_transcript_file(p, read_only=True)[0]
                       for p in (tmp_path / 'sessions').rglob('*.jsonl')]
            assert {h.metadata['cwd'] for h in headers} == {str(a), str(b)}
            rows = await catalog.list_identities((sa.discovery_scope,), limit=256)
            assert len(rows) == 2
            assert len({r.reference.source_id for r in rows}) == 2
            for row in rows:
                candidate = await catalog.open_candidate(row.reference)
                await candidate.close()
            assert Path.cwd() == original_cwd
        finally:
            await catalog.close()
    asyncio.run(scenario())
