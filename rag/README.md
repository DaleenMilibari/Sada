# Awj — Podcast RAG Knowledge Base

Part of the **Awj** project (SBA hackathon — audience-engagement analytics
across podcast episodes). This document describes the vector database that
powers retrieval for the agent.

## Pipeline overview (how this data was built)

1. **Source**: 6 podcast episodes across two shows — بودكاست رهان (Arabic, 3
   episodes) and "SO" (English, 3 episodes)
2. **Transcription**: UniScribe (uniscribe.co), exported as CSV with
   per-segment timestamps (`Start Time, End Time, Text`)
3. **Chunking**: `chunk_transcript.py` converts each episode's CSV into JSON
   chunks, attaching podcast name, episode title, YouTube URL, and a
   timestamp-linked `clip_url` to every chunk
4. **Embedding + storage**: `load_to_chroma.py` embeds every chunk with a
   free local multilingual model and upserts into **Chroma Cloud**

## Project / database identity

| | |
|---|---|
| Vector DB provider | Chroma Cloud (trychroma.com) |
| Chroma org | `rafa21alshareef` |
| Database name | `sba-hackathon` |
| Tenant ID | `6c33f474-b59c-409a-9722-dbea8c67086a` |
| Collection (transcripts) | `podcast_chunks` — 2,012 records, live |
| Collection (social reactions) | `social_reactions` — 13 records, live |

## Setup for any team member

```bash
pip install chromadb sentence-transformers python-dotenv
```

Copy `.env.example` to `.env` and fill in a real `CHROMA_API_KEY`
(get one from whoever manages the Chroma org, or generate your own under
the database's API keys tab at trychroma.com if you have access). Never
commit the real `.env` — it's already covered by `.gitignore`.

## Connection

```python
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
import os

load_dotenv()

client = chromadb.CloudClient(
    api_key=os.environ["CHROMA_API_KEY"],
    tenant="6c33f474-b59c-409a-9722-dbea8c67086a",
    database="sba-hackathon",
)
```

Get your own `CHROMA_API_KEY` from whoever manages the project, or generate
one at trychroma.com under this database's API keys tab. Put it in a local
`.env` file (see `.env.example`) — never hardcode it or commit it.

## IMPORTANT: Embedding model must match

All existing data was embedded with:

```
intfloat/multilingual-e5-base
```

via `sentence-transformers`. Any query you run **must use this exact same
model** to generate the query vector, or similarity search will return
garbage — mismatched embedding models produce vectors in different spaces
that aren't comparable.

```python
embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="intfloat/multilingual-e5-base"
)
```

## Collection 1: `podcast_chunks`

Transcript chunks from 6 podcast episodes across two shows (بودكاست رهان —
Arabic, and "SO" — English). Each record is ~20-30 seconds of spoken
transcript with timestamp-linked metadata.

**Status: live, 2,012 records loaded.**

### Metadata fields per chunk

| Field | Type | Description |
|---|---|---|
| `podcast` | string | Show name, e.g. `"بودكاست رهان"` or `"SO"` |
| `episode` | string | Episode title |
| `youtube_url` | string | Base YouTube URL for the episode |
| `clip_url` | string | Deep link with timestamp, e.g. `...&t=252s` — use this when suggesting a clip to watch |
| `start_time` / `end_time` | string | `HH:MM:SS.mmm` format |
| `start_seconds` | int | Same as start_time, in seconds — used to build clip_url |

### Example query

```python
collection = client.get_collection(
    name="podcast_chunks",
    embedding_function=embed_fn,
)

results = collection.query(
    query_texts=["ما هي أسباب التنمر عند الأطفال؟"],
    n_results=5,
)
```

Each result includes the matched text plus its metadata — use `clip_url`
directly when the agent wants to point the user to the exact moment.

## Collection 2: `social_reactions`

Holds verified public engagement/audience data for both podcasts — episode
metadata (views/likes from YouTube/Apple), a small number of verified X
posts, and show-level audience reviews.

**Status: live, 13 records loaded** (5 from بودكاست رهان, 8 from SO).

**Honest scope note:** this is *not* a large-scale reaction/sentiment
dataset. Live scraping of X, Instagram, and TikTok reaction data at volume
requires paid API access (see `AWJ_Sada_X_Collector.py` for the X API v2
full-archive script, which needs a bearer token to run) or extensive manual
collection — neither was feasible in the hackathon timeframe. What's loaded
here is a small set of **verified, real** public metrics and posts, each
tagged with its actual confidence level:

- `VERIFIED_PUBLIC` — directly confirmed public data (YouTube/Apple view
  and like counts, official episode metadata)
- `VERIFIED_INDEXED` — recovered from a historic search index; engagement
  counts confirmed but original post body not recoverable
- `PUBLIC_MIRROR` — recovered from a third-party mirror site, not X
  directly; lower confidence, partial data only

When the agent reasons over this collection, it should treat
`verification_level` as a trust signal — e.g. weight `VERIFIED_PUBLIC` data
more heavily than `PUBLIC_MIRROR` data, and avoid presenting the latter as
definitive engagement figures.

### Metadata fields per record

| Field | Description |
|---|---|
| `record_type` | `episode_metadata`, `x_post`, or `audience_signal` |
| `podcast` | `"رهان"` or `"SO"` |
| `episode_key` / `episode_title` | Episode identifiers |
| `platform` | Where the data came from (YouTube, X, Apple Podcasts) |
| `source_account` | Account that posted it |
| `likes` / `reposts` / `views` / `replies_count` | Engagement numbers, where recoverable |
| `date` | Post/episode date, where known |
| `topic` | Episode theme/category |
| `source_url` / `youtube_url` | Links back to the original source and episode |
| `verification_level` | Trust tier — see above |
| `retrieval_status` | How the data was obtained |
| `notes` | Source-specific caveats |

### Proposed metadata fields

| Field | Type | Description |
|---|---|---|
| `platform` | string | `"X"` or `"Instagram"` |
| `podcast` | string | Same show-name convention as podcast_chunks |
| `episode` | string | Same episode-title convention as podcast_chunks |
| `post_text` | string | The tweet/comment/caption text |
| `engagement` | object | `{likes, replies, shares}` |
| `posted_at` | string | ISO date `YYYY-MM-DD` |
| `related_clip_url` | string | If identifiable, which transcript moment this reaction is about |

Keeping this as a **separate collection** (not merged into `podcast_chunks`)
because the two serve different retrieval purposes: transcript chunks
answer "what was said," social reactions answer "how did people respond."
The agent can query one or both depending on the task — e.g. a "suggest a
viral clip" task likely needs both: a compelling transcript moment cross-
referenced against what topics actually got engagement.

## For the agent's system prompt

When building the agent's instructions, make clear:
- It has access to two knowledge sources (once collection 2 is built) and
  should pick the relevant one(s) per task, not always query both
- `clip_url` (not `youtube_url` alone) should be used whenever recommending
  a specific moment — it's what makes the timestamp jump-to work
- Results are unstructured text chunks, not full episodes — for "what's
  this episode about" style questions, multiple chunks may need to be
  retrieved and synthesized, not just the top 1 result
