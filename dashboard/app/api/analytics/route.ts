import { NextRequest, NextResponse } from "next/server";
import { MongoClient } from "mongodb";

// Reuse the client across invocations (important on serverless — avoid
// opening a new connection per request, which exhausts Atlas connections
// under load).
let clientPromise: Promise<MongoClient>;

function getClient(): Promise<MongoClient> {
  if (!clientPromise) {
    const client = new MongoClient(process.env.MONGODB_URI as string, {
      maxPoolSize: 10,
    });
    clientPromise = client.connect();
  }
  return clientPromise;
}

export async function GET(req: NextRequest) {
  try {
    const client = await getClient();
    const db = client.db("adhbhutgyaan_intel");
    const collection = db.collection("raw_comments");

    const searchParams = req.nextUrl.searchParams;
    const channel = searchParams.get("channel"); // optional filter

    const matchStage: Record<string, unknown> = { enriched: true };
    if (channel) matchStage.channel_name = channel;

    const [result] = await collection
      .aggregate([
        { $match: matchStage },
        {
          $facet: {
            top_topics: [
              { $group: { _id: "$topic", count: { $sum: 1 } } },
              { $sort: { count: -1 } },
              { $limit: 50 },
            ],
            top_doshs: [
              { $match: { detected_dosh: { $ne: null } } },
              { $group: { _id: "$detected_dosh", count: { $sum: 1 } } },
              { $sort: { count: -1 } },
              { $limit: 50 },
            ],
            commercial_intent_breakdown: [
              { $group: { _id: "$commercial_intent", count: { $sum: 1 } } },
            ],
            urgency_distribution: [
              { $group: { _id: "$urgency_score", count: { $sum: 1 } } },
              { $sort: { _id: 1 } },
            ],
            high_intent_leads: [
              { $match: { commercial_intent: "high" } },
              { $sort: { urgency_score: -1, scraped_at: -1 } },
              { $limit: 100 },
              {
                $project: {
                  text: 1,
                  topic: 1,
                  detected_dosh: 1,
                  urgency_score: 1,
                  channel_name: 1,
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
    return NextResponse.json(
      { error: "Failed to fetch analytics" },
      { status: 500 }
    );
  }
}
