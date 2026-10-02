"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import SearchBox from "./SearchBox";
import { useUser } from "./UserContext";
import { signOutAction } from "@/app/actions";
import GoogleButton from "./GoogleButton";
import Logo from "./Logo";

const LINKS = [
  { href: "/home", label: "Home" },
  { href: "/screener", label: "Screener" },
  { href: "/ipo", label: "IPOs & GMP" },
];

export default function Nav() {
  const path = usePathname();
  const { user, authEnabled } = useUser();
  const landing = path === "/";
  // Phones and small tablets: the page links and stock search move into panels opened from the header
  const [panel, setPanel] = useState<"menu" | "search" | null>(null);
  useEffect(() => { setPanel(null); }, [path]);
  useEffect(() => {
    if (!panel) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setPanel(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel]);
  const iconBtn = "md:hidden w-11 h-11 grid place-items-center rounded-lg text-ink-2 hover:text-ink hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
  return (
    <header className="sticky top-0 z-30 bg-bg/90 backdrop-blur border-b border-line pt-[env(safe-area-inset-top)]">
      <div className="max-w-[1440px] mx-auto px-4 sm:px-6 h-16 flex items-center gap-2 sm:gap-4">
        <Link href="/" className="shrink-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent" aria-label="FinSight home">
          <Logo />
        </Link>
        {!landing && (
          <nav aria-label="Main" className="hidden md:flex items-center gap-1 text-sm min-w-0">
            {LINKS.map((l) => {
              const active = path.startsWith(l.href);
              return (
                <Link key={l.href} href={l.href}
                  aria-current={active ? "page" : undefined}
                  className={`px-2.5 py-1.5 rounded-lg whitespace-nowrap ${active ? "bg-surface-2 text-ink font-medium" : "text-ink-2 hover:text-ink"}`}>
                  {l.label}
                </Link>
              );
            })}
          </nav>
        )}
        {!landing && <div className="ml-auto w-full max-w-xs hidden md:block"><SearchBox /></div>}
        {!landing && (
          <div className="md:hidden ml-auto flex items-center">
            <button type="button" className={iconBtn} aria-label="Search stocks" aria-expanded={panel === "search"}
              aria-controls="mobile-panel" onClick={() => setPanel(panel === "search" ? null : "search")}>
              <svg aria-hidden width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
            </button>
            <button type="button" className={iconBtn} aria-label={panel === "menu" ? "Close menu" : "Open menu"}
              aria-expanded={panel === "menu"} aria-controls="mobile-panel" onClick={() => setPanel(panel === "menu" ? null : "menu")}>
              <svg aria-hidden width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                {panel === "menu" ? <path d="M6 6l12 12M18 6 6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
              </svg>
            </button>
          </div>
        )}
        {authEnabled && (
          <div className={`${landing ? "ml-auto" : ""} flex items-center gap-2 shrink-0`}>
            {user ? (
              <>
                {user.image
                  ? <img src={user.image} alt="" width={28} height={28} className="rounded-full" referrerPolicy="no-referrer" />
                  : <span className="w-7 h-7 rounded-full bg-accent-soft text-accent grid place-items-center text-xs font-semibold">{(user.name ?? user.email ?? "?")[0]}</span>}
                <span className="text-sm text-ink-2 hidden lg:inline max-w-[140px] truncate">{user.name ?? user.email}</span>
                <form action={signOutAction}>
                  <button className="text-xs px-2.5 py-1.5 rounded-lg border border-line text-ink-2 hover:text-ink hover:border-ink-2">Sign out</button>
                </form>
              </>
            ) : (
              <GoogleButton next={landing ? "/home" : path} size="sm" compact={!landing} />
            )}
          </div>
        )}
      </div>
      {!landing && panel && (
        <div id="mobile-panel" className="md:hidden border-t border-line bg-bg px-4 pb-4 pt-3 max-h-[calc(100dvh-4rem-env(safe-area-inset-top))] overflow-y-auto">
          {panel === "search" ? (
            <SearchBox autoFocus inline />
          ) : (
            <nav aria-label="Main">
              <ul className="space-y-1">
                {LINKS.map((l) => (
                  <li key={l.href}>
                    <Link href={l.href} aria-current={path.startsWith(l.href) ? "page" : undefined}
                      className={`flex items-center min-h-11 px-3 rounded-lg text-base ${path.startsWith(l.href) ? "bg-surface-2 text-ink font-medium" : "text-ink-2 hover:bg-surface-2"}`}>
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          )}
        </div>
      )}
    </header>
  );
}
