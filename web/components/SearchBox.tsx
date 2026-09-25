"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, SearchResult } from "@/lib/api";

export default function SearchBox({ large = false, autoFocus = false }: { large?: boolean; autoFocus?: boolean }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const query = q.trim();
    if (query.length < 2) {
      setResults([]);
      return;
    }
    setLoading(true);
    const t = setTimeout(() => {
      api<SearchResult[]>(`/api/search?q=${encodeURIComponent(query)}`)
        .then((r) => { setResults(r); setActive(0); })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (!boxRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function go(symbol: string) {
    setOpen(false);
    setQ("");
    router.push(`/stock/${encodeURIComponent(symbol)}`);
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    if (e.key === "Escape") setOpen(false);
    if (e.key === "Enter") {
      if (results[active]) go(results[active].symbol);
      else if (q.trim()) go(q.trim().toUpperCase());
    }
  }

  return (
    <div ref={boxRef} className="relative w-full">
      <input
        value={q}
        autoFocus={autoFocus}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKey}
        placeholder={large ? "Search any stock: Reliance, TCS, HDFC Bank…" : "Search stocks"}
        aria-label="Search stocks"
        role="combobox"
        aria-expanded={open && results.length > 0}
        className={`w-full bg-surface border border-line rounded-xl outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 placeholder:text-muted ${large ? "text-lg px-5 py-4 shadow-sm" : "text-sm px-3 py-2"}`}
      />
      {open && q.trim().length >= 2 && (
        <ul role="listbox" className="absolute z-40 mt-2 w-full bg-surface border border-line rounded-xl shadow-lg overflow-hidden">
          {loading && results.length === 0 && <li className="px-4 py-3 text-sm text-muted">Searching…</li>}
          {!loading && results.length === 0 && <li className="px-4 py-3 text-sm text-muted">No NSE/BSE listed company found</li>}
          {results.map((r, i) => (
            <li key={r.symbol} role="option" aria-selected={i === active}
              onMouseEnter={() => setActive(i)} onMouseDown={() => go(r.symbol)}
              className={`px-4 py-2.5 cursor-pointer flex items-center justify-between gap-3 ${i === active ? "bg-surface-2" : ""}`}>
              <span className="min-w-0">
                <span className="block text-sm font-medium truncate">{r.name}</span>
                <span className="block text-xs text-muted">{r.symbol.split(".")[0]} · {r.exchange}{r.sector ? ` · ${r.sector}` : ""}</span>
              </span>
              <span className="text-xs text-muted shrink-0">↵</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
