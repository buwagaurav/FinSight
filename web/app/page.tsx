import Link from "next/link";
import { redirect } from "next/navigation";
import GoogleButton from "@/components/GoogleButton";
import { authEnabled, currentUser } from "@/auth";

// Real FinSight data, captured 25–27 Sep 2026, used as examples on this page.
const TCS_WEEKLY = [2840, 2786, 2908, 2855, 2973, 2907, 2936, 2975, 3006, 3022, 3092, 3089, 3190, 3090, 3176, 3077, 3064, 3085,
  2935, 2699, 2628, 2598, 2510, 2365, 2346, 2315, 2511, 2529, 2474, 2428, 2356, 2204, 2284, 2272, 2229, 2124, 2191, 2083, 2057,
  2038, 2201, 2243, 2432, 2373, 2375, 2298, 2248, 2320, 2204, 2190, 2087, 2082];
const SCREEN_ROWS = [
  { name: "Infosys", roe: "33.2%", de: "0.10", pe: "12.9" },
  { name: "HCLTech", roe: "23.0%", de: "0.07", pe: "19.6" },
  { name: "LTM", roe: "21.5%", de: "0.10", pe: "23.1" },
];
const ORIENT_GMP = [105, 113, 105, 100, 70, 72, 87, 97, 80, 85, 86, 90];

const STEPS = [
  { title: "Search a company", body: "Type a name. Price, five years of results, valuation and filings open on one page." },
  { title: "Understand the numbers", body: "Scores list the exact figures behind them, and every ratio has a plain-English explanation." },
  { title: "Ask and verify", body: "Ask in your own words. Answers cite their sources, and quotes link to the exact PDF page." },
];

const FEATURES = [
  { title: "The whole NSE market", body: "Screen about 2,550 listed companies by ROE, debt, growth, valuation and sector, or describe the screen in plain English." },
  { title: "Explained scores", body: "Every score lists the exact figures that moved it, so you can see why a company rates the way it does." },
  { title: "Filings and annual reports", body: "Official NSE filings and annual reports, searchable, with quotes that open the exact PDF page." },
  { title: "IPOs and GMP", body: "Live NSE subscription with grey-market premium history, always marked unofficial and unverified." },
];

