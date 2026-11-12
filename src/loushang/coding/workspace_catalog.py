"""Coding Session catalogs selected by Host-owned canonical workspace paths."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path

from loushang.apphost.managed.workspaces import WorkspaceRegistry
from loushang.appserver.protocol import SessionScopeV1
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission

from .hosted_catalog import (
    _MAX_TRANSCRIPT_BYTES,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from .managed_catalog import CodingManagedSessionCatalogV1


class CodingWorkspaceCatalog:
    """One AppHost identity catalog, with independently owned transcript stores.

    Registration prepares catalog metadata only. Product/Harness construction
    remains the original resolver's per-Session responsibility. No cwd switch,
    AppService, Registry or additional AppHost is constructed here.
    """

    def __init__(self, registry: WorkspaceRegistry, session_root: Path,
                 store_state_root: Path):
        self.registry = registry
        self._root = session_root
        self._state = store_state_root
        self._catalogs: dict[Path, CodingHostedSessionCatalogV1] = {}
        self._loaded = False
        self._closed = False

    async def workspace(self, request):
        from loushang.appserver.protocol import WorkspaceInfoV1, WorkspaceResultV1

        if request.action == "register":
            await self.register(request.path)
        elif request.action == "allocate-temporary":
            path = await asyncio.to_thread(self.registry.allocate_temporary)
            self._add(path)
        elif request.action == "open":
            selected = await self.select(request.path)
        elif request.action == "unregister":
            path = Path(request.path)
            catalog = self._catalogs.get(path)
            if catalog is not None:
                await catalog.close()
            await asyncio.to_thread(self.registry.unregister, request.path)
            self._catalogs.pop(path, None)
        entries = self._catalogs.items()
        if request.action == "open":
            entries = ((selected.cwd, self._catalogs[selected.cwd]),)
        elif request.action == "allocate-temporary":
            entries = ((path, self._catalogs[path]),)
        elif request.action == "projects":
            entries = ((root, catalog) for root, catalog in entries if not self.registry.is_temporary(root))
        return WorkspaceResultV1(tuple(
            WorkspaceInfoV1(str(path), catalog.scopes[0].scope, catalog.scopes[0].fingerprint)
            for path, catalog in entries
        ))

    async def load(self) -> None:
        if not self._loaded:
            for path in await asyncio.to_thread(self._load_paths):
                self._add(path)
            self._loaded = True

    def _load_paths(self) -> tuple[Path, ...]:
        self.registry.open()
        return self.registry.list()

    @property
    def scopes(self):
        return tuple(catalog.scopes[0] for catalog in self._catalogs.values())

    @property
    def pending_sessions(self):
        return tuple(session for catalog in self._catalogs.values() for session in catalog.pending_sessions)

    def _add(self, path: Path) -> CodingHostedSessionCatalogV1:
        if self._closed:
            raise ValueError("workspace_catalog_closed")
        if path not in self._catalogs:
            self._catalogs[path] = self._create_catalog(path)
        return self._catalogs[path]

    def _create_catalog(self, path: Path) -> CodingHostedSessionCatalogV1:
        leaf = hashlib.sha256(str(path).encode()).hexdigest()
        root = self._root / "workspaces" / leaf
        if sys.platform == "win32":
            # Use the native hosted Session writer with separate scope roots.
            return CodingHostedSessionCatalogV1(tuple(
                CodingHostedScopeV1(scope, root / scope.value, path)
                for scope in (SessionScopeV1.CWD, SessionScopeV1.USER_HOME)
            ))
        previous = self._root / leaf
        witness = TranscriptStoreAdmission(previous, state_root=self._state).witness_root
        # A surviving witness identifies the original store even if its data
        # directory is missing. New stores use the workspaces family.
        if os.path.lexists(previous) or os.path.lexists(witness):
            root = previous
        return CodingManagedSessionCatalogV1(
            session_root=root, workspace=path, store_state_root=self._state,
        )

    async def register(self, value: str) -> Path:
        path = await asyncio.to_thread(self.registry.register, value)
        self._add(path)
        return path

    async def select(self, value: str):
        path = await asyncio.to_thread(self.registry.select, value)
        return self._add(path).scopes[0]

    def admits(self, scope) -> bool:
        return not self._closed and any(
            scope.product_id == "coding" and item.scope is scope.scope
            and item.fingerprint == scope.scope_fingerprint for item in self.scopes
        )

    def _for_create(self, request):
        return self._find(lambda scope: scope.fingerprint == request.creator_scope_id)

    def _for_reference(self, reference):
        return self._find(lambda scope: scope.source_id == reference.source_id)

    def _find(self, matches):
        if not self._closed:
            for catalog in self._catalogs.values():
                if any(matches(scope) for scope in catalog.scopes):
                    return catalog
        raise ValueError("workspace_not_registered")

    async def discover_sessions(self, scope, *, stop):
        catalog = self._find(lambda item: item.scope is scope.scope
                             and item.fingerprint == scope.scope_fingerprint)
        return await catalog.discover_sessions(scope, stop=stop)

    async def workspace_identities(self, fingerprint, scope, *, limit):
        catalog = self._find(lambda item: item.fingerprint == fingerprint
                             and item.discovery_scope is scope)
        return await catalog.list_identities((scope,), limit=limit)

    async def list_identities(self, scopes, *, limit):
        result = []
        for catalog in self._catalogs.values():
            result.extend(await catalog.list_identities(scopes, limit=limit))
            if len(result) > limit:
                raise ValueError("session_catalog_limit")
        return tuple(result)

    async def open_candidate(self, reference):
        catalog = self._for_reference(reference)
        if sys.platform == "win32":
            return await catalog.open_candidate(reference)
        return await catalog.open_history_candidate(reference, max_bytes=_MAX_TRANSCRIPT_BYTES)

    async def find_created_candidate(self, request):
        return await self._for_create(request).find_created_candidate(request)

    async def create_candidate(self, intent):
        return await self._for_create(intent.request).create_candidate(intent)

    def fence(self) -> None:
        self._closed = True
        for catalog in self._catalogs.values():
            catalog.fence()

    async def close(self) -> None:
        self.fence()
        results = await asyncio.gather(*(c.close() for c in self._catalogs.values()),
                                       return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise BaseExceptionGroup("workspace_cleanup_incomplete", failures)
        await asyncio.to_thread(self.registry.close)
