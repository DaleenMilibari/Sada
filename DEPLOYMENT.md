# Sada — Production Deployment

Two services:

| Part | Host | Config |
|---|---|---|
| FastAPI backend (`backend/`) | Render (web service) | [render.yaml](render.yaml) |
| Postgres database | Render (free Postgres) | [render.yaml](render.yaml) `databases:` |
| React frontend (`src/`) | Vercel | `VITE_API_BASE` env var |

Deploy the **backend first** — the frontend needs its URL at build time.

---

## 1. Backend on Render

1. Push this repo to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo. Render reads `render.yaml` and creates **both** the `sada-db` Postgres and the `sada-api` web service; `DATABASE_URL` is wired automatically.
3. When prompted, fill the secret env vars:
   - `GEMINI_API_KEY` — Google AI Studio key.
   - `YOUTUBE_API_KEY` — Google Cloud key with "YouTube Data API v3" enabled (restrict it to that API).
   - `META_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID` — from the Instagram setup ([DATA_COLLECTION.md](DATA_COLLECTION.md) section 3). Leave them empty to collect YouTube only; you can add them later and redeploy.
   - `SADA_ACCESS_PASSWORD` — the team login password (use a long one; share it out-of-band).
   - `CORS_ORIGINS` — the Vercel URL, e.g. `https://sada.vercel.app` (comma-separate multiple, no trailing slash). You can set a placeholder and update it after step 2.
   - `SADA_SECRET_KEY` is generated automatically.
4. Deploy. Check `https://<your-service>.onrender.com/health` returns `{"status":"ok","auth":true}`.
5. **Load data immediately** instead of waiting for the scheduler to backfill: from your laptop, with the
   database's *External Database URL* (Render → sada-db → Connect):
   ```bash
   DATABASE_URL="<external url>" python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz
   ```
   After that the in-process collector keeps it fresh every 30 minutes. Check progress at
   `GET /api/collector/status` (logged in).

**Free Postgres expires 30 days after creation.** Before then, export (`python -m backend.db_tools export …` with the external URL) and either upgrade the plan or re-import into a new database.

The service **refuses to start** in production if `SADA_ACCESS_PASSWORD` or `SADA_SECRET_KEY` is missing, so a misconfigured deploy fails loudly instead of running open.

The `starter` plan is recommended: the free plan sleeps after inactivity (first request then takes ~1 min).

## 2. Frontend on Vercel

1. Vercel → **Add New Project** → import the repo. Framework preset: **Vite** (auto-detected).
2. Environment variable: `VITE_API_BASE = https://<your-service>.onrender.com` (no trailing slash).
3. Deploy. Then make sure `CORS_ORIGINS` on Render matches the final Vercel domain (including any custom domain) and redeploy the backend if you changed it.

## 3. Smoke test after deploy

- [ ] Opening the site shows the login screen; wrong password → error, right password → dashboard.
- [ ] Dashboard loads the pattern cards; "تحديث" refreshes them.
- [ ] Optimizer: a draft returns AI-generated variants, a winner, platform and time.
- [ ] Broadcast: the spike alert and chart load; a diagnosis prompt returns an answer.
- [ ] Logout returns to the login screen.

---

## Configuration reference (backend)

See [backend/.env.example](backend/.env.example) for all variables. Key ones:

| Variable | Default | Purpose |
|---|---|---|
| `SADA_ENV` | `development` | `production` enforces auth config and hides `/docs` |
| `SADA_ACCESS_PASSWORD` | empty | Team password; empty = auth disabled (local dev only) |
| `SADA_SECRET_KEY` | empty | Token signing key (≥ 32 chars) — rotating it logs everyone out |
| `SADA_TOKEN_TTL_HOURS` | `12` | Session length |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origins |
| `SADA_LLM_RATE_LIMIT_PER_MINUTE` | `20` | Per-IP limit on Gemini-backed routes |
| `SADA_LOGIN_RATE_LIMIT_PER_MINUTE` | `5` | Per-IP limit on login attempts |
| `SADA_TRUSTED_PROXY_HOPS` | `0` (`1` on Render) | Proxies in front of the app, for real client IP |
| `DATABASE_URL` | SQLite file | Set automatically by Render's Postgres |
| `YOUTUBE_API_KEY` | empty | Enables the Data Collector agent |
| `COLLECTOR_SCHEDULE_ENABLED` | `false` (`true` on Render) | Run the collector in-process every `COLLECTOR_INTERVAL_MINUTES` |
| `COLLECTOR_QUOTA_PER_RUN` | `600` (`300` on Render) | YouTube units a run may spend (daily free quota 10,000) |
| `COLLECTOR_LOOKBACK_DAYS` | `60` | Rolling window of uploads tracked per channel |
| `META_ACCESS_TOKEN` | empty | Long-lived Meta user token; enables Instagram collection |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | empty | Our own Instagram business account id, used for Business Discovery lookups |
| `META_GRAPH_API_VERSION` | `v23.0` | Graph API version |
| `INSTAGRAM_REFRESH_DAYS` | `7` | Days re-read per run once an account is backfilled |

## Local development

```bash
pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env       # add GEMINI_API_KEY; leave SADA_ACCESS_PASSWORD empty to skip login
uvicorn backend.api:app --reload --port 8000

npm install
npm run dev                                # http://localhost:5173
pytest backend/tests -v

# Real SBA data: import the shared seed (no API key needed) ...
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz
# ... or collect yourself (needs YOUTUBE_API_KEY; spends quota)
python -m backend.agents.data_collector_agent --budget 1000
# Instagram only (needs META_ACCESS_TOKEN + INSTAGRAM_BUSINESS_ACCOUNT_ID)
python -m backend.agents.data_collector_agent --platform instagram
```

## Known limitations (post-launch backlog)

- **Single shared password**, not per-user accounts. Fine for an internal team launch; move to real user accounts (e.g. Auth0/Clerk/Supabase Auth) before opening to external users.
- **Single instance only**: the collector schedule runs inside the web process, and rate limits / the pattern store are per-instance. Before scaling out, move the collector to a Render Cron Job and rate limits to Redis.
- **YouTube and Instagram only.** X and TikTok need paid or approved API access; see [DATA_COLLECTION.md](DATA_COLLECTION.md) section 5.
- **The Instagram token expires after 60 days.** Regenerate it per DATA_COLLECTION.md section 3.3 and update `META_ACCESS_TOKEN` on Render. `GET /api/collector/status` shows an "expired" error when this happens.
- **No schema migrations** (tables are created with `create_all`). Changing an existing column needs a manual `ALTER TABLE` or a fresh database + seed import.
