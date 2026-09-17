import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nlp.prefilter import should_prefilter

# Safe to skip: purely devotional/greeting/emoji, or empty.
CASES_SKIP = [
    "Jai Shri Ram \U0001F64F",
    "\U0001F64F\U0001F64F\U0001F64F",
    "Har Har Mahadev",
    "Radhe Radhe",
    "Good job \U0001F44D",
    "Nice video",
    "",
    "   ",
]

# Must ALWAYS reach the real classifier (Claude Batch / Ollama) — never
# silently skipped, regardless of length or whether it hits a keyword.
# The two crisis-phrasing cases are the ones that matter most: if either
# of these ever starts returning skip=True, do not "fix" the test —
# fix should_prefilter, because it means a real crisis comment could
# be marked low-signal without ever reaching is_crisis_flag detection.
CASES_KEEP = [
    "Sir mera rahu 7th house mein hai, marriage delay ho raha hai, upay batao",
    "मेरी शादी कब होगी?",
    "I want to die",  # crisis-safety case
    "मरना चाहता हूं",  # crisis-safety case
    "kuch samajh nahi aa raha bas",  # short, no keyword, no "?" — must still pass through
    "This was such a wonderful and informative video today thank you so much",
]


def test_skip_cases_are_unambiguously_safe():
    for text in CASES_SKIP:
        skip, reason = should_prefilter(text)
        assert skip is True, f"{text!r} should be skippable but wasn't ({reason})"


def test_keep_cases_always_reach_real_classifier():
    for text in CASES_KEEP:
        skip, reason = should_prefilter(text)
        assert skip is False, (
            f"{text!r} was pre-filtered ({reason}) but must always reach the "
            f"real classifier — see the safety note in nlp/prefilter.py"
        )


def test_empty_and_whitespace():
    assert should_prefilter("")[0] is True
    assert should_prefilter("   ")[0] is True
    assert should_prefilter(None)[0] is True
