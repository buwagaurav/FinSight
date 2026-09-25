"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import SearchBox from "./SearchBox";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/screener", label: "Screener" },
  { href: "/ipo", label: "IPOs & GMP" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-30 bg-bg/90 backdrop-blur border-b border-line">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center gap-4">
        <Link href="/" className="font-semibold tracking-tight text-lg shrink-0">
          Fin<span className="text-accent">Sight</span>
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link key={l.href} href={l.href}
                className={`px-2.5 py-1.5 rounded-lg whitespace-nowrap ${active ? "bg-surface-2 text-ink font-medium" : "text-ink-2 hover:text-ink"} ${l.href === "/" ? "hidden sm:block" : ""}`}>
                {l.label}
              </Link>
            );
          })}
        </nav>
        {path !== "/" && <div className="ml-auto w-full max-w-xs hidden md:block"><SearchBox /></div>}
      </div>
    </header>
  );
}
