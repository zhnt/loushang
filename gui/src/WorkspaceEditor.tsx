import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ProjectEntry, WorkspaceEdit, WorkspacePath } from "./client/projectDirectory";
import "./WorkspaceEditor.css";

interface WorkspaceEditorProps {
  readonly project?: ProjectEntry;
  readonly save: (edit: WorkspaceEdit) => Promise<void>;
  readonly onClose: () => void;
}

export function WorkspaceEditor({ project, save, onClose }: WorkspaceEditorProps) {
  const { t } = useTranslation("workspace", { keyPrefix: "workspaceEditor" });
  const dialog = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => { dialog.current?.showModal(); }, []);
  const workspaceId = project?.id;
  const [name, setName] = useState(project?.name ?? "");
  const [path, setPath] = useState({ id: undefined as string | undefined, alias: "", path: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedPaths, setSavedPaths] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const inFlight = useRef(false);

  async function submit(edit: WorkspaceEdit, accepted?: () => void) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await save(edit);
      if (project?.sessions.length && edit.action.endsWith("-path")) setSavedPaths(true);
      accepted?.();
    } catch (failure) {
      const code = failure instanceof Error ? failure.message : String(failure);
      const errorKey = code === "not_found" ? "missing" : code === "permission_denied" ? "permission_denied"
        : code === "operation_unavailable" && edit.action === "delete-workspace" ? "deleteBlocked" : "saveFailed";
      setError(t(errorKey));
    } finally {
      setBusy(false);
      inFlight.current = false;
    }
  }

  function updatePath(link: WorkspacePath) {
    setPath({ id: link.id, alias: link.alias, path: link.path });
  }

  return <dialog ref={dialog} className="frame-dialog workspace-editor" aria-labelledby="workspace-editor-heading"
    onClose={onClose} onCancel={(event) => { if (busy) event.preventDefault(); }}>
    <h2 id="workspace-editor-heading">{t(workspaceId ? "manage" : "create")}</h2>
    {error ? <p role="alert">{error}</p> : null}
    {savedPaths ? <p role="status">{t("savedPaths")}</p> : null}
    <form onSubmit={(event) => {
      event.preventDefault();
      if (!name.trim()) return;
      if (workspaceId) void submit({ action: "rename-workspace", workspaceId, name: name.trim() });
      else void submit({ action: "create-workspace", name: name.trim() }, onClose);
    }}>
      <label>{t("name")}<input autoFocus required maxLength={128} value={name} onChange={(event) => setName(event.target.value)} /></label>
      <button className="secondary-button" disabled={busy || !name.trim() || name === project?.name}>
        {t(workspaceId ? "rename" : "create")}
      </button>
    </form>
    {workspaceId ? <>
      <h3>{t("paths")}</h3>
      <ul>
        {project.paths?.map((link) => <li key={link.id}>
          <strong>{link.alias}</strong>
          <code>{link.path}</code>
          <span>{t(link.status)}</span>
          <div className="workspace-editor-actions">
            <button type="button" className="secondary-button" disabled={busy} onClick={() => updatePath(link)}>{t("editPath")}</button>
            <button type="button" className="secondary-button" disabled={busy || link.status !== "available"}
              onClick={() => void submit({ action: "set-default-path", workspaceId, pathId: project.defaultPathId === link.id ? undefined : link.id })}>
              {t(project.defaultPathId === link.id ? "clearDefault" : "makeDefault")}
            </button>
            <button type="button" className="secondary-button" disabled={busy}
              onClick={() => void submit({ action: "remove-path", workspaceId, pathId: link.id })}>{t("remove")}</button>
          </div>
        </li>)}
      </ul>
      <form onSubmit={(event) => {
        event.preventDefault();
        if (!path.alias.trim() || !path.path.trim()) return;
        void submit({
          action: path.id ? "update-path" : "add-path", workspaceId,
          pathId: path.id, alias: path.alias.trim(), path: path.path.trim(),
        }, () => setPath({ id: undefined, alias: "", path: "" }));
      }}>
        <label>{t("alias")}<input required maxLength={128} value={path.alias}
          onChange={(event) => setPath({ ...path, alias: event.target.value })} /></label>
        <label>{t("path")}<input required maxLength={4096} value={path.path}
          onChange={(event) => setPath({ ...path, path: event.target.value })} /></label>
        <button className="secondary-button" disabled={busy || !path.alias.trim() || !path.path.trim()}>{t(path.id ? "savePath" : "addPath")}</button>
      </form>
    </> : null}
    <div className="workspace-editor-actions">
      <button type="button" className="secondary-button" disabled={busy} onClick={onClose}>{t("close")}</button>
      {workspaceId ? <button type="button" className="secondary-button" disabled={busy}
        onClick={() => {
          if (confirmDelete) void submit({ action: "delete-workspace", workspaceId }, onClose);
          else setConfirmDelete(true);
        }}>{t(confirmDelete ? "confirmDelete" : "delete")}</button> : null}
    </div>
  </dialog>;
}
