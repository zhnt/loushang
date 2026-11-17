import { createContext, memo, useContext, type ReactNode } from "react";
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
const OpenFile = createContext<((file: FileReference, trigger: HTMLButtonElement) => void) | undefined>(undefined);

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
  return <button className="markdown-file-reference" type="button" aria-haspopup="dialog"
    onClick={(event) => open?.(file, event.currentTarget)}>
    <OpenFile.Provider value={undefined}>{children}</OpenFile.Provider>
  </button>;
}

function MarkdownLink({ url, children }: { readonly url?: string; readonly children: ReactNode }) {
  const open = useContext(OpenFile);
  const label = <OpenFile.Provider value={undefined}>{children}</OpenFile.Provider>;
  if (url && /^https?:\/\//i.test(url)) {
    return <a href={url} target="_blank" rel="noopener noreferrer">{label}</a>;
  }
  const file = url && open ? markdownFileReference(url) : undefined;
  return file ? <FileReferenceButton file={file}>{children}</FileReferenceButton> : <span>{label}</span>;
}

const components: Components = {
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

export const MessageMarkdown = memo(function MessageMarkdown({ text, openFile, codeToolbar = true }: {
  readonly text: string;
  readonly codeToolbar?: boolean;
  readonly openFile?: (file: FileReference, trigger: HTMLButtonElement) => void;
}) {
  return <div className="markdown-body">
    <CodeToolbar.Provider value={codeToolbar}><OpenFile.Provider value={openFile}>
      <Markdown skipHtml remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} urlTransform={(url, attribute) =>
        attribute === "href" && (/^https?:\/\//i.test(url) || (openFile && markdownFileReference(url))) ? url : undefined
      } components={components}>{text}</Markdown>
    </OpenFile.Provider></CodeToolbar.Provider>
  </div>;
});
