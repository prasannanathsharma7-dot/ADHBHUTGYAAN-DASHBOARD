import { formatProblemCode } from "@/lib/taxonomy";

type ComplaintRow = { _id: string; count: number };

export default function ComplaintsPanel({ data }: { data: ComplaintRow[] }) {
  const maxCount = data[0]?.count ?? 1;

  return (
    <div className="border border-sindoor/30 bg-sindoor/[0.04] p-6">
      <h2 className="font-display text-xl text-ink">Vendor complaints</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Grievances against astrologers, pujas, and gemstones — including this business.
      </p>
      {data.length === 0 ? (
        <p className="mt-6 text-sm text-ink-muted">None classified yet.</p>
      ) : (
        <ol className="mt-5 space-y-3">
          {data.slice(0, 7).map((row, i) => (
            <li key={row._id}>
              <div className="flex items-baseline justify-between text-sm">
                <span className="text-ink">{formatProblemCode(row._id)}</span>
                <span className="font-display text-ink-muted">{row.count}</span>
              </div>
              <div className="mt-1 h-1 w-full bg-line">
                <div
                  className="h-1 bg-sindoor"
                  style={{ width: `${Math.max((row.count / maxCount) * 100, 4)}%` }}
                />
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
