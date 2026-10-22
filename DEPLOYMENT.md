# Sada — Data Sources, API Keys & Deployment

How Sada gets its data, how to create every key, and how to deploy it.

- **Sections 1–7: data and keys.** Key safety, Gemini/OpenAI, Instagram, X, audience comments, TikTok.
- **Sections 8–12: deployment.** Render (API + Postgres), Vercel (frontend), smoke test, configuration, limitations.

All data feeds one database through the **Data Collector agent** (`backend/agents/data_collector_agent.py`), so every other agent sees YouTube videos, X posts and Instagram posts side by side (`platform` field). Nobody copies numbers by hand.

| Part | Host | Config |
|---|---|---|
| FastAPI backend (`backend/`) | Render (web service) | [render.yaml](render.yaml) |
| Postgres database | Render (free Postgres) | [render.yaml](render.yaml) `databases:` |
| React frontend (`src/`) | Vercel | `VITE_API_BASE` env var |

---

## 1. Key safety rules (read first)

- **Never commit a key**, paste it in a group chat, or show it in a screenshot or a screen-share. `backend/.env` is git-ignored: keep keys there.
- **Send keys only to the lead**, privately (direct message or a password manager). The lead puts them into Render's environment variables.
- **If a key leaks, regenerate it right away** (each section says where), then send the new one to the lead.
- Each key below has an owner. Don't create duplicates "just in case": they're harder to track and revoke.

| Key | Who creates it | Where it goes |
|---|---|---|
| `GEMINI_API_KEY` | **Everyone**, their own | own `backend/.env`; the lead's also goes on Render |
| `OPENAI_API_KEY` (optional) | **Lead only** | lead's `backend/.env` + Render. When set, it is the fallback once every Gemini key/model is out of quota |
| `YOUTUBE_API_KEY` | **Lead only** (already done) | lead's `backend/.env` + Render |
| `META_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID` | **One teammate** | sent privately to the lead → Render |
| `X_BEARER_TOKEN` | **Lead only** | lead's `backend/.env` + Render |

---

## 2. Gemini API key (everyone, 5 min)

Needed locally for draft suggestions, the Optimizer, Diagnosis wording, audience themes, topic and comment classification.

