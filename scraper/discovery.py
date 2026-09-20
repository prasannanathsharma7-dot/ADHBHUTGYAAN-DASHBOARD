"""
Automated discovery: finds outlier astrology videos on their own, so
video_ids.txt no longer needs to be filled in by hand.

Two sources, both using yt-dlp against YouTube's own public pages
(same category of tool as youtube_comment_downloader, already used
elsewhere in this repo -- not an official API, same accepted trade-off):

1. CHANNEL-based: for each seed channel, pull its most recent videos,
   work out that channel's own normal views/hour, and flag anything
   running well ahead of its own baseline (an "outlier" for THAT
   channel -- a small channel's average day and a big channel's
   average day look nothing alike, so nothing is compared across
   channels here).
2. SEARCH-based: run the Hindi query clusters below and pull matching
   results directly, regardless of which channel they're on.

Either way, matching video IDs are appended to video_ids.txt in the
existing "video_id,channel_id" format -- scraper/youtube_worker.py and
scripts/run_local_pipeline.py need no changes at all.

EDIT THE TWO LISTS BELOW FOR YOUR NICHE. The handles are a starting
point from your own notes -- verify each one actually resolves (this
script will tell you if a handle returns zero videos) before trusting
its results.

Usage:
    python scraper/discovery.py                 # channel + search discovery
    python scraper/discovery.py --dry-run        # print what it WOULD add, write nothing
    python scraper/discovery.py --channels-only  # skip the search pass
    python scraper/discovery.py --search-only    # skip the channel pass
    python scraper/discovery.py --multiplier 3.0 # stricter outlier bar
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime, timezone

# --- EDIT FOR YOUR NICHE ---------------------------------------------------

SEED_CHANNELS = [
    "AstroArunPandit",
    "DrJaiMadaan",
    "GrahonKaKhel",       # Pt. Suresh Shrimali
    "VinayBajrangi",      # verify -- guessed handle
    "AstroTalk",          # verify -- guessed handle
]

SEARCH_QUERIES = [
    "कुंडली दोष निवारण",
    "शनि साढ़ेसाती असली उपाय",
    "कालसर्प दोष लक्षण",
    "मांगलिक दोष विवाह उपाय",
    "राहु महादशा लक्षण",
    "सरकारी नौकरी कुंडली योग",
    "रुद्राभिषेक सही नियम",
    "पितृ दोष मुक्ति उपाय",
    "कर्ज मुक्ति ज्योतिष उपाय",
]

# ----------------------------------------------------------------------------

YTDLP = "yt-dlp"


def _run(cmd: list, timeout: int) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout
    except FileNotFoundError:
        print("ERROR: yt-dlp not found. Run: pip install -r requirements.txt")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        return ""


def get_channel_video_ids(handle: str, limit: int) -> list[str]:
    """Fast pass: just the most recent N video IDs for a channel."""
    url = f"https://www.youtube.com/@{handle}/videos"
    out = _run([YTDLP, "--flat-playlist", "--playlist-end", str(limit), "--print", "%(id)s", url], timeout=120)
    return [line.strip() for line in out.splitlines() if line.strip() and line.strip() != "NA"]


def get_video_metadata(video_id: str) -> dict | None:
    """Full pass for one video -- real view_count, duration, upload_date.
    Slower than flat-playlist but far more reliable, and we only call
    this for videos we're actually considering (tens per run, not
    thousands), so the extra time is worth the correctness."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    fields = "%(id)s|%(title)s|%(view_count)s|%(duration)s|%(upload_date)s|%(channel)s|%(channel_id)s"
    out = _run([YTDLP, "--skip-download", "--print", fields, url], timeout=60)
    line = out.strip().splitlines()[0] if out.strip() else ""
    parts = line.split("|")
    if len(parts) < 7:
        return None
    vid, title, views, duration, upload_date, channel, channel_id = parts[:7]
    try:
        view_count = int(views)
    except ValueError:
        return None
    try:
        upload_dt = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return {
        "id": vid,
        "title": title,
        "view_count": view_count,
        "upload_date": upload_dt,
        "channel": channel,
        "channel_id": channel_id,
    }


