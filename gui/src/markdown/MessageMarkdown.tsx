import { memo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import Markdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import "./markdown.css";

const languagePrefix = "language-";

function CodeBlock({ language, children }: { language?: string; children: ReactNode }) {
  const { t } = useTranslation("session");
  return <div className="markdown-code-block">
    <div className="markdown-code-label">{language ?? t("transcript.plainTextCode")}</div>
    <pre tabIndex={0}>{children}</pre>
  </div>;
}

const components: Components = {
  a: ({ href, children }) => href
    ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    : <span>{children}</span>,
  img: ({ alt }) => alt ? <span>{alt}</span> : null,
  table: ({ children }) => <div className="markdown-table" tabIndex={0}><table>{children}</table></div>,
  pre: ({ node, children }) => {
    const code = node?.children[0];
    const classes = code?.type === "element" ? code.properties.className : undefined;
    const language = Array.isArray(classes)
      ? classes.find((value): value is string => typeof value === "string" && value.startsWith(languagePrefix))?.slice(languagePrefix.length)
      : undefined;
    return <CodeBlock language={language}>{children}</CodeBlock>;
  },
};

export const MessageMarkdown = memo(function MessageMarkdown({ text }: { readonly text: string }) {
  return <div className="markdown-body">
    <Markdown skipHtml remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} urlTransform={(url, attribute) =>
      attribute === "href" && /^https?:\/\//i.test(url) ? url : undefined
    } components={components}>{text}</Markdown>
  </div>;
});
