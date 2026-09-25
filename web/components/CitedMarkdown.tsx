"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AskSource } from "@/lib/api";

/** Turn "[S1, S3]" citations into links the renderer draws as small source chips. */
function linkCitations(text: string, sources: AskSource[]) {
  const byId = new Map(sources.map((s) => [s.id, s]));
  return text.replace(/\[(S\d+(?:\s*,\s*S\d+)*)\]/g, (_, group: string) =>
    group.split(/\s*,\s*/).map((id) => `[${id}](${byId.get(id)?.url ?? `#src-${id}`})`).join(""));
}

export default function CitedMarkdown({ text, sources }: { text: string; sources: AskSource[] }) {
  return (
    <div className="text-sm leading-relaxed text-ink-2">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
        a: ({ href, children }) => {
          const id = String(children);
          if (/^S\d+$/.test(id)) {
            const src = sources.find((s) => s.id === id);
            return (
              <a href={href} target={href?.startsWith("#") ? undefined : "_blank"} rel="noreferrer" title={src ? `${src.name}: ${src.detail}` : id}
                className="inline-block align-super text-[10px] leading-none font-medium text-accent bg-accent-soft rounded px-1 py-0.5 mx-0.5 no-underline hover:underline">
                {id}
              </a>
            );
          }
          return <a href={href} target="_blank" rel="noreferrer" className="text-accent underline">{children}</a>;
        },
        h2: ({ children }) => <h3 className="text-base font-semibold text-ink mt-5 mb-1.5 first:mt-0">{children}</h3>,
        h3: ({ children }) => <h4 className="text-sm font-semibold text-ink mt-4 mb-1">{children}</h4>,
        strong: ({ children }) => <strong className="text-ink font-semibold">{children}</strong>,
        ul: ({ children }) => <ul className="list-disc pl-5 space-y-1 my-2">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1 my-2">{children}</ol>,
        p: ({ children }) => <p className="my-2">{children}</p>,
        table: ({ children }) => <div className="overflow-x-auto my-2"><table className="text-xs tabular border-collapse">{children}</table></div>,
        th: ({ children }) => <th className="text-left font-medium text-muted border-b border-line px-2 py-1">{children}</th>,
        td: ({ children }) => <td className="border-b border-line/60 px-2 py-1">{children}</td>,
      }}>
        {linkCitations(text, sources)}
      </ReactMarkdown>
    </div>
  );
}

export function SourceList({ sources }: { sources: AskSource[] }) {
  if (!sources.length) return null;
  return (
    <ol className="text-xs text-muted space-y-1 border-t border-line pt-2">
      {sources.map((s) => (
        <li key={s.id} id={`src-${s.id}`} className="flex gap-2">
          <span className="font-medium text-accent shrink-0">{s.id}</span>
          <span>{s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="underline hover:text-ink">{s.name}</a> : s.name}: {s.detail}</span>
        </li>
      ))}
    </ol>
  );
}
