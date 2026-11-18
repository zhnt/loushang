import { useTranslation } from "react-i18next";
import type { Inspection } from "./WorkspaceInspection";
import { UiIcon, type UiIconName } from "./UiIcon";

export function ReviewNotice({ title, detail, icon = "review", busy = false }: {
  readonly title: string;
  readonly detail?: string;
  readonly icon?: UiIconName;
  readonly busy?: boolean;
}) {
  return <div className="review-notice" role="status" aria-busy={busy}>
    <UiIcon name={icon} />
    <h2>{title}</h2>
    {detail && <p>{detail}</p>}
  </div>;
}

type Change = { path: string; added: number | null; removed: number | null; created?: boolean };

export function WorkspaceReview({ report }: { readonly report: Inspection }) {
  const { t } = useTranslation("workspace");
  const sessionFiles = report.sessionChanges ?? [];
  const hasChanges = report.git
    ? [report.changes.length, report.stagedDiff, report.unstagedDiff].some(Boolean)
    : sessionFiles.length > 0;
  if (!hasChanges) {
    const basis = report.git ? "git" : report.sessionChanges ? "session" : null;
    return <EmptyReview basis={basis} limited={report.limited} />;
  }
  return <div className="inspection-groups">
    {report.git ? <GitChanges report={report} /> : <ReviewGroup
      title={t("inspection.sessionChanges")} detail={t("inspection.sessionBasis")}
      files={sessionFiles} patch={report.sessionDiff} session />}
    {report.limited && <p className="inspection-note" role="status">{t("inspection.limited")}</p>}
  </div>;
}

function EmptyReview({ basis, limited }: { readonly basis: "git" | "session" | null; readonly limited: boolean }) {
  const { t } = useTranslation("workspace");
  if (limited) return <ReviewNotice title={t("inspection.reviewIncomplete")} detail={t("inspection.limited")} />;
  return basis
    ? <ReviewNotice title={t("inspection.clean")}
      detail={t(basis === "git" ? "inspection.reviewEmptyDetail" : "inspection.reviewSessionEmptyDetail")} />
    : <ReviewNotice title={t("inspection.reviewUnavailable")} detail={t("inspection.noBaseline")} />;
}

function GitChanges({ report }: { readonly report: Inspection }) {
  const { t } = useTranslation("workspace");
  return (["staged", "unstaged", "untracked"] as const).map((kind) => (
    <ReviewGroup key={kind} title={t(`inspection.${kind}`)}
      files={report.changes.filter((file) => file.kind === kind)}
      patch={kind === "untracked" ? undefined : report[kind === "staged" ? "stagedDiff" : "unstagedDiff"]} />
  ));
}

function ReviewGroup({ files, title, detail, patch, session = false }: {
  readonly files: readonly Change[];
  readonly title: string;
  readonly detail?: string;
  readonly patch?: string;
  readonly session?: boolean;
}) {
  const { t } = useTranslation("workspace");
  if (!files.length && !patch) return null;
  const { byFile, remaining } = groupPatch(patch, files, session);
  return <section className="inspection-group">
    <h2>{title}</h2>
    {detail && <p className="inspection-note">{detail}</p>}
    <ul className="inspection-files">
      {files.map((file) => <ReviewFile key={file.path} file={file} patch={byFile.get(file.path)} />)}
    </ul>
    {remaining && <details className="inspection-extra-diff">
      <summary>{t("inspection.showDiff")}</summary>
      <DiffText patch={remaining} />
    </details>}
  </section>;
}

function ReviewFile({ file, patch }: { readonly file: Change; readonly patch?: string }) {
  const label = <FileLabel file={file} />;
  return <li>{patch ? <details>
    <summary className="inspection-file-row">
      {label}<UiIcon name="chevron-down" />
    </summary>
    <DiffText patch={patch} />
  </details> : <div className="inspection-file-row">{label}</div>}</li>;
}

function FileLabel({ file }: { readonly file: Change }) {
  const { t } = useTranslation("workspace");
  return <>
    <code title={file.path}>{file.path}</code>
    <span className="inspection-stat">
      {file.added !== null && file.removed !== null
        ? <><span>+{file.added}</span><span>−{file.removed}</span></>
        : file.created === undefined ? null : t(file.created ? "inspection.created" : "inspection.modified")}
    </span>
  </>;
}

function groupPatch(patch: string | undefined, files: readonly Change[], session: boolean) {
  const byFile = new Map<string, string>();
  const remaining: string[] = [];
  const headers = new Map(files.flatMap(({ path }) => patchHeaders(path, session).map((header) => [header, path] as const)));
  const boundary = session ? /(?=^--- .+\n\+\+\+ .+\n@@)/m : /(?=^diff --git )/m;
  for (const block of patch?.split(boundary) ?? []) {
    const filename = headers.get(block.split("\n", 1)[0]);
    if (filename === undefined) remaining.push(block);
    else byFile.set(filename, (byFile.get(filename) ?? "") + block);
  }
  return { byFile, remaining: remaining.join("") };
}

function patchHeaders(path: string, session: boolean): string[] {
  if (session) return [`--- ${path}`];
  return [
    `diff --git a/${path} b/${path}`,
    `diff --git ${quoteGitPath(`a/${path}`)} ${quoteGitPath(`b/${path}`)}`,
  ];
}

function quoteGitPath(path: string): string {
  const escaped = Array.from(new TextEncoder().encode(path), (byte) => {
    const text = String.fromCharCode(byte);
    if (text === '"' || text === "\\") return "\\" + text;
    return byte < 32 || byte >= 127 ? `\\${byte.toString(8).padStart(3, "0")}` : text;
  }).join("");
  return `"${escaped}"`;
}

function DiffText({ patch }: { readonly patch: string }) {
  return <pre tabIndex={0} className="inspection-diff">{patch.split("\n").map((line, index) =>
    <span key={index} className={line.startsWith("+") && !line.startsWith("+++") ? "added"
      : line.startsWith("-") && !line.startsWith("---") ? "removed" : undefined}>{line}{"\n"}</span>
  )}</pre>;
}
