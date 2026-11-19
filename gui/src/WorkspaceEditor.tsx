import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ProjectEntry, WorkspaceEdit, WorkspacePath } from "./client/projectDirectory";
import { useContextMenu } from "./ContextMenu";
import { UiIcon } from "./UiIcon";
import "./LocalHostGate.css";

interface WorkspaceEditorProps {
  readonly project?: ProjectEntry;
  readonly save: (edit: WorkspaceEdit) => Promise<void>;
  readonly onClose: () => void;
}

export function WorkspaceEditor({ project, save, onClose }: WorkspaceEditorProps) {
  const { t } = useTranslation("workspace", { keyPrefix: "workspaceEditor" });
  const openMenu = useContextMenu();
  const dialog = useRef<HTMLDialogElement>(null);
  const pathForm = useRef<HTMLFormElement>(null);
  useLayoutEffect(() => { dialog.current?.showModal(); }, []);
  const workspaceId = project?.id;
  const [name, setName] = useState(project?.name ?? "");
  const [path, setPath] = useState<{ id?: string; alias: string; path: string } | null>(null);
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

  const editingPath = path !== null;
  useLayoutEffect(() => {
    if (pathForm.current) pathForm.current.querySelector("input")?.focus();
  }, [path?.id, editingPath]);

  function close() {
    dialog.current?.close();
  }

  function updatePath(link: WorkspacePath) {
    setPath({ id: link.id, alias: link.alias, path: link.path });
  }

  return <dialog ref={dialog} className="frame-dialog session-delete-dialog workspace-editor" aria-labelledby="workspace-editor-heading"
    onClose={onClose} onCancel={(event) => { if (busy) event.preventDefault(); }}>
    <div className="local-host-panel">
      <div className="local-host-heading">
        <h2 id="workspace-editor-heading">{t(workspaceId ? "manage" : "create")}</h2>
        <button type="button" className="icon-close" aria-label={t("close")} disabled={busy} onClick={close}>
          <UiIcon name="close" />
        </button>
      </div>
      {error ? <p role="alert">{error}</p> : null}
      {savedPaths ? <p role="status">{t("savedPaths")}</p> : null}
      <form className="local-host-card" onSubmit={(event) => {
        event.preventDefault();
        if (!name.trim()) return;
        if (workspaceId) void submit({ action: "rename-workspace", workspaceId, name: name.trim() });
        else void submit({ action: "create-workspace", name: name.trim() }, close);
      }}>
        <label>{t("name")}<input autoFocus required maxLength={128} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <div className="local-host-actions">
          <button disabled={busy || !name.trim() || name === project?.name}>{t(workspaceId ? "rename" : "create")}</button>
        </div>
      </form>
      {workspaceId ? <>
        <section className="local-host-card" aria-label={t("paths")}>
          <div className="local-host-heading">
            <h3>{t("paths")}</h3>
            <button type="button" className="icon-button" aria-label={t("addPath")} title={t("addPath")}
              disabled={busy} onClick={() => setPath({ alias: "", path: "" })}><UiIcon name="plus" /></button>
          </div>
          {project.paths?.length ? <div role="list" aria-label={t("paths")}>
            {project.paths.map((link) => {
              const isDefault = project.defaultPathId === link.id;
              return <div className="local-host-card local-host-info" key={link.id} role="listitem">
                <div className="local-host-heading">
                  <h4>{link.alias}</h4>
                  <button type="button" className="icon-button" aria-haspopup="menu" aria-label={t("pathActions", { alias: link.alias })}
                    disabled={busy} onClick={(event) => openMenu(event, [
                      { label: t("editPath"), run: () => updatePath(link) },
                      { label: t(isDefault ? "clearDefault" : "makeDefault"),
                        disabled: !isDefault && link.status !== "available",
                        run: () => submit({ action: "set-default-path", workspaceId, pathId: isDefault ? undefined : link.id }) },
                      { label: t("remove"), danger: true, run: () => submit({ action: "remove-path", workspaceId, pathId: link.id }) },
                    ])}><UiIcon name="chevron-down" /></button>
                </div>
                <code>{link.path}</code>
                {isDefault ? <p>{t("defaultPath")}</p> : null}
                {link.status !== "available" ? <p>{t(link.status)}</p> : null}
              </div>;
            })}
          </div> : null}
          {path ? <form ref={pathForm} className="local-host-panel" onSubmit={(event) => {
            event.preventDefault();
            if (!path.alias.trim() || !path.path.trim()) return;
            void submit({
              action: path.id ? "update-path" : "add-path", workspaceId,
              pathId: path.id, alias: path.alias.trim(), path: path.path.trim(),
            }, () => setPath(null));
          }}>
            <label>{t("alias")}<input required maxLength={128} value={path.alias}
              onChange={(event) => setPath({ ...path, alias: event.target.value })} /></label>
            <label>{t("path")}<input required maxLength={4096} value={path.path}
              onChange={(event) => setPath({ ...path, path: event.target.value })} /></label>
            <div className="local-host-actions">
              <button type="button" disabled={busy} onClick={() => setPath(null)}>{t("cancel")}</button>
              <button disabled={busy || !path.alias.trim() || !path.path.trim()}>{t(path.id ? "savePath" : "addPath")}</button>
            </div>
          </form> : null}
        </section>
        <div className="local-host-actions">
          {confirmDelete ? <button type="button" disabled={busy} onClick={() => setConfirmDelete(false)}>{t("cancel")}</button> : null}
          <button type="button" className="host-danger" disabled={busy} onClick={() => {
            if (confirmDelete) void submit({ action: "delete-workspace", workspaceId }, close);
            else setConfirmDelete(true);
          }}>{t(confirmDelete ? "confirmDelete" : "delete")}</button>
        </div>
      </> : null}
    </div>
  </dialog>;
}
