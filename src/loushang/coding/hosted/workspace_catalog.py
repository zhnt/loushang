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
    CanonicalTranscriptScope,
    _WorkspaceTranscriptCatalogMethods,
)
from loushang.apphost.integrations.session_control import project_session_models
from loushang.apphost.workspace_registry import (
    HostWorkspaceRegistryPort,
    Workspace,
    WorkspacePath,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionModelsV1,
    SessionScopeV1,
    SessionThinkingV1,
)
from loushang.appservice.managed_mux import TEMPORARY_MUX, project_mux_name
from loushang.coding.hosted.catalog import (
    _MAX_TRANSCRIPT_BYTES,
    CodingHostedCatalogError,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
)
from loushang.coding.hosted.managed.catalog import CodingManagedSessionCatalogV1
from loushang.coding.hosted.models import preview_workspace_models
from loushang.coding.hosted_workspace import CodingHostedWorkspace
from loushang.coding.workspace.inspection import (
    inspect_session_changes,
    inspect_workspace,
)
from loushang.harness.journal._owned_io import settled_io


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
        self._logical_catalogs: dict[str, Path] = {}
        self._loaded = False
        self._closed = False

    def _create_catalog(
        self, path: Path, workspace_id: str | None = None
    ) -> CodingHostedSessionCatalogV1:
        leaf = workspace_id or hashlib.sha256(str(path).encode()).hexdigest()
        root = self._root / "workspaces" / leaf
        if sys.platform in {"win32", "darwin"}:
            # Use the native hosted Session writer with separate scope roots.
            return CodingHostedSessionCatalogV1(
                tuple(
                    CodingHostedScopeV1(scope, root / scope.value, path, workspace_id=workspace_id,
                                        historical_origin=workspace_id is None)
                    for scope in (SessionScopeV1.CWD, SessionScopeV1.USER_HOME)
                )
            )
        previous = self._root / leaf
        # A surviving witness identifies the original store even if its data
        # directory is missing. New stores use the workspaces family.
        if workspace_id is None and self._retained_store(previous):
            root = previous
        return CodingManagedSessionCatalogV1(
            session_root=root,
            workspace=path,
            store_state_root=self._state, workspace_id=workspace_id, historical_origin=workspace_id is None,
        )

    def _retained_logical_store(self, workspace_id: str) -> bool:
        root = self._root / "workspaces" / workspace_id
        roots = (root / "cwd", root / "user_home") if sys.platform in {"win32", "darwin"} else (root,)
        return any(self._retained_transcript_root(path) for path in roots)

    def _retained_transcript_root(self, root: Path) -> bool:
        if sys.platform in {"win32", "darwin"}:
            # Native hosted writers use per-scope roots without managed-store witnesses.
            return os.path.lexists(root)
        return super()._retained_transcript_root(root)

    def _workspace_mux_name(self, workspace: Workspace) -> str:
        if workspace.default:
            return TEMPORARY_MUX
        if workspace.legacy_origins:
            return project_mux_name(str(workspace.legacy_origins[0]))
        return f"ws-{workspace.id}"

    def runtime_workspace(self, scope: CodingHostedScopeV1) -> CodingHostedWorkspace:
        """Materialize a default and freeze the approved target identities."""
        item = next((item for item in self.registry.workspaces() if item.id == scope.workspace_id
                     or scope.cwd in item.legacy_origins), None)
        if item is None:
            raise CodingHostedCatalogError()
        observed = {
            link.id: (link.path, identity)
            for link in item.paths
            if (identity := self.registry.path_identity(link)) is not None
        }
        default = observed.get(item.default_path_id or "")
        project_cwd = default[0] if default is not None else None
        legacy_plugin_origin = (
            scope.cwd if item.default and scope.cwd in item.legacy_origins
            else item.legacy_origins[0] if not item.default and item.legacy_origins else None
        )
        anchor_id = scope.fingerprint[:32] if item.default and legacy_plugin_origin is not None else item.id
        anchor = self.registry.session_context(anchor_id)
        cwd = project_cwd if project_cwd is not None else anchor
        private_roots = tuple(path for path in (self._root, self._state, anchor.parent.parent)
                              if path.is_dir())

        def still_admitted(link: WorkspacePath) -> bool:
            return link.id in observed and observed[link.id] == (
                link.path, self.registry.path_identity(link)
            )

        def current_roots() -> tuple[Path, ...]:
            current = self.registry.execution_workspace(item.id)
            return tuple(link.path for link in current.paths if still_admitted(link)) if current is not None else ()

        def current_default() -> Path | None:
            current = self.registry.execution_workspace(item.id)
            link = current.default_path if current is not None else None
            if link is not None and link.id == item.default_path_id and still_admitted(link):
                return link.path
            return None

        return CodingHostedWorkspace(
            cwd, anchor, legacy_plugin_origin, project_cwd,
            tuple(path for path, _ in observed.values()), private_roots, current_roots, current_default,
        )

    async def workspace_models(self, path: str | None, model_id: str | None = None, *, workspace_id: str | None = None) -> SessionModelsV1:
        if self._closed:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        workspace = await self._select_workspace_for_read(path) if path is not None else None
        if workspace_id is not None:
            link = await self._available_default_path(await self._workspace_by_id(workspace_id))
            if link is not None:
                # Use only the currently admitted default, with no Home or process-cwd fallback.
                workspace = link.path
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

    async def _inspect_workspace(
        self, path: Path, catalog: CodingHostedSessionCatalogV1,
        scope: CanonicalTranscriptScope, session_id: str | None,
    ) -> dict[str, object]:
        report = await settled_io(inspect_workspace, path)
        if report["git"] is None and session_id:
            try:
                candidates = await catalog.list_identities(
                    (scope.discovery_scope,), limit=128,
                )
                matches = [
                    item.reference for item in candidates
                    if item.envelope is not None and item.envelope.session_id == session_id
                ]
                if len(matches) == 1:
                    history = await catalog.preview_history_snapshot(matches[0], max_bytes=_MAX_TRANSCRIPT_BYTES)
                    report.update(inspect_session_changes(path, (entry.payload for entry in history.selected_records)))
            except (CodingHostedCatalogError, OSError, ValueError):
                report["limited"] = True
        return report

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
        if sys.platform in {"win32", "darwin"}:
            return await catalog.open_candidate(reference)
        return await catalog.open_history_candidate(
            reference, max_bytes=_MAX_TRANSCRIPT_BYTES
        )
