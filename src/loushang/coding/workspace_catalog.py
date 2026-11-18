"""Coding Session construction and open policy for Host-owned workspaces."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from loushang.ai.model import (
    Model,
    ModelSelection,
    model_selection_ref,
    normalize_model_selection,
)
from loushang.ai.model.reasoning import available_thinking_levels
from loushang.ai.model.selection import is_usable_model_selection
from loushang.apphost.integrations._canonical_transcript_catalog import (
    _WorkspaceTranscriptCatalogMethods,
)
from loushang.apphost.integrations.session_control import project_session_models
from loushang.apphost.workspace_registry import (
    HostWorkspaceRegistryPort,
    WorkspaceFileRead,
    WorkspacePreviewError,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionIdentityV1,
    SessionModelsV1,
    SessionScopeV1,
    SessionThinkingV1,
    WorkspaceInfoV1,
    WorkspaceRequestV1,
    WorkspaceResultV1,
)
from loushang.appserver.protocol.workspace_preview import (
    WorkspaceDirectoryPreviewV1,
    WorkspaceFilePreviewV1,
    WorkspacePreviewEntryV1,
    WorkspacePreviewRequestV1,
    WorkspacePreviewV1,
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

    async def workspace_models(self, path: str | None, model_id: str | None = None) -> SessionModelsV1:
        if self._closed:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        workspace = None
        if path is not None:
            try:
                workspace = await settled_io(self.registry.select, path)
            except (OSError, ValueError):
                raise AppServiceError(AppErrorCodeV1.NOT_FOUND) from None
        active, choices, default_level = await settled_io(preview_workspace_models, workspace, self._model)
        default_selection = normalize_model_selection(active)
        if model_id is not None:
            active = next((
                model for model in choices
                if (selection := normalize_model_selection(model)) is not None
                and model_selection_ref(selection) == model_id
            ), None)
        selection = normalize_model_selection(active)
        current = None
        if selection is not None and is_usable_model_selection(selection):
            current = model_selection_ref(selection)
        if model_id is not None and current != model_id:
            raise AppServiceError(AppErrorCodeV1.NOT_FOUND)
        # A model-specific preview opts in to reasoning. Older draft clients
        # reuse the initial catalog across selections and expect no settings.
        levels = available_thinking_levels(active) if model_id is not None and active is not None else ()
        level = default_level if selection == default_selection and default_level in levels else None
        return project_session_models(current, choices, SessionThinkingV1(level, levels) if levels else None)

    async def _preview_workspace(self, path: str, request: WorkspacePreviewRequestV1) -> WorkspaceResultV1:
        if self._closed:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        try:
            root = await settled_io(self.registry.select, path)
        except (OSError, ValueError):
            raise AppServiceError(AppErrorCodeV1.NOT_FOUND) from None
        catalog = self._catalogs.get(root)
        if catalog is None:
            raise AppServiceError(AppErrorCodeV1.NOT_FOUND)
        scope = catalog.scopes[0]
        if root != Path(path) or scope.fingerprint != request.scope_fingerprint:
            raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
        try:
            opened = await settled_io(self.registry.preview, root, request.reference, request.base)
        except WorkspacePreviewError as exc:
            raise AppServiceError(AppErrorCodeV1(exc.code)) from None
        preview: WorkspacePreviewV1
        if isinstance(opened, WorkspaceFileRead):
            preview = WorkspaceFilePreviewV1(opened.path, opened.text)
        else:
            entries = tuple(WorkspacePreviewEntryV1(name, kind) for name, kind in opened.entries)
            preview = WorkspaceDirectoryPreviewV1(opened.path, entries, opened.limited)
        return WorkspaceResultV1((WorkspaceInfoV1(str(root), scope.scope, scope.fingerprint, preview=preview),))

    async def workspace(self, request: WorkspaceRequestV1) -> WorkspaceResultV1:
        if request.preview is not None and request.path is not None:
            return await self._preview_workspace(request.path, request.preview)

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
