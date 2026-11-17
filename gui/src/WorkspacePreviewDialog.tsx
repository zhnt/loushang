import { useEffect, useEffectEvent, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type Ref } from "react";
import { useTranslation } from "react-i18next";
import { CopyButton } from "./CopyButton";
import { UiIcon } from "./UiIcon";
import type { WorkspacePreview } from "./client/workspacePreview";
import { MessageMarkdown } from "./markdown/MessageMarkdown";
import type { FileReference } from "./markdown/fileReference";
import "./workspacePreview.css";

interface PreviewTarget extends FileReference { readonly base: string }
type PreviewResult =
  | { readonly content: WorkspacePreview }
  | { readonly error: ReturnType<typeof previewError> };

function previewError(error: unknown) {
  switch (error instanceof Error ? error.message : error) {
    case "not_found": return "preview.notFound";
    case "permission_denied":
    case "invalid_request": return "preview.denied";
    case "workspace_preview_binary": return "preview.binary";
    case "workspace_preview_too_large": return "preview.tooLarge";
    case "instance_changed": return "preview.connectionChanged";
    default: return "preview.failed";
  }
}

export function WorkspacePreviewDialog({ initial, theme, read, onClose }: {
  readonly initial: FileReference;
  readonly theme: string;
  readonly read: (reference: string, base: string) => Promise<WorkspacePreview>;
  readonly onClose: () => void;
}) {
  const title = useId();
  const details = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [history, setHistory] = useState<readonly PreviewTarget[]>([{ ...initial, base: "" }]);
  const target = history[history.length - 1]!;
  const [result, setResult] = useState<PreviewResult>();
  const load = useEffectEvent(() => read(target.path, target.base));
  function changeTarget(next: readonly PreviewTarget[]) {
    closeButton.current?.focus({ preventScroll: true });
    setResult(undefined);
    setHistory(next);
  }
  useLayoutEffect(() => {
    const node = dialog.current!;
    node.showModal();
    closeButton.current?.focus({ preventScroll: true });
    return () => { node.close(); };
  }, []);
  useEffect(() => {
    let active = true;
    void load().then(
      (content) => { if (active) setResult({ content }); },
      (error: unknown) => { if (active) setResult({ error: previewError(error) }); },
    );
    return () => { active = false; };
  }, [target]);

  const close = () => {
    dialog.current?.close();
    onClose();
  };
  return <dialog ref={dialog} className="workspace-preview markdown-reading" data-markdown-theme={theme}
    aria-labelledby={title} aria-describedby={details}
    onCancel={(event) => { event.preventDefault(); close(); }}>
    <PreviewHeader title={title} details={details} target={target} result={result}
      closeButton={closeButton} close={close} />
    <PreviewContents result={result} line={target.line}
      back={history.length > 1 ? () => changeTarget(history.slice(0, -1)) : undefined}
      navigate={(next, base) => changeTarget([...history, { ...next, base }])} />
  </dialog>;
}

function PreviewHeader({ title, details, target, result, closeButton, close }: {
  readonly title: string;
  readonly details: string;
  readonly target: PreviewTarget;
  readonly result?: PreviewResult;
  readonly closeButton: Ref<HTMLButtonElement>;
  readonly close: () => void;
}) {
  const { t } = useTranslation("workspace");
  const content = result && "content" in result ? result.content : undefined;
  const path = content?.path ?? target.path;
  const name = path.split(/[\\/]/).filter(Boolean).pop() ?? path;
  return <header className="workspace-preview-header">
    <div>
      <h2 id={title}>{path === "." ? t("preview.root") : name}</h2>
      <p id={details}>{t("preview.currentHost")}</p>
      <div className="workspace-preview-path"><code>{path}</code>{content && <PreviewFormat content={content} />}</div>
    </div>
    <button ref={closeButton} type="button" className="icon-button" onClick={close}
      aria-label={t("preview.close")}><UiIcon name="close" /></button>
  </header>;
}

const markdownFile = /\.(?:md|markdown|mdx)$/i;

function extension(path: string) {
  return path.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase();
}

function PreviewFormat({ content }: { readonly content: WorkspacePreview }) {
  const { t } = useTranslation("workspace");
  const format = content.kind === "directory" ? t("preview.directory")
    : markdownFile.test(content.path) ? "Markdown" : extension(content.path) ?? t("preview.text");
  return <span>{format}</span>;
}

type Navigate = (file: FileReference, base: string) => void;

