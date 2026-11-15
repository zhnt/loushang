"""Coding Session construction and open policy for Host-owned workspaces."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from loushang.apphost.integrations._canonical_transcript_catalog import (
    _WorkspaceTranscriptCatalogMethods,
)
from loushang.apphost.managed.workspaces import WorkspaceRegistry
from loushang.appserver.protocol import SessionScopeV1
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission

from .hosted_catalog import (
    _MAX_TRANSCRIPT_BYTES,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from .managed_catalog import CodingManagedSessionCatalogV1


class CodingWorkspaceCatalog(
    _WorkspaceTranscriptCatalogMethods[CodingHostedSessionCatalogV1]
):
    """One AppHost identity catalog, with independently owned transcript stores.

    Registration prepares catalog metadata only. Product/Harness construction
    remains the original resolver's per-Session responsibility. No cwd switch,
    AppService, Registry or additional AppHost is constructed here.
    """

    def __init__(
        self, registry: WorkspaceRegistry, session_root: Path, store_state_root: Path
    ):
        self.registry = registry
        self._root = session_root
        self._state = store_state_root
        self._catalogs: dict[Path, CodingHostedSessionCatalogV1] = {}
        self._loaded = False
        self._closed = False

    def _create_catalog(self, path: Path) -> CodingHostedSessionCatalogV1:
        leaf = hashlib.sha256(str(path).encode()).hexdigest()
        root = self._root / "workspaces" / leaf
        if sys.platform == "win32":
            # Use the native hosted Session writer with separate scope roots.
            return CodingHostedSessionCatalogV1(
                tuple(
                    CodingHostedScopeV1(scope, root / scope.value, path)
                    for scope in (SessionScopeV1.CWD, SessionScopeV1.USER_HOME)
                )
            )
        previous = self._root / leaf
        witness = TranscriptStoreAdmission(
            previous, state_root=self._state
        ).witness_root
        # A surviving witness identifies the original store even if its data
        # directory is missing. New stores use the workspaces family.
        if os.path.lexists(previous) or os.path.lexists(witness):
            root = previous
        return CodingManagedSessionCatalogV1(
            session_root=root,
            workspace=path,
            store_state_root=self._state,
        )

    async def workspace(self, request):
        from loushang.appserver.protocol import WorkspaceInfoV1, WorkspaceResultV1

        entries = await self._workspace_entries(request)
        return WorkspaceResultV1(
            tuple(
                WorkspaceInfoV1(
                    str(path), catalog.scopes[0].scope, catalog.scopes[0].fingerprint
                )
                for path, catalog in entries
            )
        )

    def admits(self, scope) -> bool:
        return not self._closed and any(
            scope.product_id == "coding"
            and item.scope is scope.scope
            and item.fingerprint == scope.scope_fingerprint
            for item in self.scopes
        )

    async def _open_workspace_candidate(
        self, catalog: CodingHostedSessionCatalogV1, reference
    ):
        if sys.platform == "win32":
            return await catalog.open_candidate(reference)
        return await catalog.open_history_candidate(
            reference, max_bytes=_MAX_TRANSCRIPT_BYTES
        )
