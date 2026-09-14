"""
Master 50-node Problem & Grievance Taxonomy for Adhbhutgyaan Astrology
Intelligence Pipeline.

Single source of truth — both nlp/batch_pipeline.py and the dashboard's
TypeScript constants (dashboard/lib/taxonomy.ts) must stay in sync with
this file. If you add/change a code here, update both.
"""

# --- A. Career, Livelihood & Education (1-8) ---------------------------
# --- B. Marriage, Relationships & Lineage (9-18) ------------------------
# --- C. Debt, Property & Legal Quagmire (19-25) --------------------------
# --- D. Health, Mental Agony & Occult Fears (26-34) ----------------------
# --- E. Astrological Doshas & Planetary Afflictions (35-43) --------------
# --- F. User Grievances & Vendor Complaints (44-50) -----------------------

PROBLEM_CODES: dict[int, str] = {
    1: "SARKARI_EXAM_REPEATED_FAILURE",
    2: "CORPORATE_LAYOFF_JOBLESS",
    3: "PROMOTION_BLOCKED_OFFICE_POLITICS",
    4: "FOREIGN_VISA_PR_OBSTACLE",
    5: "BUSINESS_BANKRUPTCY_CASH_CRUNCH",
    6: "PARTNER_FRAUD_FINANCIAL_EMBEZZLEMENT",
    7: "CAREER_CONFUSION_LACK_OF_PURPOSE",
    8: "STUDY_CONCENTRATION_EXAM_PHOBIA",
    9: "LATE_MARRIAGE_ALLIANCE_COLLAPSE",
    10: "SEVERE_MANGLIK_KUNDLI_MISMATCH",
    11: "INTER_CASTE_FAMILY_OBJECTION",
    12: "INLAWS_CRUELTY_DOWRY_HARASSMENT",
    13: "SPOUSE_INFIDELITY_EXTRAMARITAL",
    14: "IMMINENT_DIVORCE_LEGAL_SEPARATION",
    15: "OBSESSIVE_HEARTBREAK_EX_RETURN",
    16: "CHRONIC_MARITAL_COLD_WAR",
    17: "INFERTILITY_CHILDLESSNESS_DELAY",
    18: "RECURRENT_MISCARRIAGE_GARBHA_DOSH",
    19: "CRUSHING_DEBT_LOAN_TRAP",
    20: "ANCESTRAL_LAND_BROTHER_DISPUTE",
    21: "STUCK_MONEY_NON_PAYMENT",
    22: "SHARE_MARKET_CRYPTO_RUIN",
    23: "PROPERTY_POSSESSION_BUILDER_SCAM",
    24: "FALSE_POLICE_CASE_COURT_TRIAL",
    25: "HOUSE_FORECLOSURE_AUCTION_THREAT",
    26: "CHRONIC_UNDIAGNOSED_PHYSICAL_ILLNESS",
    27: "CLINICAL_DEPRESSION_ISOLATION",
    28: "SUICIDAL_DESPERATION_END_STAGE",  # P0 crisis — see CRISIS_CODES below
    29: "TERRIFYING_NIGHTMARES_SLEEP_PARALYSIS",
    30: "CHILD_AUTISM_SPEECH_DELAY",
    31: "CHILD_ADDICTION_BAD_COMPANY",
    32: "SUSPICION_OF_BLACK_MAGIC_BANDHAN",
    33: "EVIL_EYE_NAZAR_DOSH_RUIN",
    34: "UNTIMELY_DEATH_FAMILY_CURSE",
    35: "KAAL_SARP_DOSH_FULL_LOCK",
    36: "SHANI_SADE_SATI_PEAK_CHEST_PHASE",
    37: "SHANI_DHAIYA_KANTAK_ASHTAM",
    38: "PITRA_DOSH_LINEAGE_CURSE",
    39: "GURU_CHANDAL_YOGA_MALIGN",
    40: "KEMDRUM_DOSH_EXTREME_POVERTY",
    41: "GANDMOOL_NAKSHATRA_AFFLICTION",
    42: "GRAHAN_DOSH_SURYA_CHANDRA_RAHU",
    43: "RAHU_MAHADASHA_ILLUSION_HAVOC",
    44: "FAKE_ASTROLOGER_LOOT_COMPLAINT",
    45: "GEMSTONE_INEFFECTIVE_ADVERSE_REACTION",
    46: "TEMPLE_PUJA_NO_EFFECT_COMPLAINT",
    47: "PANDIT_NO_SHOW_FAKE_SANKALP",
    48: "CONTRADICTORY_PREDICTIONS_CONFUSION",
    49: "REMEDY_TOO_EXPENSIVE_INACCESSIBLE",
    50: "UNANSWERED_CONSULTATION_GHOSTED",
}

