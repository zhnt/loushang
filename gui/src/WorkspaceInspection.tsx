import { useEffect, useEffectEvent, useState } from "react";
import { useTranslation } from "react-i18next";

export interface Inspection {
  git: { root: string; branch: string; commit: string; worktree: string } | null;
  changes: readonly { path: string; kind: "staged" | "unstaged" | "untracked"; added: number | null; removed: number | null }[];
  toolchains: readonly { name: string; declared?: string; detected?: string; environment?: string }[];
  sessionChanges?: readonly { path: string; created: boolean; added: number | null; removed: number | null }[];
  sessionDiff?: string;
  stagedDiff?: string;
  unstagedDiff?: string;
  limited: boolean;
}

export function OpenWorkspacePath({ file, open }: {
  readonly file?: string;
  readonly open: (file?: string) => Promise<void>;
}) {
  const { t } = useTranslation("workspace");
  const [status, setStatus] = useState<"idle" | "opening" | "failed">("idle");
  async function activate() {
    setStatus("opening");
    try {
      await open(file);
      setStatus("idle");
    } catch {
      setStatus("failed");
    }
  }
  return <span className="workspace-open">
    <button type="button" disabled={status === "opening"} onClick={() => void activate()}>
      {file ? <code>{file}</code> : t("inspection.openFolder")}
    </button>
    {status === "failed" && <span role="status">{t("inspection.openFailed")}</span>}
  </span>;
}

export function WorkspaceInspection({ load, review, revision }: {
  readonly load: (review: boolean) => Promise<Inspection>;
  readonly review: boolean;
  readonly revision: string;
}) {
  const { t } = useTranslation("workspace");
  const [report, setReport] = useState<Inspection | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const request = useEffectEvent(() => load(review));
  useEffect(() => {
    let current = true;
    setError(false);
    setReport(null);
    void request().then(
      (next) => { if (current) setReport(next); },
      () => { if (current) setError(true); },
    );
    return () => { current = false; };
  }, [refresh, revision, review]);

  return <section className="panel-stack workspace-inspection">
    <button type="button" className="inspection-refresh" onClick={() => setRefresh((value) => value + 1)}>{t("inspection.refresh")}</button>
    {error ? <p role="status">{t("inspection.failed")}</p> : !report ? <p role="status">{t("inspection.loading")}</p>
      : review ? <>
        {!report.git ? report.sessionChanges?.length ? <section>
          <h2>{t("inspection.sessionChanges")}</h2>
          <p>{t("inspection.sessionBasis")}</p>
          <ul className="inspection-files">
            {report.sessionChanges.map((file) => <li key={file.path}>
              <code>{file.path}</code>
              {file.added === null || file.removed === null
                ? <span>{t(file.created ? "inspection.created" : "inspection.modified")}</span>
                : <ChangeStat added={file.added} removed={file.removed} />}
            </li>)}
          </ul>
          {report.sessionDiff && <InspectionDiff patch={report.sessionDiff} />}
        </section> : <p>{t("inspection.noBaseline")}</p> : <>
          {report.changes.length === 0 && <p>{t(report.limited ? "inspection.limited" : "inspection.clean")}</p>}
          {(["staged", "unstaged", "untracked"] as const).map((kind) => {
            const files = report.changes.filter((file) => file.kind === kind);
            const patch = kind === "untracked" ? undefined : report[kind === "staged" ? "stagedDiff" : "unstagedDiff"];
            if (!files.length && !patch) return null;
            return <section key={kind}>
              <h2>{t(`inspection.${kind}`)}</h2>
              <ul className="inspection-files">
                {files.map((file) => <li key={file.path}>
                  <code>{file.path}</code>
                  {file.added !== null && file.removed !== null && <ChangeStat added={file.added} removed={file.removed} />}
                </li>)}
              </ul>
              {patch && <InspectionDiff patch={patch} />}
            </section>;
          })}
        </>}
        {report.limited && (report.changes.length > 0 || !report.git) && <p>{t("inspection.limited")}</p>}
      </> : <>
        {report.git && <section>
          <h2>Git</h2>
          {!report.limited && <p>{report.changes.length
            ? t("inspection.changedFiles", { count: new Set(report.changes.map(({ path }) => path)).size })
            : t("inspection.clean")}</p>}
          <dl className="detail-list">
            <div><dt>{t("inspection.branch")}</dt><dd>{report.git.branch || t("inspection.detached")}</dd></div>
            {report.git.commit && <div><dt>Commit</dt><dd><code title={report.git.commit}>{report.git.commit.slice(0, 12)}</code></dd></div>}
            <div><dt>{t("environment.root")}</dt><dd><code>{report.git.root}</code></dd></div>
            {report.git.worktree && <div><dt>Worktree</dt><dd>{report.git.worktree}</dd></div>}
          </dl>
        </section>}
        {report.toolchains.map((tool) => <section key={tool.name}>
          <h2>{tool.name}</h2>
          <dl className="detail-list">
            {!tool.declared && !tool.detected && !tool.environment && <div><dt>{t("inspection.detected")}</dt><dd>{t("environment.unavailable")}</dd></div>}
            {tool.declared && <div><dt>{t("inspection.declared")}</dt><dd>{tool.declared}</dd></div>}
            {tool.detected && <div><dt>{t("inspection.detected")}</dt><dd>{tool.detected}</dd></div>}
            {tool.environment && <div><dt>{t("inspection.virtualEnv")}</dt><dd><code>{tool.environment}</code></dd></div>}
          </dl>
        </section>)}
      </>}
  </section>;
}

function ChangeStat({ added, removed }: { readonly added: number; readonly removed: number }) {
  return <span className="inspection-stat"><span>+{added}</span><span>−{removed}</span></span>;
}

function InspectionDiff({ patch }: { readonly patch: string }) {
  const { t } = useTranslation("workspace");
  return <details>
    <summary>{t("inspection.showDiff")}</summary>
    <pre tabIndex={0} className="inspection-diff">{patch.split("\n").map((line, index) =>
      <span key={index} className={line.startsWith("+") && !line.startsWith("+++") ? "added"
        : line.startsWith("-") && !line.startsWith("---") ? "removed" : undefined}>{line}{"\n"}</span>
    )}</pre>
  </details>;
}
