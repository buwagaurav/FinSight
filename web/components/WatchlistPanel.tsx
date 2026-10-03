"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Card, LabelBadge, Skeleton } from "./ui";
import { useUser } from "./UserContext";
import { useWatchlist } from "./WatchlistContext";
import { api, WatchDetails, Watchlist } from "@/lib/api";
import { Currency, currencyOf, date, money, pct, safeUrl } from "@/lib/format";

const RANK: Record<string, number> = { Weak: 0, Watchlist: 1, Stable: 2, Improving: 3, Strong: 4 };

function RangeDot({ low, high, price, cur }: { low: number; high: number; price: number; cur: Currency }) {
  const pos = Math.min(100, Math.max(0, ((price - low) / (high - low || 1)) * 100));
  return (
    <div className="w-24" title={`52-week range ${money(low, cur, 0)} – ${money(high, cur, 0)}`}>
      <div className="relative h-1 rounded-full bg-surface-2">
        <div className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent ring-2 ring-surface" style={{ left: `${pos}%` }} />
      </div>
      <div className="mt-1 text-[10px] text-muted">{pos >= 90 ? "Near 52-week high" : pos <= 10 ? "Near 52-week low" : "52-week range"}</div>
    </div>
  );
}

function Note({ symbol, initial }: { symbol: string; initial: string | null }) {
  const [value, setValue] = useState(initial ?? "");
  const [editing, setEditing] = useState(false);
  const saved = useRef(initial ?? "");
  async function save() {
    setEditing(false);
    if (value.trim() === saved.current) return;
    saved.current = value.trim();
    await api(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "PATCH", body: JSON.stringify({ note: value }) }, { auth: true }).catch(() => {});
  }
  if (editing) {
    return (
      <input autoFocus value={value} maxLength={200} onChange={(e) => setValue(e.target.value)} onBlur={save}
        onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") { setValue(saved.current); setEditing(false); } }}
        aria-label={`Note for ${symbol}`} placeholder="Add a note"
        className="mt-1 w-full max-w-[220px] rounded-md border border-line bg-surface px-2 py-0.5 text-xs outline-none focus:border-accent" />
    );
  }
  return (
    <button type="button" onClick={() => setEditing(true)} className="mt-0.5 block max-w-[220px] truncate text-left text-xs text-muted hover:text-ink">
      {value ? `✎ ${value}` : "+ Add note"}
    </button>
  );
}

type Market = "IN" | "US";
const TAB_KEY = "finsight.watchlist.market";

