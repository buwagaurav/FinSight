"use client";

import { useState } from "react";
import type { EChartsOption } from "echarts";
import Chart, { baseOption, ChartColors } from "@/components/Chart";
import { Card, InfoTip, SourceLink, Stat } from "@/components/ui";
import { Company, YearRow } from "@/lib/api";
import { DASH, num, pct } from "@/lib/format";

type Key = keyof YearRow;
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function bars(c: ChartColors, rows: YearRow[], series: { key: Key; name: string; color: string }[]): EChartsOption {
  const base = baseOption(c);
  return {
    ...base,
    tooltip: { ...base.tooltip, valueFormatter: (v) => (v == null ? DASH : `₹${inr.format(Number(v))} Cr`) },
    xAxis: { ...base.xAxis, data: rows.map((r) => r.year) } as EChartsOption["xAxis"],
    yAxis: { ...base.yAxis, axisLabel: { color: c.muted, fontSize: 11, formatter: (v: number) => inr.format(v) } } as EChartsOption["yAxis"],
    series: series.map((s) => ({
      type: "bar", name: s.name, data: rows.map((r) => r[s.key] as number | null),
      itemStyle: { color: s.color, borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26, barGap: "8%",
    })),
  };
}

function lines(c: ChartColors, rows: YearRow[], series: { key: Key; name: string; color: string }[], unit = "%"): EChartsOption {
  const base = baseOption(c);
  return {
    ...base,
    tooltip: { ...base.tooltip, valueFormatter: (v) => (v == null ? DASH : `${Number(v).toFixed(unit === "x" ? 2 : 1)}${unit}`) },
    xAxis: { ...base.xAxis, data: rows.map((r) => r.year), boundaryGap: false } as EChartsOption["xAxis"],
    yAxis: { ...base.yAxis, axisLabel: { color: c.muted, fontSize: 11, formatter: `{value}${unit}` } } as EChartsOption["yAxis"],
    series: series.map((s) => ({
      type: "line", name: s.name, data: rows.map((r) => r[s.key] as number | null),
      lineStyle: { width: 2, color: s.color }, itemStyle: { color: s.color, borderColor: c.surface, borderWidth: 2 },
      symbol: "circle", symbolSize: 8, connectNulls: true,
    })),
  };
}

type TableRow = { label: string; key: Key; kind: "cr" | "pct" | "x" | "rs"; term?: string; group: string };
const TABLE: TableRow[] = [
  { group: "Profit & loss", label: "Revenue", key: "revenue", kind: "cr" },
  { group: "Profit & loss", label: "Revenue growth", key: "revenue_growth_pct", kind: "pct" },
  { group: "Profit & loss", label: "EBITDA", key: "ebitda", kind: "cr" },
  { group: "Profit & loss", label: "Operating profit", key: "operating_profit", kind: "cr" },
  { group: "Profit & loss", label: "Operating margin", key: "operating_margin_pct", kind: "pct", term: "Operating margin" },
  { group: "Profit & loss", label: "Net profit", key: "net_profit", kind: "cr" },
  { group: "Profit & loss", label: "Net profit growth", key: "profit_growth_pct", kind: "pct" },
  { group: "Profit & loss", label: "Net margin", key: "net_margin_pct", kind: "pct", term: "Net margin" },
  { group: "Profit & loss", label: "EPS (₹)", key: "eps", kind: "rs", term: "EPS" },
  { group: "Returns", label: "ROE", key: "roe_pct", kind: "pct", term: "ROE" },
  { group: "Returns", label: "ROCE", key: "roce_pct", kind: "pct", term: "ROCE" },
  { group: "Balance sheet", label: "Shareholders' equity", key: "equity", kind: "cr" },
  { group: "Balance sheet", label: "Total debt", key: "total_debt", kind: "cr" },
  { group: "Balance sheet", label: "Debt / Equity", key: "debt_to_equity", kind: "x", term: "Debt / Equity" },
  { group: "Balance sheet", label: "Cash", key: "cash", kind: "cr" },
  { group: "Balance sheet", label: "Working capital", key: "working_capital", kind: "cr" },
  { group: "Balance sheet", label: "Interest coverage", key: "interest_coverage", kind: "x", term: "Interest coverage" },
  { group: "Cash flow", label: "Operating cash flow", key: "operating_cash_flow", kind: "cr" },
  { group: "Cash flow", label: "Capital expenditure", key: "capex", kind: "cr" },
  { group: "Cash flow", label: "Free cash flow", key: "free_cash_flow", kind: "cr", term: "Free cash flow" },
  { group: "Cash flow", label: "Cash conversion", key: "cash_conversion", kind: "x", term: "Cash conversion" },
  { group: "Cash flow", label: "Dividends paid", key: "dividends_paid", kind: "cr" },
];

function fmt(v: unknown, kind: TableRow["kind"]) {
  if (v == null || typeof v !== "number") return DASH;
  if (kind === "cr") return inr.format(v);
  if (kind === "pct") return pct(v);
  if (kind === "x") return num(v, 2) + "x";
  return num(v, 2);
}

export default function Fundamentals({ c }: { c: Company }) {
  const rows = c.financials.years;
  const g = c.financials.growth;
  const [compact, setCompact] = useState(true);
  const financial = c.profile.sector === "Financial Services";
  const tableRows = compact ? TABLE.filter((r) => r.group === "Profit & loss" || r.group === "Returns") : TABLE;

  if (!rows.length) return <Card><p className="text-sm text-muted">No annual statements are available for this company.</p></Card>;

  return (
    <div className="space-y-4">
      <Card title={`Growth ${g.from ?? ""}–${g.to ?? ""} (${g.years ?? 0} years, compounded)`}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Stat label="Revenue CAGR" term="CAGR" value={pct(g.revenue_cagr_pct)} />
          <Stat label="Net profit CAGR" term="CAGR" value={pct(g.profit_cagr_pct)} />
          <Stat label="EPS CAGR" term="EPS" value={pct(g.eps_cagr_pct)} />
          <Stat label="Latest operating margin" term="Operating margin" value={pct(rows.at(-1)?.operating_margin_pct)} />
        </div>
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card title="Revenue and net profit (₹ Cr)">
          <Chart label="Revenue and net profit by year" build={(k) => bars(k, rows, [
            { key: "revenue", name: "Revenue", color: k.s1 }, { key: "net_profit", name: "Net profit", color: k.s2 }])} />
        </Card>
        <Card title={<>Profit vs cash actually generated (₹ Cr)<InfoTip term="Cash conversion" /></>}>
          <Chart label="Net profit versus operating cash flow by year" build={(k) => bars(k, rows, [
            { key: "net_profit", name: "Net profit", color: k.s2 }, { key: "operating_cash_flow", name: "Operating cash flow", color: k.s3 }])} />
        </Card>
        <Card title={<>Margins<InfoTip term="Operating margin" /></>}>
          <Chart label="Operating and net margin by year" build={(k) => lines(k, rows, [
            { key: "operating_margin_pct", name: "Operating margin", color: k.s1 }, { key: "net_margin_pct", name: "Net margin", color: k.s2 }])} />
        </Card>
        <Card title={<>Return on equity and capital<InfoTip term="ROCE" /></>}>
          <Chart label="ROE and ROCE by year" build={(k) => lines(k, rows, financial
            ? [{ key: "roe_pct", name: "ROE", color: k.s1 }]
            : [{ key: "roe_pct", name: "ROE", color: k.s1 }, { key: "roce_pct", name: "ROCE", color: k.s2 }])} />
        </Card>
        {!financial && (
          <Card title={<>Debt to equity<InfoTip term="Debt / Equity" /></>}>
            <Chart label="Debt to equity ratio by year" build={(k) => ({ ...lines(k, rows, [{ key: "debt_to_equity", name: "Debt / Equity", color: k.s1 }], "x"), legend: { show: false } })} />
          </Card>
        )}
        <Card title={<>Free cash flow (₹ Cr)<InfoTip term="Free cash flow" /></>}>
          <Chart label="Free cash flow by year" build={(k) => ({ ...bars(k, rows, [{ key: "free_cash_flow", name: "Free cash flow", color: k.s3 }]), legend: { show: false } })} />
        </Card>
      </div>

      <Card title={`Financial statements (${c.financials.unit})`}
        action={<button onClick={() => setCompact(!compact)} className="text-sm text-accent hover:underline">{compact ? "Show balance sheet & cash flow" : "Show fewer rows"}</button>}>
        <div className="overflow-x-auto -mx-4 sm:mx-0">
          <table className="w-full text-sm tabular min-w-[520px]">
            <thead>
              <tr className="text-xs text-muted border-b border-line">
                <th className="text-left font-medium py-2 px-4 sm:pl-0 sticky left-0 bg-surface">Metric</th>
                {rows.map((r) => <th key={r.year} className="text-right font-medium py-2 px-3">{r.year}</th>)}
              </tr>
            </thead>
            <tbody>
              {tableRows.map((t, i) => (
                <tr key={t.key} className={`border-b border-line/60 ${tableRows[i - 1]?.group !== t.group ? "border-t-2 border-t-line" : ""}`}>
                  <td className="py-2 px-4 sm:pl-0 text-ink-2 sticky left-0 bg-surface whitespace-nowrap">{t.label}{t.term && <InfoTip term={t.term} />}</td>
                  {rows.map((r) => {
                    const v = r[t.key];
                    const negative = typeof v === "number" && v < 0 && t.kind !== "cr";
                    return <td key={r.year} className={`text-right py-2 px-3 ${negative ? "text-bad" : ""}`}>{fmt(v, t.kind)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3"><SourceLink name={c.financials.source.name} url={c.financials.source.url} /></div>
      </Card>
    </div>
  );
}
