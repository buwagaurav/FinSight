"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { EChartsOption } from "echarts";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export type ChartColors = {
  ink: string; ink2: string; muted: string; line: string; surface: string;
  s1: string; s2: string; s3: string; good: string; bad: string;
};

function readColors(): ChartColors {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    ink: v("--ink"), ink2: v("--ink-2"), muted: v("--muted"), line: v("--line"), surface: v("--surface"),
    s1: v("--series-1"), s2: v("--series-2"), s3: v("--series-3"), good: v("--good"), bad: v("--bad"),
  };
}

/** Palette follows the page theme, re-read when the OS switches between light and dark. */
function useChartColors(): ChartColors | null {
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(readColors());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setColors(readColors());
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return colors;
}

/** Shared axis/tooltip styling so every chart reads as one system: hairline grid, muted axes. */
export function baseOption(c: ChartColors): EChartsOption {
  return {
    animation: false,
    textStyle: { fontFamily: "inherit", color: c.ink2 },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, itemGap: 16, textStyle: { color: c.ink2, fontSize: 12 } },
    tooltip: {
      trigger: "axis",
      backgroundColor: c.surface,
      borderColor: c.line,
      textStyle: { color: c.ink, fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: c.muted, width: 1 } },
    },
    xAxis: {
      type: "category",
      axisLine: { lineStyle: { color: c.line } },
      axisTick: { show: false },
      axisLabel: { color: c.muted, fontSize: 11 },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: c.line, type: "solid" } },
      axisLabel: { color: c.muted, fontSize: 11 },
    },
  };
}

export default function Chart({ build, height = 260, label }: { build: (c: ChartColors) => EChartsOption; height?: number; label: string }) {
  const colors = useChartColors();
  return (
    <div role="img" aria-label={label} style={{ height }}>
      {colors && <ReactECharts option={build(colors)} style={{ height }} notMerge opts={{ renderer: "svg" }} />}
    </div>
  );
}
