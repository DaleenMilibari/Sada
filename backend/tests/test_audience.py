import json
import re
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, inspect, select

from backend import config, db
from backend.agents import audience_agent, audience_collector, llm_client
from backend.agents.x_client import XClient
from backend.agents.youtube_client import YouTubeClient
from backend.api import app

NOW = db.utcnow().replace(microsecond=0)


@pytest.fixture(autouse=True)
def _fresh_cache():
    audience_agent.clear_cache()
    yield
    audience_agent.clear_cache()


@pytest.fixture()
def engine(_isolated_database):
    with _isolated_database.begin() as conn:
        conn.execute(insert(db.channels), [
            {"channel_id": "UC1", "platform": "youtube", "entity_key": "riyadiya", "handle": "@Riyadiyatv", "name_ar": "الرياضية", "subscriber_count": 1000},
            {"channel_id": "100", "platform": "x", "entity_key": "ekhbariya", "handle": "@alekhbariyatv", "name_ar": "الإخبارية", "subscriber_count": 500},
        ])
    return _isolated_database


def add_post(engine, vid, *, platform="youtube", channel="UC1", age=timedelta(days=3), views=1000, comments=5):
    with engine.begin() as conn:
        conn.execute(insert(db.videos), {
            "video_id": vid, "platform": platform, "channel_id": channel, "title": vid, "url": f"https://example.com/{vid}",
            "published_at": NOW - age, "content_type": "video", "topic": "news", "topic_source": "rule",
            "view_count": views, "like_count": 10, "comment_count": comments, "first_seen_at": NOW, "stats_updated_at": NOW,
        })


def add_comment(engine, cid, vid, *, platform="youtube", sentiment=None, intent=None, likes=0, text="تعليق"):
    with engine.begin() as conn:
        conn.execute(insert(db.audience_comments), {
            "comment_id": cid, "platform": platform, "video_id": vid, "text": text, "published_at": NOW - timedelta(days=1),
            "like_count": likes, "collected_at": NOW, "sentiment": sentiment, "intent": intent,
        })


def comment_ids(engine):
    with engine.connect() as conn:
        return set(conn.execute(select(db.audience_comments.c.comment_id)).scalars())


# --- collection ---


def _youtube(handler):
    return YouTubeClient("key", http=httpx.Client(transport=httpx.MockTransport(handler)), backoff_seconds=0)


def test_youtube_comments_for_recent_videos_once_and_without_authors(engine):
    add_post(engine, "recent", views=9000)
    add_post(engine, "old", age=timedelta(days=20))      # outside the 1-7 day window
    add_post(engine, "silent", comments=0)                # nothing to read
    add_post(engine, "closed", views=5000)                # comments disabled
    calls = []

    def handler(request):
        calls.append(request.url.params["videoId"])
        if request.url.params["videoId"] == "closed":
            return httpx.Response(403, json={"error": {"errors": [{"reason": "commentsDisabled"}]}})
        item = {"id": "c1", "snippet": {"topLevelComment": {"snippet": {
            "textDisplay": "برنامج رائع", "publishedAt": "2026-10-15T10:00:00Z", "likeCount": 7,
            "authorDisplayName": "Someone", "authorChannelId": {"value": "UCperson"}}}}}
        return httpx.Response(200, json={"items": [item]})

    stored = audience_collector.collect_youtube(engine, _youtube(handler), NOW)

    assert stored == 1 and sorted(calls) == ["closed", "recent"]
    columns = {c["name"] for c in inspect(engine).get_columns("audience_comments")}
    assert not any("author" in c for c in columns)  # no place to store an identity
    with engine.connect() as conn:
        row = conn.execute(select(db.audience_comments)).one()
    assert row.comment_id == "yt:c1" and row.text == "برنامج رائع" and row.like_count == 7 and row.sentiment is None

    calls.clear()
    audience_collector.collect_youtube(engine, _youtube(handler), NOW)
    assert calls == ["closed"]  # "recent" already has its comments


def _x(handler):
    return XClient("token", http=httpx.Client(transport=httpx.MockTransport(handler)), backoff_seconds=0)


