import { NextRequest, NextResponse } from "next/server";
import { MongoClient, ObjectId } from "mongodb";

const ALLOWED_DB_NAME = "astrology_intelligence";
const FORBIDDEN_DB_NAMES = ["astrokashi", "adhbhutgyaan_prod"];
const VALID_STATUSES = ["NEW", "REVIEWED", "CONTACTED", "CONVERTED", "ARCHIVED"];

let clientPromise: Promise<MongoClient> | undefined;

function getClient(): Promise<MongoClient> {
  if (!clientPromise) {
    const uri = process.env.MONGODB_URI;
    if (!uri) throw new Error("MONGODB_URI is not set.");
    const dbNameOverride = process.env.MONGO_DB_NAME || ALLOWED_DB_NAME;
    if (FORBIDDEN_DB_NAMES.includes(dbNameOverride) || dbNameOverride !== ALLOWED_DB_NAME) {
      throw new Error(`Refusing to write to '${dbNameOverride}' — only '${ALLOWED_DB_NAME}' is allowed.`);
    }
    clientPromise = new MongoClient(uri, { maxPoolSize: 10 }).connect();
  }
  return clientPromise;
}

export async function POST(req: NextRequest) {
  try {
    const { id, status } = await req.json();

    if (!id || !ObjectId.isValid(id)) {
      return NextResponse.json({ error: "Invalid or missing id" }, { status: 400 });
    }
    if (!VALID_STATUSES.includes(status)) {
      return NextResponse.json({ error: `status must be one of ${VALID_STATUSES.join(", ")}` }, { status: 400 });
    }

    const client = await getClient();
    const db = client.db(ALLOWED_DB_NAME);
    const result = await db.collection("comments").updateOne(
      { _id: new ObjectId(id) },
      { $set: { "analysis.lead_status": status } }
    );

    if (result.matchedCount === 0) {
      return NextResponse.json({ error: "No comment found with that id" }, { status: 404 });
    }

    return NextResponse.json({ ok: true, id, status });
  } catch (err) {
    console.error("Lead status update failed:", err);
    const message = err instanceof Error ? err.message : "Update failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
