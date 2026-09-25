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

## Known limits
- **Cold starts:** the free API sleeps when idle; the first visit afterwards is slow.
- **NSE may block cloud servers:** the IPO list, live subscription and filings come from NSE, which often rejects
  requests from hosting providers. If so, those sections show an error on the deployed site but work locally.
- **Long AI jobs:** a research report runs in the API's memory; if the free instance goes to sleep mid-report, start it again.
- **Secrets** live only in the Render, Netlify and GitHub settings, never in the repo.
