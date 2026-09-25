"use client";

import { useState } from "react";
import Chart, { baseOption } from "@/components/Chart";
import { Card, InfoTip, LabelBadge, SourceLink, Stat } from "@/components/ui";
import { Company } from "@/lib/api";
import { pct, rupees } from "@/lib/format";

const RANGES = [{ label: "1Y", days: 365 }, { label: "3Y", days: 3 * 365 }, { label: "5Y", days: 5 * 365 }];

export default function Overview({ c }: { c: Company }) {
  const [range, setRange] = useState(RANGES[0]);
  const cutoff = new Date(Date.now() - range.days * 864e5).toISOString().slice(0, 10);
  const prices = c.prices.filter((p) => p.date >= cutoff);
  const change = prices.length > 1 ? (prices.at(-1)!.close / prices[0].close - 1) * 100 : null;
  const t = c.technical;
  const trendLabel = t.trend === "Uptrend" ? "Improving" : t.trend === "Downtrend" ? "Weak" : "Stable";

  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <Card className="lg:col-span-2" title={<>Price <span className={`ml-2 text-xs font-medium ${change != null && change >= 0 ? "text-good" : "text-bad"}`}>{change != null && `${change >= 0 ? "▲" : "▼"} ${pct(Math.abs(change))} in ${range.label}`}</span></>}
        action={
          <div role="tablist" className="flex gap-1 bg-surface-2 rounded-lg p-0.5">
            {RANGES.map((r) => (
              <button key={r.label} role="tab" aria-selected={r === range} onClick={() => setRange(r)}
                className={`text-xs px-2.5 py-1 rounded-md ${r === range ? "bg-surface shadow-sm font-medium" : "text-muted hover:text-ink"}`}>{r.label}</button>
            ))}
          </div>
        }>
        <Chart height={300} label={`Share price over ${range.label}`} build={(k) => {
          const base = baseOption(k);
          return {
            ...base,
            legend: { show: false },
            tooltip: { ...base.tooltip, valueFormatter: (v) => rupees(Number(v)) },
            xAxis: { type: "time", axisLine: { lineStyle: { color: k.line } }, axisLabel: { color: k.muted, fontSize: 11 }, splitLine: { show: false } },
            yAxis: { ...base.yAxis, scale: true } as never,
            series: [{
              type: "line", name: "Close", showSymbol: false, data: prices.map((p) => [p.date, p.close]),
              lineStyle: { width: 2, color: k.s1 }, itemStyle: { color: k.s1 },
              areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: k.s1 + "33" }, { offset: 1, color: k.s1 + "00" }] } },
            }],
          };
        }} />
        <SourceLink name={c.profile.source.name} url={c.profile.source.url} when="prices may be delayed" />
      </Card>

      <Card title="Price trend" action={<LabelBadge label={trendLabel} />}>
        <div className="text-lg font-medium">{t.trend}</div>
        <ul className="text-sm text-ink-2 mt-2 space-y-1 list-disc pl-4">{t.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        <div className="grid grid-cols-2 gap-4 mt-4 pt-4 border-t border-line">
          <Stat label="1-year return" value={pct(t.return_1y_pct, 1, true)} />
          <Stat label="Volatility" term="Volatility" value={pct(t.volatility_1y_pct, 0)} />
          <Stat label="Max drawdown" term="Drawdown" value={pct(t.max_drawdown_1y_pct, 0)} />
          <Stat label="200-day avg" value={rupees(t.sma200, 0)} />
        </div>
        <p className="text-xs text-muted mt-4">Trend describes the past, not the future. It is not included in the overall score.</p>
      </Card>

      {c.profile.summary && (
        <Card className="lg:col-span-3" title="About the company">
          <p className="text-sm text-ink-2 leading-relaxed line-clamp-4 hover:line-clamp-none">{c.profile.summary}</p>
          <div className="flex flex-wrap gap-4 mt-3 text-sm">
            {c.profile.promoter_holding_pct != null && <span className="text-ink-2">Promoter / insider holding: <b className="text-ink">{pct(c.profile.promoter_holding_pct)}</b><InfoTip term="Promoter holding" /></span>}
            {c.profile.institutional_holding_pct != null && <span className="text-ink-2">Institutional holding: <b className="text-ink">{pct(c.profile.institutional_holding_pct)}</b></span>}
            {c.profile.website && <a href={c.profile.website} target="_blank" rel="noreferrer" className="text-accent hover:underline">Company website ↗</a>}
          </div>
        </Card>
      )}
    </div>
  );
}
