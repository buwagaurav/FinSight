# Deploying FinSight for free

| Part | Host | Free tier |
|---|---|---|
| Website (Next.js) | Netlify | yes |
| API (FastAPI) | Render web service | yes; sleeps after ~15 min idle, first request then takes ~30-60 s |
| Database | Neon PostgreSQL | yes; ~0.5 GB (FinSight uses ~50 MB) |
| Nightly data refresh | GitHub Actions | yes (public repo) |

Free tiers change; check each provider's current limits.

## 1. Database: Neon
1. Sign up at https://neon.tech, create a project, and choose the **AWS Singapore** region (closest to India).
2. Copy the connection string (`postgresql://...?sslmode=require`).
3. Copy your local data into it so the cloud starts complete (from the repo root on your Mac):
   ```bash
   cd backend
   ../.venv/bin/python -m scripts.copy_db "<neon connection string>"
   ```

## 2. Nightly refresh: GitHub Actions
In the GitHub repo: **Settings > Secrets and variables > Actions > New repository secret**,
name `DATABASE_URL`, value = the Neon connection string. The "Refresh market data" workflow then runs twice a day;
**Actions > Refresh market data > Run workflow** runs it now.

Its `us-market` job fills the US screener. The first run takes the longest (two SEC bulk files of ~1.5 GB each, then
prices for ~4,000 companies); after that it refreshes prices every run and statements once a week. Until the first run
finishes, the Screener's US tab says the data hasn't been loaded yet. The US tables add roughly 50 MB to Neon.

## 3. API: Render
1. Sign up at https://render.com with GitHub, then **New > Blueprint** and pick this repo (it reads `render.yaml`).
2. Fill in the values it asks for:
   - `DATABASE_URL`: the Neon connection string
   - `DEEPSEEK_API_KEY`: your DeepSeek key
   - `FINSIGHT_CORS_ORIGINS`: leave empty for now; set it in step 5
3. When it's live, open `https://<your-api>.onrender.com/api/health`; you should see `{"ok":true}`.
4. Also open `/api/ipos`. If it returns an NSE error, NSE is blocking Render's servers; company pages, the screener
   and GMP still work (see "Known limits").

## 4. Website: Netlify
1. Sign up at https://netlify.com with GitHub, then **Add new site > Import an existing project** and pick this repo
   (it reads `netlify.toml`).
2. Before deploying, add the environment variable `NEXT_PUBLIC_API_URL` = `https://<your-api>.onrender.com`.
3. Deploy, and note the site address, e.g. `https://finsight-xyz.netlify.app`.

## 5. Connect them
In Render, set `FINSIGHT_CORS_ORIGINS` to the Netlify address (no trailing slash) and save; Render redeploys.
Open the Netlify site. The first load may take up to a minute while the free API wakes up.

## 6. Google sign-in
Research pages stay public; signing in with Google unlocks the AI features, with a daily allowance per user.

1. **Google Cloud Console** (https://console.cloud.google.com): create a project, then **Google Auth Platform**
   (OAuth consent screen): app name *FinSight*, your support email, audience **External**.
2. **Clients > Create client > Web application**:
   - Authorized JavaScript origins: `https://<your-site>.netlify.app` and `http://localhost:3000`
   - Authorized redirect URIs: `https://<your-site>.netlify.app/api/auth/callback/google` and
     `http://localhost:3000/api/auth/callback/google`
   - Copy the **Client ID** and **Client secret**.
3. **Audience > Publish app** (switch from "Testing" to "In production"). FinSight only asks for name, email and
   profile picture, so Google doesn't require a review; while in Testing, only listed test users can sign in.
4. Generate two random secrets: run `openssl rand -base64 32` twice.
5. **Netlify** environment variables: `AUTH_SECRET` (secret 1), `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`,
   `FINSIGHT_API_JWT_SECRET` (secret 2). Redeploy.
   Sign-in always uses the site's main address (`https://<site>.netlify.app`, or your custom domain), taken from
   Netlify at build time, never Netlify's internal `main--<site>` address. Set `AUTH_URL` only to override it.
6. **Render** environment: `FINSIGHT_API_JWT_SECRET` (the same secret 2). Save; Render redeploys.

If you rename the Netlify site, redeploy and update both Google URLs and `FINSIGHT_CORS_ORIGINS`.

## Known limits
- **Cold starts:** the free API sleeps when idle; the first visit afterwards is slow.
- **NSE may block cloud servers:** the IPO list, live subscription and filings come from NSE, which often rejects
  requests from hosting providers. If so, those sections show an error on the deployed site but work locally.
- **Long AI jobs:** a research report runs in the API's memory; if the free instance goes to sleep mid-report, start it again.
- **Secrets** live only in the Render, Netlify and GitHub settings, never in the repo.

## Security notes
- **Rate limits** (per visitor IP, in the API): 240 requests a minute overall, 60 stock searches a minute, 10 AI requests
  a minute, 10 GMP entries an hour. Visitors over a limit get HTTP 429 with a `Retry-After` header. On Render the
  visitor's address comes from Cloudflare's `True-Client-IP` header (set automatically; nothing to configure).
- **Diagnostics** `/api/health/sources` and `/api/health/storage` return 404 unless the request carries
  `X-Admin-Token: <FINSIGHT_ADMIN_TOKEN>`. Set `FINSIGHT_ADMIN_TOKEN` on Render (e.g. `openssl rand -hex 32`) only if you
  want to use them.
- **Errors and logs**: visitors only ever see plain messages; everything the API prints or logs has API keys,
  `DATABASE_URL`, connection strings and database host/user details removed (`backend/app/security.py`).
- **Hardening**: remote databases are always reached over TLS (`sslmode=require` is enforced); the API's `/docs` and
  `/openapi.json` are off in production; request bodies over 512 KB are refused; symbols in URLs must look like
  symbols; API and website responses carry security headers (the website's Content-Security-Policy limits scripts,
  connections, frames and form posts to the site, the API and Google sign-in). Dependency scans: `npm audit` in
  `web/`, and `pip-audit` for `backend/requirements.txt`.
- **Penetration probe**: `cd backend && python -m security.pentest` runs a black-box security probe against a
  running instance (default localhost) — injection, broken auth, object-level authorization (IDOR), SSRF, reflected
  XSS, unbounded-input DoS, security headers, information leakage, rate limiting and CORS. Point it at any instance
  you own with `--api`/`--web`; it exits non-zero on a failure, so it can gate CI. Set `FINSIGHT_API_JWT_SECRET` so
  it can mint test tokens for the authenticated checks.
