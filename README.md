# FinSight

One research workspace for Indian stocks and IPOs: search a company once and see its price,
five years of fundamentals, explained scores, valuation scenarios, news, and live IPO/GMP data.

## Run it locally

```bash
# 1. API (Python 3.12)
.venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/uvicorn app.main:app --port 8010 --reload

# 2. Web (Node 20+), in a second terminal
cd web && npm install && npm run dev
```

Open http://localhost:3000.

**Database:** nothing to install. On first start the API runs its own PostgreSQL 16 (via the `pgserver` Python package)
with data in `backend/data/postgres/`, and a background loader starts filling it with every NSE-listed company from
NSE's official list (~2,550). The load is resumable: if Yahoo rate-limits it, it pauses and continues later, never
restarting from zero. Progress: `GET /api/loader/status` or `cd backend && ../.venv/bin/python -m app.loader --status`.
To use another PostgreSQL (Postgres.app, Neon, Supabase), set `DATABASE_URL`.

**AI features (optional):** copy `backend/.env.example` to `backend/.env` and add a key for at least one provider.
Each feature can use a different model (`FINSIGHT_MODEL_ASSISTANT`, `_REPORT`, `_SUMMARY`, `_SCREEN`) from Anthropic,
DeepSeek, Kimi (Moonshot) or any OpenAI-compatible server. Without a key, everything else works. The web app proxies `/api/*` to `FINSIGHT_API_URL` (default `http://localhost:8010`).
The first screener run of the day computes metrics for the whole universe (~1 minute); after that it is cached.

## How it is built

| Layer | What it does |
|---|---|
| `backend/app/providers/` | Data adapters. `yahoo.py`: prices, statements, profile, news (values converted to ₹ crore). `nse.py`: official IPO dates, price band and live subscription. |
| `backend/app/analytics/` | Deterministic engine. `fundamentals.py` builds the yearly table and ratios (ROE, ROCE, margins, cash conversion, CAGR) plus data-quality checks. `scores.py` gives rule-based scores where every point is a readable reason. `valuation.py` computes historical P/E and bear/base/bull scenarios with stated assumptions. `technicals.py` covers trend, volatility and drawdown. |
| `backend/app/gmp.py` | Unofficial GMP records, each with source and timestamp; never mixed into scores. |
| `backend/app/db.py` | PostgreSQL storage (embedded by default, or `DATABASE_URL`): companies, load status, profiles, statements, screener metrics, GMP, filing summaries, reports. |
| `backend/app/loader.py` | Resumable loader for every NSE company: profiles daily, statements weekly, backs off on rate limits; runs in the API's background or by hand. |
| `backend/app/screener.py` | SQL screens over every loaded company, using the same metrics engine as the company page. |
| `backend/app/ai/` | Research assistant. `tools.py`: 8 tools over the engine (snapshot, statements, valuation, news, peer comparison, screener, calculator), each result tagged with a source id. `llm.py`: per-task model choice and provider adapters (Anthropic SDK; OpenAI-compatible for DeepSeek, Kimi, self-hosted), plus the verified tool-use loop. `assistant.py`: Ask FinSight. `verify.py`: every figure in an answer must match a tool result, or Claude gets one chance to fix it and any leftovers are shown to the user. |
| `backend/app/ai/filings.py` | NSE corporate announcements summarised from the filed PDF into a fixed structure (what happened, why it matters, sentiment, materiality, affected metrics, what to watch); quoted figures are checked against the PDF text; cached per filing. |
| `backend/app/ai/screen_nl.py` | Plain-English screens become the screener's own filters and sectors (schema-enforced), with every interpretation of vague words listed for the user. |
| `backend/app/ai/report.py` | LangGraph multi-agent report: fundamentals, valuation and filings/news analysts in parallel, then a risk reviewer, writer, and a checker that sends the writer back (up to 2 times) if any figure or citation can't be traced. Runs as a background job; saved per company. |
| `backend/eval/` | `check_data.py` (FinSight data vs audited NSE XBRL filings, no key needed), `run_eval.py` + 125 questions (assistant faithfulness). See `backend/eval/README.md`. |
| `backend/research/forecast_backtest.py` | Walk-forward backtest of return forecasters by market regime, with a promotion gate: no forecast is shown to users unless it beats a random walk in every regime and its intervals are calibrated. |
| `web/` | Next.js + Tailwind + ECharts. Home, `/stock/[symbol]` (Overview · Fundamentals · Valuation · News), `/screener`, `/ipo`. |

Product rules the code follows:
- The LLM (when added) explains; code calculates. No model does arithmetic on financials.
- No single "target price": always a range, with the assumptions shown.
- Show uncertainty: data checks flag mergers, source disagreements and short history, and lower confidence.
- GMP is always labelled unofficial and kept out of every score.

## Known limitations

- Yahoo Finance returns ~4 annual years for most NSE companies. Ten-year history needs a licensed vendor or XBRL filings from NSE/BSE.
- Yahoo's reported EPS is not always restated for bonus issues, so EPS is derived from net profit ÷ average shares.
- No free official GMP feed exists. GMP is entered with its source via the IPO page or `POST /api/ipos/{symbol}/gmp`.
- The first full load of ~2,550 companies can take a few hours when Yahoo rate-limits; the screener shows its coverage meanwhile.

## Roadmap

**Next (MVP completion)**
1. ~~AI research assistant~~, ~~NSE filings with AI summaries~~, ~~natural-language screening~~,
   ~~multi-agent report (LangGraph)~~, ~~evaluation set + data check~~, ~~forecasting backtest harness~~ (done).
   Next: run the assistant eval with a real key and tune prompts against it; stream answers; surface
   `check_data.py` mismatches as data checks on company pages.
3. Peer comparison (sector peer groups) and relative valuation.
4. Watchlist and alerts (user accounts, PostgreSQL).
5. IPO detail pages: RHP financials, anchor investors, category-wise subscription, listing-day results.

**Phase 2:** natural-language screening (NL → editable filter query), a full-market universe with a nightly
TimescaleDB pipeline, earnings-call analysis, portfolio tracking, sector dashboards.

**Phase 3:** backtested forecasting models (with horizon, confidence interval and failure cases reported),
a React Native mobile app on the same API, and Indian-language support.
