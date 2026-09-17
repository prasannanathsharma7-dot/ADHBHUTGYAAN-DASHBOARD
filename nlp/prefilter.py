"""
Cheap rule-based pre-filter — runs BEFORE nlp/batch_pipeline.py or
nlp/local_enrich_ollama.py, so obviously junk/devotional-only comments
never cost an LLM call (Claude Batch $ or Ollama GPU time).

Integration: it does NOT touch either enrichment script. It writes the
SAME low-signal `analysis` shape nlp/batch_pipeline.py's own system
prompt already specifies for junk (see its "If the comment is spam..."
fallback) and nlp/local_enrich_ollama.py's p_i==0 fallback — just
instantly and for free. Both scripts query on {"analysis": None}, so
anything this script marks is automatically skipped by both. Nothing
is ever deleted or hidden: every comment keeps its full text and stays
fully visible in Mongo, this only saves LLM calls on obvious noise.

SAFETY-CRITICAL DESIGN NOTE — read before "improving" this file:
This filter is deliberately conservative. It only marks a comment as
skippable when it is PURELY devotional/greeting/emoji content (or
empty) — nothing else. It does NOT use length or keyword-presence to
decide whether to skip, because a keyword list can never fully
enumerate every way a person might express real distress, and this
pipeline's crisis-flag detection (is_crisis_flag, see nlp/taxonomy.py
and the README's "Ethics note: the crisis flag") only runs inside the
real classifiers. A short comment, or one with no astrology keyword,
must still reach Claude Batch / Ollama — so it must never be skipped
here. If you widen the skip conditions later, re-run
tests/test_prefilter.py's crisis-safety cases against the change first.

Usage:
    python nlp/prefilter.py                # apply to all un-enriched comments
    python nlp/prefilter.py --dry-run       # report counts only, write nothing
"""
import argparse
import os
import re
import sys
from datetime import datetime, timezone

from pymongo import UpdateOne

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mongo.db_guard import get_isolated_db  # noqa: E402
from nlp.taxonomy import PROBLEM_CODES  # noqa: E402

MODEL_VERSION_TAG = "rule-prefilter-v1"
# Same fallback code nlp/batch_pipeline.py's own system prompt already
# uses for spam/unrelated comments, so pre-filtered junk lands in the
# exact bucket the real classifier would have put it in anyway.
LOW_SIGNAL_CODE = PROBLEM_CODES[7]  # CAREER_CONFUSION_LACK_OF_PURPOSE

DEVOTIONAL_PATTERNS = [
    r"जय\s*श्री\s*राम", r"हर\s*हर\s*महादेव", r"राधे\s*राधे", r"प्रणाम", r"ॐ",
    r"jai\s*shri\s*ram", r"har\s*har\s*mahadev", r"radhe\s*radhe", r"pranam",
    r"good\s*job", r"nice\s*video", r"very\s*nice",
]
_devotional_re = re.compile("|".join(DEVOTIONAL_PATTERNS), re.IGNORECASE)
_emoji_re = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF]", re.UNICODE)

# --- Diagnostic-only signals (never used to decide a skip) ----------------
# Kept purely so you can see the shape of your data — e.g. what fraction
# of comments carry no recognizable astrology keyword — without that
# information ever being allowed to cause a comment to be skipped.
MIN_LENGTH = 12
QUESTION_MARKERS = ["?", "कब", "क्यों", "कैसे", "kab", "kyu", "kyun", "kaise", "kya"]
WHITELIST_TOKENS = [
    r"शनि", r"shani", r"राहु", r"rahu", r"केतु", r"ketu", r"कुंडली", r"kundli",
    r"दोष", r"dosh", r"उपाय", r"upay", r"शादी", r"marriage", r"नौकरी", r"naukri",
    r"job", r"कर्ज़?", r"karz", r"debt", r"तलाक", r"divorce", r"फीस", r"fees",
    r"अपॉइंटमेंट", r"appointment", r"संपर्क", r"contact", r"गुरुजी", r"guruji",
]
_question_re = re.compile("|".join(re.escape(m) for m in QUESTION_MARKERS), re.IGNORECASE)
_whitelist_re = re.compile("(?:" + "|".join(WHITELIST_TOKENS) + ")", re.IGNORECASE | re.UNICODE)


