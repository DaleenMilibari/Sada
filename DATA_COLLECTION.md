# Data sources & API keys

Sada collects **real SBA data automatically** from two platforms. Nobody copies numbers by hand.

| Platform | How | Status |
|---|---|---|
| **YouTube**: 9 official SBA channels | YouTube Data API v3 (free) | ✅ Live: 2,901 videos, refreshed every 30 min |
| **Instagram**: official SBA accounts | Meta Graph API "Business Discovery" (free) | 🟡 Code ready; needs the Meta setup in section 3 (≈1 h, one person) |
| X, TikTok | Not collected | See section 5 |

Both feed the same database through the **Data Collector agent** (`backend/agents/data_collector_agent.py`), so every other agent sees YouTube videos and Instagram posts side by side (`platform` field).

---

## 1. Key safety rules (read first)

- **Never commit a key**, paste it in a group chat, or show it in a screenshot or a screen-share. `backend/.env` is git-ignored: keep keys there.
- **Send keys only to the lead**, privately (direct message or a password manager). The lead puts them into Render's environment variables.
- **If a key leaks, regenerate it right away** (each section says where), then send the new one to the lead.
- Each key below has an owner. Don't create duplicates "just in case": they're harder to track and revoke.

| Key | Who creates it | Where it goes |
|---|---|---|
| `GEMINI_API_KEY` | **Everyone**, their own | own `backend/.env`; the lead's also goes on Render |
| `YOUTUBE_API_KEY` | **Lead only** (already done) | lead's `backend/.env` + Render |
| `META_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID` | **One teammate** (assigned in [team.md](team.md)) | sent privately to the lead → Render |

---

## 2. Gemini API key (everyone, 5 min)

Needed locally for the Optimizer, Diagnosis and topic classification.

1. Go to **[aistudio.google.com](https://aistudio.google.com)** and sign in with a Google account.
2. Click **Get API key** → **Create API key** (pick or create any Google Cloud project).
3. Copy the key into your `backend/.env`:
   ```
   GEMINI_API_KEY=your-key-here
   ```
4. Restart the backend. The Optimizer should now return generated variants instead of a "not configured" message.

**If it leaks:** delete it in AI Studio → API keys, then create a new one.

---

## 3. Instagram access (one teammate, ≈1 hour)

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
<INSTAGRAM_BUSINESS_ACCOUNT_ID>?fields=business_discovery.username(saudiyatv){username,name,followers_count,media_count}
```

- **Data comes back** → the setup works, and this is a real business account.
- **Error "Invalid user id" or similar** → wrong handle, or not a business account.

Now find SBA's official Instagram handles. Only `saudiyatv` came from our source list, and remember that 5 of our 8 YouTube handles turned out wrong. For each SBA entity:
1. Search Instagram for the channel's Arabic name.
2. Accept a handle only if **at least two** of these hold:
   - it has the blue verified badge
   - it's linked from **sba.sa** or from the channel's verified YouTube page
   - its follower count is plausible (thousands to millions)
   - its posts match the channel's programming
3. Run the Business Discovery query above for it. It must return data.

Add every verified handle to `SBA_INSTAGRAM_ACCOUNTS` in [backend/sba_channels.py](backend/sba_channels.py): one per entity, using that entity's `entity_key` (`sba`, `saudiya`, `ekhbariya`, `sbc`, `riyadiya`, `quran_tv`, `sunnah_tv`, `thikrayat`, `quran_radio`). Open a PR titled `data: verified Instagram accounts`, and say in the description how each one was verified.

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

---

## 4. What Instagram data we get (and don't)

| Field | Available | Notes |
|---|---|---|
| Caption, post time, permalink, type (Reel / video / image / carousel) | ✅ | Reels count as `short` |
| Likes | ✅ / null | `null` when the account hides like counts. **Never** stored as 0 |
| Comments | ✅ | |
| Followers, post count (per account) | ✅ | |
| Views, reach, shares, saves | ❌ | Meta only exposes these to the account's owner |

Because Instagram has no public views, cross-platform comparisons use **`performance_index`**: each post's main metric divided by its own account's typical value. Views on YouTube, likes + comments on Instagram. Never compare raw YouTube views against Instagram likes. See `repository.analysis_records()`.

**Limits:**
- Business Discovery allows about 200 calls per hour for our token. The collector uses roughly 2 calls per account per run, and only re-reads the last 7 days once an account is backfilled.
- The token lasts 60 days, which is longer than the hackathon.

---

## 5. X and TikTok

Not collected in this version:

- **X:** reading posts through the API needs a **paid** subscription, and the free tier can't read.
- **TikTok:** its Research API needs an approval that takes weeks, and its other APIs only cover accounts that log in to our app.

Even with SBA's permission to use the data, these are the only official routes, and the open-source scrapers that skip them are fragile and break the platforms' terms. If time or budget allows later, the cleanest options are:

- **Analytics exports from SBA's social team.** X Analytics and TikTok Studio both export per-post data, which is richer than any public API: reach and audience details.
- **A paid X API key.** A collector would then be a new client next to `backend/agents/youtube_client.py`, storing into the same tables with `platform = "x"`.

For the pitch: *"Sada collects YouTube and Instagram automatically through official APIs; X and TikTok plug into the same pipeline once API access is in place."*
