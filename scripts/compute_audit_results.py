"""
Reads back a filled-in audit_sample.csv (see build_audit_sample.py)
and prints accuracy numbers.

is_crisis_flag disagreements are always printed in full, never folded
into just a percentage -- a single missed crisis matters more than a
summary statistic can convey, and this is the one field in the whole
pipeline where "mostly right" is not good enough.

Usage:
    python scripts/compute_audit_results.py --in audit_sample.csv
"""
import argparse
import csv


def normalize_yn(value) -> bool | None:
    """Blank or unrecognized input returns None ('not yet reviewed'),
    never True -- so an unfilled cell can never be silently counted as
    agreement."""
    v = (value or "").strip().lower()
    if v in ("y", "yes", "true", "1"):
        return True
    if v in ("n", "no", "false", "0"):
        return False
    return None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", default="audit_sample.csv")
    args = parser.parse_args(argv)

    with open(args.in_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    reviewed = [r for r in rows if normalize_yn(r.get("human_agrees_primary_code")) is not None]
    unreviewed = total - len(reviewed)
    if unreviewed:
        print(
            f"WARNING: {unreviewed} of {total} rows have no human_agrees_primary_code "
            f"value yet -- excluded from the numbers below, not counted as correct. "
            f"Fill in every row for a real number.\n"
        )

    if not reviewed:
        print("No reviewed rows yet.")
        return

    primary_agree = sum(1 for r in reviewed if normalize_yn(r["human_agrees_primary_code"]) is True)
    print(
        f"primary_problem_code agreement: {primary_agree}/{len(reviewed)} "
        f"({primary_agree/len(reviewed)*100:.1f}%)"
    )

    intent_rows = [r for r in reviewed if normalize_yn(r.get("human_agrees_commercial_intent")) is not None]
    if intent_rows:
        intent_agree = sum(1 for r in intent_rows if normalize_yn(r["human_agrees_commercial_intent"]) is True)
        print(
            f"commercial_intent agreement: {intent_agree}/{len(intent_rows)} "
            f"({intent_agree/len(intent_rows)*100:.1f}%)"
        )

    print("\n--- is_crisis_flag: the field that matters most -------------------")
    crisis_rows = [r for r in reviewed if normalize_yn(r.get("human_agrees_crisis_flag")) is not None]
    if not crisis_rows:
        print(
            "No human_agrees_crisis_flag values filled in -- fill these in for "
            "every row, this field is never skippable."
        )
    else:
        disagreements = [r for r in crisis_rows if normalize_yn(r["human_agrees_crisis_flag"]) is False]
        agree_count = len(crisis_rows) - len(disagreements)
        print(f"Agreement: {agree_count}/{len(crisis_rows)} ({agree_count/len(crisis_rows)*100:.1f}%)")
        if disagreements:
            print(f"\n{len(disagreements)} DISAGREEMENT(S) ON THE CRISIS FLAG -- read each one:")
            for r in disagreements:
                print(
                    f"  comment_id={r.get('comment_id')} "
                    f"model said is_crisis_flag={r.get('model_is_crisis_flag', '')}"
                )
                print(f"    text: {(r.get('comment_text') or '')[:200]}")
                if (r.get("notes") or "").strip():
                    print(f"    notes: {r.get('notes')}")
                print()
            print(
                "If any of these are the model saying False when it should have said "
                "True, that is a missed crisis, not a rounding error -- fix the prompt "
                "(nlp/batch_pipeline.py's system prompt, or nlp/local_enrich_ollama.py) "
                "before trusting this field again, regardless of the percentage above."
            )

    with_notes = [r for r in reviewed if (r.get("notes") or "").strip()]
    if with_notes:
        print(f"\n{len(with_notes)} rows have notes -- worth a manual read-through.")


if __name__ == "__main__":
    main()
