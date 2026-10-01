"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import CitedMarkdown, { SourceList } from "@/components/CitedMarkdown";
import { Badge, Card } from "@/components/ui";
import { AiStatus, api, AskIntent, AskResult } from "@/lib/api";
import SignInPrompt from "@/components/SignInPrompt";
import { useUser } from "@/components/UserContext";

type Turn = { id: number; question: string; result?: AskResult; error?: string };

const COMPANY_SUGGESTIONS = [
  "Summarise the last 4 years of results in plain English",
  "Why did profit change differently from cash flow?",
  "What are the biggest risks right now?",
  "Compare it with its closest peers",
  "Is the valuation high compared to its own history?",
];

const TOOL_LABELS: Record<string, string> = {
  search_company: "Searched companies",
  get_company_snapshot: "Read scores and key ratios",
  get_financials: "Read annual statements",
  get_valuation: "Read valuation and scenarios",
  get_news: "Read recent news",
  get_announcements: "Read official filings",
  search_documents: "Searched annual report & filings",
  compare_companies: "Compared companies",
  run_screen: "Ran a screen",
  get_ipo_data: "Read IPO data and GMP",
  get_technicals: "Read price trend",
  portfolio_risk: "Measured portfolio risk",
  calculate: "Calculated",
};

const INTENT_LABELS: Record<AskIntent, string> = {
  company_research: "company research",
  stock_screening: "stock screening",
  company_comparison: "company comparison",
  valuation: "valuation",
  filing_question: "filings question",
  ipo_research: "IPO research",
  technical_analysis: "technical analysis",
  portfolio_risk: "portfolio risk",
  general_finance: "general finance",
  out_of_scope: "outside finance",
};

