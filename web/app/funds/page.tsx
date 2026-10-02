"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Badge, Card, ErrorBox, Skeleton, SourceLink } from "@/components/ui";
import { api, FundScheme, FundSearch } from "@/lib/api";
import { date, nav } from "@/lib/format";

const SHORTCUTS: { label: string; group: string; category: string }[] = [
  { label: "Flexi Cap", group: "Equity Scheme", category: "Flexi Cap Fund" },
  { label: "Large Cap", group: "Equity Scheme", category: "Large Cap Fund" },
  { label: "Mid Cap", group: "Equity Scheme", category: "Mid Cap Fund" },
  { label: "Small Cap", group: "Equity Scheme", category: "Small Cap Fund" },
  { label: "ELSS (tax saver)", group: "Equity Scheme", category: "ELSS" },
  { label: "Index funds", group: "Other Scheme", category: "Index Funds" },
  { label: "Liquid", group: "Debt Scheme", category: "Liquid Fund" },
];

type Filters = { q: string; cat: string; house: string; plan: string; option: string; inactive: boolean };
const EMPTY: Filters = { q: "", cat: "", house: "", plan: "", option: "", inactive: false };

function fromUrl(): Filters {
  const p = new URLSearchParams(window.location.search);
  return { q: p.get("q") ?? "", cat: p.get("cat") ?? "", house: p.get("house") ?? "", plan: p.get("plan") ?? "",
           option: p.get("option") ?? "", inactive: p.get("inactive") === "1" };
}

function query(f: Filters, offset = 0) {
  const [group, category] = f.cat ? f.cat.split("|") : ["", ""];
  const p = new URLSearchParams();
  if (f.q.trim()) p.set("q", f.q.trim());
  if (group) p.set("group", group);
  if (category) p.set("category", category);
  if (f.house) p.set("house", f.house);
  if (f.plan) p.set("plan", f.plan);
  if (f.option) p.set("option", f.option);
  if (f.inactive) p.set("include_inactive", "true");
  if (offset) p.set("offset", String(offset));
  return p.toString();
}

function Segmented({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <fieldset>
      <legend className="text-xs text-muted mb-1">{label}</legend>
      <div className="inline-flex gap-1 bg-surface-2 rounded-lg p-0.5">
        {options.map(([v, text]) => (
          <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
            className={`text-sm px-3 py-1 rounded-md ${value === v ? "bg-surface shadow-sm font-medium" : "text-muted hover:text-ink"}`}>{text}</button>
        ))}
      </div>
    </fieldset>
  );
}

function Row({ s }: { s: FundScheme }) {
  return (
    <li>
      <Link href={`/funds/${s.code}`} className="flex items-start justify-between gap-3 py-3 px-1 -mx-1 rounded-lg hover:bg-surface-2/60">
        <span className="min-w-0">
          <span className="block text-sm font-medium text-ink">{s.fund}</span>
          <span className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge variant={s.plan === "Direct" ? "accent" : "neutral"}>{s.plan}</Badge>
            <Badge>{s.option}</Badge>
            {!s.active && <Badge variant="warn">No NAV since {date(s.nav_date)}</Badge>}
            <span className="text-xs text-muted">{s.house} · {s.category}</span>
          </span>
        </span>
        <span className="text-right shrink-0">
          <span className="block text-sm font-semibold tabular">{nav(s.nav)}</span>
          <span className="block text-xs text-muted">NAV · {date(s.nav_date)}</span>
        </span>
      </Link>
    </li>
  );
}

