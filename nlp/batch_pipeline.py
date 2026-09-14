"""
Claude Message Batches API pipeline for astrology-comment enrichment.

Flow:
  1. Pull un-enriched comments from MongoDB in chunks of <=80,000
     (safely under the 100K-request / 256MB batch ceiling).
  2. Submit each chunk as a Message Batch with a shared cached system
     prompt (cache_control on the instructions) for cheaper repeated hits.
  3. Poll for completion.
  4. Stream results back, validate against the JSON schema, write
     enrichment fields onto the original MongoDB documents.
  5. Anything that fails validation goes to a dead_letter collection
     for a cheap manual/second-pass retry rather than being dropped.

Requires: anthropic, pymongo, jsonschema
    pip install anthropic pymongo jsonschema
"""

import json
import time
from datetime import datetime, timezone

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from jsonschema import validate, ValidationError
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net"
DB_NAME = "adhbhutgyaan_intel"
MODEL = "claude-haiku-4-5-20251001"  # cost-effective classification model
CHUNK_SIZE = 75_000  # stays safely under 100K requests / 256MB per batch
POLL_INTERVAL_SEC = 60

client = anthropic.Anthropic()
mongo = MongoClient(MONGO_URI)
db = mongo[DB_NAME]
raw_comments = db.raw_comments
dead_letter = db.dead_letter

# --- Strict output schema ----------------------------------------------
ENRICHMENT_SCHEMA = {
    "type": "object",
    "required": [
        "topic",
        "detected_dosh",
        "urgency_score",
        "commercial_intent",
        "recommended_service",
        "language",
    ],
    "properties": {
        "topic": {
            "type": "string",
            "enum": [
                "marriage_delay", "career_finance", "health", "education",
                "family_conflict", "manglik_dosh", "kaal_sarp_dosh",
                "sade_sati", "pitra_dosh", "general_curiosity",
                "praise_testimonial", "spam_irrelevant", "other",
            ],
        },
        "detected_dosh": {
            "type": ["string", "null"],
            "description": "Specific dosh/yog named or implied, null if none.",
        },
        "urgency_score": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "description": "1=casual curiosity, 5=distressed/urgent seeking help.",
        },
        "commercial_intent": {
            "type": "string",
            "enum": ["high", "medium", "low", "none"],
            "description": "Likelihood this person would book a paid pooja/consultation.",
        },
        "recommended_service": {
            "type": ["string", "null"],
            "description": "E.g. Rudrabhishek, Kaal Sarp Dosh Nivaran Pooja, null if not applicable.",
        },
        "language": {
            "type": "string",
            "enum": ["hindi_devanagari", "hinglish", "english", "other"],
        },
    },
}

SYSTEM_PROMPT = """You are a classification engine for an Indian astrology \
business's comment-analysis pipeline. You will be given a single public \
comment or FAQ question (possibly in Hindi, Hinglish, or English). \
Classify it strictly according to the JSON schema provided. Respond with \
ONLY a single valid JSON object — no markdown fences, no preamble, no \
explanation. If the comment is spam, an emoji reaction, or unrelated to \
astrology, use topic="spam_irrelevant" and set other fields to null/low \
defaults as appropriate."""


def build_batch_requests(comments: list[dict]) -> list[Request]:
    requests = []
    for c in comments:
        requests.append(
            Request(
                custom_id=str(c["_id"]),
                params=MessageCreateParamsNonStreaming(
                    model=MODEL,
                    max_tokens=300,
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
                                f"Comment:\n{c['text']}\n\n"
                                f"JSON Schema:\n{json.dumps(ENRICHMENT_SCHEMA)}"
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


def parse_and_apply_results(batch_id: str):
    mongo_updates = []
    dead_letter_docs = []

    for result in client.messages.batches.results(batch_id):
        comment_id = result.custom_id

        if result.result.type != "succeeded":
            dead_letter_docs.append(
                {
                    "comment_id": comment_id,
                    "reason": result.result.type,
                    "detail": getattr(result.result, "error", None).__dict__
                    if getattr(result.result, "error", None)
                    else None,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            continue

        text_block = result.result.message.content[0].text
        try:
            parsed = json.loads(text_block)
            validate(instance=parsed, schema=ENRICHMENT_SCHEMA)
        except (json.JSONDecodeError, ValidationError) as e:
            dead_letter_docs.append(
                {
                    "comment_id": comment_id,
                    "reason": "schema_validation_failed",
                    "raw_output": text_block,
                    "error": str(e),
                    "created_at": datetime.now(timezone.utc),
                }
            )
            continue

        from bson import ObjectId

        mongo_updates.append(
            UpdateOne(
                {"_id": ObjectId(comment_id)},
                {
                    "$set": {
                        **parsed,
                        "enriched": True,
                        "enriched_at": datetime.now(timezone.utc),
                    }
                },
            )
        )

    if mongo_updates:
        raw_comments.bulk_write(mongo_updates, ordered=False)
        print(f"Applied {len(mongo_updates)} enrichments to MongoDB")

    if dead_letter_docs:
        dead_letter.insert_many(dead_letter_docs)
        print(f"Sent {len(dead_letter_docs)} results to dead_letter for retry")


def run_full_pipeline():
    cursor = raw_comments.find({"enriched": False}).batch_size(1000)
    chunk = []

    for doc in cursor:
        chunk.append(doc)
        if len(chunk) >= CHUNK_SIZE:
            _process_chunk(chunk)
            chunk = []

    if chunk:
        _process_chunk(chunk)


def _process_chunk(chunk: list[dict]):
    requests = build_batch_requests(chunk)
    batch_id = submit_and_wait(requests)
    parse_and_apply_results(batch_id)


if __name__ == "__main__":
    run_full_pipeline()
