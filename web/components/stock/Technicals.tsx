"use client";

import { useEffect, useState } from "react";
import Chart, { baseOption, ChartColors } from "@/components/Chart";
import { useCurrency } from "@/components/CurrencyContext";
import { Badge, Card, InfoTip, Skeleton, SourceLink } from "@/components/ui";
import { api, IndicatorView, Timeframe } from "@/lib/api";
import { money } from "@/lib/format";

const TIMEFRAMES: { id: Timeframe; label: string }[] = [
  { id: "daily", label: "Daily · 1Y" },
  { id: "weekly", label: "Weekly · 5Y" },
  { id: "intraday", label: "Intraday · 5D" },
];

type Overlay = { key: string; label: string; series: string[]; intradayOnly?: boolean };
const OVERLAYS: Overlay[] = [
  { key: "ema20", label: "EMA 20", series: ["ema20"] },
  { key: "ema50", label: "EMA 50", series: ["ema50"] },
  { key: "ema200", label: "EMA 200", series: ["ema200"] },
  { key: "sma50", label: "SMA 50", series: ["sma50"] },
  { key: "sma200", label: "SMA 200", series: ["sma200"] },
  { key: "bollinger", label: "Bollinger", series: ["bb_upper", "bb_mid", "bb_lower"] },
  { key: "supertrend", label: "Supertrend", series: ["supertrend"] },
  { key: "vwap", label: "VWAP", series: ["vwap"], intradayOnly: true },
];

// glossary term for each reading's "?"
const TERM: Record<string, string> = {
  ema20: "EMA", ema50: "EMA", ema200: "EMA", sma: "SMA", rsi: "RSI", macd: "MACD", bollinger: "Bollinger",
  supertrend: "Supertrend", adx: "ADX", stochastic: "Stochastic", atr: "ATR", obv: "OBV", vwap: "VWAP",
};
const TONE = { positive: "good", negative: "bad", neutral: "neutral" } as const;
const TONE_LABEL = { positive: "▲", negative: "▼", neutral: "●" };

/** A dashed horizontal guide (RSI 30/70 and so on) drawn as a flat line series. */
const guide = (value: number, n: number, color: string) => ({
  type: "line" as const, data: Array(n).fill(value), symbol: "none", silent: true,
  lineStyle: { color, width: 1, type: "dashed" as const }, tooltip: { show: false },
});

function Panel({ title, term, height = 170, label, build }: {
  title: string; term: string; height?: number; label: string; build: (c: ChartColors) => object;
}) {
  return (
    <Card title={<>{title}<InfoTip term={term} /></>}>
      <Chart height={height} label={label} build={(c) => build(c) as never} />
    </Card>
  );
}

function LiveStatus({ data }: { data: IndicatorView }) {
  const us = data.market.id === "US";
  const when = data.timeframe === "intraday"   // in the exchange's own time, whatever the reader's time zone
    ? `${new Date(data.market.last_bar).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: us ? "America/New_York" : "Asia/Kolkata" })} ${us ? "ET" : "IST"}`
    : data.bars.at(-1)?.[0];
  return data.refresh_seconds ? (
    <span className="ml-2 inline-flex items-center gap-1.5 text-xs font-normal text-good">
      <span className="relative flex h-2 w-2" aria-hidden><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-good opacity-60" /><span className="relative inline-flex h-2 w-2 rounded-full bg-good" /></span>
      Live · updates every {data.refresh_seconds >= 120 ? `${Math.round(data.refresh_seconds / 60)} min` : "minute"} · last bar {when}
    </span>
  ) : (
    <span className="ml-2 text-xs font-normal text-muted">Market closed · last bar {when}</span>
  );
}

