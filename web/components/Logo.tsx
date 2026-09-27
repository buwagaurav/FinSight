/** FinSight mark: a lens (Sight) over a rising trend line (Fin), on the brand's blue-to-green tile. */
export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <defs>
        <linearGradient id="finsight-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2a78d6" />
          <stop offset="1" stopColor="#1baf7a" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#finsight-mark)" />
      <circle cx="14" cy="14" r="7.6" fill="none" stroke="#fff" strokeWidth="2.6" />
      <path d="M19.6 19.6 25 25" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M10.2 16.6 12.9 13.8 15 15.6 18 11.4" fill="none" stroke="#fff" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Logo() {
  return (
    <span className="inline-flex items-center gap-2 sm:gap-2.5">
      <LogoMark />
      <span className="text-xl sm:text-[1.375rem] font-bold tracking-tight leading-none">
        Fin<span className="text-accent">Sight</span>
      </span>
    </span>
  );
}
