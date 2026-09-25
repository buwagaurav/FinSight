import { Company } from "@/lib/api";
import { crore, num, pct, rupees } from "@/lib/format";
import { Stat } from "@/components/ui";

function RangeBar({ low, high, price }: { low: number; high: number; price: number }) {
  const pos = Math.min(100, Math.max(0, ((price - low) / (high - low || 1)) * 100));
  return (
    <div className="w-full">
      <div className="relative h-1.5 rounded-full bg-surface-2">
        <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-accent ring-2 ring-surface" style={{ left: `${pos}%` }} />
      </div>
      <div className="flex justify-between text-xs text-muted mt-1.5 tabular">
        <span>{rupees(low, 0)}</span><span>52-week range</span><span>{rupees(high, 0)}</span>
      </div>
    </div>
  );
}

export default function Header({ c }: { c: Company }) {
  const p = c.profile;
  const up = (p.change_pct ?? 0) >= 0;
  return (
    <section className="bg-surface border border-line rounded-xl p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-semibold tracking-tight">{p.name}</h1>
          <div className="text-sm text-muted mt-1">
            {p.symbol.split(".")[0]} · {p.exchange}{p.sector && ` · ${p.sector}`}{p.industry && ` · ${p.industry}`}
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl sm:text-3xl font-semibold">{rupees(p.price)}</div>
          {p.change_pct != null && (
            <div className={`text-sm font-medium ${up ? "text-good" : "text-bad"}`}>
              {up ? "▲" : "▼"} {pct(Math.abs(p.change_pct), 2)} today
            </div>
          )}
        </div>
      </div>
      {p.week52_low != null && p.week52_high != null && p.price != null && (
        <div className="mt-4 max-w-md"><RangeBar low={p.week52_low} high={p.week52_high} price={p.price} /></div>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mt-5 pt-4 border-t border-line">
        <Stat label="Market cap" term="Market cap" value={crore(p.market_cap_cr)} />
        <Stat label="P/E" term="P/E" value={num(p.pe)} />
        <Stat label="P/B" term="P/B" value={num(p.pb)} />
        <Stat label="ROE (TTM)" term="ROE" value={pct(p.roe_ttm_pct)} />
        <Stat label="Debt / Equity" term="Debt / Equity" value={p.sector === "Financial Services" ? "n/a" : num(p.debt_to_equity_ttm, 2)} />
        <Stat label="Dividend yield" term="Dividend yield" value={pct(p.dividend_yield_pct, 2)} />
      </div>
    </section>
  );
}