def test_x_replies_capped_by_budget(engine, monkeypatch):
    monkeypatch.setattr(config, "X_REPLY_BUDGET", 25)
    monkeypatch.setattr(config, "X_REPLIES_PER_POST", 20)
    add_post(engine, "111", platform="x", channel="100", age=timedelta(days=2), views=9000)
    add_post(engine, "222", platform="x", channel="100", age=timedelta(days=2), views=5000)
    add_post(engine, "333", platform="x", channel="100", age=timedelta(days=9))  # beyond recent search
    queries = []

    def handler(request):
        q = request.url.params["query"]
        queries.append(q)
        post = re.search(r"conversation_id:(\d+)", q).group(1)
        n = int(request.url.params["max_results"])
        replies = [{"id": f"{post}{i}", "text": "متى الحلقة القادمة؟", "created_at": "2026-10-15T10:00:00.000Z",
                    "public_metrics": {"like_count": 1}} for i in range(n)]
        return httpx.Response(200, json={"data": replies})

    result = audience_collector.collect_x(engine, _x(handler), NOW)

    assert queries[0] == "conversation_id:111 is:reply -from:alekhbariyatv"
    assert result["stored"] == 20 and len(queries) == 1  # 5 left < 10 per call minimum
    assert "budget" in result["errors"][0]
    assert all(c.startswith("x:111") for c in comment_ids(engine))


# --- classification + summary ---


def test_classification_keeps_invalid_labels_unclassified(engine, monkeypatch):
    add_post(engine, "v1")
    for i in range(3):
        add_comment(engine, f"c{i}", "v1")
    answer = {"0": {"s": "positive", "i": "praise"}, "1": {"s": "furious", "i": "praise"}}  # "2" missing
    monkeypatch.setattr(llm_client, "generate_json", lambda prompt: json.dumps(answer))

    assert audience_agent.classify_pending(10) == 1
    with engine.connect() as conn:
        labels = dict(conn.execute(select(db.audience_comments.c.comment_id, db.audience_comments.c.sentiment)).all())
    assert sorted(labels.values(), key=str) == [None, None, "positive"]


def test_summary_shares_need_enough_classified_and_cite_examples(engine):
    add_post(engine, "v1")
    for i in range(6):
        add_comment(engine, f"p{i}", "v1", sentiment="positive", intent="praise", likes=i)
    for i in range(4):
        add_comment(engine, f"n{i}", "v1", sentiment="negative", intent="request", text="نبي حلقة عن الدوري")
    add_comment(engine, "u", "v1")  # unclassified: counted as a comment, never as neutral

    s = audience_agent.build_summary(days=30)

    assert s["totals"]["comments"] == 11 and s["totals"]["classified"] == 10 and s["totals"]["neutral"] == 0
    assert s["totals"]["positive_share"] == 0.6 and s["totals"]["net_sentiment"] == 0.2
    praise = next(i for i in s["intents"] if i["intent"] == "praise")
    assert praise["count"] == 6 and praise["examples"][0]["like_count"] == 5
    assert praise["examples"][0]["url"] == "https://example.com/v1"
    assert s["discussed_posts"][0]["video"]["video_id"] == "v1"

    add_post(engine, "v2", channel="100", platform="x")
    add_comment(engine, "x1", "v2", platform="x", sentiment="positive", intent="praise")
    x_only = audience_agent.build_summary(days=30, platform="x")
    assert x_only["totals"]["comments"] == 1 and x_only["totals"]["positive_share"] is None  # n=1: no share


def test_follower_growth_needs_two_measurements(engine):
    with engine.begin() as conn:
        db.record_followers(conn, [{"channel_id": "UC1", "subscriber_count": 1000}], NOW - timedelta(days=2))
        db.record_followers(conn, [{"channel_id": "UC1", "subscriber_count": 1100}], NOW)
        db.record_followers(conn, [{"channel_id": "100", "subscriber_count": 500}], NOW)

    growth = {g["entity_key"]: g for g in audience_agent.build_summary(days=30)["follower_growth"]}

    assert growth["riyadiya"]["change"] == 100 and growth["riyadiya"]["change_pct"] == 0.1
    assert growth["ekhbariya"]["change"] is None  # one point: unknown, not zero


