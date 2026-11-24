import { Children, createContext, memo, useContext, useState, type ReactNode } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import type { ElementContent } from "hast";
import { CopyButton } from "../CopyButton";
import { useTranslation } from "react-i18next";
import Markdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { inlineFileReference, markdownFileReference, type FileReference } from "./fileReference";
import "./markdown.css";

const languagePrefix = "language-";
const CodeToolbar = createContext(true);
type PreviewFile = (file: FileReference, trigger: HTMLButtonElement) => void;
type RevealFile = (path: string) => Promise<{ fileMissing: boolean }>;
const OpenFile = createContext<{ preview?: PreviewFile; reveal?: RevealFile } | undefined>(undefined);

function codeText(node: ElementContent): string {
  if (node.type === "text") return node.value;
  return node.type === "element" ? node.children.map(codeText).join("") : "";
}

function CodeBlock({ language, source, children }: { language?: string; source: string; children: ReactNode }) {
  const { t } = useTranslation("session");
  const toolbar = useContext(CodeToolbar);
  return <div className="markdown-code-block">
    {toolbar && <div className="markdown-code-label">
      <span>{language ?? t("transcript.plainTextCode")}</span>
      <CopyButton text={source} label={t("transcript.copyCode")} />
    </div>}
    <pre tabIndex={0}><OpenFile.Provider value={undefined}>{children}</OpenFile.Provider></pre>
  </div>;
}

function FileReferenceButton({ file, children }: { readonly file: FileReference; readonly children: ReactNode }) {
  const open = useContext(OpenFile);
  const { t } = useTranslation("workspace");
  const [notice, setNotice] = useState<"openedNearestFolder" | "openFailed">();
  async function reveal(action: RevealFile) {
    setNotice(undefined);
    try {
      if ((await action(file.path)).fileMissing) setNotice("openedNearestFolder");
    } catch {
      setNotice("openFailed");
    }
  }
  return <>
    <button className="markdown-file-reference" type="button" aria-haspopup={open?.preview ? "dialog" : undefined}
      data-tooltip={open?.reveal ? t("inspection.revealFile") : undefined}
      onClick={(event) => {
        if (open?.reveal) void reveal(open.reveal);
        else open?.preview?.(file, event.currentTarget);
      }}>
      <OpenFile.Provider value={undefined}>{children}</OpenFile.Provider>
    </button>
    {notice && <span className="markdown-file-notice" role={notice === "openFailed" ? "alert" : "status"}> {t(`inspection.${notice}`)}</span>}
  </>;
}

function MarkdownLink({ url, children }: { readonly url?: string; readonly children: ReactNode }) {
  const open = useContext(OpenFile);
  const label = <OpenFile.Provider value={undefined}>{children}</OpenFile.Provider>;
  if (url && /^https?:\/\//i.test(url)) {
    return isTauri() ? <DesktopWebLink url={url}>{label}</DesktopWebLink>
      : <a href={url} target="_blank" rel="noopener noreferrer">{label}</a>;
  }
  const file = url && open ? markdownFileReference(url) : undefined;
  return file ? <FileReferenceButton file={file}>{children}</FileReferenceButton> : <span>{label}</span>;
}

function DesktopWebLink({ url, children }: { readonly url: string; readonly children: ReactNode }) {
  const { t } = useTranslation("common");
  const [failed, setFailed] = useState(false);
  return <>
    <a href={url} onClick={(event) => {
      event.preventDefault();
      setFailed(false);
      void invoke("open_web_link", { url }).catch(() => setFailed(true));
    }}>{children}</a>
    {failed && <span className="markdown-link-error" role="alert"> {t("openLinkFailed")}</span>}
  </>;
}

function PlainFileReferences({ children }: { readonly children: ReactNode }) {
  const open = useContext(OpenFile);
  if (!open) return children;
  return Children.map(children, (child) => {
    if (typeof child !== "string") return child;
    const parts: ReactNode[] = [];
    let end = 0;
    for (const match of child.matchAll(/(?<![\w./\\:@%?-])(?:[\w.-]+[/\\])*[\w-][\w.-]*\.[a-z][\da-z]*(?![\w/\\-]|\.[\da-z])/gi)) {
      const file = inlineFileReference(match[0]);
      if (!file) continue;
      parts.push(child.slice(end, match.index), <FileReferenceButton key={match.index} file={file}>{match[0]}</FileReferenceButton>);
      end = match.index + match[0].length;
    }
    return parts.length ? [...parts, child.slice(end)] : child;
  });
}

const components: Components = {
  p: ({ children }) => <p><PlainFileReferences>{children}</PlainFileReferences></p>,
  li: ({ node: _node, children, ...props }) => <li {...props}><PlainFileReferences>{children}</PlainFileReferences></li>,
  strong: ({ children }) => <strong><PlainFileReferences>{children}</PlainFileReferences></strong>,
  em: ({ children }) => <em><PlainFileReferences>{children}</PlainFileReferences></em>,
  a: ({ href, children }) => <MarkdownLink url={href}>{children}</MarkdownLink>,
  img: ({ alt }) => alt ? <span>{alt}</span> : null,
  code: function InlineCode({ node: _node, children, ...props }) {
    const open = useContext(OpenFile);
    const file = typeof children === "string" && open ? inlineFileReference(children) : undefined;
    const code = <code {...props}>{children}</code>;
    return file ? <FileReferenceButton file={file}>{code}</FileReferenceButton> : code;
  },
  table: ({ children }) => <div className="markdown-table" tabIndex={0}><table>{children}</table></div>,
  pre: ({ node, children }) => {
    const code = node?.children[0];
    const classes = code?.type === "element" ? code.properties.className : undefined;
    const language = Array.isArray(classes)
      ? classes.find((value): value is string => typeof value === "string" && value.startsWith(languagePrefix))?.slice(languagePrefix.length)
      : undefined;
    return <CodeBlock language={language} source={code ? codeText(code) : ""}>{children}</CodeBlock>;
  },
};

export const MessageMarkdown = memo(function MessageMarkdown({ text, openFile, revealFile, codeToolbar = true }: {
  readonly text: string;
  readonly codeToolbar?: boolean;
  readonly openFile?: PreviewFile;
  readonly revealFile?: RevealFile;
}) {
  const fileAction = revealFile ? { reveal: revealFile } : openFile ? { preview: openFile } : undefined;
  return <div className="markdown-body">
    <CodeToolbar.Provider value={codeToolbar}><OpenFile.Provider value={fileAction}>
      <Markdown skipHtml remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} urlTransform={(url, attribute) =>
        attribute === "href" && (/^https?:\/\//i.test(url) || (fileAction && markdownFileReference(url))) ? url : undefined
      } components={components}>{text}</Markdown>
    </OpenFile.Provider></CodeToolbar.Provider>
  </div>;
});
