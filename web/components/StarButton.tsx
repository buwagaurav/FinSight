"use client";

import { usePathname } from "next/navigation";
import { signInWithGoogle } from "@/app/actions";
import { useUser } from "./UserContext";
import { useWatchlist } from "./WatchlistContext";

function Star({ filled }: { filled: boolean }) {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" className={`transition-transform duration-200 ${filled ? "motion-safe:scale-110" : "motion-safe:group-hover:scale-110"}`}>
      <path d="M12 2.8l2.83 5.74 6.33.92-4.58 4.46 1.08 6.3L12 17.25l-5.66 2.97 1.08-6.3-4.58-4.46 6.33-.92z"
        fill={filled ? "#f5b50a" : "none"} stroke={filled ? "#f5b50a" : "currentColor"} strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

/** ☆ Watch / ★ Watching. Signed-out visitors are sent through Google sign-in and brought back to this page. */
export default function StarButton({ symbol, compact = false }: { symbol: string; compact?: boolean }) {
  const { user, authEnabled } = useUser();
  const { watching, toggle, ready } = useWatchlist();
  const path = usePathname();
  const on = watching(symbol);
  const cls = compact
    ? "group grid h-8 w-8 place-items-center rounded-lg text-muted hover:text-ink hover:bg-surface-2"
    : `group inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${on ? "border-[#f5b50a]/50 bg-[#f5b50a]/10 text-ink" : "border-line text-ink-2 hover:border-ink-2 hover:text-ink"}`;

  if (!user && authEnabled) {
    return (
      <form action={signInWithGoogle}>
        <input type="hidden" name="next" value={path} />
        <button className={cls} title="Continue with Google to save stocks to your watchlist" aria-label={compact ? `Watch ${symbol}` : undefined}>
          <Star filled={false} />{!compact && "Watch"}
        </button>
      </form>
    );
  }
  return (
    <button type="button" onClick={() => toggle(symbol)} disabled={!ready} aria-pressed={on}
      className={`${cls} disabled:opacity-50`} title={on ? "Remove from your watchlist" : "Add to your watchlist"}
      aria-label={compact ? (on ? `Stop watching ${symbol}` : `Watch ${symbol}`) : undefined}>
      <Star filled={on} />{!compact && (on ? "Watching" : "Watch")}
    </button>
  );
}
