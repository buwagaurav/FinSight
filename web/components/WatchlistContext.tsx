"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useUser } from "./UserContext";

type Ctx = {
  ready: boolean;
  watching: (symbol: string) => boolean;
  toggle: (symbol: string) => Promise<void>;
  error: string | null;
  version: number;   // bumps on every change, so the watchlist panel can reload
};
const WatchCtx = createContext<Ctx>({ ready: false, watching: () => false, toggle: async () => {}, error: null, version: 0 });
const base = (s: string) => s.split(".")[0].toUpperCase();

export function WatchlistProvider({ children }: { children: ReactNode }) {
  const { user, authEnabled } = useUser();
  // without sign-in configured (local development) the API treats everyone as one local user
  const active = !!user || !authEnabled;
  const [symbols, setSymbols] = useState<Set<string>>(new Set());
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!active) { setSymbols(new Set()); setReady(false); return; }
    // The free API server can take a minute to wake up, so retry instead of leaving every star disabled
    let cancelled = false, timer: ReturnType<typeof setTimeout>;
    const load = (attempt: number) =>
      api<string[]>("/api/watchlist/symbols", undefined, { auth: true })
        .then((s) => { if (!cancelled) { setSymbols(new Set(s)); setReady(true); } })
        .catch(() => { if (!cancelled && attempt < 4) timer = setTimeout(() => load(attempt + 1), 5000 * (attempt + 1)); });
    load(0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [active]);

  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setError(null), 6000);
    return () => clearTimeout(t);
  }, [error]);

  const toggle = useCallback(async (symbol: string) => {
    const s = base(symbol);
    const on = symbols.has(s);
    setError(null);
    setSymbols((cur) => { const n = new Set(cur); if (on) n.delete(s); else n.add(s); return n; });  // optimistic
    try {
      if (on) await api(`/api/watchlist/${encodeURIComponent(s)}`, { method: "DELETE" }, { auth: true });
      else await api("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol: s }) }, { auth: true });
      setVersion((v) => v + 1);
    } catch (e) {
      setSymbols((cur) => { const n = new Set(cur); if (on) n.add(s); else n.delete(s); return n; });  // undo
      setError((e as Error).message);
    }
  }, [symbols]);

  return (
    <WatchCtx.Provider value={{ ready, watching: (s) => symbols.has(base(s)), toggle, error, version }}>
      {children}
      {error && (
        <div role="alert" className="fixed inset-x-4 bottom-[calc(1rem+env(safe-area-inset-bottom,0px))] z-50 mx-auto flex max-w-md items-start gap-3 rounded-xl border border-bad/40 bg-surface p-3 text-sm shadow-lg">
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss" className="text-muted hover:text-ink">✕</button>
        </div>
      )}
    </WatchCtx.Provider>
  );
}

export const useWatchlist = () => useContext(WatchCtx);
