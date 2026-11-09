import { memo } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

const plugins = [remarkGfm];

export const MessageMarkdown = memo(function MessageMarkdown({ text }: { readonly text: string }) {
  return <div className="message-markdown">
    <Markdown skipHtml remarkPlugins={plugins} urlTransform={(url, attribute) =>
      attribute === "href" && /^https?:\/\//i.test(url) ? url : undefined
    } components={{
      a: ({ href, children }) => href
        ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
        : <span>{children}</span>,
      img: ({ alt }) => alt ? <span>{alt}</span> : null,
      table: ({ children }) => <div className="markdown-table"><table>{children}</table></div>,
    }}>{text}</Markdown>
  </div>;
});
