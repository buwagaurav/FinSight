"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import SearchBox from "@/components/SearchBox";
import WatchlistPanel from "@/components/WatchlistPanel";
import { Badge, Card, InfoTip, Skeleton } from "@/components/ui";
import { api, Ipo } from "@/lib/api";
import { date, rupees } from "@/lib/format";

const POPULAR = [
  { symbol: "RELIANCE.NS", name: "Reliance" },
  { symbol: "TCS.NS", name: "TCS" },
  { symbol: "HDFCBANK.NS", name: "HDFC Bank" },
  { symbol: "INFY.NS", name: "Infosys" },
  { symbol: "ITC.NS", name: "ITC" },
  { symbol: "TITAN.NS", name: "Titan" },
  { symbol: "BAJFINANCE.NS", name: "Bajaj Finance" },
  { symbol: "TATASTEEL.NS", name: "Tata Steel" },
];

const POPULAR_US = [
  { symbol: "AAPL.US", name: "Apple" },
  { symbol: "NVDA.US", name: "NVIDIA" },
  { symbol: "MSFT.US", name: "Microsoft" },
  { symbol: "GOOGL.US", name: "Alphabet" },
  { symbol: "AMZN.US", name: "Amazon" },
];

const SCREENS = [
  { title: "Quality compounders", desc: "ROE above 18%, low debt, profit growing 10%+ a year", preset: "quality" },
  { title: "Reasonably priced growth", desc: "Profit growth above 12% with P/E under 30", preset: "garp" },
  { title: "Dividend payers", desc: "Dividend yield above 2% with manageable debt", preset: "dividend" },
];

export default function Home() {
  const [ipos, setIpos] = useState<Ipo[] | null>(null);
  const [ipoError, setIpoError] = useState(false);

  useEffect(() => {
    api<Ipo[]>("/api/ipos").then(setIpos).catch(() => setIpoError(true));
  }, []);

  // open IPOs, mainboard first (they're the ones most investors apply to)
  const openNow = (ipos ?? []).filter((i) => i.status === "Open")
    .sort((a, b) => (a.segment === b.segment ? 0 : a.segment === "Mainboard" ? -1 : 1));

  return (
    <div className="space-y-8">
      <section className="pt-6 sm:pt-12 pb-2 text-center max-w-2xl mx-auto">
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">Research any stock in one place</h1>
        <p className="text-ink-2 mt-3">
          Fundamentals, valuation, screening and IPOs together, with every score explained in plain language.
        </p>
        <div className="mt-6 text-left"><SearchBox large autoFocus /></div>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {POPULAR.map((p) => (
            <Link key={p.symbol} href={`/stock/${p.symbol}`}
              className="tap text-sm px-3 py-1.5 rounded-full border border-line bg-surface hover:border-accent hover:text-accent">
              {p.name}
            </Link>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          <span className="text-xs font-medium text-muted">US</span>
          {POPULAR_US.map((p) => (
            <Link key={p.symbol} href={`/stock/${p.symbol}`}
              className="tap text-sm px-3 py-1.5 rounded-full border border-line bg-surface hover:border-accent hover:text-accent">
              {p.name}
            </Link>
          ))}
        </div>
      </section>

      <WatchlistPanel />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title={<>IPOs open now {ipos && <span className="ml-1 text-xs font-normal text-muted">{openNow.length}</span>} <InfoTip term="Subscription" /></>}
          action={<Link href="/ipo" className="tap text-sm text-accent hover:underline">All IPOs & GMP →</Link>}>
          {ipoError && <p className="text-sm text-muted">IPO data is unavailable right now.</p>}
          {!ipos && !ipoError && <div className="space-y-2"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>}
          {ipos && openNow.length === 0 && <p className="text-sm text-muted">No IPOs are open today.</p>}
          <ul className="divide-y divide-line">
            {openNow.slice(0, 6).map((i) => (
              <li key={i.symbol} className="py-2.5 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">{i.name}</div>
                  <div className="text-xs text-muted">
                    {i.segment === "SME" ? `SME · ${i.exchange} · ` : ""}{i.price_low && i.price_low !== i.price_high ? `${rupees(i.price_low, 0)}–` : ""}{rupees(i.price_high, 0)} · closes {date(i.close_date)}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-sm font-semibold tabular">{i.subscription_times != null ? `${i.subscription_times.toFixed(2)}x` : "—"}</div>
                  <div className="text-xs text-muted">subscribed</div>
                </div>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Start with a screen" action={<Link href="/screener" className="tap text-sm text-accent hover:underline">Build your own →</Link>}>
          <ul className="space-y-2">
            {SCREENS.map((s) => (
              <li key={s.preset}>
                <Link href={`/screener?preset=${s.preset}`} className="block rounded-lg border border-line p-3 hover:border-accent">
                  <div className="text-sm font-medium">{s.title}</div>
                  <div className="text-xs text-muted mt-0.5">{s.desc}</div>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card>
        <div className="grid sm:grid-cols-3 gap-4 text-sm">
          <div><Badge variant="accent">1</Badge><p className="mt-2 text-ink-2"><b className="text-ink">Search once.</b> Price, five years of results, valuation and news on a single page.</p></div>
          <div><Badge variant="accent">2</Badge><p className="mt-2 text-ink-2"><b className="text-ink">See why.</b> Every score lists the exact numbers that moved it up or down.</p></div>
          <div><Badge variant="accent">3</Badge><p className="mt-2 text-ink-2"><b className="text-ink">Ranges, not tips.</b> Bear, base and bull scenarios with their assumptions shown, never one &quot;target price&quot;.</p></div>
        </div>
      </Card>
    </div>
  );
}