export default function WatchlistPanel() {
  const { user, authEnabled } = useUser();
  const active = !!user || !authEnabled;
  const { version, toggle } = useWatchlist();
  const [list, setList] = useState<Watchlist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, WatchDetails>>({});
  const [tab, setTab] = useState<Market>("IN");
  useEffect(() => { try { if (localStorage.getItem(TAB_KEY) === "US") setTab("US"); } catch { /* not remembered */ } }, []);
  const chooseTab = (m: Market) => { setTab(m); try { localStorage.setItem(TAB_KEY, m); } catch { /* not remembered */ } };

  useEffect(() => {
    if (!active) return;
    api<Watchlist>("/api/watchlist", undefined, { auth: true }).then(setList).catch((e: Error) => setError(e.message));
  }, [active, version]);

  // Score and latest filing, a few rows at a time so a long watchlist doesn't overload the server
  useEffect(() => {
    if (!list) return;
    let cancelled = false;
    const queue = list.items.filter((i) => !details[i.base]).map((i) => i.base);
    const since = list.previous_visit ? `?since=${encodeURIComponent(list.previous_visit)}` : "";
    const worker = async () => {
      while (queue.length && !cancelled) {
        const s = queue.shift()!;
        const d = await api<WatchDetails>(`/api/watchlist/${encodeURIComponent(s)}/details${since}`, undefined, { auth: true })
          .catch(() => ({ symbol: s, score_error: "Unavailable", filing_error: "Unavailable" }) as WatchDetails);
        if (!cancelled) setDetails((cur) => ({ ...cur, [s]: d }));
      }
    };
    Promise.all([worker(), worker(), worker(), worker()]);
    return () => { cancelled = true; };
  }, [list]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!active) return null;
  const all = list?.items ?? [];
  const counts = { IN: all.filter((i) => i.market !== "US").length, US: all.filter((i) => i.market === "US").length };
  // an empty tab with stocks in the other market shows that market instead (the saved choice stays)
  const shown: Market = counts[tab] === 0 && counts[tab === "US" ? "IN" : "US"] > 0 ? (tab === "US" ? "IN" : "US") : tab;
  const items = all.filter((i) => (i.market === "US") === (shown === "US"));

  return (
    <Card title={<span className="flex flex-wrap items-center gap-3">My watchlist
        {list && all.length > 0 && (
          <span role="tablist" aria-label="Market" className="inline-flex rounded-lg border border-line p-0.5 text-xs font-normal">
            {(["IN", "US"] as Market[]).map((m) => (
              <button key={m} role="tab" aria-selected={shown === m} onClick={() => chooseTab(m)}
                className={`rounded-md px-2.5 py-1 ${shown === m ? "bg-accent text-white font-medium" : "text-ink-2 hover:text-ink"}`}>
                {m === "IN" ? "India" : "US"} <span className={shown === m ? "text-white/80" : "text-muted"}>{counts[m]}</span>
              </button>
            ))}
          </span>
        )}
        {list && all.length > 0 && <span className="text-xs font-normal text-muted">{items.length} of {list.limit}</span>}
      </span>}
      action={<Link href={`/screener?market=${shown}`} className="tap text-sm text-accent hover:underline">Find stocks to watch →</Link>}>
      {error && <p className="text-sm text-bad">{error}</p>}
      {!list && !error && <div className="space-y-2"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>}
      {list && all.length === 0 && (
        <div className="rounded-xl border border-dashed border-line p-6 text-center">
          <p className="font-medium">Follow the stocks you care about</p>
          <p className="mt-1 text-sm text-ink-2">Tap <span className="text-[#f5b50a]">☆ Watch</span> on any company or screener result. Your stocks show up here with today&apos;s move, score changes and new filings.</p>
          <div className="mt-4 flex flex-wrap justify-center gap-2 text-sm">
            {[["TCS.NS", "TCS"], ["RELIANCE.NS", "Reliance"], ["HDFCBANK.NS", "HDFC Bank"], ["AAPL.US", "Apple"], ["NVDA.US", "NVIDIA"]].map(([s, n]) => (
              <Link key={s} href={`/stock/${s}`} className="rounded-full border border-line px-3 py-1 hover:border-accent hover:text-accent">{n}</Link>
            ))}
          </div>
        </div>
      )}
      {items.length > 0 && (
        <div className="scroll-shadow -mx-4 overflow-x-auto sm:mx-0">
          <table className="w-full min-w-[760px] text-sm tabular-nums">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                <th className="py-2 pl-4 pr-3 text-left font-medium sm:pl-0">Company</th>
                <th className="px-3 py-2 text-right font-medium">Price</th>
                <th className="px-3 py-2 text-left font-medium">52 weeks</th>
                <th className="px-3 py-2 text-left font-medium">FinSight score</th>
                <th className="px-3 py-2 text-left font-medium">Latest filing</th>
                <th className="py-2 pl-3 pr-4 sm:pr-0"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => {
                const d = details[i.base];
                const cur = currencyOf(i.symbol);
                const price = d?.price ?? i.price;
                const low = d?.week52_low ?? i.week52_low, high = d?.week52_high ?? i.week52_high;
                const change = d?.change_pct ?? i.change_pct;
                const label = d?.label ?? i.label;
                const prev = d ? d.prev_label : null;
                const up = prev && label ? (RANK[label] ?? 0) > (RANK[prev] ?? 0) : null;
                return (
                  <tr key={i.base} className="border-b border-line/60 align-top last:border-0">
                    <td className="py-3 pl-4 pr-3 sm:pl-0">
                      <Link href={`/stock/${i.symbol}`} className="font-medium hover:text-accent">{i.name}</Link>
                      <div className="text-xs text-muted">{i.base.replace(/\.US$/, "")}{cur === "USD" ? " · US" : ""}{i.sector ? ` · ${i.sector}` : ""}</div>
                      <Note symbol={i.base} initial={i.note} />
                    </td>
                    <td className="px-3 py-3 text-right">
                      <div className="font-medium">{money(price, cur, cur === "USD" ? 2 : 0)}</div>
                      {change != null && <div className={`whitespace-nowrap text-xs ${change >= 0 ? "text-good" : "text-bad"}`}>{change >= 0 ? "▲" : "▼"} {pct(Math.abs(change), 2)}</div>}
                    </td>
                    <td className="px-3 py-3">{low != null && high != null && price != null ? <RangeDot low={low} high={high} price={price} cur={cur} /> : <span className="text-muted">—</span>}</td>
                    <td className="px-3 py-3">
                      {!d ? <Skeleton className="h-5 w-24" /> : d.score_error ? <span className="text-xs text-muted">{d.score_error}</span> : (
                        <div>
                          <div className="flex items-center gap-2"><span className="font-semibold">{d.score}</span>{label && <LabelBadge label={label} />}</div>
                          {prev && <div className={`mt-1 text-xs ${up ? "text-good" : "text-bad"}`}>{up ? "▲" : "▼"} was {prev}</div>}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-3 max-w-[260px]">
                      {!d ? <Skeleton className="h-5 w-40" /> : d.filing ? (
                        <div>
                          <div className="flex items-center gap-2 text-xs">
                            {d.filing.new && <span className="rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-semibold text-white">New</span>}
                            <span className="text-muted">{date(d.filing.published)}</span>
                          </div>
                          {d.filing.url
                            ? <a href={safeUrl(d.filing.url)} target="_blank" rel="noreferrer" className="mt-0.5 line-clamp-2 text-xs text-ink-2 hover:text-accent">{d.filing.category}: {d.filing.text}</a>
                            : <p className="mt-0.5 line-clamp-2 text-xs text-ink-2">{d.filing.category}: {d.filing.text}</p>}
                        </div>
                      ) : <span className="text-xs text-muted">{d.filing_error ?? "No recent filings"}</span>}
                    </td>
                    <td className="py-3 pl-3 pr-4 text-right sm:pr-0">
                      <button type="button" onClick={() => toggle(i.base)} aria-label={`Remove ${i.name} from watchlist`} title="Remove"
                        className="rounded-md px-2 py-1 text-muted hover:bg-bad-soft hover:text-bad">✕</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