def compute_outliers(
    videos: list[dict],
    multiplier: float = 2.5,
    min_views: int = 3000,
    min_age_hours: float = 6,
    max_age_days: float = 30,
) -> list[dict]:
    """Pure logic, no network -- the only function that decides what
    counts as an outlier, so it's the only thing tests/test_discovery.py
    needs to cover directly."""
    now = datetime.now(timezone.utc)
    scored = []
    for v in videos:
        age_hours = (now - v["upload_date"]).total_seconds() / 3600
        if age_hours < min_age_hours or age_hours / 24 > max_age_days:
            continue
        v = dict(v)
        v["views_per_hour"] = v["view_count"] / max(age_hours, 1)
        scored.append(v)

    if len(scored) < 3:
        return []  # not enough recent data to trust a baseline

    baseline = statistics.median(v["views_per_hour"] for v in scored)
    if baseline <= 0:
        return []

    outliers = []
    for v in scored:
        if v["views_per_hour"] >= multiplier * baseline and v["view_count"] >= min_views:
            v["velocity"] = v["views_per_hour"] / baseline
            outliers.append(v)
    return sorted(outliers, key=lambda v: -v["velocity"])


def search_videos(query: str, limit: int) -> list[str]:
    out = _run([YTDLP, f"ytsearch{limit}:{query}", "--flat-playlist", "--print", "%(id)s"], timeout=120)
    return [line.strip() for line in out.splitlines() if line.strip() and line.strip() != "NA"]


def load_existing_ids(path: str) -> set:
    existing = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    existing.add(line.split(",")[0].strip())
    return existing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--multiplier", type=float, default=2.5, help="Outlier bar: velocity >= this x the channel's own median")
    parser.add_argument("--channel-limit", type=int, default=30, help="Recent videos to check per channel")
    parser.add_argument("--search-limit", type=int, default=15, help="Results to check per search query")
    parser.add_argument("--min-search-views", type=int, default=3000)
    parser.add_argument("--out", default="scraper/video_ids.txt")
    parser.add_argument("--channels-only", action="store_true")
    parser.add_argument("--search-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    discovered: dict[str, tuple] = {}  # video_id -> (channel_id, source_note)

    if not args.search_only:
        print("=== Channel-based discovery ===")
        for handle in SEED_CHANNELS:
            print(f"\n@{handle}:")
            ids = get_channel_video_ids(handle, args.channel_limit)
            if not ids:
                print("  0 videos found -- handle may be wrong, verify it resolves in a browser.")
                continue
            videos = [m for m in (get_video_metadata(v) for v in ids) if m]
            outliers = compute_outliers(videos, multiplier=args.multiplier)
            print(f"  {len(videos)} videos checked, {len(outliers)} outlier(s)")
            for v in outliers:
                print(f"    {v['id']}  {v['velocity']:.1f}x baseline  {v['view_count']} views  \"{v['title'][:60]}\"")
                discovered[v["id"]] = (v["channel_id"], f"channel_outlier {v['velocity']:.1f}x")

    if not args.channels_only:
        print("\n=== Search-based discovery ===")
        for query in SEARCH_QUERIES:
            print(f"\n\"{query}\":")
            ids = search_videos(query, args.search_limit)
            added = 0
            for vid in ids:
                if vid in discovered:
                    continue
                meta = get_video_metadata(vid)
                if meta and meta["view_count"] >= args.min_search_views:
                    discovered[vid] = (meta["channel_id"], f"search: {query}")
                    added += 1
            print(f"  {added} added (of {len(ids)} results)")

    print(f"\nTotal newly discovered this run: {len(discovered)}")

    if args.dry_run:
        print("--dry-run: not writing to", args.out)
        return

    existing = load_existing_ids(args.out)
    new_lines = [f"{vid},{channel_id}\n" for vid, (channel_id, _) in discovered.items() if vid not in existing]

    with open(args.out, "a", encoding="utf-8") as f:
        f.writelines(new_lines)

    skipped = len(discovered) - len(new_lines)
    print(f"Appended {len(new_lines)} new video IDs to {args.out} ({skipped} already present, skipped).")
    print("Run scripts/run_local_pipeline.py (or the .bat files) next to actually scrape and enrich these.")


if __name__ == "__main__":
    main()
