# Sada — Production Deployment

Two services:

| Part | Host | Config |
|---|---|---|
| FastAPI backend (`backend/`) | Render (web service) | [render.yaml](render.yaml) |
| React frontend (`src/`) | Vercel | `VITE_API_BASE` env var |

Deploy the **backend first** — the frontend needs its URL at build time.

---

## 1. Backend on Render

1. Push this repo to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo. Render reads `render.yaml`.
3. When prompted, fill the secret env vars:
   - `GEMINI_API_KEY` — Google AI Studio key.
   - `SADA_ACCESS_PASSWORD` — the team login password (use a long one; share it out-of-band).
   - `CORS_ORIGINS` — the Vercel URL, e.g. `https://sada.vercel.app` (comma-separate multiple, no trailing slash). You can set a placeholder and update it after step 2.
   - `SADA_SECRET_KEY` is generated automatically.
4. Deploy. Check `https://<your-service>.onrender.com/health` returns `{"status":"ok","auth":true}`.

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

## Local development

```bash
pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env       # add GEMINI_API_KEY; leave SADA_ACCESS_PASSWORD empty to skip login
uvicorn backend.api:app --reload --port 8000

npm install
npm run dev                                # http://localhost:5173
pytest backend/tests -v
```

## Known limitations (post-launch backlog)

- **Single shared password**, not per-user accounts. Fine for an internal team launch; move to real user accounts (e.g. Auth0/Clerk/Supabase Auth) before opening to external users.
- **Rate limits and the pattern store are per-instance** (in-memory / local file). Keep Render at 1 instance, or move both to Redis/Postgres before scaling out.
- **Data is mostly synthetic**: the per-post engagement records, content history and broadcast signal are seed data; only the Hajj 1445 and AWJ | Sada datasets are real. The dashboard KPI cards / weekly chart and the broadcast video player are still static UI.
