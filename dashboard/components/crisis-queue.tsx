"use client";

// Human-review queue for is_crisis_flag=true comments. Deliberately styled
// as an alert strip, not a data card — this is a safety workflow, not a
// sales metric, and must never visually blend in with the leads table.
// Keep it functionally separate from leads-table.tsx.

type CrisisEntry = {
  comment_text: string;
  analysis: { exact_user_complaint: string; urgency_score: number };
  video_id: string;
  author_name: string;
};

export default function CrisisQueue({ data }: { data: CrisisEntry[] }) {
  if (data.length === 0) return null;

  return (
    <div className="border-l-4 border-sindoor bg-sindoor/[0.08] p-6">
      <h2 className="font-display text-xl text-sindoor">
        {data.length} comment{data.length !== 1 ? "s" : ""} flagged for human review
      </h2>
      <p className="mt-1 max-w-2xl text-sm text-ink-muted">
        These express explicit distress. This is a safety queue, not a sales
        list — route to a trained person for a direct, human response. Do
        not follow up with a service offer.
      </p>
      <ul className="mt-4 space-y-2">
        {data.map((entry, i) => (
          <li key={i} className="border border-sindoor/25 bg-void/40 p-3 text-sm">
            <p className="text-ink">{entry.analysis.exact_user_complaint}</p>
            <p className="mt-1 text-xs text-ink-muted">
              Video {entry.video_id} · urgency {entry.analysis.urgency_score}/10
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
