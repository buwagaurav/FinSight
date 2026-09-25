"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Header from "@/components/stock/Header";
import ScorePanel from "@/components/stock/ScorePanel";
import Overview from "@/components/stock/Overview";
import Fundamentals from "@/components/stock/Fundamentals";
import Valuation from "@/components/stock/Valuation";
import News from "@/components/stock/News";
import AskPanel from "@/components/stock/AskPanel";
import Filings from "@/components/stock/Filings";
import ResearchReport from "@/components/stock/ResearchReport";
import { ErrorBox, Skeleton } from "@/components/ui";
import { api, Company } from "@/lib/api";

const TABS = ["Overview", "Fundamentals", "Valuation", "Filings & news", "AI report"] as const;
type Tab = (typeof TABS)[number];
const slug = (t: string) => t.toLowerCase().replace(/[^a-z]+/g, "-").replace(/-+$/, "");

export default function StockPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const sym = decodeURIComponent(symbol);
  const [data, setData] = useState<Company | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Overview");

  useEffect(() => {
    setData(null);
    setError(null);
    const fromHash = TABS.find((t) => slug(t) === window.location.hash.slice(1));
    setTab(fromHash ?? "Overview");
    api<Company>(`/api/company/${encodeURIComponent(sym)}`)
      .then((d) => { setData(d); document.title = `${d.profile.name} · FinSight`; })
      .catch((e: Error) => setError(e.message));
  }, [sym]);

  if (error) return <ErrorBox message={`Couldn't load ${sym}: ${error}. Try searching by company name.`} />;
  if (!data) {
    return (
      <div className="space-y-4" aria-busy>
        <Skeleton className="h-40" />
        <Skeleton className="h-72" />
        <p className="text-sm text-muted text-center">Loading five years of financials for {sym.split(".")[0]}…</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Header c={data} />
      <ScorePanel c={data} />
      <AskPanel symbol={data.profile.symbol} name={data.profile.name} />
      <div role="tablist" className="sticky top-14 z-20 bg-bg/90 backdrop-blur -mx-4 px-4 sm:mx-0 sm:px-0 flex gap-1 border-b border-line overflow-x-auto">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => { setTab(t); history.replaceState(null, "", `#${slug(t)}`); }}
            className={`px-3 py-2.5 text-sm whitespace-nowrap border-b-2 -mb-px ${tab === t ? "border-accent text-ink font-medium" : "border-transparent text-muted hover:text-ink"}`}>
            {t}
          </button>
        ))}
      </div>
      {tab === "Overview" && <Overview c={data} />}
      {tab === "Fundamentals" && <Fundamentals c={data} />}
      {tab === "Valuation" && <Valuation c={data} />}
      {tab === "AI report" && <ResearchReport symbol={data.profile.symbol} name={data.profile.name} />}
      {tab === "Filings & news" && <div className="grid lg:grid-cols-5 gap-4"><div className="lg:col-span-3"><Filings symbol={sym} /></div><div className="lg:col-span-2"><News symbol={sym} /></div></div>}
    </div>
  );
}