function retrieved(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

function Answer({ result }: { result: AskResult }) {
  const v = result.verification;
  const tools = result.tool_calls.filter((c) => !c.error);
  if (result.intent === "out_of_scope") {
    return <div className="rounded-lg bg-surface-2 text-sm text-ink-2 p-3">{result.answer}</div>;
  }
  return (
    <div className="space-y-3">
      <CitedMarkdown text={result.answer} sources={result.sources} />

      {v.applicable === false ? (
        <p className="text-xs text-muted">{v.note}</p>
      ) : v.passed ? (
        <Badge variant="good">✓ Every figure, quote and calculation checked against its source</Badge>
      ) : (
        <div className="rounded-lg border border-warn/40 bg-warn-soft p-2.5 text-xs text-ink-2">
          {v.unverified.length > 0 && <div><span className="font-semibold text-warn">● Not found in FinSight data: </span>{v.unverified.join(", ")}</div>}
          {(v.misattributed ?? []).length > 0 && <div><span className="font-semibold text-warn">● Cited to the wrong source: </span>{v.misattributed!.join(", ")}</div>}
          {(v.unsupported_quotes ?? []).length > 0 && <div><span className="font-semibold text-warn">● Quote not found on the cited page: </span>{v.unsupported_quotes!.join("; ")}</div>}
          {(v.arithmetic ?? []).length > 0 && <div><span className="font-semibold text-warn">● Calculation doesn't match its figures: </span>{v.arithmetic!.join("; ")}</div>}
          <div className="mt-1">{v.note}</div>
        </div>
      )}

      {(result.warnings ?? []).length > 0 && (
        <div className="rounded-lg border border-warn/40 bg-warn-soft p-2.5 text-xs text-ink-2">
          <div className="font-semibold text-warn mb-0.5">● Check before relying on this</div>
          <ul className="space-y-0.5 pl-4 list-disc">
            {result.warnings!.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </div>
      )}

      <SourceList sources={result.sources} />

      {(result.data_timestamp || result.disclaimer) && (
        <p className="text-xs text-muted">
          {result.data_timestamp && <>Data retrieved {retrieved(result.data_timestamp)}. </>}
          {result.disclaimer}
        </p>
      )}

      <details className="text-xs text-muted">
        <summary className="cursor-pointer">
          How this was researched ({result.intent ? `${INTENT_LABELS[result.intent]} · ` : ""}{tools.length} steps · {result.model})
        </summary>
        <ul className="mt-1.5 space-y-0.5 pl-4 list-disc">
          {result.tool_calls.map((c, i) => (
            <li key={i} className={c.error ? "text-bad" : ""}>
              {TOOL_LABELS[c.tool] ?? c.tool}
              {c.tool === "calculate" ? `: ${String(c.input.label)}` : c.input.symbol ? `: ${String(c.input.symbol)}` : ""}
              {c.error && " (failed)"}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

/** `symbol` is the company in view; leave it out for questions that aren't about one company. `persistent` keeps
 * the conversation when the company changes (the site-wide chat follows the user between pages). */
export default function AskPanel({ symbol, name, suggestions = COMPANY_SUGGESTIONS, persistent = false }:
  { symbol?: string; name: string; suggestions?: string[]; persistent?: boolean }) {
  const { user } = useUser();
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { api<AiStatus>("/api/ai/status").then(setStatus).catch(() => setStatus(null)); }, []);
  useEffect(() => { if (!persistent) setTurns([]); }, [symbol, persistent]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [turns]);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    const id = Date.now();
    const history = turns.filter((t) => t.result).flatMap((t) => [
      { role: "user", content: t.question },
      { role: "assistant", content: t.result!.answer },
    ]);
    setTurns((ts) => [...ts, { id, question: q }]);
    setInput("");
    setBusy(true);
    try {
      const result = await api<AskResult>("/api/ask", { method: "POST", body: JSON.stringify({ question: q, symbol, history }) }, { auth: true });
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, result } : t)));
    } catch (e) {
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, error: (e as Error).message } : t)));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setTurns([]);
    setInput("");
  }

  const asked = new Set(turns.map((t) => t.question));
  const remaining = suggestions.filter((s) => !asked.has(s));

  function submit(e: FormEvent) {
    e.preventDefault();
    ask(input);
  }

  if (status?.configured && status.sign_in_required && !user) {
    return (
      <Card title={<>Ask FinSight AI <span className="text-xs font-normal text-muted ml-1">about {name}</span></>}>
        <SignInPrompt what={`ask questions about ${name} and get answers checked against the source`} />
      </Card>
    );
  }

  if (status && !status.configured) {
    return (
      <Card title="Ask FinSight AI" action={<Badge variant="warn">● Setup needed</Badge>}>
        <p className="text-sm text-ink-2">
          The research assistant is set to use <code className="text-ink">{status.model}</code>, which needs an API key.
          Add it to <code className="text-ink">backend/.env</code> (see <code className="text-ink">backend/.env.example</code> for DeepSeek, Kimi and other options) and restart the API, e.g.:
        </p>
        <pre className="mt-2 text-xs bg-surface-2 rounded-lg p-3 overflow-x-auto">ANTHROPIC_API_KEY=sk-ant-...</pre>
      </Card>
    );
  }

  return (
    <Card title={<>Ask FinSight AI <span className="text-xs font-normal text-muted ml-1">about {name}</span></>}
      action={turns.length > 0
        ? <button type="button" onClick={reset} disabled={busy}
            className="text-xs px-2.5 py-1 rounded-lg border border-line text-ink-2 hover:border-accent hover:text-accent disabled:opacity-50">
            ↺ New conversation
          </button>
        : <span className="text-xs text-muted hidden sm:block">Answers cite their sources · not investment advice</span>}>
      {turns.length === 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {suggestions.map((s) => (
            <button key={s} onClick={() => ask(s)} disabled={busy || !status}
              className="text-xs px-3 py-1.5 rounded-full border border-line hover:border-accent hover:text-accent text-ink-2 text-left disabled:opacity-50">
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="space-y-5">
        {turns.map((t) => (
          <div key={t.id} className="space-y-2">
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-xl rounded-br-sm bg-accent text-white text-sm px-3 py-2">{t.question}</div>
            </div>
            {t.result && <Answer result={t.result} />}
            {t.error && <div className="rounded-lg bg-bad-soft text-bad text-sm p-3">{t.error}</div>}
            {!t.result && !t.error && (
              <div className="flex items-center gap-2 text-sm text-muted">
                <span className="inline-block w-2 h-2 rounded-full bg-accent animate-pulse" />
                Researching and checking every number… (usually under 10 seconds)
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {turns.length > 0 && !busy && remaining.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <div className="text-xs text-muted mb-2">Ask next</div>
          <div className="flex flex-wrap gap-2">
            {remaining.map((s) => (
              <button key={s} onClick={() => ask(s)}
                className="text-xs px-3 py-1.5 rounded-full border border-line hover:border-accent hover:text-accent text-ink-2 text-left">
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={submit} className="flex gap-2 mt-4">
        <input value={input} onChange={(e) => setInput(e.target.value)} disabled={busy}
          placeholder={turns.length ? "Ask a follow-up…" : `Ask anything about ${name}…`}
          className="flex-1 min-w-0 bg-surface border border-line rounded-lg px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60" />
        <button disabled={busy || input.trim().length < 3}
          className="bg-accent text-white text-sm font-medium rounded-lg px-4 py-2 disabled:opacity-50">
          {busy ? "…" : "Ask"}
        </button>
      </form>
    </Card>
  );
}
