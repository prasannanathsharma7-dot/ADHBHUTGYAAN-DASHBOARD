import LeadsTable from "@/components/leads-table";
import CrisisQueue from "@/components/crisis-queue";

export default function DashboardPage() {
  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-bold">Adhbhutgyaan Intelligence Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Internal use only — reads from the isolated astrology_intelligence database.
        </p>
      </header>

      <CrisisQueue />

      <section>
        <h2 className="mb-2 text-lg font-semibold">High-Intent Leads</h2>
        <LeadsTable />
      </section>
    </main>
  );
}
