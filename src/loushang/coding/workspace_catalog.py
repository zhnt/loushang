"""Coding Session construction and open policy for Host-owned workspaces."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from loushang.ai.model import Model, ModelSelection, model_selection_ref
from loushang.ai.model.selection import is_usable_model_selection
from loushang.apphost.integrations._canonical_transcript_catalog import (
    _WorkspaceTranscriptCatalogMethods,
)
from loushang.apphost.integrations.session_control import project_session_models
from loushang.apphost.workspace_registry import HostWorkspaceRegistryPort
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionIdentityV1,
    SessionModelsV1,
    SessionScopeV1,
)
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission

from .hosted_catalog import (
    _MAX_TRANSCRIPT_BYTES,
    CodingHostedCatalogError,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from .hosted_models import preview_workspace_models
from .managed_catalog import CodingManagedSessionCatalogV1
from .workspace_inspection import inspect_session_changes, inspect_workspace


class CodingWorkspaceCatalog(
    _WorkspaceTranscriptCatalogMethods[CodingHostedSessionCatalogV1]
):
    """One AppHost identity catalog, with independently owned transcript stores.

    Registration prepares catalog metadata only. Product/Harness construction
    remains the original resolver's per-Session responsibility. No cwd switch,
    AppService, Registry or additional AppHost is constructed here.
    """

    def __init__(
        self, registry: HostWorkspaceRegistryPort, session_root: Path, store_state_root: Path,
        *, model: Model | ModelSelection | None = None,
    ):
        self.registry = registry
        self._model = model
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

    async def delete_session_history(self, identity: SessionIdentityV1) -> None:
        catalog = self._find(lambda scope: scope.fingerprint == identity.scope_fingerprint)
        await catalog.delete_session_history(identity)

    async def workspace_models(self, path: str | None) -> SessionModelsV1:
        if self._closed:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        workspace = None
        if path is not None:
            try:
                workspace = await settled_io(self.registry.select, path)
            except (OSError, ValueError):
                raise AppServiceError(AppErrorCodeV1.NOT_FOUND) from None
        selection, choices = await settled_io(preview_workspace_models, workspace, self._model)
        current = None
        if selection is not None and is_usable_model_selection(selection):
            current = model_selection_ref(selection)
        return project_session_models(current, choices)

    async def workspace(self, request):
        from loushang.appserver.protocol import WorkspaceInfoV1, WorkspaceResultV1

        if request.action == "inspect":
            if self._closed:
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            try:
                path = await settled_io(self.registry.select, request.path)
            except (OSError, ValueError):
                raise AppServiceError(AppErrorCodeV1.NOT_FOUND) from None
            catalog = self._catalogs.get(path)
            if catalog is None or self.registry.is_temporary(path):
                raise AppServiceError(AppErrorCodeV1.NOT_FOUND)
            scope = catalog.scopes[0]
            report = await settled_io(inspect_workspace, path)
            if report["git"] is None and request.session_id:
                try:
                    candidates = await catalog.list_identities((scope.discovery_scope,), limit=128)
                    matches = [item.reference for item in candidates
                               if item.envelope is not None and item.envelope.session_id == request.session_id]
                    if len(matches) == 1:
                        history = await catalog.preview_history_snapshot(matches[0], max_bytes=_MAX_TRANSCRIPT_BYTES)
                        report.update(inspect_session_changes(path, (entry.payload for entry in history.selected_records)))
                except (CodingHostedCatalogError, OSError, ValueError):
                    report["limited"] = True
            return WorkspaceResultV1((WorkspaceInfoV1(str(path), scope.scope, scope.fingerprint, report),))

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
