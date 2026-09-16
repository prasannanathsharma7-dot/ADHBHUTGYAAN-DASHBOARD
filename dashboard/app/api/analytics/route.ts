import { NextRequest, NextResponse } from "next/server";
import { getAnalytics } from "@/lib/get-analytics";

export async function GET(req: NextRequest) {
  try {
    const channelId = req.nextUrl.searchParams.get("channel_id");
    const data = await getAnalytics(channelId);
    return NextResponse.json(data);
  } catch (err) {
    console.error("Analytics query failed:", err);
    const message = err instanceof Error ? err.message : "Failed to fetch analytics";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
