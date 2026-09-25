"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import CitedMarkdown, { SourceList } from "@/components/CitedMarkdown";
import { Badge, Card } from "@/components/ui";
import { AiStatus, api, AskResult } from "@/lib/api";

type Turn = { id: number; question: string; result?: AskResult; error?: string };

const SUGGESTIONS = [
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
  compare_companies: "Compared companies",
  run_screen: "Ran a screen",
  calculate: "Calculated",
};

function Answer({ result }: { result: AskResult }) {
  const v = result.verification;
  const tools = result.tool_calls.filter((c) => !c.error);
  return (
    <div className="space-y-3">
      <CitedMarkdown text={result.answer} sources={result.sources} />

      {v.passed ? (
        <Badge variant="good">✓ Every figure matched the source it cites</Badge>
      ) : (
        <div className="rounded-lg border border-warn/40 bg-warn-soft p-2.5 text-xs text-ink-2">
          {v.unverified.length > 0 && <div><span className="font-semibold text-warn">● Not found in FinSight data: </span>{v.unverified.join(", ")}</div>}
          {(v.misattributed ?? []).length > 0 && <div><span className="font-semibold text-warn">● Cited to the wrong source: </span>{v.misattributed!.join(", ")}</div>}
          <div className="mt-1">{v.note}</div>
        </div>
      )}

      <SourceList sources={result.sources} />

      <details className="text-xs text-muted">
        <summary className="cursor-pointer">How this was researched ({tools.length} steps · {result.model})</summary>
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

export default function AskPanel({ symbol, name }: { symbol: string; name: string }) {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { api<AiStatus>("/api/ai/status").then(setStatus).catch(() => setStatus(null)); }, []);
  useEffect(() => { setTurns([]); }, [symbol]);
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
      const result = await api<AskResult>("/api/ask", { method: "POST", body: JSON.stringify({ question: q, symbol, history }) });
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, result } : t)));
    } catch (e) {
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, error: (e as Error).message } : t)));
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    ask(input);
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
      action={<span className="text-xs text-muted hidden sm:block">Answers cite their sources · not investment advice</span>}>
      {turns.length === 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {SUGGESTIONS.map((s) => (
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
                Researching: reading statements, checking every number… (usually 15–60 seconds)
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

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