def test_endpoint_contract(engine, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    add_post(engine, "v1")
    add_comment(engine, "c1", "v1", sentiment="neutral", intent="question")
    with TestClient(app) as client:
        res = client.get("/api/audience/summary?days=30&platform=youtube")
        assert res.status_code == 200
        assert set(res.json()) >= {"totals", "by_channel", "intents", "discussed_posts", "follower_growth"}
        assert client.get("/api/audience/summary?platform=tiktok").status_code == 422


def test_reply_candidates_are_shared_fairly_between_accounts(engine, monkeypatch):
    with engine.begin() as conn:
        conn.execute(insert(db.channels), {"channel_id": "200", "platform": "x", "entity_key": "riyadiya", "handle": "@riyadiyatv", "name_ar": "الرياضية", "subscriber_count": 1})
    for i in range(3):
        add_post(engine, f"10{i}", platform="x", channel="100", age=timedelta(days=2), views=100_000 + i)  # big account
    add_post(engine, "201", platform="x", channel="200", age=timedelta(days=2), views=50)               # small account

    picked = audience_collector._candidates(engine, "x", NOW, NOW - timedelta(days=6), per_account=2)

    assert [p["video_id"] for p in picked] == ["102", "201", "101"]  # best of each account first


def test_mentions_and_links_are_stripped_and_empty_replies_dropped(engine, monkeypatch):
    add_post(engine, "111", platform="x", channel="100", age=timedelta(days=2))
    texts = ["@alekhbariyatv @someone_1 الله يحفظ بلادنا 🇸🇦", "@alekhbariyatv https://t.co/abc", "شكراً @user.name على المتابعة"]

    def handler(request):
        return httpx.Response(200, json={"data": [
            {"id": str(i), "text": t, "created_at": "2026-10-15T10:00:00.000Z"} for i, t in enumerate(texts)]})

    assert audience_collector.collect_x(engine, _x(handler), NOW)["stored"] == 2
    with engine.connect() as conn:
        stored = sorted(conn.execute(select(db.audience_comments.c.text)).scalars())
    assert stored == ["الله يحفظ بلادنا 🇸🇦", "شكراً على المتابعة"]


def test_reactions_to_the_news_are_neutral_toward_sba(engine, monkeypatch):
    add_post(engine, "v1")
    add_comment(engine, "c0", "v1", text="الله ينتقم من المعتدين")
    add_comment(engine, "c1", "v1", text="تغطية ضعيفة جداً")
    answer = {"0": {"s": "negative", "i": "reaction"}, "1": {"s": "negative", "i": "criticism"}}
    monkeypatch.setattr(llm_client, "generate_json", lambda prompt: json.dumps(answer))

    audience_agent.classify_pending(10)

    with engine.connect() as conn:
        labels = dict(conn.execute(select(db.audience_comments.c.comment_id, db.audience_comments.c.sentiment)).all())
    assert labels == {"c0": "neutral", "c1": "negative"}  # anger at the event is not criticism of SBA


# --- blind human review + measured accuracy ---


def test_review_queue_is_blind_and_skips_labeled(engine):
    add_post(engine, "v1")
    add_comment(engine, "a", "v1", sentiment="positive", intent="praise")
    add_comment(engine, "b", "v1", sentiment="negative", intent="criticism")
    add_comment(engine, "u", "v1")  # not classified by the agent yet: nothing to compare against

    queue = audience_agent.review_queue(10)
    assert {q["comment_id"] for q in queue} == {"a", "b"}
    assert all("sentiment" not in q and "intent" not in q for q in queue)  # no anchoring on the model

    assert audience_agent.save_label("a", "positive", "praise")
    assert {q["comment_id"] for q in audience_agent.review_queue(10)} == {"b"}
    assert not audience_agent.save_label("missing", "positive", "praise")


def test_accuracy_against_human_labels(engine):
    add_post(engine, "v1")
    model = [("positive", "praise")] * 6 + [("negative", "criticism")] * 3 + [("neutral", "reaction")]
    human = [("positive", "praise")] * 5 + [("negative", "criticism")] + [("negative", "criticism")] * 3 + [("negative", "reaction")]
    for i, ((ms, mi), (hs, hi)) in enumerate(zip(model, human)):
        add_comment(engine, f"c{i}", "v1", sentiment=ms, intent=mi)
        audience_agent.save_label(f"c{i}", hs, hi)

    acc = audience_agent.accuracy()

    assert acc["n"] == 10 and acc["preliminary"] is True and acc["pending"] == 0
    # human "negative + reaction" is stored as neutral (same rule as the agent) -> it matches
    assert acc["sentiment"]["accuracy"] == 0.9 and acc["intent"]["accuracy"] == 0.9
    praise = next(c for c in acc["intent"]["per_class"] if c["label"] == "praise")
    assert praise["precision"] == round(5 / 6, 3) and praise["recall"] == 1.0
    assert 0 < acc["sentiment"]["kappa"] < 1


def test_review_endpoints(engine, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    add_post(engine, "v1")
    add_comment(engine, "a", "v1", sentiment="positive", intent="praise")
    with TestClient(app) as client:
        item = client.get("/api/audience/review/next").json()[0]
        assert item["comment_id"] == "a" and "sentiment" not in item
        assert client.post("/api/audience/review", json={"comment_id": "a", "sentiment": "positive", "intent": "praise"}).json() == {"saved": True}
        assert client.post("/api/audience/review", json={"comment_id": "a", "sentiment": "angry", "intent": "praise"}).status_code == 422
        body = client.get("/api/audience/accuracy").json()
        assert body["n"] == 1 and body["sentiment"]["accuracy"] == 1.0


def test_themes_are_validated_against_real_comments(engine, monkeypatch):
    add_post(engine, "v1")
    for i in range(3):
        add_comment(engine, f"r{i}", "v1", sentiment="neutral", intent="request", likes=10 - i, text=f"نبي برامج قديمة {i}")
    add_comment(engine, "c0", "v1", sentiment="negative", intent="criticism", likes=1, text="الصوت ضعيف")
    add_comment(engine, "p0", "v1", sentiment="positive", intent="praise", text="رائع")  # not sent to the model
    answer = {"themes": [
        {"title": "برامج أرشيفية", "kind": "request", "recommendation": "أعد بث البرامج القديمة", "topic": "entertainment",
         "members": [0, 1, 2, 99, 1]},                         # 99 doesn't exist, 1 is repeated
        {"title": "جودة الصوت", "kind": "criticism", "recommendation": "حسّن الصوت", "topic": "other", "members": [3]},  # 1 comment: too thin
        {"title": "مخترع", "kind": "praise", "recommendation": "-", "topic": "news", "members": [0, 3]},  # wrong kind
    ]}
    prompts = []
    monkeypatch.setattr(llm_client, "generate_json", lambda p: prompts.append(p) or json.dumps(answer))

    result = audience_agent.build_themes(days=30)

    assert "رائع" not in prompts[0]
    assert result["status"] == "ok" and len(result["themes"]) == 1
    t = result["themes"][0]
    assert t["count"] == 3 and t["likes"] == 27 and t["main_entity_key"] == "riyadiya"
    assert t["examples"][0]["url"] == "https://example.com/v1"


def test_diagnosis_includes_what_the_posts_audience_said(engine):
    from backend.agents import diagnostic_recommendation_agent as diag

    add_post(engine, "v1")
    for i in range(3):
        add_comment(engine, f"c{i}", "v1", sentiment="negative", intent="criticism")
    for i in range(3):
        add_comment(engine, f"r{i}", "v1", sentiment="neutral", intent="reaction")
    post = {"video_id": "v1", "title": "v1", "url": "https://example.com/v1"}

    factor = diag._audience_factor(post, 0.8)

    assert "6 رداً" in factor["reason"] and "3 انتقاداً" in factor["reason"]
    assert factor["evidence_url_or_ref"] == "https://example.com/v1" and factor["recommendation"]
    add_post(engine, "v2")
    assert diag._audience_factor({"video_id": "v2", "title": "", "url": ""}, 0.8) is None  # too few replies: no claim


def test_theme_members_given_as_strings_still_count(engine, monkeypatch):
    add_post(engine, "v1")
    for i in range(3):
        add_comment(engine, f"r{i}", "v1", sentiment="neutral", intent="request", likes=10 - i, text=f"نبي برامج قديمة {i}")
    answer = {"themes": [{"title": "برامج أرشيفية", "kind": "request", "recommendation": "أعد بثها", "topic": "other",
                          "members": ["0", "1", "2", "x"]}]}
    monkeypatch.setattr(llm_client, "generate_json", lambda p: json.dumps(answer))
    result = audience_agent.build_themes(days=30)
    assert [t["count"] for t in result["themes"]] == [3]


def test_classification_stops_once_every_key_is_out_of_quota(engine, monkeypatch):
    add_post(engine, "v1")
    for i in range(3 * audience_agent.BATCH_SIZE):
        add_comment(engine, f"c{i}", "v1")
    calls = []

    def exhausted(prompt):
        calls.append(prompt)
        raise llm_client.QuotaExhaustedError("all keys out")

    monkeypatch.setattr(llm_client, "generate_json", exhausted)
    assert audience_agent.classify_pending(10_000) == 0
    assert len(calls) == 1  # the remaining batches wait for the next run
