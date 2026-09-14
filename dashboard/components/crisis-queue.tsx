"use client";

import { useEffect, useState } from "react";

// Human-review queue for is_crisis_flag=true comments. This is
// intentionally a separate, visually distinct component from
// leads-table.tsx — crisis-flagged comments must never be presented
// as sales leads. If you're wiring this into a page, keep it in its
// own section, not merged into the leads table.

type CrisisEntry = {
  comment_text: string;
  analysis: { exact_user_complaint: string; urgency_score: number };
  video_id: string;
  author_name: string;
  scraped_at: string;
};

export default function CrisisQueue() {
  const [data, setData] = useState<CrisisEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/analytics")
      .then((res) => res.json())
      .then((json) => {
        setData(json.crisis_queue ?? []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return null;
  if (data.length === 0) return null;

  return (
    <div className="rounded-md border border-red-300 bg-red-50 p-4">
      <h2 className="mb-2 font-semibold text-red-800">
        Crisis Review Queue — {data.length} flagged
      </h2>
      <p className="mb-3 text-xs text-red-700">
        These comments were flagged for explicit suicidal ideation.
        This is a human-review safety queue, not a sales list — route
        to a trained person, not a booking follow-up.
      </p>
      <ul className="space-y-2">
        {data.map((entry, i) => (
          <li key={i} className="rounded border border-red-200 bg-white p-2 text-sm">
            <p className="text-muted-foreground">{entry.analysis.exact_user_complaint}</p>
            <p className="mt-1 text-xs text-gray-500">
              Video: {entry.video_id} · Urgency: {entry.analysis.urgency_score}/10
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
