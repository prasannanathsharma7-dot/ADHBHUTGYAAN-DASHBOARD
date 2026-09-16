"""
Claude Batch API enrichment pipeline — classifies scraped comments
against the full 50-node problem taxonomy and writes the result onto
each comment's `analysis` subdocument.

Hard-isolated to astrology_intelligence.comments — see mongo/db_guard.py.

Flow:
  1. Pull un-enriched comments (analysis == null) from Mongo in chunks
     of <=75,000 (safely under the 100K-request / 256MB batch ceiling).
  2. Submit each chunk as a Message Batch with a shared cached system
     prompt (the 50-node taxonomy) via cache_control.
  3. Poll for completion, stream results, validate against the JSON
     schema, write onto the matching comment by _id.
  4. lead_status is set to "NEW" only if the comment doesn't already
     have one — re-running enrichment never resets a human's progress
     on a comment they've already reviewed/contacted.
  5. Anything that fails validation goes to dead_letter for retry
     rather than being silently dropped.

Ethics / business-risk note on is_crisis_flag:
  Comments flagged is_crisis_flag=True (SUICIDAL_DESPERATION_END_STAGE)
  must NOT be surfaced in the commercial "leads" dashboard view or
  routed toward a paid-service upsell. Route them to a separate,
  human-reviewed queue. The dashboard's analytics API intentionally
  excludes crisis-flagged comments from the high_intent_leads facet
  (see dashboard/app/api/analytics/route.ts) — don't remove that filter.

Requires: anthropic, pymongo, jsonschema
    pip install anthropic pymongo jsonschema
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from bson import ObjectId
from jsonschema import validate, ValidationError
from pymongo import UpdateOne

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
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

# Sonnet is worth the extra cost here: 50 fine-grained categories plus a
# P0 suicidal-ideation flag need better judgment than a pure-classification
# model reliably gives. Switch to "claude-haiku-4-5-20251001" if you need
# to cut cost and are willing to accept more misclassification, especially
# on the crisis flag — recommend keeping Sonnet for that field regardless.
MODEL = "claude-sonnet-5"
MODEL_VERSION_TAG = "claude-sonnet-5-batch-v1"

CHUNK_SIZE = 75_000
POLL_INTERVAL_SEC = 60

client = anthropic.Anthropic()
db = get_isolated_db()
comments_col = db.comments
dead_letter = db.dead_letter

ANALYSIS_SCHEMA = build_analysis_json_schema()

SYSTEM_PROMPT = f"""You are a classification engine for an Indian astrology \
business's comment-analysis pipeline. You will be given a single public \
YouTube comment or FAQ question, possibly in Hindi (Devanagari), Hinglish, \
or English.

{taxonomy_reference_text()}

Classify the comment strictly according to the JSON schema provided. \
primary_problem_code must be the single best-matching code from the list \
above. secondary_problem_code is a second code if a distinct secondary \
issue is also clearly present, otherwise null. primary_dosh is the \
specific dosh named or clearly implied (one of: {", ".join(DOSH_ENUM)}). \
sentiment must be one of: {", ".join(SENTIMENT_ENUM)}. commercial_intent \
must be one of: {", ".join(COMMERCIAL_INTENT_ENUM)} — HIGH only if the \
user is clearly asking to book/pay for something. commercial_signals is \
a list drawn only from: {", ".join(COMMERCIAL_SIGNALS_ENUM)} (empty list \
if none apply). recommended_service must be one of: \
{", ".join(RECOMMENDED_SERVICE_ENUM)}.

is_crisis_flag must be true ONLY if the comment expresses explicit \
suicidal intent or desperation to end their life — set \
primary_problem_code to SUICIDAL_DESPERATION_END_STAGE in that case. Be \
conservative: general sadness, venting, or "life is hard" phrasing is \
NOT a crisis flag. Only explicit statements of suicidal intent qualify.

If the comment is spam, an emoji reaction, or entirely unrelated to \
astrology/personal problems, still return a valid object: use a plausible \
CAREER_CONFUSION_LACK_OF_PURPOSE-adjacent low-signal classification with \
sentiment="Curious", commercial_intent="NONE", urgency_score=1, \
is_crisis_flag=false, commercial_signals=[], recommended_service="None".

