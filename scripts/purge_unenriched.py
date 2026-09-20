"""
Removes the old, un-enriched comment backlog -- the ~2 lakh raw
comments that were scraped before this repo had discovery.py,
nlp/prefilter.py, or the accuracy-audit tooling. The dashboard's
numbers are currently dominated by this pile (1% actually classified),
which makes it look thin and doesn't reflect what the new pipeline
(discovery -> scrape -> prefilter -> enrich) actually produces.

KEEPS anything that already has `analysis` set -- those cost real
Claude Batch spend to classify and are never touched. ONLY removes
comments where analysis is still None.

Always backs up what it's about to delete first (no flag needed to
skip this). Deletes in batches, not one giant operation, since we're
talking about roughly 200k documents.

Note on crisis screening: un-enriched comments were, by definition,
never run through is_crisis_flag detection -- there is no ongoing
pipeline obligation to have screened every historical comment for
crisis content before it can be removed; the crisis-routing design
here is about correctly handling what IS processed, not a mandate to
process the entire backlog first. If you'd rather be extra cautious,
run --sample-first to hand-check a slice before deleting the rest.

Usage:
    python scripts/purge_unenriched.py                 # stats + backup only
    python scripts/purge_unenriched.py --sample-first 50   # + export 50 random un-enriched
                                                             # ones to review before deciding
    python scripts/purge_unenriched.py --confirm       # actually deletes
"""
import argparse
import csv
import datetime
import gzip
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mongo.db_guard import get_isolated_db  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BATCH_SIZE = 2000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Actually delete. Without this, only stats + backup run.")
    parser.add_argument("--backup-dir", default="backups")
    parser.add_argument("--sample-first", type=int, default=0, help="Also export N random un-enriched comments to review before deleting")
    args = parser.parse_args()

    db = get_isolated_db()
    comments_col = db.comments

    total = comments_col.count_documents({})
    to_delete_query = {"analysis": None}
    to_delete_count = comments_col.count_documents(to_delete_query)
    to_keep_count = total - to_delete_count

    print(f"Total comments:              {total:,}")
    print(f"Already classified (kept):   {to_keep_count:,}")
    print(f"Un-enriched (to be removed): {to_delete_count:,}")

    if to_delete_count == 0:
        print("\nNothing to remove.")
        return

    if args.sample_first:
        sample_path = os.path.join(".", "purge_sample_review.csv")
        pipeline = [{"$match": to_delete_query}, {"$sample": {"size": min(args.sample_first, to_delete_count)}}]
        sample = list(comments_col.aggregate(pipeline))
        with open(sample_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["comment_id", "video_id", "comment_text"])
            for doc in sample:
                writer.writerow([doc.get("comment_id", ""), doc.get("video_id", ""), doc.get("comment_text", "")])
        print(f"\nExported {len(sample)} random un-enriched comments to {sample_path} for a quick look.")

    # --- backup, always ---
    os.makedirs(args.backup_dir, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = os.path.join(args.backup_dir, f"unenriched_backup_{timestamp}.json.gz")

    print(f"\nBacking up {to_delete_count:,} comments to {backup_path} ...")
    written = 0
    with gzip.open(backup_path, "wt", encoding="utf-8") as f_out:
        cursor = comments_col.find(to_delete_query)
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            f_out.write(json.dumps(doc, default=str, ensure_ascii=False) + "\n")
            written += 1
            if written % 20000 == 0:
                print(f"  backed up {written:,} / {to_delete_count:,}...")
    print(f"Backup complete: {written:,} documents -> {backup_path}")

    if not args.confirm:
        print(
            f"\nDry run only. Re-run with --confirm to actually delete these "
            f"{to_delete_count:,} un-enriched comments."
        )
        return

    print(f"\n--confirm passed. Deleting {to_delete_count:,} un-enriched comments in batches of {BATCH_SIZE}...")
    deleted = 0
    while True:
        ids = [
            doc["_id"]
            for doc in comments_col.find(to_delete_query, {"_id": 1}).limit(BATCH_SIZE)
        ]
        if not ids:
            break
        result = comments_col.delete_many({"_id": {"$in": ids}})
        deleted += result.deleted_count
        print(f"  deleted {deleted:,} / {to_delete_count:,}...")

    remaining = comments_col.count_documents({})
    print(f"\nDone. Deleted {deleted:,} comments. {remaining:,} remain (all already classified).")
    print(
        "Note: MongoDB may not shrink the collection's reported storage size "
        "immediately after a delete -- the data itself is gone and Atlas "
        "reclaims the space over time; this is normal, not a sign it didn't work."
    )
    print("\nNext: python scraper\\discovery.py  (or just double-click run_everything.bat)")


if __name__ == "__main__":
    main()
