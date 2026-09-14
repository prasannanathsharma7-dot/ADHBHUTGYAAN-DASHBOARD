import { NextRequest, NextResponse } from "next/server";
import { MongoClient } from "mongodb";

const ALLOWED_DB_NAME = "astrology_intelligence";
const FORBIDDEN_DB_NAMES = ["adhbhutgyaan_prod"];

// Vendor-complaint codes (category F, 44-50) — mirrors nlp/taxonomy.py.
// Keep these two lists in sync if the taxonomy ever changes.
const VENDOR_COMPLAINT_CODES = [
  "FAKE_ASTROLOGER_LOOT_COMPLAINT",
  "GEMSTONE_INEFFECTIVE_ADVERSE_REACTION",
  "TEMPLE_PUJA_NO_EFFECT_COMPLAINT",
  "PANDIT_NO_SHOW_FAKE_SANKALP",
  "CONTRADICTORY_PREDICTIONS_CONFUSION",
  "REMEDY_TOO_EXPENSIVE_INACCESSIBLE",
  "UNANSWERED_CONSULTATION_GHOSTED",
];

let clientPromise: Promise<MongoClient>;

function getClient(): Promise<MongoClient> {
  if (!clientPromise) {
    const uri = process.env.MONGODB_URI;
    if (!uri) {
      throw new Error(
        "MONGODB_URI is not set. Copy dashboard/.env.local.example to " +
          "dashboard/.env.local and set it before running the dashboard."
      );
    }
    const dbNameOverride = process.env.MONGO_DB_NAME || ALLOWED_DB_NAME;
    if (FORBIDDEN_DB_NAMES.includes(dbNameOverride)) {
      throw new Error(
        `Refusing to connect to '${dbNameOverride}' — this dashboard is ` +
          `strictly isolated to '${ALLOWED_DB_NAME}' and must never touch ` +
          `the production website database.`
      );
    }
    if (dbNameOverride !== ALLOWED_DB_NAME) {
      throw new Error(
        `MONGO_DB_NAME is set to '${dbNameOverride}', but this dashboard ` +
          `is hardcoded to only read '${ALLOWED_DB_NAME}'.`
      );
    }
    const client = new MongoClient(uri, { maxPoolSize: 10 });
    clientPromise = client.connect();
  }
  return clientPromise;
}

export async function GET(req: NextRequest) {
  try {
    const client = await getClient();
    const db = client.db(ALLOWED_DB_NAME);
    const collection = db.collection("comments");

    const searchParams = req.nextUrl.searchParams;
    const channelId = searchParams.get("channel_id");

    const matchStage: Record<string, unknown> = { analysis: { $ne: null } };
    if (channelId) matchStage.channel_id = channelId;

    const [result] = await collection
      .aggregate([
        { $match: matchStage },
        {
          $facet: {
            // Top 50 Problems — full 1-50 taxonomy, ranked by volume.
            top_problems: [
              { $group: { _id: "$analysis.primary_problem_code", count: { $sum: 1 } } },
              { $sort: { count: -1 } },
              { $limit: 50 },
            ],

            // Top 50 Complaints — specifically vendor/service grievances
            // (category F, codes 44-50), the "what's broken about how we
            // deliver service" view rather than user life problems.
            top_vendor_complaints: [
              { $match: { "analysis.primary_problem_code": { $in: VENDOR_COMPLAINT_CODES } } },
              { $group: { _id: "$analysis.primary_problem_code", count: { $sum: 1 } } },
              { $sort: { count: -1 } },
              { $limit: 50 },
            ],

            top_doshs: [
              { $match: { "analysis.primary_dosh": { $ne: "None" } } },
              { $group: { _id: "$analysis.primary_dosh", count: { $sum: 1 } } },
              { $sort: { count: -1 } },
            ],

            commercial_intent_breakdown: [
              { $group: { _id: "$analysis.commercial_intent", count: { $sum: 1 } } },
            ],

            sentiment_breakdown: [
              { $group: { _id: "$analysis.sentiment", count: { $sum: 1 } } },
            ],

            // Sales-facing leads — crisis-flagged comments are explicitly
            // excluded here. They are never a sales lead. See
            // crisis_queue below for where they actually go.
            high_intent_leads: [
              {
                $match: {
                  "analysis.commercial_intent": "HIGH",
                  "analysis.lead_status": "NEW",
                  "analysis.is_crisis_flag": { $ne: true },
                },
              },
              { $sort: { "analysis.urgency_score": -1, scraped_at: -1 } },
              { $limit: 100 },
              {
                $project: {
                  comment_text: 1,
                  "analysis.primary_problem_code": 1,
                  "analysis.primary_dosh": 1,
                  "analysis.urgency_score": 1,
                  "analysis.recommended_service": 1,
                  "analysis.lead_status": 1,
                  channel_title: 1,
                  author_name: 1,
                },
              },
            ],

            // Crisis queue — for human/safety-team review only. This is
            // NOT a sales queue. Keep it visually and functionally
            // separate in the UI from high_intent_leads.
            crisis_queue: [
              { $match: { "analysis.is_crisis_flag": true } },
              { $sort: { "analysis.urgency_score": -1, scraped_at: -1 } },
              { $limit: 50 },
              {
                $project: {
                  comment_text: 1,
                  "analysis.exact_user_complaint": 1,
                  "analysis.urgency_score": 1,
                  video_id: 1,
                  author_name: 1,
                  scraped_at: 1,
                },
              },
            ],
          },
        },
      ])
      .toArray();

    return NextResponse.json(result);
  } catch (err) {
    console.error("Analytics query failed:", err);
    const message = err instanceof Error ? err.message : "Failed to fetch analytics";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