PROBLEM_CODE_NAMES: list[str] = list(PROBLEM_CODES.values())

# Codes 44-50 are grievances against astrology vendors (yours and others) —
# this is the "Top 50 Complaints" bucket for the dashboard, distinct from
# "Top 50 Problems" (which is the full 1-43 set of life grievances).
VENDOR_COMPLAINT_CODES: list[str] = [PROBLEM_CODES[i] for i in range(44, 51)]

# Codes that must NEVER be routed into a sales/lead-gen flow. See the
# ethics note in nlp/batch_pipeline.py and README.md.
CRISIS_CODES: list[str] = ["SUICIDAL_DESPERATION_END_STAGE"]

DOSH_ENUM: list[str] = [
    "Manglik",
    "Kaal Sarp",
    "Sade Sati",
    "Shani Dhaiya",
    "Pitra Dosh",
    "Guru Chandal",
    "Kemdrum",
    "Gandmool",
    "Grahan Dosh",
    "None",
]

SENTIMENT_ENUM: list[str] = [
    "Distressed",
    "Seeking Remedy",
    "Angry Grievance",
    "Devotional",
    "Curious",
    "Skeptic",
]

COMMERCIAL_INTENT_ENUM: list[str] = ["HIGH", "MEDIUM", "LOW", "NONE"]

COMMERCIAL_SIGNALS_ENUM: list[str] = [
    "asking_phone_number",
    "asking_puja_cost",
    "asking_kashi_booking",
    "asking_gemstone_price",
]

RECOMMENDED_SERVICE_ENUM: list[str] = [
    "Kashi Vishwanath Rudrabhishek",
    "Mangal Shanti Puja Ujjain",
    "Trimbakeshwar Kaal Sarp Shanti",
    "Pitra Dosh Gaya Shradh",
    "Mahamrityunjaya Jaap",
    "Personal Kundli Diagnosis",
    "None",
]

LEAD_STATUS_ENUM: list[str] = ["NEW", "REVIEWED", "CONTACTED", "CONVERTED", "ARCHIVED"]

LANGUAGE_ENUM: list[str] = ["hi", "en", "hinglish"]


def build_analysis_json_schema() -> dict:
    """Strict JSON Schema for the `analysis` object Claude must return."""
    return {
        "type": "object",
        "required": [
            "primary_problem_code",
            "secondary_problem_code",
            "primary_dosh",
            "exact_user_complaint",
            "sentiment",
            "urgency_score",
            "is_crisis_flag",
            "commercial_intent",
            "commercial_signals",
            "recommended_service",
        ],
        "properties": {
            "primary_problem_code": {"type": "string", "enum": PROBLEM_CODE_NAMES},
            "secondary_problem_code": {
                "type": ["string", "null"],
                "enum": PROBLEM_CODE_NAMES + [None],
            },
            "primary_dosh": {"type": "string", "enum": DOSH_ENUM},
            "exact_user_complaint": {
                "type": "string",
                "description": "One-line distillation of the grievance, in Hinglish.",
            },
            "sentiment": {"type": "string", "enum": SENTIMENT_ENUM},
            "urgency_score": {"type": "integer", "minimum": 1, "maximum": 10},
            "is_crisis_flag": {
                "type": "boolean",
                "description": (
                    "True ONLY if primary_problem_code is "
                    "SUICIDAL_DESPERATION_END_STAGE or the text otherwise "
                    "expresses explicit suicidal intent."
                ),
            },
            "commercial_intent": {"type": "string", "enum": COMMERCIAL_INTENT_ENUM},
            "commercial_signals": {
                "type": "array",
                "items": {"type": "string", "enum": COMMERCIAL_SIGNALS_ENUM},
            },
            "recommended_service": {"type": "string", "enum": RECOMMENDED_SERVICE_ENUM},
        },
    }


def taxonomy_reference_text() -> str:
    """Human-readable numbered list injected into the system prompt."""
    lines = ["MASTER 50-NODE PROBLEM TAXONOMY:"]
    for code_num, name in PROBLEM_CODES.items():
        lines.append(f"{code_num}. {name}")
    return "\n".join(lines)
