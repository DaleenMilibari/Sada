#!/usr/bin/env python3
"""
AWJ | Sada — X collector for 3 Rahan + 3 SO episodes.

Requires:
    pip install requests
    export X_BEARER_TOKEN="..."
and X API v2 Full Archive Search access.

Outputs:
    AWJ_Sada_X_Posts.csv
    AWJ_Sada_X_Replies.csv
    AWJ_Sada_X_Full.json
"""
import os, csv, json, time, requests

TOKEN = os.environ["X_BEARER_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
SEARCH_URL = "https://api.x.com/2/tweets/search/all"

EPISODES = [
    {"podcast":"رهان","episode_key":"RAHAN_01","title":"نحو فطرة سليمة",
     "query":'from:Medhalpodcast (الهنوف OR الحقيل OR "فطرة سليمة" OR "التحصين ضد الشذوذ")',
     "start":"2023-10-15T00:00:00Z","end":"2023-10-25T00:00:00Z"},
    {"podcast":"رهان","episode_key":"RAHAN_02","title":"هوس القروض",
     "query":'from:Medhalpodcast (نبيل OR المبارك OR "هوس القروض" OR "تقسط ثمن قهوتك")',
     "start":"2023-10-23T00:00:00Z","end":"2023-11-05T00:00:00Z"},
    {"podcast":"رهان","episode_key":"RAHAN_03","title":"سلامة عقلك",
     "query":'from:Medhalpodcast ("مشعل العقيل" OR "سلامة عقلك" OR "صوتك الداخلي")',
     "start":"2023-11-12T00:00:00Z","end":"2023-11-27T00:00:00Z"},
    {"podcast":"SO","episode_key":"SO_01","title":"Dr. Goetz",
     "query":'from:Medhalpodcast (Goetz OR "Dr. Goetz") (#SO_podcast OR SO)',
     "start":"2025-04-20T00:00:00Z","end":"2025-05-10T00:00:00Z"},
    {"podcast":"SO","episode_key":"SO_02","title":"Lidiane De Silva",
     "query":'from:Medhalpodcast (Lidiane OR "Lidiane De Silva") (#SO_podcast OR SO)',
     "start":"2025-04-05T00:00:00Z","end":"2025-04-30T00:00:00Z"},
    {"podcast":"SO","episode_key":"SO_03","title":"Delgado",
     "query":'from:Medhalpodcast (Delgado OR LeonelDelgado) (#SO_podcast OR SO)',
     "start":"2025-02-01T00:00:00Z","end":"2025-02-28T23:59:59Z"},
]

TWEET_FIELDS = "id,text,created_at,author_id,conversation_id,lang,public_metrics,in_reply_to_user_id"

def search(query, start, end):
    params = {
        "query": query,
        "start_time": start,
        "end_time": end,
        "max_results": 100,
        "tweet.fields": TWEET_FIELDS,
        "expansions": "author_id",
        "user.fields": "id,name,username"
    }
    all_rows, users, token = [], {}, None
    while True:
        if token:
            params["next_token"] = token
        r = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(60)
            continue
        r.raise_for_status()
        data = r.json()
        all_rows.extend(data.get("data", []))
        users.update({u["id"]:u for u in data.get("includes", {}).get("users", [])})
        token = data.get("meta", {}).get("next_token")
        if not token:
            break
    return all_rows, users

posts, replies = [], []

for ep in EPISODES:
    tweets, users = search(ep["query"], ep["start"], ep["end"])
    for t in tweets:
        u = users.get(t.get("author_id"), {})
        pm = t.get("public_metrics") or {}
        row = {
            "podcast": ep["podcast"],
            "episode_key": ep["episode_key"],
            "episode_title": ep["title"],
            "tweet_id": t["id"],
            "date": t.get("created_at"),
            "post_text": t.get("text"),
            "likes": pm.get("like_count"),
            "reposts": pm.get("retweet_count"),
            "replies_count": pm.get("reply_count"),
            "quotes": pm.get("quote_count"),
            "views": pm.get("impression_count"),
            "post_url": f"https://x.com/{u.get('username','Medhalpodcast')}/status/{t['id']}"
        }
        posts.append(row)

        reply_query = f"conversation_id:{t['conversation_id']} -from:Medhalpodcast"
        reply_tweets, reply_users = search(reply_query, t["created_at"], ep["end"])
        for rt in reply_tweets:
            if not rt.get("in_reply_to_user_id"):
                continue
            ru = reply_users.get(rt.get("author_id"), {})
            rpm = rt.get("public_metrics") or {}
            replies.append({
                "podcast": ep["podcast"],
                "episode_key": ep["episode_key"],
                "parent_tweet_id": t["id"],
                "reply_id": rt["id"],
                "date": rt.get("created_at"),
                "author_username": ru.get("username"),
                "reply_text": rt.get("text"),
                "likes": rpm.get("like_count"),
                "reposts": rpm.get("retweet_count"),
                "replies_count": rpm.get("reply_count"),
                "quotes": rpm.get("quote_count"),
                "views": rpm.get("impression_count"),
                "reply_url": f"https://x.com/{ru.get('username','i')}/status/{rt['id']}"
            })

def write_csv(path, rows, default_fields):
    fields = list(rows[0].keys()) if rows else default_fields
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

write_csv(
    "AWJ_Sada_X_Posts.csv",
    posts,
    ["podcast","episode_key","episode_title","tweet_id","date","post_text","likes","reposts","replies_count","quotes","views","post_url"]
)
write_csv(
    "AWJ_Sada_X_Replies.csv",
    replies,
    ["podcast","episode_key","parent_tweet_id","reply_id","date","author_username","reply_text","likes","reposts","replies_count","quotes","views","reply_url"]
)

with open("AWJ_Sada_X_Full.json", "w", encoding="utf-8") as f:
    json.dump({"posts":posts,"replies":replies}, f, ensure_ascii=False, indent=2)

print(f"posts={len(posts)} replies={len(replies)}")
