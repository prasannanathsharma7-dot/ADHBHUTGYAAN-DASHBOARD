"""
GitHub Actions-friendly scraper runner.

Celery + Redis assumes a persistent broker and long-running workers,
which doesn't fit GitHub Actions' ephemeral, scheduled-run model. This
script does the same job directly, in a single process, for the video
IDs listed in `scraper/video_ids.txt` (one video_id per line, format:
`video_id,channel_name`).

It reuses all the same logic (rate-limiting, checkpointing, dedup) from
youtube_worker.py, just without the Celery task wrapper — call the
underlying function directly instead of `.delay()`.

Environment variables required (set as GitHub repo secrets):
  MONGODB_URI
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from youtube_worker import scrape_video_comments, mongo  # noqa: E402


def load_video_list(path: str = "scraper/video_ids.txt") -> list[tuple[str, str]]:
    if not os.path.exists(path):
        print(f"No video list found at {path} — nothing to scrape this run.")
        return []
    pairs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",", 1)
            if len(parts) == 2:
                pairs.append((parts[0].strip(), parts[1].strip()))
    return pairs


def main():
    video_list = load_video_list()
    if not video_list:
        return

    for video_id, channel_name in video_list:
        try:
            # .run() executes the Celery task function body synchronously,
            # without needing a broker — fine for scheduled CI runs.
            result = scrape_video_comments.run(video_id, channel_name)
            print(f"Done: {result}")
        except Exception as e:
            print(f"Failed {video_id}: {e}")

    mongo.close()


if __name__ == "__main__":
    main()
