"""
FREE local enrichment pipeline using Ollama — optimized for sustained
multi-day throughput on a single laptop GPU. No Anthropic API cost.

Three throughput optimizations vs. a naive JSON-output version:
  1. Small model (3B default) instead of 7B — 2-3x faster generation.
  2. Compact pipe-delimited output instead of full JSON — the model
     writes ~20 characters instead of ~150, which is most of the
     per-request latency on a small local model.
  3. Concurrent requests (--workers, default 3) — Ollama queues and
     interleaves requests on the GPU, so a few in flight at once beats
     one-at-a-time, though it won't scale linearly past your VRAM.

Honest throughput note: whether 10 lakh (1M) comments finishes in your
target window depends entirely on your GPU. Run --limit 500 first,
check the printed rate, and multiply out the real ETA before committing
a laptop to a multi-day unattended run. This script IS resumable —
if the laptop sleeps, restarts, or you stop it, re-running the same
command picks up exactly where it left off (it only ever queries
comments still missing `analysis`).

For an unattended multi-day run on Windows:
  - Settings > System > Power & battery > Screen and sleep > set both
    "when plugged in" timers to Never.
  - Keep the laptop plugged in and on a surface that won't overheat it.

Setup (one-time):
    1. Install Ollama: https://ollama.com/download
    2. ollama pull qwen2.5:3b-instruct
       (try qwen2.5:1.5b-instruct if this is still too slow after
       testing — faster but noticeably less accurate)

Usage:
    # ALWAYS test throughput first on a small slice:
    python nlp/local_enrich_ollama.py --limit 500

    # then the real run, sized to your measured rate:
    python nlp/local_enrich_ollama.py --workers 4
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

import requests
from pymongo import UpdateOne

sys.path.append(".")
from mongo.db_guard import get_isolated_db  # noqa: E402
from nlp.taxonomy import (  # noqa: E402
    PROBLEM_CODES,
    DOSH_ENUM,
    SENTIMENT_ENUM,
    COMMERCIAL_INTENT_ENUM,
    COMMERCIAL_SIGNALS_ENUM,
    RECOMMENDED_SERVICE_ENUM,
    taxonomy_reference_text,
)

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:3b-instruct"
MODEL_VERSION_TAG = f"ollama-{MODEL}-local-compact"

# Index maps derived from the shared taxonomy module — stays in sync
# automatically if nlp/taxonomy.py ever changes.
DOSH_BY_INDEX = {i: v for i, v in enumerate(DOSH_ENUM)}
SENTIMENT_BY_INDEX = {i: v for i, v in enumerate(SENTIMENT_ENUM)}
INTENT_BY_INDEX = {i: v for i, v in enumerate(COMMERCIAL_INTENT_ENUM)}
SIGNAL_BY_INDEX = {i + 1: v for i, v in enumerate(COMMERCIAL_SIGNALS_ENUM)}  # 1-indexed, 0=none
SERVICE_BY_INDEX = {i: v for i, v in enumerate(RECOMMENDED_SERVICE_ENUM)}

SYSTEM_PROMPT = f"""You classify Indian astrology YouTube comments. \
{taxonomy_reference_text()}

Reply with ONLY one line in this exact compact format, nothing else — \
no labels, no explanation, no restating the format, just 9 numbers/letters \
separated by pipes:
P|S|D|E|U|I|G|R|C

P = primary problem number (1-50 from the list above)
S = secondary problem number, or 0 if none
D = dosh index: {", ".join(f"{i}={v}" for i, v in DOSH_BY_INDEX.items())}
E = sentiment index: {", ".join(f"{i}={v}" for i, v in SENTIMENT_BY_INDEX.items())}
U = urgency 1-10
I = intent index: {", ".join(f"{i}={v}" for i, v in INTENT_BY_INDEX.items())}
G = signal index (1-4, see below), or 0 if none: {", ".join(f"{i}={v}" for i, v in SIGNAL_BY_INDEX.items())}
R = service index: {", ".join(f"{i}={v}" for i, v in SERVICE_BY_INDEX.items())}
C = crisis flag: Y only for explicit suicidal intent, else N

