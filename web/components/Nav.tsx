"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import SearchBox from "./SearchBox";
import { useUser } from "./UserContext";
import { signInWithGoogle, signOutAction } from "@/app/actions";

const LINKS = [
  { href: "/home", label: "Home" },
  { href: "/screener", label: "Screener" },
  { href: "/ipo", label: "IPOs & GMP" },
];

export default function Nav() {
  const path = usePathname();
  const { user, authEnabled } = useUser();
  const landing = path === "/";
  return (
    <header className="sticky top-0 z-30 bg-bg/90 backdrop-blur border-b border-line">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center gap-4">
        <Link href="/" className="font-semibold tracking-tight text-lg shrink-0">
          Fin<span className="text-accent">Sight</span>
        </Link>
        {!landing && (
          <nav className="flex items-center gap-1 text-sm">
            {LINKS.map((l) => {
              const active = path.startsWith(l.href);
              return (
                <Link key={l.href} href={l.href}
                  className={`px-2.5 py-1.5 rounded-lg whitespace-nowrap ${active ? "bg-surface-2 text-ink font-medium" : "text-ink-2 hover:text-ink"} ${l.href === "/home" ? "hidden sm:block" : ""}`}>
                  {l.label}
                </Link>
              );
            })}
          </nav>
        )}
        {!landing && <div className="ml-auto w-full max-w-xs hidden md:block"><SearchBox /></div>}
        {authEnabled && (
          <div className={`${landing ? "ml-auto" : "md:ml-0 ml-auto"} flex items-center gap-2 shrink-0`}>
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
              <form action={signInWithGoogle}>
                <input type="hidden" name="next" value={landing ? "/home" : path} />
                <button className="text-sm px-3 py-1.5 rounded-lg bg-accent text-white font-medium hover:opacity-90">Sign in</button>
              </form>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
