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
    WorkspaceInfoV1,
    WorkspaceRequestV1,
    WorkspaceResultV1,
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
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission


def _workspace_edit_error(error: ValueError) -> AppServiceError:
    code = {
        "workspace_path_not_found": AppErrorCodeV1.NOT_FOUND,
        "workspace_path_missing": AppErrorCodeV1.NOT_FOUND,
        "workspace_path_permission_denied": AppErrorCodeV1.PERMISSION_DENIED,
        "workspace_path_unsafe": AppErrorCodeV1.PERMISSION_DENIED,
    }.get(str(error), AppErrorCodeV1.INVALID_REQUEST)
    return AppServiceError(code)


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

    def _create_catalog(self, path: Path) -> CodingHostedSessionCatalogV1:
        return self._session_catalog(path)

    def _session_catalog(self, path: Path, workspace_id: str | None = None) -> CodingHostedSessionCatalogV1:
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
        witness = TranscriptStoreAdmission(
            previous, state_root=self._state
        ).witness_root
        # A surviving witness identifies the original store even if its data
        # directory is missing. New stores use the workspaces family.
        if workspace_id is None and (os.path.lexists(previous) or os.path.lexists(witness)):
            root = previous
        return CodingManagedSessionCatalogV1(
            session_root=root,
            workspace=path,
            store_state_root=self._state, workspace_id=workspace_id, historical_origin=workspace_id is None,
        )

    async def load(self) -> None:
        if self._loaded:
            return
        await settled_io(self.registry.open)
        origins = await settled_io(self.registry.list)
        for origin in origins:
            self._add(origin)
        for workspace in await settled_io(self.registry.workspaces):
            if self._retained_logical_store(workspace.id):
                await self._logical_catalog(workspace)
        self._loaded = True

    def _retained_logical_store(self, workspace_id: str) -> bool:
        root = self._root / "workspaces" / workspace_id
        roots = (root / "cwd", root / "user_home") if sys.platform in {"win32", "darwin"} else (root,)
        return any(os.path.lexists(path) or os.path.lexists(
            TranscriptStoreAdmission(path, state_root=self._state).witness_root
        ) for path in roots)

    async def _logical_catalog(self, workspace: Workspace) -> CodingHostedSessionCatalogV1:
        path = self._logical_catalogs.get(workspace.id)
        if path is None:
            path = await settled_io(self.registry.session_context, workspace.id)
            self._catalogs[path] = self._session_catalog(path, workspace.id)
            self._logical_catalogs[workspace.id] = path
        return self._catalogs[path]

    async def _logical_info(self, item: Workspace) -> WorkspaceInfoV1:
        scope = (await self._logical_catalog(item)).scopes[0]
        links = []
        for link in item.paths:
            links.append({"id": link.id, "alias": link.alias, "path": str(link.path),
                          "status": await settled_io(self.registry.path_status, link)})
        mux = (TEMPORARY_MUX if item.default else
               project_mux_name(str(item.legacy_origins[0])) if item.legacy_origins else f"ws-{item.id}")
        return WorkspaceInfoV1(str(scope.cwd), scope.scope, scope.fingerprint, workspace={
            "id": item.id, "name": item.name, "paths": links, "default": item.default,
            "defaultPathId": item.default_path_id, "muxName": mux,
        })

    async def _workspace_by_id(self, workspace_id: str) -> Workspace:
        try:
            return await settled_io(self.registry.workspace, workspace_id)
        except ValueError:
            raise AppServiceError(AppErrorCodeV1.NOT_FOUND) from None

    async def _owned_workspace_catalogs(self, item: Workspace) -> tuple[CodingHostedSessionCatalogV1, ...]:
        if self._closed or item.default:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        logical = await self._logical_catalog(item)
        return (logical, *(self._add(origin) for origin in item.legacy_origins))

    async def workspace_deletion_scopes(self, workspace_id: str) -> frozenset[str]:
        item = await self._workspace_by_id(workspace_id)
        catalogs = await self._owned_workspace_catalogs(item)
        return frozenset(scope.fingerprint for catalog in catalogs for scope in catalog.scopes)

    async def _logical_workspace(self, request: WorkspaceRequestV1) -> WorkspaceResultV1:
        action = request.action
        if action == "workspaces":
            records = await settled_io(self.registry.workspaces)
            return WorkspaceResultV1(tuple([await self._logical_info(item) for item in records]))
        if action == "create-workspace":
            assert request.name is not None
            try:
                created = await settled_io(
                    self.registry.create_workspace, request.name, path=request.path, alias=request.alias,
                )
            except ValueError as error:
                raise _workspace_edit_error(error) from error
            return WorkspaceResultV1((await self._logical_info(created),))
        workspace_id = request.workspace_id
        assert workspace_id is not None
        item = await self._workspace_by_id(workspace_id)
        if action in {"inspect-workspace", "preview-workspace"}:
            link = item.default_path
            if link is None or await settled_io(self.registry.path_status, link) != "available":
                raise AppServiceError(AppErrorCodeV1.NOT_FOUND)
            fingerprint = request.preview.scope_fingerprint if request.preview is not None else request.scope_fingerprint
            catalog = await self._logical_catalog(item)
            if fingerprint is not None and catalog.scopes[0].fingerprint != fingerprint:
                legacy = next((self._catalogs[origin] for origin in item.legacy_origins
                               if self._catalogs[origin].scopes[0].fingerprint == fingerprint), None)
                if legacy is None:
                    raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
                catalog = legacy
            if action == "inspect-workspace":
                scope = catalog.scopes[0]
                report = await self._inspect_workspace(link.path, catalog, scope, request.session_id)
                return WorkspaceResultV1((WorkspaceInfoV1(str(link.path), scope.scope, scope.fingerprint, report),))
            assert request.preview is not None
            return await self._read_workspace_preview(link.path, catalog, request.preview)
        if action == "delete-workspace":
            if item.default or item.legacy_origins:
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            catalog = await self._logical_catalog(item)
            if self._retained_logical_store(workspace_id):
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            await settled_io(self.registry.delete_workspace, workspace_id)
            # Keep ownership until close settles, including shutdown retry.
            await catalog.close()
            path = self._logical_catalogs.pop(workspace_id)
            self._catalogs.pop(path)
            return WorkspaceResultV1(())
        if action == "delete-workspace-with-history":
            catalogs = await self._owned_workspace_catalogs(item)
            try:
                for catalog in catalogs:
                    await catalog.delete_workspace_history()
                await settled_io(self.registry.delete_workspace, workspace_id, history_deleted=True)
            except Exception as error:
                raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE) from error
            self._catalogs.pop(self._logical_catalogs.pop(workspace_id))
            for origin in item.legacy_origins:
                self._catalogs.pop(origin)
            return WorkspaceResultV1(())
        try:
            if action == "rename-workspace":
                assert request.name is not None
                await settled_io(self.registry.rename_workspace, workspace_id, request.name)
            elif action == "add-path":
                assert request.alias is not None and request.path is not None
                await settled_io(self.registry.add_path, workspace_id, request.alias, request.path)
            elif action == "update-path":
                assert request.path_id is not None and request.alias is not None and request.path is not None
                await settled_io(self.registry.update_path, workspace_id, request.path_id, request.alias, request.path)
            elif action == "remove-path":
                assert request.path_id is not None
                await settled_io(self.registry.remove_path, workspace_id, request.path_id)
            elif action == "set-default-path":
                await settled_io(self.registry.set_default_path, workspace_id, request.path_id)
        except ValueError as error:
            raise _workspace_edit_error(error) from error
        return WorkspaceResultV1((await self._logical_info(await settled_io(self.registry.workspace, workspace_id)),))

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
            try:
                item = await settled_io(self.registry.workspace, workspace_id)
            except ValueError:
                raise AppServiceError(AppErrorCodeV1.NOT_FOUND) from None
            link = item.default_path
            if link is not None and await settled_io(self.registry.path_status, link) == "available":
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

    async def workspace(self, request: WorkspaceRequestV1) -> WorkspaceResultV1:
        if request.action == "allocate-temporary":
            # Old callers still receive a creation scope, backed by the same
            # default Workspace as every other ordinary chat.
            item = await settled_io(self.registry.default_workspace)
            scope = (await self._logical_catalog(item)).scopes[0]
            return WorkspaceResultV1((WorkspaceInfoV1(str(scope.cwd), scope.scope, scope.fingerprint),))
        if request.action in {"workspaces", "create-workspace", "open-workspace", "rename-workspace",
                              "inspect-workspace", "preview-workspace",
                              "delete-workspace", "delete-workspace-with-history",
                              "add-path", "update-path", "remove-path", "set-default-path"}:
            if self._closed:
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            return await self._logical_workspace(request)
        if request.preview is not None or request.action == "inspect":
            return await super().workspace(request)

        if request.action == "open" and request.path is not None:
            selected = await settled_io(self.registry.select, request.path)
            matches = [
                item for item in await settled_io(self.registry.workspaces)
                if any(link.path == selected for link in item.paths)
            ]
            if len(matches) > 1:
                raise AppServiceError(AppErrorCodeV1.REVISION_CONFLICT)
            if matches and selected not in matches[0].legacy_origins:
                return WorkspaceResultV1((await self._logical_info(matches[0]),))
            scope = self._add(selected).scopes[0]
            return WorkspaceResultV1((WorkspaceInfoV1(str(selected), scope.scope, scope.fingerprint),))
        if request.action == "unregister" and request.path is not None:
            catalog = self._catalogs.get(Path(request.path))
            if catalog is not None and any(
                os.path.lexists(scope.session_dir) or os.path.lexists(
                    TranscriptStoreAdmission(scope.session_dir, state_root=self._state).witness_root
                )
                for scope in catalog.scopes
            ):
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        entries = await self._workspace_entries(request)
        return WorkspaceResultV1(
            tuple(
                WorkspaceInfoV1(
                    str(path), catalog.scopes[0].scope, catalog.scopes[0].fingerprint
                )
                for path, catalog in entries if catalog.scopes[0].workspace_id is None
            )
        )

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
