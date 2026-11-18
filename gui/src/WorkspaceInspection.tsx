import { useEffect, useEffectEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { WorkspaceEnvironment } from "./WorkspaceEnvironment";
import { ReviewNotice, WorkspaceReview } from "./WorkspaceReview";
import { UiIcon } from "./UiIcon";

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

function errorCode(reason: unknown) {
  return reason instanceof Error ? reason.message : reason;
}

function pathError(reason: unknown) {
  const code = errorCode(reason);
  if (code === "not_found") return "missingPath";
  if (code === "workspace_unavailable") return "workspaceMismatch";
  return "openFailed";
}

export function OpenWorkspacePath({ file, open }: {
  readonly file?: string;
  readonly open: (file?: string) => Promise<void>;
}) {
  const { t } = useTranslation("workspace");
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<"missingPath" | "workspaceMismatch" | "openFailed" | null>(null);
  async function activate() {
    setOpening(true);
    setError(null);
    try {
      await open(file);
    } catch (reason) {
      setError(pathError(reason));
    } finally {
      setOpening(false);
    }
  }
  const label = t("inspection.openFolder");
  return <span className={file ? "workspace-open" : "workspace-open-folder"}>
    <button type="button" className={file ? "secondary-button" : "workspace-folder-action"} disabled={opening}
      aria-label={file ? undefined : label} title={file ? undefined : label} onClick={() => void activate()}>
      {file ? t("inspection.openInSystem") : <UiIcon name="folder" />}
    </button>
    {error && <span className="workspace-open-error" role="status">{t(`inspection.${error}`)}</span>}
  </span>;
}

type InspectionState =
  | { kind: "loading" }
  | { kind: "ready"; report: Inspection }
  | { kind: "failed"; reason: "updateHost" | "failed" };

function useInspection(load: (review: boolean) => Promise<Inspection>, review: boolean, revision: string, refresh: number) {
  const [state, setState] = useState<InspectionState>({ kind: "loading" });
  const request = useEffectEvent(() => load(review));
  useEffect(() => {
    let current = true;
    setState({ kind: "loading" });
    void request().then(
      (report) => { if (current) setState({ kind: "ready", report }); },
      (reason: unknown) => {
        const code = errorCode(reason);
        if (current) setState({ kind: "failed", reason: code === "workspace_inspection_unavailable" ? "updateHost" : "failed" });
      },
    );
    return () => { current = false; };
  }, [refresh, revision, review]);
  return state;
}

export function WorkspaceInspection({ load, review, revision, workspacePath, refresh = 0 }: {
  readonly load: (review: boolean) => Promise<Inspection>;
  readonly review: boolean;
  readonly revision: string;
  readonly workspacePath?: string;
  readonly refresh?: number;
}) {
  const { t } = useTranslation("workspace");
  const state = useInspection(load, review, revision, refresh);
  if (state.kind === "loading") return review
    ? <ReviewNotice title={t("inspection.loading")} icon="refresh" busy />
    : <p className="inspection-note" role="status">{t("inspection.loading")}</p>;
  if (state.kind === "failed") return review
    ? <ReviewNotice title={t(state.reason === "updateHost" ? "inspection.reviewUnavailable" : "inspection.reviewFailed")}
      detail={t(`inspection.${state.reason}`)} />
    : <p className="inspection-note" role="status">{t(`inspection.${state.reason}`)}</p>;
  return review ? <WorkspaceReview report={state.report} />
    : <WorkspaceEnvironment report={state.report} workspacePath={workspacePath} />;
}
