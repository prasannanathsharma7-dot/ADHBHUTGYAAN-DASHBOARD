import { getAnalytics } from "@/lib/get-analytics";
import StatsStrip from "@/components/stats-strip";
import ProblemsPanel from "@/components/problems-panel";
import ComplaintsPanel from "@/components/complaints-panel";
import SignalsPanel from "@/components/signals-panel";
import CrisisQueue from "@/components/crisis-queue";
import LeadsTable, { type Lead } from "@/components/leads-table";

export const dynamic = "force-dynamic"; // always read current DB state, never cache

export default async function DashboardPage() {
  let data;
  let loadError: string | null = null;
  try {
    data = await getAnalytics();
  } catch (err) {
    loadError = err instanceof Error ? err.message : "Failed to load dashboard data";
  }

  if (loadError || !data) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="font-display text-2xl text-sindoor">Dashboard couldn&apos;t load</h1>
        <p className="mt-3 text-sm text-ink-muted">{loadError}</p>
      </main>
    );
  }

  const enrichedCount = data.enriched_count[0]?.count ?? 0;
  const leads: Lead[] = data.high_intent_leads.map((l) => ({
    id: String((l as { _id: unknown })._id),
    comment_text: l.comment_text,
    analysis: l.analysis as Lead["analysis"],
    channel_title: l.channel_title,
    author_name: l.author_name,
  }));

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8">
        <h1 className="font-display text-3xl text-ink">Adhbhutgyaan Intelligence</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Internal use only — reads the isolated astrology_intelligence database.
        </p>
      </header>

      <StatsStrip
        totalComments={data.total_comments}
        enriched={enrichedCount}
        highIntentCount={leads.length}
        crisisCount={data.crisis_queue.length}
      />

      {data.crisis_queue.length > 0 && (
        <div className="mt-8">
          <CrisisQueue data={data.crisis_queue} />
        </div>
      )}

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[1.5fr_1fr]">
        <ProblemsPanel data={data.top_problems} />
        <div className="space-y-6">
          <SignalsPanel intent={data.commercial_intent_breakdown} sentiment={data.sentiment_breakdown} />
          <ComplaintsPanel data={data.top_vendor_complaints} />
        </div>
      </div>

      <section className="mt-8">
        <h2 className="font-display text-xl text-ink">High-intent leads</h2>
        <p className="mt-1 text-sm text-ink-muted">
          Comments showing clear booking or price intent, newest and most urgent first.
        </p>
        <div className="mt-4">
          <LeadsTable initialLeads={leads} />
        </div>
      </section>
    </main>
  );
}
