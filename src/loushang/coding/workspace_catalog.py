"""Coding Session catalogs selected by Host-owned canonical workspace paths."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from loushang.apphost.workspaces import WorkspaceRegistry

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
        self._catalogs: dict[Path, CodingManagedSessionCatalogV1] = {}
        self._closed = False

    async def load(self) -> None:
        for path in await asyncio.to_thread(self.registry.list):
            self._add(path)

    @property
    def scopes(self):
        return tuple(scope for catalog in self._catalogs.values() for scope in catalog.scopes)

    @property
    def pending_sessions(self):
        return tuple(session for catalog in self._catalogs.values() for session in catalog.pending_sessions)

    def _add(self, path: Path) -> CodingManagedSessionCatalogV1:
        if self._closed:
            raise ValueError("workspace_catalog_closed")
        if path not in self._catalogs:
            leaf = hashlib.sha256(str(path).encode()).hexdigest()
            self._catalogs[path] = CodingManagedSessionCatalogV1(
                session_root=self._root / leaf, workspace=path,
                store_state_root=self._state,
            )
        return self._catalogs[path]

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

    async def list_identities(self, scopes, *, limit):
        result = []
        for catalog in self._catalogs.values():
            result.extend(await catalog.list_identities(scopes, limit=limit))
            if len(result) > limit:
                raise ValueError("session_catalog_limit")
        return tuple(result)

    async def open_candidate(self, reference):
        return await self._for_reference(reference).open_candidate(reference)

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
