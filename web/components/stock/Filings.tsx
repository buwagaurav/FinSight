"use client";

import { useEffect, useState } from "react";
import { Badge, Card, Skeleton } from "@/components/ui";
import { AiStatus, Announcement, api, SummaryResult } from "@/lib/api";
import { date } from "@/lib/format";

const SENTIMENT = {
  positive: { variant: "good", icon: "▲", label: "Positive" },
  negative: { variant: "bad", icon: "▼", label: "Negative" },
  neutral: { variant: "neutral", icon: "■", label: "Neutral" },
  uncertain: { variant: "warn", icon: "●", label: "Uncertain" },
} as const;

function Summary({ r }: { r: SummaryResult }) {
  const s = r.summary;
  const sent = SENTIMENT[s.sentiment];
  return (
    <div className="mt-3 rounded-xl border border-line bg-surface-2/50 p-3 space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-ink">{s.headline}</span>
        <Badge variant={sent.variant}><span className="text-[9px]">{sent.icon}</span>{sent.label}</Badge>
        <Badge variant={s.materiality === "high" ? "accent" : "neutral"}>{s.materiality} materiality</Badge>
      </div>
      <p className="text-ink-2"><b className="text-ink">What happened: </b>{s.what_happened}</p>
      <p className="text-ink-2"><b className="text-ink">Why it matters: </b>{s.why_it_matters}</p>
      {s.key_figures.length > 0 && (
        <dl className="grid sm:grid-cols-2 gap-x-4 gap-y-1 text-xs">
          {s.key_figures.map((f) => (
            <div key={f.label} className="flex justify-between gap-3 border-b border-line/60 py-1">
              <dt className="text-muted">{f.label}</dt><dd className="tabular text-ink font-medium text-right">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {s.affected_metrics.length > 0 && <p className="text-xs text-muted">May affect: {s.affected_metrics.join(", ")}</p>}
      {s.watch_next.length > 0 && (
        <div className="text-xs text-ink-2"><b className="text-ink">Watch next:</b>
          <ul className="list-disc pl-5 mt-0.5">{s.watch_next.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {!r.verification.checked ? <Badge variant="warn">● Scanned filing: figures not machine-checked</Badge>
          : r.verification.passed ? <Badge variant="good">✓ Every figure found in the filing</Badge>
          : <Badge variant="warn">● Not found in filing: {r.verification.unverified.join(", ")}</Badge>}
        <span className="text-xs text-muted">AI summary of the {r.basis} · {r.model}</span>
      </div>
    </div>
  );
}

export default function Filings({ symbol }: { symbol: string }) {
  const [items, setItems] = useState<Announcement[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [showRoutine, setShowRoutine] = useState(false);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [failed, setFailed] = useState<Record<string, string>>({});

  useEffect(() => {
    api<Announcement[]>(`/api/company/${encodeURIComponent(symbol)}/announcements`).then(setItems).catch((e: Error) => setError(e.message));
    api<AiStatus>("/api/ai/status").then(setAi).catch(() => {});
  }, [symbol]);

  async function summarise(a: Announcement) {
    setLoading((l) => ({ ...l, [a.id]: true }));
    setFailed((f) => ({ ...f, [a.id]: "" }));
    try {
      const r = await api<SummaryResult>(`/api/company/${encodeURIComponent(symbol)}/announcements/${a.id}/summary`, { method: "POST" });
      setItems((list) => list?.map((x) => (x.id === a.id ? { ...x, summary: r } : x)) ?? null);
    } catch (e) {
      setFailed((f) => ({ ...f, [a.id]: (e as Error).message }));
    } finally {
      setLoading((l) => ({ ...l, [a.id]: false }));
    }
  }

  const visible = items?.filter((a) => showRoutine || !a.routine) ?? [];
  const hidden = (items?.length ?? 0) - visible.length;

  return (
    <Card title="Exchange filings (NSE)"
      action={hidden > 0 || showRoutine
        ? <button onClick={() => setShowRoutine(!showRoutine)} className="text-xs text-accent hover:underline">{showRoutine ? "Hide routine filings" : `Show ${hidden} routine filings`}</button>
        : undefined}>
      {error && <p className="text-sm text-muted">NSE filings are unavailable right now.</p>}
      {!items && !error && <div className="space-y-3"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>}
      {ai && !ai.tasks.summary.configured && items && (
        <p className="text-xs text-muted mb-2">Add credentials for {ai.tasks.summary.model} in backend/.env to get AI summaries of these filings.</p>
      )}
      <ul className="divide-y divide-line">
        {visible.map((a) => (
          <li key={a.id} className="py-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
              <Badge variant={a.routine ? "neutral" : "accent"}>{a.category || "Announcement"}</Badge>
              <span>{date(a.published)}</span>
              {a.pdf_url && <a href={a.pdf_url} target="_blank" rel="noreferrer" className="underline hover:text-ink">Filing PDF{a.pdf_size ? ` (${a.pdf_size})` : ""} ↗</a>}
            </div>
            <p className="text-sm text-ink-2 mt-1.5 line-clamp-3">{a.text}</p>
            {a.summary ? <Summary r={a.summary} /> : ai?.tasks.summary.configured && (
              <button onClick={() => summarise(a)} disabled={loading[a.id]}
                className="mt-2 text-xs px-3 py-1.5 rounded-lg border border-line hover:border-accent hover:text-accent disabled:opacity-60">
                {loading[a.id] ? "Reading the filing…" : "Summarise with AI"}
              </button>
            )}
            {failed[a.id] && <p className="text-xs text-bad mt-1">{failed[a.id]}</p>}
          </li>
        ))}
      </ul>
    </Card>
  );
}
