"use client";

import { useState } from "react";
import Chart, { baseOption } from "@/components/Chart";
import { Card } from "@/components/ui";
import { Frequency, lakhCrore, LIMITS, PERIODS, sip, sipByYear } from "@/lib/sip";

type Limit = { min: number; max: number; step: number };

/** A number box and a slider for the same value, kept in step. The box accepts free typing; out-of-range values
 * show a message and snap back into range when the box loses focus. */
function Field({ id, label, unit, prefix, limit, value, onChange, format = (v: number) => String(v) }: {
  id: string; label: string; unit?: string; prefix?: string; limit: Limit; value: number;
  onChange: (v: number) => void; format?: (v: number) => string;
}) {
  const [text, setText] = useState(format(value));
  const parsed = Number(text.replace(/,/g, ""));
  const invalid = text.trim() === "" || !Number.isFinite(parsed) || parsed < limit.min || parsed > limit.max;
  const clamp = (v: number) => Math.min(limit.max, Math.max(limit.min, v));
  const unitFor = (v: number) => (unit === "years" && v === 1 ? "year" : unit);   // "1 year", "50 years"

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-ink">{label}</label>
        <div className={`flex items-center rounded-lg border bg-surface px-2.5 focus-within:ring-2 focus-within:ring-accent/20 ${invalid ? "border-bad" : "border-line focus-within:border-accent"}`}>
          {prefix && <span className="text-sm text-muted">{prefix}</span>}
          <input id={id} inputMode="decimal" value={text} aria-invalid={invalid} aria-describedby={invalid ? `${id}-error` : undefined}
            onChange={(e) => {
              setText(e.target.value);
              const v = Number(e.target.value.replace(/,/g, ""));
              if (Number.isFinite(v) && v >= limit.min && v <= limit.max) onChange(v);
            }}
            onBlur={() => { const v = clamp(Number.isFinite(parsed) ? parsed : value); onChange(v); setText(format(v)); }}
            className="w-24 sm:w-28 bg-transparent py-1.5 text-right text-sm font-semibold tabular outline-none" />
          {unit && <span className="text-sm text-muted ml-1">{unitFor(value)}</span>}
        </div>
      </div>
      <input type="range" aria-label={label} min={limit.min} max={limit.max} step={limit.step} value={value}
        onChange={(e) => { const v = Number(e.target.value); onChange(v); setText(format(v)); }}
        className="mt-2 w-full accent-[var(--accent)] cursor-pointer" />
      <div className="flex justify-between text-xs text-muted">
        <span>{prefix}{format(limit.min)}{unit && ` ${unitFor(limit.min)}`}</span>
        <span>{prefix}{format(limit.max)}{unit && ` ${unitFor(limit.max)}`}</span>
      </div>
      {invalid && (
        <p id={`${id}-error`} className="mt-1 text-xs text-bad">
          Enter a number from {prefix}{format(limit.min)} to {prefix}{format(limit.max)}{unit && ` ${unit}`}.
        </p>
      )}
    </div>
  );
}

