import { MongoClient } from "mongodb";

const ALLOWED_DB_NAME = "astrology_intelligence";
// Real production database name, confirmed via Atlas: "astrokashi".
const FORBIDDEN_DB_NAMES = ["astrokashi", "adhbhutgyaan_prod"];

export const VENDOR_COMPLAINT_CODES = [
  "FAKE_ASTROLOGER_LOOT_COMPLAINT",
  "GEMSTONE_INEFFECTIVE_ADVERSE_REACTION",
  "TEMPLE_PUJA_NO_EFFECT_COMPLAINT",
  "PANDIT_NO_SHOW_FAKE_SANKALP",
  "CONTRADICTORY_PREDICTIONS_CONFUSION",
  "REMEDY_TOO_EXPENSIVE_INACCESSIBLE",
  "UNANSWERED_CONSULTATION_GHOSTED",
];

let clientPromise: Promise<MongoClient> | undefined;

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

export type AnalyticsResult = {
  total_comments: number;
  enriched_count: { count: number }[];
  top_problems: { _id: string; count: number }[];
  top_vendor_complaints: { _id: string; count: number }[];
  top_doshs: { _id: string; count: number }[];
  commercial_intent_breakdown: { _id: string; count: number }[];
  sentiment_breakdown: { _id: string; count: number }[];
  high_intent_leads: Array<{
    _id: string;
    comment_text: string;
    analysis: {
      primary_problem_code: string;
      primary_dosh: string;
      urgency_score: number;
      recommended_service: string;
      lead_status: string;
    };
    channel_title: string;
    author_name: string;
  }>;
  crisis_queue: Array<{
    comment_text: string;
    analysis: { exact_user_complaint: string; urgency_score: number };
    video_id: string;
    author_name: string;
  }>;
};

export async function getAnalytics(channelId?: string | null): Promise<AnalyticsResult> {
  const client = await getClient();
  const db = client.db(ALLOWED_DB_NAME);
  const collection = db.collection("comments");

  const totalComments = await collection.countDocuments(
    channelId ? { channel_id: channelId } : {}
  );

  const matchStage: Record<string, unknown> = { analysis: { $ne: null } };
  if (channelId) matchStage.channel_id = channelId;

  const [result] = await collection
    .aggregate([
      { $match: matchStage },
      {
        $facet: {
          enriched_count: [{ $count: "count" }],
          top_problems: [
            { $group: { _id: "$analysis.primary_problem_code", count: { $sum: 1 } } },
            { $sort: { count: -1 } },
            { $limit: 50 },
          ],
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

  return { ...(result as Omit<AnalyticsResult, "total_comments">), total_comments: totalComments };
}
