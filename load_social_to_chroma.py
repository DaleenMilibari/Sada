#!/usr/bin/env python3
"""
Load the AWJ_Sada social/audience dataset (episode metadata, X posts,
audience signals) into a Chroma Cloud collection named 'social_reactions'.

This is a SEPARATE collection from 'podcast_chunks' — same database,
same embedding model, different content type (audience/engagement data
rather than transcript text).

Usage:
    python load_social_to_chroma.py AWJ_Sada_Data.csv

Requires:
    pip install chromadb sentence-transformers python-dotenv
    .env file with CHROMA_API_KEY=... (see .env.example)
"""

import argparse
import csv
import sys

import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
import os

load_dotenv()

TENANT = "6c33f474-b59c-409a-9722-dbea8c67086a"
DATABASE = "sba-hackathon"
COLLECTION_NAME = "social_reactions"

BATCH_SIZE = 100


def get_embedding_function():
    """Same model used for podcast_chunks — must match for consistent retrieval."""
    print("Using local multilingual-e5-base embedding model (free, no API key).")
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="intfloat/multilingual-e5-base"
    )


def row_to_document_text(row: dict) -> str:
    """
    Build the actual text that gets embedded. For episode_metadata and
    audience_signal rows there may be no post_text/x-post body, so fall
    back to whatever text field is populated, plus topic as context.
    """
    parts = []
    if row.get("text"):
        parts.append(row["text"])
    if row.get("reply_text"):
        parts.append(row["reply_text"])
    if not parts:
        # audience_signal / episode_metadata rows with no body text —
        # use episode title + topic so the row still has something
        # meaningful to embed and retrieve on.
        if row.get("episode_title"):
            parts.append(row["episode_title"])
    if row.get("topic"):
        parts.append(f"(topic: {row['topic']})")
    return " — ".join(p for p in parts if p) or "(no text content)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Path to AWJ_Sada_Data.csv")
    args = parser.parse_args()

    chroma_key = os.environ.get("CHROMA_API_KEY")
    if not chroma_key:
        print("ERROR: CHROMA_API_KEY not found.", file=sys.stderr)
        print("Create a .env file in this folder with: CHROMA_API_KEY=your-key-here", file=sys.stderr)
        sys.exit(1)

    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} rows from {args.csv_path}")

    client = chromadb.CloudClient(
        api_key=chroma_key,
        tenant=TENANT,
        database=DATABASE,
    )

    embed_fn = get_embedding_function()

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
    )

    ids, documents, metadatas = [], [], []

    for row in rows:
        doc_text = row_to_document_text(row)
        ids.append(row["record_id"])
        documents.append(doc_text)
        metadatas.append({
            "record_type": row.get("record_type", ""),
            "podcast": row.get("podcast", ""),
            "episode_key": row.get("episode_key", ""),
            "episode_title": row.get("episode_title", ""),
            "platform": row.get("platform", ""),
            "source_account": row.get("source_account", ""),
            "relationship": row.get("relationship", ""),
            "likes": row.get("likes", ""),
            "reposts": row.get("reposts", ""),
            "views": row.get("views", ""),
            "replies_count": row.get("replies_count", ""),
            "date": row.get("date", ""),
            "topic": row.get("topic", ""),
            "source_url": row.get("source_url", ""),
            "youtube_url": row.get("youtube_url", ""),
            "verification_level": row.get("verification_level", ""),
            "retrieval_status": row.get("retrieval_status", ""),
            "notes": row.get("notes", ""),
        })

    total = len(ids)
    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        collection.upsert(
            ids=ids[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )
        print(f"Upserted {end}/{total}")

    print(f"Done. Collection '{COLLECTION_NAME}' now has {collection.count()} items.")


if __name__ == "__main__":
    main()