export default function Technicals({ symbol }: { symbol: string }) {
  const cur = useCurrency();
  const [timeframe, setTimeframe] = useState<Timeframe>("daily");
  const [data, setData] = useState<IndicatorView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [on, setOn] = useState<Set<string>>(new Set(["ema20", "ema50", "supertrend"]));

  // While the market is open the server says how often to re-ask (intraday every minute), so today's bar, every
  // indicator and every reading move with the market. Paused while the browser tab is hidden.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let wake: (() => void) | undefined;
    setData(null);
    setError(null);
    const path = `/api/company/${encodeURIComponent(symbol)}/indicators?timeframe=${timeframe}`;
    const load = (fresh: boolean) =>
      api<IndicatorView>(path, undefined, fresh ? undefined : { cache: 60 })
        .then((d) => {
          if (cancelled) return;
          setData(d);
          setError(null);
          if (d.refresh_seconds) timer = setTimeout(tick, d.refresh_seconds * 1000);
        })
        .catch((e: Error) => { if (!cancelled) setError(e.message); });
    const tick = () => {
      if (!document.hidden) return load(true);
      wake = () => { if (!document.hidden) { document.removeEventListener("visibilitychange", wake!); load(true); } };
      document.addEventListener("visibilitychange", wake);
    };
    load(false);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (wake) document.removeEventListener("visibilitychange", wake);
    };
  }, [symbol, timeframe]);

  const toggle = (key: string) => setOn((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const labels = data?.bars.map((b) => b[0]) ?? [];
  const s = data?.series ?? {};
  const n = labels.length;
  const axis = (c: ChartColors) => ({ ...baseOption(c).xAxis as object, data: labels, axisLabel: { color: c.muted, fontSize: 11, hideOverlap: true } });
  const line = (name: string, values: (number | null)[] | undefined, color: string, width = 1.5) =>
    ({ name, type: "line" as const, data: values ?? [], symbol: "none", connectNulls: false, lineStyle: { color, width }, itemStyle: { color } });

  return (
    <div className="space-y-4">
      <Card title={<>Technical indicators{data && <LiveStatus data={data} />}</>}
        action={
          <div role="tablist" aria-label="Timeframe" className="flex flex-wrap gap-1 bg-surface-2 rounded-lg p-0.5">
            {TIMEFRAMES.map((t) => (
              <button key={t.id} role="tab" aria-selected={timeframe === t.id} onClick={() => setTimeframe(t.id)}
                className={`text-xs px-2.5 py-1 rounded-md whitespace-nowrap ${timeframe === t.id ? "bg-surface shadow-sm font-medium" : "text-muted hover:text-ink"}`}>
                {t.label}
              </button>
            ))}
          </div>
        }>
        {error && <p className="text-sm text-muted">{error}</p>}
        {!data && !error && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-24" />)}</div>}
        {data && (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.readings.map((r) => (
              <li key={r.key} className="rounded-xl border border-line p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-xs text-muted flex items-center">{r.name}{TERM[r.key] && <InfoTip term={TERM[r.key]} />}</span>
                  <Badge variant={TONE[r.tone]}><span aria-hidden className="text-[9px]">{TONE_LABEL[r.tone]}</span>{r.tone === "neutral" ? "Neutral" : r.tone === "positive" ? "Positive" : "Negative"}</Badge>
                </div>
                <div className="mt-1 text-base font-semibold tabular">{r.value}</div>
                <p className="mt-0.5 text-xs text-ink-2 leading-snug">{r.reading}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {data && (
        <>
          <Card title="Price with overlays">
            <div className="flex flex-wrap gap-2 mb-3" aria-label="Overlays">
              {OVERLAYS.filter((o) => !o.intradayOnly || timeframe === "intraday").map((o) => (
                <button key={o.key} type="button" aria-pressed={on.has(o.key)} onClick={() => toggle(o.key)}
                  className={`text-xs px-3 py-1.5 rounded-full border ${on.has(o.key) ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-2 hover:border-ink-2"}`}>
                  {o.label}
                </button>
              ))}
            </div>
            <Chart height={380} label={`${data.symbol} ${data.timeframe} price with indicator overlays`} build={(c) => {
              const base = baseOption(c);
              const palette: Record<string, string> = { ema20: c.s1, ema50: c.s2, ema200: c.s3, sma50: c.ink2, sma200: c.muted, vwap: c.s1 };
              const overlays = OVERLAYS.filter((o) => on.has(o.key) && (!o.intradayOnly || timeframe === "intraday") && s[o.series[0]]);
              const series: object[] = [{
                name: "Price", type: "candlestick",
                data: data.bars.map((b) => [b[1], b[4], b[3], b[2]]),
                itemStyle: { color: c.good, color0: c.bad, borderColor: c.good, borderColor0: c.bad },
              }];
              for (const o of overlays) {
                if (o.key === "bollinger") {
                  series.push(line("BB upper", s.bb_upper, c.muted, 1), line("BB middle", s.bb_mid, c.muted, 1), line("BB lower", s.bb_lower, c.muted, 1));
                } else if (o.key === "supertrend") {
                  const dir = s.supertrend_dir ?? [];
                  series.push(line("Supertrend (up)", s.supertrend.map((v, i) => (dir[i] === 1 ? v : null)), c.good, 2),
                              line("Supertrend (down)", s.supertrend.map((v, i) => (dir[i] === -1 ? v : null)), c.bad, 2));
                } else {
                  series.push(line(o.label, s[o.series[0]], palette[o.key] ?? c.s1));
                }
              }
              return {
                ...base,
                legend: { show: false },
                grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
                tooltip: { ...base.tooltip as object, trigger: "axis", valueFormatter: (v: unknown) => (typeof v === "number" ? money(v, cur) : String(v ?? "")) },
                xAxis: axis(c),
                yAxis: { ...base.yAxis as object, scale: true, position: "right" },
                dataZoom: [{ type: "inside", start: 0, end: 100 }],
                series,
              };
            }} />
            <p className="text-xs text-muted mt-1">Scroll or pinch to zoom, drag to pan. Supertrend is green in an uptrend and red in a downtrend.</p>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="RSI (14)" term="RSI" label="RSI with 30 and 70 levels" build={(c) => ({
              ...baseOption(c), legend: { show: false }, grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
              xAxis: axis(c), yAxis: { ...baseOption(c).yAxis as object, min: 0, max: 100, interval: 25 },
              series: [line("RSI", s.rsi, c.s1, 2), guide(70, n, c.bad), guide(30, n, c.good)],
            })} />
            <Panel title="MACD (12, 26, 9)" term="MACD" label="MACD line, signal line and histogram" build={(c) => ({
              ...baseOption(c), legend: { ...baseOption(c).legend as object, data: ["MACD", "Signal"] },
              grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true }, xAxis: axis(c),
              series: [
                { name: "Histogram", type: "bar", data: (s.macd_hist ?? []).map((v) => ({ value: v, itemStyle: { color: (v ?? 0) >= 0 ? c.good + "99" : c.bad + "99" } })) },
                line("MACD", s.macd, c.s1, 1.5), line("Signal", s.macd_signal, c.s2, 1.5),
              ],
            })} />
            <Panel title="Stochastic (14, 1, 3)" term="Stochastic" label="Stochastic %K and %D with 20 and 80 levels" build={(c) => ({
              ...baseOption(c), legend: { ...baseOption(c).legend as object, data: ["%K", "%D"] },
              grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true }, xAxis: axis(c),
              yAxis: { ...baseOption(c).yAxis as object, min: 0, max: 100, interval: 20 },
              series: [line("%K", s.stoch_k, c.s1), line("%D", s.stoch_d, c.s2), guide(80, n, c.bad), guide(20, n, c.good)],
            })} />
            <Panel title="ADX (14)" term="ADX" label="ADX with +DI and −DI, and the 25 level" build={(c) => ({
              ...baseOption(c), legend: { ...baseOption(c).legend as object, data: ["ADX", "+DI", "−DI"] },
              grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true }, xAxis: axis(c),
              series: [line("ADX", s.adx, c.ink2, 2), line("+DI", s.plus_di, c.good), line("−DI", s.minus_di, c.bad), guide(25, n, c.muted)],
            })} />
            <Panel title="On-Balance Volume" term="OBV" label="On-balance volume" build={(c) => ({
              ...baseOption(c), legend: { show: false }, grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
              xAxis: axis(c), yAxis: { ...baseOption(c).yAxis as object, scale: true, axisLabel: { color: c.muted, fontSize: 11, formatter: (v: number) => new Intl.NumberFormat("en-IN", { notation: "compact" }).format(v) } },
              series: [line("OBV", s.obv, c.s3, 1.5)],
            })} />
            <Panel title="ATR (14)" term="ATR" label="Average true range" build={(c) => ({
              ...baseOption(c), legend: { show: false }, grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
              xAxis: axis(c), yAxis: { ...baseOption(c).yAxis as object, scale: true },
              tooltip: { ...baseOption(c).tooltip as object, valueFormatter: (v: unknown) => (typeof v === "number" ? money(v, cur) : "") },
              series: [line("ATR", s.atr, c.s2, 1.5)],
            })} />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <SourceLink name={data.source.name} url={data.source.url} when="prices may be delayed" />
            <p className="text-xs text-muted max-w-2xl">{data.note} Not investment advice.</p>
          </div>
        </>
      )}
    </div>
  );
}
