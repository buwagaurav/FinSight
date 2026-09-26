"""Document search (RAG) over NSE filings and annual reports, with page-level citations.

  - Documents are split per page (long pages into overlapping chunks), so every passage keeps its page number.
  - Search is PostgreSQL full-text (websearch syntax, ranked), filtered by company and document type. It needs no
    extra memory or AI calls; meaning-based (vector) search can be added later with pgvector.
  - Filings are small and indexed on demand. Annual reports are large (300+ pages), so they are indexed ahead of
    time by `python -m app.docs` (run by the GitHub Actions refresh job for the largest companies).
"""
import argparse
import io
import logging
import re
import threading
from datetime import datetime

import requests
from pypdf import PdfReader

from app import db
from app.providers import nse

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding warnings are harmless noise

CHUNK_CHARS = 1500
OVERLAP = 200
MAX_FILING_BYTES = 15_000_000
MAX_REPORT_BYTES = 60_000_000
FILINGS_PER_COMPANY = 12
KEEP_FILINGS = 20   # newest filings kept per company
_locks: dict[str, threading.Lock] = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id          bigserial PRIMARY KEY,
    symbol      text NOT NULL,
    kind        text NOT NULL,              -- filing | annual_report
    title       text NOT NULL,
    url         text NOT NULL UNIQUE,
    published   date,
    fiscal_year text,
    pages       int,
    indexed_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_symbol_idx ON documents (symbol, kind);

