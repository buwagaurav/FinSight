"use client";

import { useEffect, useRef, useState } from "react";
import CitedMarkdown, { SourceList } from "@/components/CitedMarkdown";
import { Badge, Card, Skeleton } from "@/components/ui";
import { AiStatus, api, ReportJob, ReportResult } from "@/lib/api";

const SECTION_TITLES: Record<string, string> = {
  fundamentals: "Fundamentals analyst",
  valuation: "Valuation analyst",
  developments: "Filings & news analyst",
};
const STEP_ICON = { pending: "○", running: "◐", done: "●", retry: "↻" };

function Progress({ job }: { job: ReportJob }) {
  return (
    <ol className="space-y-1.5 text-sm">
      {job.steps.map((s) => (
        <li key={s.key} className={`flex items-center gap-2 ${s.status === "pending" ? "text-muted" : "text-ink"}`}>
          <span className={`w-4 text-center ${s.status === "running" ? "animate-pulse text-accent" : s.status === "done" ? "text-good" : s.status === "retry" ? "text-warn" : ""}`}>
            {STEP_ICON[s.status]}
          </span>
          {s.label}
          {s.status === "retry" && <span className="text-xs text-warn">found an untraceable figure, rewriting</span>}
        </li>
      ))}
    </ol>
  );
}

export default function ResearchReport({ symbol, name }: { symbol: string; name: string }) {
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [report, setReport] = useState<ReportResult | null | undefined>(undefined);
  const [job, setJob] = useState<ReportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api<AiStatus>("/api/ai/status").then(setAi).catch(() => {});
    api<ReportResult>(`/api/company/${encodeURIComponent(symbol)}/report`).then(setReport).catch(() => setReport(null));
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [symbol]);

  async function generate() {
    setError(null);
    try {
      const { job_id } = await api<{ job_id: string }>(`/api/company/${encodeURIComponent(symbol)}/report`, { method: "POST" });
      timer.current = setInterval(async () => {
        try {
          const j = await api<ReportJob>(`/api/reports/jobs/${job_id}`);
          setJob(j);
          if (j.status !== "running") {
            clearInterval(timer.current!);
            if (j.result) setReport(j.result);
            if (j.error) setError(j.error);
            setJob(null);
          }
        } catch (e) {
          clearInterval(timer.current!);
          setError((e as Error).message);
          setJob(null);
        }
      }, 2000);
      setJob({ id: job_id, status: "running", error: null, result: null, steps: [] });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (report === undefined) return <Skeleton className="h-48" />;

  const canGenerate = ai?.tasks.report.configured && !job;
  const header = (
    <div className="flex flex-wrap items-center gap-2">
      {report && <span className="text-xs text-muted">Generated {new Date(report.generated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })} in {report.duration_s < 60 ? `${report.duration_s}s` : `${Math.round(report.duration_s / 60)} min`} · {report.model}</span>}
      {canGenerate && (
        <button onClick={generate} className={`text-sm rounded-lg px-3 py-1.5 font-medium ${report ? "border border-line hover:border-accent hover:text-accent" : "bg-accent text-white"}`}>
          {report ? "Regenerate" : "Generate research report"}
        </button>
      )}
    </div>
  );

  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <Card className="lg:col-span-2" title={`Research report: ${name}`} action={header}>
        {ai && !ai.tasks.report.configured && !report && (
          <p className="text-sm text-ink-2">Add credentials for <code>{ai.tasks.report.model}</code> in <code>backend/.env</code> to generate multi-agent research reports.</p>
        )}
        {ai?.tasks.report.configured && !report && !job && (
          <div className="text-sm text-ink-2 space-y-2">
            <p>Three AI analysts research this company in parallel (fundamentals, valuation, and filings &amp; news), a risk reviewer challenges their work, and an editor writes the report. Every figure is then checked against the data the analysts actually retrieved.</p>
            <p className="text-xs text-muted">Takes about 2–5 minutes and roughly 20–40 model calls. The report is saved, so it only needs generating once.</p>
          </div>
        )}
        {job && (
          <div className="space-y-3">
            <p className="text-sm text-ink-2">Researching {name}. You can keep browsing other tabs.</p>
            {job.steps.length ? <Progress job={job} /> : <Skeleton className="h-24" />}
          </div>
        )}
        {error && <div className="rounded-lg bg-bad-soft text-bad text-sm p-3 mt-2">{error}</div>}
        {report && !job && (
          <div className="space-y-3">
            <CitedMarkdown text={report.report} sources={report.all_sources} />
            {report.verification.passed ? (
              <Badge variant="good">✓ Every figure matched the source it cites{report.verification.rewrites > 0 ? ` (after ${report.verification.rewrites} rewrite${report.verification.rewrites > 1 ? "s" : ""})` : ""}</Badge>
            ) : (
              <div className="rounded-lg border border-warn/40 bg-warn-soft p-2.5 text-xs text-ink-2">
                <span className="font-semibold text-warn">● Check before relying on this report: </span>{report.verification.problems}
              </div>
            )}
            <SourceList sources={report.sources} />
            <p className="text-xs text-muted">AI-generated research, not investment advice.</p>
          </div>
        )}
      </Card>

      {report && !job && (
        <div className="space-y-4">
          <Card title="Risk reviewer's challenges">
            <CitedMarkdown text={report.review} sources={report.all_sources} />
          </Card>
          <Card title="Analyst drafts">
            {Object.entries(report.sections).map(([k, v]) => (
              <details key={k} className="border-b border-line last:border-0 py-2">
                <summary className="cursor-pointer text-sm font-medium">{SECTION_TITLES[k] ?? k}</summary>
                <div className="mt-2"><CitedMarkdown text={v} sources={report.all_sources} /></div>
              </details>
            ))}
            <p className="text-xs text-muted mt-2">{report.tool_calls.length} tool calls across {new Set(report.tool_calls.map((c) => c.agent)).size} agents.</p>
          </Card>
        </div>
      )}
    </div>
  );
}
