#!/usr/bin/env python3
"""
Load merged transcript chunks into a Chroma Cloud collection.

Reads CHROMA_API_KEY from the environment (never hardcode it).
Tenant and database are your sba-hackathon project's values below.

Usage:
    python load_to_chroma.py all_chunks_merged.json

Requires:
    pip install chromadb sentence-transformers python-dotenv

Setup:
    1. Create a file named ".env" in this same folder (see .env.example)
    2. Put your Chroma API key in it: CHROMA_API_KEY=your-key-here
    3. Never commit .env to GitHub — add it to .gitignore
"""

import argparse
import json
import os
import sys

import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

load_dotenv()  # reads .env in the current directory and loads it into os.environ

TENANT = "6c33f474-b59c-409a-9722-dbea8c67086a"
DATABASE = "sba-hackathon"
COLLECTION_NAME = "podcast_chunks"

BATCH_SIZE = 100  # Chroma upserts are batched to stay well under API limits


def get_embedding_function():
    """
    Free, local, multilingual embedding model — no API key, no cost.
    Runs on your own machine via sentence-transformers. Handles Arabic
    and English well in the same shared vector space.
    First run will download the model (~1GB) once; cached after that.
    """
    print("Using local multilingual-e5-base embedding model (free, no API key).")
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="intfloat/multilingual-e5-base"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chunks_json", help="Path to the merged chunks JSON file")
    args = parser.parse_args()

    chroma_key = os.environ.get("CHROMA_API_KEY")
    if not chroma_key:
        print("ERROR: CHROMA_API_KEY not found.", file=sys.stderr)
        print("Create a .env file in this folder with: CHROMA_API_KEY=your-key-here", file=sys.stderr)
        sys.exit(1)

    with open(args.chunks_json, encoding="utf-8") as f:
        chunks = json.load(f)

    if not chunks:
        print("ERROR: no chunks found in input file.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(chunks)} chunks from {args.chunks_json}")

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

    ids = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):
        chunk_id = f"{chunk['podcast']}::{chunk['episode']}::{chunk['start_seconds']}::{i}"
        ids.append(chunk_id)
        documents.append(chunk["text"])
        metadatas.append({
            "podcast": chunk["podcast"],
            "episode": chunk["episode"],
            "youtube_url": chunk["youtube_url"],
            "clip_url": chunk["clip_url"],
            "start_time": chunk["start_time"],
            "end_time": chunk["end_time"],
            "start_seconds": chunk["start_seconds"],
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
