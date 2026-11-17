import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { UiIcon } from "./UiIcon";
import { TEMPORARY_WORKSPACE, workspaceName, type ProjectChat, type ProjectNavigationProps } from "./client/projectDirectory";

export interface SidebarDraft {
  readonly id: string;
  readonly workspace: string | null;
  readonly sessionId?: string;
  readonly title: string;
  readonly selected: boolean;
  readonly onSelect: () => void;
}

export function DraftChatRow({ draft }: { draft: SidebarDraft }) {
  return <div className={draft.selected ? "session-row selected" : "session-row"}>
    <button type="button" className="project-chat"
      aria-current={draft.selected ? "page" : undefined} onClick={draft.onSelect}>
      <span className="project-chat-title">{draft.title}</span>
    </button>
  </div>;
}

export function ProjectNavigation({ navigation, selectedId, titles, drafts = [] }: {
  navigation: ProjectNavigationProps;
  selectedId: string | null;
  titles: Readonly<Record<string, string>>;
  drafts?: readonly SidebarDraft[];
}) {
  const { t } = useTranslation("workspace");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [path, setPath] = useState("");
  const editable = navigation.available && !navigation.pending;
  const { projects, temporarySessions } = navigation.directory;
  const inDraft = (session: ProjectChat) => drafts.some((draft) => draft.sessionId === session.id);
  function draftRows(workspace: string | null) {
    return drafts.filter((draft) => draft.workspace === workspace)
      .map((draft) => <DraftChatRow key={draft.id} draft={draft} />);
  }
  const pinned = [
    ...projects.flatMap((project) => project.sessions.filter((session) => session.pinned && !inDraft(session))
      .map((session) => ({ workspace: project.path, session }))),
    ...temporarySessions.filter((session) => session.pinned && !inDraft(session))
      .map((session) => ({ workspace: TEMPORARY_WORKSPACE, session })),
  ];
  const sidebar = useRef<HTMLDivElement>(null);
  const pinFocus = useRef<{ id: string; pinned: boolean } | null>(null);

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

  function chat(workspace: string, session: ProjectChat, showWorkspace = false) {
    const selected = selectedId === session.id;
    const name = sessionTitle(session);
    const title = name === "New Session" ? t("sidebar.newSession") : name;
    return <div className={selected ? "session-row selected" : "session-row"} key={session.id}>
      <button type="button" className="project-chat"
        aria-current={selected ? "true" : undefined} disabled={!navigation.available}
        onClick={() => navigation.select(workspace, session.id)}>
        <span className="project-chat-title">{title}</span>
        {showWorkspace ? <small className="project-chat-scope" aria-hidden="true" title={workspace === TEMPORARY_WORKSPACE ? undefined : workspace}>
          {workspace === TEMPORARY_WORKSPACE ? t("sidebar.temporaryChats") : workspaceName(workspace)}
        </small> : null}
      </button>
      <button type="button" className="session-pin" data-pinned={session.pinned} data-pin-session={session.id}
        aria-pressed={session.pinned} disabled={!editable}
        aria-label={t(session.pinned ? "sidebar.unpinChat" : "sidebar.pinChat", { title })}
        onClick={(event) => {
          pinFocus.current = event.currentTarget === document.activeElement
            ? { id: session.id, pinned: !session.pinned } : null;
          if (session.pinned && collapsed.has(workspace)) {
            setCollapsed((old) => new Set([...old].filter((key) => key !== workspace)));
          }
          navigation.togglePin(session);
        }}><UiIcon name="pin" /></button>
    </div>;
  }

  return <div ref={sidebar}>
    {pinned.length ? <section className="project-navigation" aria-label={t("sidebar.pinned")}>
      <h2 className="section-label">{t("sidebar.pinned")}</h2>
      {pinned.map(({ workspace, session }) => chat(workspace, session, true))}
    </section> : null}
    <section className="project-navigation" aria-label={t("sidebar.projects")}>
      <div className="project-heading">
        <h2 className="section-label">{t("sidebar.projects")}</h2>
        <button type="button" className="project-action" aria-label={t("sidebar.addProject")}
          title={t("sidebar.addProject")} disabled={!editable}
          onClick={navigation.openFolder}><span className="sidebar-add-mark" aria-hidden="true" /></button>
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
        const label = workspaceName(project.path);
        const expanded = !collapsed.has(project.path);
        return <div key={project.path}>
          <div className="project-heading project-row">
            <button type="button" className="project-label" aria-expanded={expanded} title={project.path}
              onClick={() => setCollapsed((old) => {
                const next = new Set(old);
                if (expanded) next.add(project.path);
                else next.delete(project.path);
                return next;
              })}><UiIcon name={expanded ? "folder" : "folder-closed"} /><span>{label}</span></button>
            <button type="button" className="project-action" disabled={!editable}
              aria-label={t("sidebar.newProjectChat", { project: label })} title={t("sidebar.newProjectChat", { project: label })}
              onClick={() => { setCollapsed((old) => new Set([...old].filter((key) => key !== project.path))); navigation.create(project.path); }}><span className="sidebar-add-mark" aria-hidden="true" /></button>
          </div>
          <div className="project-chats" aria-hidden={!expanded} inert={!expanded}>
            <div>
              {draftRows(project.path)}
              {project.sessions.filter((session) => !session.pinned && !inDraft(session)).map((session) => chat(project.path, session))}
            </div>
          </div>
        </div>;
      })}
    </section>
    <section className="project-navigation" aria-label={t("sidebar.chats")}>
      <h2 className="section-label">{t("sidebar.temporaryChats")}</h2>
      {draftRows(null)}
      {temporarySessions.filter((session) => !session.pinned && !inDraft(session)).map((session) => chat(TEMPORARY_WORKSPACE, session))}
    </section>
  </div>;
}
