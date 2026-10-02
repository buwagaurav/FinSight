"use client";

import { useEffect, useState } from "react";
import CandleChart, { CANDLE_RANGES, CandleRange } from "@/components/stock/CandleChart";
import Chart, { baseOption } from "@/components/Chart";
import { Card, InfoTip, LabelBadge, SourceLink, Stat } from "@/components/ui";
import { Company } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { useCurrency } from "@/components/CurrencyContext";

const RANGES = [{ label: "1Y", days: 365 }, { label: "3Y", days: 3 * 365 }, { label: "5Y", days: 5 * 365 }];
type Mode = "line" | "candles";
const MODE_KEY = "finsight.chart.mode";

export default function Overview({ c }: { c: Company }) {
  const [range, setRange] = useState(RANGES[0]);
  const [mode, setMode] = useState<Mode>("line");
  const [candleRange, setCandleRange] = useState<CandleRange>("1d");
  const [candleChange, setCandleChange] = useState<number | null>(null);
  useEffect(() => { try { if (localStorage.getItem(MODE_KEY) === "candles") setMode("candles"); } catch { /* not remembered */ } }, []);
  const chooseMode = (m: Mode) => { setMode(m); try { localStorage.setItem(MODE_KEY, m); } catch { /* not remembered */ } };
  const cutoff = new Date(Date.now() - range.days * 864e5).toISOString().slice(0, 10);
  const prices = c.prices.filter((p) => p.date >= cutoff);
  const lineChange = prices.length > 1 ? (prices.at(-1)!.close / prices[0].close - 1) * 100 : null;
  const change = mode === "line" ? lineChange : candleChange;
  const rangeLabel = mode === "line" ? range.label : CANDLE_RANGES.find((x) => x.id === candleRange)!.label;
  const tab = (active: boolean) => `text-xs px-2.5 py-1 rounded-md ${active ? "bg-surface shadow-sm font-medium" : "text-muted hover:text-ink"}`;
  const t = c.technical;
  const cur = useCurrency();
  const trendLabel = t.trend === "Uptrend" ? "Improving" : t.trend === "Downtrend" ? "Weak" : "Stable";

  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <Card className="lg:col-span-2" title={<>Price <span className={`ml-2 text-xs font-medium ${change != null && change >= 0 ? "text-good" : "text-bad"}`}>{change != null && `${change >= 0 ? "▲" : "▼"} ${pct(Math.abs(change))} in ${rangeLabel}`}</span></>}
        action={
          <div className="flex flex-wrap justify-end gap-2">
            <div role="tablist" aria-label="Chart type" className="flex gap-1 bg-surface-2 rounded-lg p-0.5">
              {(["line", "candles"] as Mode[]).map((m) => (
                <button key={m} role="tab" aria-selected={mode === m} onClick={() => chooseMode(m)} className={tab(mode === m)}>
                  {m === "line" ? "Line" : "Candles"}
                </button>
              ))}
            </div>
            <div role="tablist" aria-label="Range" className="flex gap-1 bg-surface-2 rounded-lg p-0.5">
              {mode === "line"
                ? RANGES.map((r) => <button key={r.label} role="tab" aria-selected={r === range} onClick={() => setRange(r)} className={tab(r === range)}>{r.label}</button>)
                : CANDLE_RANGES.map((r) => <button key={r.id} role="tab" aria-selected={r.id === candleRange} onClick={() => setCandleRange(r.id)} className={tab(r.id === candleRange)}>{r.label}</button>)}
            </div>
          </div>
        }>
        {mode === "candles" ? <CandleChart symbol={c.profile.symbol} range={candleRange} onChange={setCandleChange} /> : <Chart height={300} label={`Share price over ${range.label}`} build={(k) => {
          const base = baseOption(k);
          return {
            ...base,
            legend: { show: false },
            tooltip: { ...base.tooltip, valueFormatter: (v) => money(Number(v), cur) },
            xAxis: { type: "time", axisLine: { lineStyle: { color: k.line } }, axisLabel: { color: k.muted, fontSize: 11, hideOverlap: true }, splitLine: { show: false } },
            yAxis: { ...base.yAxis, scale: true } as never,
            series: [{
              type: "line", name: "Close", showSymbol: false, data: prices.map((p) => [p.date, p.close]),
              lineStyle: { width: 2, color: k.s1 }, itemStyle: { color: k.s1 },
              areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: k.s1 + "33" }, { offset: 1, color: k.s1 + "00" }] } },
            }],
          };
        }} />}
        <SourceLink name={c.profile.source.name} url={c.profile.source.url} when="prices may be delayed" />
      </Card>

      <Card title="Price trend" action={<LabelBadge label={trendLabel} />}>
        <div className="text-lg font-medium">{t.trend}</div>
        <ul className="text-sm text-ink-2 mt-2 space-y-1 list-disc pl-4">{t.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        <div className="grid grid-cols-2 gap-4 mt-4 pt-4 border-t border-line">
          <Stat label="1-year return" value={pct(t.return_1y_pct, 1, true)} />
          <Stat label="Volatility" term="Volatility" value={pct(t.volatility_1y_pct, 0)} />
          <Stat label="Max drawdown" term="Drawdown" value={pct(t.max_drawdown_1y_pct, 0)} />
          <Stat label="200-day avg" value={money(t.sma200, cur, 0)} />
        </div>
        <p className="text-xs text-muted mt-4">Trend describes the past, not the future. It is not included in the overall score.</p>
      </Card>

      {c.profile.summary && (
        <Card className="lg:col-span-3" title="About the company">
          <p className="text-sm text-ink-2 leading-relaxed line-clamp-4 hover:line-clamp-none">{c.profile.summary}</p>
          <div className="flex flex-wrap gap-4 mt-3 text-sm">
            {c.profile.promoter_holding_pct != null && <span className="text-ink-2">Promoter / insider holding: <b className="text-ink">{pct(c.profile.promoter_holding_pct)}</b><InfoTip term="Promoter holding" /></span>}
            {c.profile.institutional_holding_pct != null && <span className="text-ink-2">Institutional holding: <b className="text-ink">{pct(c.profile.institutional_holding_pct)}</b></span>}
            {c.profile.website && <a href={c.profile.website} target="_blank" rel="noreferrer" className="tap text-accent hover:underline">Company website ↗</a>}
          </div>
        </Card>
      )}
    </div>
  );
}