def is_devotional_only(text: str) -> bool:
    """True only if the ENTIRE comment is devotional/greeting/emoji noise —
    i.e. nothing at all remains after stripping those patterns."""
    stripped = _devotional_re.sub("", text)
    stripped = _emoji_re.sub("", stripped)
    stripped = re.sub(r"[\s.,!।~\-_]+", "", stripped)
    return len(stripped) == 0


def should_prefilter(text: str) -> tuple[bool, str]:
    """
    The only function allowed to decide whether a comment skips the real
    classifier. Returns (skip, reason). See the safety note at the top
    of this file before changing what counts as skippable.
    """
    text = (text or "").strip()
    if not text:
        return True, "empty"
    if is_devotional_only(text):
        return True, "devotional_only"
    return False, "passed_to_real_classifier"


def diagnostic_flags(text: str) -> list[str]:
    """Informational only — never affects should_prefilter's decision."""
    text = (text or "").strip()
    flags = []
    has_question = bool(_question_re.search(text))
    if len(text) < MIN_LENGTH and not has_question:
        flags.append("short")
    if not _whitelist_re.search(text):
        flags.append("no_keyword")
    return flags


def build_low_signal_analysis(reason: str) -> dict:
    return {
        "primary_problem_code": LOW_SIGNAL_CODE,
        "secondary_problem_code": None,
        "primary_dosh": "None",
        "exact_user_complaint": "",
        "sentiment": "Curious",
        "urgency_score": 1,
        "is_crisis_flag": False,
        "commercial_intent": "NONE",
        "commercial_signals": [],
        "recommended_service": "None",
        "analyzed_at": datetime.now(timezone.utc),
        "model_version": MODEL_VERSION_TAG,
        "prefilter_reason": reason,
        "lead_status": "NEW",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report counts only, write nothing")
    parser.add_argument("--batch-write-size", type=int, default=500)
    args = parser.parse_args()

    db = get_isolated_db()
    comments_col = db.comments

    cursor = comments_col.find({"analysis": None}, {"comment_text": 1})
    acted_counts: dict[str, int] = {}
    diagnostic_counts: dict[str, int] = {}
    updates = []
    total = 0

    for doc in cursor:
        total += 1
        text = doc.get("comment_text", "")
        skip, reason = should_prefilter(text)
        acted_counts[reason] = acted_counts.get(reason, 0) + 1
        for flag in diagnostic_flags(text):
            diagnostic_counts[flag] = diagnostic_counts.get(flag, 0) + 1

        if skip and not args.dry_run:
            updates.append(
                UpdateOne({"_id": doc["_id"]}, {"$set": {"analysis": build_low_signal_analysis(reason)}})
            )
            if len(updates) >= args.batch_write_size:
                comments_col.bulk_write(updates, ordered=False)
                updates = []

    if updates:
        comments_col.bulk_write(updates, ordered=False)

    print(f"Scanned {total} un-enriched comments.\n")
    print("Acted on (these decide what gets skipped):")
    for reason, n in sorted(acted_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {reason}: {n}")

    prefiltered = sum(n for r, n in acted_counts.items() if r != "passed_to_real_classifier")
    pct = (prefiltered / total * 100) if total else 0
    verb = "Would pre-filter" if args.dry_run else "Pre-filtered"
    print(f"\n{verb} {prefiltered} of {total} ({pct:.1f}%) — never costs an LLM call.")
    print(f"{total - prefiltered} remain for nlp/batch_pipeline.py or nlp/local_enrich_ollama.py.\n")

    print("Diagnostic only (NOT used to skip anything, just informative):")
    for flag, n in sorted(diagnostic_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {flag}: {n}")


if __name__ == "__main__":
    main()
