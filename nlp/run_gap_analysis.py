"""
Applies nlp/gap_analysis.py across classified comments and stores the
result on each one, so the dashboard can rank topics by what people
asked that the video genuinely didn't cover.

Run order:
    python scraper/discovery.py         # find outlier videos
    python scripts/run_local_pipeline.py --skip-enrich   # scrape comments
    python nlp/prefilter.py             # drop obvious junk for free
    <enrichment: batch_pipeline.py or local_enrich_ollama.py>
    python scraper/transcripts.py       # fetch what the videos actually said
    python nlp/run_gap_analysis.py      # <- this script

Writes a `gap` subdocument on each comment:
    {status, coverage, matched_terms, missing_terms, basis, threshold, method}

It never modifies `analysis`, never deletes anything, and never
touches a comment with analysis.is_crisis_flag = True -- those are
skipped entirely and left for the existing human-review CrisisQueue.
Someone's crisis is not content research.

Usage:
    python nlp/run_gap_analysis.py
    python nlp/run_gap_analysis.py --dry-run
    python nlp/run_gap_analysis.py --threshold 0.4
"""
import argparse
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pymongo import UpdateOne

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mongo.db_guard import get_isolated_db  # noqa: E402
from nlp.gap_analysis import classify_gap  # noqa: E402

PREFILTER_VERSION = "rule-prefilter-v1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rescore", action="store_true", help="Re-score comments that already have a gap field")
    parser.add_argument("--batch-write-size", type=int, default=500)
    args = parser.parse_args()

    db = get_isolated_db()
    comments_col = db.comments
    transcripts_col = db.video_transcripts

    transcripts = {
        doc["video_id"]: doc.get("transcript", "")
        for doc in transcripts_col.find({}, {"video_id": 1, "transcript": 1})
    }
    if not transcripts:
        print("No transcripts found. Run: python scraper/transcripts.py")
        return
    print(f"Loaded {len(transcripts)} transcript(s).")

    query = {
        "analysis": {"$ne": None},
        # Rule-prefiltered junk was never a real question -- nothing to check.
        "analysis.model_version": {"$ne": PREFILTER_VERSION},
        # Crisis comments are excluded by design. See module docstring.
        "analysis.is_crisis_flag": {"$ne": True},
    }
    if not args.rescore:
        query["gap"] = None

    total = comments_col.count_documents(query)
    print(f"{total} comment(s) to score.\n")
    if total == 0:
        return

    status_counts: dict[str, int] = {}
    basis_counts: dict[str, int] = {}
    updates = []
    processed = 0

    for doc in comments_col.find(query, {"comment_text": 1, "video_id": 1}):
        transcript = transcripts.get(doc.get("video_id"), "")
        result = classify_gap(doc.get("comment_text", ""), transcript, threshold=args.threshold)
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1
        basis_counts[result["basis"]] = basis_counts.get(result["basis"], 0) + 1
        processed += 1

        if not args.dry_run:
            updates.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"gap": result}}))
            if len(updates) >= args.batch_write_size:
                comments_col.bulk_write(updates, ordered=False)
                updates = []

    if updates:
        comments_col.bulk_write(updates, ordered=False)

    verb = "Would score" if args.dry_run else "Scored"
    print(f"{verb} {processed} comment(s).\n")
    print("By status:")
    for status, n in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status}: {n} ({n/processed*100:.1f}%)")

    print("\nBy matching basis:")
    for basis, n in sorted(basis_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {basis}: {n}")

    unknown = status_counts.get("unknown", 0)
    if unknown:
        print(
            f"\n{unknown} scored 'unknown' (no transcript, or no recognizable terms). "
            f"These are NOT gaps -- exclude them from any gap percentage you report, "
            f"or you'll be counting missing data as evidence."
        )
    token_basis = basis_counts.get("tokens", 0)
    if token_basis > processed * 0.3:
        print(
            f"\nNOTE: {token_basis} comment(s) fell back to plain word overlap because they "
            f"used none of the known astrology vocabulary. If that fraction stays high, add "
            f"the terms you're seeing to TERM_ALIASES in nlp/gap_analysis.py -- cross-script "
            f"matching is what makes this measurement meaningful."
        )


if __name__ == "__main__":
    main()