Your entire reply must be exactly one line like this example, nothing else:
9|0|9|4|3|3|0|5|N"""


def parse_compact(line: str) -> dict | None:
    try:
        # Strip anything that isn't part of the 9-field pipe format —
        # small models sometimes prepend "Reply:" or similar despite
        # instructions not to.
        cleaned = line.strip()
        parts = cleaned.split("|")
        if len(parts) != 9:
            return None

        def to_int(s: str) -> int:
            digits = "".join(ch for ch in s if ch.isdigit() or ch == "-")
            return int(digits) if digits else 0

        p, s, d, e, u, i, g, r, c = parts
        p_i, s_i, d_i, e_i, u_i, i_i, g_i, r_i = (
            to_int(p), to_int(s), to_int(d), to_int(e),
            to_int(u), to_int(i), to_int(g), to_int(r),
        )
        if p_i not in PROBLEM_CODES:
            return None
        return {
            "primary_problem_code": PROBLEM_CODES[p_i],
            "secondary_problem_code": PROBLEM_CODES.get(s_i) if s_i else None,
            "primary_dosh": DOSH_BY_INDEX.get(d_i, "None"),
            "sentiment": SENTIMENT_BY_INDEX.get(e_i, "Curious"),
            "urgency_score": max(1, min(10, u_i)),
            "commercial_intent": INTENT_BY_INDEX.get(i_i, "NONE"),
            "commercial_signals": [SIGNAL_BY_INDEX[g_i]] if g_i in SIGNAL_BY_INDEX else [],
            "recommended_service": SERVICE_BY_INDEX.get(r_i, "None"),
            "is_crisis_flag": c.strip().upper().startswith("Y"),
            "exact_user_complaint": "",  # skipped in compact mode for speed
        }
    except (ValueError, KeyError, IndexError):
        return None


def classify_comment(text: str, debug: bool = False) -> dict | None:
    prompt = f"{SYSTEM_PROMPT}\n\nComment:\n{text}\n\nReply:"
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "num_predict": 40},
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        candidate_lines = [l for l in raw.splitlines() if "|" in l]
        line = candidate_lines[-1] if candidate_lines else raw
        parsed = parse_compact(line)
        if parsed is None and debug:
            print(f"  [debug] unparseable model output: {raw!r}")
        return parsed
    except (requests.RequestException,) as e:
        print(f"  request failed: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3, help="Concurrent requests to Ollama")
    parser.add_argument("--batch-write-size", type=int, default=50)
    parser.add_argument("--debug", action="store_true", help="Print raw model output when parsing fails")
    args = parser.parse_args()

    db = get_isolated_db()
    comments_col = db.comments

    cursor = comments_col.find({"analysis": None}, {"comment_text": 1})
    if args.limit:
        cursor = cursor.limit(args.limit)
    docs = list(cursor)
    total = len(docs)
    print(f"Found {total} un-enriched comments. Model={MODEL}, workers={args.workers}\n")

    write_lock = Lock()
    pending_updates: list[UpdateOne] = []
    done_count = [0]
    fail_count = [0]
    start = time.time()

    def worker(doc):
        parsed = classify_comment(doc.get("comment_text", ""), debug=args.debug)
        if parsed is None:
            with write_lock:
                fail_count[0] += 1
            return
        parsed["analyzed_at"] = datetime.now(timezone.utc)
        parsed["model_version"] = MODEL_VERSION_TAG
        parsed["lead_status"] = "NEW"
        with write_lock:
            pending_updates.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"analysis": parsed}}))
            done_count[0] += 1
            if len(pending_updates) >= args.batch_write_size:
                comments_col.bulk_write(pending_updates, ordered=False)
                pending_updates.clear()
            if done_count[0] % 25 == 0 or done_count[0] == total:
                elapsed = time.time() - start
                rate = done_count[0] / elapsed if elapsed > 0 else 0
                remaining_sec = (total - done_count[0]) / rate if rate > 0 else float("inf")
                print(
                    f"  {done_count[0]}/{total} done ({fail_count[0]} failed) | "
                    f"{rate:.2f}/sec | ETA {remaining_sec/3600:.1f}h remaining this run"
                )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(worker, doc) for doc in docs]
        for _ in as_completed(futures):
            pass

    if pending_updates:
        comments_col.bulk_write(pending_updates, ordered=False)

    elapsed_min = (time.time() - start) / 60
    print(f"\nDone. {done_count[0]} classified, {fail_count[0]} failed, in {elapsed_min:.1f} min.")
    if done_count[0] > 0:
        rate = done_count[0] / (elapsed_min * 60)
        print(f"Measured rate: {rate:.2f}/sec — at this rate, 1,000,000 comments = {1_000_000/rate/86400:.1f} days.")


if __name__ == "__main__":
    main()
