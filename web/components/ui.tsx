import { ReactNode } from "react";
import { GLOSSARY } from "@/lib/glossary";
import { tone } from "@/lib/format";

export function Card({ title, action, children, className = "" }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`bg-surface border border-line rounded-xl p-4 sm:p-5 ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between gap-3 mb-3">
          {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

const TONES = {
  good: "bg-good-soft text-good",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  neutral: "bg-surface-2 text-ink-2",
  accent: "bg-accent-soft text-accent",
};

export function Badge({ children, variant = "neutral" }: { children: ReactNode; variant?: keyof typeof TONES }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${TONES[variant]}`}>{children}</span>;
}

const LABEL_ICON = { good: "▲", warn: "●", bad: "▼", neutral: "■" };

/** Score labels always carry an icon and text, never color alone. */
export function LabelBadge({ label }: { label: string }) {
  const t = tone(label);
  return <Badge variant={t}><span aria-hidden className="text-[9px]">{LABEL_ICON[t]}</span>{label}</Badge>;
}

export function InfoTip({ term }: { term: string }) {
  const text = GLOSSARY[term];
  if (!text) return null;
  return (
    <span className="relative inline-block group align-middle ml-1">
      <button type="button" aria-label={`What is ${term}?`}
        className="w-4 h-4 rounded-full border border-line text-[10px] leading-none text-muted hover:text-ink hover:border-ink-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        ?
      </button>
      <span role="tooltip"
        className="pointer-events-none absolute z-30 left-1/2 -translate-x-1/2 bottom-6 w-64 rounded-lg bg-ink text-bg text-xs font-normal leading-relaxed p-3 shadow-lg opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
        {text}
      </span>
    </span>
  );
}

export function Stat({ label, value, sub, term }: { label: string; value: ReactNode; sub?: ReactNode; term?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted flex items-center">{label}{term && <InfoTip term={term} />}</div>
      <div className="text-base font-semibold tabular mt-0.5 truncate">{value}</div>
      {sub && <div className="text-xs text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

export function SourceLink({ name, url, when }: { name: string; url?: string | null; when?: string }) {
  return (
    <span className="text-xs text-muted">
      Source: {url ? <a href={url} target="_blank" rel="noreferrer" className="underline hover:text-ink">{name}</a> : name}
      {when && <> · {when}</>}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-surface-2 ${className}`} />;
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="rounded-xl border border-bad/40 bg-bad-soft text-bad text-sm p-4">{message}</div>;
}
