"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import CitedMarkdown, { SourceList } from "@/components/CitedMarkdown";
import { Badge, Card } from "@/components/ui";
import { AiStatus, api, AskIntent, AskResult, ConversationState } from "@/lib/api";
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

      <div className="flex items-start justify-between gap-3">
      <details className="text-xs text-muted min-w-0">
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
      <CopyButton text={result.answer} />
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button type="button" aria-label="Copy answer"
      onClick={() => navigator.clipboard?.writeText(text.replace(/\s*\[S\d+(?:\s*,\s*S\d+)*\]/g, "")).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }).catch(() => {})}
      className="shrink-0 text-xs px-2 py-0.5 rounded-md border border-line text-muted hover:text-ink hover:border-ink-2">
      {copied ? "✓ Copied" : "Copy"}
    </button>
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
  const [context, setContext] = useState<ConversationState | null>(null);   // what follow-ups refer back to
  const [elapsed, setElapsed] = useState(0);
  const [answered, setAnswered] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const turnRefs = useRef(new Map<number, HTMLDivElement>());
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { api<AiStatus>("/api/ai/status").then(setStatus).catch(() => setStatus(null)); }, []);
  useEffect(() => { if (!persistent) { setTurns([]); setContext(null); } }, [symbol, persistent]);
  // While waiting, keep the "researching" row in view; when an answer arrives, show it from its first line
  // (the question above it at the top) instead of jumping to the end of a long answer.
  useEffect(() => { if (busy) endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [busy]);
  useEffect(() => {
    if (answered !== null) turnRefs.current.get(answered)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [answered]);
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => {   // the input grows with the question, up to five lines
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [input]);

  async function ask(question: string, retryOf?: number) {
    const q = question.trim();
    if (q.length < 3 || busy) return;
    const id = Date.now();
    const done = turns.filter((t) => t.result && t.id !== retryOf);
    const history = done.flatMap((t) => [
      { role: "user", content: t.question },
      { role: "assistant", content: t.result!.answer },
    ]);
    setTurns((ts) => [...ts.filter((t) => t.id !== retryOf), { id, question: q }]);
    setInput("");
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const result = await api<AskResult>("/api/ask", {
        method: "POST", signal: controller.signal,
        body: JSON.stringify({ question: q, symbol, history, state: context }),
      }, { auth: true });
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, result } : t)));
      if (result.state !== undefined) setContext(result.state ?? null);
      setAnswered(id);
    } catch (e) {
      const stopped = (e as Error).name === "AbortError";
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, error: stopped ? "Stopped." : (e as Error).message } : t)));
    } finally {
      abortRef.current = null;
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  function reset() {
    abortRef.current?.abort();
    setTurns([]);
    setContext(null);
    setInput("");
  }

  const last = [...turns].reverse().find((t) => t.result);
  const asked = new Set(turns.map((t) => t.question));
  const next = (last?.result?.follow_ups?.length ? last.result.follow_ups : suggestions).filter((s) => !asked.has(s));
  const topic = context && (context.companies.length || context.metric)
    ? [context.companies.map((c) => c.symbol.replace(/\.(NS|BO)$/, "")).join(" vs "), context.metric, context.period]
        .filter(Boolean).join(" · ")
    : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    ask(input);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {   // Shift+Enter: new line
      e.preventDefault();
      ask(input);
    }
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

  const chip = "text-xs px-3 py-1.5 rounded-full border border-line hover:border-accent hover:text-accent hover:bg-accent-soft text-ink-2 text-left transition-colors disabled:opacity-50";

  return (
    <Card title={<>Ask FinSight AI <span className="text-xs font-normal text-muted ml-1">about {name}</span></>}
      action={turns.length > 0
        ? <button type="button" onClick={reset}
            className="text-xs px-2.5 py-1 rounded-lg border border-line text-ink-2 hover:border-accent hover:text-accent">
            ↺ New conversation
          </button>
        : <span className="text-xs text-muted hidden sm:block">Answers cite their sources · not investment advice</span>}>
      {turns.length === 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {suggestions.map((s) => (
            <button key={s} onClick={() => ask(s)} disabled={busy || !status} className={chip}>{s}</button>
          ))}
        </div>
      )}

      <div className="space-y-5" aria-live="polite">
        {turns.map((t) => (
          <div key={t.id} className={`space-y-2 ${persistent ? "scroll-mt-3" : "scroll-mt-28"}`}   /* page: clear the sticky header */
            ref={(el) => { if (el) turnRefs.current.set(t.id, el); else turnRefs.current.delete(t.id); }}>
            <div className="flex justify-end fade-up">
              <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-accent text-white text-sm px-3.5 py-2 whitespace-pre-wrap">{t.question}</div>
            </div>
            {t.result && <div className="fade-up"><Answer result={t.result} /></div>}
            {t.error && (
              <div className="fade-up flex items-center justify-between gap-3 rounded-lg bg-bad-soft text-bad text-sm p-3">
                <span>{t.error}</span>
                <button type="button" onClick={() => ask(t.question, t.id)} disabled={busy}
                  className="shrink-0 text-xs font-medium px-2.5 py-1 rounded-lg border border-bad/40 hover:bg-bad hover:text-white disabled:opacity-50">
                  ↻ Try again
                </button>
              </div>
            )}
            {!t.result && !t.error && (
              <div className="fade-up flex items-center gap-3 rounded-xl bg-surface-2 px-3 py-2.5 text-sm text-muted">
                <span className="flex gap-1" aria-hidden>
                  <span className="typing-dot w-1.5 h-1.5 rounded-full bg-accent" />
                  <span className="typing-dot w-1.5 h-1.5 rounded-full bg-accent" />
                  <span className="typing-dot w-1.5 h-1.5 rounded-full bg-accent" />
                </span>
                <span className="flex-1">
                  Researching and checking every figure…
                  <span className="tabular ml-1.5 text-xs">{elapsed}s</span>
                </span>
                <button type="button" onClick={() => abortRef.current?.abort()}
                  className="text-xs px-2.5 py-1 rounded-lg border border-line text-ink-2 hover:border-bad hover:text-bad">
                  ■ Stop
                </button>
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {turns.length > 0 && !busy && next.length > 0 && (
        <div className="mt-4 border-t border-line pt-3 fade-up">
          <div className="text-xs text-muted mb-2">Ask next</div>
          <div className="flex flex-wrap gap-2">
            {next.slice(0, 4).map((s) => <button key={s} onClick={() => ask(s)} className={chip}>{s}</button>)}
          </div>
        </div>
      )}

      {topic && (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted">
          <span>Talking about:</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft text-accent px-2.5 py-0.5 font-medium">
            {topic}
            <button type="button" onClick={() => setContext(null)} disabled={busy} aria-label="Forget this topic"
              title="Forget this topic: the next question starts fresh" className="hover:text-ink disabled:opacity-50">✕</button>
          </span>
        </div>
      )}

      <form onSubmit={submit}   /* in the floating chat the input stays visible while an answer is read from the top */
        className={`flex items-end gap-2 mt-3 ${persistent ? "sticky bottom-0 -mx-4 sm:-mx-5 -mb-4 sm:-mb-5 px-4 sm:px-5 py-3 bg-surface border-t border-line" : ""}`}>
        <textarea ref={inputRef} rows={1} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKeyDown}
          disabled={busy} maxLength={2000}
          placeholder={turns.length ? "Ask a follow-up… (Enter to send)" : `Ask anything about ${name}…`}
          className="flex-1 min-w-0 resize-none bg-surface border border-line rounded-xl px-3 py-2 text-sm leading-5 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60" />
        <button disabled={busy || input.trim().length < 3} aria-label="Ask"
          className="bg-accent text-white text-sm font-medium rounded-xl px-4 py-2 transition-opacity hover:opacity-90 disabled:opacity-50">
          {busy ? "…" : "Ask"}
        </button>
      </form>
    </Card>
  );
}
