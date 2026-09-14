// Mirrors nlp/taxonomy.py — keep both in sync if the taxonomy changes.

export const VENDOR_COMPLAINT_CODES = [
  "FAKE_ASTROLOGER_LOOT_COMPLAINT",
  "GEMSTONE_INEFFECTIVE_ADVERSE_REACTION",
  "TEMPLE_PUJA_NO_EFFECT_COMPLAINT",
  "PANDIT_NO_SHOW_FAKE_SANKALP",
  "CONTRADICTORY_PREDICTIONS_CONFUSION",
  "REMEDY_TOO_EXPENSIVE_INACCESSIBLE",
  "UNANSWERED_CONSULTATION_GHOSTED",
] as const;

export const CRISIS_CODES = ["SUICIDAL_DESPERATION_END_STAGE"] as const;

export const LEAD_STATUS_OPTIONS = [
  "NEW",
  "REVIEWED",
  "CONTACTED",
  "CONVERTED",
  "ARCHIVED",
] as const;

export type LeadStatus = (typeof LEAD_STATUS_OPTIONS)[number];

/** Turns SARKARI_EXAM_REPEATED_FAILURE into "Sarkari Exam Repeated Failure" for display. */
export function formatProblemCode(code: string | null | undefined): string {
  if (!code) return "—";
  return code
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
