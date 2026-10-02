"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Badge, Card, ErrorBox, Skeleton, SourceLink } from "@/components/ui";
import { api, FundDetail } from "@/lib/api";
import { date, nav, pct } from "@/lib/format";

export default function FundPage() {
  const { code } = useParams<{ code: string }>();
  const [data, setData] = useState<FundDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api<FundDetail>(`/api/funds/${encodeURIComponent(code)}`).then(setData).catch((e: Error) => setError(e.message));
  }, [code]);

  if (error) {
    return (
      <div className="space-y-4">
        <Link href="/funds" className="tap text-sm text-accent hover:underline">← All mutual funds</Link>
        <ErrorBox message={error} />
      </div>
    );
  }
  if (!data) {
    return <div className="space-y-4" aria-busy><Skeleton className="h-40" /><Skeleton className="h-56" /></div>;
  }

  const s = data.scheme;
  const gap = data.direct_vs_regular;
  return (
    <div className="space-y-4">
      <Link href="/funds" className="tap text-sm text-accent hover:underline">← All mutual funds</Link>

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-semibold tracking-tight">{s.fund}</h1>
            <p className="text-sm text-ink-2 mt-1">{s.house} · {s.group}{s.category !== s.group ? ` · ${s.category}` : ""}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge variant={s.plan === "Direct" ? "accent" : "neutral"}>{s.plan} plan</Badge>
              <Badge>{s.option_detail ?? s.option}</Badge>
              {s.type && <Badge>{s.type}</Badge>}
              {!s.active && <Badge variant="warn">No NAV since {date(s.nav_date)}: may have matured or closed</Badge>}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-muted">NAV per unit</div>
            <div className="text-3xl font-semibold tabular">{nav(s.nav)}</div>
            <div className="text-xs text-muted">as of {date(s.nav_date)}</div>
          </div>
        </div>

        <dl className="mt-5 pt-4 border-t border-line grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
          <div><dt className="text-xs text-muted">AMFI scheme code</dt><dd className="font-medium tabular">{s.code}</dd></div>
          <div className="min-w-0"><dt className="text-xs text-muted">ISIN</dt><dd className="font-medium tabular break-all">{s.isins.join(", ") || "—"}</dd></div>
          <div className="col-span-2 sm:col-span-1 flex sm:justify-end items-end">
            <Link href="/sip" className="tap inline-flex items-center rounded-lg bg-accent text-white text-sm font-medium px-4 py-2 hover:opacity-90">
              Plan a SIP →
            </Link>
          </div>
        </dl>
      </Card>

      {gap && (
        <Card title="Direct vs Regular">
          <p className="text-sm text-ink-2">
            The Direct plan&apos;s NAV is <span className="font-semibold text-ink tabular">{pct(gap.direct_ahead_pct, 1)}</span> higher
            than the Regular plan&apos;s today. Both plans hold the same portfolio; the Regular plan pays a distributor
            commission through a higher expense ratio, and that cost has built up since the Direct plan began.
          </p>
        </Card>
      )}

      <Card title={`All plans and options (${data.variants.length})`}>
        <ul className="divide-y divide-line">
          {data.variants.map((v) => (
            <li key={v.code}>
              <Link href={`/funds/${v.code}`} aria-current={v.code === s.code ? "page" : undefined}
                className={`flex items-center justify-between gap-3 py-2.5 px-2 -mx-2 rounded-lg ${v.code === s.code ? "bg-accent-soft/50" : "hover:bg-surface-2/60"}`}>
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <Badge variant={v.plan === "Direct" ? "accent" : "neutral"}>{v.plan}</Badge>
                    <span className="text-sm text-ink">{v.option_detail ?? v.option}</span>
                  </span>
                  <span className="block text-xs text-muted mt-0.5">Code {v.code}{!v.active ? ` · no NAV since ${date(v.nav_date)}` : ""}</span>
                </span>
                <span className="text-right shrink-0">
                  <span className="block text-sm font-semibold tabular">{nav(v.nav)}</span>
                  <span className="block text-xs text-muted">{date(v.nav_date)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <SourceLink name="AMFI daily NAV" url={data.source.url} when="official, published each evening" />
        <span className="text-xs text-muted">Mutual fund investments are subject to market risks. Not investment advice.</span>
      </div>
    </div>
  );
}
