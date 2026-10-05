"use client";

import { useEffect, useState } from "react";
import Chart, { baseOption } from "@/components/Chart";
import { Badge, Card, Skeleton, SourceLink } from "@/components/ui";
import { api, Backtest as BacktestData, StrategyKey } from "@/lib/api";
import { date, money, pct } from "@/lib/format";

const KEYS: StrategyKey[] = ["ema_trend", "rsi", "macd", "supertrend"];
const PERIODS = [{ years: null, label: "All (~9 years)" }, { years: 5, label: "Last 5 years" }] as const;

/** A number with its sign, coloured only by sign: no "winner" styling, the reader judges. */
function Signed({ v, suffix = "%" }: { v: number | null | undefined; suffix?: string }) {
  if (v == null) return <span className="text-muted">—</span>;
  return <span className={v >= 0 ? "text-good" : "text-bad"}>{v >= 0 ? "+" : ""}{v.toFixed(1)}{suffix}</span>;
}

export default function Backtest({ symbol }: { symbol: string }) {
  const [years, setYears] = useState<number | null>(null);
  const [data, setData] = useState<BacktestData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<StrategyKey>("ema_trend");

  useEffect(() => {
    setData(null);
    setError(null);
    api<BacktestData>(`/api/company/${encodeURIComponent(symbol)}/backtest${years ? `?years=${years}` : ""}`, undefined, { cache: 300 })
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [symbol, years]);

  const cur = data?.currency ?? "INR";
  const m = (v: number) => money(v, cur, 0);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-warn/40 bg-warn-soft p-3 text-sm text-ink-2">
        <span className="font-semibold text-warn">● Past results, not predictions.</span>{" "}
        These are fixed, textbook rules run on this stock&apos;s past prices with costs, next to simply buying and holding.
        They aren&apos;t recommendations, and a rule that worked here may not work on other stocks or in the future.
      </div>

      <Card title="How each rule would have done"
        action={
          <div role="tablist" aria-label="Period" className="flex gap-1 bg-surface-2 rounded-lg p-0.5">
            {PERIODS.map((p) => (
              <button key={p.label} role="tab" aria-selected={years === p.years} onClick={() => setYears(p.years)}
                className={`text-xs px-2.5 py-1 rounded-md whitespace-nowrap ${years === p.years ? "bg-surface shadow-sm font-medium" : "text-muted hover:text-ink"}`}>{p.label}</button>
            ))}
          </div>
        }>
        {error && <p className="text-sm text-muted">{error}</p>}
        {!data && !error && <Skeleton className="h-56" />}
        {data && (
          <>
            <p className="text-xs text-muted mb-3">
              {date(data.period.from)} to {date(data.period.to)} ({data.period.years} years), starting with {m(data.capital)}.
              Each rule trades at the next day&apos;s open after its signal. Click a row for details.
            </p>
            <div className="scroll-shadow overflow-x-auto -mx-4 sm:mx-0">
              <table className="w-full text-sm tabular min-w-[720px]">
                <thead>
                  <tr className="text-left text-xs text-muted border-b border-line">
                    <th className="py-2 px-2 font-medium">Rule</th>
                    <th className="py-2 px-2 font-medium text-right">Final value</th>
                    <th className="py-2 px-2 font-medium text-right">CAGR</th>
                    <th className="py-2 px-2 font-medium text-right">vs buy &amp; hold</th>
                    <th className="py-2 px-2 font-medium text-right">Worst fall</th>
                    <th className="py-2 px-2 font-medium text-right">Trades</th>
                    <th className="py-2 px-2 font-medium text-right">Time invested</th>
                    <th className="py-2 px-2 font-medium text-right">Costs paid</th>
                  </tr>
                </thead>
                <tbody>
                  {(["buy_hold", ...KEYS] as const).map((k) => {
                    const r = data.results[k];
                    const selectable = k !== "buy_hold";
                    return (
                      <tr key={k} onClick={selectable ? () => setPick(k as StrategyKey) : undefined}
                        className={`border-b border-line/60 ${selectable ? "cursor-pointer hover:bg-surface-2/60" : "bg-surface-2/40"} ${pick === k ? "bg-accent-soft/50" : ""}`}>
                        <td className="py-2.5 px-2">
                          {selectable
                            ? <button type="button" onClick={() => setPick(k as StrategyKey)} aria-pressed={pick === k} className="font-medium text-left hover:text-accent">{r.name}</button>
                            : <span className="font-medium">{r.name}</span>}
                        </td>
                        <td className="py-2.5 px-2 text-right">{m(r.final_value)}</td>
                        <td className="py-2.5 px-2 text-right"><Signed v={r.cagr_pct} /></td>
                        <td className="py-2.5 px-2 text-right">{k === "buy_hold" ? <span className="text-muted">—</span> : <Signed v={r.cagr_vs_hold_pct} suffix=" pts" />}</td>
                        <td className="py-2.5 px-2 text-right text-bad">{pct(r.max_drawdown_pct, 1)}</td>
                        <td className="py-2.5 px-2 text-right">{k === "buy_hold" ? <span className="text-muted">Held throughout</span> : <>{r.trades}{r.open_trade ? " + 1 open" : ""}</>}</td>
                        <td className="py-2.5 px-2 text-right">{pct(r.time_invested_pct, 0)}</td>
                        <td className="py-2.5 px-2 text-right">{m(r.costs_paid)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-muted mt-2">CAGR: average yearly growth. &quot;vs buy &amp; hold&quot;: difference in CAGR, in percentage points. Worst fall: largest drop from a previous high.</p>
          </>
        )}
      </Card>

      {data && (() => {
        const r = data.results[pick];
        const trades = r.trades_list ?? [];
        return (
          <>
            <Card title={<>{r.name} <span className="text-xs font-normal text-muted ml-1">{r.rule}</span></>}>
              <Chart height={300} label={`Growth of ${m(data.capital)}: ${r.name} versus buy and hold`} build={(c) => {
                const base = baseOption(c);
                return {
                  ...base,
                  legend: { ...base.legend as object, data: [r.name, "Buy and hold"] },
                  tooltip: { ...base.tooltip as object, valueFormatter: (v: unknown) => (typeof v === "number" ? m(v) : "") },
                  xAxis: { ...base.xAxis as object, data: data.curves.dates.map((d) => date(d)), boundaryGap: false },
                  yAxis: { ...base.yAxis as object, scale: true, axisLabel: { color: c.muted, fontSize: 11, formatter: (v: number) => new Intl.NumberFormat("en-IN", { notation: "compact" }).format(v) } },
                  series: [
                    { name: r.name, type: "line", showSymbol: false, data: data.curves[pick], lineStyle: { color: c.s1, width: 2 }, itemStyle: { color: c.s1 } },
                    { name: "Buy and hold", type: "line", showSymbol: false, data: data.curves.buy_hold, lineStyle: { color: c.muted, width: 1.5 }, itemStyle: { color: c.muted } },
                  ],
                };
              }} />
              <dl className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                <div><dt className="text-xs text-muted">Winning trades</dt><dd className="font-semibold tabular">{r.win_rate_pct == null ? "—" : pct(r.win_rate_pct, 0)}</dd></div>
                <div><dt className="text-xs text-muted">Average win / loss</dt><dd className="font-semibold tabular"><Signed v={r.avg_win_pct} /> / <Signed v={r.avg_loss_pct} /></dd></div>
                <div><dt className="text-xs text-muted">Worst losing streak</dt><dd className="font-semibold tabular">{r.worst_losing_streak} trades</dd></div>
                <div><dt className="text-xs text-muted">Total return</dt><dd className="font-semibold tabular"><Signed v={r.total_return_pct} /> <span className="text-xs font-normal text-muted">(buy &amp; hold <Signed v={data.results.buy_hold.total_return_pct} />)</span></dd></div>
              </dl>
              <p className="mt-2 text-xs text-muted">A high share of winning trades can still lose overall if the losses are bigger than the wins; compare the averages.</p>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card title={`Trades (${trades.length})`}>
                {trades.length === 0 ? <p className="text-sm text-muted">This rule never traded in the period.</p> : (
                  <div className="scroll-shadow overflow-auto max-h-80 -mx-4 sm:mx-0">
                    <table className="w-full text-sm tabular min-w-[440px]">
                      <thead><tr className="text-left text-xs text-muted border-b border-line">
                        <th className="py-1.5 px-2 font-medium">Bought</th><th className="py-1.5 px-2 font-medium">Sold</th>
                        <th className="py-1.5 px-2 font-medium text-right">Shares</th><th className="py-1.5 px-2 font-medium text-right">Return</th>
                      </tr></thead>
                      <tbody>
                        {[...trades].reverse().map((t, i) => (
                          <tr key={i} className="border-b border-line/60">
                            <td className="py-1.5 px-2">{date(t.entry_date)}<span className="block text-xs text-muted">{money(t.entry_price, cur)}</span></td>
                            <td className="py-1.5 px-2">{t.open ? <Badge variant="accent">Still holding</Badge> : date(t.exit_date)}<span className="block text-xs text-muted">{money(t.exit_price, cur)}</span></td>
                            <td className="py-1.5 px-2 text-right">{t.shares}</td>
                            <td className="py-1.5 px-2 text-right"><Signed v={t.return_pct} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="mt-2 text-xs text-muted">Returns are after costs. The open position is valued at the last close.</p>
              </Card>

              <Card title="Year by year">
                <div className="scroll-shadow overflow-auto max-h-80 -mx-4 sm:mx-0">
                  <table className="w-full text-sm tabular">
                    <thead><tr className="text-left text-xs text-muted border-b border-line">
                      <th className="py-1.5 px-2 font-medium">Year</th>
                      <th className="py-1.5 px-2 font-medium text-right">{r.name}</th>
                      <th className="py-1.5 px-2 font-medium text-right">Buy &amp; hold</th>
                    </tr></thead>
                    <tbody>
                      {[...data.yearly].reverse().map((y) => (
                        <tr key={y.year} className="border-b border-line/60">
                          <td className="py-1.5 px-2">{y.year}{y.partial && <span className="text-xs text-muted"> (part)</span>}</td>
                          <td className="py-1.5 px-2 text-right"><Signed v={y[pick]} /></td>
                          <td className="py-1.5 px-2 text-right"><Signed v={y.buy_hold} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-xs text-muted">Rules often beat buy-and-hold in falling years and lag it in rising ones.</p>
              </Card>
            </div>

            <Card title="Read before relying on this">
              <ul className="list-disc pl-5 space-y-1.5 text-sm text-ink-2">
                {data.warnings.map((w) => <li key={w}>{w}</li>)}
                <li>Costs used: {data.costs}</li>
              </ul>
              <div className="mt-3"><SourceLink name={data.source.name} url={data.source.url} /></div>
            </Card>
          </>
        );
      })()}
    </div>
  );
}
