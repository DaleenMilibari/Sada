# Sada — Production Launch Tasks (team.md)

**Deadline: 2026-10-16 (tomorrow).**

The MVP is now production-capable: login, rate limiting, env-driven config, a real Optimizer, and Render/Vercel deploy config are in place (see [DEPLOYMENT.md](DEPLOYMENT.md)). This file splits the remaining launch work into **4 independent tasks**, one person each. No task needs another task's code to exist first.

The original agent contracts (field names, JSON shapes) are in [AGENT_SPEC.md](AGENT_SPEC.md) and [backend/schemas.py](backend/schemas.py). Do not rename existing fields.

---

## Who owns which files

Independence comes from file ownership. Only edit files in your own row. If you need a change in someone else's file, message them instead of editing it.

| Task | Owns (may edit / create) |
|---|---|
| 1 — Deploy, CI & Ops | `render.yaml`, `.github/workflows/*` (new), `eslint.config.js` (new), `package.json` (scripts/devDeps only), `DEPLOYMENT.md` |
| 2 — Real Dashboard Analytics | `src/components/DashboardView.tsx`, `backend/analytics.py` (new), `backend/tests/test_analytics.py` (new) |
| 3 — Broadcast & Diagnosis Completion | `src/components/BroadcastView.tsx`, `backend/tests/test_broadcast_api.py` (new) |
| 4 — Security Hardening & QA | `src/App.tsx`, `src/components/Sidebar.tsx`, `vercel.json` (new), `backend/security.py` (new) |

**`backend/api.py` is shared.** Tasks 2, 3 and 4 each add a few lines to it. Only *append* inside a comment block with your task number, for example `# --- Task 2: analytics ---`. Don't reorder or edit existing routes. Merge conflicts are then trivial.

Locked files: nobody edits `src/lib/api.ts`, `backend/auth.py`, `backend/config.py` or `backend/schemas.py` (existing models) without telling the whole team.

---

## Task 1 — Deploy, CI & Ops

**Owner:** _(assign)_

**Goal:** Sada is live on its production URLs, and every push is automatically checked.

1. **Deploy** following [DEPLOYMENT.md](DEPLOYMENT.md): backend to Render (Blueprint from `render.yaml`), then frontend to Vercel with `VITE_API_BASE` set. Set `CORS_ORIGINS` to the final Vercel domain, including any custom domain.
2. **Secrets:** generate a strong `SADA_ACCESS_PASSWORD` (≥ 16 chars) and share it with the team out-of-band (not in Slack/Git). Confirm `SADA_SECRET_KEY` was auto-generated.
3. **Fix lint:** `npm run lint` currently fails because there is no `eslint.config.js`. Add a flat config using the already-installed `@eslint/js`, `typescript-eslint`, `eslint-plugin-react-hooks` and `eslint-plugin-react-refresh`. Fix only lint *config*. If the rules flag code in someone else's file, report it to them.
4. **CI:** add `.github/workflows/ci.yml` that runs on every push and PR:
   - `pip install -r backend/requirements-dev.txt` → `pytest backend/tests`
   - `npm ci` → `npm run lint` → `npm run build`
5. **Monitoring:**
   - Free uptime monitor (e.g. UptimeRobot) on `https://<render-url>/health`, alerting the team email.
   - A budget alert in Google Cloud / AI Studio on the Gemini key.
6. Run the smoke-test checklist in DEPLOYMENT.md against production and tick it off in the PR.

**Done when:** both production URLs work, the smoke test passes, CI is green on `main`, and the uptime monitor is active.

---

## Task 2 — Real Dashboard Analytics

**Owner:** _(assign)_

**Goal:** Every number on the Dashboard comes from data, not hardcoded constants.

**Currently fake** in [DashboardView.tsx](src/components/DashboardView.tsx):
- the KPI cards (e.g. `14.2M`)
- the `weeklyData` area chart
- the `platforms` breakdown (`5.4M تفاعل`, …)
- the today / week / month period filter, which changes nothing

**Steps:**
1. Create `backend/analytics.py` with a pure function `summary() -> dict` that computes:
   - **KPIs** from `backend/data/engagement_records.json`: total views, total engagement (likes + shares), average watch time, record count.
   - **Engagement by day of week** from the same file (`day_of_week` field), to replace `weeklyData`.
   - **Platform breakdown** from the real `backend/data/hajj_1445_platform_totals.json`. Only compare platforms that report the same metric (see the `note` in that file). Use `null` for unreported values, never `0`.
   - A `sources` list naming which file each block came from, so the UI can label real vs. synthetic data.
2. In `backend/api.py` (Task 2 block), add `GET /api/analytics/summary` on the authenticated `api` router.
3. Wire DashboardView to it with `apiFetch` (from `src/lib/api.ts`). Use the same loading/error pattern as the pattern cards already in that file.
4. **Period filter:** the dataset has no dates, so it can't be filtered by period. Remove the filter rather than fake it.
5. Under each chart, add a small label showing the data source: "بيانات حقيقية – حج 1445هـ" or "بيانات تجريبية".
6. Add `backend/tests/test_analytics.py`: totals match a manual sum over the JSON, and unreported platform metrics stay `null`.