/** Line (and optional area) path for a small chart, scaled into width × height with a little padding. */
function sparkPaths(values: number[], width: number, height: number, pad = 4) {
  const min = Math.min(...values), max = Math.max(...values);
  const x = (i: number) => pad + (i / (values.length - 1)) * (width - 2 * pad);
  const y = (v: number) => pad + (1 - (v - min) / (max - min || 1)) * (height - 2 * pad);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(values.length - 1).toFixed(1)},${height} L${x(0).toFixed(1)},${height} Z`;
  return { line, area, end: { x: x(values.length - 1), y: y(values[values.length - 1]) } };
}

function Sparkline({ values, width, height, label, tone = "accent" }: { values: number[]; width: number; height: number; label: string; tone?: "accent" | "bad" | "good" }) {
  const { line, area, end } = sparkPaths(values, width, height);
  const color = `var(--${tone === "accent" ? "accent" : tone})`;
  const gid = `spark-${tone}-${values.length}`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto overflow-visible" role="img" aria-label={label}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={end.x} cy={end.y} r="3.5" fill={color} stroke="var(--surface)" strokeWidth="2" />
    </svg>
  );
}

export default async function Landing() {
  if (await currentUser()) redirect("/home");

  return (
    <div className="space-y-16 sm:space-y-24 py-4 sm:py-10">
      {/* ---------- hero ---------- */}
      <section className="relative grid lg:grid-cols-[1.1fr_1fr] gap-10 lg:gap-14 items-center">
        {/* backdrop: soft accent glow over a faint dot grid */}
        <div aria-hidden="true" className="pointer-events-none absolute -inset-x-6 -inset-y-10 -z-10 overflow-hidden [mask-image:radial-gradient(ellipse_at_center,black_45%,transparent_78%)]">
          <div className="absolute inset-0 opacity-[0.55] [background-image:radial-gradient(var(--line)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:radial-gradient(ellipse_at_center,black_35%,transparent_75%)]" />
          <div className="absolute right-[-10%] top-[5%] h-[420px] w-[420px] rounded-full bg-accent/15 blur-3xl" />
          <div className="absolute left-[10%] bottom-[-15%] h-[260px] w-[260px] rounded-full bg-good/10 blur-3xl" />
        </div>

        <div>
          <p className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/70 px-3 py-1 text-xs font-semibold uppercase tracking-[0.12em] text-accent backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-good" aria-hidden="true" /> For Indian investors
          </p>
          <h1 className="mt-4 text-4xl sm:text-5xl lg:text-[3.4rem] font-semibold tracking-tight leading-[1.05] text-balance">
            Research any NSE stock{" "}
            <span className="bg-gradient-to-r from-accent to-[var(--series-3)] bg-clip-text text-transparent">in one place.</span>
          </h1>
          <p className="mt-5 text-lg text-ink-2 max-w-[34rem]">
            Fundamentals, valuation, official filings, IPO GMP and an AI assistant that checks every number it gives you
            against the source.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-4">
            {authEnabled ? (
              <GoogleButton next="/home" />
            ) : (
              <Link href="/home" className="inline-flex h-12 items-center rounded-full bg-accent px-6 font-medium text-white hover:opacity-90">
                Explore FinSight
              </Link>
            )}
          </div>
          <p className="mt-4 text-sm text-muted">
            {authEnabled ? "Free. One click with your Google account." : "Free and open. Sign-in isn't configured on this server yet."}
          </p>
          {authEnabled && (
            <p className="mt-1 text-xs text-muted">
              By continuing, you agree to our{" "}
              <Link href="/terms" className="underline underline-offset-2 hover:text-ink">Terms of Use</Link> and{" "}
              <Link href="/privacy" className="underline underline-offset-2 hover:text-ink">Privacy Policy</Link>.
            </p>
          )}
          <dl className="mt-8 flex flex-wrap gap-x-8 gap-y-3 text-sm">
            <div><dt className="text-muted text-xs">NSE companies</dt><dd className="font-semibold tabular-nums">2,552</dd></div>
            <div><dt className="text-muted text-xs">Annual reports searchable</dt><dd className="font-semibold tabular-nums">48 of the top 50</dd></div>
            <div><dt className="text-muted text-xs">Refreshed</dt><dd className="font-semibold">Twice a day</dd></div>
          </dl>
        </div>

        <figure className="relative rounded-2xl border border-line bg-surface p-5 sm:p-6 shadow-[0_20px_50px_-24px_rgba(16,24,40,0.35)] transition-transform duration-300 motion-safe:hover:-translate-y-1" aria-label="Example company analysis">
          <figcaption className="flex items-center justify-between text-xs text-muted">
            <span>Example · Tata Consultancy Services</span>
            <span>Sep 2026</span>
          </figcaption>
          <div className="mt-4 flex items-start justify-between gap-4">
            <p className="text-[15px] leading-snug text-ink">
              Strong fundamentals, moderate growth, fair valuation, low balance-sheet risk; price in a downtrend.
            </p>
            <div className="text-center shrink-0">
              <div className="text-3xl font-semibold tabular-nums">72</div>
              <div className="mt-1 rounded-full bg-good-soft px-2 py-0.5 text-[11px] font-semibold text-good">▲ Strong</div>
            </div>
          </div>
          <div className="mt-4">
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted">Share price · 1 year</span>
              <span className="tabular-nums"><span className="text-muted">₹2,840 → </span><span className="font-semibold text-ink">₹2,082</span> <span className="text-bad">▼ 26.7%</span></span>
            </div>
            <div className="mt-2"><Sparkline values={TCS_WEEKLY} width={320} height={64} label="TCS weekly share price over one year, from ₹2,840 to ₹2,082" tone="bad" /></div>
          </div>
          <dl className="mt-4 grid grid-cols-3 gap-3 border-t border-line pt-4 text-sm">
            <div><dt className="text-xs text-muted">ROE</dt><dd className="font-semibold tabular-nums">48.7%</dd></div>
            <div><dt className="text-xs text-muted">P/E vs 4-yr median</dt><dd className="font-semibold tabular-nums">15.1 / 25.3</dd></div>
            <div><dt className="text-xs text-muted">Net profit FY26</dt><dd className="font-semibold tabular-nums">₹49,210 Cr</dd></div>
          </dl>
          <div className="mt-5 rounded-xl bg-surface-2 p-4 text-sm">
            <p className="text-xs font-medium text-muted">Ask FinSight: “What does TCS say about attrition?”</p>
            <p className="mt-2 text-ink-2">
              The annual report states{" "}
              <span className="text-ink">“voluntary IT services’ attrition at 13.7%”</span>
              <span className="ml-1 rounded bg-accent-soft px-1 text-[10px] font-medium text-accent align-super">p.56</span>
            </p>
            <p className="mt-3 inline-flex rounded-full bg-good-soft px-2 py-0.5 text-[11px] font-semibold text-good">
              ✓ Quote found on the cited page
            </p>
          </div>
        </figure>
      </section>

      {/* ---------- how it works ---------- */}
      <section aria-labelledby="how-h">
        <h2 id="how-h" className="text-2xl font-semibold tracking-tight">How it works</h2>
        <ol className="mt-6 grid gap-6 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="relative">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-accent-soft text-sm font-semibold text-accent">{i + 1}</span>
              <h3 className="mt-3 font-semibold">{s.title}</h3>
              <p className="mt-1.5 text-sm text-ink-2 leading-relaxed">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* ---------- product previews ---------- */}
      <section aria-labelledby="action-h">
        <h2 id="action-h" className="text-2xl font-semibold tracking-tight">See it in action</h2>
        <p className="mt-2 text-sm text-muted">Real results from FinSight, 26–27 Sep 2026.</p>
        <div className="mt-6 grid gap-5 lg:grid-cols-2">
          <article className="rounded-2xl border border-line bg-surface p-5 sm:p-6 transition-[transform,box-shadow] duration-300 motion-safe:hover:-translate-y-1 hover:shadow-[0_16px_40px_-24px_rgba(16,24,40,0.35)]">
            <p className="text-xs font-semibold uppercase tracking-[0.1em] text-muted">Screen in plain English</p>
            <p className="mt-3 rounded-xl border border-line bg-surface-2 px-4 py-3 text-sm text-ink">“Debt-free IT companies with ROE above 20%”</p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              {["Sector: Technology", "Debt / Equity < 0.1", "ROE > 20%"].map((c) => (
                <span key={c} className="rounded-full bg-accent-soft px-2.5 py-1 font-medium text-accent">{c}</span>
              ))}
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm tabular-nums">
                <thead>
                  <tr className="text-xs text-muted"><th className="py-1.5 text-left font-medium">Company</th><th className="py-1.5 text-right font-medium">ROE</th><th className="py-1.5 text-right font-medium">D/E</th><th className="py-1.5 text-right font-medium">P/E</th></tr>
                </thead>
                <tbody>
                  {SCREEN_ROWS.map((r) => (
                    <tr key={r.name} className="border-t border-line">
                      <td className="py-2 font-medium">{r.name}</td><td className="py-2 text-right">{r.roe}</td><td className="py-2 text-right">{r.de}</td><td className="py-2 text-right">{r.pe}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-muted">22 matches across the NSE, largest first.</p>
          </article>

          <article className="rounded-2xl border border-line bg-surface p-5 sm:p-6 transition-[transform,box-shadow] duration-300 motion-safe:hover:-translate-y-1 hover:shadow-[0_16px_40px_-24px_rgba(16,24,40,0.35)]">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-semibold uppercase tracking-[0.1em] text-muted">IPO tracker</p>
              <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn">● GMP unofficial</span>
            </div>
            <h3 className="mt-3 font-semibold">Orient Cables (India)</h3>
            <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
              <div><dt className="text-xs text-muted">Price band</dt><dd className="font-semibold tabular-nums">₹258–272</dd></div>
              <div><dt className="text-xs text-muted">Subscribed</dt><dd className="font-semibold tabular-nums">1.32x</dd></div>
              <div><dt className="text-xs text-muted">Latest GMP</dt><dd className="font-semibold tabular-nums">₹90 <span className="text-good text-xs">+33%</span></dd></div>
            </dl>
            <div className="mt-4">
              <p className="text-xs text-muted">GMP trend · last 12 readings</p>
              <div className="mt-2"><Sparkline values={ORIENT_GMP} width={320} height={70} label="Orient Cables GMP over its last 12 readings, between ₹70 and ₹113, latest ₹90" tone="good" /></div>
            </div>
            <p className="mt-3 text-xs text-muted">Issue details from NSE · GMP from InvestorGain, 27 Sep 2026, 6:02 am.</p>
          </article>
        </div>
      </section>

      {/* ---------- features ---------- */}
      <section aria-labelledby="features-h">
        <h2 id="features-h" className="text-2xl font-semibold tracking-tight">Everything in one workspace</h2>
        <div className="mt-6 grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f) => (
            <div key={f.title} className="border-t border-line pt-4">
              <h3 className="font-semibold">{f.title}</h3>
              <p className="mt-2 text-sm text-ink-2 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
