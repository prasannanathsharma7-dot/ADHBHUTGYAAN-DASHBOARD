type Stats = {
  totalComments: number;
  enriched: number;
  highIntentCount: number;
  crisisCount: number;
};

function Cell({ value, label, accent }: { value: string; label: string; accent?: boolean }) {
  return (
    <div className="relative flex-1 px-6 py-5 first:pl-0 last:pr-0">
      <div
        className={`font-display text-3xl leading-none ${accent ? "text-marigold" : "text-ink"}`}
      >
        {value}
      </div>
      <div className="mt-1.5 text-sm text-ink-muted">{label}</div>
      <span
        aria-hidden
        className="absolute right-0 top-1/2 hidden h-10 w-px -translate-y-1/2 bg-gradient-to-b from-transparent via-line to-transparent last:hidden sm:block"
        style={{ transform: "translateY(-50%) skewX(-12deg)" }}
      />
    </div>
  );
}

export default function StatsStrip({ totalComments, enriched, highIntentCount, crisisCount }: Stats) {
  const pct = totalComments > 0 ? Math.round((enriched / totalComments) * 100) : 0;
  return (
    <div className="flex flex-wrap divide-x divide-line border-b border-line pb-5 sm:flex-nowrap sm:divide-x-0">
      <Cell value={totalComments.toLocaleString("en-IN")} label="Comments scraped" />
      <Cell value={`${enriched.toLocaleString("en-IN")} (${pct}%)`} label="Classified by Claude" />
      <Cell value={String(highIntentCount)} label="Open high-intent leads" accent />
      {crisisCount > 0 && (
        <Cell value={String(crisisCount)} label="Flagged for human review" />
      )}
    </div>
  );
}
