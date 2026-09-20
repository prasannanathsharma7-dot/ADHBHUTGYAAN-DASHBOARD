"""
Pulls a random sample of already-classified comments for a human
spot-check, per ARCHITECTURE.md's own recommendation: "Sample-audit
~200 classified comments by hand early on and adjust the prompt --
don't trust the first pass blindly, this number directly drives your
business decisions."

Skips anything nlp/prefilter.py classified (model_version ==
"rule-prefilter-v1") -- that's deterministic rule logic, not a model
guess, so auditing it doesn't tell you anything about model accuracy.

Usage:
    python scripts/build_audit_sample.py --out audit_sample.csv --n 200
    python scripts/build_audit_sample.py --crisis-only --n 50
        # audits ONLY is_crisis_flag=True comments -- a plain random
        # sample of 200 will likely contain very few or zero of these,
        # which isn't enough to say anything about recall on the one
        # field where a miss matters most.
"""
import argparse
import csv
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mongo.db_guard import get_isolated_db  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="audit_sample.csv")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument(
        "--crisis-only",
        action="store_true",
        help="Sample only is_crisis_flag=True comments, to specifically check recall on that field.",
    )
    args = parser.parse_args()

    load_dotenv()
    db = get_isolated_db()
    comments_col = db.comments

    # Only comments the REAL classifier looked at -- exclude prefiltered.
    query: dict = {
        "analysis": {"$ne": None},
        "analysis.model_version": {"$ne": "rule-prefilter-v1"},
    }
    if args.crisis_only:
        query["analysis.is_crisis_flag"] = True

    total_eligible = comments_col.count_documents(query)
    label = "crisis-flagged" if args.crisis_only else "classified"
    print(f"{total_eligible} {label} comments eligible for audit.")

    if total_eligible == 0:
        print("Nothing to sample yet.")
        return

    pipeline = [{"$match": query}, {"$sample": {"size": min(args.n, total_eligible)}}]
    sample = list(comments_col.aggregate(pipeline))
    print(f"Sampled {len(sample)}.")

    if not args.crisis_only:
        crisis_in_sample = sum(1 for d in sample if d.get("analysis", {}).get("is_crisis_flag"))
        print(f"  of which is_crisis_flag=True: {crisis_in_sample}")
        if crisis_in_sample < 5:
            print(
                f"  NOTE: only {crisis_in_sample} crisis-flagged comments landed in this "
                f"random sample -- not enough to trust a recall number on that field. "
                f"Run again with --crisis-only to audit those specifically."
            )

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "comment_id", "comment_text", "model_primary_problem_code",
                "model_is_crisis_flag", "model_commercial_intent", "model_urgency_score",
                "model_version",
                "human_agrees_primary_code", "correct_primary_code_if_no",
                "human_agrees_crisis_flag", "human_agrees_commercial_intent", "notes",
            ]
        )
        for doc in sample:
            a = doc.get("analysis", {}) or {}
            writer.writerow(
                [
                    str(doc.get("_id", "")),
                    doc.get("comment_text", ""),
                    a.get("primary_problem_code", ""),
                    a.get("is_crisis_flag", ""),
                    a.get("commercial_intent", ""),
                    a.get("urgency_score", ""),
                    a.get("model_version", ""),
                    "", "", "", "", "",
                ]
            )

    print(f"\nWrote {args.out}.")
    print(
        "Open it in Excel/Sheets and fill in the human_* columns for EVERY row -- "
        "including ones you agree with, so a blank cell never gets silently counted "
        "as agreement (compute_audit_results.py treats blanks as 'not reviewed', "
        "not as correct). For human_agrees_crisis_flag specifically: read the actual "
        "comment text yourself on every row, not just the model's flag -- the real "
        "risk is the model missing a crisis, which you can only catch by reading the "
        "text, not by trusting rows where it already said False."
    )


if __name__ == "__main__":
    main()