**Done when:** `grep` finds no hardcoded metric values left in DashboardView.tsx, tests pass, and each chart shows its data source.

---

## Task 3 — Broadcast & Diagnosis Completion

**Owner:** _(assign)_

**Goal:** The Broadcast view only shows things that are real, and the per-item diagnosis agent (`POST /api/diagnose`, built and tested, but no UI calls it yet) is usable.

**Steps:**
1. **Per-item diagnosis:**
   - In `backend/api.py` (Task 3 block), add `GET /api/content/history`. It returns `backend/data/content_history.json` (42 items, `HistoricalContentItem` shape) via the existing `diagnostic_recommendation_agent._load_history()`.
   - In the chat panel, add a "اختر محتوى لتشخيصه" dropdown fed by that endpoint.
   - On select, build a `PublishedItemMetrics` body from the item and call `POST /api/diagnose`. Use the same `apiFetch` / `describeError` handling and message rendering the existing AWJ diagnosis prompts already use (`runDiagnosis`, `renderDiagnosisMessage`).
   - Keep the two existing AWJ prompts as they are.
2. **Video player:** there is no real video stream. The play/pause button only toggles an icon. Either remove the fake controls, or clearly label the panel "إعادة بث محاكاة" (simulated replay) and make play/pause animate the timeline cursor over the real signal. Pick one; don't leave controls that do nothing.
3. **Clip approval:** "اعتماد المقطع" has no backend. Keep it as a UI approval, but add "نسخ توقيت المقطع" to copy `start–end + segment_label` to the clipboard so editors can actually use it.
4. Add `backend/tests/test_broadcast_api.py` using FastAPI `TestClient` (see `backend/tests/test_api.py` for the auth/login fixture pattern). Cover:
   - `/api/content/history` requires auth and returns 42 items.
   - `/api/broadcast/detect-clips` returns the 2 seeded spikes.

**Done when:**
- Picking one over-performing and one under-performing item in the dropdown gives different, evidence-cited diagnoses.
- No control in the Broadcast view is a no-op.
- Tests pass.

---

## Task 4 — Security Hardening & QA

**Owner:** _(assign)_

**Goal:** Close the remaining security gaps and catch UI bugs before users do.

**Steps:**
1. **Backend security headers:**
   - Create `backend/security.py` with a small Starlette middleware that adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and `Strict-Transport-Security` (only when `config.IS_PRODUCTION`).
   - Register it in `backend/api.py` (Task 4 block, one `app.add_middleware(...)` line).
   - Add one test asserting the headers are present.
2. **Frontend headers:** add `vercel.json` with the same headers plus a `Content-Security-Policy`. It must allow `connect-src` to the Render API URL and Google Fonts if the app uses them. Verify that the deployed site still loads with no CSP errors in the console.
3. **Remove fake status UI:**
   - App.tsx: "بث مباشر متصل" is always shown, and the search box does nothing. Remove the search box.
   - Sidebar.tsx: "تزامن الوكلاء نشط" is always shown.
   - For the status pills, either drive them from a real `GET /health` check (green when the API responds, grey when it doesn't) or remove them.
4. **Bundle size:** the JS bundle is 619 kB (Vite warns). Lazy-load the three views in App.tsx with `React.lazy` + `Suspense` so Recharts loads only with the Dashboard.
5. **Dependency audit:**
   - Run `npm audit --omit=dev` and `pip install pip-audit && pip-audit -r backend/requirements.txt`.
   - Fix high/critical issues by bumping versions. Coordinate `package.json` changes with Task 1's owner.
6. **QA pass** on the production (or local) build, in Chrome, Safari/Edge and a 390 px-wide mobile viewport:
   - **Login:** wrong password, right password, 6 fast wrong attempts → "محاولات كثيرة".
   - **Session expiry:** delete `sada.token` in DevTools → the next action returns to login.
   - **Error states:** stop the backend → every view shows an Arabic error toast, no blank screen. Remove `GEMINI_API_KEY` → Optimizer and Diagnosis show the "not configured" message.
   - **RTL:** layout and text alignment in all three views.
   - Log every bug as a GitHub issue tagged with the owning task's number (see the ownership table) so the right person fixes it.

**Done when:** headers verified with `curl -I` on both deployments, no fake status indicators remain, the bundle warning is gone, the audit is clean of high/critical issues, and the QA issues are filed.

---

## Shared rules for all 4 tasks

- **Branch per task** (`task-1-deploy`, `task-2-analytics`, …). Open a PR into `main`; CI (from Task 1) must be green before merging.
- **All HTTP calls go through `apiFetch` / `describeError`** in `src/lib/api.ts`. Never hardcode a URL or the `localhost:8000` port, and never call `fetch` directly.
- **All new `/api` routes go on the authenticated `api` router** in `backend/api.py`. Only `/health` and `/api/auth/*` are public.
- **No fake data or no-op controls.** If something can't be backed by real data or a real action before the deadline, remove it or label it clearly as sample/simulated. Shipping a fake number is worse than shipping fewer numbers.
- **Run `pytest backend/tests` and `npm run build` locally** before opening your PR.
- **Flag, don't guess.** If you need a field or endpoint that doesn't exist, raise it with the team instead of inventing a shape in your own file.
