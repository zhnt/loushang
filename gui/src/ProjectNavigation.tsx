import { useState } from "react";
import { useTranslation } from "react-i18next";
import { UiIcon } from "./UiIcon";
import { TEMPORARY_WORKSPACE, type ProjectChat, type ProjectNavigationProps } from "./client/projectDirectory";

export function ProjectNavigation({ navigation, selectedId, titles }: {
  navigation: ProjectNavigationProps;
  selectedId: string | null;
  titles: Readonly<Record<string, string>>;
}) {
  const { t } = useTranslation("workspace");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [path, setPath] = useState("");
  const editable = navigation.available && !navigation.pending;

  function chat(workspace: string, session: ProjectChat) {
    const selected = selectedId === session.id;
    const name = titles[session.id] ?? session.title;
    const title = name === "New Session" ? t("sidebar.newSession") : name;
    return <div className="session-row" key={session.id}>
      <button type="button" className="project-chat"
        aria-current={selected ? "true" : undefined} disabled={!navigation.available}
        onClick={() => navigation.select(workspace, session.id)}>{title}</button>
      <button type="button" className="session-pin" data-pinned={session.pinned}
        aria-pressed={session.pinned} disabled={!editable}
        aria-label={t(session.pinned ? "sidebar.unpinChat" : "sidebar.pinChat", { title })}
        onClick={() => navigation.togglePin(session)}><UiIcon name="pin" /></button>
    </div>;
  }

  return <>
    <section className="project-navigation" aria-label={t("sidebar.projects")}>
      <div className="project-heading">
        <h2 className="section-label">{t("sidebar.projects")}</h2>
        <button type="button" className="project-action" aria-label={t("sidebar.addProject")}
          title={t("sidebar.addProject")} disabled={!editable} onClick={navigation.openFolder}>+</button>
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
      {navigation.directory.projects.map((project) => {
        const label = project.path.split(/[\\/]/).filter(Boolean).pop() ?? project.path;
        const expanded = !collapsed.has(project.path);
        return <div key={project.path}>
          <div className="project-heading project-row">
            <button type="button" className="project-label" aria-expanded={expanded} title={project.path}
              onClick={() => setCollapsed((old) => {
                const next = new Set(old);
                if (expanded) next.add(project.path);
                else next.delete(project.path);
                return next;
              })}><UiIcon name="folder" /><span>{label}</span></button>
            <button type="button" className="project-action" disabled={!editable}
              aria-label={t("sidebar.newProjectChat", { project: label })} title={t("sidebar.newProjectChat", { project: label })}
              onClick={() => { setCollapsed((old) => new Set([...old].filter((key) => key !== project.path))); navigation.create(project.path); }}>+</button>
          </div>
          {expanded ? <div className="project-chats">{project.sessions.map((session) => chat(project.path, session))}</div> : null}
        </div>;
      })}
    </section>
    <section className="project-navigation" aria-label={t("sidebar.chats")}>
      <h2 className="section-label">{t("sidebar.chats")}</h2>
      {navigation.directory.temporarySessions.map((session) => chat(TEMPORARY_WORKSPACE, session))}
    </section>
  </>;
}
