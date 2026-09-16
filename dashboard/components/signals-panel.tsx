"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";

type Row = { _id: string; count: number };

const INTENT_COLORS: Record<string, string> = {
  HIGH: "#F2A93B",
  MEDIUM: "#B87F28",
  LOW: "#4A4E7A",
  NONE: "#2A2E52",
};

const SENTIMENT_ORDER = [
  "Distressed",
  "Seeking Remedy",
  "Angry Grievance",
  "Skeptic",
  "Curious",
  "Devotional",
];

export default function SignalsPanel({
  intent,
  sentiment,
}: {
  intent: Row[];
  sentiment: Row[];
}) {
  const intentData = intent.filter((r) => r._id);
  const total = intentData.reduce((s, r) => s + r.count, 0);
  const sentimentMap = new Map(sentiment.map((r) => [r._id, r.count]));
  const sentimentMax = Math.max(1, ...sentiment.map((r) => r.count));

  return (
    <div className="border border-line p-6">
      <h2 className="font-display text-xl text-ink">Commercial intent</h2>
      {total === 0 ? (
        <p className="mt-6 text-sm text-ink-muted">None classified yet.</p>
      ) : (
        <>
          <div className="mt-2 flex items-center gap-6">
            <div style={{ width: 120, height: 120 }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={intentData}
                    dataKey="count"
                    nameKey="_id"
                    innerRadius={38}
                    outerRadius={58}
                    startAngle={90}
                    endAngle={-270}
                    strokeWidth={0}
                  >
                    {intentData.map((entry, i) => (
                      <Cell key={i} fill={INTENT_COLORS[entry._id] ?? "#4A4E7A"} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      background: "#1B1E3D",
                      border: "1px solid rgba(237,234,224,0.12)",
                      borderRadius: 2,
                      color: "#EDEAE0",
                      fontSize: 13,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <ul className="space-y-1.5 text-sm">
              {intentData
                .sort((a, b) => b.count - a.count)
                .map((row) => (
                  <li key={row._id} className="flex items-center gap-2">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ background: INTENT_COLORS[row._id] ?? "#4A4E7A" }}
                    />
                    <span className="text-ink-muted">{row._id}</span>
                    <span className="ml-auto font-display text-ink">
                      {Math.round((row.count / total) * 100)}%
                    </span>
                  </li>
                ))}
            </ul>
          </div>

          <h3 className="mt-6 text-sm text-ink-muted">Sentiment</h3>
          <ul className="mt-2 space-y-2">
            {SENTIMENT_ORDER.map((label) => {
              const count = sentimentMap.get(label) ?? 0;
              return (
                <li key={label}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="text-ink-muted">{label}</span>
                    <span className="text-ink-muted">{count}</span>
                  </div>
                  <div className="mt-0.5 h-1 w-full bg-line">
                    <div
                      className="h-1 bg-marigold-dim"
                      style={{ width: `${(count / sentimentMax) * 100}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
