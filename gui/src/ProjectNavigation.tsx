import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useContextMenu } from "./ContextMenu";
import { UiIcon } from "./UiIcon";
import { WorkspaceEditor } from "./WorkspaceEditor";
import { projectKey, TEMPORARY_WORKSPACE, workspaceName, type ProjectChat, type ProjectNavigationProps } from "./client/projectDirectory";

export function ProjectNavigation({ navigation, selectedId, titles, hiddenSessions }: {
  navigation: ProjectNavigationProps;
  selectedId: string | null;
  titles: Readonly<Record<string, string>>;
  hiddenSessions?: ReadonlySet<string>;
}) {
  const { t } = useTranslation("workspace");
  const openMenu = useContextMenu();
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const [deletion, setDeletion] = useState<{ workspace: string; session: ProjectChat; title: string; hostKey: string } | null>(null);
  const [deleteFailed, setDeleteFailed] = useState(false);
  const [deleting, setDeleting] = useState(false);
  useLayoutEffect(() => {
    if (deletion?.hostKey === navigation.hostKey) deleteDialog.current?.showModal();
    else deleteDialog.current?.close();
  }, [deletion, navigation.hostKey]);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [path, setPath] = useState("");
  const [editing, setEditing] = useState<{ host: string; workspace?: string } | null>(null);
  const editable = navigation.available && !navigation.pending;
  const createDisabled = navigation.createDisabled ?? !editable;
  const { projects, temporarySessions } = navigation.directory;
  const visible = (chat: ProjectChat) => !hiddenSessions?.has(chat.id)
    && !(chat.continuityId && hiddenSessions?.has(chat.continuityId));
  const pinned = [
    ...projects.flatMap((project) => project.sessions.filter((session) => session.pinned && visible(session))
      .map((session) => ({ workspace: projectKey(project), session }))),
    ...temporarySessions.filter((session) => session.pinned && visible(session))
      .map((session) => ({ workspace: TEMPORARY_WORKSPACE, session })),
  ];
  const sidebar = useRef<HTMLDivElement>(null);
  const pinFocus = useRef<{ id: string; pinned: boolean } | null>(null);
  const [chatTooltip, setChatTooltip] = useState<{ text: string; workspace?: string; position: CSSProperties } | null>(null);

  useEffect(() => {
    if (!chatTooltip) return;
    const hide = () => setChatTooltip(null);
    const dismiss = (event: KeyboardEvent) => { if (event.key === "Escape") hide(); };
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    window.addEventListener("keydown", dismiss);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
      window.removeEventListener("keydown", dismiss);
    };
  }, [chatTooltip]);

  function showChatTooltip(button: HTMLButtonElement, text: string, workspace?: string) {
    const labels = Array.from(button.children);
    if (!labels.some((label) => label.scrollWidth > label.clientWidth)) return;
    const bounds = button.getBoundingClientRect();
    const left = Math.max(8, Math.min(bounds.left, window.innerWidth - 288));
    const position = bounds.top < 120 ? { left, top: bounds.bottom + 4 } : { left, bottom: window.innerHeight - bounds.top + 4 };
    setChatTooltip({ text, workspace, position });
  }

  useLayoutEffect(() => {
    const expected = pinFocus.current;
    if (!expected) return;
    const button = Array.from(sidebar.current?.querySelectorAll<HTMLButtonElement>("[data-pin-session]") ?? [])
      .find((item) => item.dataset.pinSession === expected.id && item.dataset.pinned === String(expected.pinned));
    if (button) {
      pinFocus.current = null;
      if (document.activeElement === document.body) button.focus();
    }
  }, [navigation.directory]);

  const sessionTitle = (session: ProjectChat) => titles[session.id] ?? session.title;

  function expand(workspace: string) {
    setCollapsed((current) => new Set([...current].filter((key) => key !== workspace)));
  }

  async function confirmDeletion() {
    if (!editable || deleting || !deletion || deletion.hostKey !== navigation.hostKey || !navigation.deleteChat) return;
    setDeleting(true);
    setDeleteFailed(false);
    try {
      if (await navigation.deleteChat(deletion.workspace, deletion.session)) deleteDialog.current?.close();
      else setDeleteFailed(true);
    } finally {
      setDeleting(false);
    }
  }

  function chat(workspace: string, session: ProjectChat, showWorkspace = false) {
    const selected = selectedId === session.id;
    const name = sessionTitle(session);
    const project = projects.find((item) => projectKey(item) === workspace);
    const label = workspace === TEMPORARY_WORKSPACE ? t("sidebar.temporaryChats")
      : project?.name ?? workspaceName(project?.path ?? workspace);
    const scopeLabel = showWorkspace ? label : undefined;
    const title = name === "New Session" ? t("sidebar.newSession") : name;
    function togglePin() {
      if (session.pinned && collapsed.has(workspace)) expand(workspace);
      navigation.togglePin(session);
    }
    return <div className={selected ? "session-row selected" : "session-row"} key={session.id}>
      <button type="button" className="project-chat"
        aria-current={selected ? "true" : undefined} disabled={!navigation.available}
        onPointerEnter={(event) => {
          if (event.pointerType !== "touch") showChatTooltip(event.currentTarget, title, scopeLabel);
        }}
        onPointerLeave={() => setChatTooltip(null)}
        onFocus={(event) => {
          if (event.currentTarget.matches(":focus-visible")) showChatTooltip(event.currentTarget, title, scopeLabel);
        }}
        onBlur={() => setChatTooltip(null)}
        onClick={() => { setChatTooltip(null); navigation.select(workspace, session.id); }}
        onContextMenu={(event) => {
          setChatTooltip(null);
          openMenu(event, [
            { label: t(session.pinned ? "sidebar.unpin" : "sidebar.pin"), disabled: !editable, run: togglePin },
            ...(navigation.deleteChat ? [{
              label: t("sidebar.deleteChat"), disabled: !editable, danger: true,
              run: () => {
                setDeleteFailed(false);
                setDeletion({ workspace, session, title, hostKey: navigation.hostKey });
              },
            }] : []),
          ]);
        }}>
        <span className="project-chat-title">{title}</span>
        {scopeLabel ? <small className="project-chat-scope" aria-hidden="true">
          {scopeLabel}
        </small> : null}
      </button>
      <button type="button" className="session-pin" data-pinned={session.pinned} data-pin-session={session.id}
        aria-pressed={session.pinned} disabled={!editable}
        aria-label={t(session.pinned ? "sidebar.unpinChat" : "sidebar.pinChat", { title })}
        onClick={(event) => {
          pinFocus.current = event.currentTarget === document.activeElement
            ? { id: session.id, pinned: !session.pinned } : null;
          togglePin();
        }}><UiIcon name="pin" /></button>
    </div>;
  }

  function projectMenu(event: MouseEvent<HTMLElement>) {
    if (navigation.editWorkspace) openMenu(event, [
      { label: t("sidebar.addProject"), disabled: !editable, run: navigation.openFolder },
      { label: t("workspaceEditor.create"), disabled: !editable, run: () => setEditing({ host: navigation.hostKey }) },
    ]);
  }

  return <div ref={sidebar}>
    {chatTooltip ? createPortal(<div className="sidebar-chat-tooltip" aria-hidden="true" style={chatTooltip.position}>
      {chatTooltip.text}{chatTooltip.workspace ? <small>{chatTooltip.workspace}</small> : null}
    </div>, document.body) : null}
    {pinned.length ? <section className="project-navigation" aria-label={t("sidebar.pinned")}>
      <h2 className="section-label">{t("sidebar.pinned")}</h2>
      {pinned.map(({ workspace, session }) => chat(workspace, session, true))}
    </section> : null}
    <section className="project-navigation" aria-label={t("sidebar.projects")}>
      <div className="project-heading">
        <h2 className="section-label" onContextMenu={projectMenu}>{t("sidebar.projects")}</h2>
        <button type="button" className="project-action" aria-label={t("sidebar.addProject")}
          title={t("sidebar.addProject")} disabled={!editable}
          onClick={navigation.openFolder} onContextMenu={projectMenu}><UiIcon name="plus" /></button>
      </div>
      {navigation.folderInput ? <form className="project-path" onSubmit={(event) => {
        event.preventDefault();
        if (path.trim() && editable) void navigation.register(path.trim()).then((accepted) => { if (accepted) setPath(""); });
      }}>
        <input autoFocus aria-label={t("localHost.pathHint")} placeholder={t("localHost.pathHint")}
          value={path} onChange={(event) => setPath(event.target.value)} />
        <button type="submit" disabled={!editable || !path.trim()}>{t("sidebar.addProject")}</button>
        <button type="button" onClick={navigation.closeFolder}>{t("localHost.cancel")}</button>
      </form> : null}
      {navigation.error ? <p className="project-error" role="alert">{t("localHost.workspaceUnavailable")}</p> : null}
      {projects.map((project) => {
        const workspace = projectKey(project);
        const label = project.name ?? workspaceName(project.path ?? workspace);
        const expanded = !collapsed.has(workspace);
        function create() {
          expand(workspace);
          navigation.create(workspace);
        }
        return <div key={workspace}>
          <div className="project-heading project-row">
            <button type="button" className="project-label" aria-expanded={expanded} title={project.path ?? undefined}
              onContextMenu={(event) => openMenu(event, [
                { label: t("sidebar.newSession"), disabled: createDisabled, run: create },
                ...(project.id && navigation.editWorkspace ? [{
                  label: t("workspaceEditor.manage"), disabled: !editable,
                  run: () => setEditing({ host: navigation.hostKey, workspace }),
                }] : []),
                ...(project.path ? [{
                  label: t("sidebar.copyProjectPath"), run: () => navigator.clipboard.writeText(project.path!),
                }] : []),
              ])}
              onClick={() => setCollapsed((old) => {
                const next = new Set(old);
                if (expanded) next.add(workspace);
                else next.delete(workspace);
                return next;
              })}><UiIcon name={expanded ? "folder" : "folder-closed"} /><span>{label}</span></button>
            <button type="button" className="project-action" disabled={createDisabled}
              aria-label={t("sidebar.newProjectChat", { project: label })} title={t("sidebar.newProjectChat", { project: label })}
              onClick={create}><UiIcon name="plus" /></button>
          </div>
          <div className="project-chats" aria-hidden={!expanded} inert={!expanded}>
            <div>
              {project.sessions.filter((session) => !session.pinned && visible(session)).map((session) => chat(workspace, session))}
            </div>
          </div>
        </div>;
      })}
    </section>
    <section className="project-navigation" aria-label={t("sidebar.chats")}>
      <h2 className="section-label">{t("sidebar.temporaryChats")}</h2>
      {temporarySessions.filter((session) => !session.pinned && visible(session)).map((session) => chat(TEMPORARY_WORKSPACE, session))}
    </section>
    {editing?.host === navigation.hostKey && navigation.editWorkspace
      && (!editing.workspace || projects.some((project) => projectKey(project) === editing.workspace)) ?
      <WorkspaceEditor
        key={editing.workspace ?? "new"}
        project={projects.find((project) => projectKey(project) === editing.workspace)}
        save={navigation.editWorkspace}
        onClose={() => setEditing(null)}
      /> : null}
    {navigation.deleteChat ? <dialog ref={deleteDialog} className="frame-dialog session-delete-dialog" aria-labelledby="delete-chat-heading"
      onClose={() => setDeletion(null)} onCancel={(event) => { if (deleting) event.preventDefault(); }}>
      <h2 id="delete-chat-heading">{t("sidebar.deleteChat")}</h2>
      <p>{t("sidebar.deleteChatPrompt", { title: deletion?.title ?? "" })}</p>
      {deleteFailed ? <p role="alert">{t("sidebar.deleteFailed")}</p> : null}
      <div className="session-delete-actions">
        <button type="button" autoFocus disabled={deleting} onClick={() => deleteDialog.current?.close()}>{t("sidebar.cancelDelete")}</button>
        <button type="button" disabled={deleting || !editable} onClick={() => { void confirmDeletion(); }}>{t("sidebar.confirmDelete")}</button>
      </div>
    </dialog> : null}
  </div>;
}
