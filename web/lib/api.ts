export type Source = { name: string; url: string };

export type SearchResult = { symbol: string; name: string; exchange: string; sector: string | null };

export type Profile = {
  symbol: string;
  name: string;
  exchange: string;
  sector: string | null;
  industry: string | null;
  summary: string | null;
  website: string | null;
  price: number | null;
  change_pct: number | null;
  market_cap_cr: number | null;
  week52_high: number | null;
  week52_low: number | null;
  pe: number | null;
  forward_pe: number | null;
  pb: number | null;
  ev_ebitda: number | null;
  ps: number | null;
  peg: number | null;
  dividend_yield_pct: number | null;
  roe_ttm_pct: number | null;
  debt_to_equity_ttm: number | null;
  promoter_holding_pct: number | null;
  institutional_holding_pct: number | null;
  beta: number | null;
  trailing_eps: number | null;
  source: Source;
};

export type YearRow = {
  year: string;
  period_end: string;
  revenue: number | null;
  ebitda: number | null;
  operating_profit: number | null;
  net_profit: number | null;
  eps: number | null;
  equity: number | null;
  total_debt: number | null;
  cash: number | null;
  working_capital: number | null;
  operating_cash_flow: number | null;
  capex: number | null;
  free_cash_flow: number | null;
  dividends_paid: number | null;
  operating_margin_pct: number | null;
  net_margin_pct: number | null;
  roe_pct: number | null;
  roce_pct: number | null;
  debt_to_equity: number | null;
  interest_coverage: number | null;
  cash_conversion: number | null;
  revenue_growth_pct: number | null;
  profit_growth_pct: number | null;
};

export type Reason = { text: string; points: number };
export type ScoreCard = { name: string; score: number | null; label: string; reasons: Reason[] };

export type Scenario = {
  growth_pct: number;
  exit_pe: number;
  eps_in_3y: number;
  implied_price: number;
  implied_return_pct: number;
  implied_annual_return_pct: number | null;
};

export type Company = {
  profile: Profile;
  financials: {
    unit: string;
    years: YearRow[];
    growth: {
      years?: number;
      from?: string;
      to?: string;
      revenue_cagr_pct?: number | null;
      profit_cagr_pct?: number | null;
      eps_cagr_pct?: number | null;
    };
    data_checks: string[];
    source: Source;
  };
  scores: {
    overall: { score: number | null; label: string };
    view: string;
    cards: Record<"fundamentals" | "growth" | "valuation" | "safety", ScoreCard>;
    positives: string[];
    risks: string[];
    confidence: string;
    confidence_basis: string;
    method: string;
  };
  technical: {
    trend: string;
    sma50?: number | null;
    sma200?: number | null;
    return_1y_pct?: number;
    volatility_1y_pct?: number | null;
    max_drawdown_1y_pct?: number;
    reasons: string[];
  };
  valuation: {
    pe_history: { year: string; price: number; eps: number; pe: number }[];
    scenarios: {
      horizon_years: number;
      current_price: number;
      eps_ttm: number;
      cases: Record<"bear" | "base" | "bull", Scenario>;
      assumptions: string[];
    } | null;
  };
  prices: { date: string; close: number }[];
};

export type NewsItem = { title: string; summary: string; published: string | null; publisher: string | null; url: string };

export type GmpEntry = { gmp: number; source: string; source_url: string | null; observed_at: string };

export type Ipo = {
  symbol: string;
  name: string;
  segment: "Mainboard" | "SME";
  status: string;
  open_date: string | null;
  close_date: string | null;
  price_low: number | null;
  price_high: number | null;
  shares_offered: number | null;
  shares_bid: number | null;
  subscription_times: number | null;
  issue_size_cr: number | null;
  source: Source;
  gmp: {
    official: false;
    disclaimer: string;
    latest: GmpEntry | null;
    estimate: { estimated_listing_price: number; estimated_premium_pct: number; label: string } | null;
    history: GmpEntry[];
  };
};

export type ScreenFilter = { field: string; op: ">" | ">=" | "<" | "<="; value: number };
export type ScreenRow = Record<string, number | string | null> & { symbol: string; name: string };
export type ScreenResult = {
  universe: string;
  coverage: { listed: number; loaded: number; pending: number; unavailable: string[]; updated_at: number | null };
  built_at: number | null;
  count: number;
  shown: number;
  query: string;
  rows: ScreenRow[];
};

// Deployed: the site calls the API directly (NEXT_PUBLIC_API_URL, e.g. https://finsight-api.onrender.com).
// Local dev: unset, so "/api/..." goes through the Next.js rewrite to localhost:8010.
const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, { ...init, headers: { "content-type": "application/json", ...init?.headers } });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${res.status})`);
  }
  return res.json();
}

export type AskSource = { id: string; name: string; url: string | null; detail: string };
export type AskResult = {
  answer: string;
  sources: AskSource[];
  tool_calls: { tool: string; input: Record<string, unknown>; error: boolean }[];
  verification: { passed: boolean; unverified: string[]; misattributed?: string[]; note: string };
  model: string;
};
export type AiTask = "assistant" | "report" | "summary" | "screen";
export type AiStatus = { configured: boolean; model: string; tasks: Record<AiTask, { model: string; configured: boolean }> };

export type FilingSummary = {
  headline: string;
  what_happened: string;
  why_it_matters: string;
  sentiment: "positive" | "negative" | "neutral" | "uncertain";
  materiality: "high" | "medium" | "low";
  affected_metrics: string[];
  watch_next: string[];
  key_figures: { label: string; value: string }[];
};
export type SummaryResult = {
  summary: FilingSummary;
  basis: string;
  verification: { checked: boolean; passed: boolean; unverified: string[] };
  model: string;
};
export type Announcement = {
  id: string;
  company: string;
  category: string;
  text: string;
  published: string | null;
  pdf_url: string | null;
  pdf_size: string | null;
  routine: boolean;
  summary: SummaryResult | null;
};

export type ReportResult = {
  symbol: string;
  company: string;
  report: string;
  sections: Record<string, string>;
  review: string;
  sources: AskSource[];
  all_sources: AskSource[];
  verification: { passed: boolean; unverified: string[]; problems: string; rewrites: number };
  tool_calls: { tool: string; input: Record<string, unknown>; error: boolean; agent: string }[];
  model: string;
  generated_at: string;
  duration_s: number;
};
export type ReportJob = {
  id: string;
  status: "running" | "done" | "error";
  error: string | null;
  result: ReportResult | null;
  steps: { key: string; label: string; status: "pending" | "running" | "done" | "retry" }[];
};
