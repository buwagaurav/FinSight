"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Card, ErrorBox, Skeleton } from "@/components/ui";
import { AiStatus, api, ScreenFilter, ScreenResult } from "@/lib/api";
import { crore, DASH, num, pct, rupees } from "@/lib/format";

type ScreenSpec = {
  sectors: string[];
  filters: ScreenFilter[];
  sort: string | null;
  descending: boolean;
  interpretations: string[];
  unsupported: string[];
};

const EXAMPLES = [
  "Debt-free IT companies with ROE above 20%",
  "Cheap large caps paying good dividends",
  "Fast-growing companies with low debt, best margins first",
];

const PRESETS: Record<string, { title: string; filters: ScreenFilter[] }> = {
  quality: { title: "Quality compounders", filters: [
    { field: "roe_pct", op: ">", value: 18 }, { field: "debt_to_equity", op: "<", value: 0.5 }, { field: "profit_cagr_pct", op: ">", value: 10 }] },
  garp: { title: "Reasonably priced growth", filters: [
    { field: "profit_cagr_pct", op: ">", value: 12 }, { field: "pe", op: "<", value: 30 }, { field: "pe", op: ">", value: 0 }] },
  dividend: { title: "Dividend payers", filters: [
    { field: "dividend_yield_pct", op: ">", value: 2 }, { field: "debt_to_equity", op: "<", value: 1 }] },
};

const COLUMNS: { key: string; label: string; render: (v: number | null) => string }[] = [
  { key: "market_cap_cr", label: "Market cap", render: crore },
  { key: "pe", label: "P/E", render: (v) => num(v) },
  { key: "roe_pct", label: "ROE", render: (v) => pct(v) },
  { key: "roce_pct", label: "ROCE", render: (v) => pct(v) },
  { key: "debt_to_equity", label: "D/E", render: (v) => num(v, 2) },
  { key: "revenue_cagr_pct", label: "Rev. CAGR", render: (v) => pct(v) },
  { key: "profit_cagr_pct", label: "Profit CAGR", render: (v) => pct(v) },
  { key: "dividend_yield_pct", label: "Div. yield", render: (v) => pct(v, 2) },
];

