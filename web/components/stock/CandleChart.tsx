"use client";

import { useEffect, useState } from "react";
import Chart, { baseOption } from "@/components/Chart";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { useCurrency } from "@/components/CurrencyContext";

type Bar = [label: string, open: number, high: number, low: number, close: number, volume: number, ts: number];
type Candles = {
  range: string;
  interval: string;
  bars: Bar[];
  market: { id: "IN" | "US"; open: boolean; live: boolean; last_bar: string; delay_minutes: number | null };
  refresh_seconds: number | null;
  source: { name: string; url: string };
};

export const CANDLE_RANGES = [
  { id: "1d", label: "1D" }, { id: "5d", label: "5D" }, { id: "1mo", label: "1M" },
  { id: "6mo", label: "6M" }, { id: "1y", label: "1Y" }, { id: "5y", label: "5Y" },
] as const;
export type CandleRange = (typeof CANDLE_RANGES)[number]["id"];

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

/** Candlesticks with volume. While the market is open on the intraday ranges it re-asks the API every minute or
 *  so (the API caches each stock briefly, so many viewers share one Yahoo request), and pauses in hidden tabs. */
export default function CandleChart({ symbol, range, onChange }: { symbol: string; range: CandleRange; onChange?: (pct: number | null) => void }) {
  const cur = useCurrency();
  const [data, setData] = useState<Candles | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setData(null);
    setError(null);
    const load = () =>
      api<Candles>(`/api/company/${encodeURIComponent(symbol)}/candles?range=${range}`)
        .then((d) => {
          if (cancelled) return;
          setData(d);
          if (d.refresh_seconds) timer = setTimeout(tick, d.refresh_seconds * 1000);
        })
        .catch((e: Error) => { if (!cancelled) setError(e.message); });
    const tick = () => {
      if (document.hidden) {   // come back to it when the tab is visible again
        document.addEventListener("visibilitychange", function wake() {
          if (!document.hidden) { document.removeEventListener("visibilitychange", wake); load(); }
        });
        return;
      }
      load();
    };
    load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [symbol, range]);

  const bars = data?.bars ?? [];
  useEffect(() => {
    onChange?.(bars.length > 1 ? (bars.at(-1)![4] / bars[0][1] - 1) * 100 : null);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <p className="text-sm text-muted h-[300px] grid place-items-center">Candles are unavailable right now.</p>;
  if (!data) return <div className="h-[340px] animate-pulse rounded-lg bg-surface-2" />;

  const m = data.market;
  const intraday = data.interval.endsWith("m");
  const tz = m.id === "US" ? "America/New_York" : "Asia/Kolkata";
  // daily and weekly candles are stamped at midnight, so show their date rather than a time
  const updated = intraday
    ? `${new Date(m.last_bar).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: tz })} ${m.id === "US" ? "ET" : "IST"}`
    : bars.at(-1)![0];

  return (
    <div>
      <div className="flex items-center gap-2 text-xs text-muted mb-1 min-h-5">
        {m.live ? (
          <span className="inline-flex items-center gap-1.5 text-good font-medium">
            <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-good opacity-60" /><span className="relative inline-flex h-2 w-2 rounded-full bg-good" /></span>
            Live
          </span>
        ) : (
          <span>{m.open ? "Market open" : "Market closed"}</span>
        )}
        <span>· {data.interval === "1wk" ? "weekly" : data.interval === "1d" ? "daily" : data.interval} candles · last {updated}{m.live ? ` · refreshes every ${data.refresh_seconds! >= 120 ? `${data.refresh_seconds! / 60} min` : "minute"}` : ""}</span>
      </div>
      <Chart height={340} label={`Candlestick chart, ${data.interval} candles`} build={(k) => {
        const base = baseOption(k);
        const up = k.good, down = k.bad;
        return {
          ...base,
          legend: { show: false },
          grid: [
            { left: 8, right: 16, top: 12, height: "68%", containLabel: true },
            { left: 8, right: 16, top: "80%", bottom: 8, containLabel: true },
          ],
          tooltip: {
            ...base.tooltip, trigger: "axis", axisPointer: { type: "cross", lineStyle: { color: k.muted } },
            formatter: (params: unknown) => {
              const p = (params as { dataIndex: number }[])[0];
              const b = bars[p.dataIndex];
              if (!b) return "";
              const row = (l: string, v: string) => `<div style="display:flex;justify-content:space-between;gap:16px"><span>${l}</span><b>${v}</b></div>`;
              return `<div style="font-size:12px"><div style="margin-bottom:4px">${b[0]}</div>${row("Open", money(b[1], cur))}${row("High", money(b[2], cur))}${row("Low", money(b[3], cur))}${row("Close", money(b[4], cur))}${row("Volume", compact.format(b[5]))}</div>`;
            },
          },
          axisPointer: { link: [{ xAxisIndex: "all" }] },
          xAxis: [
            { type: "category", data: bars.map((b) => b[0]), boundaryGap: true, axisLine: { lineStyle: { color: k.line } }, axisTick: { show: false }, axisLabel: { color: k.muted, fontSize: 11, hideOverlap: true, showMinLabel: false }, splitLine: { show: false } },
            { type: "category", gridIndex: 1, data: bars.map((b) => b[0]), axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: k.line } } },
          ],
          yAxis: [
            { ...base.yAxis, scale: true, position: "right" } as never,
            { type: "value", gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
          ],
          dataZoom: [{ type: "inside", xAxisIndex: [0, 1], start: 0, end: 100 }],
          series: [
            {
              type: "candlestick", name: "Price", data: bars.map((b) => [b[1], b[4], b[3], b[2]]),
              itemStyle: { color: up, color0: down, borderColor: up, borderColor0: down },
            },
            {
              type: "bar", name: "Volume", xAxisIndex: 1, yAxisIndex: 1,
              data: bars.map((b) => ({ value: b[5], itemStyle: { color: (b[4] >= b[1] ? up : down) + "88" } })),
            },
          ],
        };
      }} />
      <p className="text-xs text-muted mt-1">Scroll or pinch to zoom, drag to pan. Near-live: candles update about once a minute, not on every trade.</p>
    </div>
  );
}
