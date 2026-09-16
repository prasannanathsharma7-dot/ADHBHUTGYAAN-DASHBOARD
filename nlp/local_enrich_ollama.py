"""
FREE local enrichment pipeline using Ollama — optimized for sustained
multi-day throughput on a single laptop GPU. No Anthropic API cost.

Three throughput optimizations vs. a naive JSON-output version:
  1. Small model (3B default) instead of 7B — 2-3x faster generation.
  2. Compact JSON output (single-letter keys) with Ollama's grammar-
     constrained "format: json" mode — guarantees syntactically valid
     JSON every time, which fixed a real failure mode where the small
     model echoed template placeholders back instead of real values.
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
MODEL_VERSION_TAG = f"ollama-{MODEL}-local-json"

# Index maps derived from the shared taxonomy module — stays in sync
# automatically if nlp/taxonomy.py ever changes.
DOSH_BY_INDEX = {i: v for i, v in enumerate(DOSH_ENUM)}
SENTIMENT_BY_INDEX = {i: v for i, v in enumerate(SENTIMENT_ENUM)}
INTENT_BY_INDEX = {i: v for i, v in enumerate(COMMERCIAL_INTENT_ENUM)}
SIGNAL_BY_INDEX = {i + 1: v for i, v in enumerate(COMMERCIAL_SIGNALS_ENUM)}  # 1-indexed, 0=none
SERVICE_BY_INDEX = {i: v for i, v in enumerate(RECOMMENDED_SERVICE_ENUM)}

SYSTEM_PROMPT = f"""You classify Indian astrology YouTube comments. \
{taxonomy_reference_text()}

Return a JSON object with these exact keys, filled with YOUR classification \
of the comment below — these are field definitions, not values to copy:
- "p": primary problem number, an integer 1-50 from the numbered list above (pick the closest match — NEVER output 0, every comment gets a number, use 7 if nothing else fits)
- "s": secondary problem number 1-50, or 0 if there is no clear second issue
- "d": dosh index, an integer: {", ".join(f"{i}={v}" for i, v in DOSH_BY_INDEX.items())}
- "e": sentiment index, an integer: {", ".join(f"{i}={v}" for i, v in SENTIMENT_BY_INDEX.items())}
- "u": urgency, an integer 1-10
- "i": intent index, an integer: {", ".join(f"{i}={v}" for i, v in INTENT_BY_INDEX.items())}
- "g": signal index, an integer, 0 if none: {", ".join(f"{i}={v}" for i, v in SIGNAL_BY_INDEX.items())}
- "r": service index, an integer: {", ".join(f"{i}={v}" for i, v in SERVICE_BY_INDEX.items())}
- "c": crisis flag, true only for explicit suicidal intent, else false

Worked examples (comment -> your JSON):
"Thank you so much sir, very helpful" -> {{"p":7,"s":0,"d":9,"e":4,"u":1,"i":3,"g":0,"r":6,"c":false}}
"How can I contact you for consultation" -> {{"p":7,"s":0,"d":9,"e":4,"u":2,"i":0,"g":1,"r":5,"c":false}}
"19 powerful but also paying karmic debts" -> {{"p":38,"s":0,"d":4,"e":4,"u":3,"i":3,"g":0,"r":6,"c":false}}

Now classify the real comment below. Output ONLY the JSON object, no other text."""


def parse_compact(obj: dict) -> dict | None:
    try:
        p_i = int(obj["p"])
        if p_i == 0:
            # Model couldn't confidently match a taxonomy code — this is
            # common for casual/devotional comments with no real problem.
            # Fall back to the low-signal category rather than discard
            # the classification entirely (mirrors the Claude prompt's
            # explicit fallback instruction in nlp/batch_pipeline.py).
            p_i = 7  # CAREER_CONFUSION_LACK_OF_PURPOSE
        s_i = int(obj.get("s", 0) or 0)
        d_i = int(obj.get("d", 9))
        e_i = int(obj.get("e", 4))
        u_i = int(obj.get("u", 1))
        i_i = int(obj.get("i", 3))
        g_i = int(obj.get("g", 0) or 0)
        r_i = int(obj.get("r", 6))
        c = obj.get("c", False)
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
            "is_crisis_flag": bool(c) if not isinstance(c, str) else c.strip().lower().startswith("t"),
            "exact_user_complaint": "",  # skipped in compact mode for speed
        }
    except (ValueError, KeyError, TypeError):
        return None


def classify_comment(text: str, debug: bool = False) -> dict | None:
    prompt = f"{SYSTEM_PROMPT}\n\nComment:\n{text}\n\nJSON:"
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",  # grammar-constrained: Ollama guarantees valid JSON syntax
                "options": {"temperature": 0, "num_predict": 60},
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            if debug:
                print(f"  [debug] invalid JSON from model: {raw!r}")
            return None
        parsed = parse_compact(obj)
        if parsed is None and debug:
            print(f"  [debug] JSON parsed but fields invalid: {obj!r}")
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
