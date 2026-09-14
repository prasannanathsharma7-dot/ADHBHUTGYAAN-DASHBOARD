"""
YouTube comment scraper worker — writes into the isolated
`astrology_intelligence.comments` collection only.

Design goals:
- Never hold more than one video's comments in memory at a time.
- Resumable: every video's progress is checkpointed.
- Rate-limited to reduce IP-ban risk.
- Pulls real video/channel metadata via YouTube's public oEmbed endpoint
  (no API key, no quota) instead of leaving video_title/channel_title blank.
- Hard-isolated to astrology_intelligence — see mongo/db_guard.py.

Requires: youtube-comment-downloader, pymongo, celery, redis, requests
    pip install youtube-comment-downloader pymongo celery redis requests
"""

import os
import random
import sys
import time
from datetime import datetime, timezone

import requests
from celery import Celery
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError
from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_POPULAR

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mongo.db_guard import get_isolated_db  # noqa: E402

# --- Config -----------------------------------------------------------
BATCH_INSERT_SIZE = 500
MIN_DELAY_SEC = 2.0
MAX_DELAY_SEC = 6.0

# Rotate through a proxy pool for the initial bulk load. In production,
# pull this from your residential proxy provider's endpoint list.
PROXY_POOL = [
    # "http://user:pass@proxy1.example.com:8000",
]

celery_app = Celery("scraper", broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"))

db = get_isolated_db()
comments_col = db.comments
scrape_status = db.scrape_status
video_metadata_cache = db.video_metadata_cache

# Indexes — idempotent, safe on every worker boot
comments_col.create_index("comment_id", unique=True)
comments_col.create_index("video_id")
comments_col.create_index("channel_id")
comments_col.create_index([("analysis.primary_problem_code", 1), ("analysis.urgency_score", -1)])
comments_col.create_index([("analysis.commercial_intent", 1), ("analysis.lead_status", 1)])
comments_col.create_index("analysis.is_crisis_flag")
comments_col.create_index([("comment_text", "text")])
scrape_status.create_index("video_id", unique=True)
video_metadata_cache.create_index("video_id", unique=True)


def polite_sleep():
    time.sleep(random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC))


def get_proxy():
    return random.choice(PROXY_POOL) if PROXY_POOL else None


def fetch_video_metadata(video_id: str) -> dict:
    """
    Video title + channel title via YouTube's public oEmbed endpoint —
    no API key, no quota cost. Cached in Mongo so repeated runs don't
    re-fetch the same video's metadata.
    """
    cached = video_metadata_cache.find_one({"video_id": video_id})
    if cached:
        return {"video_title": cached["video_title"], "channel_title": cached["channel_title"]}

    url = f"https://www.youtube.com/watch?v={video_id}"
    resp = requests.get(
        "https://www.youtube.com/oembed",
        params={"url": url, "format": "json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    metadata = {
        "video_title": data.get("title", ""),
        "channel_title": data.get("author_name", ""),
    }
    video_metadata_cache.insert_one(
        {"video_id": video_id, **metadata, "cached_at": datetime.now(timezone.utc)}
    )
    return metadata


@celery_app.task(bind=True, max_retries=5, default_retry_delay=120)
def scrape_video_comments(self, video_id: str, channel_id: str = ""):
    """Scrapes all comments for one video, streaming inserts to Mongo."""
    status_doc = scrape_status.find_one({"video_id": video_id})
    if status_doc and status_doc.get("status") == "done":
        return {"video_id": video_id, "skipped": True}

    scrape_status.update_one(
        {"video_id": video_id},
        {"$set": {"status": "in_progress", "started_at": datetime.now(timezone.utc)}},
        upsert=True,
    )

    try:
        metadata = fetch_video_metadata(video_id)
    except requests.RequestException as e:
        metadata = {"video_title": "", "channel_title": ""}
        print(f"Warning: metadata fetch failed for {video_id}: {e}")

    downloader = YoutubeCommentDownloader()
    buffer = []
    total_scraped = 0

    try:
        comment_generator = downloader.get_comments(video_id, sort_by=SORT_BY_POPULAR)

        for comment in comment_generator:
            time_parsed = comment.get("time_parsed")
            published_at = (
                datetime.fromtimestamp(time_parsed, tz=timezone.utc)
                if time_parsed
                else None
            )
            author_channel_id = comment.get("channel", "")

            doc = {
                "comment_id": comment.get("cid"),
                "video_id": video_id,
                "video_title": metadata["video_title"],
                "channel_title": metadata["channel_title"],
                "channel_id": channel_id,
                "published_at": published_at,
                "author_name": comment.get("author"),
                "author_channel_url": (
                    f"https://www.youtube.com/channel/{author_channel_id}"
                    if author_channel_id
                    else None
                ),
                "comment_text": comment.get("text"),
                "language_detected": None,  # filled by nlp/batch_pipeline.py
                "scraped_at": datetime.now(timezone.utc),
                "analysis": None,  # filled by nlp/batch_pipeline.py
            }

            if not doc["comment_id"]:
                continue  # can't dedup/upsert without YouTube's own comment id

            buffer.append(doc)
            total_scraped += 1

            if len(buffer) >= BATCH_INSERT_SIZE:
                _flush_buffer(buffer)
                buffer = []
                polite_sleep()

        if buffer:
            _flush_buffer(buffer)

        scrape_status.update_one(
            {"video_id": video_id},
            {"$set": {"status": "done", "completed_at": datetime.now(timezone.utc), "total_scraped": total_scraped}},
        )
        return {"video_id": video_id, "total_scraped": total_scraped}

    except Exception as exc:
        scrape_status.update_one(
            {"video_id": video_id},
            {"$set": {"status": "failed", "error": str(exc)}},
        )
        raise self.retry(exc=exc)


def _flush_buffer(buffer):
    if not buffer:
        return
    try:
        comments_col.insert_many(buffer, ordered=False)
    except BulkWriteError as bwe:
        real_errors = [e for e in bwe.details.get("writeErrors", []) if e.get("code") != 11000]
        if real_errors:
            raise


def enqueue_channel(video_ids: list[str], channel_id: str = ""):
    for vid in video_ids:
        scrape_video_comments.delay(vid, channel_id)


if __name__ == "__main__":
    sample_video_ids = ["VIDEO_ID_1", "VIDEO_ID_2"]
    enqueue_channel(sample_video_ids, channel_id="UC_EXAMPLE_CHANNEL_ID")
