import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nlp.gap_analysis import classify_gap, coverage_score, tokenize  # noqa: E402
from scraper.transcripts import vtt_to_text  # noqa: E402

HINDI_TRANSCRIPT = (
    "नमस्कार दोस्तों आज हम बात करेंगे शनि की साढ़ेसाती के बारे में। "
    "शनि जब आपकी राशि से गुजरता है तो क्या होता है, और इसके उपाय क्या हैं। "
    "शनि के मंत्र का जाप करें और शनिवार को तेल चढ़ाएं।"
)


def test_hinglish_question_matches_devanagari_transcript():
    """The whole point of TERM_ALIASES -- a Hinglish comment must match
    a Devanagari transcript, otherwise everything looks unanswered."""
    result = classify_gap("shani sade sati ke upay bataye", HINDI_TRANSCRIPT)
    assert result["status"] == "likely_covered", result
    assert result["coverage"] == 1.0


def test_devanagari_question_matches_devanagari_transcript():
    result = classify_gap("शनि की साढ़ेसाती के उपाय क्या हैं", HINDI_TRANSCRIPT)
    assert result["status"] == "likely_covered"


def test_genuinely_unanswered_question_is_flagged():
    """Video is about Shani; the viewer asks about Kaal Sarp and
    marriage -- neither is mentioned."""
    result = classify_gap("kaal sarp dosh aur shadi ka kya connection hai", HINDI_TRANSCRIPT)
    assert result["status"] == "likely_unanswered", result
    assert result["coverage"] < 0.5


def test_partial_coverage():
    """Shani is covered, karz is not -- should land between 0 and 1."""
    result = classify_gap("shani ke karan karz ho gaya hai kya karu", HINDI_TRANSCRIPT)
    assert 0 < result["coverage"] < 1
    assert "कर्ज" in result["missing_terms"]


def test_missing_transcript_is_unknown_not_unanswered():
    """The most important case: no data must never become a gap."""
    for empty in ("", "   ", None):
        result = classify_gap("shani sade sati ke upay bataye", empty)
        assert result["status"] == "unknown", f"{empty!r} produced {result['status']}"
        assert result["coverage"] is None


def test_empty_question_is_unknown():
    result = classify_gap("", HINDI_TRANSCRIPT)
    assert result["status"] == "unknown"


def test_stopword_only_question_does_not_look_covered():
    """A contentless comment shouldn't score as 'covered' just because
    its filler words appear in the transcript."""
    result = classify_gap("sir ji please batao", HINDI_TRANSCRIPT)
    assert result["status"] == "unknown"
    assert result["basis"] == "no_content_words"


def test_tokenize_strips_stopwords():
    tokens = tokenize("sir mera shani kharab hai kya karu")
    assert "sir" not in tokens
    assert "hai" not in tokens
    assert "shani" in tokens


def test_coverage_reports_basis():
    concept = coverage_score("shani upay", HINDI_TRANSCRIPT)
    assert concept["basis"] == "concepts"
    fallback = coverage_score("cricket match score", HINDI_TRANSCRIPT)
    assert fallback["basis"] == "tokens"


def test_vtt_parsing_strips_timing_and_dedupes():
    vtt = """WEBVTT
Kind: captions
Language: hi

00:00:01.000 --> 00:00:03.000
शनि की साढ़ेसाती

00:00:03.000 --> 00:00:05.000
शनि की साढ़ेसाती

00:00:05.000 --> 00:00:07.000
<c>के उपाय</c>
"""
    text = vtt_to_text(vtt)
    assert "-->" not in text
    assert "WEBVTT" not in text
    assert "<c>" not in text
    assert text.count("शनि की साढ़ेसाती") == 1  # rolling duplicate collapsed
    assert "के उपाय" in text