function PreviewContents({ result, line, back, navigate }: {
  readonly result?: PreviewResult;
  readonly line?: number;
  readonly back?: () => void;
  readonly navigate: Navigate;
}) {
  const { t } = useTranslation("workspace");
  if (!result) return <div className="workspace-preview-body"><p role="status">{t("preview.loading")}</p></div>;
  if ("error" in result) return <>
    <PreviewActions back={back} />
    <div className="workspace-preview-body"><p role="alert">{t(result.error)}</p></div>
  </>;
  const { content } = result;
  if (content.kind === "file") return <FilePreview file={content} line={line} back={back} navigate={navigate} />;
  return <>
    <PreviewActions back={back} path={content.path} />
    <div className="workspace-preview-body"><DirectoryPreview directory={content} navigate={navigate} /></div>
  </>;
}

function PreviewActions({ back, path, children }: {
  readonly back?: () => void;
  readonly path?: string;
  readonly children?: ReactNode;
}) {
  const { t } = useTranslation("workspace");
  return <div className="workspace-preview-actions">
    {back && <button type="button" className="secondary-button" onClick={back}>{t("preview.back")}</button>}
    {path && <CopyButton text={path} showLabel label={t("preview.copyPath")} />}
    {children}
  </div>;
}

function FilePreview({ file, line, back, navigate }: {
  readonly file: Extract<WorkspacePreview, { kind: "file" }>;
  readonly line?: number;
  readonly back?: () => void;
  readonly navigate: Navigate;
}) {
  const { t } = useTranslation("workspace");
  const [source, setSource] = useState(Boolean(line));
  const isMarkdown = markdownFile.test(file.path);
  const reading = isMarkdown && !source;
  const base = file.path.split("/").slice(0, -1).join("/");
  return <>
    <PreviewActions back={back} path={file.path}>
      <CopyButton text={file.text} showLabel label={t("preview.copyContent")} />
      {isMarkdown && <button type="button" className="secondary-button" aria-pressed={source}
        onClick={() => setSource(!source)}>{t("preview.source")}</button>}
      {line && !reading ? <span className="workspace-preview-line">{t("preview.line", { line })}</span> : null}
    </PreviewActions>
    <div className="workspace-preview-body" key={String(reading)}>
      {reading ? <MessageMarkdown text={file.text} openFile={(reference) => navigate(reference, base)} />
        : <SourcePreview text={file.text} language={extension(file.path)} line={line} />}
    </div>
  </>;
}

function DirectoryPreview({ directory, navigate }: {
  readonly directory: Extract<WorkspacePreview, { kind: "directory" }>;
  readonly navigate: Navigate;
}) {
  const { t } = useTranslation("workspace");
  const base = directory.path === "." ? "" : directory.path;
  return <>
    <ul className="workspace-preview-entries">
      {base && <li><button type="button" onClick={() => navigate({ path: ".." }, base)}>{t("preview.parent")}</button></li>}
      {directory.entries.map((item) => <li key={item.name}>
        <button type="button" onClick={() => navigate({ path: item.name }, base)}>
          {item.name}{item.kind === "directory" ? "/" : ""}
        </button>
      </li>)}
    </ul>
    {!directory.entries.length && <p>{t("preview.empty")}</p>}
    {directory.limited && <p role="status">{t("preview.limited")}</p>}
  </>;
}

function SourcePreview({ text, language, line }: {
  readonly text: string;
  readonly language?: string;
  readonly line?: number;
}) {
  const body = useRef<HTMLDivElement>(null);
  // Use a fence longer than every run in the file so its contents stay literal.
  const fenceLength = Array.from(text.matchAll(/~{3,}/g)).reduce((max, run) => Math.max(max, run[0].length + 1), 3);
  const fence = "~".repeat(fenceLength);
  const fenced = fence + (language ?? "") + "\n" + text + (text.endsWith("\n") ? "" : "\n") + fence;
  useLayoutEffect(() => {
    const pre = body.current?.querySelector("pre");
    if (!pre || !line) return;
    pre.scrollTop = Math.max(0, line - 3) * Number.parseFloat(getComputedStyle(pre).lineHeight);
  }, [line, fenced]);
  return <div ref={body} className="workspace-preview-source"
    style={line ? { "--preview-line": line } as CSSProperties : undefined} data-located={Boolean(line)}>
    <MessageMarkdown text={fenced} codeToolbar={false} />
  </div>;
}
