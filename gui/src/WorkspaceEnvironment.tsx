import { useTranslation } from "react-i18next";
import type { Inspection } from "./WorkspaceInspection";

export function WorkspaceEnvironment({ report, workspacePath }: {
  readonly report: Inspection;
  readonly workspacePath?: string;
}) {
  return <div className="inspection-groups">
    {report.git && <GitEnvironment report={report} git={report.git} workspacePath={workspacePath} />}
    {report.toolchains.map((tool) => <ToolchainEnvironment key={tool.name} tool={tool} />)}
  </div>;
}

function GitEnvironment({ report, git, workspacePath }: {
  readonly report: Inspection;
  readonly git: NonNullable<Inspection["git"]>;
  readonly workspacePath?: string;
}) {
  const { t } = useTranslation("workspace");
  const changedFiles = new Set(report.changes.map(({ path }) => path)).size;
  return <section className="inspection-group">
    <header className="inspection-group-heading">
      <h2>{t("inspection.git")}</h2>
      {!report.limited && <span>{changedFiles ? t("inspection.changedFiles", { count: changedFiles }) : t("inspection.clean")}</span>}
    </header>
    <dl className="inspection-fields">
      <div><dt>{t("inspection.branch")}</dt><dd>{git.branch || t("inspection.detached")}</dd></div>
      {git.commit && <div><dt>{t("inspection.commit")}</dt><dd><code title={git.commit}>{git.commit.slice(0, 12)}</code></dd></div>}
      {git.root !== workspacePath &&
        <div><dt>{t("inspection.repositoryRoot")}</dt><dd><code title={git.root}>{git.root}</code></dd></div>}
      {git.worktree && <div><dt>{t("inspection.worktree")}</dt><dd>{git.worktree}</dd></div>}
    </dl>
  </section>;
}

function ToolchainEnvironment({ tool }: { readonly tool: Inspection["toolchains"][number] }) {
  const { t } = useTranslation("workspace");
  return <section className="inspection-group">
    <h2>{tool.name}</h2>
    <dl className="inspection-fields">
      {!tool.declared && !tool.detected && !tool.environment &&
        <div><dt>{t("inspection.detected")}</dt><dd>{t("environment.unavailable")}</dd></div>}
      {tool.declared && <div><dt>{t("inspection.declared")}</dt><dd>{tool.declared}</dd></div>}
      {tool.detected && <div><dt>{t("inspection.detected")}</dt><dd>{tool.detected}</dd></div>}
      {tool.environment && <div><dt>{t("inspection.virtualEnv")}</dt><dd><code title={tool.environment}>{tool.environment}</code></dd></div>}
    </dl>
  </section>;
}
