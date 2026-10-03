"use client";

import { FormEvent, useEffect, useState } from "react";
import Chart, { baseOption } from "@/components/Chart";
import { Badge, Card, ErrorBox, InfoTip, Skeleton, SourceLink } from "@/components/ui";
import { api, GmpEntry, Ipo } from "@/lib/api";
import { crore, date, pct, rupees } from "@/lib/format";

const SEGMENTS = ["Mainboard", "SME", "All"] as const;
const STAGES = [
  { id: "live", label: "Open & upcoming", statuses: ["Open", "Upcoming"] },
  { id: "done", label: "Closed & allotted", statuses: ["Closed", "Allotted"] },
  { id: "listed", label: "Recently listed", statuses: ["Listed"] },
  { id: "all", label: "All", statuses: null },
] as const;

function stageBadge(i: Ipo): { text: string; variant: "accent" | "neutral" | "good" | "bad" } {
  if (i.status === "Open") return { text: daysLeft(i.close_date) ?? "Open", variant: "accent" };
  if (i.status === "Upcoming") return { text: `Opens ${date(i.open_date)}`, variant: "accent" };
  if (i.status === "Closed") return { text: i.allotment_date ? `Closed · allotment ${date(i.allotment_date)}` : "Closed", variant: "neutral" };
  if (i.status === "Allotted") return { text: i.listing_date ? `Allotted · lists ${date(i.listing_date)}` : "Allotted", variant: "neutral" };
  if (i.status === "Listed") {
    const g = i.listing_gain_pct;
    return { text: `Listed ${date(i.listing_date)}${g != null ? ` · ${pct(g, 1, true)}` : ""}`, variant: g == null ? "neutral" : g >= 0 ? "good" : "bad" };
  }
  return { text: i.status, variant: "neutral" };
}

function daysLeft(close: string | null) {
  if (!close) return null;
  const d = Math.ceil((new Date(close + "T17:00:00+05:30").getTime() - Date.now()) / 864e5);
  return d < 0 ? "Closed" : d === 0 ? "Closes today" : `${d} day${d > 1 ? "s" : ""} left`;
}

