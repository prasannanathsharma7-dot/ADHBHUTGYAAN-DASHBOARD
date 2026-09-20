"""
Fetches YouTube transcripts (subtitles/auto-captions) via yt-dlp and
caches them in the isolated database, so nlp/gap_analysis.py can check
what a video actually said.

Free, no API key, no quota -- same category of tool as
youtube_comment_downloader already used by scraper/youtube_worker.py.

Note on quality: for Hindi astrology content these are usually
AUTO-generated captions, which are noticeably noisy (names and
Sanskrit terms especially). That's why gap_analysis.py treats its
output as a signal to review, not a verdict -- and why a video with no
captions at all is recorded as `unknown`, never as a gap.

Usage:
    python scraper/transcripts.py                 # fetch for all videos that have comments
    python scraper/transcripts.py --limit 10      # just the first 10 missing ones
    python scraper/transcripts.py --video-id abc  # one specific video
"""
import argparse
import glob
import os
import re
import subprocess
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mongo.db_guard import get_isolated_db  # noqa: E402

SUB_LANGS = "hi,en,hi-orig,en-orig"


def vtt_to_text(vtt_content: str) -> str:
    """Strip WEBVTT timing/markup and collapse the repeated rolling
    lines auto-captions produce, so the same phrase isn't counted
    dozens of times."""
    lines = []
    for raw in vtt_content.splitlines():
        line = raw.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)  # inline word-timing tags
        line = line.strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return " ".join(lines)


def fetch_transcript(video_id: str) -> tuple[str, str]:
    """Returns (transcript_text, source). source is 'subtitles',
    'auto_captions', or 'none'."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmpdir:
        out_tpl = os.path.join(tmpdir, "%(id)s.%(ext)s")
        # Manual subtitles first -- much cleaner when a creator uploaded them.
        for flag, source in (("--write-subs", "subtitles"), ("--write-auto-subs", "auto_captions")):
            try:
                subprocess.run(
                    ["yt-dlp", "--skip-download", flag, "--sub-langs", SUB_LANGS,
                     "--sub-format", "vtt", "-o", out_tpl, url],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                )
            except FileNotFoundError:
                print("ERROR: yt-dlp not found. Run: pip install -r requirements.txt")
                sys.exit(1)
            except subprocess.TimeoutExpired:
                continue

            vtt_files = glob.glob(os.path.join(tmpdir, "*.vtt"))
            if vtt_files:
                combined = []
                for path in vtt_files:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        combined.append(vtt_to_text(f.read()))
                    os.remove(path)
                text = " ".join(t for t in combined if t).strip()
                if text:
                    return text, source
    return "", "none"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    parser.add_argument("--video-id", help="Fetch one specific video only")
    parser.add_argument("--refetch", action="store_true", help="Re-fetch videos already cached")
    args = parser.parse_args()

    db = get_isolated_db()
    transcripts_col = db.video_transcripts
    transcripts_col.create_index("video_id", unique=True)

    if args.video_id:
        video_ids = [args.video_id]
    else:
        video_ids = db.comments.distinct("video_id")
        if not args.refetch:
            already = set(transcripts_col.distinct("video_id"))
            video_ids = [v for v in video_ids if v not in already]
        if args.limit:
            video_ids = video_ids[: args.limit]

    if not video_ids:
        print("Nothing to fetch -- every video with comments already has a transcript record.")
        return

    print(f"Fetching transcripts for {len(video_ids)} video(s)...\n")
    counts = {"subtitles": 0, "auto_captions": 0, "none": 0}

    for i, vid in enumerate(video_ids, 1):
        text, source = fetch_transcript(vid)
        counts[source] += 1
        transcripts_col.update_one(
            {"video_id": vid},
            {"$set": {
                "video_id": vid,
                "transcript": text,
                "source": source,
                "char_count": len(text),
                "fetched_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        label = f"{source} ({len(text)} chars)" if text else "NO CAPTIONS"
        print(f"  [{i}/{len(video_ids)}] {vid}: {label}")

    print(
        f"\nDone. manual subtitles: {counts['subtitles']}, "
        f"auto-captions: {counts['auto_captions']}, none: {counts['none']}"
    )
    if counts["none"]:
        print(
            f"{counts['none']} video(s) had no captions at all -- their comments will be "
            f"scored 'unknown' by gap analysis, never 'unanswered'."
        )
    print("\nNext: python nlp/run_gap_analysis.py")


if __name__ == "__main__":
    main()