1. Go to **[aistudio.google.com](https://aistudio.google.com)** and sign in with a Google account.
2. Click **Get API key** → **Create API key** (pick or create any Google Cloud project).
3. Copy the key into your `backend/.env`:
   ```
   GEMINI_API_KEY=your-key-here
   ```
4. Restart the backend. The Optimizer should now return generated variants instead of a "not configured" message.

`GEMINI_API_KEY` (and `OPENAI_API_KEY`) may hold several comma-separated keys. When a key runs out of quota, the next one is tried, then each `GEMINI_FALLBACK_MODEL`. If `OPENAI_API_KEY` is set, OpenAI (`OPENAI_MODEL`, default `gpt-5-mini`) is tried only after every Gemini key/model is unavailable.

**If it leaks:** delete it in AI Studio → API keys, then create a new one.

---

## 3. Instagram access (one teammate, ≈1 hour)

> **Already in the database without this setup:** 500 posts from 5 SBA accounts (`sbagovsa`, `saudia.sa`, `alekhbariya.tv`, `riyadiyatv`, `sbc_channel`) and their comments, from Apify scraper exports in `backend/data/dataset_instagram-scraper_*.json`. Load them with `python -m backend.instagram_import <file>` (locally, or against Render's database as in section 8). The setup below is for **live** collection every 30 minutes.

Business Discovery lets **our** Instagram business account read the public posts of other **business/creator** accounts, such as SBA's official ones. It's free and needs no app review for our use. Meta's menus get renamed from time to time, so if a label below differs slightly, look for the closest match.

### 3.1 An Instagram professional account linked to a Facebook Page (≈15 min)

You need an Instagram account **we control**. A new one is fine; it doesn't need posts or followers.

1. In the Instagram app: **Settings → Account type and tools → Switch to professional account → Business**.
2. Create a Facebook Page, or use one you manage (any name, e.g. "Sada Hackathon").
3. Link them. On the Facebook Page: **Settings → Linked accounts → Instagram → Connect**, then log in to the Instagram account.

### 3.2 A Meta developer app (≈10 min)

1. Go to **[developers.facebook.com](https://developers.facebook.com)**, log in with the Facebook account that manages the Page, and accept the developer terms.
2. **My Apps → Create App**. Choose the **Other** use case → app type **Business**. Name it e.g. `sada-collector`.
3. In the app dashboard, **add the Instagram product** and pick the **"API setup with Facebook login"** option, the one that uses a Facebook Page.
4. Leave the app in **Development mode**. That's enough, because you are the app's admin.

### 3.3 Generate the token and find our account id (≈15 min)

1. Open the **[Graph API Explorer](https://developers.facebook.com/tools/explorer/)**.
2. Top right: select **your app** under *Meta App*, and **User Token** under *User or Page*.
3. Under *Permissions*, add:
   - `instagram_basic`
   - `pages_show_list`
   - `pages_read_engagement`
   - `business_management`
4. Click **Generate Access Token**, log in, and when asked, **select the Page and the Instagram account from 3.1**.
5. In the query box, run:
   ```
   me/accounts?fields=name,instagram_business_account{id,username}
   ```
   The `instagram_business_account.id` in the result (a long number) is **`INSTAGRAM_BUSINESS_ACCOUNT_ID`**.
6. **Make the token last 60 days.** The Explorer's token expires in about an hour.
   - Copy it into the **[Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/)** → **Debug** → **Extend Access Token** at the bottom.
   - The new long-lived token is **`META_ACCESS_TOKEN`**.
   - Check that the Debugger shows *Expires: in ~60 days*.

### 3.4 Test it and verify the SBA handles (≈20 min)

In the Graph API Explorer, with the long-lived token, run (replace the id):

```
<INSTAGRAM_BUSINESS_ACCOUNT_ID>?fields=business_discovery.username(saudia.sa){username,name,followers_count,media_count}
```

- **Data comes back** → the setup works, and this is a real business account.
- **Error "Invalid user id" or similar** → wrong handle, or not a business account.

Now check the handles already in `SBA_INSTAGRAM_ACCOUNTS`: `sbagovsa`, `saudia.sa`, `alekhbariya.tv`, `riyadiyatv` and `sbc_channel` (their profiles and posts match each channel, from the scrape of 17 Oct). Each must return data from the query above. To add another SBA entity (remember that 5 of our 8 original YouTube handles turned out wrong):
1. Search Instagram for the channel's Arabic name.
2. Accept a handle only if **at least two** of these hold:
   - it has the blue verified badge
   - it's linked from **sba.sa** or from the channel's verified YouTube page
   - its follower count is plausible (thousands to millions)
   - its posts match the channel's programming
3. Run the Business Discovery query above for it. It must return data.

Add every verified handle to `SBA_INSTAGRAM_ACCOUNTS` in [backend/sba_channels.py](backend/sba_channels.py): one per entity, using that entity's `entity_key` (`sba`, `saudiya`, `ekhbariya`, `sbc`, `riyadiya`, `quran_tv`, `sunnah_tv`, `thikrayat`, `quran_radio`). Commit it to `main` and say in the commit message how each one was verified.

### 3.5 Hand over

Send the lead, **privately**:
- `META_ACCESS_TOKEN`: the long-lived token from 3.3
- `INSTAGRAM_BUSINESS_ACCOUNT_ID`: the number from 3.3
- the token's expiry date from the Debugger

The lead adds both to Render. From the next collection run (≤30 min), Instagram posts appear in `GET /api/videos?platform=instagram`, and `GET /api/collector/status` shows `instagram_calls`.

**To test locally first:** put both values in your own `backend/.env` and run:

```bash
python -m backend.agents.data_collector_agent --platform instagram --llm-limit 0
```

**If the token leaks or expires:**
- Repeat 3.3 steps 4–6 for a new token.
- To revoke the old one, remove the app in Facebook **Settings → Apps and websites** (then re-add it), or reset the app secret in the app dashboard.

### 3.6 Alternative: live collection through Apify (optional)

If the Meta setup is blocked, `INSTAGRAM_PROVIDER=apify` collects the accounts in `SBA_INSTAGRAM_ACCOUNTS` through Apify's Instagram Scraper (`backend/agents/apify_instagram_client.py`). It reads any public account and needs no Facebook Page.

**Decide as a team before using it:** it is a scraper, so it breaks Instagram's terms of use and can stop working when Instagram changes its pages. Apify bills per result (about $2.70 per 1,000 on the free plan). Meta's official API stays the default.

1. Create an account at **[apify.com](https://apify.com)**, then **Settings → API & integrations** and copy your **personal API token**. Treat it like any other key (section 1) and send it only to the lead.
2. Put this in `backend/.env`:
   ```
   INSTAGRAM_PROVIDER=apify
   APIFY_API_TOKEN=your-token-here
   ```
3. Check one account first. This costs a few cents at most:
   ```bash
   python -m backend.agents.apify_instagram_client sbagovsa
   ```
4. Then collect: `python -m backend.agents.data_collector_agent --platform instagram --llm-limit 0`

**Spend control.** Each account is fetched at most once per `APIFY_MIN_INTERVAL_MINUTES` (default 360), even though the collector runs every 30 minutes. That throttle lives in memory: the first fetch after every restart or redeploy backfills `COLLECTOR_LOOKBACK_DAYS` again (up to `APIFY_RESULTS_LIMIT_PER_ACCOUNT` posts per account), and later ones re-read `INSTAGRAM_REFRESH_DAYS`. Set a monthly spending limit in Apify Console as a safety net.

Live Apify collection stores posts only, not comments. Comments come from scraper exports: run Apify's Instagram Scraper on its website, download the JSON, and load it with `python -m backend.instagram_import <file>`.

---

## 4. What Instagram data we get (and don't)

| Field | Available | Notes |
|---|---|---|
| Caption, post time, permalink, type (Reel / video / image / carousel) | ✅ | Reels count as `short` |
| Likes | ✅ / null | `null` when the account hides like counts. **Never** stored as 0 |
| Comments | ✅ | |
| Followers, post count (per account) | ✅ | |
| Views, reach, shares, saves | ❌ | Meta only exposes these to the account's owner |

The scraper exports carry the same fields (no views for posts we don't own either) plus each post's latest comments.

Because Instagram has no public views, cross-platform comparisons use **`performance_index`**: each post's main metric divided by its own account's typical value. Views on YouTube, likes + comments on Instagram. Never compare raw YouTube views against Instagram likes. See `repository.analysis_records()`.

**Limits:**
- Business Discovery allows about 200 calls per hour for our token. The collector uses roughly 2 calls per account per run, and only re-reads the last 7 days once an account is backfilled.
- The token lasts 60 days, which is longer than the hackathon.

---

## 5. X (pay-per-use API, lead, ≈15 min)

We read SBA's **public** posts with our own developer account's app-only bearer token. No SBA login or password is needed.

1. Sign in at **console.x.com** with any X account, create a project + app, add a payment card (new accounts get about $20 of free credit) and set a low auto-recharge / spending limit.
2. Copy the app's **Bearer Token** into `backend/.env` (locally) or Render's env vars: `X_BEARER_TOKEN=...`
3. Verify each extra SBA handle on x.com before adding it to `SBA_X_ACCOUNTS` in `backend/sba_channels.py`. Verified so far: `@SBAgovSA`, `@saudiatv`, `@alekhbariyatv`, `@riyadiyatv`.
4. Run once: `python -m backend.agents.data_collector_agent --platform x`

**Cost control (X bills ≈ $0.005 per post returned):**
- Each post is read **once**. Every run first reads the posts newer than the newest one stored, for every account; the rest of the run's budget backfills toward the lookback window, page by page, always for the account with the shortest history. Past the timeline's ~3,200-tweet reach the backfill uses full-archive search (same price per post).
- `X_TOTAL_POST_BUDGET` (6,000 ≈ $30) is a hard stop across all runs, counted from the posts already stored.
- Reposts and replies are excluded. Account ids are looked up once and reused.
- When the project ends, delete `X_BEARER_TOKEN`. The collected data stays in the database.

**What we store:** text, time, link, type (text / image / carousel / video), impressions (as `view_count`), likes, replies (as `comment_count`). Reposts and quotes are not stored. Metrics are as of collection time, since posts are not re-read.

---

## 6. Audience comments (YouTube, X, Instagram)

The collector's audience step (`backend/agents/audience_collector.py`) gathers what people say about SBA posts. Instagram comments come from the scraper exports (`backend/instagram_import.py`). The Audience agent then classifies them with the LLM (sentiment + intent) and groups requests and criticism into themes.

| Source | What is read | Cost |
|---|---|---|
| YouTube | Top comments (up to `AUDIENCE_YT_COMMENTS_PER_VIDEO`, 100) for the `AUDIENCE_YT_VIDEOS_PER_RUN` (3) most-viewed videos per account published 1–7 days ago | 1 quota unit per video |
| X | Up to `X_REPLIES_PER_POST` (20) replies to the `AUDIENCE_X_POSTS_PER_RUN` (10) most-seen posts per account from the last ~7 days | ≈ $0.005 per reply; `X_REPLY_BUDGET` (1,000 ≈ $5) is a hard stop across all runs |
| Instagram | The latest comments (and their replies) on each scraped post | Free (already exported) |

- **Privacy:** only the comment text, time and like count are stored. **No author name, handle or id**, so the analysis is about the audience as a whole, never about individuals.
- Each post's comments are read once.
- Up to `AUDIENCE_LLM_CLASSIFY_PER_RUN` (200) comments are classified per run. Without an LLM key they stay unclassified, and are never counted as neutral.
- Accuracy is measured against blind human labels: teammates label comments in the Audience view's review card (`POST /api/audience/review`), and `GET /api/audience/accuracy` compares them with the agent's labels.
- Follower counts are snapshotted too (YouTube every 6 h, Instagram every run, X daily), so growth can be measured.

---

## 7. TikTok

Not collected: its Research API needs an approval that takes weeks, and its other APIs only cover accounts that log in to our app. SBA's TikTok Studio analytics export is the cleanest alternative.

---

## 8. Backend on Render

Deploy the **backend first**: the frontend needs its URL at build time.

1. Push this repo to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo. Render reads `render.yaml` and creates **both** the `sada-db` Postgres and the `sada-api` web service; `DATABASE_URL` is wired automatically.
3. When prompted, fill the secret env vars:
   - `GEMINI_API_KEY` — Google AI Studio key (comma-separate several to rotate on quota).
   - `OPENAI_API_KEY` — optional; when set, OpenAI is the fallback after Gemini.
   - `YOUTUBE_API_KEY` — Google Cloud key with "YouTube Data API v3" enabled (restrict it to that API).
   - `META_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID` — from the Instagram setup (section 3). Leave them empty to collect YouTube only; you can add them later and redeploy.
   - `X_BEARER_TOKEN` — app-only X token (section 5). Leave it empty to skip X; X alone is enough to start the collector.
   - `SADA_ACCESS_PASSWORD` — the team login password (use a long one; share it out-of-band).
   - `CORS_ORIGINS` — the Vercel URL, e.g. `https://sada.vercel.app` (comma-separate multiple, no trailing slash). You can set a placeholder and update it after section 9.
   - `SADA_SECRET_KEY` is generated automatically.
4. Deploy. Check `https://<your-service>.onrender.com/health` returns `{"status":"ok","auth":true}`.
5. **Load data immediately** instead of waiting for the scheduler to backfill: from your laptop, with the
   database's *External Database URL* (Render → sada-db → Connect):
   ```bash
   DATABASE_URL="<external url>" python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz
   ```
   The seed carries everything already paid for: posts, snapshots, audience comments (incl. X replies), review labels,
   follower counts, saved diagnoses and saved audience themes, so production never re-buys X history or repeats a model call. Then load Instagram the same way:
   ```bash
   for f in backend/data/dataset_instagram-scraper_*.json; do DATABASE_URL="<external url>" python -m backend.instagram_import "$f"; done
   ```
   After that the in-process collector keeps it fresh every 30 minutes.
   Set `X_TOTAL_POST_BUDGET` on Render above the number of X posts in the seed, or X stops immediately (budget counted from stored posts). Check progress at
   `GET /api/collector/status` (logged in).

**Free Postgres expires 30 days after creation.** Before then, export (`python -m backend.db_tools export …` with the external URL) and either upgrade the plan or re-import into a new database.

The service **refuses to start** in production if `SADA_ACCESS_PASSWORD` or `SADA_SECRET_KEY` is missing, so a misconfigured deploy fails loudly instead of running open.

The `starter` plan is recommended: the free plan sleeps after inactivity (first request then takes ~1 min).

## 9. Frontend on Vercel

1. Vercel → **Add New Project** → import the repo. Framework preset: **Vite** (auto-detected).
2. Environment variable: `VITE_API_BASE = https://<your-service>.onrender.com` (no trailing slash).
3. Deploy. Then make sure `CORS_ORIGINS` on Render matches the final Vercel domain (including any custom domain) and redeploy the backend if you changed it.

## 10. Smoke test after deploy

- [ ] Opening the site shows the login screen; wrong password → error, right password → dashboard.
- [ ] Dashboard shows real KPIs, the platform switch (YouTube, X, Instagram), trending videos, the accuracy card, the publishing playbook and the pattern cards with per-account numbers; "تحديث" refreshes the patterns.
- [ ] Optimizer: picking a topic suggests a first draft with the posts it's based on; a draft returns AI-generated variants, a winner, an SBA account and a publish slot.
- [ ] Alerts (التنبيهات والتشخيص): clicking an alert returns a diagnosis with its most likely root cause and links to real posts.
- [ ] Audience (تحليل الجمهور): sentiment, intents, themes, the accuracy card and follower growth load, and Instagram comments appear.
- [ ] `GET /api/collector/status` shows recent successful runs.
- [ ] Logout returns to the login screen.

---

## 11. Configuration reference

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
| `OPENAI_API_KEY` | empty | Optional; comma-separated keys. When set, OpenAI is tried first |
| `OPENAI_MODEL` | `gpt-5-mini` (then `OPENAI_FALLBACK_MODEL`, default none) | Used first whenever `OPENAI_API_KEY` is set; Gemini becomes the fallback |
| `GEMINI_API_KEY` | empty | Comma-separated keys, rotated when one runs out of quota |
| `GEMINI_MODEL` | `gemini-3.8-flash` (falls back to `GEMINI_FALLBACK_MODEL`, default `gemini-3.5-flash,gemini-3.5-flash-lite`) | Model for draft suggestions, variants, diagnosis narratives, audience themes, topics and comment classification |
| `GEMINI_TIMEOUT_SECONDS` | `30` | Max time for one Gemini request |
| `GEMINI_DEADLINE_SECONDS` | `60` | Max time for the whole key/model rotation; past it the API answers 504 (or the agent's evidence-only fallback) |
| `DATABASE_URL` | SQLite file | Set automatically by Render's Postgres |
| `YOUTUBE_API_KEY` | empty | Enables the Data Collector agent |
| `COLLECTOR_SCHEDULE_ENABLED` | `false` (`true` on Render) | Run the collector in-process every `COLLECTOR_INTERVAL_MINUTES` |
| `COLLECTOR_QUOTA_PER_RUN` | `600` (`300` on Render) | YouTube units a run may spend (daily free quota 10,000) |
| `COLLECTOR_LOOKBACK_DAYS` | `180` | Rolling window of uploads tracked per channel; also the history behind patterns and the best-time heatmap |
| `COLLECTOR_MAX_VIDEOS_PER_CHANNEL` | `6000` | Cap per channel inside the window (the busiest channel uploads ~22/day) |
| `COLLECTOR_LLM_CLASSIFY_PER_RUN` | `400` | Posts whose topic the LLM refines per run |
| `META_ACCESS_TOKEN` | empty | Long-lived Meta user token; enables Instagram collection |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | empty | Our own Instagram business account id, used for Business Discovery lookups |
| `META_GRAPH_API_VERSION` | `v23.0` | Graph API version |
| `INSTAGRAM_REFRESH_DAYS` | `7` | Days re-read per run once an account is backfilled |
| `INSTAGRAM_MAX_PAGES_PER_ACCOUNT` | `10` | Pages of posts read per account per run |
| `INSTAGRAM_PROVIDER` | `meta` | `meta` (official Graph API) or `apify` (scraper, section 3.6) |
| `APIFY_API_TOKEN` | empty | Apify token; enables Instagram collection when `INSTAGRAM_PROVIDER=apify` |
| `APIFY_INSTAGRAM_ACTOR` | `apify~instagram-scraper` | Apify actor that is run |
| `APIFY_RESULTS_LIMIT_PER_ACCOUNT` | `300` | Max posts per account per Apify fetch |
| `APIFY_MIN_INTERVAL_MINUTES` | `360` | Each account is fetched at most this often (Apify bills per result) |
| `X_BEARER_TOKEN` | empty | App-only X API token; enables X collection |
| `X_TOTAL_POST_BUDGET` | `6000` | Hard cap on X posts read across all runs (≈ $30) |
| `X_MAX_POSTS_PER_RUN` / `X_MAX_POSTS_PER_ACCOUNT` | `4000` / `600` | Per-run and per-account backfill caps |
| `X_REPLY_BUDGET` | `1000` | Hard cap on X replies read for audience analysis (≈ $5); `0` disables |
| `AUDIENCE_YT_VIDEOS_PER_RUN` | `3` | Videos per account whose comments are read each run (1 unit each) |
| `AUDIENCE_LLM_CLASSIFY_PER_RUN` | `200` | Comments classified by Gemini per run; `0` disables |

## 12. Known limitations

- **Instagram is a snapshot until the Meta token is set up.** The scraper exports are from 16–17 Oct; their stats don't change until live collection starts.
- **The Instagram token expires after 60 days.** Regenerate it per section 3.3 and update `META_ACCESS_TOKEN` on Render. `GET /api/collector/status` shows an "expired" error when this happens.
- **X costs money per read.** The post and reply budgets are hard stops; delete `X_BEARER_TOKEN` when the project ends.
- **Free Postgres expires after 30 days** (see section 8).
- **Single instance only**: the collector schedule runs inside the web process, and rate limits and the pattern store are per-instance.
- **No schema migrations** (tables are created with `create_all`). Changing an existing column needs a manual `ALTER TABLE` or a fresh database + seed import.
- **Single shared password**, not per-user accounts. Fine for an internal team; move to real accounts before opening to external users.