CREATE TABLE IF NOT EXISTS doc_chunks (
    id           bigserial PRIMARY KEY,
    document_id  bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page         int NOT NULL,
    text         text NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX IF NOT EXISTS doc_chunks_tsv_idx ON doc_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS doc_chunks_doc_idx ON doc_chunks (document_id);
"""
_schema_ready = False


def _ensure_schema():
    global _schema_ready
    if not _schema_ready:
        db.execute(SCHEMA)
        _schema_ready = True


def _download(url: str, max_bytes: int) -> bytes:
    if not url.startswith("https://nsearchives.nseindia.com/"):
        raise ValueError("Only NSE archive documents are fetched")
    r = requests.get(url, headers={"User-Agent": nse.HEADERS["User-Agent"]}, timeout=120, stream=True)
    r.raise_for_status()
    data = r.raw.read(max_bytes + 1, decode_content=True)
    if len(data) > max_bytes:
        raise ValueError("Document too large to index")
    return data


def _chunks(pages: list[str]) -> list[tuple[int, str]]:
    """(page number, text) passages. Long pages are split with overlap so a sentence isn't cut from its context."""
    out = []
    for n, text in enumerate(pages, 1):
        text = re.sub(r"[ \t]+", " ", text).strip()
        if len(text) < 40:
            continue  # blank or image-only page
        start = 0
        while start < len(text):
            out.append((n, text[start:start + CHUNK_CHARS]))
            if start + CHUNK_CHARS >= len(text):
                break
            start += CHUNK_CHARS - OVERLAP
    return out


def index_pdf(symbol: str, kind: str, title: str, url: str, published: str | None, fiscal_year: str | None,
              max_bytes: int) -> int:
    """Download, split and store one PDF. Returns the number of passages (0 if already indexed)."""
    _ensure_schema()
    if db.fetch_one("SELECT 1 FROM documents WHERE url = %s", (url,)):
        return 0
    reader = PdfReader(io.BytesIO(_download(url, max_bytes)), strict=False)  # many filed PDFs are slightly malformed
    pages = []
    for p in reader.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    chunks = _chunks(pages)
    with db.conn() as c:
        doc = c.execute("""INSERT INTO documents (symbol, kind, title, url, published, fiscal_year, pages)
                           VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (url) DO NOTHING RETURNING id""",
                        (symbol, kind, title, url, published, fiscal_year, len(pages))).fetchone()
        if not doc:
            return 0
        with c.cursor() as cur:
            cur.executemany("INSERT INTO doc_chunks (document_id, page, text) VALUES (%s, %s, %s)",
                            [(doc["id"], page, text.replace("\x00", "")) for page, text in chunks])
    return len(chunks)


def index_filings(symbol: str, limit: int = FILINGS_PER_COMPANY) -> int:
    """Index the company's latest non-routine NSE filings that aren't stored yet (fast: small PDFs)."""
    base = symbol.split(".")[0].upper()
    lock = _locks.setdefault(f"filings:{base}", threading.Lock())
    with lock:
        added = 0
        for a in nse.announcements(base, 40):
            if a["routine"] or not a["pdf_url"] or not a["pdf_url"].lower().endswith(".pdf"):
                continue
            if limit <= 0:
                break
            limit -= 1
            try:
                added += index_pdf(base, "filing", f"{a['category'] or 'Announcement'}: {a['text'][:160]}",
                                   a["pdf_url"], (a["published"] or "")[:10] or None, None, MAX_FILING_BYTES)
            except Exception:
                continue  # one broken PDF shouldn't stop the rest
        db.execute("""DELETE FROM documents WHERE id IN (
                          SELECT id FROM documents WHERE symbol = %s AND kind = 'filing'
                          ORDER BY published DESC NULLS LAST OFFSET %s)""", (base, KEEP_FILINGS))
        return added


def index_annual_report(symbol: str) -> int:
    """Index the company's latest annual report PDF published on NSE."""
    base = symbol.split(".")[0].upper()
    rows = nse._get(f"/api/annual-reports?index=equities&symbol={requests.utils.quote(base)}").get("data", [])
    for r in rows:
        url = r.get("fileName") or ""
        if not url.lower().endswith(".pdf"):
            continue  # older years are sometimes zipped
        fy = f"FY{str(r['toYr'])[-2:]}"
        published = None
        try:
            published = datetime.strptime(r["broadcast_dttm"], "%d-%b-%Y %H:%M:%S").date().isoformat()
        except (KeyError, ValueError):
            pass
        added = index_pdf(base, "annual_report", f"Annual Report {fy} ({r['fromYr']}-{r['toYr']})", url, published, fy,
                          MAX_REPORT_BYTES)
        # keep only the latest annual report per company (older ones are ~5 MB each)
        db.execute("DELETE FROM documents WHERE symbol = %s AND kind = 'annual_report' AND url <> %s", (base, url))
        return added
    return 0


def _run(base: str, tsquery_sql: str, query: str, kind: str | None, limit: int, exclude: list[int]) -> list[dict]:
    kind_clause, params = "", [query, base]
    if kind in ("filing", "annual_report"):
        kind_clause = "AND d.kind = %s"
        params.append(kind)
    params += [exclude or [0], limit]
    return db.fetch_all(f"""
        SELECT c.id, d.kind, d.title, d.url, d.published, d.fiscal_year, c.page, c.text,
               ts_rank_cd(c.tsv, q, 32) AS rank
        FROM doc_chunks c JOIN documents d ON d.id = c.document_id, {tsquery_sql} AS q
        WHERE d.symbol = %s {kind_clause} AND c.tsv @@ q AND c.id <> ALL(%s)
        ORDER BY rank DESC, d.published DESC NULLS LAST
        LIMIT %s""", params)


def search(symbol: str, query: str, kind: str | None = None, limit: int = 5) -> list[dict]:
    """Best-matching passages for a company: passages containing every search word first, then passages
    containing some of them (ranked by how many and how close together)."""
    _ensure_schema()
    base = symbol.split(".")[0].upper()
    rows = _run(base, "websearch_to_tsquery('english', %s)", query, kind, limit, [])
    words = list(dict.fromkeys(w.lower() for w in re.findall(r"[A-Za-z0-9]+", query)))[:8]
    if len(rows) < limit and words:
        rows += _run_any(base, words, kind, limit - len(rows), [r["id"] for r in rows])
    return rows


def _run_any(base: str, words: list[str], kind: str | None, limit: int, exclude: list[int]) -> list[dict]:
    """Passages matching any word, ordered by how many different words they match, then by rank. Without this a
    page that repeats one common word ("employees") beats the page that actually answers ("attrition")."""
    matched = " + ".join(["(c.tsv @@ plainto_tsquery('english', %s))::int"] * len(words))
    kind_clause = "AND d.kind = %s" if kind in ("filing", "annual_report") else ""
    params = [*words, " or ".join(words), base, *([kind] if kind_clause else []), exclude or [0], limit]
    return db.fetch_all(f"""
        SELECT c.id, d.kind, d.title, d.url, d.published, d.fiscal_year, c.page, c.text,
               ({matched}) AS matched, ts_rank_cd(c.tsv, q, 32) AS rank
        FROM doc_chunks c JOIN documents d ON d.id = c.document_id, websearch_to_tsquery('english', %s) AS q
        WHERE d.symbol = %s {kind_clause} AND c.tsv @@ q AND c.id <> ALL(%s)
        ORDER BY matched DESC, rank DESC, d.published DESC NULLS LAST
        LIMIT %s""", params)


def coverage(symbol: str) -> dict:
    _ensure_schema()
    rows = db.fetch_all("""SELECT kind, count(*) AS n, max(fiscal_year) AS latest_fy FROM documents
                           WHERE symbol = %s GROUP BY kind""", (symbol.split(".")[0].upper(),))
    return {r["kind"]: {"documents": r["n"], "latest_fy": r["latest_fy"]} for r in rows}


def main():
    ap = argparse.ArgumentParser(description="Index NSE annual reports and filings for document search.")
    ap.add_argument("--symbols", help="comma-separated NSE symbols (default: the largest companies)")
    ap.add_argument("--top", type=int, default=50, help="when --symbols is not given, index this many largest companies")
    ap.add_argument("--skip-reports", action="store_true")
    args = ap.parse_args()
    symbols = args.symbols.split(",") if args.symbols else [
        r["symbol"] for r in db.fetch_all("SELECT symbol FROM metrics ORDER BY market_cap_cr DESC NULLS LAST LIMIT %s", (args.top,))]
    for s in symbols:
        try:
            reports = 0 if args.skip_reports else index_annual_report(s)
            filings = index_filings(s)
            print(f"{s:<12} annual report passages +{reports:<5} filing passages +{filings}")
        except Exception as e:
            print(f"{s:<12} error: {e}")
    size = db.fetch_one("SELECT pg_size_pretty(pg_database_size(current_database())) AS s")["s"]
    print(f"database size: {size}")


if __name__ == "__main__":
    main()