function Screener() {
  const params = useSearchParams();
  const preset = PRESETS[params.get("preset") ?? ""];
  const [fields, setFields] = useState<Record<string, string>>({});
  const [filters, setFilters] = useState<ScreenFilter[]>(preset?.filters ?? [{ field: "roe_pct", op: ">", value: 15 }]);
  const [sort, setSort] = useState({ key: "market_cap_cr", desc: true });
  const [result, setResult] = useState<ScreenResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allSectors, setAllSectors] = useState<string[]>([]);
  const [sectors, setSectors] = useState<string[]>([]);
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [nl, setNl] = useState("");
  const [parsing, setParsing] = useState(false);
  const [spec, setSpec] = useState<ScreenSpec | null>(null);
  const [nlError, setNlError] = useState<string | null>(null);

  useEffect(() => {
    api<Record<string, string>>("/api/screener/fields").then(setFields).catch(() => {});
    api<string[]>("/api/screener/sectors").then(setAllSectors).catch(() => {});
    api<AiStatus>("/api/ai/status").then(setAi).catch(() => {});
  }, []);

  const run = useCallback((f: ScreenFilter[], s: typeof sort, sec: string[] = []) => {
    setLoading(true);
    setError(null);
    api<ScreenResult>("/api/screener", { method: "POST", body: JSON.stringify({ filters: f.filter((x) => !Number.isNaN(x.value)), sort: s.key, descending: s.desc, sectors: sec }) })
      .then(setResult)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { run(filters, sort, sectors); }, [sort]); // eslint-disable-line react-hooks/exhaustive-deps

  async function describe(text: string) {
    const q = text.trim();
    if (q.length < 3) return;
    setNl(q);
    setParsing(true);
    setNlError(null);
    try {
      const sp = await api<ScreenSpec>("/api/screener/parse", { method: "POST", body: JSON.stringify({ query: q }) });
      setSpec(sp);
      setFilters(sp.filters);
      setSectors(sp.sectors);
      const nextSort = { key: sp.sort ?? sort.key, desc: sp.descending };
      setSort(nextSort);
      run(sp.filters, nextSort, sp.sectors);
    } catch (e) {
      setNlError((e as Error).message);
    } finally {
      setParsing(false);
    }
  }

  const toggleSector = (s: string) => setSectors((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));

  const update = (i: number, patch: Partial<ScreenFilter>) => setFilters(filters.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  const sortBy = (key: string) => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Screener</h1>
        <p className="text-sm text-ink-2 mt-1">Filter companies by the numbers that matter. Every metric uses the same calculations as the company page.</p>
      </div>

      {ai?.tasks.screen.configured && (
        <Card title="Describe your screen in plain English">
          <form onSubmit={(e) => { e.preventDefault(); describe(nl); }} className="flex gap-2">
            <input value={nl} onChange={(e) => setNl(e.target.value)} placeholder="e.g. profitable IT companies with no debt, cheapest first"
              className="flex-1 min-w-0 bg-surface border border-line rounded-lg px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20" />
            <button disabled={parsing || nl.trim().length < 3} className="bg-accent text-white text-sm font-medium rounded-lg px-4 py-2 disabled:opacity-50">
              {parsing ? "Building…" : "Build screen"}
            </button>
          </form>
          {!spec && !parsing && (
            <div className="flex flex-wrap gap-2 mt-3">
              {EXAMPLES.map((x) => <button key={x} onClick={() => describe(x)} className="text-xs px-3 py-1.5 rounded-full border border-line text-ink-2 hover:border-accent hover:text-accent">{x}</button>)}
            </div>
          )}
          {nlError && <p className="text-sm text-bad mt-2">{nlError}</p>}
          {spec && (
            <div className="mt-3 text-sm space-y-2">
              {spec.interpretations.length > 0 && (
                <div><span className="text-xs font-semibold text-ink">How FinSight read your request</span>
                  <ul className="list-disc pl-5 text-ink-2 text-xs mt-1 space-y-0.5">{spec.interpretations.map((t) => <li key={t}>{t}</li>)}</ul></div>
              )}
              {spec.unsupported.length > 0 && (
                <div className="rounded-lg bg-warn-soft p-2 text-xs text-ink-2"><span className="font-semibold text-warn">● Not applied (no matching data): </span>{spec.unsupported.join("; ")}</div>
              )}
              <p className="text-xs text-muted">The filters below were filled in from your sentence. Edit anything and press Run screen.</p>
            </div>
          )}
        </Card>
      )}

      <div className="flex flex-wrap gap-2">
        {Object.entries(PRESETS).map(([id, p]) => (
          <button key={id} onClick={() => { setFilters(p.filters); setSectors([]); setSpec(null); run(p.filters, sort, []); }}
            className="text-sm px-3 py-1.5 rounded-full border border-line bg-surface hover:border-accent hover:text-accent">{p.title}</button>
        ))}
      </div>

      <Card title="Your screen">
        {allSectors.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-3" aria-label="Sectors">
            <span className="text-xs text-muted w-10 pt-1">Sector</span>
            {allSectors.map((sec) => (
              <button key={sec} onClick={() => toggleSector(sec)} aria-pressed={sectors.includes(sec)}
                className={`text-xs px-2.5 py-1 rounded-full border ${sectors.includes(sec) ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-2 hover:border-ink-2"}`}>{sec}</button>
            ))}
          </div>
        )}
        <div className="space-y-2">
          {filters.map((f, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted w-10">{i === 0 ? "Where" : "and"}</span>
              <select value={f.field} onChange={(e) => update(i, { field: e.target.value })} aria-label="Metric"
                className="bg-surface border border-line rounded-lg px-2 py-1.5 text-sm">
                {Object.entries(fields).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                {!fields[f.field] && <option value={f.field}>{f.field}</option>}
              </select>
              <select value={f.op} onChange={(e) => update(i, { op: e.target.value as ScreenFilter["op"] })} aria-label="Comparison"
                className="bg-surface border border-line rounded-lg px-2 py-1.5 text-sm">
                {[">", ">=", "<", "<="].map((o) => <option key={o}>{o}</option>)}
              </select>
              <input type="number" step="any" value={Number.isNaN(f.value) ? "" : f.value} aria-label="Value"
                onChange={(e) => update(i, { value: e.target.value === "" ? NaN : Number(e.target.value) })}
                className="w-24 bg-surface border border-line rounded-lg px-2 py-1.5 text-sm tabular" />
              <button onClick={() => setFilters(filters.filter((_, j) => j !== i))} aria-label="Remove filter" className="text-muted hover:text-bad px-2">✕</button>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-2 mt-4">
          <button onClick={() => setFilters([...filters, { field: "pe", op: "<", value: 25 }])}
            className="text-sm px-3 py-1.5 rounded-lg border border-line hover:border-ink-2">+ Add filter</button>
          <button onClick={() => run(filters, sort, sectors)} disabled={loading}
            className="text-sm px-4 py-1.5 rounded-lg bg-accent text-white font-medium disabled:opacity-60">{loading ? "Running…" : "Run screen"}</button>
        </div>
        {result && <p className="text-xs text-muted mt-3">Query: <code className="text-ink-2">{result.query}</code></p>}
      </Card>

      {error && <ErrorBox message={error} />}
      {loading && !result && (
        <div className="space-y-2">
          <Skeleton className="h-10" /><Skeleton className="h-10" /><Skeleton className="h-10" />
          <p className="text-sm text-muted text-center">Running your screen…</p>
        </div>
      )}

      {result && (
        <Card title={`${result.count} match${result.count === 1 ? "" : "es"}`}
          action={<span className="text-xs text-muted">Universe: {result.universe}{result.built_at ? ` · updated ${new Date(result.built_at * 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}` : ""}</span>}>
          {result.coverage.pending > 0 && (
            <div className="rounded-lg bg-accent-soft text-ink-2 text-xs p-2.5 mb-3">
              FinSight is still loading the full market: {result.coverage.loaded.toLocaleString("en-IN")} of {result.coverage.listed.toLocaleString("en-IN")} NSE companies so far
              ({result.coverage.pending.toLocaleString("en-IN")} to go). Results cover loaded companies only; this fills in automatically while the API runs.
            </div>
          )}
          {/* Own scroll area so the header row (and the company column) stay visible while scrolling.
              Page-level sticky can't work here: a horizontally scrolling wrapper becomes the sticky container. */}
          <div className={`overflow-auto max-h-[70vh] -mx-4 sm:mx-0 rounded-lg border border-line ${loading ? "opacity-60" : ""}`}>
            <table className="w-full text-sm tabular min-w-[760px] border-separate border-spacing-0">
              <thead>
                <tr className="text-xs text-muted">
                  <th className="sticky top-0 left-0 z-20 bg-surface text-left font-medium py-2.5 px-4 shadow-[inset_0_-1px_0_var(--line),inset_-1px_0_0_var(--line)]">Company</th>
                  <th className="sticky top-0 z-10 bg-surface text-right font-medium py-2.5 px-3 shadow-[inset_0_-1px_0_var(--line)]">Price</th>
                  {COLUMNS.map((c) => (
                    <th key={c.key} aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : undefined}
                      className="sticky top-0 z-10 bg-surface text-right font-medium py-2.5 px-3 whitespace-nowrap shadow-[inset_0_-1px_0_var(--line)]">
                      <button onClick={() => sortBy(c.key)} title={`Sort by ${c.label}`} className={`hover:text-ink ${sort.key === c.key ? "text-ink" : ""}`}>
                        {c.label}{sort.key === c.key ? (sort.desc ? " ↓" : " ↑") : ""}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r) => (
                  <tr key={r.symbol} className="group">
                    <td className="sticky left-0 z-[5] bg-surface group-hover:bg-surface-2 py-2 px-4 border-b border-line/60 shadow-[inset_-1px_0_0_var(--line)] max-w-[240px]">
                      <Link href={`/stock/${r.symbol}`} className="font-medium hover:text-accent block truncate" title={r.name}>{r.name}</Link>
                      <div className="text-xs text-muted truncate">{r.symbol.split(".")[0]}{r.sector ? ` · ${r.sector}` : ""}</div>
                    </td>
                    <td className="text-right py-2 px-3 border-b border-line/60 group-hover:bg-surface-2">{rupees(r.price as number | null, 0)}</td>
                    {COLUMNS.map((c) => (
                      <td key={c.key} className="text-right py-2 px-3 border-b border-line/60 group-hover:bg-surface-2">{c.render(r[c.key] as number | null) ?? DASH}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.count === 0 && <p className="text-sm text-muted py-4">No companies match. Try loosening a filter.</p>}
          {result.count > result.shown && (
            <p className="text-xs text-muted mt-3">Showing the top {result.shown} of {result.count.toLocaleString("en-IN")} matches by the sorted column. Add filters to narrow the list.</p>
          )}
          <p className="text-xs text-muted mt-3">Banks and financials show no ROCE or D/E, so filters on those metrics leave them out.</p>
          {result.coverage.unavailable.length > 0 && (
            <details className="text-xs text-muted mt-1">
              <summary className="cursor-pointer">{result.coverage.unavailable.length} listed {result.coverage.unavailable.length === 1 ? "company has" : "companies have"} no data from our source yet</summary>
              <p className="mt-1">Usually very recent listings or temporary rights-entitlement lines. FinSight rechecks them monthly: {result.coverage.unavailable.join(", ")}.</p>
            </details>
          )}
        </Card>
      )}
    </div>
  );
}

export default function ScreenerPage() {
  return <Suspense fallback={<Skeleton className="h-64" />}><Screener /></Suspense>;
}
