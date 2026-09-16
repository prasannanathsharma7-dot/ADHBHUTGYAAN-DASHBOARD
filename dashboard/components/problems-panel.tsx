"use client";

import { BarChart, Bar, XAxis, YAxis, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { formatProblemCode } from "@/lib/taxonomy";

type ProblemRow = { _id: string; count: number };

export default function ProblemsPanel({ data }: { data: ProblemRow[] }) {
  const top = data.slice(0, 12).map((d) => ({ name: formatProblemCode(d._id), count: d.count }));
  const maxCount = top[0]?.count ?? 1;

  return (
    <div className="border border-line p-6">
      <div className="flex items-baseline justify-between">
        <h2 className="font-display text-xl text-ink">Top problems</h2>
        <span className="text-sm text-ink-muted">
          {data.length} of 50 tracked categories appear in this data
        </span>
      </div>
      {top.length === 0 ? (
        <p className="mt-6 text-sm text-ink-muted">
          No classified comments yet. Run the enrichment pipeline to populate this.
        </p>
      ) : (
        <div style={{ width: "100%", height: Math.max(top.length * 34, 200) }} className="mt-4">
          <ResponsiveContainer>
            <BarChart data={top} layout="vertical" margin={{ left: 0, right: 24, top: 0, bottom: 0 }}>
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="name"
                width={210}
                tick={{ fill: "#8B8FA8", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: "rgba(242,169,59,0.06)" }}
                contentStyle={{
                  background: "#1B1E3D",
                  border: "1px solid rgba(237,234,224,0.12)",
                  borderRadius: 2,
                  color: "#EDEAE0",
                  fontSize: 13,
                }}
                labelStyle={{ color: "#EDEAE0" }}
              />
              <Bar dataKey="count" radius={[0, 2, 2, 0]} barSize={16}>
                {top.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={
                      entry.count === maxCount
                        ? "#F2A93B"
                        : `rgba(242,169,59,${0.35 + 0.4 * (entry.count / maxCount)})`
                    }
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
