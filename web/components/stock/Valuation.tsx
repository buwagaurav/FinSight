"use client";

import Chart, { baseOption } from "@/components/Chart";
import { Card, InfoTip, Stat } from "@/components/ui";
import { Company } from "@/lib/api";
import { num, pct, rupees } from "@/lib/format";

const CASES = [
  { id: "bear", title: "Bear case", tone: "text-bad", icon: "▼" },
  { id: "base", title: "Base case", tone: "text-ink", icon: "■" },
  { id: "bull", title: "Bull case", tone: "text-good", icon: "▲" },
] as const;

export default function Valuation({ c }: { c: Company }) {
  const p = c.profile;
  const v = c.valuation;
  const sc = v.scenarios;
  const peData = [...v.pe_history.map((h) => ({ label: h.year, pe: h.pe })), ...(p.pe ? [{ label: "Today", pe: p.pe }] : [])];

  let lo = 0, hi = 1;
  if (sc) {
    const vals = [sc.current_price, ...CASES.map((k) => sc.cases[k.id].implied_price)];
    lo = Math.min(...vals) * 0.9;
    hi = Math.max(...vals) * 1.05;
  }
  const at = (x: number) => `${((x - lo) / (hi - lo)) * 100}%`;

  return (
    <div className="space-y-4">
      <Card title="Valuation ratios">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          <Stat label="P/E (trailing)" term="P/E" value={num(p.pe)} />
          <Stat label="P/E (forward)" term="P/E" value={num(p.forward_pe)} />
          <Stat label="P/B" term="P/B" value={num(p.pb)} />
          <Stat label="EV/EBITDA" term="EV/EBITDA" value={num(p.ev_ebitda)} />
          <Stat label="PEG" term="PEG" value={num(p.peg, 2)} />
          <Stat label="Price / Sales" value={num(p.ps, 2)} />
        </div>
      </Card>

      <div className="grid lg:grid-cols-5 gap-4">
        <Card className="lg:col-span-2" title={<>P/E at each year end<InfoTip term="P/E" /></>}>
          {peData.length > 1 ? (
            <Chart height={240} label="Price to earnings ratio at each fiscal year end and today" build={(k) => {
              const base = baseOption(k);
              return {
                ...base, legend: { show: false },
                tooltip: { ...base.tooltip, valueFormatter: (x) => `${Number(x).toFixed(1)}x` },
                xAxis: { ...base.xAxis, data: peData.map((d) => d.label) } as never,
                series: [{
                  type: "bar", name: "P/E", barMaxWidth: 30,
                  data: peData.map((d) => ({ value: d.pe, itemStyle: { color: d.label === "Today" ? k.s2 : k.s1, borderRadius: [4, 4, 0, 0] } })),
                  label: { show: true, position: "top", color: k.ink2, fontSize: 11, formatter: (x: { value?: unknown }) => Number(x.value).toFixed(1) },
                }],
              };
            }} />
          ) : <p className="text-sm text-muted">Not enough history to compare valuation over time.</p>}
          <p className="text-xs text-muted mt-2">Year-end price ÷ that year&apos;s EPS. Orange bar is today.</p>
        </Card>

        <Card className="lg:col-span-3" title={sc ? `Where the price could be in ${sc.horizon_years} years: scenarios, not predictions` : "Scenarios"}>
          {!sc ? (
            <p className="text-sm text-muted">Scenarios need positive earnings and at least two years of valuation history.</p>
          ) : (
            <>
              <div className="relative h-14 mt-2 mb-4" aria-hidden>
                <div className="absolute top-6 left-0 right-0 h-1 rounded-full bg-surface-2" />
                <div className="absolute top-6 h-1 bg-accent/30 rounded-full"
                  style={{ left: at(sc.cases.bear.implied_price), width: `calc(${at(sc.cases.bull.implied_price)} - ${at(sc.cases.bear.implied_price)})` }} />
                {CASES.map((k) => (
                  <div key={k.id} className="absolute top-4 -translate-x-1/2 text-center" style={{ left: at(sc.cases[k.id].implied_price) }}>
                    <div className={`w-3 h-3 mx-auto mt-0.5 rounded-full ring-2 ring-surface ${k.id === "bear" ? "bg-bad" : k.id === "bull" ? "bg-good" : "bg-ink-2"}`} />
                    <div className="text-[11px] text-muted mt-1 whitespace-nowrap">{k.title.split(" ")[0]}</div>
                  </div>
                ))}
                <div className="absolute top-0 -translate-x-1/2 text-center" style={{ left: at(sc.current_price) }}>
                  <div className="text-[11px] font-medium text-accent whitespace-nowrap">Today {rupees(sc.current_price, 0)}</div>
                  <div className="w-0.5 h-6 bg-accent mx-auto" />
                </div>
              </div>
              <div className="grid sm:grid-cols-3 gap-3">
                {CASES.map((k) => {
                  const s = sc.cases[k.id];
                  return (
                    <div key={k.id} className="rounded-xl border border-line p-3">
                      <div className={`text-xs font-semibold ${k.tone}`}>{k.icon} {k.title}</div>
                      <div className="text-xl font-semibold tabular mt-1">{rupees(s.implied_price, 0)}</div>
                      <div className={`text-sm tabular ${s.implied_return_pct >= 0 ? "text-good" : "text-bad"}`}>
                        {pct(s.implied_return_pct, 0, true)} total{s.implied_annual_return_pct != null && ` · ${pct(s.implied_annual_return_pct, 1, true)}/yr`}
                      </div>
                      <dl className="text-xs text-muted mt-2 space-y-0.5">
                        <div className="flex justify-between"><dt>EPS growth</dt><dd className="tabular text-ink-2">{pct(s.growth_pct)}/yr</dd></div>
                        <div className="flex justify-between"><dt>EPS in {sc.horizon_years}y</dt><dd className="tabular text-ink-2">{rupees(s.eps_in_3y)}</dd></div>
                        <div className="flex justify-between"><dt>Exit P/E</dt><dd className="tabular text-ink-2">{num(s.exit_pe)}x</dd></div>
                      </dl>
                    </div>
                  );
                })}
              </div>
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer text-accent">Assumptions behind these numbers</summary>
                <ul className="list-disc pl-5 mt-2 space-y-1 text-ink-2">{sc.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
              </details>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
