"use client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { isDesktopRuntime } from "@/lib/api";

export function Markdown({ children }: { children: string }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
    // Remote images in model output could track a user; only verified attachments render images.
    img: ({ alt }) => <span className="muted">[Görsel: {alt || "ek"}]</span>,
    a: ({ href, children: label }) => {
      if (!href || !/^https?:\/\//iu.test(href)) return <span>{label}</span>;
      return <a href={href} target="_blank" rel="noopener noreferrer" onClick={(event) => {
        if (isDesktopRuntime()) { event.preventDefault(); void window.akashiDesktop?.shell.openExternal(href); }
      }}>{label}</a>;
    },
    table: ({ children: content }) => <div className="table-scroll"><table>{content}</table></div>,
  }}>{children}</ReactMarkdown></div>;
}