const grouped = (v: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(v);

export default function SipPage() {
  const [amount, setAmount] = useState(LIMITS.amount.initial);
  const [frequency, setFrequency] = useState<Frequency>("monthly");
  const [rate, setRate] = useState(LIMITS.rate.initial);
  const [years, setYears] = useState(LIMITS.years.initial);
  const result = sip(amount, frequency, rate, years);
  const growth = sipByYear(amount, frequency, rate, years);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">SIP calculator</h1>
        <p className="text-sm text-ink-2 mt-1 max-w-3xl">
          See what a fixed monthly or quarterly investment could grow to at an assumed yearly return. Same method as
          SEBI&apos;s investor calculator. Results update as you type.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Card title="Your SIP">
          <div className="space-y-6">
            <Field id="sip-amount" label="SIP amount" prefix="₹" limit={LIMITS.amount} value={amount} onChange={setAmount} format={grouped} />

            <fieldset>
              <legend className="text-sm font-medium text-ink">Investment frequency</legend>
              <div role="radiogroup" className="mt-2 inline-flex gap-1 bg-surface-2 rounded-lg p-0.5">
                {(["monthly", "quarterly"] as const).map((f) => (
                  <label key={f} className={`cursor-pointer text-sm px-4 py-1.5 rounded-md capitalize has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent ${frequency === f ? "bg-surface shadow-sm font-medium" : "text-muted hover:text-ink"}`}>
                    <input type="radio" name="frequency" value={f} checked={frequency === f} onChange={() => setFrequency(f)} className="sr-only" />
                    {f}
                  </label>
                ))}
              </div>
            </fieldset>

            <Field id="sip-rate" label="Expected rate of return (p.a.)" unit="%" limit={LIMITS.rate} value={rate} onChange={setRate} />
            <Field id="sip-years" label="Investment duration" unit="years" limit={LIMITS.years} value={years} onChange={setYears} />
          </div>
        </Card>

        <Card title="Result">
          {result ? (
            <div className="space-y-4" aria-live="polite">
              <dl className="grid grid-cols-2 gap-4">
                <div>
                  <dt className="text-xs text-muted">Your investment</dt>
                  <dd className="text-xl font-semibold tabular mt-0.5">{lakhCrore(result.invested)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Future value of your investment</dt>
                  <dd className="text-xl font-semibold tabular mt-0.5 text-good">{lakhCrore(result.futureValue)}</dd>
                </div>
                <div className="col-span-2 text-sm text-ink-2">
                  Estimated gains <span className="font-semibold text-ink tabular">{lakhCrore(result.gains)}</span>
                  {" "}on {grouped(PERIODS[frequency] * years)} {frequency === "monthly" ? "monthly" : "quarterly"} instalments of ₹{grouped(amount)}
                </div>
              </dl>
              <Chart height={130} label={`Your investment ${lakhCrore(result.invested)}, future value ${lakhCrore(result.futureValue)}`}
                build={(c) => ({
                  ...baseOption(c),
                  grid: { left: 8, right: 24, top: 4, bottom: 4, containLabel: true },
                  tooltip: { ...(baseOption(c).tooltip as object), trigger: "item", valueFormatter: (v) => lakhCrore(Number(v)) },
                  xAxis: { type: "value", show: false },
                  yAxis: { type: "category", inverse: true, data: ["Your investment", "Future value"], axisTick: { show: false },
                           axisLine: { show: false }, axisLabel: { color: c.ink2, fontSize: 12 } },
                  series: [{ type: "bar", barWidth: 22, data: [
                    { value: result.invested, itemStyle: { color: c.s2, borderRadius: 4 } },
                    { value: result.futureValue, itemStyle: { color: c.good, borderRadius: 4 } },
                  ] }],
                })} />
            </div>
          ) : (
            <p className="text-sm text-bad">Enter a valid SIP amount, return and duration to see the result.</p>
          )}
        </Card>
      </div>

      {result && growth.length > 1 && (
        <Card title="How it grows">
          <Chart height={260} label="Amount invested and estimated value at the end of each year"
            build={(c) => ({
              ...baseOption(c),
              tooltip: { ...(baseOption(c).tooltip as object), valueFormatter: (v) => lakhCrore(Number(v)) },
              legend: { ...(baseOption(c).legend as object), data: ["Invested", "Estimated value"] },
              xAxis: { ...(baseOption(c).xAxis as object), data: growth.map((g) => `Yr ${g.year}`), boundaryGap: false },
              yAxis: { ...(baseOption(c).yAxis as object), axisLabel: { color: c.muted, fontSize: 11, formatter: (v: number) => lakhCrore(v) } },
              series: [
                { name: "Invested", type: "line", showSymbol: false, data: growth.map((g) => g.invested), lineStyle: { color: c.s2 }, itemStyle: { color: c.s2 } },
                { name: "Estimated value", type: "line", showSymbol: false, data: growth.map((g) => g.futureValue), lineStyle: { color: c.good }, itemStyle: { color: c.good }, areaStyle: { color: c.good, opacity: 0.08 } },
              ],
            })} />
        </Card>
      )}

      <div className="rounded-xl border border-warn/40 bg-warn-soft p-4 text-sm text-ink-2">
        <p className="font-semibold text-warn">Disclaimer</p>
        <p className="mt-1">
          Please note that these calculators are for illustrations only and do not represent actual returns. Stock
          Market does not have a fixed rate of return and it is not possible to predict the rate of return.
        </p>
        <p className="mt-2 text-xs text-muted">
          Assumes each instalment is invested at the end of its period and the yearly return is split evenly across
          periods (12% a year = 1% a month), as in{" "}
          <a href="https://investor.sebi.gov.in/calculators/sip_calculator.html" target="_blank" rel="noreferrer" className="underline hover:text-ink">
            SEBI&apos;s SIP calculator
          </a>. Taxes, fund expenses and exit loads are not included.
        </p>
      </div>
    </div>
  );
}
