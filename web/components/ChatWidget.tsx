"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import AskPanel from "@/components/stock/AskPanel";

const GENERAL = [
  "Which IT stocks have ROE above 20% and low debt?",
  "Compare HDFC Bank and ICICI Bank",
  "Which IPOs are open right now?",
  "How risky is a portfolio of 50% TCS, 30% Infosys and 20% HDFC Bank?",
  "What is a P/E ratio and how should I read it?",
];
const BY_PAGE: Record<string, string[]> = {
  "/ipo": [
    "Which IPOs are open right now, and how subscribed are they?",
    "What is the price band, lot size and issue size of the open mainboard IPOs?",
    "What is the latest GMP for the open IPOs, and why is it unofficial?",
  ],
  "/screener": [
    "Find profitable small caps with low debt",
    "Which banks trade below 2x book value?",
    "Stocks with 15%+ profit growth and a P/E under 25",
  ],
};
const COMPANY = [
  "Summarise the last 4 years of results in plain English",
  "What are the biggest risks right now?",
  "Is the valuation high compared to its own history?",
  "Is the stock in an uptrend?",
];

/** Ask FinSight on every page: a button in the corner that opens the assistant. On a stock page it knows the
 * company; elsewhere it takes any stock, market or finance question. The conversation carries across pages. */
export default function ChatWidget() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [used, setUsed] = useState(false);   // mount the panel on first open, then keep it (and its conversation)
  const symbol = path.match(/^\/stock\/([^/]+)/)?.[1];
  const ticker = symbol ? decodeURIComponent(symbol).toUpperCase().replace(/\.(NS|BO)$/, "") : undefined;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      {used && (
        <div role="dialog" aria-label="Ask FinSight AI" hidden={!open}
          className="fixed z-40 left-4 right-4 sm:left-auto sm:w-[440px] bottom-[calc(5rem+env(safe-area-inset-bottom,0px))] max-h-[min(680px,calc(100dvh-7rem))] overflow-y-auto overscroll-contain rounded-xl shadow-2xl">
          <AskPanel symbol={symbol ? decodeURIComponent(symbol) : undefined}
            name={ticker ?? "stocks, IPOs & finance"}
            suggestions={symbol ? COMPANY : BY_PAGE[path] ?? GENERAL}
            persistent />
        </div>
      )}
      <button type="button" onClick={() => { setUsed(true); setOpen((o) => !o); }} aria-expanded={open}
        className="fixed z-40 right-4 bottom-[calc(1rem+env(safe-area-inset-bottom,0px))] flex items-center gap-2 rounded-full bg-accent text-white text-sm font-medium pl-3.5 pr-4 py-2.5 shadow-lg hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2">
        <span aria-hidden>{open ? "✕" : "✦"}</span>
        {open ? "Close" : "Ask FinSight"}
      </button>
    </>
  );
}