Respond with ONLY a single valid JSON object — no markdown fences, no \
preamble, no explanation."""


def detect_language_hint(text: str) -> str:
    """Cheap heuristic language tag stored alongside the LLM's own read.
    Devanagari Unicode block: U+0900-U+097F."""
    if any("\u0900" <= ch <= "\u097f" for ch in text):
        return "hi"
    hinglish_markers = ("hai", "kya", "nahi", "mera", "meri", "kyun", "kaise")
    lowered = text.lower()
    if any(f" {m} " in f" {lowered} " for m in hinglish_markers):
        return "hinglish"
    return "en"


def build_batch_requests(comments: list[dict]) -> list[Request]:
    requests = []
    for c in comments:
        requests.append(
            Request(
                custom_id=str(c["_id"]),
                params=MessageCreateParamsNonStreaming(
                    model=MODEL,
                    max_tokens=500,
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"Comment:\n{c['comment_text']}\n\n"
                                f"JSON Schema:\n{json.dumps(ANALYSIS_SCHEMA)}"
                            ),
                        }
                    ],
                ),
            )
        )
    return requests


def submit_and_wait(requests: list[Request]) -> str:
    batch = client.messages.batches.create(requests=requests)
    print(f"Submitted batch {batch.id} with {len(requests)} requests")

    while True:
        batch = client.messages.batches.retrieve(batch.id)
        counts = batch.request_counts
        print(
            f"[{batch.id}] processing={counts.processing} "
            f"succeeded={counts.succeeded} errored={counts.errored}"
        )
        if batch.processing_status == "ended":
            break
        time.sleep(POLL_INTERVAL_SEC)

    return batch.id


def parse_and_apply_results(batch_id: str, comment_texts_by_id: dict[str, str]):
    analysis_updates = []
    lead_status_init_ids = []
    dead_letter_docs = []

    for result in client.messages.batches.results(batch_id):
        comment_mongo_id = result.custom_id

        if result.result.type != "succeeded":
            dead_letter_docs.append(
                {
                    "comment_mongo_id": comment_mongo_id,
                    "reason": result.result.type,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            continue

        text_block = result.result.message.content[0].text
        # Sonnet occasionally wraps output in a markdown fence despite
        # instructions not to. Strip it before parsing rather than
        # sending valid classifications to dead_letter over formatting.
        cleaned = text_block.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        try:
            parsed = json.loads(cleaned)
            validate(instance=parsed, schema=ANALYSIS_SCHEMA)
        except (json.JSONDecodeError, ValidationError) as e:
            dead_letter_docs.append(
                {
                    "comment_mongo_id": comment_mongo_id,
                    "reason": "schema_validation_failed",
                    "raw_output": text_block,
                    "error": str(e),
                    "created_at": datetime.now(timezone.utc),
                }
            )
            continue

        parsed["analyzed_at"] = datetime.now(timezone.utc)
        parsed["model_version"] = MODEL_VERSION_TAG

        original_text = comment_texts_by_id.get(comment_mongo_id, "")
        language_detected = detect_language_hint(original_text)

        analysis_updates.append(
            UpdateOne(
                {"_id": ObjectId(comment_mongo_id)},
                {"$set": {"analysis": parsed, "language_detected": language_detected}},
            )
        )
        lead_status_init_ids.append(ObjectId(comment_mongo_id))

    if analysis_updates:
        comments_col.bulk_write(analysis_updates, ordered=False)
        print(f"Applied {len(analysis_updates)} enrichments")

    # Second pass: only set lead_status if not already present, so
    # re-running enrichment never resets a human's CONTACTED/CONVERTED work.
    if lead_status_init_ids:
        comments_col.update_many(
            {
                "_id": {"$in": lead_status_init_ids},
                "analysis.lead_status": {"$exists": False},
            },
            {"$set": {"analysis.lead_status": "NEW"}},
        )

    if dead_letter_docs:
        dead_letter.insert_many(dead_letter_docs)
        print(f"Sent {len(dead_letter_docs)} results to dead_letter")


def run_full_pipeline():
    cursor = comments_col.find({"analysis": None}).batch_size(1000)
    chunk = []

    for doc in cursor:
        chunk.append(doc)
        if len(chunk) >= CHUNK_SIZE:
            _process_chunk(chunk)
            chunk = []

    if chunk:
        _process_chunk(chunk)


def _process_chunk(chunk: list[dict]):
    text_by_id = {str(c["_id"]): c.get("comment_text", "") for c in chunk}
    requests = build_batch_requests(chunk)
    batch_id = submit_and_wait(requests)
    parse_and_apply_results(batch_id, text_by_id)


if __name__ == "__main__":
    run_full_pipeline()
