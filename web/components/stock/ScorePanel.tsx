"use client";

import { useState } from "react";
import { Company, ScoreCard } from "@/lib/api";
import { tone } from "@/lib/format";
import { Badge, LabelBadge } from "@/components/ui";

const ORDER = ["fundamentals", "growth", "valuation", "safety"] as const;
const HINTS: Record<(typeof ORDER)[number], string> = {
  fundamentals: "Returns on capital, margins and cash quality",
  growth: "How fast revenue and profit have grown",
  valuation: "Price relative to earnings and its own history (higher = cheaper)",
  safety: "Debt, interest cover and price swings (higher = lower risk)",
};
const BAR = { good: "bg-good", warn: "bg-warn", bad: "bg-bad", neutral: "bg-accent" };

function ScoreTile({ id, card, open, onToggle }: { id: (typeof ORDER)[number]; card: ScoreCard; open: boolean; onToggle: () => void }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open}
      className={`text-left rounded-xl border p-3 transition-colors ${open ? "border-accent bg-accent-soft/40" : "border-line hover:border-ink-2"}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{card.name}</span>
        <LabelBadge label={card.label} />
      </div>
      <div className="flex items-baseline gap-1 mt-2">
        <span className="text-2xl font-semibold tabular">{card.score ?? "—"}</span>
        <span className="text-xs text-muted">/ 100</span>
      </div>
      <div className="h-1 rounded-full bg-surface-2 mt-2 overflow-hidden">
        <div className={`h-full rounded-full ${BAR[tone(card.label)]}`} style={{ width: `${card.score ?? 0}%` }} />
      </div>
      <div className="text-xs text-muted mt-2 leading-snug">{HINTS[id]}</div>
      <div className="text-xs text-accent mt-2">{open ? "Hide reasons" : "Why this score?"}</div>
    </button>
  );
}

function Reasons({ card }: { card: ScoreCard }) {
  return (
    <div className="rounded-xl border border-line p-4 bg-surface-2/50">
      <div className="text-sm font-medium mb-2">Why {card.name} is {card.score ?? "—"}: every score starts at 50</div>
      <ul className="space-y-1.5">
        {card.reasons.map((r, i) => (
          <li key={i} className="flex items-start gap-3 text-sm">
            <span className={`tabular w-10 shrink-0 text-right font-medium ${r.points > 0 ? "text-good" : r.points < 0 ? "text-bad" : "text-muted"}`}>
              {r.points > 0 ? `+${r.points}` : r.points === 0 ? "±0" : r.points}
            </span>
            <span className="text-ink-2">{r.text}</span>
          </li>
        ))}
        {card.reasons.length === 0 && <li className="text-sm text-muted">Not enough data to score this area.</li>}
      </ul>
    </div>
  );
}

export default function ScorePanel({ c }: { c: Company }) {
  const s = c.scores;
  const [open, setOpen] = useState<(typeof ORDER)[number] | null>(null);
  const checks = c.financials.data_checks;

  return (
    <section className="bg-surface border border-line rounded-xl p-4 sm:p-5 space-y-4">
      <div className="flex flex-wrap items-start gap-4 justify-between">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium uppercase tracking-wide text-muted">FinSight view</div>
          <p className="text-lg font-medium mt-1 leading-snug">{s.view}</p>
          <div className="flex flex-wrap gap-2 mt-2 items-center">
            <Badge>Confidence: {s.confidence}</Badge>
            <span className="text-xs text-muted">{s.confidence_basis}</span>
          </div>
        </div>
        <div className="text-center shrink-0">
          <div className="text-4xl font-semibold tabular">{s.overall.score ?? "—"}</div>
          <div className="mt-1"><LabelBadge label={s.overall.label} /></div>
          <div className="text-xs text-muted mt-1">Overall score</div>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        <div className="rounded-xl bg-good-soft/60 p-3">
          <div className="text-xs font-semibold text-good mb-1.5">▲ Main positives</div>
          <ul className="text-sm text-ink-2 space-y-1 list-disc pl-4">
            {s.positives.length ? s.positives.map((t) => <li key={t}>{t}</li>) : <li>None stood out</li>}
          </ul>
        </div>
        <div className="rounded-xl bg-bad-soft/60 p-3">
          <div className="text-xs font-semibold text-bad mb-1.5">▼ Main risks</div>
          <ul className="text-sm text-ink-2 space-y-1 list-disc pl-4">
            {s.risks.length ? s.risks.map((t) => <li key={t}>{t}</li>) : <li>None stood out</li>}
          </ul>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {ORDER.map((id) => (
          <ScoreTile key={id} id={id} card={s.cards[id]} open={open === id} onToggle={() => setOpen(open === id ? null : id)} />
        ))}
      </div>
      {open && <Reasons card={s.cards[open]} />}

      {checks.length > 0 && (
        <div className="rounded-xl border border-warn/40 bg-warn-soft p-3">
          <div className="text-xs font-semibold text-warn mb-1">● Check before relying on these numbers</div>
          <ul className="text-sm text-ink-2 space-y-1 list-disc pl-4">{checks.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      )}
      <p className="text-xs text-muted">{s.method}</p>
    </section>
  );
}
