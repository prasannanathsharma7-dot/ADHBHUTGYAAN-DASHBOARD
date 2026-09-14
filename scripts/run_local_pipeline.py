"""
Local pipeline orchestrator. Runs the full scrape -> enrich flow on your
own machine, no cloud dependency, no Celery broker required for this
mode (it calls the task function directly rather than via .delay()).

For the full 1M-comment initial bulk load with real concurrency, run
Celery workers separately instead (see README.md "Full-scale local run"
section) — this script is the simple, single-process path for smaller
incremental runs and for testing the pipeline end-to-end.

Usage:
    python scripts/run_local_pipeline.py --video-list scraper/video_ids.txt
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scraper.youtube_worker import scrape_video_comments, db  # noqa: E402
from nlp.batch_pipeline import run_full_pipeline  # noqa: E402


def load_video_list(path: str) -> list[tuple[str, str]]:
    if not os.path.exists(path):
        print(f"No video list found at {path}")
        return []
    pairs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",", 1)
            video_id = parts[0].strip()
            channel_id = parts[1].strip() if len(parts) == 2 else ""
            pairs.append((video_id, channel_id))
    return pairs


def main():
    parser = argparse.ArgumentParser(description="Run the local scrape + enrich pipeline")
    parser.add_argument("--video-list", default="scraper/video_ids.txt")
    parser.add_argument("--skip-scrape", action="store_true", help="Only run enrichment on existing unenriched comments")
    parser.add_argument("--skip-enrich", action="store_true", help="Only scrape, skip Claude Batch enrichment")
    args = parser.parse_args()

    if not args.skip_scrape:
        video_list = load_video_list(args.video_list)
        if not video_list:
            print("No videos to scrape. Add entries to your video list file.")
        for video_id, channel_id in video_list:
            print(f"Scraping {video_id}...")
            try:
                result = scrape_video_comments.run(video_id, channel_id)
                print(f"  -> {result}")
            except Exception as e:
                print(f"  -> FAILED: {e}")

    if not args.skip_enrich:
        print("Running Claude Batch enrichment on un-enriched comments...")
        run_full_pipeline()

    print("Pipeline run complete.")


if __name__ == "__main__":
    main()
