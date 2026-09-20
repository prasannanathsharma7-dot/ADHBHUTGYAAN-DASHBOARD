"""
Transcript-based gap analysis: did the video ACTUALLY answer the
question being asked in the comment?

Until now "unanswered" was an assumption. This measures it: pull the
video's own transcript (scraper/transcripts.py), then check whether the
specific terms in a viewer's question appear in what the creator
actually said.

WHAT THIS IS AND ISN'T
This is a keyword-coverage proxy, not comprehension. It answers "were
these concepts spoken about in this video", not "was this person's
question answered well". YouTube's auto-generated Hindi captions are
also noticeably noisy. So:
  - Low coverage => `likely_unanswered` (a lead worth looking at),
    never a hard claim that the video ignored it.
  - No transcript available => status is `unknown`, NEVER
    `unanswered`. Missing data is not evidence of a gap. This
    distinction is the whole point -- collapsing the two would
    manufacture fake gaps out of videos that simply had captions off.

CROSS-SCRIPT MATCHING
Comments are usually Hinglish ("shani sade sati kya hai") while Hindi
transcripts come back in Devanagari ("शनि साढ़ेसाती"). A naive string
match finds nothing and every comment looks unanswered. TERM_ALIASES
below maps the domain's core vocabulary across both scripts so the
comparison is meaningful. Extend it as you notice terms being missed.

CRISIS COMMENTS ARE EXCLUDED
Comments with analysis.is_crisis_flag = True are skipped entirely and
never scored. A person in real distress is not a "content gap" to mine
for a video hook -- they belong in the human-review CrisisQueue that
already exists, and nowhere else. See the README's ethics note.
"""
import re
import unicodedata

# Core domain vocabulary, grouped so either script matches the other.
# Each tuple is one concept; add rows as you see terms slipping through.
TERM_ALIASES = [
    ("शनि", "shani", "sani", "saturn"),
    ("साढ़ेसाती", "साढ़े साती", "sade sati", "sadesati", "sadhesati"),
    ("ढैया", "dhaiya", "dhaiyya"),
    ("राहु", "rahu"),
    ("केतु", "ketu"),
    ("मंगल", "mangal", "mars"),
    ("मांगलिक", "manglik", "mangalik"),
    ("गुरु", "guru", "brihaspati", "jupiter"),
    ("शुक्र", "shukra", "venus"),
    ("बुध", "budh", "mercury"),
    ("सूर्य", "surya", "sun"),
    ("चंद्र", "चन्द्र", "chandra", "moon"),
    ("कुंडली", "कुण्डली", "kundli", "kundali", "horoscope", "chart"),
    ("दोष", "dosh", "dosha"),
    ("कालसर्प", "काल सर्प", "kaal sarp", "kalsarp", "kaalsarp"),
    ("पितृ", "pitra", "pitru", "pitr"),
    ("महादशा", "mahadasha", "mahadsha"),
    ("अंतर्दशा", "antardasha"),
    ("उपाय", "upay", "upaay", "remedy", "remedies"),
    ("रुद्राभिषेक", "rudrabhishek", "rudraabhishek"),
    ("पूजा", "puja", "pooja"),
    ("मंत्र", "mantra", "jaap", "जाप"),
    ("रत्न", "ratna", "gemstone", "stone"),
    ("विवाह", "शादी", "vivah", "shadi", "marriage", "wedding"),
    ("तलाक", "talaq", "divorce"),
    ("नौकरी", "naukri", "job", "employment"),
    ("सरकारी", "sarkari", "government"),
    ("व्यापार", "business", "vyapar", "vyapaar"),
    ("कर्ज", "कर्ज़", "karz", "karja", "debt", "loan"),
    ("संतान", "santan", "santaan", "child", "children", "baccha"),
    ("स्वास्थ्य", "swasthya", "health", "bimari", "बीमारी"),
    ("वास्तु", "vastu", "vaastu"),
    ("भाव", "bhav", "house"),
    ("लग्न", "lagna", "ascendant"),
    ("गोचर", "gochar", "transit"),
    ("दशा", "dasha"),
    ("नक्षत्र", "nakshatra"),
    ("राशि", "rashi", "zodiac", "sign"),
]

