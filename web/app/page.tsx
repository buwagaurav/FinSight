import Link from "next/link";
import { redirect } from "next/navigation";
import GoogleButton from "@/components/GoogleButton";
import { authEnabled, currentUser } from "@/auth";

const FEATURES = [
  { title: "The whole NSE market", body: "Screen about 2,550 listed companies by ROE, debt, growth, valuation and sector, or describe the screen in plain English." },
  { title: "Explained scores", body: "Every score lists the exact figures that moved it, so you can see why a company rates the way it does." },
  { title: "Filings and annual reports", body: "Official NSE filings and annual reports, searchable, with quotes that open the exact PDF page." },
  { title: "IPOs and GMP", body: "Live NSE subscription with grey-market premium history, always marked unofficial and unverified." },
];

export default async function Landing() {
  if (await currentUser()) redirect("/home");

  return (
    <div className="space-y-14 sm:space-y-20 py-4 sm:py-10">
      <section className="grid lg:grid-cols-[1.1fr_1fr] gap-10 lg:gap-14 items-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">For Indian investors</p>
          <h1 className="mt-3 text-4xl sm:text-5xl font-semibold tracking-tight leading-[1.08] text-balance">
            Research any NSE stock in one place.
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
            <Link href="/home" className="text-sm font-medium text-ink-2 hover:text-ink underline-offset-4 hover:underline">
              Explore without an account →
            </Link>
          </div>
          <p className="mt-4 text-sm text-muted">
            {authEnabled
              ? "Free. Research is open to everyone; signing in unlocks the AI assistant, filing summaries and reports."
              : "Free and open. Sign-in isn't configured on this server yet."}
          </p>
        </div>

        <figure className="rounded-2xl border border-line bg-surface p-5 sm:p-6 shadow-sm" aria-label="Example company analysis">
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
          <dl className="mt-5 grid grid-cols-3 gap-3 border-t border-line pt-4 text-sm">
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

      <section aria-labelledby="features-h">
        <h2 id="features-h" className="sr-only">What FinSight does</h2>
        <div className="grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f) => (
            <div key={f.title} className="border-t border-line pt-4">
              <h3 className="font-semibold">{f.title}</h3>
              <p className="mt-2 text-sm text-ink-2 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {authEnabled && (
        <section className="rounded-2xl border border-line bg-surface px-6 py-8 sm:px-10 flex flex-wrap items-center justify-between gap-6">
          <div>
            <h2 className="text-xl font-semibold">Start researching in one click</h2>
            <p className="mt-1 text-sm text-ink-2">Use your Google account. No new password, no forms.</p>
          </div>
          <GoogleButton next="/home" />
        </section>
      )}
    </div>
  );
}
