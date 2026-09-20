import csv
import io
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from compute_audit_results import normalize_yn, main as compute_main  # noqa: E402


def test_normalize_yn():
    assert normalize_yn("y") is True
    assert normalize_yn("Yes") is True
    assert normalize_yn("TRUE") is True
    assert normalize_yn(" 1 ") is True
    assert normalize_yn("n") is False
    assert normalize_yn("No") is False
    assert normalize_yn("0") is False
    assert normalize_yn("") is None
    assert normalize_yn(None) is None
    assert normalize_yn("maybe") is None


def test_blank_rows_never_counted_as_agreement(tmp_path):
    """A row a human hasn't reviewed yet must be excluded from the
    percentage, never silently treated as a match."""
    path = tmp_path / "audit_sample.csv"
    rows = [
        {
            "comment_id": "1", "comment_text": "text1",
            "model_primary_problem_code": "SHANI_SADE_SATI_PEAK_CHEST_PHASE",
            "model_is_crisis_flag": "False", "model_commercial_intent": "HIGH",
            "model_urgency_score": "5", "model_version": "claude-sonnet-5-batch-v1",
            "human_agrees_primary_code": "y", "correct_primary_code_if_no": "",
            "human_agrees_crisis_flag": "y", "human_agrees_commercial_intent": "y",
            "notes": "",
        },
        {
            "comment_id": "2", "comment_text": "text2",
            "model_primary_problem_code": "CAREER_CONFUSION_LACK_OF_PURPOSE",
            "model_is_crisis_flag": "False", "model_commercial_intent": "NONE",
            "model_urgency_score": "1", "model_version": "claude-sonnet-5-batch-v1",
            "human_agrees_primary_code": "",  # NOT reviewed yet
            "correct_primary_code_if_no": "", "human_agrees_crisis_flag": "",
            "human_agrees_commercial_intent": "", "notes": "",
        },
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    buf = io.StringIO()
    with redirect_stdout(buf):
        compute_main(["--in", str(path)])
    output = buf.getvalue()

    assert "1 of 2 rows have no human_agrees_primary_code" in output
    assert "1/1 (100.0%)" in output  # only the reviewed row counts


def test_crisis_disagreement_is_printed_in_full(tmp_path):
    """A crisis-flag disagreement must never be reducible to just a
    percentage -- the actual row has to be printed for a human to read."""
    path = tmp_path / "audit_sample.csv"
    rows = [
        {
            "comment_id": "99", "comment_text": "mujhe koi rasta nahi dikh raha, sab khatam karna chahta hoon",
            "model_primary_problem_code": "CAREER_CONFUSION_LACK_OF_PURPOSE",
            "model_is_crisis_flag": "False",  # model MISSED this
            "model_commercial_intent": "NONE", "model_urgency_score": "2",
            "model_version": "claude-sonnet-5-batch-v1",
            "human_agrees_primary_code": "n", "correct_primary_code_if_no": "SUICIDAL_DESPERATION_END_STAGE",
            "human_agrees_crisis_flag": "n", "human_agrees_commercial_intent": "y",
            "notes": "model missed this, should be crisis flag",
        },
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    buf = io.StringIO()
    with redirect_stdout(buf):
        compute_main(["--in", str(path)])
    output = buf.getvalue()

    assert "DISAGREEMENT" in output
    assert "comment_id=99" in output
    assert "missed" not in output.split("DISAGREEMENT")[0]  # sanity: not just buried earlier
