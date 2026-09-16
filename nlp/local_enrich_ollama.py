"""
FREE local enrichment pipeline using Ollama — no Anthropic API cost.

Runs a small open-source model on your own GPU via Ollama. Zero API
spend, but meaningfully slower and less accurate than Claude, especially
on nuanced fields (is_crisis_flag, commercial_intent). Use this for
large free-tier runs where budget is the hard constraint; use
nlp/batch_pipeline.py (Claude) when accuracy matters more, especially
for the crisis flag.

Setup (one-time):
    1. Install Ollama: https://ollama.com/download (Windows installer)
    2. Pull a model:  ollama pull qwen2.5:7b-instruct
       (7B fits comfortably on a laptop RTX GPU; try qwen2.5:14b-instruct
       if you have 12GB+ VRAM for better accuracy, slower speed)
    3. Ollama runs as a background service automatically after install —
       no separate "start server" step needed on Windows.

Usage:
    python nlp/local_enrich_ollama.py --limit 20000
    (omit --limit to process everything un-enriched — will take a long
    time at full 10-lakh scale; see the honest throughput note below)
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import requests
from bson import ObjectId
from pymongo import UpdateOne

sys.path.append(".")
from mongo.db_guard import get_isolated_db  # noqa: E402
from nlp.taxonomy import (  # noqa: E402
    build_analysis_json_schema,
    taxonomy_reference_text,
    DOSH_ENUM,
    SENTIMENT_ENUM,
    COMMERCIAL_INTENT_ENUM,
    COMMERCIAL_SIGNALS_ENUM,
    RECOMMENDED_SERVICE_ENUM,
)

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b-instruct"  # change to match what you `ollama pull`ed
MODEL_VERSION_TAG = f"ollama-{MODEL}-local"

ANALYSIS_SCHEMA = build_analysis_json_schema()

SYSTEM_PROMPT = f"""You are a classification engine for an Indian astrology \
business's comment-analysis pipeline. You will be given a single public \
comment, possibly in Hindi, Hinglish, or English.

{taxonomy_reference_text()}

Classify strictly per the JSON schema. primary_dosh one of: \
{", ".join(DOSH_ENUM)}. sentiment one of: {", ".join(SENTIMENT_ENUM)}. \
commercial_intent one of: {", ".join(COMMERCIAL_INTENT_ENUM)}. \
commercial_signals only from: {", ".join(COMMERCIAL_SIGNALS_ENUM)}. \
recommended_service one of: {", ".join(RECOMMENDED_SERVICE_ENUM)}.

is_crisis_flag must be true ONLY for explicit suicidal intent — be \
conservative, general sadness is not a crisis flag.

Respond with ONLY a single valid JSON object. No markdown, no preamble."""


def classify_comment(text: str) -> dict | None:
    prompt = (
        f"{SYSTEM_PROMPT}\n\nComment:\n{text}\n\n"
        f"JSON Schema:\n{json.dumps(ANALYSIS_SCHEMA)}\n\nJSON:"
    )
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except (requests.RequestException, json.JSONDecodeError, IndexError) as e:
        print(f"  classify failed: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Max comments to process this run")
    parser.add_argument("--batch-write-size", type=int, default=50)
    args = parser.parse_args()

    db = get_isolated_db()
    comments_col = db.comments

    cursor = comments_col.find({"analysis": None})
    if args.limit:
        cursor = cursor.limit(args.limit)

    docs = list(cursor)
    total = len(docs)
    print(f"Found {total} un-enriched comments. Starting local classification...\n")

    updates = []
    start = time.time()
    for i, doc in enumerate(docs, 1):
        parsed = classify_comment(doc.get("comment_text", ""))
        if parsed is None:
            continue

        parsed["analyzed_at"] = datetime.now(timezone.utc)
        parsed["model_version"] = MODEL_VERSION_TAG
        parsed.setdefault("lead_status", "NEW")

        updates.append(
            UpdateOne({"_id": doc["_id"]}, {"$set": {"analysis": parsed}})
        )

        if len(updates) >= args.batch_write_size:
            comments_col.bulk_write(updates, ordered=False)
            updates = []

        if i % 25 == 0 or i == total:
            elapsed = time.time() - start
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate if rate > 0 else float("inf")
            print(
                f"  {i}/{total} done | {rate:.2f}/sec | "
                f"~{remaining/60:.0f} min remaining this run"
            )

    if updates:
        comments_col.bulk_write(updates, ordered=False)

    print(f"\nDone. Processed {total} comments in {(time.time()-start)/60:.1f} minutes.")


if __name__ == "__main__":
    main()