function GmpPanel({ ipo, onAdded }: { ipo: Ipo; onAdded: (e: GmpEntry) => void }) {
  const g = ipo.gmp;
  const [form, setForm] = useState({ gmp: "", source: "", source_url: "" });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const entry = await api<GmpEntry>(`/api/ipos/${ipo.symbol}/gmp`, {
        method: "POST",
        body: JSON.stringify({ gmp: Number(form.gmp), source: form.source, source_url: form.source_url || null }),
      }, { auth: true });   // adding GMP needs a signed-in user
      onAdded(entry);
      setForm({ gmp: "", source: "", source_url: "" });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-xl border border-warn/40 bg-warn-soft/40 p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">Grey market premium</span><InfoTip term="GMP" />
        <Badge variant="warn">● Unofficial · unverified</Badge>
      </div>
      <p className="text-xs text-ink-2">{g.disclaimer}</p>

      {g.latest ? (
        <div className="grid sm:grid-cols-3 gap-4">
          <div>
            <div className="text-xs text-muted">Latest GMP</div>
            <div className="text-xl font-semibold tabular">{rupees(g.latest.gmp, 0)}</div>
            <div className="text-xs text-muted">
              {g.latest.source_url ? <a className="underline" href={g.latest.source_url} target="_blank" rel="noreferrer">{g.latest.source}</a> : g.latest.source}
              {" · "}{new Date(g.latest.observed_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
            </div>
          </div>
          {g.estimate && (
            <div>
              <div className="text-xs text-muted">Estimated listing price</div>
              <div className="text-xl font-semibold tabular">{rupees(g.estimate.estimated_listing_price, 0)}</div>
              <div className="text-xs text-muted">{pct(g.estimate.estimated_premium_pct, 1, true)} vs upper band · {g.estimate.label}</div>
            </div>
          )}
          {g.history.length > 1 && (
            <div className="sm:col-span-3">
              <Chart height={180} label="GMP history" build={(k) => {
                const base = baseOption(k);
                return {
                  ...base, legend: { show: false },
                  tooltip: { ...base.tooltip, valueFormatter: (v) => rupees(Number(v), 0) },
                  xAxis: { type: "time", axisLine: { lineStyle: { color: k.line } }, axisLabel: { color: k.muted, fontSize: 11 } },
                  series: [{ type: "line", name: "GMP", data: g.history.map((h) => [h.observed_at, h.gmp]), lineStyle: { width: 2, color: k.s2 }, itemStyle: { color: k.s2 }, symbolSize: 8 }],
                };
              }} />
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted">InvestorGain has no GMP reading for this IPO yet.</p>
      )}

      <details className="pt-2 border-t border-warn/30">
      <summary className="text-xs text-muted cursor-pointer">Add a reading from another source</summary>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2 pt-2">
        <label className="text-xs text-muted">GMP (₹)
          <input required type="number" step="0.5" value={form.gmp} onChange={(e) => setForm({ ...form, gmp: e.target.value })}
            className="block w-24 mt-1 bg-surface border border-line rounded-lg px-2 py-1.5 text-sm text-ink" />
        </label>
        <label className="text-xs text-muted">Source name
          <input required minLength={2} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} placeholder="e.g. a GMP website"
            className="block w-40 mt-1 bg-surface border border-line rounded-lg px-2 py-1.5 text-sm text-ink" />
        </label>
        <label className="text-xs text-muted flex-1 min-w-40">Source link (optional)
          <input type="url" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} placeholder="https://"
            className="block w-full mt-1 bg-surface border border-line rounded-lg px-2 py-1.5 text-sm text-ink" />
        </label>
        <button disabled={saving} className="bg-ink text-bg text-sm rounded-lg px-3 py-1.5 disabled:opacity-50">{saving ? "Saving…" : "Record GMP"}</button>
        {err && <span className="text-xs text-bad w-full">{err}</span>}
      </form>
      </details>
    </div>
  );
}

export default function IpoPage() {
  const [ipos, setIpos] = useState<Ipo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [segment, setSegment] = useState<(typeof SEGMENTS)[number]>("All");
  const [stage, setStage] = useState<(typeof STAGES)[number]["id"]>("live");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => { api<Ipo[]>("/api/ipos").then(setIpos).catch((e: Error) => setError(e.message)); }, []);

  function addGmp(symbol: string, entry: GmpEntry) {
    setIpos((list) => list?.map((i) => {
      if (i.symbol !== symbol) return i;
      const history = [...i.gmp.history, entry];
      const estimate = i.price_high ? {
        estimated_listing_price: i.price_high + entry.gmp,
        estimated_premium_pct: (entry.gmp / i.price_high) * 100,
        label: "Estimate from unofficial GMP. Not a forecast.",
      } : null;
      return { ...i, gmp: { ...i.gmp, latest: entry, history, estimate } };
    }) ?? null);
  }

  const inSegment = ipos?.filter((i) => segment === "All" || i.segment === segment) ?? [];
  const inStage = (id: string, i: Ipo) => {
    const s = STAGES.find((x) => x.id === id)!.statuses;
    return s === null || (s as readonly string[]).includes(i.status);
  };
  const rows = inSegment.filter((i) => inStage(stage, i));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">IPOs & GMP</h1>
          <p className="text-sm text-ink-2 mt-1">Every mainboard and SME IPO on NSE and BSE, from upcoming to recently listed. Live subscription comes from NSE where NSE lists the issue. GMP comes from InvestorGain, is unofficial and unverified, and is kept separate from official data.</p>
        </div>
        <div role="tablist" className="flex gap-1 bg-surface-2 rounded-lg p-0.5">
          {SEGMENTS.map((s) => (
            <button key={s} role="tab" aria-selected={segment === s} onClick={() => setSegment(s)}
              className={`text-sm px-3 py-1.5 rounded-md ${segment === s ? "bg-surface shadow-sm font-medium" : "text-muted hover:text-ink"}`}>{s}</button>
          ))}
        </div>
      </div>

      <div role="tablist" aria-label="Stage" className="flex flex-wrap gap-2">
        {STAGES.map((s) => {
          const n = inSegment.filter((i) => inStage(s.id, i)).length;
          return (
            <button key={s.id} role="tab" aria-selected={stage === s.id} onClick={() => setStage(s.id)}
              className={`text-sm px-3 py-1.5 rounded-full border ${stage === s.id ? "border-accent bg-accent-soft text-accent font-medium" : "border-line text-ink-2 hover:border-ink-2"}`}>
              {s.label} {ipos && <span className={stage === s.id ? "" : "text-muted"}>{n}</span>}
            </button>
          );
        })}
      </div>

      {error && <ErrorBox message={error} />}
      {!ipos && !error && <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20" />)}</div>}
      {ipos && rows.length === 0 && <Card><p className="text-sm text-muted">No {segment === "All" ? "" : segment + " "}IPOs {stage === "live" ? "are open or upcoming right now" : "in this list right now"}.</p></Card>}

      <div className="space-y-3">
        {rows.map((i) => {
          const isOpen = open === i.symbol;
          const sub = i.subscription_times;
          const badge = stageBadge(i);
          const minInvest = i.lot && i.price_high ? i.lot * i.price_high : null;
          return (
            <Card key={i.symbol}>
              <div>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium">{i.name}</div>
                    <div className="text-xs text-muted mt-0.5 flex flex-wrap gap-x-2">
                      {i.nse_symbol && <><span>{i.nse_symbol}</span><span>·</span></>}
                      <span>{i.segment}{i.exchange ? ` · ${i.exchange}` : ""}</span><span>·</span>
                      <span>{date(i.open_date)} – {date(i.close_date)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={badge.variant}>{badge.text}</Badge>
                    {i.gmp.latest && <Badge variant="warn">GMP {rupees(i.gmp.latest.gmp, 0)}{i.gmp.estimate ? ` (${pct(i.gmp.estimate.estimated_premium_pct, 0, true)})` : ""} · unofficial</Badge>}
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-3">
                  <div><div className="text-xs text-muted">Price{i.price_low !== i.price_high ? " band" : ""}</div><div className="text-sm font-semibold tabular">{i.price_high ? (i.price_low && i.price_low !== i.price_high ? `${rupees(i.price_low, 0)} – ${rupees(i.price_high, 0)}` : rupees(i.price_high, 0)) : "—"}</div></div>
                  <div><div className="text-xs text-muted">Issue size (at upper band)</div><div className="text-sm font-semibold tabular">{crore(i.issue_size_cr)}</div></div>
                  <div>
                    <div className="text-xs text-muted">Lot · min. investment</div>
                    <div className="text-sm font-semibold tabular">{i.lot ? `${new Intl.NumberFormat("en-IN").format(i.lot)} shares` : "—"}</div>
                    {minInvest != null && <div className="text-xs text-muted tabular">{rupees(minInvest, 0)}</div>}
                  </div>
                  <div>
                    <div className="text-xs text-muted flex items-center">Subscribed<InfoTip term="Subscription" /></div>
                    <div className="text-sm font-semibold tabular">{sub != null ? `${sub.toFixed(2)}x` : "—"}</div>
                    {sub != null && (
                      <div className="h-1 rounded-full bg-surface-2 mt-1 overflow-hidden">
                        <div className={`h-full ${sub >= 1 ? "bg-good" : "bg-accent"}`} style={{ width: `${Math.min(100, (sub / 5) * 100)}%` }} />
                      </div>
                    )}
                  </div>
                </div>
                <button type="button" onClick={() => setOpen(isOpen ? null : i.symbol)} aria-expanded={isOpen}
                  className="text-xs text-accent mt-3 hover:underline">{isOpen ? "Hide GMP" : "GMP & details"}</button>
              </div>
              {isOpen && (
                <div className="mt-3 space-y-2">
                  <GmpPanel ipo={i} onAdded={(e) => addGmp(i.symbol, e)} />
                  <SourceLink name={i.source.name} url={i.source.url} when="subscription figures update during market hours" />
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
