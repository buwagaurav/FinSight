"""Request rate limits, and keeping secrets and database details out of responses and logs.

Rate limits are per visitor IP, in memory (one API process; switch to Redis if FinSight ever runs several). Behind
Render, the visitor's address comes from Cloudflare's True-Client-IP header, which Cloudflare overwrites, so a
client can't fake it; X-Forwarded-For is not used (clients can prepend to it, and on Render its last entries are
Cloudflare and Render hops shared by every visitor).

Redaction: everything the API prints or logs goes through `redact()`, which removes the values of secret
environment variables (API keys, JWT secret, DATABASE_URL), any connection string, and database host/user
details, so a crash or an upstream error can't write credentials to the logs.
"""
import os
import re
import sys
import threading
import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------------------------------------------- redaction

SECRET_ENV = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|DATABASE_URL|AUTH_TOKEN|PROFILE", re.IGNORECASE)
PATTERNS = [
    (re.compile(r"\b(?:postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?)://\S+", re.IGNORECASE), "[connection string]"),
    (re.compile(r"\b(?:host|hostaddr|user|password|dbname)=\S+", re.IGNORECASE), "[db detail]"),
    (re.compile(r'(?:server at|for user) "[^"]*"( \([^)]*\))?', re.IGNORECASE), "[db detail]"),
    (re.compile(r"\b[\w.-]+\.(?:neon\.tech|supabase\.co|render\.com|amazonaws\.com|rds\.amazonaws\.com)\b"), "[host]"),
    (re.compile(r"\b(?:sk-ant-|sk-|ghp_|github_pat_|npg_|GOCSPX-)[A-Za-z0-9_\-]{8,}"), "[key]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer [token]"),
]


def _secret_values() -> list[str]:
    return sorted({v for k, v in os.environ.items() if SECRET_ENV.search(k) and v and len(v) >= 8}, key=len, reverse=True)


def redact(text: str) -> str:
    if not text:
        return text
    for value in _secret_values():
        text = text.replace(value, "[secret]")
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class _RedactingStream:
    """Wraps stdout/stderr so that print(), uvicorn's logs and tracebacks are all redacted on the way out."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        return self._stream.write(redact(text))

    def __getattr__(self, name):
        return getattr(self._stream, name)


def protect_output():
    if not isinstance(sys.stdout, _RedactingStream):
        sys.stdout = _RedactingStream(sys.stdout)
    if not isinstance(sys.stderr, _RedactingStream):
        sys.stderr = _RedactingStream(sys.stderr)


GENERIC_500 = "Something went wrong on our side. Please try again in a moment."


async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Any error no route handled: a plain message for the visitor; the (redacted) details go to the server log."""
    print(f"[error] {request.method} {request.url.path}: {type(exc).__name__}: {redact(str(exc))}", file=sys.stderr)
    return JSONResponse({"detail": GENERIC_500}, status_code=500)


# ---------------------------------------------------------------- client address

def client_ip(request: Request) -> str:
    if os.environ.get("RENDER") or os.environ.get("FINSIGHT_BEHIND_CLOUDFLARE"):
        for header in ("true-client-ip", "cf-connecting-ip"):
            if value := request.headers.get(header):
                return value.strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------- rate limits

# (method or "*", path regex, requests, per seconds). First match wins; every request also counts against "all".
RULES = [
    ("POST", re.compile(r"^/api/(ask|screener/parse|company/[^/]+/report|company/[^/]+/announcements/[^/]+/summary)$"), 10, 60),
    ("POST", re.compile(r"^/api/ipos/[^/]+/gmp$"), 10, 3600),
    ("GET", re.compile(r"^/api/search$"), 60, 60),
]
OVERALL = (240, 60)   # a page makes ~6 calls; this allows fast browsing but stops scripted scraping
EXEMPT = {"/api/health"}   # the keep-warm ping
MAX_KEYS = 50_000


class RateLimiter:
    """Sliding-window counts per (rule, visitor)."""

    def __init__(self):
        self._hits: dict[tuple, deque] = {}
        self._lock = threading.Lock()

    def hit(self, key: tuple, limit: int, window: float, now: float | None = None) -> float | None:
        """Record a request; returns None if allowed, else seconds until the next one would be."""
        now = now if now is not None else time.monotonic()
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                self._hits.clear()   # crude bound on memory under a flood of distinct addresses
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return q[0] + window - now
            q.append(now)
            return None

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path in EXEMPT or not path.startswith("/api/"):
            return await call_next(request)
        ip = client_ip(request)
        checks = [(("all", ip), *OVERALL)]
        for method, pattern, limit, window in RULES:
            if (method in ("*", request.method)) and pattern.match(path):
                checks.append(((pattern.pattern, ip), limit, window))
                break
        for key, limit, window in checks:
            wait = limiter.hit(key, limit, window)
            if wait is not None:
                return JSONResponse({"detail": "Too many requests. Please wait a moment and try again."},
                                    status_code=429, headers={"Retry-After": str(max(1, int(wait) + 1))})
        return await call_next(request)


# ---------------------------------------------------------------- request size and response headers

MAX_BODY_BYTES = 512 * 1024   # the largest real request (a chat question with its history and state) is ~150 KB
HEADERS = {
    "X-Content-Type-Options": "nosniff",       # browsers must not guess a JSON response is HTML or script
    "X-Frame-Options": "DENY",                 # API responses never belong in a frame
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",               # responses can carry a user's watchlist; never keep them in shared caches
}
# Stock symbols as they appear in URLs: NSE (M&M, BAJAJ-AUTO), US (BRK-B.US), with an optional exchange suffix.
# Anything else is refused before it reaches Yahoo, NSE or SEC requests.
SYMBOL_IN_PATH = re.compile(r"^/api/(?:company|watchlist|ipos)/([^/]+)")
SYMBOL = re.compile(r"^[A-Za-z0-9&.\-]{1,40}$")


class HardeningMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return JSONResponse({"detail": "Request too large."}, status_code=413)
        m = SYMBOL_IN_PATH.match(request.url.path)
        if m and m.group(1) not in ("symbols",) and not SYMBOL.match(m.group(1)):
            return JSONResponse({"detail": "Invalid symbol."}, status_code=422)
        response = await call_next(request)
        for k, v in HEADERS.items():
            response.headers.setdefault(k, v)
        return response