export default function FundsPage() {
  const [f, setF] = useState<Filters>(EMPTY);
  const [ready, setReady] = useState(false);
  const [data, setData] = useState<FundSearch | null>(null);
  const [rows, setRows] = useState<FundScheme[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setF(fromUrl()); setReady(true); }, []);

  useEffect(() => {
    if (!ready) return;
    const p = new URLSearchParams();   // shareable URL with the current filters
    if (f.q) p.set("q", f.q);
    if (f.cat) p.set("cat", f.cat);
    if (f.house) p.set("house", f.house);
    if (f.plan) p.set("plan", f.plan);
    if (f.option) p.set("option", f.option);
    if (f.inactive) p.set("inactive", "1");
    history.replaceState(null, "", p.toString() ? `?${p}` : window.location.pathname);

    setLoading(true);
    const t = setTimeout(() => {   // wait for typing to pause
      api<FundSearch>(`/api/funds?${query(f)}`)
        .then((d) => { setData(d); setRows(d.rows); setError(null); })
        .catch((e: Error) => setError(e.message))
        .finally(() => setLoading(false));
    }, f.q ? 250 : 0);
    return () => clearTimeout(t);
  }, [f, ready]);

  async function more() {
    setLoading(true);
    try {
      const d = await api<FundSearch>(`/api/funds?${query(f, rows.length)}`);
      setRows((r) => [...r, ...d.rows]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const set = (patch: Partial<Filters>) => setF((cur) => ({ ...cur, ...patch }));
  const filtered = f.cat || f.house || f.plan || f.option || f.inactive;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Mutual funds</h1>
        <p className="text-sm text-ink-2 mt-1 max-w-3xl">
          Every mutual fund scheme in India with its latest NAV, from AMFI&apos;s official daily file. Search by fund,
          fund house or scheme code; Direct and Regular plans of the same fund are listed side by side.
        </p>
      </div>

      <Card>
        <label htmlFor="fund-q" className="sr-only">Search mutual funds</label>
        <input id="fund-q" value={f.q} onChange={(e) => set({ q: e.target.value })} type="search"
          placeholder="Search: Parag Parikh, HDFC flexi, nifty index, 122639…"
          className="w-full bg-surface border border-line rounded-xl px-4 py-3 text-base outline-none focus:border-accent focus:ring-2 focus:ring-accent/20" />

        <div className="mt-3 flex flex-wrap gap-2" aria-label="Popular categories">
          {SHORTCUTS.map((s) => {
            const on = f.cat === `${s.group}|${s.category}`;
            return (
              <button key={s.label} type="button" aria-pressed={on} onClick={() => set({ cat: on ? "" : `${s.group}|${s.category}` })}
                className={`text-xs px-3 py-1.5 rounded-full border ${on ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-2 hover:border-ink-2"}`}>
                {s.label}
              </button>
            );
          })}
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto_auto] items-end">
          <label className="text-xs text-muted">
            Category
            <select value={f.cat} onChange={(e) => set({ cat: e.target.value })}
              className="mt-1 w-full bg-surface border border-line rounded-lg px-2.5 py-2 text-sm text-ink">
              <option value="">All categories</option>
              {Object.entries(data?.facets.groups ?? {}).map(([group, cats]) => (
                <optgroup key={group} label={group}>
                  {cats.map((c) => <option key={c} value={`${group}|${c}`}>{c}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="text-xs text-muted">
            Fund house
            <select value={f.house} onChange={(e) => set({ house: e.target.value })}
              className="mt-1 w-full bg-surface border border-line rounded-lg px-2.5 py-2 text-sm text-ink">
              <option value="">All fund houses</option>
              {(data?.facets.houses ?? []).map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
          <Segmented label="Plan" value={f.plan} onChange={(v) => set({ plan: v })} options={[["", "All"], ["Direct", "Direct"], ["Regular", "Regular"]]} />
          <Segmented label="Option" value={f.option} onChange={(v) => set({ option: v })} options={[["", "All"], ["Growth", "Growth"], ["IDCW", "IDCW"]]} />
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <label className="inline-flex items-center gap-2 text-sm text-ink-2 cursor-pointer min-h-11 sm:min-h-0">
            <input type="checkbox" checked={f.inactive} onChange={(e) => set({ inactive: e.target.checked })} className="accent-[var(--accent)] w-4 h-4" />
            Include schemes with no recent NAV (matured or closed)
          </label>
          {filtered && <button type="button" onClick={() => setF({ ...EMPTY, q: f.q })} className="text-sm text-accent hover:underline">Clear filters</button>}
        </div>
      </Card>

      {error && <ErrorBox message={error} />}

      <Card title={data ? <>{data.total.toLocaleString("en-IN")} schemes <span className="text-xs font-normal text-muted ml-1">NAVs as of {date(data.nav_date)}</span></> : "Schemes"}
        action={data && <SourceLink name="AMFI" url="https://www.amfiindia.com/net-asset-value" when="updated each evening" />}>
        {!data && !error && <div className="space-y-3">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-14" />)}</div>}
        {data && rows.length === 0 && (
          <p className="text-sm text-muted py-6 text-center">
            No schemes match{f.q ? <> &ldquo;{f.q}&rdquo;</> : ""}. Try fewer words or clear the filters.
          </p>
        )}
        <ul className={`divide-y divide-line ${loading ? "opacity-60" : ""}`}>
          {rows.map((s) => <Row key={s.code} s={s} />)}
        </ul>
        {data && rows.length < data.total && (
          <div className="mt-3 text-center">
            <button type="button" onClick={more} disabled={loading}
              className="text-sm px-4 py-2 rounded-lg border border-line text-ink-2 hover:border-accent hover:text-accent disabled:opacity-50">
              {loading ? "Loading…" : `Show more (${(data.total - rows.length).toLocaleString("en-IN")} left)`}
            </button>
          </div>
        )}
      </Card>

      <p className="text-xs text-muted">
        NAV is the price of one unit, published once a day after markets close. A higher NAV doesn&apos;t make a fund
        better or worse value. Mutual fund investments are subject to market risks; read all scheme-related documents
        carefully. Research tool, not investment advice.
      </p>
    </div>
  );
}
