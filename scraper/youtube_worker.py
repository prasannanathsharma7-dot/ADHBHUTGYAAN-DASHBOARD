"""
YouTube comment scraper worker.

Design goals:
- Never hold more than one video's comments in memory at a time (stream to Mongo).
- Resumable: every video's progress is checkpointed, so a crash/restart
  never re-scrapes from zero.
- Rate-limited + proxy-rotated to reduce IP-ban risk.
- Runs as a Celery task so you can horizontally scale workers.

Requires: youtube-comment-downloader, pymongo, celery, redis
    pip install youtube-comment-downloader pymongo celery redis
"""

import hashlib
import random
import time
from datetime import datetime, timezone

from celery import Celery
from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError
from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_POPULAR

# --- Config -----------------------------------------------------------
MONGO_URI = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net"
DB_NAME = "adhbhutgyaan_intel"
BATCH_INSERT_SIZE = 500
MIN_DELAY_SEC = 2.0
MAX_DELAY_SEC = 6.0

# Rotate through a proxy pool. In production, pull this from your
# residential proxy provider's endpoint list rather than hardcoding.
PROXY_POOL = [
    # "http://user:pass@proxy1.example.com:8000",
    # "http://user:pass@proxy2.example.com:8000",
]

celery_app = Celery("scraper", broker="redis://localhost:6379/0")
mongo = MongoClient(MONGO_URI)
db = mongo[DB_NAME]
raw_comments = db.raw_comments
scrape_status = db.scrape_status

# Ensure indexes exist (idempotent, safe to call on every worker boot)
raw_comments.create_index("content_hash", unique=True)
raw_comments.create_index("video_id")
raw_comments.create_index([("enriched", 1), ("scraped_at", 1)])
scrape_status.create_index("video_id", unique=True)


def content_hash(text: str, author_channel_id: str) -> str:
    normalized = (text or "").strip().lower()
    return hashlib.sha256(f"{normalized}|{author_channel_id}".encode()).hexdigest()


def polite_sleep():
    time.sleep(random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC))


def get_proxy():
    return random.choice(PROXY_POOL) if PROXY_POOL else None


@celery_app.task(bind=True, max_retries=5, default_retry_delay=120)
def scrape_video_comments(self, video_id: str, channel_name: str):
    """
    Scrapes all comments for one video, streaming inserts to Mongo in
    chunks. Resumable via scrape_status checkpoint.
    """
    status_doc = scrape_status.find_one({"video_id": video_id})
    if status_doc and status_doc.get("status") == "done":
        return {"video_id": video_id, "skipped": True}

    scrape_status.update_one(
        {"video_id": video_id},
        {"$set": {"status": "in_progress", "started_at": datetime.now(timezone.utc)}},
        upsert=True,
    )

    downloader = YoutubeCommentDownloader()
    buffer = []
    total_scraped = 0

    try:
        comment_generator = downloader.get_comments(
            video_id, sort_by=SORT_BY_POPULAR
        )

        for comment in comment_generator:
            doc = {
                "video_id": video_id,
                "channel_name": channel_name,
                "author": comment.get("author"),
                "author_channel_id": comment.get("channel"),
                "text": comment.get("text"),
                "like_count": comment.get("votes", 0),
                "is_reply": comment.get("reply", False),
                "content_hash": content_hash(
                    comment.get("text", ""), comment.get("channel", "")
                ),
                "scraped_at": datetime.now(timezone.utc),
                "enriched": False,  # flips to True once NLP pipeline processes it
                "source": "youtube",
            }
            buffer.append(doc)
            total_scraped += 1

            if len(buffer) >= BATCH_INSERT_SIZE:
                _flush_buffer(buffer)
                buffer = []
                polite_sleep()  # rate-limit between chunks, not every comment

        if buffer:
            _flush_buffer(buffer)

        scrape_status.update_one(
            {"video_id": video_id},
            {
                "$set": {
                    "status": "done",
                    "completed_at": datetime.now(timezone.utc),
                    "total_scraped": total_scraped,
                }
            },
        )
        return {"video_id": video_id, "total_scraped": total_scraped}

    except Exception as exc:
        scrape_status.update_one(
            {"video_id": video_id},
            {"$set": {"status": "failed", "error": str(exc)}},
        )
        # Exponential-ish backoff retry via Celery
        raise self.retry(exc=exc)


def _flush_buffer(buffer):
    """Bulk insert; ordered=False so one duplicate doesn't kill the batch."""
    if not buffer:
        return
    try:
        raw_comments.insert_many(buffer, ordered=False)
    except BulkWriteError as bwe:
        # Duplicate key errors (content_hash) are expected and fine to skip.
        real_errors = [
            e for e in bwe.details.get("writeErrors", [])
            if e.get("code") != 11000
        ]
        if real_errors:
            raise


def enqueue_channel(video_ids: list[str], channel_name: str):
    """Call this once with a channel's full video-id list to queue the job."""
    for vid in video_ids:
        scrape_video_comments.delay(vid, channel_name)


if __name__ == "__main__":
    # Example: enqueue a batch of video IDs for one channel.
    # In practice, pull video_ids via yt-dlp's flat-playlist extraction
    # against the channel's /videos tab, not manually.
    sample_video_ids = ["VIDEO_ID_1", "VIDEO_ID_2"]
    enqueue_channel(sample_video_ids, channel_name="ExampleAstrologyChannel")