# Words that carry no topical meaning -- if these were counted, every
# comment would look well-covered just for sharing filler with the
# transcript.
STOPWORDS = {
    # Hinglish / roman
    "hai", "hain", "ho", "hoga", "hogi", "tha", "thi", "the", "kya", "kyu", "kyun",
    "kaise", "kab", "kahan", "kaun", "mera", "meri", "mere", "apna", "apni", "aap",
    "main", "mai", "hum", "ye", "yeh", "wo", "woh", "iska", "uska", "ka", "ki", "ke",
    "ko", "se", "me", "mein", "par", "aur", "bhi", "nahi", "na", "to", "toh", "sir",
    "guruji", "ji", "please", "plz", "batao", "bataye", "bataiye", "kripya", "help",
    "koi", "kuch", "bahut", "bohot", "saal", "din", "abhi", "kar", "karo", "karna",
    "raha", "rahi", "rahe", "gaya", "gayi", "liye", "wala", "wali", "sakta", "sakte",
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "i", "my", "me",
    "you", "your", "he", "she", "it", "we", "they", "this", "that", "of", "in",
    "on", "for", "to", "and", "or", "but", "what", "why", "how", "when", "where",
    "can", "will", "do", "does", "did", "please", "sir", "any", "some",
    # Devanagari
    "है", "हैं", "हो", "होगा", "होगी", "था", "थी", "थे", "क्या", "क्यों", "कैसे",
    "कब", "कहां", "कौन", "मेरा", "मेरी", "मेरे", "अपना", "आप", "मैं", "हम", "ये",
    "यह", "वो", "वह", "का", "की", "के", "को", "से", "में", "पर", "और", "भी",
    "नहीं", "ना", "तो", "जी", "कृपया", "कोई", "कुछ", "बहुत", "साल", "दिन", "अभी",
    "कर", "करो", "करना", "रहा", "रही", "रहे", "गया", "लिए", "वाला", "सकता",
}

_token_re = re.compile(r"[a-zA-Z]+|[\u0900-\u097F]+", re.UNICODE)


def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    return text.lower().strip()


def tokenize(text: str) -> list[str]:
    return [t for t in _token_re.findall(normalize(text)) if t not in STOPWORDS and len(t) > 1]


def _concept_ids_in(text: str) -> set[int]:
    """Which TERM_ALIASES concepts appear in this text, in any script."""
    norm = normalize(text)
    found = set()
    for idx, aliases in enumerate(TERM_ALIASES):
        for alias in aliases:
            if normalize(alias) in norm:
                found.add(idx)
                break
    return found


def coverage_score(question: str, transcript: str) -> dict:
    """
    How much of what this comment is asking about was actually spoken
    about in the video.

    Returns a dict with:
      score        0.0-1.0, or None when there's nothing to compare
      matched      concept/terms found in the transcript
      missing      concept/terms NOT found
      basis        "concepts" (domain terms matched) or "tokens"
                   (fell back to plain word overlap)

    Concepts are checked first because they're script-aware; plain
    token overlap is only a fallback for comments that use none of the
    known vocabulary.
    """
    if not transcript or not transcript.strip():
        return {"score": None, "matched": [], "missing": [], "basis": "no_transcript"}
    if not question or not question.strip():
        return {"score": None, "matched": [], "missing": [], "basis": "no_question"}

    q_concepts = _concept_ids_in(question)
    if q_concepts:
        t_concepts = _concept_ids_in(transcript)
        matched = sorted(q_concepts & t_concepts)
        missing = sorted(q_concepts - t_concepts)
        return {
            "score": len(matched) / len(q_concepts),
            "matched": [TERM_ALIASES[i][0] for i in matched],
            "missing": [TERM_ALIASES[i][0] for i in missing],
            "basis": "concepts",
        }

    q_tokens = set(tokenize(question))
    if not q_tokens:
        return {"score": None, "matched": [], "missing": [], "basis": "no_content_words"}
    t_tokens = set(tokenize(transcript))
    matched = sorted(q_tokens & t_tokens)
    missing = sorted(q_tokens - t_tokens)
    return {
        "score": len(matched) / len(q_tokens),
        "matched": matched,
        "missing": missing,
        "basis": "tokens",
    }


def classify_gap(question: str, transcript: str, threshold: float = 0.5) -> dict:
    """
    Wraps coverage_score into a status the dashboard can group on.

    status is one of:
      "likely_unanswered"  coverage below threshold -- worth a look
      "likely_covered"     coverage at or above threshold
      "unknown"            no transcript, or nothing comparable

    "unknown" is deliberately its own status and must never be counted
    as a gap -- see the module docstring.
    """
    result = coverage_score(question, transcript)
    if result["score"] is None:
        status = "unknown"
    elif result["score"] < threshold:
        status = "likely_unanswered"
    else:
        status = "likely_covered"
    return {
        "status": status,
        "coverage": result["score"],
        "matched_terms": result["matched"],
        "missing_terms": result["missing"],
        "basis": result["basis"],
        "threshold": threshold,
        "method": "keyword-coverage-v1",
    }
